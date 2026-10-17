#!/usr/bin/env python3
"""Bounded static replay of selected fixtures with trusted inspection tools (successor of replay_otool.sh).

usage: python3 -I replay_bounded.py --platform macos-native|linux-llvm --fixture-dir DIR --out NEW_DIR
           --otool PATH --lipo PATH [--input REL ...] [--inputs-from FILE] [limits ...]

Only the trusted tools given on the command line (and file, od, uname, sw_vers) are launched; a
fixture is only ever passed to them as a path argument. This is for cooperative tools that the
wrapper owns. It is not containment for hostile programs: a process that leaves its process group
or session, or keeps a pipe open from outside it, is not tracked.

Preconditions: this process starts each tool itself and is its only reaper. SIGCHLD must not be
SIG_IGN, and no handler or thread may reap children (for example via SA_NOCLDWAIT or waitpid(-1)).
Python 3.9 or newer.

Per case: cases/cNNNNN.{cmd,stdout,stderr,rc,capture.json}. stdout/stderr hold at most the
retained prefix. capture.json keeps process completion, pipe EOF, timeout and cleanup apart; a
full-content digest appears only for a complete stream. rc is the direct child's exit code,
"signal:N", "timeout" or "unknown"; it is not a validity verdict.
"""

import argparse
import base64
import errno
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time

CHUNK = 65536
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}


class StreamCapture:
    """Byte accounting for one pipe. Never asks for more than limit + 1 bytes in total."""

    def __init__(self, limit):
        self.limit = limit
        self.observed = 0
        self.buf = bytearray()
        self.eof_phase = None  # "capture" (before any cleanup) or "after_cleanup"
        self.overflow = False

    def want(self):
        return max(0, min(CHUNK, self.limit + 1 - self.observed))

    def feed(self, data):
        if len(data) > self.want():
            raise ValueError("read beyond limit + 1")
        self.observed += len(data)
        self.buf += data[: self.limit - len(self.buf)]
        if self.observed > self.limit:
            self.overflow = True

    def done(self):
        return self.eof_phase is not None or self.overflow

    def record(self):
        complete = self.eof_phase == "capture" and not self.overflow
        digest = hashlib.sha256(bytes(self.buf)).hexdigest()
        return {
            "limit_bytes": self.limit,
            "observed_bytes": self.observed,
            "observed_is_lower_bound": self.eof_phase is None,
            "retained_bytes": len(self.buf),
            "eof": self.eof_phase,
            "overflow": self.overflow,
            "complete": complete,
            "retained_sha256": digest,
            "complete_sha256": digest if complete else None,
        }


