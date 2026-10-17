# Mach-O bundle inspection: existing tools, public fixtures, macOS replay recipe

Request `public-macho-inspection-20261017-01`. Research files only: there is no change to llama.cpp
runtime, build or mandatory dependencies, and no upstream PR. **Nothing here is macOS
qualification.** Three kinds of statement are kept apart in this file:

- **Linux measurements:** made in this Cloud session on Linux x86_64 with LLVM 18 tools and macholib.
- **Source review:** read from the scripts and sources in this branch, not observed as a failure.
- **Caller-reported macOS observations:** native results that the caller reported. They are not
  measurements from this session, and their raw artifacts are not in this branch (see
  [below](#macos-observations-reported-by-the-caller-not-measured-in-this-session)).

This session made no native macOS measurements, and the macOS replay recipe below was not run
here. Fixtures are synthetic parse fixtures; no fixture was run, and no target was loaded,
executed, modified or signed. Parser agreement (macholib, llvm-otool, otool) is not evidence that
dyld would load a file. Return code 0, a successful parse, or the absence of a recognized warning
is not a validity gate for untrusted binaries.

## Decision

1. **macholib 1.16.4 is rejected** as the reader or resolver for untrusted bundles
   ([FINDINGS-baseline.md](FINDINGS-baseline.md)). Its raw parser accepts malformed load commands
   and fat tables, loses the good slice when another one is bad, and needs unbounded memory for
   overlapping sections (320 KiB input -> `MemoryError` at 1 GiB). Its `walkRelocatables`, `dump`,
   `dyld_find` and `MachOGraph` helpers are limited by design: no lazy loads, no `@rpath`, host
   `DYLD_*` and host paths.
2. **The custom parser is deferred.** The 932-line draft is frozen in
   [unqualified-draft/](unqualified-draft/UNQUALIFIED.md): no tests, not qualified, not to be
   extended. No tool result in this file reopens parser work by itself; that needs a separate decision.
3. **Path for the macOS consumer: native `otool` / `lipo` / `file`**, through a replay wrapper
   with per-case limits ([limits](#replay-wrapper-limits-source-review); the worker as a whole is
   not resource-bounded) that records raw stdout/stderr/rc and classifies conservatively
   ([scripts/replay_otool.sh](scripts/replay_otool.sh),
   [scripts/classify_replay.py](scripts/classify_replay.py)). After that comes the **separate,
   required relocated runtime test** ([scripts/macos_relocated_runtime_test.sh](scripts/macos_relocated_runtime_test.sh)).
   Neither wrapper parses Mach-O bytes itself; the classifier reads only the tools' text output.

## Identities

| item | value |
|---|---|
| branch | `claude/adoring-shannon-msj8rb` on `gmfjc624d2-dot/llama.cpp`, based on public `420f01a4f0b6514d1880e9d347157ebed25d2edb` |
| earlier branch (unchanged) | `claude/pensive-fermi-tpr2cj` at `930f59c212b0da09acd77c7b0f0b0aca816c2d18` |
| checkpoint 1 | `d684bb18a0bdb49d40f9e628f151f8ecc05149b7` (baseline; has case-colliding names, see below) |
| checkpoint 2 | `6a67e59f0e6b1729f832a2b179da7a057769a878` (case-collision rename) |
| macholib / altgraph | 1.16.4 (`v1.16.4` = `ce372341...`) / 0.17.5 (`v0.17.5` = `3719ef29...`), MIT; wheel hashes in [requirements.txt](requirements.txt), wheels in `evidence/upstream/wheels/` |
| CMake (source only) | `v4.4.4`, tag object `569e8959...`, commit `2e0b3aec...` |
| Linux tools | Ubuntu LLVM 18.1.3 `llvm-otool-18`, `llvm-lipo-18`, `llvm-objdump-18`; `file-5.45`; Python 3.13 |

## Existing-tools sufficiency analysis

| tool | per-arch load commands | malformed input | bounds | symlinks / containment | `@rpath` resolution | use here |
|---|---|---|---|---|---|---|
| native `otool -arch A -l/-L`, `lipo -archs`, `file` (macOS) | not measured in this session; caller reports m21 can print an inner x86_64 header when arm64 was requested | not measured in this session; caller reports (otool-classic and macholib replay) m08's alignment defect accepted, m10/m15 rc 0 with invalid-name indications, m24 rc 0 with an inconsistent-size diagnostic | per case only: wall timeout on the direct PID, `ulimit -t`/`-v` if accepted; no output quota; inputs hashed before the size cap ([limits](#replay-wrapper-limits-source-review)) | not its job: the replay records `readlink` as data | no | static inventory aid via replay, not a validity gate |
| `llvm-otool` 18 (Linux) | **no**: ignores `-arch` for `-l`/`-h`; `-arch all` prints only the first slice (all 7 fat inputs `arch_selection_unreliable`; it would attribute u03's x86_64 build rpath to arm64) | rejects m05-m11, m14-m22, u05; accepts m12/m13 (`cmd ?(`), m24, u01/u02; rc 0 for non-objects; truncated header m03 shown as "not an object file" | as above | no | no | Linux comparison only |
| `llvm-objdump --macho --arch=A` 18 (Linux) | yes in a probe (u03, and it reads the good arm64 slice of u05) | not studied | - | no | no | possible Linux convenience, not qualified |
| macholib 1.16.4 | raw parser yes for well-formed input | accepts m08, m10, m11, m15, m21, m22; `MemoryError` on m17 | none built in | no | none (`MachOGraph`) | rejected |
| CMake 4.4.4 `BundleUtilities` / `GetPrerequisites` | `otool -l`/`-L` without `-arch`, rpaths merged across slices | not studied | - | `verify_bundle_symlinks` is a stub that always succeeds; `@loader_path`/`@executable_path` items count as embedded without a containment check | host `find_file`, exepath/dirs before rpaths | **not an escape gate** ([observations](evidence/cmake-source-check-20261017T023148Z/observations.md)) |
| dyld, relocated runtime test (macOS) | the one arch that ran | real loader | wall timeout on the direct PID only | trace of the observed run checked against the copy; the original build stays readable | real, for that OS version, arch, command and run only | required separate step for the consumer's own trusted build |

**Conclusion.** For the macOS consumer's purpose, a static inventory of the load commands of its
own build, native `otool`/`lipo`/`file` behind the replay wrapper plus the relocated runtime test
is the proposed path. It is **not a validity gate for untrusted binaries**.

The caller-reported native observations show why the tool's output can't serve as one:
- m08's alignment defect is accepted;
- m10 and m15 can return 0 with invalid-name indications, and m24 returns 0 with an inconsistent-size diagnostic;
- m21 can show a slice other than the one requested.

The gaps shown in this session are on the Linux side: llvm-otool's arch selection, JSON output,
per-slice isolation, and Linux availability. Path resolution cases that the static string checks
cannot see (b02 inherited `@rpath`, b14, b16 case-only match, b17 executable as dependency) are
left to dyld in the runtime test, with the limits stated there.

**What would weaken this path**, if seen in a native replay:
- native otool also ignores `-arch` (any fat fixture `arch_selection_unreliable`);
- rc 0 for a fixture that llvm-otool rejects (m05-m11, m14-m22, u05), as the caller reports for m08, m10 and m15;
- a timeout.

Such results limit what the replay can be used for. They do not by themselves start custom-parser
work, and the 932-line draft stays frozen and unqualified.

## Linux llvm-otool replay (Linux measurement, separate from macOS)

`evidence/replay-linux-llvm-20261017T024344Z/`: 99 files, 10 symlinks, 1005 cases (rc 0: 849,
rc 1: 156). No case reached the timeout, and no input was larger than `max_bytes` (1 MiB), so no
case was skipped. All inputs were still hashed in full (see limits). arm64 outcomes:

| outcome (-l / -L) | files |
|---|---|
| parsed_by_tool / parsed_by_tool | 62 |
| rejected / rejected | 18 |
| arch_selection_unreliable / arch_unverified | 7 |
| not_object / not_object | 4 |
| unknown_load_command / parsed_by_tool | 3 |
| arch_absent / arch_absent | 3 |
| not_object_but_macho_magic | 2 (m03 truncated header, m23 Java class) |

Consumer example ([examples/consume_outcomes.py](examples/consume_outcomes.py)) per bundle for
arm64 with forbidden root `/tmp/llama-build-7f3a`, in `consumer-example-v5/`. Exit 0 means only
"no static defect found" by its few string and symlink rules. It does not mean the dependencies
resolve, and it is not a validity verdict for untrusted binaries:

- fail (1): b03, b04, b06, b07, b08, b10, b11, b13
- unsupported (3): b15 duplicate `LC_RPATH`, b18 `LC_DYLD_ENVIRONMENT`, b19 lazy load, b21 directory symlink
- no static defect found (0): b01, b02, b05, b09, b12, b14, b16, b17, b20

## macOS observations reported by the caller (not measured in this session)

This Cloud session made no native macOS measurements. The caller reports a separate, already
completed, bounded 12-fixture replay on macOS arm64 (fixture names as in this branch) with Apple `otool-classic`
and stock macholib 1.16.4. Its raw artifacts are not in this branch, and nothing here links to
them. The examples below are as reported by the caller and were not re-checked here:

| fixture | caller-reported native result | Linux measurement in this session (llvm-otool 18, for contrast only) |
|---|---|---|
| m08 (`cmdsize` not a multiple of 8) | alignment defect accepted | rejected (rc 1) |
| m10 (`lc_str` offset past `cmdsize`) | can return 0 with an invalid-name indication | rejected (rc 1) |
| m15 (`lc_str` offset inside the struct) | can return 0 with an invalid-name indication | rejected (rc 1) |
| m24 (`sizeofcmds` slack) | returns 0 with an inconsistent-size diagnostic | rc 0, no diagnostic, `parsed_by_tool` |
| m21 (`fat_arch` arm64 points at an x86_64 slice) | can print the inner x86_64 header when arm64 was requested | rejected (rc 1) |

- As reported, no target fixture was executed and no m17 memory replay took place on macOS.
- No dyld-loadability conclusion follows from these results.
- The caller used `otool-classic`. `replay_otool.sh` uses whatever `xcrun --find otool` selects, which is not necessarily `otool-classic`, so results from the two are not interchangeable without checking tool identity.

## macOS replay of the public fixtures (exact steps, static only)

Needs a Mac with Xcode or the Command Line Tools (`xcrun`, `otool`, `lipo`, `/usr/bin/python3`).
Nothing in these steps runs a fixture.

```sh
git clone --branch claude/adoring-shannon-msj8rb https://github.com/gmfjc624d2-dot/llama.cpp
cd llama.cpp/research/macho-bundle-inspection-20261017-01
python3 -I scripts/check_casefold_collisions.py --git ../..   # expect "collision_groups": 0
F=evidence/replay-fixtures-20261017T023926Z
(cd "$F" && shasum -a 256 -c fixtures.sha256)                # tar f4c9d6c3..., fixtures.json 53bd96ef...
RUN="$HOME/macho-replay-$(date -u +%Y%m%dT%H%M%SZ)"           # new dir outside the clone
mkdir -p "$RUN/fixtures" && tar -xf "$F/fixtures-snapshot.tar" -C "$RUN/fixtures"
bash scripts/replay_otool.sh macos-native "$RUN/fixtures" "$RUN/raw" 20 1048576
python3 -I scripts/classify_replay.py "$RUN/raw" "$RUN/classified"
python3 -I scripts/compare_replays.py evidence/replay-linux-llvm-20261017T024344Z/classified-v3/outcomes.json "$RUN/classified/outcomes.json" > "$RUN/compare.md"
python3 -I scripts/check_casefold_collisions.py --tree "$RUN" > "$RUN/casefold.json"
tar -cf "$RUN.tar" -C "$(dirname "$RUN")" "$(basename "$RUN")"
```

- Limits: per case only, as listed under [Replay wrapper limits](#replay-wrapper-limits-source-review). The largest fixture is 320,368 bytes. About 1000 cases.
- Tool identity is recorded as cases: `sw_vers`, `uname -a`, `hw.optional.arm64`, `xcode-select -p`, SDK version, `xcodebuild -version`, CLT package info, `otool --version` and `-version`, `lipo -version`, `file --version`, and SHA-256 of the real `otool`, `lipo` and `file` binaries.
- Raw data: `raw/cases/cNNNNN.{cmd,stdout,stderr,rc}`, `raw/index.tsv` (labels), `inputs.sha256`. Case files are numbered, so names never collide on case-insensitive volumes.
- Return `$RUN.tar` as macOS evidence. Keep it separate from the Linux runs; `compare.md` puts the platforms in separate columns.

Outcome values describe tool output only:
- `parsed_by_tool` (and `passing_parse`): the tool returned 0, none of the recognized markers appeared, and the arch checks held. For `-l` the printed header matches the requested arch; for `-L` the arch is in `lipo -archs` (and on fat files `-l` honoured `-arch` for every slice). This is not a validity verdict. The classifier recognizes only a non-zero rc, "is not an object file" or "not recognized as a valid object file", `cmd ?(` on stdout, non-empty stderr, and the header and arch checks. A diagnostic that a tool prints on stdout with rc 0, such as the caller-reported m10/m15/m24 indications, is not recognized and can still come out as `parsed_by_tool`.
- Everything else is not passing: `rejected`, `not_object`, `not_object_but_macho_magic`, `unknown_load_command`, `arch_absent`, `arch_selection_unreliable`, `arch_unverified`, `slices_missing_from_output`, `no_header`, `parsed_with_stderr`, `timeout`, `skipped_size`.

### Replay wrapper limits (source review)

Read from `scripts/replay_otool.sh` and `scripts/classify_replay.py` at commit `1116d14`. None of
these was observed as a crash or resource exhaustion; they are limits of the code, and the worker
as a whole is not resource-bounded.

- `max_bytes` gates only the per-file tool cases (`file`, `od`, `lipo`, `otool`). Before that, the script hashes every listed input in full (`inputs.sha256`) and measures it with `wc -c`. So a file over `max_bytes` is still read. The earlier text "files over 1 MiB are not read" was wrong.
- Tool stdout and stderr go to files with no output quota. `classify_replay.py` later reads each of these files into memory in full.
- The wall timeout sends `SIGKILL` to the direct child PID only. The script creates no process group, so a process that the tool itself starts is not covered.
- `ulimit -t` and `ulimit -v` run in the child with errors discarded, and the case runs even if they fail. `limits_in_child` in `raw/run.txt` reports what a separate test subshell got, not proof of enforcement for each case. A memory bound on macOS is not established (`ulimit -v` usually fails there).
- `find`, the hashing, `wc`, the shell loop itself and the classifier run without any of these limits.

## Relocated runtime test (separate, required, real bundle only)

This runs the consumer's own built program, never a fixture, and is the only step here that
executes anything. It was not run in this session. It is meant for a build the consumer already
trusts; it does not qualify running an untrusted target:

```sh
bash scripts/macos_relocated_runtime_test.sh ./dist bin/llama-cli arm64 "$HOME/reloc-arm64-1" 60 -- --version
bash scripts/macos_relocated_runtime_test.sh ./dist bin/llama-cli arm64 "$HOME/reloc-arm64-2" 60 -- --list-devices
# x86_64 slice on Apple silicon needs Rosetta: same with arch x86_64
```

- The script copies the bundle with `ditto` to a new `mktemp` directory. It runs the program under `env -i` with only `HOME`, `PATH=/usr/bin:/bin`, `TMPDIR` and `DYLD_PRINT_LIBRARIES=1`, so no inherited `DYLD_*` remain and the trace only prints. It runs via `arch -<arch>`, with a wall timeout.
- It keeps `program.stdout`, `program.stderr`, `program.rc` and `loaded.txt`.
- It passes only if rc is 0, a dyld load trace exists, and every image in the trace of that run is in the copy or under `/usr/lib/` or `/System/Library/`. A load from the build tree is caught only if it happens during that run and appears in the trace.
- Limits (source review of `scripts/macos_relocated_runtime_test.sh`):
  - The fresh copy and the clean environment leave the original build tree in place and readable. The script does not move, hide or delete it and does not enforce that it is unavailable, so a pass does not show that the bundle works without it. This research does not move, hide or delete any build; the script header's remark about hiding the build tree by hand is not part of this recipe.
  - A pass covers only the images dyld reported for that one command, arch, OS version and run. It does not prove independence from the build tree for every loading path, for example `dlopen()` paths that this command does not reach.
  - The trace is read from the program's own stderr, so the program can also write lines there. The program runs with the operator's privileges and can read anything the account can read; `env -i` keeps `HOME` and `TMPDIR`.
  - The wall timeout kills the direct PID only. Program output has no quota.
- Before the runtime test, replay the real bundle statically with the same unchanged script. It expects `parse/` and `bundles/`, so stage a copy:
  ```sh
  S=$(mktemp -d); mkdir -p "$S/parse" "$S/bundles" && ditto ./dist "$S/bundles/dist"
  bash scripts/replay_otool.sh macos-native "$S" "$HOME/replay-dist-1" 20 536870912
  python3 -I scripts/classify_replay.py "$HOME/replay-dist-1" "$HOME/replay-dist-1-classified"
  python3 -I examples/consume_outcomes.py "$HOME/replay-dist-1-classified/outcomes.json" arm64 bundles/dist/ /path/to/build-root
  ```
  Raise `max_bytes` (here 512 MiB) to the largest real dylib; every input is hashed in full regardless. Exit 0 from the consumer is only "no static defect found".

## Case-insensitive checkout incident

Checkpoint 1 (`d684bb1`) had otool logs `L__*` (`-L`) and `l__*` (`-l`): 285 collision groups,
so a faithful checkout on default macOS volumes was not possible. Checkpoint 2 renamed 597 files
with `git mv`, bytes unchanged, to `dependencies__*` / `loadcommands__*`. The map with old paths
and SHA-256 is in [evidence/path-renames-1.json](evidence/path-renames-1.json). History was not
rewritten. [scripts/check_casefold_collisions.py](scripts/check_casefold_collisions.py) (NFD +
casefold, every directory component) runs on the tree, the git index, tar members and each run dir.

## Evidence index

| dir | what |
|---|---|
| `evidence/acquisition-*` | clones, tags, PyPI downloads, hashes, diffs wheel/sdist vs tag, offline install, pinned-release facts |
| `evidence/upstream/` | vendored wheels, licenses, PyPI metadata |
| `evidence/dev-20261017T021238Z/` | first generator version and llvm-otool dev check |
| `evidence/baseline-stock-macholib-*` | baseline: fixtures, probe, otool oracle, summary |
| `evidence/checkpoint-*/` | manifests per commit, checkpoint-2 onward taken from the git index (checkpoint-1 paths updated after the rename, see `paths_renamed_after`) |
| `evidence/verify-checkpoint-*` | fresh-clone checks |
| `evidence/casefold-fix-*` | collision check before and after, rename log, checker tests |
| `evidence/dev-inspector-*` | runs of the now unqualified draft |
| `evidence/cmake-source-check-*` | CMake 4.4.4 module sources (BSD-3-Clause, with LICENSE.rst) and observations |
| `evidence/replay-fixtures-*` | fixture snapshot for the replay (adds u05 and b21), determinism check |
| `evidence/replay-linux-llvm-*` | Linux llvm-otool replays, classifications v1-v3, arch selection probe, consumer runs; `-staging-check-*` tries the real-bundle staging steps on b01 |

## Retained negative and initial results

- Checkpoint 1 case collisions (above); first unittest invocation failed (`python -I -m unittest <path>`, `casefold-fix-*/08`); `04-sha256-tar` was run from the wrong directory (`replay-fixtures-*`).
- Shell quoting mistake `l-arch-.*` and the `logrun.sh` overwrite refusals (baseline).
- Draft internal error (dev-inspector run 02).
- First replay `replay-linux-llvm-20261017T023936Z` had no magic read. Its `classified/` trusted `-L` on fat files, and `classified-v2/` still trusted a coincidental first-slice match; both are kept, and `classified-v3/` fixes them.
- Consumer example versions v1-v4 had weaker rules (forbidden roots only, no symlink checks, no lexical escape check).
- The README at `1116d14` overstated some limits and conclusions; see the corrections below.

## Documentation corrections, 2026-10-17

Documentation only: no script, fixture or evidence file changed, and nothing was rerun. Compared
with the README at `1116d14`:

- **Removed claims:**
  - "files over 1 MiB are not read";
  - `raw/run.txt` "records whether it took effect" for `ulimit -v`;
  - the whole replay wrapper described as "bounded";
  - "That last condition catches loads from the build tree", without qualification;
  - the advice to hide the build tree by hand;
  - "Any one of these means ... the deferred parser question reopens".
- **Added:**
  - the per-case limits from source review;
  - the runtime test limits;
  - the caller-reported macOS observations, kept apart from the Linux measurements;
  - the classifier marker limits;
  - the statement that rc 0, a parse or no warning is not a validity gate.

`FINDINGS-baseline.md` has a dated addendum that qualifies its worker-survival statement.

## Limits

- This session has no native macOS measurements. Every tool result measured here is LLVM on Linux. Caller-reported macOS observations are listed in their own section, without raw artifacts in this branch.
- Rc 0, a successful parse, the absence of a recognized warning, `parsed_by_tool` and the consumer's "no static defect found" are limited outcomes, not a validity gate for untrusted binaries.
- The replay wrapper and the runtime test have only per-case or per-run limits ([source review](#replay-wrapper-limits-source-review)); the worker as a whole is not resource-bounded.
- The replay classifies tool output only. The static consumer does not resolve `@rpath`, `@loader_path` or `@executable_path`, and does not model case-insensitive or normalization-insensitive lookup, inherited `@rpath`, dyld fallback paths, lazy loads or `LC_DYLD_ENVIRONMENT`. Those are left to the runtime test or reported as unsupported.
- Local paths of the cloud container (`/home/user/...`, `/tmp/claude-0/...`) appear in `.cmd` files. They are container paths, not user machine paths. No credentials are recorded.
