# CMake 4.4.4 BundleUtilities / GetPrerequisites: source reading

Source: public tag `v4.4.4` of https://github.com/Kitware/CMake (tag object
`569e8959d3c6d49cf77ae00d51ce18e1bceb62ea`, commit
`2e0b3aec14fe2e3e555faac4698e281749aae4b5`, tagger Brad King), fetched blobless
(logs 01-04). Blobs: `Modules/BundleUtilities.cmake` `7b063f8a6d8c0ec8adafa2c4f90ce2311e39ce71`,
`Modules/GetPrerequisites.cmake` `952e66c0d1da8ece3696d0b95e37254d036753bb`, `LICENSE.rst`
`3ddcf8774af6d2d08b8bda6f28c970948b39f60e` (BSD 3-Clause; copies in logs 05 and 06).

This is source reading only. CMake was not built or run here, and no bundle was fixed up.
Line numbers refer to the `05-show-*.log` copies (= file lines).

| # | observation | where |
|---|---|---|
| 1 | `verify_bundle_symlinks` is a stub: sets `result 1` and has the comment "TODO: implement this function for real... Right now, it is just a stub that verifies unconditionally". `verify_app` calls it. | BundleUtilities 1374-1384, call at 1414 |
| 2 | `gp_resolved_file_type` sets `is_embedded 1` for any item that matches `^@(executable|loader)_path`. It does not resolve the item and does not check that it stays inside the bundle, so `@loader_path/../../outside/x.dylib` counts as embedded. | GetPrerequisites 610-618 |
| 3 | `get_item_rpaths` runs `otool -l <item>` with no `-arch` and collects every `LC_RPATH` with a regex. It adds each path once (`IN_LIST`), so the per-architecture lists are merged, duplicates disappear, and the slice that an rpath came from is lost. | BundleUtilities 711-736 |
| 4 | `gp_resolve_item` resolves `@rpath/x` with `find_file(... ${exepath} ${dirs} ${rpaths} NO_DEFAULT_PATH)` on the host filesystem. The search order is exepath and dirs first, then the merged rpaths, not dyld's per-image order. An absolute build-tree rpath that exists on the build host resolves there. | GetPrerequisites 487-495 (area) |
| 5 | `get_prerequisites` uses `otool -L` (no `-arch`) and the regex `^\t([^\t]+) \(compatibility version ..., current version ...(, weak)?\)`. From the regex alone, lines that `otool -L` marks `reexport`, `upward` or `lazy` (seen with llvm-otool 18 in baseline C4) would not match. Not run here, so not confirmed. | GetPrerequisites 853-858 |

Consequence for this request: `fixup_bundle` / `verify_app` are not a containment, symlink-escape or per-architecture gate and are not used as one.
