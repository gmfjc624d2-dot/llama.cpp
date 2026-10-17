#!/usr/bin/env python3
# Tests for `llama-completion --completion-report`, see tools/completion/README.md
#
# SyntheticTests use a generated model: the real llama-spm vocab from models/ plus weights that make each
# listed token predict one fixed next token (all other tokens predict </s>). They are deterministic by
# construction and run the real llama-completion binary, sampler, EOG check and antiprompt check.
# This model is a test fixture, not a real model.
#
# ModelCases only use invariants that hold for any decoder-only model. SyntheticModelTests runs them on the synthetic model
# and RealModelTests on --real-model. Without --real-model the real-model run is reported as skipped (NOT_EXECUTED).
#
# FaultTests need --shim (LD_PRELOAD module, Linux only) to fail or signal at a chosen llama_process() call.
# LegacyTests compare against an unmodified build when --base-bin is given.

import argparse
import base64
import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import threading
import time
import unittest

ARGS = argparse.Namespace()
TOK: dict = {}
EOS = -1

# each list is a chain: the model predicts list[i + 1] after list[i]
# "\u2581" is the SentencePiece space marker
W = "\u2581"

CHAINS = [
    # NUL, a 3-byte UTF-8 char split over 3 byte tokens, literal marker text, incomplete UTF-8 at the end
    [W + "bytes", "<0x41>", "<0x00>", "<0xE2>", "<0x82>", "<0xAC>", "[", "end", W + "of", W + "text", "]", "<0xF0>", "</s>"],
    [W + "stop", "ST", "OP", W + "after", W + "more", "</s>"],
    [W + "ST", "OP"],
    ["<s>", W + "hello", W + "world", "</s>"],
    [W + "unknown", W + "x", "<unk>", W + "tail", "</s>"],
    [W + "loop", W + "one", W + "two", W + "three", W + "one"],
]

BYTES_TEXT = b"A\x00\xe2\x82\xac[end of text]\xf0"  # chain 0 without </s>
LOOP_TEXT  = [b" one", b" two", b" three"]

N_EMBD = 64
N_FF   = 64


class Unobserved(Exception):
    pass


# exit status for each reason, see tools/completion/README.md
EXIT_STATUS = {
    "eog":             {0},
    "token_limit":     {0},
    "antiprompt":      {0},
    "context_limit":   {0},
    "runtime_failure": {1, 255},
    "unsupported":     {1},
}


def add_vocab(w, r):
    tokens = r.fields["tokenizer.ggml.tokens"].contents()
    w.add_vocab_size(len(tokens))
    w.add_tokenizer_model("llama")
    w.add_tokenizer_pre("default")
    w.add_token_list(tokens)
    w.add_token_scores(r.fields["tokenizer.ggml.scores"].contents())
    w.add_token_types(r.fields["tokenizer.ggml.token_type"].contents())
    w.add_bos_token_id(r.fields["tokenizer.ggml.bos_token_id"].contents())
    w.add_eos_token_id(r.fields["tokenizer.ggml.eos_token_id"].contents())
    w.add_unk_token_id(r.fields["tokenizer.ggml.unknown_token_id"].contents())
    w.add_add_bos_token(True)
    w.add_add_eos_token(False)


