#!/usr/bin/env python3
"""Generate deterministic synthetic Mach-O fixtures.

The files have real mach_header / fat_header / load command layouts, but they
are parse fixtures only: they have no code that can run, no symbol tables and
no code signatures. They are not runtime evidence.
"""

import argparse
import hashlib
import io
import json
import os
import struct
import sys
import tarfile

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF

ARCH = {
    "arm64": (0x0100000C, 0x0),
    "arm64e": (0x0100000C, 0x80000002),
    "x86_64": (0x01000007, 0x3),
}
TEXT = {
    "arm64": bytes.fromhex("c0035fd6"),
    "arm64e": bytes.fromhex("c0035fd6"),
    "x86_64": b"\xc3\x90\x90\x90",
}

MH_EXECUTE, MH_DYLIB, MH_BUNDLE = 2, 6, 8
FLAGS = {MH_EXECUTE: 0x00200085, MH_DYLIB: 0x00100085, MH_BUNDLE: 0x00000085}

LC_REQ_DYLD = 0x80000000
LC_SEGMENT_64 = 0x19
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_DYLINKER = 0xE
LC_LOAD_WEAK_DYLIB = 0x18 | LC_REQ_DYLD
LC_UUID = 0x1B
LC_RPATH = 0x1C | LC_REQ_DYLD
LC_REEXPORT_DYLIB = 0x1F | LC_REQ_DYLD
LC_LAZY_LOAD_DYLIB = 0x20
LC_LOAD_UPWARD_DYLIB = 0x23 | LC_REQ_DYLD
LC_DYLD_ENVIRONMENT = 0x27
LC_MAIN = 0x28 | LC_REQ_DYLD
LC_BUILD_VERSION = 0x32

KIND = {
    "load": LC_LOAD_DYLIB,
    "weak": LC_LOAD_WEAK_DYLIB,
    "reexport": LC_REEXPORT_DYLIB,
    "upward": LC_LOAD_UPWARD_DYLIB,
    "lazy": LC_LAZY_LOAD_DYLIB,
}

DEFAULT_BUILD_ROOT = "/tmp/llama-build-7f3a"
SYS = b"/usr/lib/libSystem.B.dylib"
CXX = b"/usr/lib/libc++.1.dylib"


def str_cmd(cmd, s, tail=b""):
    # lc_str placed right after the fixed fields, padded so cmdsize is a multiple of 8
    off = 12 + len(tail)
    data = s + b"\0"
    data += b"\0" * (-(off + len(data)) % 8)
    return struct.pack("<III", cmd, off + len(data), off) + tail + data


def dylib_cmd(cmd, path):
    return str_cmd(cmd, path, struct.pack("<III", 2, 0x10000, 0x10000))


def seg64(name, vmaddr, vmsize, fileoff, filesize, prot, sects=()):
    body = struct.pack("<16sQQQQiiII", name, vmaddr, vmsize, fileoff, filesize, prot, prot, len(sects), 0)
    return struct.pack("<II", LC_SEGMENT_64, 8 + len(body) + 80 * len(sects)) + body + b"".join(sects)


def sect64(sectname, segname, addr, size, offset, align, flags):
    return struct.pack("<16s16sQQIIIIIIII", sectname, segname, addr, size, offset, align, 0, 0, flags, 0, 0, 0)


