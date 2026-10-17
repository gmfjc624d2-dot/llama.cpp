# Evidence: llama-completion --completion-report

Request: public-completion-report-20261016-01. Everything here is public: public source, the public vocab fixture `models/ggml-vocab-llama-spm.gguf` from the repository, and generated test models (not committed, only their SHA-256).

## Identities

| What | Value |
| ---- | ----- |
| upstream | https://github.com/ggml-org/llama.cpp |
| fork, branch | https://github.com/gmfjc624d2-dot/llama.cpp, `claude/pensive-fermi-tpr2cj` (new branch, created from the base) |
| base | tag `b11696` = `ceefd16daa2093730bf3340315fa2b84b286ddbc` (checked with `git ls-remote https://github.com/ggml-org/llama.cpp refs/tags/b11696`) |
| comparison only | tag `b9842` = `6f4f53f2b7da54fcdbbecaaa734337c337ad6176`, only used for the `llama_version()` header check |
| fork master | `6420cf5dd588c68e48657a0bbd82bb3bd5ac7209`, not modified; no tag, issue or PR was created or changed |
| source commits | `6df3172e2f39725cf6d3b54c63419a626b44e15e` feature, `95de7ea8a6bfa95567b7cd6d64f8f1ccf1b2cbcc` test driver fix, `420f01a4f0b6514d1880e9d347157ebed25d2edb` review fix (publication race, lock-free check) |
| tested source | `420f01a4f0b6514d1880e9d347157ebed25d2edb` (binaries report `version: 0.7.0-dev (build 4, commit 420f01a)`) |
| evidence commit | the commit that adds this directory, on top of `420f01a` |

`MANIFEST.json` lists every changed file with SHA-256 and git blob at `420f01a`, and the SHA-256 of the patches. `patches/` has the three commits as `git format-patch` files and the full diff `ceefd16..420f01a.diff`.

## Recovery

```sh
git clone https://github.com/gmfjc624d2-dot/llama.cpp && cd llama.cpp
git checkout claude/pensive-fermi-tpr2cj
git diff ceefd16daa2093730bf3340315fa2b84b286ddbc 420f01a4f0b6514d1880e9d347157ebed25d2edb   # the change
# or apply patches/*.patch on top of b11696 with git am
```

## Build

Linux x86_64, Ubuntu 24.04.5, GCC 13.3.0, CMake 3.28.3, Ninja 1.11.1, CPU backend only, `GGML_NATIVE=ON`, shared libs (`logs/420f01a/environment.txt`). Only the needed targets were built.

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=ON -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF
cmake --build build --target llama-completion test-arg-parser test-completion-report-shim -j 4
```

The unmodified base binary for the legacy comparison was built the same way from a `git worktree` at `ceefd16` (target `llama-completion`, later `test-arg-parser`), logs in `logs/base-ceefd16/`.

## Tests

```sh
# registered test (label python), no base binary
ctest --test-dir build -R test-completion-report --output-on-failure
# full run, with the base binary for the legacy comparison
python3 -I tests/test-completion-report.py --bin-dir build/bin --vocab models/ggml-vocab-llama-spm.gguf --gguf-py gguf-py \
    --work-dir WORK --shim build/bin/libtest-completion-report-shim.so --base-bin BASE_BUILD/bin/llama-completion
# real model, not run here
python3 -I tests/test-completion-report.py ... --real-model stories15M-q4_0.gguf RealModelTests
```

Every invocation makes a new run dir `WORK/run-<UTC time>-<pid>`; case dirs are never removed or reused. Each case dir has `cmd.json` (command, extra environment, exit status), `stdout.bin`, `stderr.txt`, and the report or other files the case made.

Commands, exit codes and logs: `TEST-RESULTS.json` (`commands`). Per requirement results: `TEST-RESULTS.json` (`by_requirement`). Every case of the final run: `cases-index.json`. Exact reports with their commands: `report-examples/`.

### Result at 420f01a

55 PASS, 0 FAIL, 0 ERROR, 7 NOT_EXECUTED (`runs/runs-420f01a/run-*/results.json`). Separated by kind:

- Deterministic synthetic fixture, real binary (`SyntheticTests`, 36 tests, requirements A to I): a generated 1-layer llama model with the real llama-spm vocab, zero attention and FFN outputs, and an output matrix that maps each listed token to one next token. The EOG check, sampler, antiprompt checks, context check and serialization are the production code paths. This is a test fixture, not a real model.
- Fault injection, synthetic fixture (`FaultTests`, 9 tests): `tests/test-completion-report-shim.c`, an `LD_PRELOAD` module (Linux, shared libs only) that fails or raises a signal at the N-th `llama_process()` decode call, or, at the `fdopen()` of the report, moves the new report and puts an unrelated test-owned file at its path.
- Model-agnostic cases on the synthetic fixture (`SyntheticModelTests`, 7 tests): the same code as the real-model cases, run on the synthetic model to check the test code. They do not qualify a real model.
- Legacy (`LegacyTests`, 3 tests): without `--completion-report`, the new and the base binary give the same exit status, the same stdout bytes, and the same stderr after removing only the per-line log timestamp and the measured times in `common_perf_print` lines; no file is created; SIGINT still exits 130 with "Interrupted by user".
- Real-model integration (`RealModelTests`, 7 tests): NOT_EXECUTED, see below.

`test-arg-parser`: exit 1 for both `420f01a` and the base `ceefd16`, at the same point, the network section (`test good URL`, `http://ggml.ai/` is denied by the session egress policy). The new `--completion-report` assertions run before that section; the new binary prints the expected `invalid argument: --completion-report` for the CLI example and passes the completion example.