def make_model(vocab_path, out_path, gguf_py):
    sys.path.insert(0, gguf_py)
    import numpy as np
    import gguf

    r = gguf.GGUFReader(vocab_path)
    tokens = r.fields["tokenizer.ggml.tokens"].contents()
    n_vocab = len(tokens)
    tid = {t: i for i, t in enumerate(tokens)}
    eos = r.fields["tokenizer.ggml.eos_token_id"].contents()

    succ = {}
    for chain in CHAINS:
        for a, b in zip(chain, chain[1:]):
            ia, ib = tid[a], tid[b]
            assert succ.get(ia, ib) == ib, f"conflicting successor for {a}"
            succ[ia] = ib
    assert len(succ) + 1 <= N_EMBD

    # state 0 is the sink for tokens without a successor, it predicts </s>
    embd = np.zeros((n_vocab, N_EMBD), dtype=np.float32)
    outw = np.zeros((n_vocab, N_EMBD), dtype=np.float32)
    embd[:, 0] = 1.0
    outw[eos, 0] = 4.0
    for state, (a, b) in enumerate(sorted(succ.items()), start=1):
        embd[a, :] = 0.0
        embd[a, state] = 1.0
        outw[b, state] = 4.0

    w = gguf.GGUFWriter(out_path, "llama")
    w.add_name("completion-report-synthetic")
    w.add_block_count(1)
    w.add_context_length(4096)
    w.add_embedding_length(N_EMBD)
    w.add_feed_forward_length(N_FF)
    w.add_head_count(4)
    w.add_head_count_kv(4)
    w.add_rope_dimension_count(N_EMBD // 4)
    w.add_layer_norm_rms_eps(1e-5)
    add_vocab(w, r)

    # zero attention and FFN outputs, so the residual stream is the token embedding
    def zeros(*shape):
        return np.zeros(shape, dtype=np.float32)

    def ones(n):
        return np.ones((n,), dtype=np.float32)

    w.add_tensor("token_embd.weight",         embd)
    w.add_tensor("output_norm.weight",        ones(N_EMBD))
    w.add_tensor("output.weight",             outw)
    w.add_tensor("blk.0.attn_norm.weight",    ones(N_EMBD))
    w.add_tensor("blk.0.attn_q.weight",       zeros(N_EMBD, N_EMBD))
    w.add_tensor("blk.0.attn_k.weight",       zeros(N_EMBD, N_EMBD))
    w.add_tensor("blk.0.attn_v.weight",       zeros(N_EMBD, N_EMBD))
    w.add_tensor("blk.0.attn_output.weight",  zeros(N_EMBD, N_EMBD))
    w.add_tensor("blk.0.ffn_norm.weight",     ones(N_EMBD))
    w.add_tensor("blk.0.ffn_gate.weight",     zeros(N_FF, N_EMBD))
    w.add_tensor("blk.0.ffn_up.weight",       zeros(N_FF, N_EMBD))
    w.add_tensor("blk.0.ffn_down.weight",     zeros(N_EMBD, N_FF))
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()
    return {t: tid[t] for chain in CHAINS for t in chain}, eos


def make_t5_model(vocab_path, out_path, gguf_py):
    """zero-weight encoder-decoder model, only used to check that it is rejected"""
    sys.path.insert(0, gguf_py)
    import numpy as np
    import gguf

    r = gguf.GGUFReader(vocab_path)
    n_vocab = len(r.fields["tokenizer.ggml.tokens"].contents())
    w = gguf.GGUFWriter(out_path, "t5")
    w.add_name("completion-report-synthetic-t5")
    w.add_block_count(1)
    w.add_context_length(512)
    w.add_embedding_length(N_EMBD)
    w.add_feed_forward_length(N_FF)
    w.add_head_count(4)
    w.add_key_length(N_EMBD // 4)
    w.add_value_length(N_EMBD // 4)
    w.add_layer_norm_rms_eps(1e-6)
    w.add_relative_attn_buckets_count(32)
    w.add_decoder_start_token_id(0)
    add_vocab(w, r)

    def f32(*shape):
        return np.zeros(shape, dtype=np.float32)

    w.add_tensor("token_embd.weight", f32(n_vocab, N_EMBD))
    for p in ["enc", "dec"]:
        w.add_tensor(f"{p}.output_norm.weight", np.ones((N_EMBD,), dtype=np.float32))
        w.add_tensor(f"{p}.blk.0.attn_norm.weight", np.ones((N_EMBD,), dtype=np.float32))
        w.add_tensor(f"{p}.blk.0.ffn_norm.weight", np.ones((N_EMBD,), dtype=np.float32))
        w.add_tensor(f"{p}.blk.0.attn_rel_b.weight", f32(32, 4))
        for t in ["attn_q", "attn_k", "attn_v", "attn_o"] + (["cross_attn_q", "cross_attn_k", "cross_attn_v", "cross_attn_o"] if p == "dec" else []):
            w.add_tensor(f"{p}.blk.0.{t}.weight", f32(N_EMBD, N_EMBD))
        w.add_tensor(f"{p}.blk.0.ffn_up.weight", f32(N_FF, N_EMBD))
        w.add_tensor(f"{p}.blk.0.ffn_down.weight", f32(N_EMBD, N_FF))
    w.add_tensor("dec.blk.0.cross_attn_norm.weight", np.ones((N_EMBD,), dtype=np.float32))
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()


def gguf_eos(path, gguf_py):
    sys.path.insert(0, gguf_py)
    import gguf
    return int(gguf.GGUFReader(path).fields["tokenizer.ggml.eos_token_id"].contents())


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_report(path, pid, returncode):
    """the consumer protocol from README.md: anything that fails here is not an observed result"""
    if returncode is None:
        raise Unobserved("process status unknown")
    if not os.path.lexists(path):
        raise Unobserved("no report file")
    with open(path, "rb") as f:
        raw = f.read()
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Unobserved(f"not one complete JSON document: {e}")
    if not isinstance(obj, dict) or obj.get("schema") != "llama-completion-report" or obj.get("schema_version") != 1:
        raise Unobserved("unknown schema")
    if obj.get("pid") != pid:
        raise Unobserved(f"report pid {obj.get('pid')} is not process {pid} (stale report)")
    data = base64.b64decode(obj["generated"]["base64"], validate=True)
    if len(data) != obj["generated"]["n_bytes"]:
        raise Unobserved("n_bytes does not match the decoded data")
    if obj["reason"] == "cancelled" and isinstance(obj.get("signal"), int):
        expected = {128 + obj["signal"]}
    else:
        expected = EXIT_STATUS.get(obj["reason"], set())
    if returncode not in expected:
        raise Unobserved(f"exit status {returncode} does not match reason {obj['reason']}")
    return obj, data


class Result:
    def __init__(self, cmd, proc, out, err, path, case_dir):
        self.cmd = cmd
        self.pid = proc.pid
        self.rc = proc.returncode
        self.stdout = out
        self.stderr = err
        self.path = path
        self.case_dir = case_dir

    def report(self):
        return load_report(self.path, self.pid, self.rc)


def case_dir(name):
    # each run dir is new, so a case dir (and its report path) is never reused
    d = os.path.join(ARGS.work_dir, "cases", name)
    os.makedirs(d)
    return d


def save_case(d, cmd, env_extra, proc_rc, out, err):
    with open(os.path.join(d, "cmd.json"), "w") as f:
        json.dump({"cmd": cmd, "env": env_extra or {}, "returncode": proc_rc}, f, indent=2)
    with open(os.path.join(d, "stdout.bin"), "wb") as f:
        f.write(out)
    with open(os.path.join(d, "stderr.txt"), "wb") as f:
        f.write(err)


def base_cmd(binary, model):
    return [binary, "-m", model, "-t", "2", "--temp", "0", "--top-k", "1", "-s", "1"]


def start(name, args, model, report=True, binary=None, env_extra=None, preexec_fn=None, report_path=None):
    d = case_dir(name)
    path = report_path or os.path.join(d, "report.json")
    cmd = base_cmd(binary or ARGS.completion, model) + args
    if report:
        cmd += ["--completion-report", path]
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=d, preexec_fn=preexec_fn)
    return d, path, cmd, proc


def run(name, args, model, report=True, binary=None, env_extra=None, preexec_fn=None, report_path=None, timeout=300):
    d, path, cmd, proc = start(name, args, model, report, binary, env_extra, preexec_fn, report_path)
    out, err = proc.communicate(timeout=timeout)
    save_case(d, cmd, env_extra, proc.returncode, out, err)
    return Result(cmd, proc, out, err, path, d)


def run_and_signal(name, args, model, sig, report=True, binary=None, min_bytes=32, timeout=300):
    """start a long run, wait until it printed generated text, then send `sig` from outside"""
    d, path, cmd, proc = start(name, args, model, report=report, binary=binary)
    out = bytearray()
    err = bytearray()
    seen = threading.Event()

    def read_out():
        while True:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) >= min_bytes:
                seen.set()

    def read_err():
        for chunk in iter(lambda: os.read(proc.stderr.fileno(), 4096), b""):
            err.extend(chunk)

    threads = [threading.Thread(target=read_out), threading.Thread(target=read_err)]
    for t in threads:
        t.start()
    if not seen.wait(timeout):
        proc.kill()
        raise AssertionError("no generated output before timeout")
    sent_at = len(out)
    proc.send_signal(sig)
    proc.wait(timeout=timeout)
    for t in threads:
        t.join()
    save_case(d, cmd, {"external_signal": int(sig), "stdout_bytes_before_signal": sent_at}, proc.returncode, bytes(out), bytes(err))
    return Result(cmd, proc, bytes(out), bytes(err), path, d)


def limit_file_size():
    """files written by the child fail after 64 bytes with EFBIG"""
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (64, 64))


