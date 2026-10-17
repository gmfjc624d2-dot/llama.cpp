#!/usr/bin/env python3
"""Bounded Mach-O load command validator, JSON inventory and static bundle check (research tool).

Targets are read as data only. The tool never loads, runs, changes or signs a
target, never reads DYLD_* variables, never asks the host dyld or shared cache,
and never opens paths outside the given files or bundle root. A "pass" is a
static claim about load commands only; a runtime test on macOS is still needed.
"""

import argparse
import base64
import hashlib
import json
import os
import stat
import struct
import sys
import traceback
from collections import deque
from io import BytesIO

import macholib
from macholib import mach_o
from macholib.MachO import MachOHeader
from macholib.ptypes import sizeof

SCHEMA = "macho-bundle-inspection/1"
TOOL_VERSION = "0.1.0"

FAT = {0xCAFEBABE: False, 0xCAFEBABF: True}
THIN = {0xFEEDFACE: (">", 32), 0xCEFAEDFE: ("<", 32), 0xFEEDFACF: (">", 64), 0xCFFAEDFE: ("<", 64)}
MAGIC_BYTES = {struct.pack(">I", m) for m in list(FAT) + list(THIN)}

DEP_KINDS = {
    mach_o.LC_LOAD_DYLIB: "load",
    mach_o.LC_LOAD_WEAK_DYLIB: "weak",
    mach_o.LC_REEXPORT_DYLIB: "reexport",
    mach_o.LC_LOAD_UPWARD_DYLIB: "upward",
    mach_o.LC_LAZY_LOAD_DYLIB: "lazy",
}
DYLIB_FILETYPES = {mach_o.MH_DYLIB, mach_o.MH_DYLIB_STUB}
CPU_TYPE_X86_64 = 0x01000007
CPU_TYPE_ARM64 = 0x0100000C

DEFAULT_LIMITS = {
    "max_file_bytes": 512 << 20,
    "max_fat_arch": 32,
    "max_sizeofcmds": 4 << 20,
    "max_ncmds": 65536,
    "max_walk_entries": 50000,
    "max_walk_depth": 64,
    "max_symlink_hops": 32,
    "max_images": 4096,
    "max_edges": 100000,
}

# bundle check: code -> verdict severity
SEVERITY = {
    "MISSING_ARCHITECTURE": "fail",
    "UNRESOLVED": "fail",
    "ABSOLUTE_EXTERNAL": "fail",
    "FORBIDDEN_BUILD_ROOT": "fail",
    "EXTERNAL_CANDIDATE": "fail",
    "PATH_ESCAPE": "fail",
    "SYMLINK_ESCAPE": "fail",
    "SYMLINK_ABSOLUTE": "fail",
    "RPATH_FORBIDDEN_BUILD_ROOT": "fail",
    "RPATH_ABSOLUTE_EXTERNAL": "fail",
    "DEP_WRONG_FILETYPE": "fail",
    "ROOT_MISSING": "fail",
    "SLICE_NOT_COMPLETE": "incomplete",
    "AMBIGUOUS_ARCHITECTURE": "incomplete",
    "UNKNOWN_LOAD_COMMAND": "incomplete",
    "UNSUPPORTED_CONTEXT": "incomplete",
    "RPATH_UNSUPPORTED": "incomplete",
    "RPATH_INHERITED_NOT_MODELLED": "incomplete",
    "RPATH_DUPLICATE": "incomplete",
    "LAZY_LOAD_DYLIB": "incomplete",
    "LOADER_PATH_SYMLINK_DIR": "incomplete",
    "DYLD_ENVIRONMENT": "incomplete",
    "ROOT_IS_SYMLINK": "incomplete",
    "ROOT_NOT_MACHO": "incomplete",
    "ROOT_NOT_EXECUTE": "incomplete",
    "UNREACHABLE_NOT_COMPLETE": "incomplete",
    "LIMIT_EXCEEDED": "incomplete",
    "SYMLINK_BROKEN": "warning",
    "SYMLINK_LOOP": "warning",
    "UNRESOLVED_WEAK": "warning",
    "UNREACHABLE_MACHO": "warning",
    "UNUSED_SLICE_NOT_COMPLETE": "warning",
    "ID_DYLIB_FORBIDDEN_BUILD_ROOT": "warning",
    "OTHER_LC_FORBIDDEN_BUILD_ROOT": "warning",
    "SYSTEM_POLICY_ALLOWED": "info",
    "RPATH_SYSTEM_POLICY": "info",
    "UPWARD_DYLIB": "info",
    "CYCLE": "info",
}


def b64(b):
    return base64.b64encode(b).decode("ascii")


def disp(b):
    return b.decode("utf-8", "backslashreplace")


def bstr(b):
    """Exact bytes as base64 plus display text."""
    try:
        b.decode("utf-8")
        utf8 = True
    except UnicodeDecodeError:
        utf8 = False
    return {"text": disp(b), "b64": b64(b), "utf8": utf8}


def unb(v):
    return base64.b64decode(v["b64"])


def arch_name(cpu, sub):
    s = sub & 0x00FFFFFF
    if cpu == CPU_TYPE_ARM64:
        return {0: "arm64", 2: "arm64e"}.get(s, "arm64:sub%d" % s)
    if cpu == CPU_TYPE_X86_64:
        return {3: "x86_64", 8: "x86_64h"}.get(s, "x86_64:sub%d" % s)
    if cpu == 7:
        return "i386"
    return "cpu0x%08x:sub%d" % (cpu, s)


def lcstr_fields(klass):
    """(field, byte offset in the command) of each lc_str field, from macholib's struct layout."""
    out, pos = [], 8
    for name, typ in klass._fields_:
        if isinstance(typ, type) and issubclass(typ, mach_o.lc_str):
            out.append((name, pos))
        pos += sizeof(typ)
    return out


