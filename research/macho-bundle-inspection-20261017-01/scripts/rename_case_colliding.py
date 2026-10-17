#!/usr/bin/env python3
"""Rename otool log files whose names differ only by case (-L vs -l) with `git mv`.

usage: python -I rename_case_colliding.py REPO RESEARCH_REL MAP_OUT SOURCE_COMMIT
File bytes are not changed. Writes a map (old -> new, sha256) and updates the
paths in evidence/checkpoint-1/MANIFEST.json and SHA256SUMS to the new names.
"""

import hashlib
import json
import os
import subprocess
import sys

RULES = [
    ("/otool-oracle/L__", "/otool-oracle/dependencies__"),
    ("/otool-oracle/l__", "/otool-oracle/loadcommands__"),
    ("/otool-oracle-arch/L-arch-", "/otool-oracle-arch/dependencies-arch-"),
    ("/otool-oracle-arch/l-arch-", "/otool-oracle-arch/loadcommands-arch-"),
]


def main():
    repo, research, map_out, source = sys.argv[1:5]
    files = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--", research], check=True, capture_output=True).stdout.decode().split("\0")
    moves = []
    for old in sorted(f for f in files if f):
        for a, b in RULES:
            if a in old:
                new = old.replace(a, b, 1)
                with open(os.path.join(repo, old), "rb") as fp:
                    sha = hashlib.sha256(fp.read()).hexdigest()
                moves.append({"old": old, "new": new, "sha256": sha})
                break
    news = [m["new"] for m in moves]
    assert len(set(n.casefold() for n in news)) == len(news), "new names collide"
    assert not set(news) & set(files), "new name already tracked"
    for m in moves:
        subprocess.run(["git", "-C", repo, "mv", "--", m["old"], m["new"]], check=True)
        with open(os.path.join(repo, m["new"]), "rb") as fp:
            assert hashlib.sha256(fp.read()).hexdigest() == m["sha256"]
    with open(map_out, "x") as fp:
        json.dump({"reason": "names differing only by case (otool -L vs -l) collide on case-insensitive volumes",
                   "source_commit": source, "rules": RULES, "bytes_changed": False, "moves": moves}, fp, indent=2)
        fp.write("\n")
    rel = {m["old"][len(research) + 1:]: m["new"][len(research) + 1:] for m in moves}
    ck = os.path.join(repo, research, "evidence", "checkpoint-1")
    man = json.load(open(os.path.join(ck, "MANIFEST.json")))
    for e in man["entries"]:
        e["path"] = rel.get(e["path"], e["path"])
    man["entries"].sort(key=lambda e: e["path"])
    man["paths_renamed_after"] = {"commit": source, "map": os.path.relpath(map_out, os.path.join(repo, research))}
    with open(os.path.join(ck, "MANIFEST.json"), "w") as fp:
        json.dump(man, fp, indent=2)
        fp.write("\n")
    lines = []
    for line in open(os.path.join(ck, "SHA256SUMS")):
        sha, path = line.rstrip("\n").split("  ", 1)
        lines.append("%s  %s\n" % (sha, rel.get(path, path)))
    with open(os.path.join(ck, "SHA256SUMS"), "w") as fp:
        fp.writelines(sorted(lines, key=lambda l: l.split("  ", 1)[1]))
    print("rename_case_colliding: %d files moved" % len(moves))
    return 0


if __name__ == "__main__":
    sys.exit(main())
