#!/usr/bin/env python3
"""Find paths that collide on a case-insensitive, normalization-insensitive volume (default macOS APFS).

usage:
  python -I check_casefold_collisions.py --git REPO [--prefix DIR]   paths from `git ls-files` at the work tree
  python -I check_casefold_collisions.py --git-rev REPO REV [--prefix DIR]   paths from `git ls-tree -r REV`
  python -I check_casefold_collisions.py --tree DIR      paths from a directory walk (symlinks not followed)
  python -I check_casefold_collisions.py --tar FILE      member names of a tar file

Every directory component is checked too: "a/x" and "A/y" collide on "a".
Key: NFD normalization, then str.casefold(). Output is sorted JSON; exit 1 if any collision.
"""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import unicodedata


def key(s):
    return unicodedata.normalize("NFD", s).casefold()


def git_paths(argv):
    out = subprocess.run(argv, check=True, capture_output=True).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def collisions(paths):
    seen = {}
    for p in paths:
        parts = p.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            name = "/".join(parts[:i])
            seen.setdefault(key(name), set()).add(name)
    return {k: sorted(v) for k, v in sorted(seen.items()) if len(v) > 1}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--git")
    g.add_argument("--git-rev", nargs=2, metavar=("REPO", "REV"))
    g.add_argument("--tree")
    g.add_argument("--tar")
    ap.add_argument("--prefix", default="", help="limit git paths to this directory")
    args = ap.parse_args()
    if args.git:
        paths, src = git_paths(["git", "-C", args.git, "ls-files", "-z", "--", args.prefix or "."]), "git ls-files"
    elif args.git_rev:
        repo, rev = args.git_rev
        paths, src = git_paths(["git", "-C", repo, "ls-tree", "-r", "-z", "--name-only", rev, "--", args.prefix or "."]), "git ls-tree " + rev
    elif args.tree:
        paths, src = [], "tree"
        for d, dirs, files in os.walk(args.tree):
            for n in dirs + files:
                paths.append(os.path.relpath(os.path.join(d, n), args.tree))
    else:
        with tarfile.open(args.tar) as t:
            paths, src = [m.name for m in t.getmembers()], "tar members"
    c = collisions(paths)
    groups = list(c.values())
    json.dump({"source": src, "prefix": args.prefix, "paths_checked": len(paths), "collision_groups": len(groups),
               "colliding_names": sum(len(v) for v in groups), "groups": groups}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 1 if groups else 0


if __name__ == "__main__":
    sys.exit(main())