class Ctx:
    def __init__(self, limits):
        self.limits = limits
        self.limit_hits = []

    def hit(self, name, detail):
        self.limit_hits.append({"limit": name, "value": self.limits[name], "detail": detail})


# ---------------------------------------------------------------- validator


def err(lst, code, detail, severity="malformed", **kw):
    e = {"code": code, "severity": severity, "detail": detail}
    e.update(kw)
    lst.append(e)


def section_reads(raw, end, bits, fixed, nsects, size, errors, i):
    """Bytes macholib would read into memory for section data of one segment."""
    total, so = 0, fixed
    ssz = 80 if bits == 64 else 68
    for _ in range(nsects):
        if bits == 64:
            ssize, soffset = struct.unpack_from(end + "QI", raw, so + 40)
            sflags = struct.unpack_from(end + "I", raw, so + 64)[0]
        else:
            ssize, soffset = struct.unpack_from(end + "II", raw, so + 36)
            sflags = struct.unpack_from(end + "I", raw, so + 56)[0]
        if (sflags & mach_o.S_ZEROFILL) != mach_o.S_ZEROFILL:
            if soffset > size:
                err(errors, "SECTION_BEYOND_SLICE", "section offset %d > slice size %d" % (soffset, size), lc_index=i)
            total += min(ssize, max(0, size - soffset))
        so += ssz
    return total


def scan_commands(buf, off, size, end, bits, ncmds, sizeofcmds, errors):
    hsz = 28 if bits == 32 else 32
    align = 8 if bits == 64 else 4
    segs = {mach_o.LC_SEGMENT: (mach_o.segment_command, 68), mach_o.LC_SEGMENT_64: (mach_o.segment_command_64, 80)}
    cmds, pos, broken, section_bytes, ids = [], hsz, False, 0, 0
    limit = hsz + sizeofcmds
    for i in range(ncmds):
        if pos + 8 > limit:
            err(errors, "CMD_BEYOND_SIZEOFCMDS", "load command %d header is past sizeofcmds" % i, lc_index=i)
            broken = True
            break
        cmd, cmdsize = struct.unpack_from(end + "II", buf, off + pos)
        rec = {"index": i, "offset": pos, "cmd": "0x%08x" % cmd, "name": mach_o.LC_NAMES.get(cmd), "cmdsize": cmdsize,
               "requires_dyld": bool(cmd & mach_o.LC_REQ_DYLD), "known_to_macholib": cmd in mach_o.LC_REGISTRY}
        cmds.append(rec)
        if cmdsize < 8:
            err(errors, "CMDSIZE_TOO_SMALL", "cmdsize %d < 8" % cmdsize, lc_index=i)
            broken = True
            break
        if pos + cmdsize > limit:
            err(errors, "CMD_BEYOND_SIZEOFCMDS", "load command %d ends at %d, sizeofcmds ends at %d" % (i, pos + cmdsize, limit), lc_index=i)
            broken = True
            break
        raw = buf[off + pos: off + pos + cmdsize]
        rec["raw_b64"] = b64(raw)
        pos += cmdsize
        if cmdsize % align:
            err(errors, "CMDSIZE_UNALIGNED", "cmdsize %d not a multiple of %d" % (cmdsize, align), lc_index=i)
        klass = mach_o.LC_REGISTRY.get(cmd)
        if klass is None:
            err(errors, "UNKNOWN_LOAD_COMMAND", "cmd 0x%08x not in macholib LC_REGISTRY" % cmd, "incomplete", lc_index=i)
            continue
        fixed = 8 + sizeof(klass)
        if cmdsize < fixed:
            err(errors, "CMDSIZE_SMALLER_THAN_STRUCT", "cmdsize %d < %d for %s" % (cmdsize, fixed, rec["name"]), lc_index=i)
            continue
        strings = []
        for field, fpos in lcstr_fields(klass):
            soff = struct.unpack_from(end + "I", raw, fpos)[0]
            if not (fixed <= soff < cmdsize):
                err(errors, "LCSTR_OFFSET_INVALID", "%s.offset %d outside [%d, %d)" % (field, soff, fixed, cmdsize), lc_index=i)
                continue
            nul = raw.find(b"\0", soff)
            if nul < 0:
                err(errors, "LCSTR_NOT_TERMINATED", "%s has no NUL before the end of the command" % field, lc_index=i)
            s = {"field": field, "offset": soff, "nul_terminated": nul >= 0}
            s.update(bstr(raw[soff:] if nul < 0 else raw[soff:nul]))
            strings.append(s)
        if strings:
            rec["strings"] = strings
        if cmd in segs:
            scls, ssz = segs[cmd]
            nsects = struct.unpack_from(end + "I", raw, sizeof(scls))[0]
            if cmdsize != fixed + nsects * ssz:
                err(errors, "SEGMENT_SIZE_MISMATCH", "cmdsize %d, nsects %d" % (cmdsize, nsects), lc_index=i)
            else:
                section_bytes += section_reads(raw, end, bits, fixed, nsects, size, errors, i)
        if cmd in DEP_KINDS or cmd == mach_o.LC_ID_DYLIB:
            ts, cur, compat = struct.unpack_from(end + "III", raw, 12)
            rec["dylib"] = {"timestamp": ts, "current_version": cur, "compatibility_version": compat}
        ids += cmd == mach_o.LC_ID_DYLIB
    if not broken and pos != limit:
        err(errors, "SIZEOFCMDS_SLACK", "load commands end at %d, sizeofcmds ends at %d" % (pos, limit), "incomplete")
    if ids > 1:
        err(errors, "DUPLICATE_ID_DYLIB", "%d LC_ID_DYLIB commands" % ids)
    if section_bytes > size:
        err(errors, "SECTION_DATA_AMPLIFICATION", "sections would read %d bytes from a %d byte slice" % (section_bytes, size))
    return cmds


