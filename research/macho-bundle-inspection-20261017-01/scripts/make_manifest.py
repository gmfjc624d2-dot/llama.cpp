#!/usr/bin/env python3
"""Write MANIFEST.json and SHA256SUMS for files under a research dir.

usage: python -I make_manifest.py RESEARCH_DIR OUT_DIR [--exclude REL ...] [--git-index REPO]
Paths are relative to RESEARCH_DIR. Symlinks are listed with their target, not followed.
--git-index lists what is staged in REPO's index (the next commit), not the work tree.
Refuses to overwrite existing output files.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys


def index_entries(repo, root):
    """(path relative to root, is_symlink, bytes) for every staged file under root."""
    top = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip()
    prefix = os.path.relpath(os.path.abspath(root), top)
    out = subprocess.run(["git", "-C", top, "ls-files", "-z", "-s", "--", prefix], check=True, capture_output=True).stdout
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, blob, _stage = meta.split()
        data = subprocess.run(["git", "-C", top, "cat-file", "blob", blob.decode()], check=True, capture_output=True).stdout
        yield os.path.relpath(path.decode(), prefix), mode == b"120000", data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--git-index")
    args = ap.parse_args()
    out_rel = os.path.relpath(os.path.abspath(args.out), os.path.abspath(args.root))
    entries = []
    skip = lambda rel: rel.startswith(out_rel + os.sep) or any(rel == e or rel.startswith(e.rstrip("/") + "/") for e in args.exclude)
    if args.git_index:
        for rel, link, data in index_entries(args.git_index, args.root):
            if skip(rel):
                continue
            if link:
                entries.append({"path": rel, "type": "symlink", "target": data.decode("utf-8", "surrogateescape")})
            else:
                entries.append({"path": rel, "type": "file", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    for d, dirs, files in ([] if args.git_index else os.walk(args.root)):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for n in sorted(files + [x for x in dirs if os.path.islink(os.path.join(d, x))]):
            full = os.path.join(d, n)
            rel = os.path.relpath(full, args.root)
            if skip(rel):
                continue
            if os.path.islink(full):
                entries.append({"path": rel, "type": "symlink", "target": os.readlink(full)})
                continue
            with open(full, "rb") as fp:
                data = fp.read()
            entries.append({"path": rel, "type": "file", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    entries.sort(key=lambda e: e["path"])
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "MANIFEST.json"), "x") as fp:
        json.dump({"root": "research/" + os.path.basename(os.path.abspath(args.root)), "source": "git index" if args.git_index else "work tree",
                   "excluded": args.exclude, "entries": entries}, fp, indent=2)
        fp.write("\n")
    with open(os.path.join(args.out, "SHA256SUMS"), "x") as fp:
        for e in entries:
            if e["type"] == "file":
                fp.write("%s  %s\n" % (e["sha256"], e["path"]))
    print("make_manifest: %d entries" % len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
