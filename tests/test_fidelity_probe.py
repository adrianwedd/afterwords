"""Focused, deterministic, no-GPU tests for scripts/fidelity-probe.py (issue #122).

Everything here runs offline:
  - the matrix/cap/annotation logic is exercised directly through the module,
  - live execution is exercised against a throwaway HTTP server bound to
    127.0.0.1 inside the test process (never the real afterwords server on :7860),
  - the silence detector is exercised against synthetic WAVs written to tmp_path.

No test imports backends, loads MLX, reads voices/, or touches the network.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import struct
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "fidelity-probe.py"
SPEC = importlib.util.spec_from_file_location("fidelity_probe", SCRIPT)
fp = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["fidelity_probe"] = fp
SPEC.loader.exec_module(fp)


# ── synthetic audio helpers ──────────────────────────────────────────────────

SR = 24000


def tone(seconds: float, freq: float = 1000.0, amp: float = 0.5) -> np.ndarray:
    n = int(round(seconds * SR))
    t = np.arange(n) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(round(seconds * SR)), dtype=np.float64)


def write_wav(path: Path, *parts: np.ndarray, sr: int = SR) -> Path:
    data = np.concatenate(parts) if parts else silence(0.0)
    sf.write(str(path), data.astype(np.float32), sr, subtype="PCM_16")
    return path


def plan_for(voices=None, **kwargs):
    defaults = dict(
        repeats=2,
        lang="en",
        endpoint="http://127.0.0.1:7860",
        allow_non_loopback=False,
        send_stripped=False,
        opening_body=fp.DEFAULT_OPENING_BODY,
        pause_body=fp.DEFAULT_PAUSE_BODY,
    )
    defaults.update(kwargs)
    return fp.build_plan(voices or [("picard-qwen3-06b", "qwen3-0.6b")], **defaults)


def run_cli(argv, monkeypatch=None, fail_on_network=True):
    """Invoke the CLI with the network hard-disabled unless a test overrides it.

    Returns the process exit code. argparse errors raise SystemExit(2) and are
    folded back into the return value — that IS the code the operator sees.
    """
    if monkeypatch is not None and fail_on_network:
        def _boom(*a, **k):
            raise AssertionError("probe attempted a network call in a dry-run test")

        monkeypatch.setattr(fp, "_fetch", _boom)
    try:
        return fp.main(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code in (None, "") else 2)


# ── 1. condition pairing: identical body, controlled difference ──────────────

def test_opening_pair_differs_only_by_the_heading_cue():
    plan = plan_for()
    by_id = {r["condition_id"]: r for r in plan["requests"] if r["repeat"] == 1}
    with_cue, plain_cue, without_cue = (
        by_id["opening_heading"], by_id["opening_plain_label"], by_id["opening_no_heading"]
    )

    assert with_cue["family"] == without_cue["family"] == "opening_pair"
    assert with_cue["cue_text"].startswith("## ")
    assert without_cue["cue_text"] == ""
    assert plain_cue["cue_text"] == "Setup cue.\n\n"
    assert {r["text"][len(r["cue_text"]):] for r in (with_cue, plain_cue, without_cue)} == {
        plan["bodies"]["opening_pair"]
    }
    assert fp.opening_tokens(with_cue["expected_spoken_text"])[:2] == \
        fp.opening_tokens(plain_cue["expected_spoken_text"])[:2] == ["setup", "cue"]
    # The heading form is exactly the cue plus the other form's text.
    assert with_cue["text"] == with_cue["cue_text"] + without_cue["text"]
    # …and nothing else about the following words moved.
    assert with_cue["text"][len(with_cue["cue_text"]):] == without_cue["text"]
    # The heading adds two spoken cue words; the body tokens follow in order.
    assert fp.opening_tokens(with_cue["text"]) == ["setup", "cue"] + (
        fp.opening_tokens(with_cue["text"])[2:]
    )
    assert fp.opening_tokens(without_cue["text"])[0] == "the"
    assert without_cue["text"] in with_cue["expected_spoken_text"]


def test_pause_forms_share_one_identical_body():
    plan = plan_for()
    forms = [
        r for r in plan["requests"]
        if r["family"] == "pause_form" and r["repeat"] == 1
    ]
    assert {r["condition_id"] for r in forms} == {
        "pause_heading",
        "pause_punct_only",
        "pause_paragraph_break",
        "pause_none",
    }
    for r in forms:
        # text == cue + body, with the body byte-identical across every form.
        assert r["text"] == r["cue_text"] + plan["bodies"]["pause_form"]
    bodies = {r["text"][len(r["cue_text"]):] for r in forms}
    assert bodies == {plan["bodies"]["pause_form"]}
    assert by_id(forms, "pause_none")["cue_text"] == ""
    assert by_id(forms, "pause_punct_only")["cue_text"].strip() == "\u2026"


def by_id(rows, condition_id):
    matches = [r for r in rows if r["condition_id"] == condition_id]
    assert len(matches) == 1, f"expected exactly one {condition_id}, got {len(matches)}"
    return matches[0]


def test_every_condition_matches_a_declared_condition_row():
    plan = plan_for()
    declared = [c["id"] for c in plan["conditions"]]
    assert {r["condition_id"] for r in plan["requests"]} == set(declared)
    assert len(declared) == len(set(declared)) == 7


# ── 2. repeats and request order ─────────────────────────────────────────────

def test_repeat_count_and_order_are_deterministic():
    plan = plan_for(repeats=3)
    assert plan["request_count"] == 7 * 3
    assert [r["order_index"] for r in plan["requests"]] == list(range(21))

    # voice-major, then condition, then repeat — all repeats adjacent.
    keys = [(r["voice_index"], r["condition_index"], r["repeat"]) for r in plan["requests"]]
    assert keys == sorted(keys)
    for r in plan["requests"]:
        assert r["repeat"] in (1, 2, 3)
    per_condition = {}
    for r in plan["requests"]:
        per_condition.setdefault((r["voice"], r["condition_id"]), []).append(r["repeat"])
    assert all(v == [1, 2, 3] for v in per_condition.values())


def test_two_voices_are_ordered_and_mapped_explicitly():
    plan = plan_for(
        voices=[("picard-qwen3-06b", "qwen3-0.6b"), ("picard", "qwen3-1.7b")], repeats=2
    )
    assert plan["request_count"] == 28
    assert [v["requested_backend"] for v in plan["voices"]] == ["qwen3-0.6b", "qwen3-1.7b"]
    first_half = [r for r in plan["requests"] if r["voice_index"] == 0]
    second_half = [r for r in plan["requests"] if r["voice_index"] == 1]
    assert len(first_half) == len(second_half) == 14
    assert max(r["order_index"] for r in first_half) < min(r["order_index"] for r in second_half)
    assert {r["requested_backend"] for r in second_half} == {"qwen3-1.7b"}
    for r in plan["requests"]:
        assert r["attempt_id"].count("__") == 2


def test_plan_id_is_stable_and_content_addressed():
    a = plan_for()
    b = plan_for()
    assert a["plan_id"] == b["plan_id"]
    assert a["requests"] == b["requests"]
    assert plan_for(repeats=3)["plan_id"] != a["plan_id"]
    assert plan_for(opening_body="Different body entirely.")["plan_id"] != a["plan_id"]


def test_send_stripped_is_opt_in_and_still_records_the_raw_request():
    raw = plan_for(send_stripped=False)
    stripped = plan_for(send_stripped=True)
    raw_req = raw["requests"][0]
    stripped_req = stripped["requests"][0]
    assert raw_req["text"] == raw_req["raw_text"] == "## Setup cue\n\n" + fp.DEFAULT_OPENING_BODY
    assert stripped_req["text"] == stripped_req["expected_spoken_text"]
    assert stripped_req["raw_text"] == raw_req["raw_text"]
    assert "##" not in stripped_req["text"]


# ── 3. dry run and the hard request cap issue zero calls ─────────────────────

def test_dry_run_is_default_and_makes_no_call(tmp_path, monkeypatch, capsys):
    rc = run_cli(["--voice", "picard-qwen3-06b", "--repeats", "2",
                  "--out", str(tmp_path / "plan")], monkeypatch)
    assert rc == 0
    plan = json.loads((tmp_path / "plan" / "plan.json").read_text())
    assert plan["request_count"] == 14
    assert (tmp_path / "plan" / ".gitignore").read_text().strip() == "*"
    assert not (tmp_path / "plan" / "audio").exists()
    assert not (tmp_path / "plan" / "manifest.json").exists()


def test_default_dry_run_on_a_closed_port_writes_no_files(monkeypatch, capsys):
    """No --out: the plan goes to stdout and nothing is created on disk."""
    rc = run_cli(["--voice", "picard-qwen3-06b"], monkeypatch)
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out.split("\nDRY RUN")[0])["request_count"] == 14


def test_plan_over_cap_is_refused_before_any_call(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: calls.append(a))
    rc = fp.main([
        "--voice", "picard-qwen3-06b", "--repeats", "2", "--max-requests", "11",
        "--execute", "--out", str(tmp_path / "run"),
    ])
    assert rc == 2
    assert calls == []
    assert "needs 15 HTTP requests" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_cap_checked_before_calls_even_when_within_reach(tmp_path, probe_wav):
    """A cap equal to the plan lets every request through, and never more."""
    with _FakeServer(probe_wav) as srv:
        rc = fp.main([
            "--voice", "picard-qwen3-06b=qwen3-0.6b", "--repeats", "2", "--max-requests", "14",
            "--endpoint", srv.endpoint, "--execute", "--out", str(tmp_path / "run"),
            "--no-health-check",
        ])
    assert rc == 0
    assert len(srv.seen) == 14


# ── 4. endpoint guard, cap and required-argument validation ──────────────────

def test_non_loopback_endpoint_is_refused_without_the_override(capsys):
    rc = run_cli(["--voice", "x", "--endpoint", "http://10.0.0.5:7860"])
    assert rc == 2
    assert "not loopback" in capsys.readouterr().err


def test_non_loopback_override_is_recorded(monkeypatch, capsys):
    captured = {}

    def fake_build_plan(*a, **k):
        captured.update(k)
        return {"requests": [], "voices": [], "conditions": [], "bodies": {}}

    monkeypatch.setattr(fp, "build_plan", fake_build_plan)
    monkeypatch.setattr(fp, "build_annotations", lambda plan, status=None: {})
    rc = fp.main(["--voice", "x", "--endpoint", "http://10.0.0.5:7860",
                  "--allow-non-loopback"])
    assert rc == 0
    assert captured["allow_non_loopback"] is True


def test_loopback_hosts_are_recognised():
    for url in ("http://127.0.0.1:7860", "http://localhost:7860", "http://127.0.0.9:80", "http://[::1]:7860"):
        info, err = fp.endpoint_guard(url, False)
        assert err is None and info["is_loopback"] is True
    for url in ("http://10.0.0.5:7860", "http://127.fake.com:7860",
                "http://user:pass@localhost:7860", "http://localhost:7860?x=1"):
        _, err = fp.endpoint_guard(url, False)
        assert err is not None
    _, err = fp.endpoint_guard("http://127.0.0.1:7860/nested", False)
    assert err is not None


def test_repeats_below_two_and_zero_cap_are_refused(capsys):
    assert run_cli(["--voice", "x", "--repeats", "1"]) == 2
    assert ">= 2" in capsys.readouterr().err
    assert run_cli(["--voice", "x", "--max-requests", "0"]) == 2
    assert "positive" in capsys.readouterr().err
    assert run_cli(["--voice", "x", "--repeats", "0"]) == 2


def test_missing_voice_is_refused(capsys):
    assert run_cli(["--repeats", "2"]) == 2
    assert "no voice selected" in capsys.readouterr().err
    assert run_cli(["--voice", "voices/picard-ref.wav"]) == 2
    assert run_cli(["--voice", "../private"]) == 2


def test_duplicate_voice_names_cannot_reuse_attempt_ids(capsys):
    assert run_cli(["--voice", "dup", "--voice", "dup"]) == 2
    assert "duplicate --voice" in capsys.readouterr().err
    with pytest.raises(ValueError, match="duplicate voice names"):
        plan_for(voices=[("dup", "qwen3-0.6b"), ("dup", "qwen3-1.7b")])
    with pytest.raises(ValueError, match="duplicate voice names"):
        plan_for(voices=[("Dup", "qwen3-0.6b"), ("dup", "qwen3-1.7b")])
    with pytest.raises(ValueError, match="plain profile name"):
        plan_for(voices=[("../escape", "qwen3-0.6b")])


def test_execute_requires_out(capsys):
    assert run_cli(["--voice", "x", "--execute"]) == 2
    assert "requires --out" in capsys.readouterr().err


def test_two_model_live_run_cannot_skip_backend_preflight(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: pytest.fail("unexpected network call"))
    out = tmp_path / "run"
    rc = fp.main([
        "--voice", "picard-qwen3-06b=qwen3-0.6b",
        "--voice", "picard=qwen3-1.7b",
        "--execute", "--no-health-check", "--out", str(out),
    ])
    assert rc == 2
    assert "requires /health preflight" in capsys.readouterr().err
    assert not out.exists()


def test_unpinned_second_voice_cannot_bypass_two_model_preflight(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: pytest.fail("unexpected network call"))
    out = tmp_path / "run"
    rc = fp.main([
        "--voice", "picard-qwen3-06b=qwen3-0.6b", "--voice", "picard",
        "--execute", "--no-health-check", "--out", str(out),
    ])
    assert rc == 2
    assert "NAME=BACKEND" in capsys.readouterr().err
    assert not out.exists()


def test_execute_refuses_to_clobber_an_existing_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: fp.FetchResult(200, {}, b"", False, None))
    out = tmp_path / "run"
    out.mkdir()
    (out / "manifest.json").write_text("{}")
    rc = run_cli(["--voice", "x=qwen3-0.6b", "--execute", "--out", str(out)], monkeypatch,
                 fail_on_network=False)
    assert rc == 2
    assert "not empty" in capsys.readouterr().err
    assert (out / "manifest.json").read_text() == "{}"


def test_nonempty_output_directory_is_untouched_before_any_call(tmp_path, monkeypatch):
    out = tmp_path / "existing"
    out.mkdir()
    (out / ".gitignore").write_text("!keep-me\n")
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: pytest.fail("unexpected network call"))
    with pytest.raises(ValueError, match="not empty"):
        fp.execute(plan_for(), out_dir=out, max_requests=32, timeout=2.0,
                   silence_dbfs=-50.0, min_silence_s=0.25, health_check=True)
    assert sorted(p.name for p in out.iterdir()) == [".gitignore"]
    assert (out / ".gitignore").read_text() == "!keep-me\n"


def test_execute_rechecks_endpoint_even_when_called_without_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: pytest.fail("unexpected network call"))
    out = tmp_path / "run"
    plan = plan_for(endpoint="http://10.0.0.5:7860", allow_non_loopback=False)
    with pytest.raises(ValueError, match="not loopback"):
        fp.execute(plan, out_dir=out, max_requests=32, timeout=2.0,
                   silence_dbfs=-50.0, min_silence_s=0.25, health_check=False)
    assert not out.exists()


def test_execute_rejects_duplicate_attempt_ids_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: pytest.fail("unexpected network call"))
    plan = plan_for()
    plan["requests"][1]["attempt_id"] = plan["requests"][0]["attempt_id"]
    out = tmp_path / "run"
    with pytest.raises(ValueError, match="duplicate attempt IDs"):
        fp.execute(plan, out_dir=out, max_requests=32, timeout=2.0,
                   silence_dbfs=-50.0, min_silence_s=0.25, health_check=False)
    assert not out.exists()


def test_execute_rejects_an_unsafe_receipt_path_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "_fetch", lambda *a, **k: pytest.fail("unexpected network call"))
    plan = plan_for()
    plan["requests"][0]["attempt_id"] = "../escape"
    out = tmp_path / "run"
    with pytest.raises(ValueError, match="safe receipt filename"):
        fp.execute(plan, out_dir=out, max_requests=32, timeout=2.0,
                   silence_dbfs=-50.0, min_silence_s=0.25, health_check=False)
    assert not out.exists()


def test_only_probe_paths_can_be_fetched():
    with pytest.raises(ValueError):
        fp._fetch("http://127.0.0.1:7860/reload", 1.0)
    with pytest.raises(ValueError):
        fp._fetch("http://127.0.0.1:7860/clone", 1.0)


def test_probe_never_follows_a_synthesis_redirect(probe_wav):
    with _FakeServer(probe_wav, modes={1: 4}) as srv:
        result = fp._fetch(srv.endpoint + "/synthesize?text=synthetic", 2.0)
    assert result.status == 302
    assert "HTTPError 302" in result.error
    assert [request["path"] for request in srv.seen] == ["/synthesize"]


def test_probe_never_starts_or_restarts_the_server_on_disk():
    """Structural guard over the CODE (docstrings excluded).

    No process execution, no launchd, no cloning helper, and no string constant
    that names a file under voices/ — the probe cannot start, stop, reload or
    re-clone anything, and cannot be pointed at a private reference file.
    """
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("subprocess", "shutil", "os"):
        assert banned not in imported, f"{banned} must not be imported"

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))

    code_strings = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings
    ]
    blob = "\n".join(code_strings)
    assert "voices/" not in blob and "voices\\" not in blob
    assert "VOICES_DIR" not in blob
    for banned in ("afterwords.sh", "launchctl", "clone-voice", "/reload", "/clone"):
        assert banned not in blob, f"{banned!r} appears in probe code"

    # The only request paths the probe can ever issue.
    assert fp.ALLOWED_PATHS == {"/synthesize", "/health"}
    source_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr in {"urlopen", "urlretrieve", "Request"}
    ]
    assert {n.attr for n in source_calls} <= {"urlopen", "Request"}


# ── 5. silence detector against synthetic WAVs ───────────────────────────────

def test_detects_one_long_internal_silence_span(tmp_path):
    path = write_wav(tmp_path / "gap.wav", tone(0.5), silence(2.0), tone(0.5))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)

    assert metrics["duration_s"] == pytest.approx(3.0, abs=0.01)
    assert len(metrics["internal_silences"]) == 1
    span = metrics["internal_silences"][0]
    assert span["duration_s"] == pytest.approx(2.0, abs=0.06)
    assert span["start_s"] == pytest.approx(0.5, abs=0.06)
    assert metrics["longest_internal_silence_s"] == span["duration_s"]
    assert metrics["peak_dbfs"] == pytest.approx(20 * np.log10(0.5), abs=0.5)
    assert metrics["leading_silence_s"] < 0.05
    assert metrics["trailing_silence_s"] < 0.05


def test_long_cue_gap_after_a_tiny_click_is_still_internal(tmp_path):
    path = write_wav(tmp_path / "near-edge-gap.wav", tone(0.01), silence(16.0), tone(0.4))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)
    assert metrics["leading_silence_s"] < 0.02
    assert metrics["longest_internal_silence_s"] > 15.9
    assert len(metrics["internal_silences"]) == 1


def test_reports_leading_silence_but_not_as_an_internal_span(tmp_path):
    path = write_wav(tmp_path / "lead.wav", silence(1.0), tone(1.0))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)
    assert metrics["leading_silence_s"] == pytest.approx(1.0, abs=0.05)
    assert metrics["internal_silences"] == []
    assert metrics["longest_internal_silence_s"] == 0.0


def test_all_silent_audio_is_not_an_internal_gap(tmp_path):
    path = write_wav(tmp_path / "dead.wav", silence(2.0))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)
    assert metrics["internal_silences"] == []
    assert metrics["leading_silence_s"] == pytest.approx(2.0, abs=0.05)
    assert metrics["peak_dbfs"] is None


def test_short_gap_below_threshold_is_not_reported(tmp_path):
    path = write_wav(tmp_path / "short.wav", tone(0.5), silence(0.05), tone(0.5))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)
    assert metrics["internal_silences"] == []
    # …but the same file with a lower minimum does report it.
    loose = fp.analyse_audio(data, sr, min_silence_s=0.02)
    assert len(loose["internal_silences"]) == 1


def test_spectral_detector_ignores_quiet_tone_above_threshold(tmp_path):
    """A quiet-but-audible tone is left alone; only true silence is a span."""
    path = write_wav(tmp_path / "quiet.wav", tone(0.5, amp=0.2), silence(0.5), tone(0.5, amp=0.2))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)
    assert all(
        s["start_s"] > 0.45 and s["end_s"] < 1.05 for s in metrics["internal_silences"]
    ), "the quiet tones themselves must not be reported as silence"


def test_audio_below_the_threshold_is_reported_as_silence(tmp_path):
    """The detector is threshold-driven, not content-driven: a very quiet tone
    (well under the -50 dBFS default) IS silence by this measurement."""
    path = write_wav(tmp_path / "faint.wav", tone(0.5), tone(0.5, amp=0.0005), tone(0.5))
    data, sr = sf.read(str(path), dtype="float32")
    metrics = fp.analyse_audio(data, sr)
    assert len(metrics["internal_silences"]) == 1
    assert metrics["internal_silences"][0]["duration_s"] == pytest.approx(0.5, abs=0.06)


def test_analysis_does_not_modify_the_input(tmp_path):
    path = write_wav(tmp_path / "keep.wav", tone(0.3), silence(1.0), tone(0.3))
    before = path.read_bytes()
    data, sr = sf.read(str(path), dtype="float32")
    copied = data.copy()
    fp.analyse_audio(data, sr)
    assert np.array_equal(data, copied)
    assert path.read_bytes() == before  # never trimmed, never repaired


# ── 6. RIFF / partial detection ──────────────────────────────────────────────

def test_riff_info_flags_a_truncated_data_chunk(tmp_path):
    path = write_wav(tmp_path / "ok.wav", tone(0.2))
    raw = path.read_bytes()
    good = fp.riff_info(raw)
    assert good["is_riff_wave"] and good["truncated"] is False
    assert good["data_actual_bytes"] == good["data_declared_bytes"]

    cut = fp.riff_info(raw[: len(raw) - 1000])
    assert cut["is_riff_wave"] and cut["truncated"] is True


def test_riff_header_with_false_total_size_is_not_a_complete_wav(tmp_path):
    path = write_wav(tmp_path / "false-size.wav", tone(0.2))
    raw = bytearray(path.read_bytes())
    struct.pack_into("<I", raw, 4, 0)  # streaming-style unset RIFF size
    path.write_bytes(raw)
    info = fp.riff_info(bytes(raw))
    assert "RIFF byte count disagrees" in info["error"]
    wav, metrics, error = fp.read_and_analyse(path, silence_dbfs=-50.0, min_silence_s=0.25)
    assert wav["valid"] is False
    assert metrics is None
    assert "RIFF byte count disagrees" in error


def test_riff_info_rejects_non_wav_payload():
    assert fp.riff_info(b"<html>not audio</html>")["is_riff_wave"] is False
    assert fp.riff_info(b"")["error"] == "not a RIFF/WAVE container"


def test_read_and_analyse_rejects_a_truncated_wav(tmp_path):
    path = write_wav(tmp_path / "cut.wav", tone(0.5), silence(1.0), tone(0.5))
    partial = tmp_path / "partial.wav"
    partial.write_bytes(path.read_bytes()[: len(path.read_bytes()) - 5000])
    wav, metrics, error = fp.read_and_analyse(partial, silence_dbfs=-50.0, min_silence_s=0.25)
    assert wav["valid"] is False and error and "truncated" in error
    assert metrics is not None  # metrics still recorded for the receipt


def test_read_and_analyse_rejects_a_non_wav_payload(tmp_path):
    path = tmp_path / "error.wav"
    path.write_bytes(b'{"error": "unknown voice: nope"}')
    wav, metrics, error = fp.read_and_analyse(path, silence_dbfs=-50.0, min_silence_s=0.25)
    assert wav["valid"] is False and metrics is None
    assert error == "not a RIFF/WAVE container"


# ── 7. annotation template ───────────────────────────────────────────────────

def test_annotation_template_is_unknown_until_filled():
    plan = plan_for(repeats=2)
    annotations = fp.build_annotations(plan)
    assert annotations["perceptual_fidelity_claim"] == "NONE"
    assert len(annotations["entries"]) == plan["request_count"]
    for entry in annotations["entries"]:
        assert entry["heard_opening_words"] is None
        assert entry["missing_tokens"] is None
        assert entry["missing_token_judgement"] == "UNKNOWN"
        assert entry["human"]["verdict"] == "UNKNOWN"
        assert entry["human"]["notes"] is None
        assert entry["asr"] == {"engine": None, "model": None,
                               "transcript": None, "run_at": None}
        assert entry["attempt_status"] == "not_attempted"
    assert annotations["entries"][0]["attempt_id"] == "picard-qwen3-06b__opening_heading__r1"


def test_annotation_attempt_status_reflects_the_manifest_only():
    plan = plan_for(repeats=2)
    annotations = fp.build_annotations(
        plan, {"picard-qwen3-06b__opening_heading__r1": "ok",
               "picard-qwen3-06b__opening_heading__r2": "bad"}
    )
    by_id_ = {e["attempt_id"]: e for e in annotations["entries"]}
    assert by_id_["picard-qwen3-06b__opening_heading__r1"]["attempt_status"] == "ok"
    assert by_id_["picard-qwen3-06b__opening_heading__r2"]["attempt_status"] == "bad"
    # A status is not a verdict: the judgement fields stay UNKNOWN.
    assert by_id_["picard-qwen3-06b__opening_heading__r1"]["missing_token_judgement"] == "UNKNOWN"
    assert by_id_["picard-qwen3-06b__opening_heading__r1"]["human"]["verdict"] == "UNKNOWN"


def test_annotation_template_cli_needs_no_network(tmp_path, monkeypatch):
    rc = run_cli(["--voice", "picard-qwen3-06b", "--annotation-template",
                  "--out", str(tmp_path / "t")], monkeypatch)
    assert rc == 0
    template = json.loads((tmp_path / "t" / "annotations.template.json").read_text())
    assert template["legend"]["rule"].startswith("Waveform metrics are objective")
    assert all(e["missing_token_judgement"] == "UNKNOWN" for e in template["entries"])


def test_opening_token_diff_never_sets_a_verdict():
    diff = fp.opening_token_diff("Setup cue. The quick brown fox", "the quick brown fox")
    assert diff["missing"] == ["setup", "cue"]
    assert diff["judgement"] == "UNKNOWN"
    blank = fp.opening_token_diff("", "")
    assert blank["missing"] is None and blank["judgement"] == "UNKNOWN"
    assert fp.opening_tokens("Setup cue. The quick brown fox jumps") == [
        "setup", "cue", "the", "quick", "brown"]


def test_opening_token_diff_preserves_repetition_and_order():
    diff = fp.opening_token_diff(
        "The quick fox and the dog barked.", "The the quick fox and dog barked."
    )
    assert diff["missing"] == ["the"]
    assert diff["extra"] == ["the"]
    assert diff["judgement"] == "UNKNOWN"


# ── 8. live execution against a throwaway loopback server ────────────────────

class _FakeServer:
    """Local 127.0.0.1 HTTP server that answers /synthesize with canned bodies.

    Modes (keyed by request index, 1-based):
      0 -> valid WAV,  1 -> non-WAV 400 body,  2 -> valid body, wrong X-Backend,
      3 -> truncated body advertised with a larger Content-Length,
      4 -> redirect to a different, closed loopback port (must not be followed)
    """

    def __init__(self, wav: bytes, *, modes: dict[int, int] | None = None,
                 loaded_backends: tuple[str, ...] = ("qwen3-0.6b",)):
        self.wav = wav
        self.modes = modes or {}
        self.loaded_backends = loaded_backends
        self.seen: list[dict] = []
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # silence
                pass

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                index = len(server_self.seen) + 1
                server_self.seen.append({"path": parsed.path, "query": query})
                mode = server_self.modes.get(index, 0)

                if parsed.path == "/health":
                    body = json.dumps({
                        "status": "ok", "ready": True, "voices": {},
                        "loaded_backends": {
                            name: {"loaded": True} for name in server_self.loaded_backends
                        },
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if mode == 4:
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:9/synthesize?text=leak")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                if mode == 1:
                    body = b'{"error": "text is empty"}'
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                elif mode == 3:
                    body = server_self.wav[: len(server_self.wav) // 2]
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("X-Backend", "qwen3-0.6b")
                    self.send_header("Content-Length", str(len(server_self.wav)))
                    self.end_headers()
                    self.wfile.write(body)
                    self.close_connection = True
                    return
                else:
                    body = server_self.wav
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header(
                        "X-Backend",
                        "qwen3-1.7b" if mode == 2 else "qwen3-0.6b",
                    )
                    self.send_header("X-Duration", "1.0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def probe_wav() -> bytes:
    import io

    buf = io.BytesIO()
    sf.write(buf, np.concatenate([tone(0.4), silence(1.2), tone(0.4)]), SR,
             format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_live_run_manifest_receipts_and_metrics(tmp_path, probe_wav):
    with _FakeServer(probe_wav) as srv:
        plan = plan_for(repeats=2, endpoint=srv.endpoint)
        out = tmp_path / "run"
        manifest, rc = fp.execute(
            plan, out_dir=out, max_requests=32, timeout=10.0,
            silence_dbfs=-50.0, min_silence_s=0.25, health_check=False,
        )

    assert rc == 0
    assert manifest["perceptual_fidelity_claim"] == "NONE"
    assert manifest["config"]["requests_made"] == 14
    assert manifest["summary"]["bad"] == 0 and manifest["summary"]["aborted"] is False
    assert len(manifest["attempts"]) == 14

    # Requests were issued serially, in exactly manifest order, one body each.
    assert [a["order_index"] for a in manifest["attempts"]] == list(range(14))
    assert [r["query"]["text"] for r in srv.seen] == [a["request"]["text"] for a in manifest["attempts"]]
    assert [r["query"]["voice"] for r in srv.seen] == ["picard-qwen3-06b"] * 14
    assert [r["path"] for r in srv.seen] == ["/synthesize"] * 14

    first = manifest["attempts"][0]
    assert first["response"]["status"] == 200
    assert first["response"]["content_type"] == "audio/wav"
    assert first["response"]["bytes"] == len(probe_wav)
    assert first["response"]["sha256"] == fp._sha256(probe_wav)
    assert first["response"]["receipt_path"] == "audio/picard-qwen3-06b__opening_heading__r1.wav"
    assert first["backend"] == {"expected": "qwen3-0.6b", "observed": "qwen3-0.6b", "match": True}
    assert first["wav"]["valid"] is True and first["wav"]["truncated"] is False
    assert first["metrics"]["duration_s"] == pytest.approx(2.0, abs=0.02)
    assert first["metrics"]["longest_internal_silence_s"] == pytest.approx(1.2, abs=0.06)
    assert first["attempt"] == 1

    # One WAV per attempt on disk, hashes matching the manifest.
    on_disk = sorted(p.name for p in (out / "audio").glob("*.wav"))
    assert len(on_disk) == 14
    wav_path = out / first["response"]["receipt_path"]
    assert fp._sha256(wav_path.read_bytes()) == first["response"]["sha256"]
    assert (out / ".gitignore").read_text().strip() == "*"

    # The annotation sidecar exists, mirrors the attempts and stays UNKNOWN.
    template = json.loads((out / "annotations.template.json").read_text())
    assert template["plan_id"] == plan["plan_id"]
    assert len(template["entries"]) == 14
    assert {e["attempt_status"] for e in template["entries"]} == {"ok"}
    assert all(e["missing_token_judgement"] == "UNKNOWN" for e in template["entries"])


def test_live_run_reports_the_long_gap_symptom_without_judging_it(tmp_path, probe_wav):
    with _FakeServer(probe_wav) as srv:
        manifest, rc = fp.execute(
            plan_for(repeats=2, endpoint=srv.endpoint), out_dir=tmp_path / "r",
            max_requests=32, timeout=10.0, silence_dbfs=-50.0, min_silence_s=0.25,
            health_check=False,
        )
    assert rc == 0
    summary = manifest["summary"]
    assert len(summary["attempts_with_internal_silence"]) == 14
    assert summary["max_internal_silence_s"] == pytest.approx(1.2, abs=0.06)
    # A finding is recorded; nothing claims the words were heard.
    assert manifest["claim_scope"].startswith("Waveform metrics only")


def test_non_audio_response_fails_closed_and_stops_the_run(tmp_path, probe_wav):
    with _FakeServer(probe_wav, modes={3: 1}) as srv:
        out = tmp_path / "run"
        manifest, rc = fp.execute(
            plan_for(repeats=2, endpoint=srv.endpoint), out_dir=out,
            max_requests=32, timeout=10.0, silence_dbfs=-50.0, min_silence_s=0.25,
            health_check=False,
        )
    assert rc == 1
    assert manifest["summary"]["aborted"] is True
    assert manifest["summary"]["made"] == 3          # stopped at the bad attempt
    assert len(srv.seen) == 3                        # no further request issued
    bad = manifest["attempts"][-1]
    assert bad["ok"] is False and bad["response"]["status"] == 400
    assert "non-audio response" in bad["error"]
    assert bad["response"]["receipt_path"].endswith(".body")
    # Receipts for the two completed attempts survive.
    assert len(list((out / "audio").glob("*.wav"))) == 2
    assert (out / "manifest.json").exists()
    assert (out / "receipts").glob("*.body")


def test_partial_truncated_response_fails_closed_with_receipt_kept(tmp_path, probe_wav):
    with _FakeServer(probe_wav, modes={2: 3}) as srv:
        out = tmp_path / "run"
        manifest, rc = fp.execute(
            plan_for(repeats=2, endpoint=srv.endpoint), out_dir=out,
            max_requests=32, timeout=10.0, silence_dbfs=-50.0, min_silence_s=0.25,
            health_check=False,
        )
    assert rc == 1
    bad = manifest["attempts"][-1]
    assert bad["ok"] is False
    assert bad["response"]["partial"] is True or bad["response"]["content_length_mismatch"]
    assert bad["wav"]["valid"] is False
    assert bad["response"]["receipt_path"].endswith(".body"), "partial audio is never named as a completed WAV"
    assert (out / bad["response"]["receipt_path"]).exists()  # receipt kept
    assert len(manifest["attempts"]) == 2


def test_backend_mismatch_fails_closed(tmp_path, probe_wav):
    with _FakeServer(probe_wav, modes={1: 2}) as srv:
        out = tmp_path / "run"
        manifest, rc = fp.execute(
            plan_for(repeats=2, endpoint=srv.endpoint), out_dir=out,
            max_requests=32, timeout=10.0, silence_dbfs=-50.0, min_silence_s=0.25,
            health_check=False,
        )
    assert rc == 1
    first = manifest["attempts"][0]
    assert first["backend"] == {
        "expected": "qwen3-0.6b", "observed": "qwen3-1.7b", "match": False}
    assert "backend mismatch" in first["error"]
    assert len(manifest["attempts"]) == 1


def test_backend_is_reported_not_assumed_when_no_pin_was_given(tmp_path, probe_wav):
    with _FakeServer(probe_wav) as srv:
        plan = plan_for(voices=[("picard-qwen3-06b", None)], repeats=2, endpoint=srv.endpoint)
        manifest, rc = fp.execute(
            plan, out_dir=tmp_path / "run", max_requests=32, timeout=10.0,
            silence_dbfs=-50.0, min_silence_s=0.25, health_check=False,
        )
    assert rc == 0
    first = manifest["attempts"][0]
    assert first["backend"] == {"expected": None, "observed": "qwen3-0.6b", "match": None}


def test_execute_refuses_an_incomplete_matrix_before_any_call(tmp_path, probe_wav):
    with _FakeServer(probe_wav) as srv:
        with pytest.raises(ValueError, match="plan needs 14 HTTP request"):
            fp.execute(
                plan_for(repeats=2, endpoint=srv.endpoint), out_dir=tmp_path / "run",
                max_requests=5, timeout=10.0, silence_dbfs=-50.0, min_silence_s=0.25,
                health_check=False,
            )
    assert srv.seen == []
    assert not (tmp_path / "run").exists()


def test_health_check_is_read_only_and_recorded(tmp_path, probe_wav):
    with _FakeServer(probe_wav) as srv:
        manifest, _ = fp.execute(
            plan_for(repeats=2, endpoint=srv.endpoint), out_dir=tmp_path / "run",
            max_requests=32, timeout=10.0, silence_dbfs=-50.0, min_silence_s=0.25,
            health_check=True,
        )
    assert srv.seen[0]["path"] == "/health"
    assert manifest["health"]["status"] == 200
    assert manifest["health"]["ready"] is True
    assert manifest["health"]["loaded_backend_names"] == ["qwen3-0.6b"]
    assert manifest["config"]["http_requests_made"] == 15


def test_health_call_counts_against_the_hard_request_cap(tmp_path, probe_wav):
    with _FakeServer(probe_wav) as srv:
        with pytest.raises(ValueError, match="plan needs 15 HTTP request"):
            fp.execute(plan_for(repeats=2, endpoint=srv.endpoint),
                       out_dir=tmp_path / "run", max_requests=14, timeout=10.0,
                       silence_dbfs=-50.0, min_silence_s=0.25, health_check=True)
    assert srv.seen == []
    assert not (tmp_path / "run").exists()


def test_two_model_preflight_refuses_missing_17b_without_synthesis(tmp_path, probe_wav):
    with _FakeServer(probe_wav, loaded_backends=("qwen3-0.6b",)) as srv:
        plan = plan_for(voices=[("picard-qwen3-06b", "qwen3-0.6b"),
                                ("picard", "qwen3-1.7b")],
                        repeats=2, endpoint=srv.endpoint)
        manifest, rc = fp.execute(plan, out_dir=tmp_path / "run", max_requests=32,
                                  timeout=10.0, silence_dbfs=-50.0,
                                  min_silence_s=0.25, health_check=True)
    assert rc == 1
    assert [request["path"] for request in srv.seen] == ["/health"]
    assert manifest["summary"]["made"] == 0
    assert "qwen3-1.7b" in manifest["summary"]["abort_reason"]
    assert manifest["config"]["http_requests_made"] == 1
    assert not list((tmp_path / "run" / "audio").iterdir())


def test_cli_live_run_end_to_end(tmp_path, probe_wav, capsys):
    with _FakeServer(probe_wav) as srv:
        rc = fp.main([
            "--voice", "picard-qwen3-06b=qwen3-0.6b", "--repeats", "2",
            "--endpoint", srv.endpoint, "--execute", "--out", str(tmp_path / "run"),
            "--no-health-check", "--max-requests", "14",
        ])
    assert rc == 0
    out = capsys.readouterr().out
    summary = json.loads(out[out.index("{"):])["summary"]
    assert summary == {"planned": 14, "made": 14, "ok": 14, "bad": 0,
                       "aborted": False, "abort_reason": None,
                       "max_internal_silence_s": pytest.approx(1.2, abs=0.06)}
    assert (tmp_path / "run" / "manifest.json").exists()


def test_cli_closed_port_records_a_transport_failure(tmp_path, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rc = fp.main([
        "--voice", "picard-qwen3-06b=qwen3-0.6b", "--repeats", "2",
        "--endpoint", f"http://127.0.0.1:{port}", "--execute",
        "--out", str(tmp_path / "run"), "--no-health-check", "--max-requests", "14",
    ])
    assert rc == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["summary"]["made"] == 1 and manifest["summary"]["aborted"] is True
    attempt = manifest["attempts"][0]
    assert attempt["response"]["status"] is None
    assert attempt["error"] and "Connection refused" in attempt["error"]
    assert (tmp_path / "run" / attempt["response"]["receipt_path"]).exists()