def macholib_crosscheck(buf, off, size, magic, bits, end, cmds):
    """Parse the same slice with macholib and compare. Only run after the validator passed."""
    hdr = mach_o.mach_header if bits == 32 else mach_o.mach_header_64

    class Parent:
        filename = "<memory>"

    try:
        h = MachOHeader(Parent(), BytesIO(buf), off, size, magic, hdr, end, allow_unknown_load_commands=True)
    except Exception as e:
        return {"status": "error", "error": "%s: %s" % (type(e).__name__, str(e)[:300])}
    diffs = []
    if len(h.commands) != len(cmds):
        diffs.append("command count %d != %d" % (len(h.commands), len(cmds)))
    for (lc, c, _d), rec in zip(h.commands, cmds):
        if "0x%08x" % lc.cmd != rec["cmd"] or lc.cmdsize != rec["cmdsize"]:
            diffs.append("lc %d: cmd/cmdsize differ" % rec["index"])
        for s in rec.get("strings", []):
            if int(getattr(c, s["field"])) != s["offset"]:
                diffs.append("lc %d: %s offset differs" % (rec["index"], s["field"]))
    out = {"status": "agree" if not diffs else "disagree"}
    if diffs:
        out["diffs"] = diffs
    return out


def scan_slice(buf, off, size, ctx):
    sl = {"offset": off, "size": size, "errors": []}
    errors = sl["errors"]
    magic = struct.unpack_from(">I", buf, off)[0] if size >= 4 else None
    if magic not in THIN:
        err(errors, "BAD_MAGIC" if magic is not None else "TRUNCATED_HEADER", "magic %s" % (None if magic is None else "0x%08x" % magic))
        sl["status"] = "malformed"
        return sl
    end, bits = THIN[magic]
    hsz = 28 if bits == 32 else 32
    if size < hsz:
        err(errors, "TRUNCATED_HEADER", "slice has %d bytes, header needs %d" % (size, hsz))
        sl["status"] = "malformed"
        return sl
    m, cpu, sub, ftype, ncmds, sizeofcmds, flags = struct.unpack_from(end + "7I", buf, off)
    sl.update({"magic": "0x%08x" % m, "bits": bits, "endian": "big" if end == ">" else "little", "cputype": cpu,
               "cpusubtype": sub, "arch": arch_name(cpu, sub), "filetype": ftype,
               "filetype_name": mach_o.MH_FILETYPE_SHORTNAMES.get(ftype, "unknown"), "ncmds": ncmds,
               "sizeofcmds": sizeofcmds, "flags": "0x%08x" % flags})
    lim = ctx.limits
    if sizeofcmds > size - hsz:
        err(errors, "LOAD_COMMANDS_BEYOND_SLICE", "sizeofcmds %d > %d" % (sizeofcmds, size - hsz))
    elif ncmds * 8 > sizeofcmds:
        err(errors, "NCMDS_EXCEEDS_SIZEOFCMDS", "ncmds %d cannot fit in %d bytes" % (ncmds, sizeofcmds))
    elif sizeofcmds > lim["max_sizeofcmds"] or ncmds > lim["max_ncmds"]:
        name = "max_sizeofcmds" if sizeofcmds > lim["max_sizeofcmds"] else "max_ncmds"
        ctx.hit(name, "slice at offset %d" % off)
        err(errors, "LIMIT_EXCEEDED", "%s exceeded" % name, "incomplete")
    else:
        sl["load_commands"] = scan_commands(buf, off, size, end, bits, ncmds, sizeofcmds, errors)
    if any(e["severity"] == "malformed" for e in errors):
        sl["status"] = "malformed"
        sl["macholib"] = {"status": "not_run", "reason": "validator found malformed structure"}
    elif "load_commands" not in sl:
        sl["status"] = "incomplete"
        sl["macholib"] = {"status": "not_run", "reason": "limit exceeded"}
    else:
        sl["macholib"] = macholib_crosscheck(buf, off, size, magic, bits, end, sl["load_commands"])
        sl["status"] = "complete" if not errors and sl["macholib"]["status"] == "agree" else "incomplete"
    if "load_commands" in sl:
        summarize_slice(sl)
    return sl


def summarize_slice(sl):
    sl["rpaths"], sl["dependencies"], sl["id_dylib"], sl["dyld_environment"] = [], [], None, []
    for rec in sl["load_commands"]:
        strs = rec.get("strings")
        if not strs:
            continue
        cmd = int(rec["cmd"], 16)
        val = {"lc_index": rec["index"], "text": strs[0]["text"], "b64": strs[0]["b64"]}
        if cmd == mach_o.LC_RPATH:
            sl["rpaths"].append(val)
        elif cmd in DEP_KINDS:
            val.update({"kind": DEP_KINDS[cmd], "command": rec["name"]})
            sl["dependencies"].append(val)
        elif cmd == mach_o.LC_ID_DYLIB:
            sl["id_dylib"] = val
        elif cmd == mach_o.LC_DYLD_ENVIRONMENT:
            sl["dyld_environment"].append(val)
    sl["unknown_load_commands"] = [r["index"] for r in sl["load_commands"] if not r["known_to_macholib"]]