class Base(unittest.TestCase):
    model = None

    def ok(self, r, reason, rc=0):
        self.assertEqual(r.rc, rc, r.stderr.decode(errors="replace")[-3000:])
        rep, data = r.report()
        self.assertEqual(rep["reason"], reason)
        self.assertEqual(rep["last_token"] is None, rep["n_generated"] == 0)
        return rep, data


class SyntheticTests(Base):
    """deterministic synthetic fixture, see CHAINS"""

    def run_s(self, name, args, **kw):
        return run("synthetic-" + name, ["-no-cnv"] + args, ARGS.synthetic_model, **kw)

    # A. budget
    def test_a_budget_zero(self):
        rep, data = self.ok(self.run_s("budget-zero", ["-p", "bytes", "-n", "0"]), "token_limit")
        self.assertEqual(rep["n_generated"], 0)
        self.assertEqual(data, b"")
        self.assertIs(rep["budget_exhausted"], True)
        self.assertIsNone(rep["last_token"])
        self.assertIsNone(rep["eog"])

    def test_a_budget_one(self):
        rep, data = self.ok(self.run_s("budget-one", ["-p", "bytes", "-n", "1"]), "token_limit")
        self.assertEqual(rep["n_generated"], 1)
        self.assertEqual(data, b"A")
        self.assertIs(rep["budget_exhausted"], True)
        self.assertEqual(rep["last_token"], {"id": TOK["<0x41>"], "eog": False, "n_bytes": 1})

    def test_a_eog_in_last_budget_slot(self):
        rep, data = self.ok(self.run_s("eog-last-slot", ["-p", "bytes", "-n", "12"]), "eog")
        self.assertEqual(rep["n_generated"], 12)
        self.assertIs(rep["budget_exhausted"], True)
        self.assertEqual(rep["eog"], {"id": EOS, "origin": "generated"})
        self.assertEqual(data, BYTES_TEXT)

    # B. EOG
    def test_b_eog_empty_piece(self):
        r = self.run_s("eog", ["-p", "bytes", "-n", "20"])
        rep, data = self.ok(r, "eog")
        self.assertEqual(rep["n_generated"], 12)
        self.assertIs(rep["budget_exhausted"], False)
        self.assertEqual(rep["last_token"], {"id": EOS, "eog": True, "n_bytes": 0})
        self.assertEqual(data, BYTES_TEXT)
        self.assertIn(b" [end of text]\n", r.stdout)  # console marker, not in the report bytes

    def test_b_literal_marker_is_text(self):
        r = self.run_s("literal-marker", ["-p", "bytes", "-n", "11"])
        rep, data = self.ok(r, "token_limit")
        self.assertEqual(data, BYTES_TEXT)
        self.assertIn(b"[end of text]", data)
        self.assertIs(rep["last_token"]["eog"], False)
        self.assertIsNone(rep["eog"])

    def test_b_eog_render_special(self):
        rep, data = self.ok(self.run_s("eog-special", ["-p", "bytes", "-n", "20", "-sp"]), "eog")
        self.assertIs(rep["generated"]["render_special"], True)
        self.assertEqual(data, BYTES_TEXT + b"</s>")
        self.assertEqual(rep["last_token"], {"id": EOS, "eog": True, "n_bytes": 4})

    def test_b_eog_from_prompt(self):
        rep, data = self.ok(self.run_s("eog-prompt", ["-p", "hello</s>", "-n", "5"]), "eog")
        self.assertEqual(rep["n_generated"], 0)
        self.assertEqual(rep["eog"], {"id": EOS, "origin": "prompt"})
        self.assertEqual(data, b"")

    # C. antiprompt
    def test_c_antiprompt_across_pieces(self):
        rep, data = self.ok(self.run_s("ap-pieces", ["-p", "stop", "-r", "STOP", "-n", "5"]), "antiprompt")
        self.assertEqual(data, b"STOP")
        self.assertEqual(rep["n_generated"], 2)
        self.assertIs(rep["budget_exhausted"], False)
        self.assertEqual(rep["antiprompt"], {"text": {"index": 0, "origin": "generated"}, "token": None})

    def test_c_antiprompt_single_piece_and_index(self):
        rep, data = self.ok(self.run_s("ap-index", ["-p", "stop", "-r", "zzz", "-r", "after", "-n", "5"]), "antiprompt")
        self.assertEqual(data, b"STOP after")
        self.assertEqual(rep["antiprompt"]["text"], {"index": 1, "origin": "generated"})

    def test_c_antiprompt_and_budget(self):
        rep, data = self.ok(self.run_s("ap-budget", ["-p", "stop", "-r", "STOP", "-n", "2"]), "antiprompt")
        self.assertEqual(data, b"STOP")
        self.assertIs(rep["budget_exhausted"], True)

    def test_c_antiprompt_single_token(self):
        rep, data = self.ok(self.run_s("ap-token", ["-p", "unknown", "-r", "<unk>", "-n", "8"]), "antiprompt")
        self.assertEqual(rep["last_token"]["id"], TOK["<unk>"])
        self.assertEqual(rep["antiprompt"]["token"], {"index": 0, "origin": "generated"})
        # the history renders control tokens, so the text check matches the same step
        self.assertEqual(rep["antiprompt"]["text"], {"index": 0, "origin": "generated"})
        self.assertEqual(data, b" x")  # <unk> renders empty without --special

    def test_c_antiprompt_and_eog(self):
        rep, data = self.ok(self.run_s("ap-eog", ["-p", "bytes", "-r", "</s>", "-n", "20"]), "eog")
        self.assertEqual(rep["eog"], {"id": EOS, "origin": "generated"})
        self.assertEqual(rep["antiprompt"], {"text": {"index": 0, "origin": "generated"}, "token": {"index": 0, "origin": "generated"}})
        self.assertEqual(data, BYTES_TEXT)

    def test_c_antiprompt_from_prompt(self):
        rep, data = self.ok(self.run_s("ap-prompt", ["-p", "STOP", "-r", "STOP", "-n", "5"]), "antiprompt")
        self.assertEqual(rep["n_generated"], 0)
        self.assertEqual(data, b"")
        self.assertEqual(rep["antiprompt"]["text"], {"index": 0, "origin": "prompt"})

    def test_c_antiprompt_across_boundary(self):
        rep, data = self.ok(self.run_s("ap-boundary", ["-p", "go ST", "-r", "STOP", "-n", "5"]), "antiprompt")
        self.assertEqual(data, b"OP")
        self.assertEqual(rep["antiprompt"]["text"], {"index": 0, "origin": "prompt_and_generated"})

    def test_c_antiprompt_window_limit(self):
        # the text check only looks at the last len(antiprompt) + 2 bytes, "af" is followed by "ter" in one piece
        rep, data = self.ok(self.run_s("ap-window", ["-p", "stop", "-r", "af", "-n", "10"]), "eog")
        self.assertIn(b"af", data)
        self.assertIsNone(rep["antiprompt"])

    # D. prompt/generation boundary
    def test_d_display_prompt_does_not_change_output(self):
        a = self.run_s("display-on",  ["-p", "go ST", "-n", "6", "--display-prompt"])
        b = self.run_s("display-off", ["-p", "go ST", "-n", "6", "--no-display-prompt"])
        ra, da = self.ok(a, "eog")
        rb, db = self.ok(b, "eog")
        self.assertNotEqual(a.stdout, b.stdout)
        self.assertEqual(da, db)
        self.assertEqual(da, b"OP after more")
        self.assertEqual(ra["n_generated"], rb["n_generated"])

    def test_d_batch_size_one(self):
        a = self.run_s("batch-default", ["-p", "go ST", "-n", "6"])
        b = self.run_s("batch-one",     ["-p", "go ST", "-n", "6", "-b", "1", "-ub", "1"])
        ra, da = self.ok(a, "eog")
        rb, db = self.ok(b, "eog")
        self.assertEqual(ra["n_prompt_tokens"], 3)
        self.assertEqual(rb["n_prompt_tokens"], 3)
        self.assertEqual(da, db)
        self.assertEqual(ra["n_generated"], rb["n_generated"])

    def test_d_one_token_prompt(self):
        for disp in ["--display-prompt", "--no-display-prompt"]:
            rep, data = self.ok(self.run_s("one-token-prompt" + disp, ["-p", "", "-n", "8", disp]), "eog")
            self.assertEqual(rep["n_prompt_tokens"], 1)
            self.assertEqual(data, b" hello world")
            self.assertEqual(rep["n_generated"], 3)

    def test_d_conversation_auto_off(self):
        # no chat template in the model, so the default conversation mode resolves to off
        r = run("synthetic-cnv-auto", ["-p", "stop", "-n", "1"], ARGS.synthetic_model)
        rep, data = self.ok(r, "token_limit")
        self.assertEqual(data, b"ST")

    # E. context
    def test_e_context_limit(self):
        rep, data = self.ok(self.run_s("ctx-limit", ["-p", "loop", "-c", "8", "-n", "1000"]), "context_limit")
        self.assertEqual(rep["n_ctx"], 256)
        self.assertEqual(rep["n_prompt_tokens"], 2)
        # the last sampled token is not decoded: n_past + 1 >= n_ctx is checked before its decode
        self.assertEqual(rep["n_generated"], rep["n_ctx"] - rep["n_prompt_tokens"])
        self.assertIs(rep["budget_exhausted"], False)
        self.assertEqual(rep["n_context_shifts"], 0)
        self.assertEqual(data, b"".join(LOOP_TEXT[i % 3] for i in range(rep["n_generated"])))

    def test_e_budget_ends_before_context(self):
        rep, _ = self.ok(self.run_s("ctx-budget", ["-p", "loop", "-c", "8", "-n", "254"]), "token_limit")
        self.assertEqual(rep["n_generated"], 254)
        self.assertIs(rep["budget_exhausted"], True)
        rep, _ = self.ok(self.run_s("ctx-budget-plus-one", ["-p", "loop", "-c", "8", "-n", "255"]), "context_limit")
        self.assertEqual(rep["n_generated"], 254)

    def test_e_context_shift(self):
        rep, data = self.ok(self.run_s("ctx-shift", ["-p", "loop", "-c", "8", "-n", "600", "--context-shift"]), "token_limit")
        self.assertGreaterEqual(rep["n_context_shifts"], 1)
        self.assertEqual(rep["n_generated"], 600)
        self.assertEqual(data, b"".join(LOOP_TEXT[i % 3] for i in range(600)))

    # F. cancellation from outside the process
    def long_args(self):
        return ["-p", "loop", "-c", "512", "-n", "2000000", "--context-shift", "--no-display-prompt"]

    def check_cancelled(self, r, signo):
        self.assertEqual(r.rc, 128 + signo, r.stderr.decode(errors="replace")[-3000:])
        rep, data = r.report()
        self.assertEqual(rep["reason"], "cancelled")
        self.assertEqual(rep["signal"], signo)
        self.assertGreater(rep["n_generated"], 0)
        self.assertEqual(data, b"".join(LOOP_TEXT[i % 3] for i in range(rep["n_generated"])))
        # the prompt is not displayed, so stdout is the generated text plus the final newlines
        self.assertEqual(r.stdout, data + b"\n\n")
        return rep

    def test_f_external_sigint(self):
        self.check_cancelled(run_and_signal("synthetic-ext-sigint", ["-no-cnv"] + self.long_args(), ARGS.synthetic_model, signal.SIGINT), signal.SIGINT)

    def test_f_external_sigterm(self):
        self.check_cancelled(run_and_signal("synthetic-ext-sigterm", ["-no-cnv"] + self.long_args(), ARGS.synthetic_model, signal.SIGTERM), signal.SIGTERM)

    def test_f_sigkill_leaves_no_report(self):
        r = run_and_signal("synthetic-ext-sigkill", ["-no-cnv"] + self.long_args(), ARGS.synthetic_model, signal.SIGKILL)
        self.assertEqual(r.rc, -signal.SIGKILL)
        self.assertFalse(os.path.lexists(r.path))
        with self.assertRaises(Unobserved):
            r.report()

    def test_f_incomplete_report_rejected(self):
        r = self.run_s("truncated-source", ["-p", "bytes", "-n", "3"])
        self.ok(r, "token_limit")
        with open(r.path, "rb") as f:
            full = f.read()
        for n in [0, 1, len(full) // 2, len(full) - 3]:
            p = os.path.join(r.case_dir, f"truncated-{n}.json")
            with open(p, "wb") as f:
                f.write(full[:n])
            with self.assertRaises(Unobserved):
                load_report(p, r.pid, r.rc)
        # a finished file from a process that is still running (status unknown) is not accepted either
        with self.assertRaises(Unobserved):
            load_report(r.path, r.pid, None)

    # G. failures and unsupported modes
    def test_g_missing_model(self):
        r = run("synthetic-missing-model", ["-no-cnv", "-p", "x", "-n", "4"], os.path.join(ARGS.work_dir, "does-not-exist.gguf"))
        rep, _ = self.ok(r, "runtime_failure", rc=1)
        self.assertEqual(rep["error"], {"stage": "init", "code": None, "unsupported": None})
        self.assertIsNone(rep["n_ctx"])
        self.assertIsNone(rep["budget_exhausted"])

    def test_g_invalid_model(self):
        bad = os.path.join(ARGS.work_dir, "invalid.gguf")
        with open(bad, "wb") as f:
            f.write(b"GGUF" + b"\xff" * 60)
        rep, _ = self.ok(run("synthetic-invalid-model", ["-no-cnv", "-p", "x", "-n", "4"], bad), "runtime_failure", rc=1)
        self.assertEqual(rep["error"]["stage"], "init")

    def test_g_prompt_too_long(self):
        rep, _ = self.ok(self.run_s("prompt-too-long", ["-p", "loop " * 300, "-c", "8", "-n", "4"]), "runtime_failure", rc=1)
        self.assertEqual(rep["error"]["stage"], "prompt_too_long")
        self.assertGreater(rep["n_prompt_tokens"], rep["n_ctx"] - 4)

    def test_g_unsupported(self):
        cases = [
            ("interactive",  ["-no-cnv", "-i"]),
            ("interactive",  ["-no-cnv", "-if"]),
            ("conversation", ["-cnv"]),
            ("n_predict",    ["-no-cnv"]),
            ("n_predict",    ["-no-cnv", "-n", "-2"]),
            ("prompt_cache", ["-no-cnv", "--prompt-cache", "cache.bin"]),
            ("self_extend",  ["-no-cnv", "-gan", "2", "-gaw", "16"]),
        ]
        for i, (name, extra) in enumerate(cases):
            with self.subTest(name=name, args=extra):
                args = ["-p", "stop"] + extra
                if "-n" not in extra and name != "n_predict":
                    args += ["-n", "4"]
                r = run(f"synthetic-unsupported-{i}", args, ARGS.synthetic_model)
                rep, data = self.ok(r, "unsupported", rc=1)
                self.assertEqual(rep["error"], {"stage": "config", "code": None, "unsupported": name})
                self.assertEqual(data, b"")
                self.assertFalse(os.path.exists(os.path.join(r.case_dir, "cache.bin")))

    def test_g_unsupported_encoder_decoder(self):
        r = run("synthetic-unsupported-t5", ["-no-cnv", "-p", "x", "-n", "4"], ARGS.t5_model)
        rep, _ = self.ok(r, "unsupported", rc=1)
        self.assertEqual(rep["error"], {"stage": "config", "code": None, "unsupported": "encoder_decoder"})
        self.assertIsNotNone(rep["n_ctx"])  # the model and context loaded, this is not a load failure

    def test_g_existing_destination(self):
        old = self.run_s("stale-source", ["-p", "bytes", "-n", "1"])
        self.ok(old, "token_limit")
        with open(old.path, "rb") as f:
            stale = f.read()
        r = self.run_s("stale", ["-p", "stop", "-n", "2"], report_path=old.path)
        self.assertEqual(r.rc, 1)
        self.assertIn(b"already exists", r.stderr)
        with open(old.path, "rb") as f:
            self.assertEqual(f.read(), stale)
        with self.assertRaises(Unobserved):
            load_report(old.path, r.pid, r.rc)

    def test_g_dangling_symlink_destination(self):
        d = case_dir("synthetic-symlink-target")
        target = os.path.join(d, "target.json")
        link = os.path.join(d, "link.json")
        os.symlink(target, link)
        r = self.run_s("symlink", ["-p", "stop", "-n", "2"], report_path=link)
        self.assertEqual(r.rc, 1)
        self.assertFalse(os.path.exists(target))

    def test_g_missing_directory(self):
        path = os.path.join(ARGS.work_dir, "no-such-dir", "report.json")
        r = self.run_s("missing-dir", ["-p", "stop", "-n", "2"], report_path=path)
        self.assertEqual(r.rc, 1)
        self.assertIn(b"failed to create report file", r.stderr)
        self.assertFalse(os.path.lexists(path))

    def test_g_write_failure(self):
        r = self.run_s("write-failure", ["-p", "stop", "-n", "2"], preexec_fn=limit_file_size)
        self.assertEqual(r.rc, 1)
        self.assertIn(b"failed to write report file", r.stderr)
        # the partial file is kept, the exit status and the consumer rules reject it
        self.assertTrue(os.path.exists(r.path), "the partial report was removed")
        self.assertEqual(os.path.getsize(r.path), 64)
        with self.assertRaises(Unobserved):
            r.report()

    # H. byte transport through the real serialization path
    def test_h_bytes_round_trip(self):
        r = self.run_s("bytes", ["-p", "bytes", "-n", "11"])
        rep, data = self.ok(r, "token_limit")
        with open(r.path, "rb") as f:
            raw = f.read()
        raw.decode("ascii")  # base64 keeps the file ASCII
        self.assertEqual(rep["generated"]["n_bytes"], 19)
        self.assertEqual(data, BYTES_TEXT)
        self.assertEqual(data.count(b"\x00"), 1)
        self.assertEqual(base64.b64encode(data).decode(), rep["generated"]["base64"])
        with self.assertRaises(UnicodeDecodeError):
            data.decode("utf-8")  # the trailing 0xF0 stays invalid, nothing is replaced
        self.assertEqual(data[:-1].decode("utf-8"), "A\x00\u20ac[end of text]")


class FaultTests(Base):
    """fault injection with the LD_PRELOAD shim, synthetic model"""

    def setUp(self):
        if not ARGS.shim:
            self.skipTest("NOT_EXECUTED: no LD_PRELOAD shim (needs Linux and shared libs)")

    def run_f(self, name, args, at, action):
        env = {"LD_PRELOAD": ARGS.shim, "CR_SHIM_AT": str(at), "CR_SHIM_ACTION": action}
        r = run("fault-" + name, ["-no-cnv", "--no-warmup"] + args, ARGS.synthetic_model, env_extra=env)
        self.assertIn(b"test-completion-report-shim: decode call", r.stderr)
        return r

    def test_g_decode_failure_prompt(self):
        rep, data = self.ok(self.run_f("decode-prompt", ["-p", "loop", "-n", "10"], 1, "fail"), "runtime_failure", rc=1)
        self.assertEqual(rep["error"], {"stage": "decode_prompt", "code": None, "unsupported": None})
        self.assertEqual(rep["n_generated"], 0)
        self.assertIsNone(rep["signal"])

    def test_g_decode_failure_generated(self):
        rep, data = self.ok(self.run_f("decode-generated", ["-p", "loop", "-n", "10"], 3, "fail"), "runtime_failure", rc=1)
        self.assertEqual(rep["error"]["stage"], "decode_generated")
        # call 1 is the prompt, calls 2 and 3 decode the first two sampled tokens
        self.assertEqual(rep["n_generated"], 2)
        self.assertEqual(data, b" one two")
        self.assertIs(rep["budget_exhausted"], False)

    def test_f_signal_with_failure_is_failure(self):
        rep, _ = self.ok(self.run_f("sigint-fail", ["-p", "loop", "-n", "10"], 3, "sigint_fail"), "runtime_failure", rc=1)
        self.assertEqual(rep["signal"], signal.SIGINT)
        self.assertEqual(rep["error"]["stage"], "decode_generated")

    def test_f_sigint_cooperative(self):
        r = self.run_f("sigint", ["-p", "loop", "-n", "10"], 5, "sigint")
        rep, data = self.ok(r, "cancelled", rc=130)
        self.assertEqual(rep["signal"], signal.SIGINT)
        # the flag is set during decode call 5, one more token is sampled before the loop checks it
        self.assertEqual(rep["n_generated"], 5)
        self.assertEqual(data, b" one two three one two")

    def test_f_sigterm_cooperative(self):
        rep, _ = self.ok(self.run_f("sigterm", ["-p", "loop", "-n", "10"], 2, "sigterm"), "cancelled", rc=143)
        self.assertEqual(rep["signal"], signal.SIGTERM)
        self.assertEqual(rep["n_generated"], 2)

    def test_f_signal_during_prompt(self):
        rep, data = self.ok(self.run_f("sigint-prompt", ["-p", "loop", "-n", "10"], 1, "sigint"), "cancelled", rc=130)
        self.assertEqual(rep["n_generated"], 1)

    def run_swap(self, name, spec, preexec_fn=None):
        """another actor moves the new report away and puts an unrelated file at its path before fdopen()"""
        d = case_dir("fault-" + name + "-target")
        path = os.path.join(d, "report.json")
        env = {"LD_PRELOAD": ARGS.shim, "CR_SHIM_FDOPEN": spec + ":" + path}
        r = run("fault-" + name, ["-no-cnv", "-p", "stop", "-n", "2"], ARGS.synthetic_model, env_extra=env, report_path=path, preexec_fn=preexec_fn)
        self.assertIn(b"test-completion-report-shim: fdopen: moved the report", r.stderr)
        self.assertEqual(r.rc, 1)
        # the unrelated file at the report path is not removed or changed
        self.assertTrue(os.path.exists(path), "the unrelated file at the report path was removed")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"unrelated file\n")
        with self.assertRaises(Unobserved):
            load_report(path, r.pid, r.rc)
        with self.assertRaises(Unobserved):
            load_report(path + ".moved", r.pid, r.rc)
        return path + ".moved"

    def test_g_publish_swap_fdopen_failure(self):
        moved = self.run_swap("swap-fdopen-failure", "swap_fail")
        self.assertEqual(os.path.getsize(moved), 0)

    def test_g_publish_swap_write_failure(self):
        moved = self.run_swap("swap-write-failure", "swap", preexec_fn=limit_file_size)
        self.assertEqual(os.path.getsize(moved), 64)

    def test_g_destination_created_during_run(self):
        d = case_dir("fault-created-during-run-target")
        path = os.path.join(d, "report.json")
        env = {"LD_PRELOAD": ARGS.shim, "CR_SHIM_AT": "2", "CR_SHIM_ACTION": "touch:" + path}
        r = run("fault-created-during-run", ["-no-cnv", "--no-warmup", "-p", "loop", "-n", "4"], ARGS.synthetic_model, env_extra=env, report_path=path)
        self.assertEqual(r.rc, 1)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"unrelated file\n")
        with self.assertRaises(Unobserved):
            load_report(path, r.pid, r.rc)