def image(arch, filetype, name, id_path=None, rpaths=(), deps=(), extra=(), extra_sects=0):
    """One thin 64-bit little-endian image. deps: [(kind, path)], extra: raw load commands."""
    cpu, sub = ARCH[arch]
    exe = filetype == MH_EXECUTE
    base = 0x100000000 if exe else 0
    rest = []
    if exe:
        rest.append(str_cmd(LC_LOAD_DYLINKER, b"/usr/lib/dyld"))
    if id_path is not None:
        rest.append(dylib_cmd(LC_ID_DYLIB, id_path))
    rest.append(struct.pack("<II", LC_UUID, 24) + hashlib.sha256(b"uuid:%s:%s" % (name.encode(), arch.encode())).digest()[:16])
    rest.append(struct.pack("<IIIIII", LC_BUILD_VERSION, 24, 1, 0x000B0000, 0x000E0000, 0))
    for kind, path in deps:
        rest.append(dylib_cmd(KIND[kind], path))
    for path in rpaths:
        rest.append(str_cmd(LC_RPATH, path))
    rest.extend(extra)

    nsects = 1 + extra_sects
    sizeofcmds = (72 if exe else 0) + 72 + 80 * nsects + 72 + sum(len(c) for c in rest) + (24 if exe else 0)
    text_off = (32 + sizeofcmds + 15) & ~15
    file_size = text_off + 16
    sects = [sect64(b"__text", b"__TEXT", base + text_off, 4, text_off, 2, 0x80000400)]
    # extra sections all point at the whole slice: used to show section data amplification
    sects += [sect64(b"__amp%04d" % i, b"__TEXT", base, file_size, 0, 0, 0) for i in range(extra_sects)]
    cmds = []
    if exe:
        cmds.append(seg64(b"__PAGEZERO", 0, 0x100000000, 0, 0, 0))
    cmds.append(seg64(b"__TEXT", base, max(0x4000, (file_size + 0x3FFF) & ~0x3FFF), 0, file_size, 5, sects))
    cmds.append(seg64(b"__LINKEDIT", base + max(0x4000, (file_size + 0x3FFF) & ~0x3FFF), 0x4000, file_size, 0, 1))
    cmds += rest
    if exe:
        cmds.append(struct.pack("<IIQQ", LC_MAIN, 24, text_off, 0))
    blob = b"".join(cmds)
    assert len(blob) == sizeofcmds
    hdr = struct.pack("<IIIIIIII", MH_MAGIC_64, cpu, sub, filetype, len(cmds), sizeofcmds, FLAGS[filetype], 0)
    out = hdr + blob
    out += b"\0" * (text_off - len(out))
    out += TEXT[arch] + b"\0" * 12
    assert len(out) == file_size
    return out


def patch_u32(data, off, value):
    return data[:off] + struct.pack("<I", value) + data[off + 4:]


def shrink_sizeofcmds(data):
    # last load command then extends past sizeofcmds: rejected by macholib, llvm and dyld
    return patch_u32(data, 20, struct.unpack_from("<I", data, 20)[0] - 8)


def fat(slices, magic=FAT_MAGIC, align=14, arch_override=None):
    """slices: [(arch, bytes)]. arch_override: {index: arch} written in fat_arch only."""
    step = 1 << align
    entries, payload = [], b""
    off = step
    for i, (arch, data) in enumerate(slices):
        cpu, sub = ARCH[(arch_override or {}).get(i, arch)]
        entries.append((cpu, sub, off, len(data)))
        chunk = data + b"\0" * (-len(data) % step)
        payload += chunk
        off += len(chunk)
    out = struct.pack(">II", magic, len(slices))
    for cpu, sub, o, size in entries:
        if magic == FAT_MAGIC_64:
            out += struct.pack(">IIQQII", cpu, sub, o, size, align, 0)
        else:
            out += struct.pack(">IIIII", cpu, sub, o, size, align)
    out += b"\0" * (step - len(out))
    return out + payload


def dylib(name, arch="arm64", **kw):
    return image(arch, MH_DYLIB, name, **kw)


def exe(name, arch="arm64", **kw):
    return image(arch, MH_EXECUTE, name, **kw)


