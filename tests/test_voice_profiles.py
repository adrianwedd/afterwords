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
    _write_profile(tmp_path, "new", backend="xtts-v2")  # no ref_text — xtts-v2 OPTIONAL
    _load_voice_profiles()
    assert "new" in VOICES
    assert VOICES["new"].backend == "xtts-v2"


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
    _write_profile(tmp_path, "xttsvoice", backend="xtts-v2")
    _load_voice_profiles()
    assert "xttsvoice" in VOICES
    assert VOICES["xttsvoice"].ref_text is None


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


def test_profile_family_field_loaded_from_json(tmp_path, monkeypatch):
    """The family JSON field must round-trip into VoiceProfile.family."""
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "picard-test", reference_text="x", family="picard")
    _write_profile(tmp_path, "lone-voice", reference_text="x")  # no family field
    _load_voice_profiles()
    assert VOICES["picard-test"].family == "picard"
    assert VOICES["lone-voice"].family is None


# --- Schema validation of the 290+ shipped voices/*.json profiles ---
#
# These tests catch malformed/orphaned profiles before they ship. They scan the
# real voices/ directory and assert each JSON: (1) has the required fields,
# (2) points at an existing reference_audio WAV, (3) names a registered backend
# slug (default qwen3-0.6b), and (4) provides reference_text when the backend's
# policy requires it.


def _voice_profile_paths():
    import glob
    repo_voices = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "voices"
    )
    return sorted(glob.glob(os.path.join(repo_voices, "*.json")))


@pytest.mark.parametrize(
    "profile_path",
    _voice_profile_paths(),
    ids=lambda p: os.path.basename(p),
)
def test_shipped_voice_profile_schema(profile_path):
    """Every shipped voices/*.json must be schema-valid for production loading."""
    from backends.base import RefTextPolicy

    with open(profile_path) as fh:
        payload = json.load(fh)

    name = payload.get("name")
    assert isinstance(name, str) and name, f"missing/empty 'name' in {profile_path}"

    ref_audio = payload.get("reference_audio")
    assert isinstance(ref_audio, str) and ref_audio.endswith(".wav"), \
        f"'reference_audio' must be a .wav filename in {profile_path}"

    voices_dir = os.path.dirname(profile_path)
    ref_full = os.path.join(voices_dir, ref_audio)
    assert os.path.exists(ref_full), (
        f"reference_audio {ref_audio!r} does not exist next to {profile_path}"
    )

    backend_name = payload.get("backend", "qwen3-0.6b")
    assert backend_name in backends.names(), (
        f"backend {backend_name!r} in {profile_path} is not registered"
    )

    backend = backends.get(backend_name)
    if backend.ref_text_policy is RefTextPolicy.REQUIRED:
        ref_text = payload.get("reference_text")
        assert isinstance(ref_text, str) and ref_text.strip(), (
            f"backend {backend_name!r} requires reference_text but {profile_path} "
            f"has none"
        )
