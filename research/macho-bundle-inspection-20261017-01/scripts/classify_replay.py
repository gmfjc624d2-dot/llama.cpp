#!/usr/bin/env python3
"""Classify a replay_otool.sh run conservatively; raw files are not changed.

usage: python -I classify_replay.py RUN_DIR OUT_DIR [MAX_CASE_BYTES]
Writes OUT_DIR/outcomes.json and OUT_DIR/outcomes.md (OUT_DIR must be new).
An outcome is about what the tool printed. "parsed_by_tool" does not mean dyld
would load the file, and anything else is not passing.
Every file is read with a cap. A case file over MAX_CASE_BYTES (an integer in [1, 256 MiB],
default 8 MiB), or a replay_bounded.py case whose capture.json is not complete, is not passing.
A replay_bounded.py run without "status: complete" in run.txt is not passing at all. The run
directory is trusted as written by the wrapper; receipts are not authenticated.
"""

import base64
import json
import os
import re
import sys

CPU = {16777228: "arm64", 16777223: "x86_64"}
SUB = {("arm64", 2): "arm64e", ("x86_64", 8): "x86_64h"}
MACHO_MAGIC = {"feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "cafebabf"}
DYLIB_CMDS = {b"LC_LOAD_DYLIB", b"LC_LOAD_WEAK_DYLIB", b"LC_REEXPORT_DYLIB", b"LC_LOAD_UPWARD_DYLIB", b"LC_LAZY_LOAD_DYLIB", b"LC_ID_DYLIB", b"LC_DYLD_ENVIRONMENT"}


def b(v):
    return {"text": v.decode("utf-8", "backslashreplace"), "b64": base64.b64encode(v).decode()}


META_CAP = 16 << 20
CASE_BYTES = (1, 256 << 20)
READ_BYTES = (1, 1 << 30)


def check_cap(name, cap, lo, hi):
    if isinstance(cap, bool) or not isinstance(cap, int) or not lo <= cap <= hi:
        raise ValueError("%s must be an integer in [%d, %d], got %r" % (name, lo, hi, cap))
    return cap


def read_capped(path, cap):
    """(at most cap bytes, True if that was the whole file)."""
    check_cap("cap", cap, *READ_BYTES)
    with open(path, "rb") as fp:
        data = fp.read(cap + 1)
    return data[:cap], len(data) <= cap


def read_meta(path):
    data, whole = read_capped(path, META_CAP)
    if not whole:
        raise SystemExit("classify_replay: %s is larger than %d bytes" % (path, META_CAP))
    return data


def capture_problem(cap):
    """None if a replay_bounded.py capture record says the case is complete."""
    sm = cap.get("summary", {})
    if cap.get("aborted"):
        return "aborted"
    if sm.get("capture_complete"):
        return None
    if cap.get("process", {}).get("timed_out"):
        return "timeout"
    if not sm.get("streams_complete", False):
        return "capture_incomplete"
    if not sm.get("cleanup_certain", False):
        return "cleanup_uncertain"
    return "process_incomplete"


def load(run, cap=8 << 20):
    check_cap("cap", cap, *CASE_BYTES)
    cases = {}
    for line in read_meta(os.path.join(run, "index.tsv")).split(b"\n"):
        if not line:
            continue
        cid, label = line.split(b"\t", 1)
        base = os.path.join(run, "cases", cid.decode())
        c = {"id": cid.decode(), "label": label.decode("utf-8", "backslashreplace"), "rc": read_capped(base + ".rc", 64)[0].decode().strip()}
        for k in ("stdout", "stderr"):
            p = base + "." + k
            c[k], whole = read_capped(p, cap) if os.path.exists(p) else (b"", True)
            if not whole:
                c["capture_problem"] = "classifier_read_truncated"
        if os.path.exists(base + ".capture.json") and "capture_problem" not in c:
            c["capture"] = json.loads(read_meta(base + ".capture.json"))
            prob = capture_problem(c["capture"])
            if prob:
                c["capture_problem"] = prob
        cases[c["label"]] = c
    return cases


def usable(c):
    return c is not None and c["rc"] == "0" and "capture_problem" not in c


def headers(out):
    """(arch) of each 'Mach header' block in otool -l output."""
    res = []
    lines = out.split(b"\n")
    for i, l in enumerate(lines):
        if l.strip() == b"Mach header" and i + 2 < len(lines):
            f = lines[i + 2].split()
            try:
                cpu, sub = int(f[1]), int(f[2]) & 0x00FFFFFF
            except (IndexError, ValueError):
                res.append("unparsed")
                continue
            a = CPU.get(cpu, "cpu%d" % cpu)
            res.append(SUB.get((a, sub), a if sub in (0, 3) else "%s:sub%d" % (a, sub)))
    return res


def strings(out):
    """LC_RPATH paths, dylib names and LC_DYLD_ENVIRONMENT from otool -l output, in order, as bytes."""
    res, cmd = [], None
    for l in out.split(b"\n"):
        s = l.strip()
        if s.startswith(b"cmd "):
            cmd = s[4:]
        m = re.match(rb"^(path|name) (.*) \(offset \d+\)$", s)
        if m and (cmd == b"LC_RPATH" or cmd in DYLIB_CMDS):
            res.append({"cmd": cmd.decode(), "value": b(m.group(2))})
    return res


def outcome(c, want_arch, lipo_archs):
    if c is None:
        return "not_run", None
    if c["rc"] == "timeout":
        return "timeout", None
    if c["rc"] == "skipped_size":
        return "skipped_size", None
    if "capture_problem" in c:
        return c["capture_problem"], None
    text = c["stdout"] + c["stderr"]
    if b"is not an object file" in text or b"not recognized as a valid object file" in text:
        return "not_object", None
    err = next((l for l in c["stderr"].split(b"\n") if b"error" in l), None)
    if c["rc"] != "0":
        if want_arch != "all" and lipo_archs is not None and want_arch not in lipo_archs:
            return "arch_absent", err
        return "rejected", err
    if b"cmd ?(" in c["stdout"]:
        return "unknown_load_command", None
    if c["label"].startswith("otool-loadcommands"):
        h = headers(c["stdout"])
        if not h:
            return "no_header", None
        if want_arch != "all" and want_arch not in h:
            return "arch_absent", ("tool printed %s" % ",".join(h)).encode()
    elif lipo_archs is None:
        return "arch_unverified", None
    elif want_arch not in lipo_archs:
        return "arch_absent", b"lipo -archs: " + " ".join(lipo_archs).encode()
    if c["stderr"].strip():
        return "parsed_with_stderr", c["stderr"].strip().split(b"\n")[0]
    return "parsed_by_tool", None


def main():
    run, out = sys.argv[1], sys.argv[2]
    try:
        cap = check_cap("MAX_CASE_BYTES", int(sys.argv[3]) if len(sys.argv) > 3 else 8 << 20, *CASE_BYTES)
    except ValueError as e:
        raise SystemExit("classify_replay: %s" % e)
    os.makedirs(out)
    meta = dict(l.split(": ", 1) for l in read_meta(os.path.join(run, "run.txt")).decode().splitlines() if ": " in l)
    cases = load(run, cap)
    files = [l for l in read_meta(os.path.join(run, "inputs.files")).decode().split("\n") if l]
    ipath = os.path.join(run, "inputs.json")
    inputs = {r["path"]: r for r in json.loads(read_meta(ipath))} if os.path.exists(ipath) else {}
    archs = meta.get("archs", "arm64 x86_64").split()
    rows = []
    for f in files:
        lc = cases.get("lipo-archs " + f)
        lipo = lc["stdout"].decode().split() if usable(lc) else None
        mc = cases.get("magic " + f)
        magic = mc["stdout"].decode().replace(" ", "").strip() if usable(mc) else None
        row = {"file": f, "magic": magic, "lipo_archs": lipo, "lipo_rc": lc["rc"] if lc else None, "per_arch": {}}
        if f in inputs:
            row["input_status"] = inputs[f]["status"]
        if "file " + f in cases and cases["file " + f]["rc"] == "skipped_size":
            row["skipped"] = "size"
        for a in archs + ["all"]:
            l = cases.get("otool-loadcommands %s %s" % (a, f))
            d = cases.get("otool-dependencies %s %s" % (a, f))
            lo, le = outcome(l, a, lipo)
            ent = {"loadcommands": lo, "loadcommands_case": l and l["id"]}
            if le:
                ent["loadcommands_detail"] = le.decode("utf-8", "backslashreplace")
            if lo == "parsed_by_tool" and l:
                ent["headers"] = headers(l["stdout"])
                ent["strings"] = strings(l["stdout"])
            if a != "all":
                do, de = outcome(d, a, lipo)
                # -L prints no header; on a fat file trust it only if -l showed this tool honours -arch
                if do == "parsed_by_tool" and lipo and len(lipo) > 1 and not (lo == "parsed_by_tool" and ent.get("headers") == [a]):
                    do, de = "arch_unverified", b"-l for this arch did not print exactly one %s header" % a.encode()
                ent.update({"dependencies": do, "dependencies_case": d and d["id"]})
                if de:
                    ent["dependencies_detail"] = de.decode("utf-8", "backslashreplace")
                ent["passing_parse"] = lo == "parsed_by_tool" and do == "parsed_by_tool"
            row["per_arch"][a] = ent
        if magic is None or magic in MACHO_MAGIC:
            # a truncated Mach-O can be reported as "not an object file"
            for e in row["per_arch"].values():
                for k in ("loadcommands", "dependencies"):
                    if e.get(k) == "not_object":
                        e[k] = "not_object_but_macho_magic" if magic else "not_object_magic_unknown"
        if lipo and len(lipo) > 1:
            # one wrong header for any arch means this tool does not honour -arch for this file
            honours = all(row["per_arch"][a].get("headers") == [a] for a in archs if a in lipo)
            row["arch_selection_honoured"] = honours
            if not honours:
                for a in archs:
                    ent = row["per_arch"][a]
                    if ent["loadcommands"] in ("parsed_by_tool", "arch_absent") and a in lipo:
                        ent["loadcommands"] = "arch_selection_unreliable"
                    if ent["dependencies"] == "parsed_by_tool":
                        ent["dependencies"] = "arch_unverified"
                    ent["passing_parse"] = False
            al = row["per_arch"]["all"]
            if al["loadcommands"] == "parsed_by_tool" and sorted(al.get("headers", [])) != sorted(lipo):
                al["loadcommands"] = "slices_missing_from_output"
                al["loadcommands_detail"] = "printed %s, lipo lists %s" % (",".join(al.get("headers", [])), ",".join(lipo))
        if inputs.get(f, {}).get("unchanged_after_cases") is False:
            for e in row["per_arch"].values():
                for k in ("loadcommands", "dependencies"):
                    if k in e:
                        e[k] = "input_changed"
                e["passing_parse"] = False
        rows.append(row)
    links = []
    for l in read_meta(os.path.join(run, "inputs.symlinks")).split(b"\n"):
        if not l:
            continue
        rec = inputs.get(l.decode("utf-8", "backslashreplace"))
        if rec is not None:
            links.append({"link": b(l), "rc": None, "target": rec.get("target")})
            continue
        c = cases.get("readlink " + l.decode("utf-8", "backslashreplace"))
        links.append({"link": b(l), "rc": c and c["rc"], "target": b(c["stdout"].rstrip(b"\n")) if usable(c) else None})
    if meta.get("wrapper") == "replay_bounded.py" and meta.get("status") != "complete":
        # interrupted, failed or unfinished run: nothing in it may pass
        for row in rows:
            row["run_status"] = meta.get("status", "missing")
            for e in row["per_arch"].values():
                e["passing_parse"] = False
    res = {"platform": meta.get("platform"), "run": meta, "note": "tool parse outcomes only; not loader validity; not runtime evidence",
           "files": rows, "symlinks": links}
    with open(os.path.join(out, "outcomes.json"), "x") as fp:
        json.dump(res, fp, indent=2, sort_keys=True)
        fp.write("\n")
    md = ["# Replay outcomes: %s" % meta.get("platform"), "",
          "Tool parse outcomes only. `parsed_by_tool` does not mean dyld would load the file; every other value is not passing.", "",
          "| file | lipo -archs | " + " | ".join("%s -l / -L" % a for a in archs) + " | all -l |", "|---|---|" + "---|" * (len(archs) + 1)]
    for r in rows:
        cells = ["%s / %s" % (r["per_arch"][a]["loadcommands"], r["per_arch"][a]["dependencies"]) for a in archs]
        md.append("| %s | %s | %s | %s |" % (r["file"], " ".join(r["lipo_archs"]) if r["lipo_archs"] is not None else "rc %s" % r["lipo_rc"], " | ".join(cells), r["per_arch"]["all"]["loadcommands"]))
    with open(os.path.join(out, "outcomes.md"), "x") as fp:
        fp.write("\n".join(md) + "\n")
    print("classify_replay: %d files" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