class ModelCases(Base):
    """invariants for any decoder-only model; the subclass picks the model, this class is not run itself"""

    prompt = None
    label = None

    def setUp(self):
        if self.model is None:
            self.skipTest(f"NOT_EXECUTED: no {self.label} model")

    def run_m(self, name, args, **kw):
        return run(f"{self.label}-{name}", ["-no-cnv", "-p", self.prompt] + args, self.model, **kw)

    def test_budget_zero(self):
        rep, data = self.ok(self.run_m("budget-zero", ["-n", "0"]), "token_limit")
        self.assertEqual((rep["n_generated"], data), (0, b""))

    def test_budget_small(self):
        rep, data = self.ok(self.run_m("budget-4", ["-n", "4", "--ignore-eos"]), "token_limit")
        self.assertEqual(rep["n_generated"], 4)
        self.assertIs(rep["last_token"]["eog"], False)

    def test_forced_eog(self):
        eos = gguf_eos(self.model, ARGS.gguf_py)
        rep, data = self.ok(self.run_m("forced-eog", ["-n", "8", "--logit-bias", f"{eos}+100"]), "eog")
        self.assertEqual(rep["n_generated"], 1)
        self.assertEqual(rep["eog"], {"id": eos, "origin": "generated"})
        self.assertEqual(rep["last_token"], {"id": eos, "eog": True, "n_bytes": 0})
        self.assertEqual(data, b"")

    def test_antiprompt_from_previous_output(self):
        _, first = self.ok(self.run_m("ap-source", ["-n", "3", "--ignore-eos"]), "token_limit")
        try:
            stop = first.decode("utf-8").strip()
        except UnicodeDecodeError:
            stop = ""
        if not stop or "\\" in stop or "\x00" in stop:
            self.skipTest("NOT_EXECUTED: first tokens are not usable as -r text")
        rep, data = self.ok(self.run_m("ap", ["-n", "16", "--ignore-eos", "-r", stop]), "antiprompt")
        self.assertLessEqual(rep["n_generated"], 3)
        self.assertTrue(first.startswith(data))
        self.assertIsNotNone(rep["antiprompt"]["text"])

    def test_display_prompt(self):
        _, a = self.ok(self.run_m("display-on",  ["-n", "8", "--ignore-eos"]), "token_limit")
        _, b = self.ok(self.run_m("display-off", ["-n", "8", "--ignore-eos", "--no-display-prompt"]), "token_limit")
        self.assertEqual(a, b)

    def test_context_limit(self):
        rep, _ = self.ok(self.run_m("ctx", ["-c", "8", "-n", "100000", "--ignore-eos"]), "context_limit")
        self.assertEqual(rep["n_generated"], rep["n_ctx"] - rep["n_prompt_tokens"])

    def test_external_sigint(self):
        r = run_and_signal(f"{self.label}-ext-sigint", ["-no-cnv", "-p", self.prompt, "-n", "2000000", "--ignore-eos",
                           "--context-shift", "-c", "256", "--no-display-prompt"], self.model, signal.SIGINT)
        rep, data = self.ok(r, "cancelled", rc=130)
        self.assertGreater(rep["n_generated"], 0)


