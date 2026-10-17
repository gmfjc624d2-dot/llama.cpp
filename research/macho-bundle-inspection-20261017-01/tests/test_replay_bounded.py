"""Focused tests for scripts/replay_bounded.py and the bounded reads in scripts/classify_replay.py.

Native cases start only finite cooperative fake tools (`python -I -c ...`, at most 3 s of natural
life) in their own new session; nothing else is signalled. No fixture is executed.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rb = load("replay_bounded")
cr = load("classify_replay")


def fake(code):
    return [sys.executable, "-I", "-c", code]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def tmpdir(test):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    return d


def feed_all(cap, data):
    while data and cap.want():
        n = cap.want()
        cap.feed(data[:n])
        data = data[n:]


class StreamCaptureTest(unittest.TestCase):
    def test_exact_limit(self):
        c = rb.StreamCapture(10)
        feed_all(c, b"0123456789")
        c.eof_phase = "capture"
        r = c.record()
        self.assertEqual((r["observed_bytes"], r["retained_bytes"], r["overflow"], r["complete"]), (10, 10, False, True))
        self.assertEqual(r["complete_sha256"], sha(b"0123456789"))
        self.assertFalse(r["observed_is_lower_bound"])

    def test_first_overflow(self):
        c = rb.StreamCapture(10)
        feed_all(c, b"0123456789AB")
        r = c.record()
        self.assertEqual((r["observed_bytes"], r["retained_bytes"], r["overflow"], r["complete"]), (11, 10, True, False))
        self.assertIsNone(r["complete_sha256"])
        self.assertEqual(r["retained_sha256"], sha(b"0123456789"))
        self.assertEqual(c.want(), 0)

    def test_truncated_without_eof(self):
        c = rb.StreamCapture(10)
        c.feed(b"01234")
        r = c.record()
        self.assertFalse(r["complete"])
        self.assertTrue(r["observed_is_lower_bound"])
        self.assertIsNone(r["complete_sha256"])

    def test_eof_after_cleanup_is_not_complete(self):
        c = rb.StreamCapture(10)
        c.feed(b"0123")
        c.eof_phase = "after_cleanup"
        self.assertFalse(c.record()["complete"])

    def test_never_reads_past_limit_plus_one(self):
        c = rb.StreamCapture(3)
        self.assertEqual(c.want(), 4)
        with self.assertRaises(ValueError):
            c.feed(b"12345")


class RunCaseTest(unittest.TestCase):
    def run_case(self, code, timeout=5.0, out_limit=1024, err_limit=1024, grace=1.0, **kw):
        return rb.run_case(fake(code), HERE, timeout, out_limit, err_limit, grace, **kw)

    def test_clean_completion(self):
        res, so, se = self.run_case("import sys; sys.stdout.write('out'); sys.stderr.write('err')")
        self.assertEqual((so, se, res["rc"]), (b"out", b"err", "0"))
        self.assertTrue(res["summary"]["capture_complete"])
        self.assertEqual(res["cleanup"]["group_signal"], "not_sent")
        self.assertEqual(res["streams"]["stdout"]["complete_sha256"], sha(b"out"))

    def test_nonzero_exit_is_recorded_not_judged(self):
        res, _so, _se = self.run_case("import sys; sys.exit(3)")
        self.assertEqual(res["rc"], "3")
        self.assertTrue(res["summary"]["process_completed"])

    def test_exact_limit_process(self):
        res, so, _se = self.run_case("import sys; sys.stdout.write('x' * 4096)", out_limit=4096)
        self.assertEqual(len(so), 4096)
        self.assertTrue(res["streams"]["stdout"]["complete"])
        self.assertTrue(res["summary"]["capture_complete"])

    def test_first_overflow_ends_case(self):
        code = "import sys; sys.stdout.write('x' * 4097); sys.stdout.flush(); sys.stderr.write('e')"
        res, so, _se = self.run_case(code, out_limit=4096)
        o, e = res["streams"]["stdout"], res["streams"]["stderr"]
        self.assertEqual((len(so), o["overflow"], o["observed_bytes"], o["complete"]), (4096, True, 4097, False))
        self.assertIsNone(o["complete_sha256"])
        self.assertIn(res["cleanup"]["group_signal"], ("sent", "no_such_group"))
        self.assertFalse(res["summary"]["capture_complete"])
        # stderr may or may not be drained after the cutoff; only its consistency is checked
        self.assertEqual(e["complete"], e["eof"] == "capture" and not e["overflow"])

    def test_timeout_direct_child(self):
        t0 = time.monotonic()
        res, _so, _se = self.run_case("import time; time.sleep(3)", timeout=0.5)
        self.assertLess(time.monotonic() - t0, 2.9)
        self.assertEqual(res["rc"], "timeout")
        self.assertEqual((res["process"]["timed_out"], res["process"]["signal"], res["cleanup"]["group_signal"]), (True, signal.SIGKILL, "sent"))
        self.assertFalse(res["summary"]["capture_complete"])

    def test_timeout_with_inherited_pipe(self):
        # the direct child exits at once; a grandchild in the same group keeps both pipes open for up to 3 s
        code = ("import subprocess, sys; subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(3)']); "
                "sys.stdout.write('parent done')")
        t0 = time.monotonic()
        res, so, _se = self.run_case(code, timeout=0.7)
        self.assertLess(time.monotonic() - t0, 2.9)
        self.assertEqual(so, b"parent done")
        self.assertEqual(res["process"]["exit_code"], 0)
        self.assertTrue(res["process"]["timed_out"])
        self.assertFalse(res["summary"]["process_completed"])
        self.assertEqual(res["cleanup"]["group_signal"], "sent")
        self.assertNotEqual(res["streams"]["stdout"]["eof"], "capture")
        self.assertFalse(res["summary"]["capture_complete"])

    def test_permission_error_is_not_success(self):
        def deny(*_a):
            raise PermissionError(1, "denied")
        res, _so, _se = self.run_case("import time; time.sleep(1.0)", timeout=0.3, grace=2.5, killpg=deny, kill=deny)
        self.assertTrue(res["cleanup"]["group_signal"].startswith("failed"))
        self.assertTrue(res["cleanup"]["direct_signal"].startswith("failed"))
        self.assertFalse(res["summary"]["cleanup_certain"])
        self.assertFalse(res["summary"]["capture_complete"])

    def test_reaped_elsewhere_stops_signals(self):
        calls = []

        def lost(*_a):
            raise ChildProcessError(10, "no child")
        res, _so, _se = self.run_case("pass", killpg=lambda *a: calls.append(a), waitpid=lost)
        os.waitpid(res["pid"], 0)  # the real child is still ours to reap
        self.assertEqual(calls, [])
        self.assertEqual(res["cleanup"]["reaped"], "by_other")
        self.assertFalse(res["summary"]["capture_complete"])


class CheckInputTest(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir(self)

    def put(self, rel, data):
        p = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fp:
            fp.write(data)
        return p

    def never(self, *_a):
        raise AssertionError("must not open")

    def test_regular_ok(self):
        self.put("a.bin", b"\xcf\xfa\xed\xfe" + b"x" * 60)
        r = rb.check_input(self.d, "a.bin", 64)
        self.assertEqual((r["status"], r["size"], r["magic"]), ("ok", 64, "cffaedfe"))
        self.assertEqual(r["sha256"], sha(b"\xcf\xfa\xed\xfe" + b"x" * 60))

    def test_size_checked_before_open(self):
        self.put("big.bin", b"y" * 65)
        r = rb.check_input(self.d, "big.bin", 64, opener=self.never)
        self.assertEqual((r["status"], r["size"]), ("too_large", 65))
        self.assertNotIn("sha256", r)

    def test_fifo_not_opened(self):
        os.mkfifo(os.path.join(self.d, "f"))
        r = rb.check_input(self.d, "f", 64, opener=self.never)
        self.assertEqual(r["status"], "not_regular")
        self.assertEqual(r["mode"], "0o%o" % stat.S_IFIFO)

    def test_symlinks_not_followed(self):
        self.put("real/a.bin", b"z")
        os.symlink("real/a.bin", os.path.join(self.d, "link"))
        os.symlink("real", os.path.join(self.d, "dirlink"))
        r = rb.check_input(self.d, "link", 64, opener=self.never)
        self.assertEqual((r["status"], r["target"]["text"]), ("symlink", "real/a.bin"))
        self.assertEqual(rb.check_input(self.d, "dirlink/a.bin", 64, opener=self.never)["status"], "parent_not_a_directory")

    def test_bad_paths(self):
        for rel in ("/etc/passwd", "../x", "a//b", "./a"):
            self.assertEqual(rb.check_input(self.d, rel, 64, opener=self.never)["status"], "bad_path")


class ClassifierBoundsTest(unittest.TestCase):
    def make_run(self, cases):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "cases"))
        with open(os.path.join(d, "index.tsv"), "w") as idx:
            for cid, label, rc, out, capture in cases:
                idx.write("%s\t%s\n" % (cid, label))
                for ext, data in ((".rc", rc.encode() + b"\n"), (".stdout", out), (".stderr", b"")):
                    with open(os.path.join(d, "cases", cid + ext), "wb") as fp:
                        fp.write(data)
                if capture is not None:
                    with open(os.path.join(d, "cases", cid + ".capture.json"), "w") as fp:
                        json.dump(capture, fp)
        return d

    def test_read_capped(self):
        d = tmpdir(self)
        p = os.path.join(d, "f")
        with open(p, "wb") as fp:
            fp.write(b"a" * 11)
        self.assertEqual(cr.read_capped(p, 11), (b"a" * 11, True))
        self.assertEqual(cr.read_capped(p, 10), (b"a" * 10, False))

    def test_incomplete_capture_and_oversize_case_are_not_passing(self):
        incomplete = {"summary": {"capture_complete": False, "streams_complete": False, "cleanup_certain": True}, "process": {"timed_out": False}}
        run = self.make_run([
            ("c00001", "lipo-archs f", "0", b"arm64\n", incomplete),
            ("c00002", "otool-dependencies arm64 f", "0", b"x" * 100, None),
            ("c00003", "magic f", "0", b" cf fa ed fe\n", None),
        ])
        cases = cr.load(run, cap=50)
        self.assertEqual(cases["lipo-archs f"]["capture_problem"], "capture_incomplete")
        self.assertFalse(cr.usable(cases["lipo-archs f"]))
        self.assertEqual(cr.outcome(cases["otool-dependencies arm64 f"], "arm64", ["arm64"])[0], "classifier_read_truncated")
        self.assertTrue(cr.usable(cases["magic f"]))


class PreconditionTest(unittest.TestCase):
    def test_ignored_sigchld_refused(self):
        old = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        try:
            with self.assertRaises(SystemExit):
                rb.main(["--platform", "linux-llvm", "--fixture-dir", HERE, "--out", os.path.join(tmpdir(self), "o"),
                         "--otool", "/bin/true", "--lipo", "/bin/true", "--input", "x"])
        finally:
            signal.signal(signal.SIGCHLD, old)


if __name__ == "__main__":
    unittest.main()
