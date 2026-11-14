cmake_minimum_required(VERSION 3.15)
project(test_fdb_c LANGUAGES C)

find_package(FoundationDBClient REQUIRED CONFIG)

# Plain C consumer: also validates that a static libfdb_c.a links without
# the consumer knowing about FDB's internal C++ dependencies.
add_executable(test_fdb_c test_fdb_c.c)
target_link_libraries(test_fdb_c PRIVATE FoundationDB::fdb_c)
