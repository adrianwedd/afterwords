"""Tests for VoiceProfile loading and backend-aware profile discovery."""
from __future__ import annotations

import json
import os

import pytest

import backends


@pytest.fixture(autouse=True)
def _load_registry():
    backends.reset_for_tests()
    backends.register_all()
    yield
    backends.reset_for_tests()


def _write_profile(tmp_path, name: str, **fields):
    """Helper: write a voices/*.json + a minimal -ref.wav next to it."""
    import soundfile as sf
    import numpy as np

    json_path = tmp_path / f"{name}.json"
    ref_path = tmp_path / f"{name}-ref.wav"
    sf.write(str(ref_path), np.zeros(24000, dtype=np.float32), 24000)
    payload = {
        "name": name,
        "reference_audio": f"{name}-ref.wav",
        **fields,
    }
    json_path.write_text(json.dumps(payload))
    return json_path, ref_path


def test_profile_without_backend_field_defaults_to_qwen3_06b(tmp_path, monkeypatch):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "legacy", reference_text="hello world")
    _load_voice_profiles()
    assert "legacy" in VOICES
    assert VOICES["legacy"].backend == "qwen3-0.6b"


def test_profile_with_explicit_backend_honoured(tmp_path, monkeypatch):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "new", backend="chatterbox")  # no ref_text — Chatterbox OPTIONAL
    _load_voice_profiles()
    assert "new" in VOICES
    assert VOICES["new"].backend == "chatterbox"


def test_profile_unknown_backend_skipped(tmp_path, monkeypatch, caplog):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "future", backend="some-future-model", reference_text="x")
    _load_voice_profiles()
    assert "future" not in VOICES
    assert "unregistered backend" in caplog.text


def test_profile_required_policy_without_ref_text_skipped(tmp_path, monkeypatch, caplog):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "qwen3voice", backend="qwen3-0.6b")  # no ref_text
    _load_voice_profiles()
    assert "qwen3voice" not in VOICES
    assert "REQUIRES ref_text" in caplog.text


def test_profile_optional_policy_without_ref_text_kept(tmp_path, monkeypatch):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "chatvoice", backend="chatterbox")
    _load_voice_profiles()
    assert "chatvoice" in VOICES
    assert VOICES["chatvoice"].ref_text is None


def test_profile_with_unknown_extras_skipped(tmp_path, monkeypatch, caplog):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(
        tmp_path, "badextras",
        backend="qwen3-0.6b",
        reference_text="x",
        synthesis_extras={"bogus_key": 1},
    )
    _load_voice_profiles()
    assert "badextras" not in VOICES
    assert "invalid extras" in caplog.text