def run_case(argv, cwd, timeout, out_limit, err_limit, grace, killpg=os.killpg, kill=os.kill, waitpid=os.waitpid):
    """Run one trusted tool in its own new session and capture both pipes with independent limits."""
    deadline = time.monotonic() + timeout
    res = {"argv": argv, "timeout_s": timeout, "grace_s": grace}
    try:
        p = subprocess.Popen(argv, cwd=cwd, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
    except OSError as e:
        res.update({"spawn_error": "%s: %s" % (type(e).__name__, e), "rc": "unknown",
                    "summary": {"process_completed": False, "capture_complete": False, "reasons": ["spawn failed"]}})
        return res, b"", b""
    res["pid"] = p.pid
    caps = {"stdout": StreamCapture(out_limit), "stderr": StreamCapture(err_limit)}
    pipes = {"stdout": p.stdout, "stderr": p.stderr}
    sel = selectors.DefaultSelector()
    for name, f in pipes.items():
        os.set_blocking(f.fileno(), False)
        sel.register(f.fileno(), selectors.EVENT_READ, name)

    def stop(name):
        sel.unregister(pipes[name].fileno())
        pipes[name].close()

    def pump(wait, phase):
        for key, _ in sel.select(wait):
            cap = caps[key.data]
            try:
                data = os.read(key.fd, cap.want())
            except BlockingIOError:
                continue
            if not data:
                cap.eof_phase = phase
                stop(key.data)
            else:
                cap.feed(data)
                if cap.overflow:
                    stop(key.data)

    reasons, cleanup = [], {"group_signal": "not_sent", "direct_signal": "not_sent", "reaped": False}
    status, timed_out = None, False

    def reap(until):
        # returns True when reaped; ChildProcessError means another reaper took it
        nonlocal status
        while True:
            try:
                pid, st = waitpid(p.pid, os.WNOHANG)
            except ChildProcessError:
                cleanup["reaped"] = "by_other"
                p.returncode = -1  # keep Popen from waiting later on a PID that may be reused
                reasons.append("direct child was reaped elsewhere (precondition broken); no further signals sent")
                return True
            if pid == p.pid:
                status = st
                cleanup["reaped"] = True
                return True
            if time.monotonic() >= until:
                return False
            time.sleep(0.01)

    # capture: nothing is reaped here, so the child's PID (= its process group ID) stays reserved
    while sel.get_map() and not any(c.overflow for c in caps.values()):
        left = deadline - time.monotonic()
        if left <= 0:
            timed_out = True
            break
        pump(min(0.05, left), "capture")
    abnormal = timed_out or any(c.overflow for c in caps.values())
    if not abnormal and not reap(deadline):
        timed_out = abnormal = True
    if abnormal and cleanup["reaped"] is False:
        # the leader is not reaped yet, so this ID still names the owned group
        try:
            killpg(p.pid, signal.SIGKILL)
            cleanup["group_signal"] = "sent"
        except ProcessLookupError:
            cleanup["group_signal"] = "no_such_group"
        except OSError as e:
            cleanup["group_signal"] = "failed: %s" % errno.errorcode.get(e.errno, e.errno)
            reasons.append("SIGKILL to the owned process group failed (%s)" % type(e).__name__)
            try:
                kill(p.pid, signal.SIGKILL)
                cleanup["direct_signal"] = "sent"
            except ProcessLookupError:
                cleanup["direct_signal"] = "no_such_process"
            except OSError as e2:
                cleanup["direct_signal"] = "failed: %s" % errno.errorcode.get(e2.errno, e2.errno)
                reasons.append("SIGKILL to the direct child failed (%s)" % type(e2).__name__)
        end = time.monotonic() + grace
        while sel.get_map() and time.monotonic() < end:
            pump(min(0.05, max(0.0, end - time.monotonic())), "after_cleanup")
        if not reap(time.monotonic() + grace):
            reasons.append("direct child not reaped within the grace period")
    for name in list(sel.get_map().values()):
        reasons.append("%s: no EOF after cleanup; a writer outside the owned group may remain" % name.data)
        stop(name.data)
    sel.close()
    if status is not None:
        code = os.waitstatus_to_exitcode(status)
        p.returncode = code
        exit_code, sig = (code, None) if code >= 0 else (None, -code)
    else:
        exit_code = sig = None
    streams = {k: c.record() for k, c in caps.items()}
    completed = cleanup["reaped"] is True and exit_code is not None and not timed_out
    if timed_out:
        rc = "timeout"
    elif sig is not None:
        rc = "signal:%d" % sig
    elif exit_code is not None:
        rc = str(exit_code)
    else:
        rc = "unknown"
    res.update({
        "rc": rc,
        "process": {"exit_code": exit_code, "signal": sig, "timed_out": timed_out, "reaped": cleanup["reaped"]},
        "streams": streams,
        "cleanup": cleanup,
        "claims": {
            "process_completion": "direct child only, from waitpid",
            "pipe_eof": "per stream, see streams.*.eof",
            "descendants": "not tracked; only members of the owned process group at signal time were sent SIGKILL, and only on timeout or overflow",
        },
        "summary": {
            "process_completed": completed,
            "streams_complete": all(s["complete"] for s in streams.values()),
            "cleanup_certain": not reasons,
            "capture_complete": completed and all(s["complete"] for s in streams.values()) and not reasons,
            "reasons": reasons,
        },
    })
    return res, bytes(caps["stdout"].buf), bytes(caps["stderr"].buf)


def bstr(b):
    return {"text": b.decode("utf-8", "backslashreplace"), "b64": base64.b64encode(b).decode("ascii")}


def check_input(root, rel, max_bytes, opener=os.open):
    """Type and size from lstat first; only then open (no symlink follow, no FIFO block) and hash at most max_bytes + 1 bytes."""
    parts = rel.split("/")
    if rel.startswith("/") or any(x in ("", ".", "..") for x in parts):
        return {"path": rel, "status": "bad_path"}
    for i in range(1, len(parts)):
        try:
            if not stat.S_ISDIR(os.lstat(os.path.join(root, *parts[:i])).st_mode):
                return {"path": rel, "status": "parent_not_a_directory"}
        except OSError as e:
            return {"path": rel, "status": "lstat_failed", "error": type(e).__name__}
    path = os.path.join(root, *parts)
    try:
        st = os.lstat(path)
    except OSError as e:
        return {"path": rel, "status": "lstat_failed", "error": type(e).__name__}
    if stat.S_ISLNK(st.st_mode):
        return {"path": rel, "status": "symlink", "target": bstr(os.readlink(os.fsencode(path)))}
    if not stat.S_ISREG(st.st_mode):
        return {"path": rel, "status": "not_regular", "mode": "0o%o" % stat.S_IFMT(st.st_mode)}
    if st.st_size > max_bytes:
        return {"path": rel, "status": "too_large", "size": st.st_size, "max_bytes": max_bytes}
    try:
        fd = opener(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        return {"path": rel, "status": "open_failed", "error": type(e).__name__}
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(fst.st_mode) or fst.st_size > max_bytes:
            return {"path": rel, "status": "changed_before_read"}
        h, n, head = hashlib.sha256(), 0, b""
        while True:
            chunk = os.read(fd, min(CHUNK, max_bytes + 1 - n))
            if not chunk:
                break
            if n < 4:
                head = (head + chunk)[:4]
            n += len(chunk)
            if n > max_bytes:
                return {"path": rel, "status": "grew_during_read", "observed_bytes": n}
            h.update(chunk)
        if n != fst.st_size:
            return {"path": rel, "status": "size_changed_during_read", "observed_bytes": n, "size": fst.st_size}
        return {"path": rel, "status": "ok", "size": n, "sha256": h.hexdigest(), "magic": head.hex(),
                "identity": [fst.st_dev, fst.st_ino, fst.st_size, fst.st_mtime_ns]}
    finally:
        os.close(fd)


def unchanged(root, rec):
    try:
        st = os.lstat(os.path.join(root, *rec["path"].split("/")))
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns] == rec["identity"]


def sha256_capped(path, cap):
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as fp:
        while n <= cap:
            chunk = fp.read(min(CHUNK, cap + 1 - n))
            if not chunk:
                return {"path": path, "bytes": n, "sha256": h.hexdigest()}
            n += len(chunk)
            h.update(chunk)
    return {"path": path, "bytes_read": n, "sha256": None, "note": "larger than cap, no digest"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform", required=True, choices=["macos-native", "linux-llvm"])
    ap.add_argument("--fixture-dir", required=True)
    ap.add_argument("--out", required=True, help="new run directory")
    ap.add_argument("--otool", required=True, help="absolute path of the trusted otool")
    ap.add_argument("--lipo", required=True, help="absolute path of the trusted lipo")
    ap.add_argument("--file", default="/usr/bin/file")
    ap.add_argument("--od", default="/usr/bin/od")
    ap.add_argument("--input", action="append", default=[], help="fixture path relative to --fixture-dir")
    ap.add_argument("--inputs-from", help="file with one relative fixture path per line (at most 64 KiB)")
    ap.add_argument("--arch", action="append", help="default arm64 and x86_64")
    ap.add_argument("--timeout", type=float, default=20.0, help="wall seconds per case")
    ap.add_argument("--grace", type=float, default=2.0, help="seconds for drain and reap after SIGKILL")
    ap.add_argument("--max-input-bytes", type=int, default=1 << 20)
    ap.add_argument("--max-stdout-bytes", type=int, default=1 << 20)
    ap.add_argument("--max-stderr-bytes", type=int, default=64 << 10)
    ap.add_argument("--max-tool-hash-bytes", type=int, default=256 << 20)
    args = ap.parse_args(argv)
    if args.platform == "macos-native" and sys.platform != "darwin":
        ap.error("macos-native needs macOS")
    if signal.getsignal(signal.SIGCHLD) == signal.SIG_IGN:
        ap.error("SIGCHLD is ignored; children would be reaped automatically")
    for t in (args.otool, args.lipo, args.file, args.od):
        if not os.path.isabs(t):
            ap.error("tool paths must be absolute: %s" % t)
    inputs = list(args.input)
    if args.inputs_from:
        with open(args.inputs_from, "rb") as fp:
            data = fp.read((64 << 10) + 1)
        if len(data) > 64 << 10:
            ap.error("--inputs-from is larger than 64 KiB")
        inputs += [l for l in data.decode("utf-8").splitlines() if l.strip()]
    if not inputs:
        ap.error("no inputs selected")
    archs = args.arch or ["arm64", "x86_64"]
    root = os.path.abspath(args.fixture_dir)
    if os.path.lexists(args.out):
        ap.error("--out must not exist: %s" % args.out)
    os.makedirs(os.path.join(args.out, "cases"))
    out = os.path.abspath(args.out)
    n = [0]

    def write(name, data, mode="xb"):
        with open(os.path.join(out, name), mode) as fp:
            fp.write(data)

    def case(label, argv):
        n[0] += 1
        cid = "c%05d" % n[0]
        res, so, se = run_case(argv, root, args.timeout, args.max_stdout_bytes, args.max_stderr_bytes, args.grace)
        res["label"] = label
        write("cases/%s.cmd" % cid, ("label: %s\nargv: %s\n" % (label, json.dumps(argv))).encode())
        write("cases/%s.stdout" % cid, so)
        write("cases/%s.stderr" % cid, se)
        write("cases/%s.rc" % cid, (res["rc"] + "\n").encode())
        write("cases/%s.capture.json" % cid, (json.dumps(res, indent=2, sort_keys=True) + "\n").encode())
        write("index.tsv", ("%s\t%s\n" % (cid, label)).encode(), "ab")
        return res

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta = {"platform": args.platform, "start_utc": started, "timeout_s": args.timeout, "grace_s": args.grace,
            "max_input_bytes": args.max_input_bytes, "max_stdout_bytes": args.max_stdout_bytes,
            "max_stderr_bytes": args.max_stderr_bytes, "archs": " ".join(archs), "otool": args.otool, "lipo": args.lipo,
            "file": args.file, "od": args.od, "python": sys.version.split()[0], "env": ENV, "wrapper": "replay_bounded.py"}
    case("identity uname", ["/usr/bin/uname", "-a"])
    if args.platform == "macos-native":
        case("identity sw_vers", ["/usr/bin/sw_vers"])
        case("identity otool -version", [args.otool, "-version"])
    case("identity otool --version", [args.otool, "--version"])
    case("identity lipo -version", [args.lipo, "-version"])
    case("identity file --version", [args.file, "--version"])
    meta["tool_sha256"] = [sha256_capped(t, args.max_tool_hash_bytes) for t in (args.otool, args.lipo, args.file, args.od)]

    recs = [check_input(root, rel, args.max_input_bytes) for rel in inputs]
    files = [r for r in recs if r["status"] != "symlink"]
    write("inputs.files", "".join(r["path"] + "\n" for r in files).encode())
    write("inputs.symlinks", "".join(r["path"] + "\n" for r in recs if r["status"] == "symlink").encode())
    write("inputs.sha256", "".join("%s  %s\n" % (r["sha256"], r["path"]) for r in recs if r["status"] == "ok").encode())
    for r in recs:
        if r["status"] != "ok":
            continue
        f = r["path"]
        case("file " + f, [args.file, "-b", f])
        case("magic " + f, [args.od, "-An", "-tx1", "-N4", f])
        case("lipo-info " + f, [args.lipo, "-info", f])
        case("lipo-archs " + f, [args.lipo, "-archs", f])
        case("otool-fatheaders " + f, [args.otool, "-f", f])
        case("otool-loadcommands all " + f, [args.otool, "-arch", "all", "-l", f])
        for a in archs:
            case("otool-loadcommands %s %s" % (a, f), [args.otool, "-arch", a, "-l", f])
            case("otool-dependencies %s %s" % (a, f), [args.otool, "-arch", a, "-L", f])
        r["unchanged_after_cases"] = unchanged(root, r)
    write("inputs.json", (json.dumps(recs, indent=2) + "\n").encode())
    meta.update({"end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cases": n[0]})
    write("run.json", (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode())
    write("run.txt", "".join("%s: %s\n" % (k, meta[k]) for k in ("platform", "start_utc", "end_utc", "archs", "cases", "wrapper")).encode())
    print("replay_bounded: %d cases, %d inputs (%d accepted) in %s" % (n[0], len(recs), sum(r["status"] == "ok" for r in recs), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