def scan_fat(buf, ctx):
    magic, n = struct.unpack_from(">II", buf, 0) if len(buf) >= 8 else (struct.unpack_from(">I", buf, 0)[0], None)
    fat = {"magic": "0x%08x" % magic, "nfat_arch": n, "errors": []}
    if n is None:
        err(fat["errors"], "TRUNCATED_HEADER", "fat header needs 8 bytes")
        return fat, []
    if n == 0:
        err(fat["errors"], "FAT_NO_ARCHS", "nfat_arch is 0")
        return fat, []
    if n > ctx.limits["max_fat_arch"]:
        ctx.hit("max_fat_arch", "nfat_arch %d" % n)
        err(fat["errors"], "FAT_TOO_MANY_ARCHS", "nfat_arch %d over limit (Java class files share this magic)" % n)
        return fat, []
    esz = 32 if FAT[magic] else 20
    table_end = 8 + n * esz
    if table_end > len(buf):
        err(fat["errors"], "FAT_TABLE_BEYOND_EOF", "fat_arch table ends at %d, file has %d bytes" % (table_end, len(buf)))
        return fat, []
    archs = []
    for i in range(n):
        if FAT[magic]:
            cpu, sub, off, size, align, _r = struct.unpack_from(">IIQQII", buf, 8 + i * esz)
        else:
            cpu, sub, off, size, align = struct.unpack_from(">IIIII", buf, 8 + i * esz)
        archs.append({"index": i, "cputype": cpu, "cpusubtype": sub, "arch": arch_name(cpu, sub), "offset": off, "size": size, "align": align})
    slices = []
    for a in archs:
        e = []
        if a["offset"] < table_end:
            err(e, "SLICE_OVERLAPS_FAT_HEADER", "offset %d < %d" % (a["offset"], table_end))
        if a["offset"] + a["size"] > len(buf):
            err(e, "SLICE_BEYOND_EOF", "slice ends at %d, file has %d bytes" % (a["offset"] + a["size"], len(buf)))
        if a["align"] > 15 or a["offset"] % (1 << a["align"]):
            err(e, "SLICE_MISALIGNED", "offset %d, align 2^%d" % (a["offset"], a["align"]))
        for b in archs:
            if b is not a and a["offset"] < b["offset"] + b["size"] and b["offset"] < a["offset"] + a["size"]:
                err(e, "SLICES_OVERLAP", "overlaps fat_arch %d" % b["index"])
            if b is not a and (a["cputype"], a["cpusubtype"] & 0x00FFFFFF) == (b["cputype"], b["cpusubtype"] & 0x00FFFFFF):
                err(e, "FAT_DUPLICATE_ARCH", "same arch as fat_arch %d" % b["index"])
        if e:
            sl = {"offset": a["offset"], "size": a["size"], "errors": e, "status": "malformed"}
        else:
            sl = scan_slice(buf, a["offset"], a["size"], ctx)
            if "cputype" in sl and (sl["cputype"], sl["cpusubtype"]) != (a["cputype"], a["cpusubtype"]):
                err(sl["errors"], "FAT_ARCH_MISMATCH", "fat_arch says %s, header says %s" % (a["arch"], sl["arch"]))
                sl["status"] = "malformed"
        sl["index"], sl["fat_arch"] = a["index"], a
        slices.append(sl)
    return fat, slices


def open_regular(path):
    """Never follow a final symlink, never block on a FIFO."""
    return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))


def read_regular(path, ctx):
    fd = open_regular(path)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "not a regular file", st.st_size
        if st.st_size > ctx.limits["max_file_bytes"]:
            ctx.hit("max_file_bytes", "file of %d bytes" % st.st_size)
            return None, "limit max_file_bytes exceeded, not read", st.st_size
        chunks, left = [], st.st_size
        while left > 0:
            c = os.read(fd, min(left, 1 << 20))
            if not c:
                break
            chunks.append(c)
            left -= len(c)
        return b"".join(chunks), None, st.st_size
    finally:
        os.close(fd)


def scan_file(path, display, ctx):
    rec = {"path": bstr(display)}
    try:
        buf, why, size = read_regular(path, ctx)
    except OSError as e:
        rec.update({"status": "error", "error": "%s: %s" % (type(e).__name__, e.strerror)})
        return rec
    rec["size"] = size
    if buf is None:
        rec.update({"status": "incomplete", "container": None, "error": why})
        return rec
    rec.update({"sha256": hashlib.sha256(buf).hexdigest(), "fat": None, "slices": []})
    magic = struct.unpack_from(">I", buf, 0)[0] if len(buf) >= 4 else None
    if magic in FAT:
        rec["container"] = "fat64" if FAT[magic] else "fat"
        rec["fat"], rec["slices"] = scan_fat(buf, ctx)
    elif magic in THIN:
        rec["container"] = "thin"
        sl = scan_slice(buf, 0, len(buf), ctx)
        sl["index"], sl["fat_arch"] = 0, None
        rec["slices"] = [sl]
    else:
        rec.update({"container": "not_macho", "status": "not_macho"})
        return rec
    good = [s for s in rec["slices"] if s["status"] == "complete"]
    if rec["fat"] and rec["fat"]["errors"]:
        rec["status"] = "malformed"
    elif len(good) == len(rec["slices"]):
        rec["status"] = "complete"
    elif good:
        rec["status"] = "partial"
    elif any(s["status"] == "incomplete" for s in rec["slices"]):
        rec["status"] = "incomplete"
    else:
        rec["status"] = "malformed"
    return rec


# ---------------------------------------------------------------- bundle check


