import os
import stat
from conan import ConanFile
from conan.tools.cmake import CMake, CMakeToolchain, CMakeDeps, cmake_layout
from conan.tools.files import (
    get, copy, save, replace_in_file,
    export_conandata_patches, apply_conandata_patches,
)
from conan.tools.env import Environment
from conan.tools.scm import Version
from conan.errors import ConanInvalidConfiguration, ConanException

class FoundationDBClientConan(ConanFile):
    name = "foundationdb-client"
    description = "FoundationDB C/C++ Client built from source (Zero System Dependencies)"
    license = "Apache-2.0"
    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    options = {"shared": [True, False]}
    default_options = {"shared": False}

    def set_version(self):
        self.version = self.version or "7.4.8"

    def export_sources(self):
        export_conandata_patches(self)

    def validate(self):
        if self.settings.os != "Linux":
            raise ConanInvalidConfiguration("Linux only.")

    def build_requirements(self):
        self.tool_requires("cmake/[>=3.24]")
        self.tool_requires("ninja/1.12.1")

    def requirements(self):
        self.requires("boost/1.83.0")
        self.requires("openssl/3.2.1")
        self.requires("toml11/3.8.1")
        self.requires("msgpack-cxx/6.1.0")
        if Version(self.version) >= "7.4.0":
            self.requires("fmt/11.1.4")

    def layout(self):
        cmake_layout(self, src_folder="src")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)
        apply_conandata_patches(self)

    def generate(self):
        # 1. Use persistent .NET cache in ~/.conan2/dotnet_cache
        persistent_cache = os.path.expanduser("~/.conan2/dotnet_cache/8.0.404")
        dotnet_bin = os.path.join(persistent_cache, "dotnet")

        if not os.path.exists(dotnet_bin):
            self.output.info(f"Downloading portable .NET SDK once to {persistent_cache}...")
            os.makedirs(persistent_cache, exist_ok=True)
            dotnet_url = "https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.404/dotnet-sdk-8.0.404-linux-x64.tar.gz"
            get(self, dotnet_url, destination=persistent_cache)
        else:
            self.output.info(f"Using cached portable .NET SDK from {persistent_cache}")

        # 2. Create portable shims for mono and mcs
        shim_dir = os.path.join(self.build_folder, "mono_shims")
        os.makedirs(shim_dir, exist_ok=True)

        mcs_script = """#!/usr/bin/env python3
import sys, os, subprocess, shutil

DOTNET_BIN = "__DOTNET_BIN__"
args = sys.argv[1:]
out_file = None
sources = []

for a in args:
    if a.startswith("-out:"):
        out_file = a.split(":", 1)[1]
    elif not a.startswith("-"):
        sources.append(os.path.abspath(a))

if not out_file:
    sys.exit(0)

out_abs = os.path.abspath(out_file)
proj_dir = os.path.join(os.path.dirname(out_abs), "_dotnet_proj_" + os.path.basename(out_abs))
os.makedirs(proj_dir, exist_ok=True)

compile_items = "\\n".join(['    <Compile Include="' + s + '" />' for s in sources])

csproj = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>disable</Nullable>
    <GenerateAssemblyInfo>false</GenerateAssemblyInfo>
  </PropertyGroup>
  <ItemGroup>
''' + compile_items + '''
  </ItemGroup>
</Project>'''

csproj_path = os.path.join(proj_dir, "build.csproj")
with open(csproj_path, "w") as f:
    f.write(csproj)

out_dir = os.path.join(proj_dir, "out")
subprocess.check_call([DOTNET_BIN, "build", csproj_path, "-c", "Release", "-o", out_dir, "--nologo", "-v", "q"])
shutil.copyfile(os.path.join(out_dir, "build.dll"), out_abs)
shutil.copyfile(os.path.join(out_dir, "build.runtimeconfig.json"), out_abs + ".runtimeconfig.json")
shutil.copyfile(os.path.join(out_dir, "build.runtimeconfig.json"), os.path.splitext(out_abs)[0] + ".runtimeconfig.json")
""".replace("__DOTNET_BIN__", dotnet_bin)

        mcs_path = os.path.join(shim_dir, "mcs")
        save(self, mcs_path, mcs_script)
        os.chmod(mcs_path, os.stat(mcs_path).st_mode | stat.S_IEXEC)

        mono_script = f"""#!/bin/sh
exec "{dotnet_bin}" "$@"
"""
        mono_path = os.path.join(shim_dir, "mono")
        save(self, mono_path, mono_script)
        os.chmod(mono_path, os.stat(mono_path).st_mode | stat.S_IEXEC)

        env = Environment()
        env.prepend_path("PATH", shim_dir)
        env.prepend_path("PATH", persistent_cache)
        env.define("DOTNET_ROOT", persistent_cache)
        env.define("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
        env.vars(self).save_script("conanbuild_dotnet")

        # 3. CMake configuration
        deps = CMakeDeps(self)
        deps.generate()

        tc = CMakeToolchain(self, generator="Ninja")
        tc.variables["CSHARP_COMPILER_EXECUTABLE"] = mcs_path
        tc.variables["MONO_EXECUTABLE"] = mono_path
        tc.variables["OPEN_FOR_IDE"] = False
        tc.variables["GENERATE_PACKAGE"] = False
        tc.variables["BUILD_DOCUMENTATION"] = False
        tc.variables["BUILD_PYTHON_BINDINGS"] = False
        tc.variables["BUILD_JAVA_BINDINGS"] = False
        tc.variables["BUILD_GO_BINDINGS"] = False
        tc.variables["BUILD_RUBY_BINDINGS"] = False
        tc.variables["BUILD_AWS_BACKUP"] = False
        tc.variables["WITH_ROCKSDB"] = False
        tc.variables["WITH_ROCKSDB_EXPERIMENTAL"] = False
        tc.variables["WITH_CONAN"] = True
        tc.variables["USE_JEMALLOC"] = False
        if Version(self.version) < "7.4.0":
            tc.variables["CMAKE_DISABLE_FIND_PACKAGE_fmt"] = True  # force bundled fmt 8.1.1 (contrib), not system fmt
        tc.variables["USE_WERROR"] = False
        tc.variables["RUN_JUNIT_TESTS"] = False

        # Compatibility of FDB source with GCC 16
        tc.blocks["cmake_flags_init"].values["CMAKE_CXX_FLAGS"] = "-include cstdint"
        tc.generate()

    def build(self):
        if not self.options.shared:
            # Upstream only defines fdb_c as SHARED; build it as an archive instead.
            bindings_c = os.path.join(self.source_folder, "bindings", "c", "CMakeLists.txt")
            replace_in_file(self, bindings_c, "add_library(fdb_c SHARED", "add_library(fdb_c STATIC")
            replace_in_file(self, bindings_c, "strip_debug_symbols(fdb_c)", "")
        cmake = CMake(self)
        cmake.configure()
        cmake.build(target="fdb_c")

    def package(self):
        copy(self, "LICENSE", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
        copy(self, "*.h", src=os.path.join(self.source_folder, "bindings", "c", "foundationdb"),
             dst=os.path.join(self.package_folder, "include", "foundationdb"))
        copy(self, "*.h", src=os.path.join(self.build_folder, "bindings", "c", "foundationdb"),
             dst=os.path.join(self.package_folder, "include", "foundationdb"))
        if self.options.shared:
            copy(self, "libfdb_c.so*", src=os.path.join(self.build_folder, "lib"),
                 dst=os.path.join(self.package_folder, "lib"))
        else:
            self._merge_static_archives()

    def _merge_static_archives(self):
        # fdb_c's real code lives in fdbclient/fdbrpc/flow and contrib libs; merge them
        # into a single libfdb_c.a so consumers need no link-order knowledge.
        wanted = {"libfdb_c.a", "libfdbclient.a", "libfdbrpc.a", "libflow.a", "libeio.a",
                  "libcoro.a", "libcrc32.a", "libmd5.a", "libstacktrace.a",
                  "libfolly_memcpy.a", "liblibb64.a", "libfmt.a", "libfmtd.a"}
        found = {}
        for root, _, files in os.walk(self.build_folder):
            for f in files:
                if f in wanted:
                    found[f] = os.path.join(root, f)
        if "libfdb_c.a" not in found:
            raise ConanException("libfdb_c.a was not produced by the static build")
        self.output.info("Merging static archives: " + ", ".join(sorted(found)))
        libdir = os.path.join(self.package_folder, "lib")
        os.makedirs(libdir, exist_ok=True)
        out = os.path.join(libdir, "libfdb_c.a")
        mri = "create {}\n".format(out)
        mri += "".join("addlib {}\n".format(p) for _, p in sorted(found.items()))
        mri += "save\nend\n"
        self.run(f"printf '%s' '{mri}' | ar -M")
        self.run(f"ranlib {out}")

    def package_info(self):
        self.cpp_info.libs = ["fdb_c"]
        self.cpp_info.set_property("cmake_file_name", "FoundationDBClient")
        self.cpp_info.set_property("cmake_target_name", "FoundationDB::fdb_c")
        self.cpp_info.system_libs = ["pthread", "dl", "m", "rt"]
        if not self.options.shared:
            self.cpp_info.system_libs.append("stdc++")
