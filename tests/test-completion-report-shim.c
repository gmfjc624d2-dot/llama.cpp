// LD_PRELOAD module for test-completion-report.py (Linux only)
// acts on the N-th decode call of llama_process() (CR_SHIM_AT, 1-based):
//   CR_SHIM_ACTION=fail          return CR_SHIM_RC (default 1) without decoding
//   CR_SHIM_ACTION=sigint        raise SIGINT, then decode
//   CR_SHIM_ACTION=sigterm       raise SIGTERM, then decode
//   CR_SHIM_ACTION=sigint_fail   raise SIGINT, then fail
//   CR_SHIM_ACTION=touch:PATH    create PATH (exclusive), then decode
// acts on the fdopen() of the report file (CR_SHIM_FDOPEN), like another process would:
//   CR_SHIM_FDOPEN=swap:PATH       rename PATH to PATH.moved, create an unrelated file at PATH, then fdopen
//   CR_SHIM_FDOPEN=swap_fail:PATH  same, then fail with EMFILE
#define _GNU_SOURCE
#include "llama.h"

#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

typedef int32_t (*llama_process_fn)(struct llama_context *, enum llama_process_type, struct llama_batch_ext *);

static int n_decode = 0;

int32_t llama_process(struct llama_context * ctx, enum llama_process_type type, struct llama_batch_ext * batch) {
    static llama_process_fn real = NULL;
    if (real == NULL) {
        *(void **) &real = dlsym(RTLD_NEXT, "llama_process");
        if (real == NULL) {
            fprintf(stderr, "test-completion-report-shim: llama_process not found\n");
            abort();
        }
    }

    if (type != LLAMA_PROCESS_TYPE_DECODE) {
        return real(ctx, type, batch);
    }

    const char * at     = getenv("CR_SHIM_AT");
    const char * action = getenv("CR_SHIM_ACTION");

    n_decode++;
    if (at == NULL || action == NULL || n_decode != atoi(at)) {
        return real(ctx, type, batch);
    }

    fprintf(stderr, "test-completion-report-shim: decode call %d: %s\n", n_decode, action);

    if (strcmp(action, "fail") == 0 || strcmp(action, "sigint_fail") == 0) {
        if (strcmp(action, "sigint_fail") == 0) {
            raise(SIGINT);
        }
        const char * rc = getenv("CR_SHIM_RC");
        return rc ? atoi(rc) : 1;
    }
    if (strcmp(action, "sigint") == 0) {
        raise(SIGINT);
    } else if (strcmp(action, "sigterm") == 0) {
        raise(SIGTERM);
    } else if (strncmp(action, "touch:", 6) == 0) {
        FILE * f = fopen(action + 6, "wx");
        if (f) {
            fputs("unrelated file\n", f);
            fclose(f);
        }
    }
    return real(ctx, type, batch);
}

FILE * fdopen(int fd, const char * mode) {
    static FILE * (*real)(int, const char *) = NULL;
    static int done = 0;
    if (real == NULL) {
        *(void **) &real = dlsym(RTLD_NEXT, "fdopen");
    }

    const char * spec = getenv("CR_SHIM_FDOPEN");
    const char * path = spec ? strchr(spec, ':') : NULL;
    if (done || path == NULL) {
        return real(fd, mode);
    }
    path++;

    // only the fd that was opened for PATH
    struct stat st_fd;
    struct stat st_path;
    if (fstat(fd, &st_fd) != 0 || stat(path, &st_path) != 0 || st_fd.st_dev != st_path.st_dev || st_fd.st_ino != st_path.st_ino) {
        return real(fd, mode);
    }
    done = 1;

    char moved[4096];
    snprintf(moved, sizeof(moved), "%s.moved", path);
    if (rename(path, moved) != 0) {
        fprintf(stderr, "test-completion-report-shim: rename failed\n");
        abort();
    }
    FILE * f = fopen(path, "wx");
    if (f == NULL) {
        fprintf(stderr, "test-completion-report-shim: cannot create unrelated file\n");
        abort();
    }
    fputs("unrelated file\n", f);
    fclose(f);
    fprintf(stderr, "test-completion-report-shim: fdopen: moved the report to %s and created an unrelated file at %s\n", moved, path);

    if (strncmp(spec, "swap_fail:", 10) == 0) {
        errno = EMFILE;
        return NULL;
    }
    return real(fd, mode);
}