def walk_bundle(root, ctx):
    """Inventory of the tree under root. Symlinks are data here and are never followed."""
    entries, stack, count = {}, [(b"", 0)], 0
    while stack:
        rel, depth = stack.pop()
        try:
            with os.scandir(root + b"/" + rel if rel else root) as it:
                items = sorted(it, key=lambda e: e.name)
        except OSError as e:
            entries.setdefault(rel, {"type": "dir"})["error"] = "%s: %s" % (type(e).__name__, e.strerror)
            continue
        for e in items:
            count += 1
            if count > ctx.limits["max_walk_entries"]:
                ctx.hit("max_walk_entries", "walk stopped")
                return entries, False
            r = rel + b"/" + e.name if rel else e.name
            st = e.stat(follow_symlinks=False)
            ent = {"type": "other", "mode": "0o%o" % stat.S_IMODE(st.st_mode)}
            if stat.S_ISDIR(st.st_mode):
                ent["type"] = "dir"
                if depth + 1 >= ctx.limits["max_walk_depth"]:
                    ctx.hit("max_walk_depth", disp(r))
                    return entries, False
                stack.append((r, depth + 1))
            elif stat.S_ISLNK(st.st_mode):
                ent.update({"type": "symlink", "target": os.readlink(root + b"/" + r)})
            elif stat.S_ISREG(st.st_mode):
                ent.update({"type": "file", "size": st.st_size})
            entries[r] = ent
    return entries, True


def resolve(root, parts, ctx):
    """Resolve bundle-relative components physically, reading symlinks as data.

    Only paths without a symlink component are lstat()ed, so nothing outside root is touched.
    """
    stack, queue, links = [], deque((c, False) for c in parts), []

    def out(status, **kw):
        r = {"status": status, "links": [{"link": bstr(a), "target": bstr(t)} for a, t in links]}
        r.update(kw)
        return r

    while queue:
        c, from_link = queue.popleft()
        if c in (b"", b"."):
            continue
        if c == b"..":
            if not stack:
                return out("symlink_escape" if from_link else "path_escape")
            stack.pop()
            continue
        full = root + b"/" + b"/".join(stack + [c])
        try:
            st = os.lstat(full)
        except (FileNotFoundError, NotADirectoryError):
            return out("symlink_broken" if from_link else "missing")
        if stat.S_ISLNK(st.st_mode):
            if len(links) >= ctx.limits["max_symlink_hops"]:
                return out("symlink_loop")
            t = os.readlink(full)
            links.append((b"/".join(stack + [c]), t))
            if t.startswith(b"/"):
                return out("symlink_absolute")
            queue.extendleft(reversed([(x, True) for x in t.split(b"/")]))
            continue
        if queue and not stat.S_ISDIR(st.st_mode):
            return out("symlink_broken" if from_link else "missing")
        stack.append(c)
    if not stack or not stat.S_ISREG(os.lstat(root + b"/" + b"/".join(stack)).st_mode):
        return out("not_regular_file")
    return out("ok", rel=b"/".join(stack))


def dirparts(rel):
    return rel.split(b"/")[:-1]


def under(path, roots):
    return any(path == r or path.startswith(r.rstrip(b"/") + b"/") for r in roots)


def aliases(roots):
    """macOS /tmp and /var are symlinks into /private; forbid both spellings."""
    out = set()
    for r in roots:
        out.add(r)
        for a, b in ((b"/tmp/", b"/private/tmp/"), (b"/var/", b"/private/var/")):
            if r.startswith(a):
                out.add(b + r[len(a):])
            elif r.startswith(b):
                out.add(a + r[len(b):])
    return sorted(out)


def is_token(p, tok):
    return p == tok or p.startswith(tok + b"/")


def lexical(parts):
    out = []
    for x in parts:
        if x == b"..":
            out = out[:-1]
        elif x not in (b"", b"."):
            out.append(x)
    return out


def uses_loader_path(sl):
    return any(is_token(unb(v), b"@loader_path") for v in sl.get("rpaths", []) + sl.get("dependencies", []))