class SyntheticModelTests(ModelCases):
    prompt = "loop"
    label = "synthetic-agnostic"


class RealModelTests(ModelCases):
    prompt = "Once upon a time"
    label = "real"


def legacy_filter(err):
    """drop the per-line log timestamp and the measured times in the perf summary, nothing else"""
    keep = []
    for line in err.decode(errors="replace").splitlines():
        line = re.sub(r"^\d+\.\d+\.\d+\.\d+ ", "", line)
        if "common_perf_print:" in line:
            line = re.sub(r"\s*\d+\.\d+", " #", line)
        keep.append(line)
    return keep


class LegacyTests(Base):
    """without --completion-report: no report, same output as the base build"""

    INVOCATIONS = [
        ("eog",       ["-p", "bytes", "-n", "20"]),
        ("budget",    ["-p", "bytes", "-n", "11"]),
        ("ap",        ["-p", "stop", "-r", "STOP", "-n", "5"]),
        ("ctx",       ["-p", "loop", "-c", "8", "-n", "1000"]),
        ("ctx-shift", ["-p", "loop", "-c", "8", "-n", "600", "--context-shift"]),
        ("no-n",      ["-p", "loop", "-c", "8"]),
        ("missing",   None),
    ]

    def invocation(self, args):
        if args is None:
            return ["-no-cnv", "-p", "x", "-n", "4"], os.path.join(ARGS.work_dir, "does-not-exist.gguf")
        return ["-no-cnv"] + args, ARGS.synthetic_model

    def test_i_no_report_created(self):
        for name, args in self.INVOCATIONS:
            with self.subTest(name=name):
                a, m = self.invocation(args)
                r = run(f"legacy-new-{name}", a, m, report=False)
                # the case dir is the cwd of the run, only the files written by this script are there
                self.assertEqual(sorted(os.listdir(r.case_dir)), ["cmd.json", "stderr.txt", "stdout.bin"])

    def test_i_same_as_base(self):
        if not ARGS.base_bin:
            self.skipTest("NOT_EXECUTED: no --base-bin")
        for name, args in self.INVOCATIONS:
            with self.subTest(name=name):
                a, m = self.invocation(args)
                new = run(f"legacy-cmp-new-{name}", a, m, report=False)
                old = run(f"legacy-cmp-base-{name}", a, m, report=False, binary=ARGS.base_bin)
                self.assertEqual(new.rc, old.rc)
                self.assertEqual(new.stdout, old.stdout)
                self.assertEqual(legacy_filter(new.stderr), legacy_filter(old.stderr))

    def test_i_legacy_sigint(self):
        for label, binary in [("new", ARGS.completion), ("base", ARGS.base_bin)]:
            if binary is None:
                continue
            with self.subTest(binary=label):
                r = run_and_signal(f"legacy-sigint-{label}", ["-no-cnv", "-p", "loop", "-c", "512", "-n", "2000000", "--context-shift", "--no-display-prompt"],
                                   ARGS.synthetic_model, signal.SIGINT, report=False, binary=binary)
                self.assertEqual(r.rc, 130)
                self.assertIn(b"Interrupted by user", r.stdout)
                self.assertEqual(sorted(os.listdir(r.case_dir)), ["cmd.json", "stderr.txt", "stdout.bin"])


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for c in [SyntheticTests, FaultTests, SyntheticModelTests, RealModelTests, LegacyTests]:
        suite.addTests(loader.loadTestsFromTestCase(c))
    return suite


