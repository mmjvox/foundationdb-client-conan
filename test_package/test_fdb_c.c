#define FDB_API_VERSION 730
#include <foundationdb/fdb_c.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    int max_api = fdb_get_max_api_version();
    printf("fdb max api version: %d\n", max_api);
    if (max_api < FDB_API_VERSION) {
        fprintf(stderr, "max api version too low\n");
        return 1;
    }

    /* Pulls in much of flow/fdbclient, so unresolved symbols in a static
       archive would fail at link time. */
    fdb_error_t err = fdb_select_api_version(FDB_API_VERSION);
    if (err) {
        fprintf(stderr, "select_api_version: %s\n", fdb_get_error(err));
        return 1;
    }
    if (strcmp(fdb_get_error(0), "Success") != 0) {
        fprintf(stderr, "unexpected error string\n");
        return 1;
    }
    err = fdb_setup_network();
    if (err) {
        fprintf(stderr, "setup_network: %s\n", fdb_get_error(err));
        return 1;
    }
    printf("ok\n");
    return 0;
}
