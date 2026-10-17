// LD_PRELOAD module for test-completion-report.py (Linux only)
// acts on the N-th decode call of llama_process() (CR_SHIM_AT, 1-based):
//   CR_SHIM_ACTION=fail          return CR_SHIM_RC (default 1) without decoding
//   CR_SHIM_ACTION=sigint        raise SIGINT, then decode
//   CR_SHIM_ACTION=sigterm       raise SIGTERM, then decode
//   CR_SHIM_ACTION=sigint_fail   raise SIGINT, then fail
//   CR_SHIM_ACTION=touch:PATH    create PATH (exclusive), then decode
#define _GNU_SOURCE
#include "llama.h"

#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
