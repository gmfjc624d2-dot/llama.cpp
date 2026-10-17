#!/usr/bin/env python3
"""Check facts about the installed pinned macholib wheel (not upstream master).

usage: python -I verify_pinned_release.py [--git-dir DIR --rev REV ...]
Reads source files only; does not import macholib.dyld or MachOGraph.
"""

import argparse
import base64
import csv
import hashlib
import importlib.metadata as md
import json
import os
import re
import subprocess
import sys


def record_check(dist):
    out = []
    for row in csv.reader(dist.read_text("RECORD").splitlines()):
        path, digest = row[0], row[1]
        if not digest or not path.endswith(".py"):
            continue
        algo, want = digest.split("=", 1)
        data = dist.locate_file(path).read_bytes()
        got = base64.urlsafe_b64encode(hashlib.new(algo, data).digest()).rstrip(b"=").decode()
        out.append({"path": path, "record_ok": got == want, "sha256": hashlib.sha256(data).hexdigest()})
    return out


def facts(src_machO, src_dyld, src_graph):
    m = re.search(r"_RELOCATABLE = \{(.*?)\}", src_machO, re.S)
    reloc = re.findall(r"LC_[A-Z_]+", m.group(1))
    return {
        "MachO._RELOCATABLE": reloc,
        "MachO._RELOCATABLE_has_LC_LAZY_LOAD_DYLIB": "LC_LAZY_LOAD_DYLIB" in reloc,
        "MachO._RELOCATABLE_has_LC_PREBOUND_DYLIB": "LC_PREBOUND_DYLIB" in reloc,
        "MachO.walkRelocatables_decodes_with_fs_encoding": "decode(sys.getfilesystemencoding())" in src_machO,
        "MachO.walkRelocatables_find_minus_one_slice": 'data.find(b"\\x00", ofs)' in src_machO,
        "MachO.load_fat_raises_on_first_bad_slice": "for arch in archs:\n            self.load_header(fh, arch.offset, arch.size)" in src_machO,
        "MachO.reads_section_data": "seg.add_section_data(sd)" in src_machO,
        "dyld.mentions_rpath": "@rpath" in src_dyld,
        "dyld.uses_os_environ_when_env_None": "env = os.environ" in src_dyld,
        "dyld.reads_DYLD_vars": sorted(set(re.findall(r'"(DYLD_[A-Z_]+)"', src_dyld))),
        "dyld.ctypes_libSystem_on_darwin": 'ctypes.CDLL("libSystem.dylib")' in src_dyld,
        "dyld.shared_cache_lookup": "_dyld_shared_cache_contains_path" in src_dyld,
        "dyld.isfile_probe_on_host": "os.path.isfile(path)" in src_dyld,
        "dyld.default_fallback_has_home_lib": 'os.path.expanduser("~/lib")' in src_dyld,
        "MachOGraph.uses_dyld_find": "from macholib.dyld import dyld_find" in src_graph,
        "MachOGraph.mentions_rpath": "@rpath" in src_graph,
    }


def git_show(git_dir, rev, path):
    return subprocess.run(["git", "-C", git_dir, "show", "%s:%s" % (rev, path)], check=True, capture_output=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--git-dir")
    ap.add_argument("--rev", action="append", default=[])
    args = ap.parse_args()
    dist = md.distribution("macholib")
    files = {p: dist.locate_file("macholib/" + p).read_text() for p in ("MachO.py", "dyld.py", "MachOGraph.py")}
    res = {
        "installed": {"name": dist.metadata["Name"], "version": dist.version, "requires": dist.requires},
        "record": record_check(dist),
        "facts_installed_wheel": facts(files["MachO.py"], files["dyld.py"], files["MachOGraph.py"]),
        "git": {},
    }
    for rev in args.rev:
        g = {p: git_show(args.git_dir, rev, "macholib/" + p) for p in ("MachO.py", "dyld.py", "MachOGraph.py", "mach_o.py")}
        same = {p: hashlib.sha256(g[p]).hexdigest() == hashlib.sha256(dist.locate_file("macholib/" + p).read_bytes()).hexdigest() for p in g}
        res["git"][rev] = {"identical_to_installed": same, "facts": facts(*(g[p].decode() for p in ("MachO.py", "dyld.py", "MachOGraph.py")))}
    res["record_all_ok"] = all(r["record_ok"] for r in res["record"])
    json.dump(res, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if res["record_all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