def parse_fixtures(build_root):
    br = build_root.encode()
    f = {}
    f["t01-thin-arm64-exe"] = exe("t01", rpaths=[b"@executable_path/../lib"], deps=[("load", b"@rpath/libllama.dylib"), ("load", SYS)])
    f["t02-thin-arm64-dylib"] = dylib("t02", id_path=b"@rpath/libggml.dylib", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libggml-base.dylib"), ("weak", CXX)])
    f["t03-thin-x86_64-dylib"] = dylib("t03", arch="x86_64", id_path=b"@rpath/libggml.dylib", deps=[("load", SYS)])
    f["t04-thin-arm64e-dylib"] = dylib("t04", arch="arm64e", id_path=b"@rpath/libe.dylib", deps=[("load", SYS)])
    f["t05-build-rpath-exe"] = exe("t05", rpaths=[br + b"/bin", b"@loader_path"], deps=[("load", b"@rpath/libllama.dylib"), ("load", br + b"/ggml/src/libggml.dylib")])
    f["t06-dyld-environment-exe"] = exe("t06", deps=[("load", SYS)], extra=[str_cmd(LC_DYLD_ENVIRONMENT, b"DYLD_LIBRARY_PATH=" + br + b"/lib")])
    f["t07-undecodable-path"] = dylib("t07", id_path=b"@rpath/libu.dylib", deps=[("load", b"@rpath/lib\xff\xfeggml.dylib")], rpaths=[b"@loader_path/\xc3\x28"])
    f["t08-duplicate-rpath"] = exe("t08", rpaths=[b"@loader_path", b"@loader_path"], deps=[("load", b"@rpath/libllama.dylib")])
    f["t09-all-dependency-kinds"] = exe("t09", rpaths=[b"@loader_path"], deps=[(k, b"@rpath/lib%s.dylib" % k.encode()) for k in ("load", "weak", "reexport", "upward", "lazy")])

    good_x86 = dylib("u", arch="x86_64", id_path=b"@rpath/libu.dylib", deps=[("load", SYS)])
    good_arm = dylib("u", arch="arm64", id_path=b"@rpath/libu.dylib", deps=[("load", SYS)])
    bad_x86 = shrink_sizeofcmds(good_x86)
    bad_arm = shrink_sizeofcmds(good_arm)
    f["u01-fat-x86_64-broken-arm64-ok"] = fat([("x86_64", bad_x86), ("arm64", good_arm)])
    f["u02-fat-x86_64-ok-arm64-broken"] = fat([("x86_64", good_x86), ("arm64", bad_arm)])
    f["u03-fat-per-slice-rpaths"] = fat([
        ("x86_64", dylib("u03", arch="x86_64", id_path=b"@rpath/libu.dylib", rpaths=[br + b"/lib"])),
        ("arm64", dylib("u03", arch="arm64", id_path=b"@rpath/libu.dylib", rpaths=[b"@loader_path"])),
    ])
    f["u04-fat64-ok"] = fat([("x86_64", good_x86), ("arm64", good_arm)], magic=FAT_MAGIC_64)

    good = exe("m", rpaths=[b"@loader_path"], deps=[("load", SYS)])
    f["m01-empty"] = b""
    f["m24-sizeofcmds-slack"] = patch_u32(good, 20, struct.unpack_from("<I", good, 20)[0] + 8)
    f["m02-short-magic"] = b"\xcf\xfa"
    f["m03-truncated-header"] = good[:14]
    f["m04-not-macho-script"] = b"#!/bin/sh\necho must-not-run\nexit 99\n"
    f["m05-sizeofcmds-beyond-eof"] = good[:96]
    f["m06-ncmds-huge"] = patch_u32(good, 16, 0xFFFFFFFF)
    f["m07-cmdsize-zero"] = exe("m07", extra=[struct.pack("<II", LC_RPATH, 0) + b"\0" * 8])
    f["m08-cmdsize-unaligned"] = exe("m08", extra=[struct.pack("<III", LC_RPATH, 20, 12) + b"@lp/abc\0"])
    f["m09-cmdsize-overrun"] = exe("m09", extra=[struct.pack("<III", LC_RPATH, 4096, 12) + b"@loader_path\0\0\0\0"])
    f["m10-lcstr-offset-beyond-cmd"] = exe("m10", extra=[struct.pack("<III", LC_RPATH, 24, 200) + b"@loader_path"])
    f["m11-lcstr-no-nul"] = exe("m11", extra=[struct.pack("<IIIIII", LC_LOAD_DYLIB, 48, 24, 2, 0x10000, 0x10000) + b"@rpath/libnonul-ab.dylib"])
    f["m12-unknown-lc"] = exe("m12", deps=[("load", SYS)], extra=[struct.pack("<II", 0x7E, 16) + b"\0" * 8])
    f["m13-unknown-lc-req-dyld"] = exe("m13", deps=[("load", SYS)], extra=[struct.pack("<II", 0x7E | LC_REQ_DYLD, 16) + b"\0" * 8])
    f["m14-duplicate-id-dylib"] = dylib("m14", id_path=b"@rpath/liba.dylib", extra=[dylib_cmd(LC_ID_DYLIB, b"@rpath/libb.dylib")])
    f["m15-lcstr-offset-into-header"] = exe("m15", extra=[struct.pack("<III", LC_RPATH, 24, 4) + b"@loader_path"])
    f["m16-segment-size-mismatch"] = exe("m16", extra=[struct.pack("<II", LC_SEGMENT_64, 72) + struct.pack("<16sQQQQiiII", b"__DATA", 0, 0, 0, 0, 3, 3, 1, 0)])
    f["m17-section-amplification"] = dylib("m17", id_path=b"@rpath/libamp.dylib", extra_sects=4000)
    f["m18-fat-nfat-huge"] = struct.pack(">II", FAT_MAGIC, 0x10000) + b"\0" * 64
    full = fat([("arm64", good_arm)])
    f["m19-fat-slice-beyond-eof"] = full[: 0x4000 + 64]
    f["m20-fat-overlapping-slices"] = _overlap(good_arm, good_x86)
    f["m21-fat-arch-mismatch"] = fat([("x86_64", good_x86)], arch_override={0: "arm64"})
    f["m22-fat-duplicate-arch"] = fat([("arm64", good_arm), ("arm64", good_arm)])
    f["m23-java-class-magic"] = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\0" * 120
    return f


def _overlap(arm, x86):
    # two fat_arch entries that point at the same bytes
    out = struct.pack(">II", FAT_MAGIC, 2)
    out += struct.pack(">IIIII", *ARCH["arm64"], 0x4000, len(arm), 14)
    out += struct.pack(">IIIII", *ARCH["x86_64"], 0x4000 + 16, len(x86), 14)
    out += b"\0" * (0x4000 - len(out))
    return out + arm + b"\0" * 64


def bundles(build_root):
    """Each bundle: (files {rel: bytes}, links {rel: target}). '_outside' holds decoys beside the bundles."""
    br = build_root.encode()
    b = {}
    b["b01-flat-good"] = ({
        "llama-cli": exe("b01-cli", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libllama.dylib"), ("load", SYS), ("load", b"/System/Library/Frameworks/Metal.framework/Versions/A/Metal"), ("weak", CXX)]),
        "libllama.dylib": dylib("b01-llama", id_path=b"@rpath/libllama.dylib", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libggml.dylib"), ("load", CXX), ("load", SYS)]),
        "libggml.0.dylib": dylib("b01-ggml", id_path=b"@rpath/libggml.dylib", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libggml-base.dylib"), ("load", b"@loader_path/libggml-cpu.dylib"), ("load", SYS)]),
        "libggml-base.dylib": dylib("b01-base", id_path=b"@rpath/libggml-base.dylib", deps=[("load", SYS)]),
        "libggml-cpu.dylib": dylib("b01-cpu", id_path=b"@rpath/libggml-cpu.dylib", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libggml-base.dylib")]),
        "README.txt": b"not a Mach-O file\n",
    }, {"libggml.dylib": b"libggml.0.dylib"})
    b["b02-nested-inherited-rpath"] = ({
        "bin/llama-server": exe("b02-server", rpaths=[b"@executable_path/../lib"], deps=[("load", b"@rpath/libllama.dylib"), ("load", SYS)]),
        "lib/libllama.dylib": dylib("b02-llama", id_path=b"@rpath/libllama.dylib", deps=[("load", b"@rpath/libggml.dylib"), ("load", b"@loader_path/sub/libnested.dylib")]),
        "lib/libggml.dylib": dylib("b02-ggml", id_path=b"@rpath/libggml.dylib", deps=[("load", SYS)]),
        "lib/sub/libnested.dylib": dylib("b02-nested", id_path=b"@rpath/libnested.dylib", deps=[("load", b"@executable_path/../lib/libggml.dylib")]),
        "PlugIns/libggml-metal.so": image("arm64", MH_BUNDLE, "b02-metal", rpaths=[b"@loader_path/../lib"], deps=[("load", b"@rpath/libggml.dylib")]),
    }, {})
    b["b03-build-rpath"] = ({
        "llama-cli": exe("b03-cli", rpaths=[br + b"/bin", b"@loader_path"], deps=[("load", b"@rpath/libllama.dylib"), ("load", SYS)]),
        "libllama.dylib": dylib("b03-llama", id_path=br + b"/src/libllama.dylib", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libggml.dylib"), ("load", br + b"/ggml/src/libggml-base.dylib")]),
        "libggml.dylib": dylib("b03-ggml", id_path=b"@rpath/libggml.dylib", deps=[("load", SYS)]),
        "libggml-base.dylib": dylib("b03-base", id_path=b"@rpath/libggml-base.dylib", deps=[("load", SYS)]),
    }, {})
    b["b04-system-and-external"] = ({
        "app": exe("b04-app", rpaths=[b"@loader_path/lib"], deps=[
            ("load", SYS),
            ("load", b"/System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate"),
            ("load", b"/usr/local/lib/libomp.dylib"),
            ("load", b"/opt/homebrew/opt/libomp/lib/libomp.dylib"),
            ("load", b"libbare.dylib"),
            ("load", b"@foo/libtoken.dylib"),
            ("load", b"@executable_path/lib/libok.dylib"),
            ("load", b"@rpath/libmissing.dylib"),
            ("weak", b"@rpath/libweakmissing.dylib"),
        ]),
        "lib/libok.dylib": dylib("b04-ok", id_path=b"@rpath/libok.dylib", deps=[("load", SYS)]),
    }, {})
    b["b05-cycle"] = ({
        "main": exe("b05-main", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libA.dylib")]),
        "libA.dylib": dylib("b05-a", id_path=b"@rpath/libA.dylib", deps=[("load", b"@loader_path/libB.dylib")]),
        "libB.dylib": dylib("b05-b", id_path=b"@rpath/libB.dylib", deps=[("load", b"@loader_path/libA.dylib")]),
    }, {})
    b["b06-symlinks"] = ({
        "bin/tool": exe("b06-tool", rpaths=[b"@executable_path/../lib"], deps=[
            ("load", b"@rpath/libinternal.dylib"),
            ("load", b"@rpath/libbroken.dylib"),
            ("load", b"@rpath/libescape.dylib"),
            ("load", b"@rpath/libabs.dylib"),
            ("load", b"@rpath/libloop.dylib"),
            ("load", b"@rpath/ext/libescape.dylib"),
        ]),
        "lib/real/libinternal.1.dylib": dylib("b06-internal", id_path=b"@rpath/libinternal.dylib", deps=[("load", SYS)]),
    }, {
        "lib/libinternal.dylib": b"real/libinternal.1.dylib",
        "lib/libbroken.dylib": b"real/libnothere.dylib",
        "lib/libescape.dylib": b"../../_outside/b06-symlinks/libescape.dylib",
        "lib/libabs.dylib": b"/usr/lib/libSystem.B.dylib",
        "lib/libloop.dylib": b"libloop2.dylib",
        "lib/libloop2.dylib": b"libloop.dylib",
        "lib/ext": b"../../_outside/b06-symlinks",
    })
    b["b07-missing-arch"] = ({
        "main": exe("b07-main", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libx86only.dylib"), ("load", b"@rpath/libfat.dylib")]),
        "libx86only.dylib": dylib("b07-x86", arch="x86_64", id_path=b"@rpath/libx86only.dylib"),
        "libfat.dylib": fat([("x86_64", dylib("b07-fat", arch="x86_64", id_path=b"@rpath/libfat.dylib")), ("arm64", dylib("b07-fat", id_path=b"@rpath/libfat.dylib"))]),
    }, {})
    main_x86 = exe("b08-main", arch="x86_64", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libu.dylib")])
    b["b08-universal-broken-slice"] = ({
        "main": fat([("x86_64", shrink_sizeofcmds(main_x86)), ("arm64", exe("b08-main", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/libu.dylib")]))]),
        "libu.dylib": fat([("x86_64", dylib("b08-u", arch="x86_64", id_path=b"@rpath/libu.dylib")), ("arm64", dylib("b08-u", id_path=b"@rpath/libu.dylib"))]),
    }, {})
    b["b09-weak-missing"] = ({
        "main": exe("b09-main", rpaths=[b"@loader_path"], deps=[("load", SYS), ("weak", b"@rpath/libggml-blas.dylib")]),
    }, {})
    b["b10-unknown-lc-dep"] = ({
        "main": exe("b10-main", deps=[("load", b"@loader_path/libunk.dylib")]),
        "libunk.dylib": dylib("b10-unk", id_path=b"@rpath/libunk.dylib", extra=[struct.pack("<II", 0x7E | LC_REQ_DYLD, 16) + b"\0" * 8]),
    }, {})
    b["b11-malformed-dep"] = ({
        "main": exe("b11-main", deps=[("load", b"@loader_path/libtrunc.dylib")]),
        "libtrunc.dylib": dylib("b11-t", id_path=b"@rpath/libtrunc.dylib")[:40],
    }, {})
    b["b12-root-symlink"] = ({
        "real/main": exe("b12-main", deps=[("load", SYS)]),
    }, {"main": b"real/main"})
    b["b13-dotdot-escape"] = ({
        "main": exe("b13-main", deps=[("load", b"@loader_path/../_outside/b13-dotdot-escape/libx.dylib")]),
    }, {})
    b["b14-undecodable-dep"] = ({
        "main": exe("b14-main", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/lib\xff\xfe.dylib")]),
    }, {})
    b["b15-duplicate-rpath"] = ({
        "main": exe("b15-main", rpaths=[b"@loader_path", b"@loader_path"], deps=[("load", b"@rpath/libok.dylib")]),
        "libok.dylib": dylib("b15-ok", id_path=b"@rpath/libok.dylib"),
    }, {})
    b["b16-case-mismatch"] = ({
        "main": exe("b16-main", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/LibGGML.dylib")]),
        "libggml.dylib": dylib("b16-ggml", id_path=b"@rpath/libggml.dylib"),
    }, {})
    b["b17-dependency-is-executable"] = ({
        "main": exe("b17-main", rpaths=[b"@loader_path"], deps=[("load", b"@rpath/helper")]),
        "helper": exe("b17-helper"),
    }, {})
    b["b18-dyld-environment"] = ({
        "main": exe("b18-main", deps=[("load", SYS)], extra=[str_cmd(LC_DYLD_ENVIRONMENT, b"DYLD_LIBRARY_PATH=@executable_path/lib")]),
    }, {})
    kinds = ("load", "weak", "reexport", "upward", "lazy")
    b["b19-dependency-kinds"] = (dict(
        [("main", exe("b19-main", rpaths=[b"@loader_path"], deps=[(k, b"@rpath/lib%s.dylib" % k.encode()) for k in kinds]))]
        + [("lib%s.dylib" % k, dylib("b19-" + k, id_path=b"@rpath/lib%s.dylib" % k.encode(), deps=[("load", SYS)])) for k in kinds]
    ), {})
    b["b20-dependency-kinds-no-lazy"] = (dict(
        [("main", exe("b20-main", rpaths=[b"@loader_path"], deps=[(k, b"@rpath/lib%s.dylib" % k.encode()) for k in kinds[:4]]))]
        + [("lib%s.dylib" % k, dylib("b20-" + k, id_path=b"@rpath/lib%s.dylib" % k.encode(), deps=[("load", SYS)])) for k in kinds[:4]]
    ), {})
    outside = {
        "_outside/b06-symlinks/libescape.dylib": dylib("decoy-escape", id_path=b"@rpath/libescape.dylib"),
        "_outside/b13-dotdot-escape/libx.dylib": dylib("decoy-x", id_path=b"@rpath/libx.dylib"),
        "_decoy-dyld/libllama.dylib": dylib("decoy-llama", id_path=b"@rpath/libllama.dylib"),
        "_decoy-dyld/libggml.dylib": dylib("decoy-ggml", id_path=b"@rpath/libggml.dylib"),
        "_decoy-dyld/libmissing.dylib": dylib("decoy-missing", id_path=b"@rpath/libmissing.dylib"),
    }
    return b, outside


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_tree(out, build_root):
    if os.path.exists(out) and os.listdir(out):
        raise SystemExit("gen_fixtures: refuse to write into non-empty %s" % out)
    entries = []

    def put(rel, data, mode=0o644):
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "xb") as fp:
            fp.write(data)
        os.chmod(path, mode)
        entries.append({"path": rel, "type": "file", "size": len(data), "sha256": sha256(data)})

    def link(rel, target):
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.symlink(target, os.fsencode(path))
        entries.append({"path": rel, "type": "symlink", "target": target.decode("utf-8", "backslashreplace")})

    for name, data in sorted(parse_fixtures(build_root).items()):
        put("parse/%s.bin" % name, data)
    bs, outside = bundles(build_root)
    for bname, (files, links) in sorted(bs.items()):
        for rel, data in sorted(files.items()):
            put("bundles/%s/%s" % (bname, rel), data, 0o755 if data[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") else 0o644)
        for rel, target in sorted(links.items()):
            link("bundles/%s/%s" % (bname, rel), target)
    for rel, data in sorted(outside.items()):
        put("bundles/%s" % rel, data)
    manifest = {
        "generator": "gen_fixtures.py",
        "build_root_literal": build_root,
        "note": "synthetic parse fixtures; not executable; not runtime evidence",
        "entries": sorted(entries, key=lambda e: e["path"]),
    }
    with open(os.path.join(out, "fixtures.json"), "x") as fp:
        json.dump(manifest, fp, indent=2, sort_keys=True)
        fp.write("\n")
    return manifest


def write_tar(src, dst):
    """Deterministic tar of the generated tree (fixed mtime/owner, sorted)."""
    paths = []
    for root, dirs, files in os.walk(src):
        dirs.sort()
        for n in sorted(dirs + files):
            paths.append(os.path.relpath(os.path.join(root, n), src))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in sorted(paths):
            full = os.path.join(src, rel)
            st = os.lstat(full)
            ti = tarfile.TarInfo(rel)
            ti.mtime = 0
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            if os.path.islink(full):
                ti.type, ti.linkname, ti.mode = tarfile.SYMTYPE, os.readlink(full), 0o777
                tar.addfile(ti)
            elif os.path.isdir(full):
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(ti)
            else:
                ti.size, ti.mode = st.st_size, st.st_mode & 0o777
                with open(full, "rb") as fp:
                    tar.addfile(ti, fp)
    with open(dst, "xb") as fp:
        fp.write(buf.getvalue())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", help="output directory (must be new or empty)")
    ap.add_argument("--build-root", default=DEFAULT_BUILD_ROOT, help="literal absolute build root embedded in fixtures")
    ap.add_argument("--tar", help="also write a deterministic tar of the tree")
    args = ap.parse_args(argv)
    m = write_tree(args.out, args.build_root)
    if args.tar:
        write_tar(args.out, args.tar)
    print("gen_fixtures: %d entries in %s" % (len(m["entries"]), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