class Checker:
    def __init__(self, root, root_exe, archs, forbid, system, extra_roots, ctx):
        self.root, self.root_exe, self.archs = root, root_exe, archs
        self.forbid, self.system, self.extra_roots, self.ctx = forbid, system, extra_roots, ctx
        self.roots = {root_exe} | set(extra_roots)
        self.findings, self.edges, self.files, self._seen = [], [], {}, set()

    def find(self, code, path=None, arch=None, lc_index=None, detail=""):
        key = (code, path, arch, lc_index, detail)
        if key not in self._seen:
            self._seen.add(key)
            self.findings.append({"code": code, "severity": SEVERITY[code], "path": None if path is None else bstr(path),
                                  "arch": arch, "lc_index": lc_index, "detail": detail})

    def classify_abs(self, p):
        if under(p, self.forbid):
            return "forbidden_build_root"
        if under(p, self.system):
            return "system_policy"
        return "absolute_external"

    def file(self, rel):
        if rel not in self.files:
            self.files[rel] = scan_file(self.root + b"/" + rel, rel, self.ctx)
        return self.files[rel]

    def select(self, rec, arch):
        slices = rec.get("slices", [])
        named = [s for s in slices if (s.get("fat_arch") or s).get("arch") == arch or s.get("arch") == arch]
        if not named:
            return None, "missing"
        if len(named) > 1:
            return None, "ambiguous"
        return named[0], None

    def literal_checks(self, rel, sl, arch):
        seen = set()
        for r in sl["rpaths"]:
            p = unb(r)
            if p in seen:
                self.find("RPATH_DUPLICATE", rel, arch, r["lc_index"], disp(p))
            seen.add(p)
            if p.startswith(b"/"):
                k = self.classify_abs(p)
                code = {"forbidden_build_root": "RPATH_FORBIDDEN_BUILD_ROOT", "system_policy": "RPATH_SYSTEM_POLICY"}.get(k, "RPATH_ABSOLUTE_EXTERNAL")
                self.find(code, rel, arch, r["lc_index"], disp(p))
            elif not (is_token(p, b"@loader_path") or is_token(p, b"@executable_path")):
                self.find("RPATH_UNSUPPORTED", rel, arch, r["lc_index"], "cwd-relative or unknown token: " + disp(p))
        for d in sl["dependencies"]:
            p = unb(d)
            if p.startswith(b"/"):
                k = self.classify_abs(p)
                if k != "system_policy":
                    self.find("FORBIDDEN_BUILD_ROOT" if k == "forbidden_build_root" else "ABSOLUTE_EXTERNAL", rel, arch, d["lc_index"], disp(p))
        for rec in sl["load_commands"]:
            cmd = int(rec["cmd"], 16)
            if cmd in DEP_KINDS or cmd == mach_o.LC_RPATH:
                continue
            for s in rec.get("strings", []):
                if any(f in unb(s) for f in self.forbid):
                    code = "ID_DYLIB_FORBIDDEN_BUILD_ROOT" if cmd == mach_o.LC_ID_DYLIB else "OTHER_LC_FORBIDDEN_BUILD_ROOT"
                    self.find(code, rel, arch, rec["index"], "%s: %s" % (rec["name"], s["text"]))
        for i in sl["unknown_load_commands"]:
            self.find("UNKNOWN_LOAD_COMMAND", rel, arch, i, sl["load_commands"][i]["cmd"])
        if sl["dyld_environment"]:
            v = sl["dyld_environment"][0]
            self.find("DYLD_ENVIRONMENT", rel, arch, v["lc_index"], v["text"])

    def candidates(self, rel, lit, own):
        """Candidates in dyld order, limited to this image's own context."""
        if lit.startswith(b"@rpath/"):
            tail = lit[len(b"@rpath/"):].split(b"/")
            out = []
            for rp, idx in own:
                c = {"via": "own_rpath", "rpath_lc_index": idx, "rpath": bstr(rp)}
                if is_token(rp, b"@loader_path"):
                    c.update({"class": "in_bundle", "parts": dirparts(rel) + rp[len(b"@loader_path"):].split(b"/") + tail})
                elif is_token(rp, b"@executable_path"):
                    c.update({"class": "in_bundle", "parts": dirparts(self.root_exe) + rp[len(b"@executable_path"):].split(b"/") + tail})
                elif rp.startswith(b"/"):
                    c.update({"class": self.classify_abs(rp), "literal": bstr(rp.rstrip(b"/") + b"/" + b"/".join(tail))})
                else:
                    c.update({"class": "unsupported", "literal": bstr(rp)})
                out.append(c)
            return out
        if lit.startswith(b"@loader_path/"):
            return [{"via": "loader_path", "class": "in_bundle", "parts": dirparts(rel) + lit[len(b"@loader_path/"):].split(b"/")}]
        if lit.startswith(b"@executable_path/"):
            return [{"via": "executable_path", "class": "in_bundle", "parts": dirparts(self.root_exe) + lit[len(b"@executable_path/"):].split(b"/")}]
        if lit.startswith(b"/"):
            return [{"via": "absolute", "class": self.classify_abs(lit), "literal": bstr(lit)}]
        return [{"via": "unknown_token" if lit.startswith(b"@") else "cwd_relative", "class": "unsupported", "literal": bstr(lit)}]

    def edge(self, rel, arch, dep, own):
        lit = unb(dep)
        e = {"from": bstr(rel), "arch": arch, "lc_index": dep["lc_index"], "kind": dep["kind"], "command": dep["command"],
             "literal": bstr(lit), "candidates": [], "status": None, "target": None}
        loc = (rel, arch, dep["lc_index"])
        if dep["kind"] == "lazy":
            self.find("LAZY_LOAD_DYLIB", *loc, detail="LC_LAZY_LOAD_DYLIB semantics not modelled; inventory and path checks only")
        elif dep["kind"] == "upward":
            self.find("UPWARD_DYLIB", *loc, detail="path resolved like LC_LOAD_DYLIB; init order not modelled")
        missing_arch, unsupported, external = False, False, False
        for c in self.candidates(rel, lit, own):
            e["candidates"].append(c)
            if c["class"] == "in_bundle":
                parts = c.pop("parts")
                c["path"] = bstr(b"/".join(parts))
                r = resolve(self.root, parts, self.ctx)
                c["result"] = r["status"]
                if r["links"]:
                    c["links"] = r["links"]
                if r["status"] == "ok":
                    tgt = r["rel"]
                    c["resolved"] = bstr(tgt)
                    trec = self.file(tgt)
                    if trec.get("container") in (None, "not_macho"):
                        c["result"] = "not_macho" if trec.get("container") else "not_read"
                        continue
                    tsl, why = self.select(trec, arch)
                    if tsl is None and why == "missing":
                        c["result"] = "missing_architecture"
                        missing_arch = True
                        continue
                    if r["links"] and tsl is not None and uses_loader_path(tsl) and dirparts(tgt) != lexical(parts)[:-1]:
                        self.find("LOADER_PATH_SYMLINK_DIR", tgt, arch, detail="reached via %s; its @loader_path behind a directory symlink is ambiguous" % c["path"]["text"])
                    if tsl is not None and tsl.get("filetype") is not None and tsl["filetype"] not in DYLIB_FILETYPES:
                        self.find("DEP_WRONG_FILETYPE", *loc, detail="%s is %s" % (disp(tgt), tsl.get("filetype_name")))
                    e.update({"status": "in_bundle", "target": bstr(tgt)})
                    return e, tgt
                code = {"path_escape": "PATH_ESCAPE", "symlink_escape": "SYMLINK_ESCAPE", "symlink_absolute": "SYMLINK_ABSOLUTE",
                        "symlink_broken": "SYMLINK_BROKEN", "symlink_loop": "SYMLINK_LOOP"}.get(r["status"])
                if code:
                    self.find(code, *loc, detail="%s -> %s" % (disp(lit), c["path"]["text"]))
            elif c["class"] == "system_policy":
                e["status"] = "system_policy_allowed"
                self.find("SYSTEM_POLICY_ALLOWED", *loc, detail=c["literal"]["text"])
                return e, None
            elif c["class"] in ("forbidden_build_root", "absolute_external"):
                external = True
                code = "FORBIDDEN_BUILD_ROOT" if c["class"] == "forbidden_build_root" else ("ABSOLUTE_EXTERNAL" if c["via"] == "absolute" else "EXTERNAL_CANDIDATE")
                self.find(code, *loc, detail=c["literal"]["text"])
            else:
                unsupported = True
                self.find("UNSUPPORTED_CONTEXT", *loc, detail="%s: %s" % (c["via"], c["literal"]["text"]))
        weak = dep["kind"] == "weak"
        if missing_arch:
            e["status"] = "missing_architecture"
            self.find("MISSING_ARCHITECTURE", *loc, detail=disp(lit))
        elif unsupported:
            e["status"] = "unsupported_context"
        elif lit.startswith(b"@rpath/") and rel not in self.roots:
            # dyld would go on with the LC_RPATHs of the images that loaded this one
            e["status"] = "unsupported_context"
            self.find("RPATH_INHERITED_NOT_MODELLED", *loc, detail="%s not found via own LC_RPATH; inherited LC_RPATH not modelled" % disp(lit))
        elif external and not any(c["class"] == "in_bundle" for c in e["candidates"]):
            e["status"] = "external"
        else:
            e["status"] = "unresolved_weak" if weak else "unresolved"
            self.find("UNRESOLVED_WEAK" if weak else "UNRESOLVED", *loc, detail=disp(lit))
        return e, None

    def run(self):
        ctx = self.ctx
        self.inventory, complete_walk = walk_bundle(self.root, ctx)
        queue, visited, edges = deque(), set(), 0
        for r in [self.root_exe] + self.extra_roots:
            ent = self.inventory.get(r)
            if ent is None:
                self.find("ROOT_MISSING", r, detail="not in the bundle inventory")
                continue
            if ent["type"] == "symlink":
                self.find("ROOT_IS_SYMLINK", r, detail="give the real file; @executable_path of a symlinked root is ambiguous")
                continue
            if self.file(r).get("container") in (None, "not_macho"):
                self.find("ROOT_NOT_MACHO", r)
                continue
            for arch in self.archs:
                queue.append((r, arch, ()))
        while queue:
            rel, arch, ancestry = queue.popleft()
            if (rel, arch) in visited:
                continue
            if len(visited) >= ctx.limits["max_images"]:
                ctx.hit("max_images", "traversal stopped")
                break
            visited.add((rel, arch))
            rec = self.file(rel)
            sl, why = self.select(rec, arch)
            if sl is None:
                self.find("MISSING_ARCHITECTURE" if why == "missing" else "AMBIGUOUS_ARCHITECTURE", rel, arch, detail="file status %s" % rec.get("status"))
                continue
            if sl["status"] != "complete":
                self.find("SLICE_NOT_COMPLETE", rel, arch, detail="slice status %s: %s" % (sl["status"], ", ".join(e["code"] for e in sl["errors"])))
                continue
            if rel == self.root_exe and sl["filetype"] != mach_o.MH_EXECUTE:
                self.find("ROOT_NOT_EXECUTE", rel, arch, detail="filetype %s" % sl["filetype_name"])
            self.literal_checks(rel, sl, arch)
            own = [(unb(r), r["lc_index"]) for r in sl["rpaths"]]
            for dep in sl["dependencies"]:
                edges += 1
                if edges > ctx.limits["max_edges"]:
                    ctx.hit("max_edges", "traversal stopped")
                    queue.clear()
                    break
                e, tgt = self.edge(rel, arch, dep, own)
                self.edges.append(e)
                if tgt is None:
                    continue
                if tgt == rel or tgt in ancestry:
                    self.find("CYCLE", rel, arch, dep["lc_index"], "back to " + disp(tgt))
                else:
                    queue.append((tgt, arch, ancestry + (rel,)))
        self.unreachable(visited)
        return complete_walk

    def unreachable(self, visited):
        seen = {r for r, _a in visited}
        for rel, ent in sorted(self.inventory.items()):
            if ent["type"] != "file" or rel in seen:
                continue
            try:
                fd = open_regular(self.root + b"/" + rel)
                try:
                    head = os.read(fd, 4)
                finally:
                    os.close(fd)
            except OSError:
                continue
            if head not in MAGIC_BYTES:
                continue
            rec = self.file(rel)
            self.find("UNREACHABLE_MACHO", rel, detail="not reached from the given roots; pass --extra-root if it is dlopen()ed")
            if rec["status"] != "complete":
                self.find("UNREACHABLE_NOT_COMPLETE", rel, detail="file status %s" % rec["status"])
            for sl in rec.get("slices", []):
                if sl["status"] == "complete":
                    self.literal_checks(rel, sl, sl["arch"])
        for rel in sorted(seen):
            for sl in self.files[rel].get("slices", []):
                a = (sl.get("fat_arch") or sl).get("arch")
                if sl["status"] != "complete" and a not in self.archs:
                    self.find("UNUSED_SLICE_NOT_COMPLETE", rel, a, detail="slice status %s" % sl["status"])