Static checks (`logs/420f01a/static-checks.log`): flake8 with the repo config, `ty` 0.0.88 as in the repo workflow, `git diff --check`, no non-ASCII added line. `editorconfig-checker` and the `flake8-no-print` plugin could not be installed here; their rules were checked by `git diff --check`, final newline check and `grep -c 'print('` (0).

### Failed runs kept as evidence

- `logs/dev-uncommitted/cr-dev-run1.log` and `archives/dev-uncommitted-*.tar.gz`: the first runs on the uncommitted tree. 8 failures: the legacy stderr comparison did not normalize log timestamps and padded perf numbers, and the T5 fixture path was wrong (`test-llama-archs` cannot save T5; the run then failed at model load and was correctly reported as `runtime_failure`/`init`). Later a generated T5 model without relative attention bias segfaulted at graph reservation (exit -11, no report), fixed by adding `attn_rel_b`.
- `logs/6df3172/ctest-test-completion-report-EXCERPT.txt`: ctest at `6df3172` exited 8 because the test driver's results writer read the suite after unittest had dropped its tests. All cases had run; fixed in `95de7ea`. The full log of this run was deleted by mistake, only the excerpt shown in the session is kept.
- `logs/prefix-race-95de7ea/`, `runs/runs-prefix-race/`: the new publication tests against the pre-fix binary (`95de7ea`, same production code as `6df3172`). All 3 fail: the pathname cleanup removed the partial report, and in both swap cases it removed the unrelated file that was put at the report path. Only `report.json.moved` is left in the target dirs. At `420f01a` the same tests pass.
- `logs/95de7ea/`, `archives/run-95de7ea-cr-final.tar.gz`: full run at `95de7ea`, 53 PASS, 7 NOT_EXECUTED, before the review fix.

## Fixtures and models

| Fixture | Identity |
| ------- | -------- |
| vocab | `models/ggml-vocab-llama-spm.gguf` in the repository, SHA-256 in `runs/runs-420f01a/run-*/fixtures.json` |
| synthetic model | generated by `make_model()` in `tests/test-completion-report.py` at `420f01a`, 17224000 bytes, SHA-256 in `fixtures.json`, not committed |
| synthetic T5 model | generated by `make_t5_model()`, zero weights, only used for the `encoder_decoder` rejection, SHA-256 in `fixtures.json`, not committed |
| invalid model | 64 bytes, `b"GGUF" + b"\xff" * 60`, written by the test, not committed |
| real model | NOT fetched. Intended: `tinyllamas/stories15M-q4_0.gguf` from `https://huggingface.co/ggml-org/models`, SHA-256 `66967fbece6dbe97886593fdbb73589584927e29119ec31f08090732d1861739` (as in upstream `tests/CMakeLists.txt`), license as given by its source repository. `huggingface.co:443` was denied by the session egress policy (403 on CONNECT, recorded by the session proxy), so the real-model cases are NOT_EXECUTED. |

Sampling in all runs: `--temp 0 --top-k 1 -s 1 -t 2`. This is fixture configuration, not a determinism guarantee; the synthetic model is deterministic because one token has a much higher logit (32 against 0) than all others.

## Platforms

Qualified here: Linux x86_64, CPU backend, the environment above. Not qualified: macOS (including Apple Silicon and Metal), Windows, other backends, other architectures. The cancellation code path for macOS is the same POSIX code as Linux but was not built or run on macOS. On Windows, report mode keeps the old Ctrl+C handler (exit 130 without a report); the Windows file creation code (`_open` with `_O_EXCL`) was not compiled.

## Known limitations and skipped cases

- Real-model integration: NOT_EXECUTED (no network access to Hugging Face). The 7 `RealModelTests` must be run with `--real-model` to qualify a real model.
- Supported runs only: non-interactive, conversation off, `-n N >= 0`, no `--prompt-cache`, no self-extend, decoder-only. Others are rejected with `reason` `unsupported`.
- `error.code` is always `null`: `common_prompt_batch_decode()` returns only success or failure.
- Single-token antiprompt matches also match as text in the same step for the tested vocab, because the sampler history renders special tokens; a token-only match was not exercised.
- Publication is exclusive create plus one write, not atomic and not durable (no `fsync`, no rename). A failed write keeps an empty or partial file; consumers reject it with the documented rules (parse, `pid`, exit status). Crash during the write: not tested beyond truncated files fed to the consumer check.
- Allocation failure during serialization is handled by a `catch` (exit 1) but was not tested.
- Signals: tested SIGINT and SIGTERM (raised in the process during a decode, and sent from another process), and SIGKILL (no report). A second signal of the same kind ends the process with the default action (not tested). Signals before the handler is installed give no report (not tested). No preemption of a running decode.
- `build.build_number` comes from the commit count of the checkout; this clone is shallow, so it is 4 at `420f01a` and 1 at the base, not the release numbers. The example report in `tools/completion/README.md` was copied from a development build of the uncommitted tree, so its build info shows the base commit `ceefd16` and build number 1.
- `test-arg-parser` cannot pass in this environment (network section), for the base as well.
