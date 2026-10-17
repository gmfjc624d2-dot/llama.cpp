# UNQUALIFIED draft - do not use as a gate

`macho_bundle_inspect.py` here is a frozen draft of a bounded Mach-O load-command
validator, JSON inventory and narrow bundle check. Per the scope decision for
public-macho-inspection-20261017-01 it was stopped before qualification:

- no test suite, no review, no comparison with native macOS `otool`;
- 932 lines (sha256 `bad54bbea28d020a9aef30a1835c3ec23dcaa0ab463405b799f60bf0391b1b71`), above the size that a demonstrated gap would justify;
- a replacement parser is deferred pending local adjudication. Do not extend it here.

The only runs are the dev runs in `evidence/dev-inspector-20261017T022856Z/`: one internal error (run 02, missing CPU constants, fixed before run 03), the `inspect` run 03 over all parse fixtures, and one `check` per bundle for arm64 (`check/`). Those `.cmd` files name the old path `tool/macho_bundle_inspect.py`; the file was moved here unchanged after those runs, and this hash is the one that ran in run 03 and in `check/`. An earlier, broader version (inherited `@rpath` modelling) was never run and is not kept.

Known limits of the draft (not fixed): the `check` verdict follows the policies written in its `SEVERITY` table, not dyld; case-insensitive and normalization-insensitive volume lookup is not modelled (b16 is `fail` on Linux); inherited `@rpath`, lazy loads, `LC_DYLD_ENVIRONMENT` and dyld fallback paths are reported as unsupported context; there is no time limit inside the process.
