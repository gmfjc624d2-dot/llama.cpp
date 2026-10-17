#!/usr/bin/env python3
"""Baseline: what stock macholib utilities do on the synthetic fixtures.

usage: python -I probe_stock_macholib.py PYTHON FIXTURE_DIR OUT_JSONL
Each case runs in a child process (PYTHON -I) with a wall timeout and
RLIMIT_AS / RLIMIT_CPU. Targets are read as data only; nothing is executed.
"""

import json
import os
import resource
import subprocess
import sys
import time

TIMEOUT = 60
AS_LIMIT = 1 << 30
CPU_LIMIT = 30

CHILD = r'''
import json, os, resource, sys
mode, path = sys.argv[1], sys.argv[2]
out = {"mode": mode}
def lcs(m):
    return [{"cputype": h.header.cputype, "ncmds": h.header.ncmds,
             "cmds": [[lc.cmd, lc.cmdsize] for lc, _c, _d in h.commands]} for h in m.headers]
try:
    from macholib.MachO import MachO
    if mode == "strict":
        out["headers"] = lcs(MachO(path))
    elif mode == "walk":
        m = MachO(path, allow_unknown_load_commands=True)
        out["headers"] = lcs(m)
        out["relocatables"] = [[[i, n, f] for i, n, f in h.walkRelocatables()] for h in m.headers]
    elif mode.startswith("graph"):
        from macholib.MachOGraph import MachOGraph
        env = {} if mode == "graph-empty-env" else ({"DYLD_LIBRARY_PATH": sys.argv[3]} if mode == "graph-dyld-env" else None)
        g = MachOGraph(env=env, executable_path=os.path.dirname(path))
        g.run_file(path)
        nodes = []
        for n in g.flatten():
            nodes.append([type(n).__name__, n.graphident])
        out["nodes"] = sorted(nodes)
    out["ok"] = True
except BaseException as e:
    out["ok"] = False
    out["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
out["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps(out))
'''


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (AS_LIMIT, AS_LIMIT))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT, CPU_LIMIT))


def run(argv, env=None):
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, preexec_fn=limits, env=env)
        rc, so, se = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, so, se = "timeout", e.stdout or b"", e.stderr or b""
    return {
        "argv": argv,
        "exit": rc,
        "wall_s": round(time.monotonic() - t0, 3),
        "stdout": so.decode("utf-8", "backslashreplace")[-4000:],
        "stderr": se.decode("utf-8", "backslashreplace")[-2000:],
    }


def main():
    py, fx, out = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3])
    os.chdir(fx)
    fx = "."
    cases = []
    parse_dir = os.path.join(fx, "parse")
    for n in sorted(os.listdir(parse_dir)):
        p = os.path.join(parse_dir, n)
        cases.append(("dump", p, [py, "-I", "-m", "macholib", "dump", p], None))
        for mode in ("strict", "walk"):
            cases.append((mode, p, [py, "-I", "-c", CHILD, mode, p], None))
    decoy = os.path.join(fx, "bundles", "_decoy-dyld")
    roots = {
        "b01-flat-good": "llama-cli",
        "b02-nested-inherited-rpath": "bin/llama-server",
        "b04-system-and-external": "app",
        "b06-symlinks": "bin/tool",
        "b19-dependency-kinds": "main",
    }
    for b, rel in sorted(roots.items()):
        p = os.path.join(fx, "bundles", b, rel)
        cases.append(("dump-bundle-dir", p, [py, "-I", "-m", "macholib", "dump", os.path.join(fx, "bundles", b)], None))
        for mode in ("graph-empty-env", "graph-dyld-env"):
            cases.append((mode, p, [py, "-I", "-c", CHILD, mode, p, decoy], None))
        # env=None: MachOGraph falls back to os.environ of the child
        env = {"PATH": "/usr/bin:/bin", "DYLD_LIBRARY_PATH": decoy}
        cases.append(("graph-os-environ", p, [py, "-I", "-c", CHILD, "graph-os-environ", p], env))
    with open(out, "x") as fp:
        for mode, p, argv, env in cases:
            r = run(argv, env)
            r["argv"] = ["$PY" if a == py else a for a in r["argv"]]
            r["case"] = mode
            r["target"] = os.path.relpath(p, fx)
            if env:
                r["env"] = {k: os.path.relpath(v, fx) if k.startswith("DYLD") else v for k, v in env.items()}
            fp.write(json.dumps(r, sort_keys=True) + "\n")
            print("%-16s %-50s exit=%s %.2fs" % (mode, r["target"], r["exit"], r["wall_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