def verdict(findings):
    sev = {"fail": set(), "incomplete": set(), "warning": set(), "info": set()}
    for f in findings:
        sev[f["severity"]].add(f["code"])
    return {
        "status": "fail" if sev["fail"] else ("incomplete" if sev["incomplete"] else "pass"),
        "fail_codes": sorted(sev["fail"]),
        "incomplete_codes": sorted(sev["incomplete"]),
        "warning_codes": sorted(sev["warning"]),
        "info_codes": sorted(sev["info"]),
        "static_only": True,
        "runtime_qualified": False,
        "statement": "Static load command inspection only. It does not prove that dyld loads this bundle; run the separate relocated runtime test on macOS.",
    }


def tool_info(ctx):
    return {"name": "macho_bundle_inspect", "version": TOOL_VERSION, "macholib": macholib.__version__,
            "python": "%d.%d.%d" % sys.version_info[:3], "limits": ctx.limits}


def bundle_rel(p):
    parts = [x for x in os.fsencode(p).split(b"/") if x not in (b"", b".")]
    if b".." in parts:
        raise ValueError("path must stay inside the bundle: %r" % p)
    return b"/".join(parts)


def cmd_inspect(args, ctx):
    files = []
    for p in args.files:
        pb = os.fsencode(p)
        try:
            st = os.lstat(pb)
        except OSError as e:
            files.append({"path": bstr(pb), "status": "error", "error": "%s: %s" % (type(e).__name__, e.strerror)})
            continue
        if stat.S_ISLNK(st.st_mode):
            files.append({"path": bstr(pb), "status": "symlink", "target": bstr(os.readlink(pb))})
            continue
        files.append(scan_file(pb, pb, ctx))
    ok = all(f.get("status") in ("complete", "not_macho") for f in files) and not ctx.limit_hits
    return {"schema": SCHEMA, "mode": "inspect", "tool": tool_info(ctx), "files": files, "limit_hits": ctx.limit_hits,
            "inventory_status": "complete" if ok else "incomplete"}, (0 if ok else 3)


