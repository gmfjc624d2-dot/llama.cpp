# Replay outcomes: linux-llvm

Tool parse outcomes only. `parsed_by_tool` does not mean dyld would load the file; every other value is not passing.

| file | lipo -archs | arm64 -l / -L | x86_64 -l / -L | all -l |
|---|---|---|---|---|
| parse/t01-thin-arm64-exe.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/u03-fat-per-slice-rpaths.bin | x86_64 arm64 | arch_selection_unreliable / arch_unverified | arch_selection_unreliable / arch_unverified | slices_missing_from_output |
| parse/m08-cmdsize-unaligned.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m17-section-amplification.bin | rc None | not_run / not_run | not_run / not_run | not_run |
| bundles/b01-flat-good/missing.dylib | rc None | not_run / not_run | not_run / not_run | not_run |
