#!/usr/bin/env python3
"""Check a fresh clone against a MANIFEST.json: every entry tracked by git and identical.

usage: python -I verify_clone.py CLONE_DIR MANIFEST_REL
MANIFEST_REL is relative to the clone root, e.g. research/<dir>/evidence/checkpoint-1/MANIFEST.json
"""

import hashlib
import json
import os
import subprocess
import sys


def main():
    clone, mrel = sys.argv[1], sys.argv[2]
    m = json.load(open(os.path.join(clone, mrel)))
    root = m["root"]
    tracked = set(subprocess.run(["git", "-C", clone, "ls-files", "-z", "--", root], check=True, capture_output=True).stdout.decode().split("\0"))
    bad = []
    for e in m["entries"]:
        rel = root + "/" + e["path"]
        full = os.path.join(clone, rel)
        if rel not in tracked:
            bad.append(("untracked", rel))
            continue
        if e["type"] == "symlink":
            if not os.path.islink(full) or os.readlink(full) != e["target"]:
                bad.append(("symlink differs", rel))
            continue
        with open(full, "rb") as fp:
            if hashlib.sha256(fp.read()).hexdigest() != e["sha256"]:
                bad.append(("sha256 differs", rel))
    exts = {}
    for e in m["entries"]:
        x = os.path.splitext(e["path"])[1] or "(none)"
        exts[x] = exts.get(x, 0) + 1
    print(json.dumps({"manifest": mrel, "entries": len(m["entries"]), "by_extension": dict(sorted(exts.items())), "problems": bad}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