def cmd_check(args, ctx):
    root = os.path.realpath(os.fsencode(args.bundle_root))
    forbid = aliases([os.fsencode(f) for f in args.forbid_root])
    system = [os.fsencode(s) for s in (args.system_prefix or ["/usr/lib/", "/System/Library/"])]
    ck = Checker(root, bundle_rel(args.root_executable), args.require_arch, forbid, system, [bundle_rel(r) for r in args.extra_root], ctx)
    if not ck.run():
        ck.find("LIMIT_EXCEEDED", detail="bundle walk stopped early")
    for h in ctx.limit_hits:
        ck.find("LIMIT_EXCEEDED", detail="%s: %s" % (h["limit"], h["detail"]))
    inv = [dict({"path": bstr(r)}, **{k: (bstr(x) if isinstance(x, bytes) else x) for k, x in e.items()}) for r, e in sorted(ck.inventory.items())]
    findings = sorted(ck.findings, key=lambda f: (f["severity"], f["code"], f["path"]["b64"] if f["path"] else "", f["arch"] or "",
                                                  -1 if f["lc_index"] is None else f["lc_index"], f["detail"]))
    v = verdict(findings)
    out = {
        "schema": SCHEMA,
        "mode": "check",
        "tool": tool_info(ctx),
        "inputs": {
            "root_executable": bstr(ck.root_exe),
            "extra_roots": [bstr(r) for r in ck.extra_roots],
            "required_archs": args.require_arch,
            "forbidden_build_roots": [bstr(f) for f in forbid],
            "system_policy_prefixes": [bstr(s) for s in system],
            "host_environment_consulted": False,
            "modelled_contexts": ["own LC_RPATH", "@loader_path", "@executable_path", "absolute path classification"],
        },
        "inventory": inv,
        "files": [ck.files[r] for r in sorted(ck.files)],
        "edges": ck.edges,
        "findings": findings,
        "limit_hits": ctx.limit_hits,
        "verdict": v,
    }
    return out, {"pass": 0, "fail": 1, "incomplete": 3}[v["status"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="write JSON to this new file instead of stdout")
    for k, v in DEFAULT_LIMITS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=int, default=v, help="limit (default %d)" % v)
    sub = ap.add_subparsers(dest="mode", required=True)
    pi = sub.add_parser("inspect", help="validated load command inventory of the given files")
    pi.add_argument("files", nargs="+")
    pc = sub.add_parser("check", help="bounded static bundle check")
    pc.add_argument("--bundle-root", required=True)
    pc.add_argument("--root-executable", required=True, help="path relative to the bundle root")
    pc.add_argument("--require-arch", action="append", required=True, help="e.g. arm64; repeat for more")
    pc.add_argument("--forbid-root", action="append", default=[], help="absolute build root that must not be referenced")
    pc.add_argument("--system-prefix", action="append", help="absolute prefix allowed by system policy (default /usr/lib/ and /System/Library/)")
    pc.add_argument("--extra-root", action="append", default=[], help="extra in-bundle image to check, e.g. a dlopen()ed plugin")
    args = ap.parse_args(argv)
    ctx = Ctx({k: getattr(args, k) for k in DEFAULT_LIMITS})
    try:
        out, rc = (cmd_inspect if args.mode == "inspect" else cmd_check)(args, ctx)
    except Exception:
        sys.stderr.write("macho_bundle_inspect: internal error\n" + traceback.format_exc())
        return 4
    text = json.dumps(out, indent=2, ensure_ascii=True) + "\n"
    if args.json:
        with open(args.json, "x") as fp:
            fp.write(text)
    else:
        sys.stdout.write(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
