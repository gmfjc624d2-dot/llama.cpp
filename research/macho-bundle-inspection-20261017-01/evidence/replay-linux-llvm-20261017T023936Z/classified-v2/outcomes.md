# Replay outcomes: linux-llvm

Tool parse outcomes only. `parsed_by_tool` does not mean dyld would load the file; every other value is not passing.

| file | lipo -archs | arm64 -l / -L | x86_64 -l / -L | all -l |
|---|---|---|---|---|
| bundles/_decoy-dyld/libggml.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/_decoy-dyld/libllama.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/_decoy-dyld/libmissing.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/_outside/b06-symlinks/libescape.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/_outside/b13-dotdot-escape/libx.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b01-flat-good/README.txt | rc 1 | not_object / not_object | not_object / not_object | not_object |
| bundles/b01-flat-good/libggml-base.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b01-flat-good/libggml-cpu.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b01-flat-good/libggml.0.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b01-flat-good/libllama.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b01-flat-good/llama-cli | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b02-nested-inherited-rpath/PlugIns/libggml-metal.so | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b02-nested-inherited-rpath/bin/llama-server | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b02-nested-inherited-rpath/lib/libggml.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b02-nested-inherited-rpath/lib/libllama.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b02-nested-inherited-rpath/lib/sub/libnested.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b03-build-rpath/libggml-base.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b03-build-rpath/libggml.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b03-build-rpath/libllama.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b03-build-rpath/llama-cli | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b04-system-and-external/app | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b04-system-and-external/lib/libok.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b05-cycle/libA.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b05-cycle/libB.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b05-cycle/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b06-symlinks/bin/tool | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b06-symlinks/lib/real/libinternal.1.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b07-missing-arch/libfat.dylib | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| bundles/b07-missing-arch/libx86only.dylib | x86_64 | arch_absent / arch_absent | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| bundles/b07-missing-arch/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b08-universal-broken-slice/libu.dylib | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| bundles/b08-universal-broken-slice/main | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| bundles/b09-weak-missing/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b10-unknown-lc-dep/libunk.dylib | arm64 | unknown_load_command / parsed_by_tool | unknown_load_command / arch_absent | unknown_load_command |
| bundles/b10-unknown-lc-dep/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b11-malformed-dep/libtrunc.dylib | rc 1 | rejected / rejected | rejected / rejected | rejected |
| bundles/b11-malformed-dep/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b12-root-symlink/real/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b13-dotdot-escape/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b14-undecodable-dep/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b15-duplicate-rpath/libok.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b15-duplicate-rpath/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b16-case-mismatch/libggml.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b16-case-mismatch/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b17-dependency-is-executable/helper | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b17-dependency-is-executable/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b18-dyld-environment/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b19-dependency-kinds/liblazy.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b19-dependency-kinds/libload.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b19-dependency-kinds/libreexport.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b19-dependency-kinds/libupward.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b19-dependency-kinds/libweak.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b19-dependency-kinds/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b20-dependency-kinds-no-lazy/libload.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b20-dependency-kinds-no-lazy/libreexport.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b20-dependency-kinds-no-lazy/libupward.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b20-dependency-kinds-no-lazy/libweak.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b20-dependency-kinds-no-lazy/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b21-loader-path-symlink-dir/main | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b21-loader-path-symlink-dir/versions/A/lib/libbar.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/b21-loader-path-symlink-dir/versions/A/lib/libfoo.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/m01-empty.bin | rc 1 | not_object / not_object | not_object / not_object | not_object |
| parse/m02-short-magic.bin | rc 1 | not_object / not_object | not_object / not_object | not_object |
| parse/m03-truncated-header.bin | rc 1 | not_object / not_object | not_object / not_object | not_object |
| parse/m04-not-macho-script.bin | rc 1 | not_object / not_object | not_object / not_object | not_object |
| parse/m05-sizeofcmds-beyond-eof.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m06-ncmds-huge.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m07-cmdsize-zero.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m08-cmdsize-unaligned.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m09-cmdsize-overrun.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m10-lcstr-offset-beyond-cmd.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m11-lcstr-no-nul.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m12-unknown-lc.bin | arm64 | unknown_load_command / parsed_by_tool | unknown_load_command / arch_absent | unknown_load_command |
| parse/m13-unknown-lc-req-dyld.bin | arm64 | unknown_load_command / parsed_by_tool | unknown_load_command / arch_absent | unknown_load_command |
| parse/m14-duplicate-id-dylib.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m15-lcstr-offset-into-header.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m16-segment-size-mismatch.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m17-section-amplification.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m18-fat-nfat-huge.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m19-fat-slice-beyond-eof.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m20-fat-overlapping-slices.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m21-fat-arch-mismatch.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m22-fat-duplicate-arch.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
| parse/m23-java-class-magic.bin | rc 1 | not_object / not_object | not_object / not_object | not_object |
| parse/m24-sizeofcmds-slack.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t01-thin-arm64-exe.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t02-thin-arm64-dylib.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t03-thin-x86_64-dylib.bin | x86_64 | arch_absent / arch_absent | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| parse/t04-thin-arm64e-dylib.bin | arm64e | arch_absent / arch_absent | arch_absent / arch_absent | parsed_by_tool |
| parse/t05-build-rpath-exe.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t06-dyld-environment-exe.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t07-undecodable-path.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t08-duplicate-rpath.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/t09-all-dependency-kinds.bin | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| parse/u01-fat-x86_64-broken-arm64-ok.bin | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| parse/u02-fat-x86_64-ok-arm64-broken.bin | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| parse/u03-fat-per-slice-rpaths.bin | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| parse/u04-fat64-ok.bin | x86_64 arm64 | arch_absent / arch_unverified | parsed_by_tool / parsed_by_tool | parsed_by_tool |
| parse/u05-fat-x86_64-cmdsize-zero-arm64-ok.bin | rc 1 | rejected / rejected | rejected / rejected | rejected |
