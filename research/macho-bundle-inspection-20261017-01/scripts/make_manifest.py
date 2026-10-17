#!/usr/bin/env python3
"""Write MANIFEST.json and SHA256SUMS for files under a research dir.

usage: python -I make_manifest.py RESEARCH_DIR OUT_DIR [--exclude REL ...]
Paths are relative to RESEARCH_DIR. Symlinks are listed with their target, not followed.
Refuses to overwrite existing output files.
"""

import argparse
import hashlib
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()
    out_rel = os.path.relpath(os.path.abspath(args.out), os.path.abspath(args.root))
    entries = []
    for d, dirs, files in os.walk(args.root):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for n in sorted(files + [x for x in dirs if os.path.islink(os.path.join(d, x))]):
            full = os.path.join(d, n)
            rel = os.path.relpath(full, args.root)
            if rel.startswith(out_rel + os.sep) or any(rel == e or rel.startswith(e.rstrip("/") + "/") for e in args.exclude):
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
        json.dump({"root": "research/" + os.path.basename(os.path.abspath(args.root)), "excluded": args.exclude, "entries": entries}, fp, indent=2)
        fp.write("\n")
    with open(os.path.join(args.out, "SHA256SUMS"), "x") as fp:
        for e in entries:
            if e["type"] == "file":
                fp.write("%s  %s\n" % (e["sha256"], e["path"]))
    print("make_manifest: %d entries" % len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
