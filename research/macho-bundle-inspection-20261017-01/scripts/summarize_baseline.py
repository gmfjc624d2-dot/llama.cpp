#!/usr/bin/env python3
"""Markdown table from probe-results.jsonl and the otool oracle logs.

usage: python -I summarize_baseline.py BASELINE_DIR
"""

import json
import os
import sys


def last_json(stdout):
    for line in reversed(stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def cell(r):
    if r["case"] in ("dump", "dump-bundle-dir"):
        err = r["stderr"].strip().splitlines()
        deps = sum(1 for l in r["stdout"].splitlines() if l.startswith("\t"))
        return "exit %s, %d dep lines%s" % (r["exit"], deps, (", " + err[-1][:70]) if err else "")
    o = last_json(r["stdout"])
    if o is None:
        return "exit %s, no result" % r["exit"]
    if not o["ok"]:
        return "ERROR " + o["error"][:80]
    if r["case"] == "strict":
        return "ok, %d header(s)" % len(o["headers"])
    if r["case"] == "walk":
        return "ok: " + "; ".join(",".join("%s=%s" % (n, f) for _i, n, f in h) or "-" for h in o["relocatables"])
    outside = [n for t, n in o["nodes"] if t == "MachO" and "_decoy" in n]
    missing = [n for t, n in o["nodes"] if t == "MissingMachO"]
    return "parsed outside bundle: %s; missing: %d" % (outside or "none", len(missing))


def otool(base, name):
    p = os.path.join(base, "otool-oracle", "l__parse_%s" % name)
    if not os.path.exists(p + ".exit"):
        return "n/a"
    rc = open(p + ".exit").read().strip()
    log = open(p + ".log", errors="backslashreplace").read()
    msg = ""
    for line in log.splitlines():
        if "error:" in line:
            msg = line.split("error:", 1)[1].strip()[:70]
            break
        if "is not an object file" in line:
            msg = "is not an object file"
            break
    return "exit %s%s" % (rc, (", " + msg) if msg else "")


def main():
    base = sys.argv[1]
    rows = {}
    for line in open(os.path.join(base, "probe-results.jsonl")):
        r = json.loads(line)
        rows.setdefault(r["target"], {})[r["case"]] = cell(r)
    out = ["| fixture | `python -m macholib dump` | `MachO()` strict | `MachO(allow_unknown)` + `walkRelocatables` | `llvm-otool -l` |", "|---|---|---|---|---|"]
    for t in sorted(k for k in rows if k.startswith("./parse/") or k.startswith("parse/")):
        n = os.path.basename(t)
        c = rows[t]
        out.append("| %s | %s | %s | %s | %s |" % (n[:-4], c.get("dump", ""), c.get("strict", ""), c.get("walk", "").replace("|", "/"), otool(base, n)))
    out += ["", "| bundle root | `dump DIR` | `MachOGraph(env={})` | `MachOGraph(env={DYLD_LIBRARY_PATH: decoy})` | `MachOGraph(env=None)`, child has DYLD_LIBRARY_PATH |", "|---|---|---|---|---|"]
    for t in sorted(k for k in rows if "bundles/" in k):
        c = rows[t]
        out.append("| %s | %s | %s | %s | %s |" % (t.split("bundles/", 1)[1], c.get("dump-bundle-dir", ""), c.get("graph-empty-env", ""), c.get("graph-dyld-env", ""), c.get("graph-os-environ", "")))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
