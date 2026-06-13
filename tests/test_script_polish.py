"""Tests for --json flag and exit-code contracts on analysis scripts."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VOICES_DIR = REPO / "voices"
QA_SCRIPT = REPO / "scripts" / "qa-voices.py"
TRIM_SCRIPT = REPO / "scripts" / "trim-silence-gaps.py"
COMPARE_SCRIPT = REPO / "scripts" / "compare-transcription.py"
SAMPLE_WAV = REPO / "voices" / "galadriel-ref.wav"  # tracked in repo

def run_script(script, *args, timeout=600):
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=timeout,
    )

# ── CI-safe: flag presence via --help (argparse exits before importing whisper) ──
def test_qa_has_json_flag():
    result = run_script(QA_SCRIPT, "--help", timeout=30)
    assert result.returncode == 0
    assert "--json" in result.stdout

# ── Heavy: real model run; integration-gated ──
@pytest.mark.integration
def test_qa_json_structure():
    pytest.importorskip("faster_whisper")
    result = run_script(QA_SCRIPT, "--json", "--ref-only")
    assert result.returncode in (0, 1), f"unexpected exit {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)  # stdout must be JSON only — no progress text
    assert data["threshold"] == 0.15
    assert isinstance(data["voices"], list)
    if data["voices"]:
        v = data["voices"][0]
        assert "name" in v and "ref_wer" in v


# ── trim-silence-gaps tests ──

def test_trim_has_json_flag():
    result = run_script(TRIM_SCRIPT, "--help", timeout=30)
    assert result.returncode == 0
    assert "--json" in result.stdout

@pytest.mark.integration
def test_trim_json_structure():
    pytest.importorskip("faster_whisper")
    result = run_script(TRIM_SCRIPT, "--json")  # dry run — must still emit JSON
    assert result.returncode in (0, 1), f"exit {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)  # JSON in dry-run mode is the regression guard
    assert isinstance(data["voices"], list)
    if data["voices"]:
        v = data["voices"][0]
        assert "name" in v and "gap_count" in v and "changed" in v


# ── compare-transcription tests ──

def test_compare_has_json_flag():
    result = run_script(COMPARE_SCRIPT, "--help", timeout=30)
    assert result.returncode == 0
    assert "--json" in result.stdout

@pytest.mark.integration
def test_compare_json_structure():
    pytest.importorskip("faster_whisper")  # loads large-v2 — heavy, dev-machine only
    result = run_script(COMPARE_SCRIPT, str(SAMPLE_WAV), "--json", "--skip-parakeet")
    # one model skipped → partial comparison → exit 1
    assert result.returncode in (0, 1), f"exit {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)
    assert "winner" in data          # may be None when only one model ran
    assert "whisper_words" in data
    assert "skipped" in data
    assert "parakeet" in data["skipped"]