def test_ids(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from test_ids(t)
        else:
            yield t.id()


def result_records(ids, res):
    """PASS, FAIL, ERROR or NOT_EXECUTED (skipped) per test, a failed subtest fails its test"""
    records = {tid: {"test": tid, "status": "PASS", "detail": ""} for tid in ids}
    for status, entries in [("NOT_EXECUTED", res.skipped), ("FAIL", res.failures), ("ERROR", res.errors)]:
        for t, detail in entries:
            rec = records.setdefault(t.id().split(" ")[0], {"test": t.id(), "status": status, "detail": ""})
            rec["status"] = status
            rec["detail"] += f"{t.id()}: {detail}\n"
    return list(records.values())


def main():
    global TOK, EOS
    p = argparse.ArgumentParser()
    p.add_argument("--bin-dir", required=True)
    p.add_argument("--vocab", required=True)
    p.add_argument("--gguf-py", required=True)
    p.add_argument("--work-dir", required=True)
    p.add_argument("--shim")
    p.add_argument("--base-bin", help="llama-completion built from the unmodified base revision")
    p.add_argument("--real-model", help="a real decoder-only GGUF, e.g. tinyllamas/stories15M-q4_0.gguf")
    p.add_argument("unittest_args", nargs="*")
    p.parse_args(namespace=ARGS)

    ARGS.completion = os.path.join(ARGS.bin_dir, "llama-completion")
    # a new run dir for every invocation, earlier runs and their reports are kept
    os.makedirs(ARGS.work_dir, exist_ok=True)
    ARGS.work_dir = os.path.join(ARGS.work_dir, time.strftime("run-%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{os.getpid()}")
    os.makedirs(ARGS.work_dir)
    sys.stderr.write(f"test-completion-report: run dir {ARGS.work_dir}\n")

    ARGS.synthetic_model = os.path.join(ARGS.work_dir, "synthetic.gguf")
    TOK, EOS = make_model(ARGS.vocab, ARGS.synthetic_model, ARGS.gguf_py)
    ARGS.t5_model = os.path.join(ARGS.work_dir, "synthetic-t5.gguf")
    make_t5_model(ARGS.vocab, ARGS.t5_model, ARGS.gguf_py)
    SyntheticModelTests.model = ARGS.synthetic_model
    RealModelTests.model = ARGS.real_model

    fixtures = {
        "synthetic_model": {"path": ARGS.synthetic_model, "sha256": sha256(ARGS.synthetic_model), "vocab": ARGS.vocab, "vocab_sha256": sha256(ARGS.vocab)},
        "synthetic_t5_model": {"path": ARGS.t5_model, "sha256": sha256(ARGS.t5_model)},
        "real_model": {"path": ARGS.real_model, "sha256": sha256(ARGS.real_model)} if ARGS.real_model else None,
        "base_bin": ARGS.base_bin,
        "shim": ARGS.shim,
    }
    with open(os.path.join(ARGS.work_dir, "fixtures.json"), "w") as f:
        json.dump(fixtures, f, indent=2)

    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    if ARGS.unittest_args:
        suite = unittest.defaultTestLoader.loadTestsFromNames(ARGS.unittest_args, sys.modules[__name__])
    # the suite drops its tests while it runs, so take the ids first
    ids = list(test_ids(suite))
    res = runner.run(suite)
    with open(os.path.join(ARGS.work_dir, "results.json"), "w") as f:
        json.dump(result_records(ids, res), f, indent=2)
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
