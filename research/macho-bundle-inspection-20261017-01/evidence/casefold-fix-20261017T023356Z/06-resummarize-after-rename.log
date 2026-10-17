| fixture | `python -m macholib dump` | `MachO()` strict | `MachO(allow_unknown)` + `walkRelocatables` | `llvm-otool -l` |
|---|---|---|---|---|
| m01-empty | exit 0, 0 dep lines | ERROR error: unpack requires a buffer of 4 bytes | ERROR error: unpack requires a buffer of 4 bytes | exit 0, is not an object file |
| m02-short-magic | exit 0, 0 dep lines | ERROR error: unpack requires a buffer of 4 bytes | ERROR error: unpack requires a buffer of 4 bytes | exit 0, is not an object file |
| m03-truncated-header | exit 1, 0 dep lines, struct.error: unpack requires a buffer of 32 bytes | ERROR error: unpack requires a buffer of 32 bytes | ERROR error: unpack requires a buffer of 32 bytes | exit 0, is not an object file |
| m04-not-macho-script | exit 0, 0 dep lines | ERROR ValueError: Unknown Mach-O header: 0x23212f62 in <_io.BufferedReader name='./par | ERROR ValueError: Unknown Mach-O header: 0x23212f62 in <_io.BufferedReader name='./par | exit 0, is not an object file |
| m05-sizeofcmds-beyond-eof | exit 1, 0 dep lines, struct.error: unpack requires a buffer of 64 bytes | ERROR error: unpack requires a buffer of 64 bytes | ERROR error: unpack requires a buffer of 64 bytes | exit 1, 'parse/m05-sizeofcmds-beyond-eof.bin': truncated or malformed object ( |
| m06-ncmds-huge | exit 1, 0 dep lines, ValueError: Unknown load command: 0 | ERROR ValueError: Unknown load command: 0 | ERROR ValueError: ('Invalid size %s while reading from %s', -8, <_io.BufferedReader na | exit 1, 'parse/m06-ncmds-huge.bin': truncated or malformed object (load comman |
| m07-cmdsize-zero | exit 1, 0 dep lines, ValueError: ('Invalid size %s while reading from %s', -12, <_io.Buffer | ERROR ValueError: ('Invalid size %s while reading from %s', -12, <_io.BufferedReader n | ERROR ValueError: ('Invalid size %s while reading from %s', -12, <_io.BufferedReader n | exit 1, 'parse/m07-cmdsize-zero.bin': truncated or malformed object (load comm |
| m08-cmdsize-unaligned | exit 0, 0 dep lines | ok, 1 header(s) | ok: - | exit 1, 'parse/m08-cmdsize-unaligned.bin': truncated or malformed object (load |
| m09-cmdsize-overrun | exit 1, 0 dep lines, struct.error: unpack requires a buffer of 8 bytes | ERROR error: unpack requires a buffer of 8 bytes | ERROR error: unpack requires a buffer of 8 bytes | exit 1, 'parse/m09-cmdsize-overrun.bin': truncated or malformed object (load c |
| m10-lcstr-offset-beyond-cmd | exit 0, 0 dep lines | ok, 1 header(s) | ok: - | exit 1, 'parse/m10-lcstr-offset-beyond-cmd.bin': truncated or malformed object |
| m11-lcstr-no-nul | exit 0, 1 dep lines | ok, 1 header(s) | ok: load_dylib=@rpath/libnonul-ab.dyli | exit 1, 'parse/m11-lcstr-no-nul.bin': truncated or malformed object (load comm |
| m12-unknown-lc | exit 1, 0 dep lines, ValueError: Unknown load command: 126 | ERROR ValueError: Unknown load command: 126 | ok: load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |
| m13-unknown-lc-req-dyld | exit 1, 0 dep lines, ValueError: Unknown load command: 2147483774 | ERROR ValueError: Unknown load command: 2147483774 | ok: load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |
| m14-duplicate-id-dylib | exit 1, 0 dep lines, ValueError: This dylib already has an id | ERROR ValueError: This dylib already has an id | ERROR ValueError: This dylib already has an id | exit 1, 'parse/m14-duplicate-id-dylib.bin': truncated or malformed object (mor |
| m15-lcstr-offset-into-header | exit 0, 0 dep lines | ok, 1 header(s) | ok: - | exit 1, 'parse/m15-lcstr-offset-into-header.bin': truncated or malformed objec |
| m16-segment-size-mismatch | exit 1, 0 dep lines, ValueError: Segment size mismatch | ERROR ValueError: Segment size mismatch | ERROR ValueError: Segment size mismatch | exit 1, 'parse/m16-segment-size-mismatch.bin': truncated or malformed object ( |
| m17-section-amplification | exit 1, 0 dep lines, lost sys.stderr | ERROR MemoryError:  | ERROR MemoryError:  | exit 1, 'parse/m17-section-amplification.bin': truncated or malformed object ( |
| m18-fat-nfat-huge | exit 0, 0 dep lines | ERROR error: unpack requires a buffer of 20 bytes | ERROR error: unpack requires a buffer of 20 bytes | exit 1, 'parse/m18-fat-nfat-huge.bin': truncated or malformed fat file (fat_ar |
| m19-fat-slice-beyond-eof | exit 1, 0 dep lines, struct.error: unpack requires a buffer of 64 bytes | ERROR error: unpack requires a buffer of 64 bytes | ERROR error: unpack requires a buffer of 64 bytes | exit 1, 'parse/m19-fat-slice-beyond-eof.bin': truncated or malformed fat file  |
| m20-fat-overlapping-slices | exit 1, 0 dep lines, ValueError: Unknown Mach-O header: 0x06000000 in <_io.BufferedReader n | ERROR ValueError: Unknown Mach-O header: 0x06000000 in <_io.BufferedReader name='./par | ERROR ValueError: Unknown Mach-O header: 0x06000000 in <_io.BufferedReader name='./par | exit 1, 'parse/m20-fat-overlapping-slices.bin': truncated or malformed fat fil |
| m21-fat-arch-mismatch | exit 0, 1 dep lines | ok, 1 header(s) | ok: load_dylib=/usr/lib/libSystem.B.dylib | exit 1, 'parse/m21-fat-arch-mismatch.bin': truncated or malformed object (univ |
| m22-fat-duplicate-arch | exit 0, 2 dep lines | ok, 2 header(s) | ok: load_dylib=/usr/lib/libSystem.B.dylib; load_dylib=/usr/lib/libSystem.B.dylib | exit 1, 'parse/m22-fat-duplicate-arch.bin': truncated or malformed fat file (c |
| m23-java-class-magic | exit 0, 0 dep lines | ERROR error: unpack requires a buffer of 20 bytes | ERROR error: unpack requires a buffer of 20 bytes | exit 0, is not an object file |
| m24-sizeofcmds-slack | exit 1, 0 dep lines, ValueError: Read 488 bytes, header reports 496 bytes | ERROR ValueError: Read 488 bytes, header reports 496 bytes | ERROR ValueError: Read 488 bytes, header reports 496 bytes | exit 0 |
| t01-thin-arm64-exe | exit 0, 2 dep lines | ok, 1 header(s) | ok: load_dylib=@rpath/libllama.dylib,load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |
| t02-thin-arm64-dylib | exit 0, 2 dep lines | ok, 1 header(s) | ok: load_dylib=@rpath/libggml-base.dylib,load_weak_dylib=/usr/lib/libc++.1.dylib | exit 0 |
| t03-thin-x86_64-dylib | exit 0, 1 dep lines | ok, 1 header(s) | ok: load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |
| t04-thin-arm64e-dylib | exit 0, 1 dep lines | ok, 1 header(s) | ok: load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |
| t05-build-rpath-exe | exit 0, 2 dep lines | ok, 1 header(s) | ok: load_dylib=@rpath/libllama.dylib,load_dylib=/tmp/llama-build-7f3a/ggml/src/libggml.dylib | exit 0 |
| t06-dyld-environment-exe | exit 0, 1 dep lines | ok, 1 header(s) | ok: load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |
| t07-undecodable-path | exit 1, 0 dep lines, UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 1 | ok, 1 header(s) | ERROR UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 10: invalid | exit 0 |
| t08-duplicate-rpath | exit 0, 1 dep lines | ok, 1 header(s) | ok: load_dylib=@rpath/libllama.dylib | exit 0 |
| t09-all-dependency-kinds | exit 0, 4 dep lines | ok, 1 header(s) | ok: load_dylib=@rpath/libload.dylib,load_weak_dylib=@rpath/libweak.dylib,reexport_dylib=@rpath/libreexport.dylib,load_upward_dylib=@rpath/libupward.dylib | exit 0 |
| u01-fat-x86_64-broken-arm64-ok | exit 1, 0 dep lines, ValueError: Read 376 bytes, header reports 368 bytes | ERROR ValueError: Read 376 bytes, header reports 368 bytes | ERROR ValueError: Read 376 bytes, header reports 368 bytes | exit 0 |
| u02-fat-x86_64-ok-arm64-broken | exit 1, 0 dep lines, ValueError: Read 376 bytes, header reports 368 bytes | ERROR ValueError: Read 376 bytes, header reports 368 bytes | ERROR ValueError: Read 376 bytes, header reports 368 bytes | exit 0 |
| u03-fat-per-slice-rpaths | exit 0, 0 dep lines | ok, 2 header(s) | ok: -; - | exit 0 |
| u04-fat64-ok | exit 0, 0 dep lines | ok, 2 header(s) | ok: load_dylib=/usr/lib/libSystem.B.dylib; load_dylib=/usr/lib/libSystem.B.dylib | exit 0 |

| bundle root | `dump DIR` | `MachOGraph(env={})` | `MachOGraph(env={DYLD_LIBRARY_PATH: decoy})` | `MachOGraph(env=None)`, child has DYLD_LIBRARY_PATH |
|---|---|---|---|---|
| b01-flat-good/llama-cli | exit 0, 12 dep lines | parsed outside bundle: none; missing: 4 | parsed outside bundle: ['./bundles/_decoy-dyld/libllama.dylib']; missing: 3 | parsed outside bundle: ['./bundles/_decoy-dyld/libllama.dylib']; missing: 3 |
| b02-nested-inherited-rpath/bin/llama-server | exit 0, 7 dep lines | parsed outside bundle: none; missing: 2 | parsed outside bundle: ['./bundles/_decoy-dyld/libllama.dylib']; missing: 1 | parsed outside bundle: ['./bundles/_decoy-dyld/libllama.dylib']; missing: 1 |
| b04-system-and-external/app | exit 0, 10 dep lines | parsed outside bundle: none; missing: 8 | parsed outside bundle: ['./bundles/_decoy-dyld/libmissing.dylib']; missing: 7 | parsed outside bundle: ['./bundles/_decoy-dyld/libmissing.dylib']; missing: 7 |
| b06-symlinks/bin/tool | exit 0, 7 dep lines, dump: ./bundles/b06-symlinks/lib/libloop2.dylib: No such file or direc | parsed outside bundle: none; missing: 6 | parsed outside bundle: none; missing: 6 | parsed outside bundle: none; missing: 6 |
| b19-dependency-kinds/main | exit 0, 9 dep lines | parsed outside bundle: none; missing: 4 | parsed outside bundle: none; missing: 4 | parsed outside bundle: none; missing: 4 |
