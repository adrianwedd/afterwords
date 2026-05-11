"""Tests for the Afterwords FastAPI server.

All tests use a mocked ML model — no GPU, no model download,
no network access. The mock generates a tiny valid WAV file
to exercise the full synthesis response path.
"""
import json
import os

import pytest
import server


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "ready" in data
    assert "voices" in data


def test_health_lists_voices(client, sample_voice):
    r = client.get("/health")
    assert sample_voice in r.json()["voices"]


def test_synthesize_returns_wav(client, sample_voice):
    r = client.get("/synthesize", params={"text": "Hello", "voice": sample_voice})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert "x-synthesis-time" in r.headers
    assert "x-duration" in r.headers


def test_synthesize_missing_text(client):
    r = client.get("/synthesize")
    assert r.status_code == 422


def test_synthesize_empty_text(client):
    r = client.get("/synthesize", params={"text": " "})
    assert r.status_code == 400
    assert "empty" in r.json()["error"]


def test_synthesize_text_too_long(client):
    r = client.get("/synthesize", params={"text": "x" * 5001})
    assert r.status_code == 400
    assert "too long" in r.json()["error"]


def test_synthesize_unknown_voice(client):
    r = client.get("/synthesize", params={"text": "Hi", "voice": "nonexistent"})
    assert r.status_code == 400
    data = r.json()
    assert "unknown voice" in data["error"]
    assert "available" in data


def test_synthesize_not_ready(client):
    server._ready.clear()
    r = client.get("/synthesize", params={"text": "Hi", "voice": "testvoice"})
    assert r.status_code == 503
    server._ready.set()


def test_synthesize_default_voice(client, sample_voice):
    # FastAPI captures Query(DEFAULT_VOICE) at import time, so we test
    # that omitting voice uses a valid default (not that we can swap it).
    # Register the actual default voice so the request succeeds.
    default = server.DEFAULT_VOICE
    if default not in server.VOICES:
        server.VOICES[default] = server.VOICES[sample_voice]
    r = client.get("/synthesize", params={"text": "Hello"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_resolve_voice_known(sample_voice):
    result = server._resolve_voice(sample_voice)
    assert result is not None
    assert isinstance(result.ref_audio, str)
    assert isinstance(result.ref_text, str)
    assert result.backend == "fake"


def test_resolve_voice_unknown():
    result = server._resolve_voice("definitely_not_a_voice")
    assert result is None


# --- POST /clone tests ---


def test_clone_creates_voice(client, tmp_path):
    """POST /clone with valid audio creates a voice entry."""
    server._clone_enabled = True
    # Create a small valid WAV (2 seconds)
    import struct

    wav_path = str(tmp_path / "test.wav")
    sr = 24000
    n_samples = sr * 2
    data_size = n_samples * 2
    with open(wav_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)

    with open(wav_path, "rb") as f:
        r = client.post(
            "/clone",
            files={"audio": ("test.wav", f, "audio/wav")},
            data={"session_id": "test-session", "emotion": "neutral", "transcript": "Hello world"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["voice"].startswith("test-session-")
    assert data["emotion"] == "neutral"
    assert data["quality"] in ("rough", "developing", "good")
    # Cleanup
    server._unregister_session("test-session")
    server._clone_enabled = False


def test_clone_disabled_by_default(client):
    """POST /clone returns 404 when --allow-clone not set."""
    server._clone_enabled = False
    r = client.post(
        "/clone",
        files={"audio": ("test.wav", b"fake", "audio/wav")},
        data={"session_id": "s1", "emotion": "neutral"},
    )
    assert r.status_code == 404


def test_clone_too_short(client):
    """POST /clone with tiny audio returns 400."""
    server._clone_enabled = True
    r = client.post(
        "/clone",
        files={"audio": ("test.wav", b"tiny", "audio/wav")},
        data={"session_id": "s1", "emotion": "neutral"},
    )
    assert r.status_code == 400
    server._clone_enabled = False


# --- POST /synthesize tests ---


def test_post_synthesize_returns_wav(client, sample_voice):
    """POST /synthesize with JSON body returns WAV audio."""
    server._clone_enabled = True
    r = client.post("/synthesize", json={"text": "Hello", "voice": sample_voice})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    server._clone_enabled = False


def test_post_synthesize_empty_text(client):
    """POST /synthesize with empty text returns 400."""
    server._clone_enabled = True
    r = client.post("/synthesize", json={"text": " ", "voice": "testvoice"})
    assert r.status_code == 400
    server._clone_enabled = False


def test_post_synthesize_disabled_by_default(client):
    """POST /synthesize returns 404 when --allow-clone not set."""
    server._clone_enabled = False
    r = client.post("/synthesize", json={"text": "Hi", "voice": "testvoice"})
    assert r.status_code == 404


# --- DELETE /session tests ---


def test_delete_session(client, tmp_path):
    """DELETE /session removes palette entries."""
    import backends as _backends
    _backend = _backends.get("fake")
    wav_a = str(tmp_path / "a.wav")
    wav_b = str(tmp_path / "b.wav")
    # Write minimal WAV stubs so _register_voice doesn't error on missing files.
    import struct as _struct
    for p in (wav_a, wav_b):
        with open(p, "wb") as _f:
            sr = 24000
            _f.write(b"RIFF" + _struct.pack("<I", 36) + b"WAVE" + b"fmt " +
                     _struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) +
                     b"data" + _struct.pack("<I", 0))
    prep_a = _backend.prepare_voice(wav_a, "text", {})
    prep_b = _backend.prepare_voice(wav_b, "text", {})
    server._clone_enabled = True
    server._register_voice("viewer-xyz-001", "fake", wav_a, "text", prep_a, "neutral")
    server._register_voice("viewer-xyz-002", "fake", wav_b, "text", prep_b, "sad")
    r = client.delete("/session/viewer-xyz")
    assert r.status_code == 200
    assert "viewer-xyz-001" not in server.VOICES
    assert "viewer-xyz-002" not in server.VOICES
    server._clone_enabled = False


def test_delete_session_idempotent(client):
    """DELETE /session for nonexistent session returns 200."""
    server._clone_enabled = True
    r = client.delete("/session/nonexistent")
    assert r.status_code == 200
    server._clone_enabled = False


# --- Voice palette selection ---


def test_resolve_voice_with_emotion(tmp_path):
    """_resolve_voice selects best palette entry by emotion."""
    import backends as _backends
    import struct as _struct
    _backend = _backends.get("fake")
    wav_a = str(tmp_path / "s1-a.wav")
    wav_b = str(tmp_path / "s1-b.wav")
    for p in (wav_a, wav_b):
        with open(p, "wb") as _f:
            sr = 24000
            _f.write(b"RIFF" + _struct.pack("<I", 36) + b"WAVE" + b"fmt " +
                     _struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) +
                     b"data" + _struct.pack("<I", 0))
    prep_a = _backend.prepare_voice(wav_a, "hi", {})
    prep_b = _backend.prepare_voice(wav_b, "sad", {})
    server._register_voice(
        "viewer-s1-001", "fake", wav_a, "hi", prep_a, "neutral",
        {"session_id": "viewer-s1", "duration_s": 5, "confidence": 0.8},
    )
    server._register_voice(
        "viewer-s1-002", "fake", wav_b, "sad", prep_b, "vulnerable",
        {"session_id": "viewer-s1", "duration_s": 10, "confidence": 0.9},
    )
    result = server._resolve_voice("viewer-s1", emotion="vulnerable")
    assert result is not None
    assert result.ref_audio == wav_b
    # Cleanup
    server._unregister_session("viewer-s1")


def test_health_includes_loaded_backends(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "mlx"  # legacy field unchanged
    assert "loaded_backends" in body
    assert set(body["loaded_backends"].keys()) >= {
        "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5",
    }
    for name, info in body["loaded_backends"].items():
        assert info["loaded"] is True
        assert isinstance(info["voice_count"], int)
        assert isinstance(info["sample_rate"], int)


def test_health_preserves_legacy_fields(client):
    resp = client.get("/health")
    body = resp.json()
    for key in ("status", "model", "backend", "model_loaded", "ready", "voices", "default_voice"):
        assert key in body


def test_synthesize_unknown_voice_returns_400(client):
    resp = client.get("/synthesize?text=hi&voice=nonexistent-voice-zzzz")
    assert resp.status_code == 400
    body = resp.json()
    assert "unknown voice" in body["error"]
    assert isinstance(body["available"], list)


def test_health_exposes_supported_langs(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    for name, info in body["loaded_backends"].items():
        assert "supported_langs" in info, f"backend {name!r} missing supported_langs"
        assert isinstance(info["supported_langs"], list)
        assert all(isinstance(x, str) for x in info["supported_langs"])


def test_synthesize_unsupported_lang_returns_400(client, sample_voice):
    """GET /synthesize?lang=fr against an en-only voice must return 400."""
    r = client.get("/synthesize", params={"text": "Bonjour", "voice": sample_voice, "lang": "fr"})
    assert r.status_code == 400
    body = r.json()
    assert "supported_langs" in body
    assert "en" in body["supported_langs"]
    assert "fr" not in body["supported_langs"]


def test_fake_backend_synthesize_raises_for_unsupported_lang():
    """FakeBackend.synthesize must raise ValueError for langs outside supported_langs.

    This verifies the backend contract, independent of the HTTP routing layer.
    The server relies on ValueError to produce the 400 + supported_langs body.
    """
    import backends as _backends
    from backends.base import PreparedVoice, _read_only
    import numpy as np

    be = _backends.get("fake")
    pv = PreparedVoice(
        ref_audio_path="/dev/null",
        ref_text=None,
        extras=_read_only({}),
    )
    assert "en" in be.supported_langs
    assert "fr" not in be.supported_langs

    # Supported lang must not raise
    audio, sr = be.synthesize("hello", pv, "en")
    assert isinstance(audio, np.ndarray)

    # Unsupported lang must raise ValueError (not KeyError, not RuntimeError)
    import pytest as _pytest
    with _pytest.raises(ValueError, match="fr"):
        be.synthesize("bonjour", pv, "fr")


def test_post_synthesize_accepts_lang(client, sample_voice):
    """POST /synthesize with lang=en against an en voice should succeed."""
    server._clone_enabled = True
    try:
        r = client.post("/synthesize", json={"text": "Hello", "voice": sample_voice, "lang": "en"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
    finally:
        server._clone_enabled = False


def test_cleanup_current_voices_deletes_tracked_paths(tmp_path):
    """_cleanup_current_voices must delete cleanup_paths + owned_temp_audio for all VOICES."""
    import tempfile as _tempfile
    tmp_cleanup = os.path.join(_tempfile.gettempdir(), "test-cleanup-xyz.bin")
    tmp_owned = os.path.join(_tempfile.gettempdir(), "test-owned-xyz.wav")
    safe_file = str(tmp_path / "safe.wav")
    for p in (tmp_cleanup, tmp_owned, safe_file):
        with open(p, "wb") as f:
            f.write(b"x")

    prep = server.PreparedVoice(
        ref_audio_path=tmp_owned,
        ref_text=None,
        extras={},
        owns_temp_audio=True,
        cleanup_paths=(tmp_cleanup,),
    )
    profile = server.VoiceProfile(
        name="cleaner", backend="fake", ref_audio=tmp_owned, ref_text=None,
        session_id=None, emotion="neutral", quality=None, duration_s=None,
        confidence=None, sequence=None, extras={}, prepared=prep,
    )
    server.VOICES["cleaner"] = profile
    try:
        server._cleanup_current_voices()
        assert not os.path.exists(tmp_cleanup), "cleanup_paths entry not deleted"
        assert not os.path.exists(tmp_owned), "owns_temp_audio ref not deleted"
        assert os.path.exists(safe_file), "file outside tempdir must NOT be touched"
    finally:
        server.VOICES.pop("cleaner", None)
        for p in (tmp_cleanup, tmp_owned, safe_file):
            try:
                os.remove(p)
            except OSError:
                pass


def test_sweep_orphaned_temp_files_deletes_voxcpm_refs():
    """_sweep_orphaned_temp_files must delete files matching voxcpm-ref-*.wav."""
    import tempfile as _tempfile
    stale = os.path.join(_tempfile.gettempdir(), "voxcpm-ref-deadbeef.wav")
    unrelated = os.path.join(_tempfile.gettempdir(), "not-voxcpm-xyz.wav")
    for p in (stale, unrelated):
        with open(p, "wb") as f:
            f.write(b"x")
    try:
        server._sweep_orphaned_temp_files()
        assert not os.path.exists(stale), "stale voxcpm-ref-*.wav not swept"
        assert os.path.exists(unrelated), "unrelated file must NOT be swept"
    finally:
        for p in (stale, unrelated):
            try:
                os.remove(p)
            except OSError:
                pass


def _write_profile_json(dir_path, name, backend="fake", ref_text="hello"):
    """Write a profile JSON + ref WAV to dir_path. Returns (json_path, wav_path)."""
    import soundfile as sf
    import numpy as np
    wav = os.path.join(dir_path, f"{name}-ref.wav")
    sf.write(wav, np.zeros(24000, dtype=np.float32), 24000)
    j = os.path.join(dir_path, f"{name}.json")
    with open(j, "w") as f:
        json.dump({
            "name": name,
            "backend": backend,
            "reference_audio": f"{name}-ref.wav",
            "reference_text": ref_text,
        }, f)
    return j, wav


def test_reload_disabled_without_allow_clone(client):
    server._clone_enabled = False
    r = client.post("/reload")
    assert r.status_code == 404


def test_reload_adds_new_voice_from_disk(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        _write_profile_json(str(tmp_path), "alpha", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 200
        body = r.json()
        assert "alpha" in body["reloaded"]
        assert body["errors"] == []
        assert "alpha" in server.VOICES
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_is_add_only_keeps_deleted_voices(client, tmp_path, monkeypatch):
    """If a JSON is deleted from disk, the voice stays in VOICES (add-only)."""
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        j1, _ = _write_profile_json(str(tmp_path), "keeper", backend="fake")
        r = client.post("/reload")
        assert "keeper" in server.VOICES
        os.remove(j1)
        r = client.post("/reload")
        assert r.status_code == 200
        assert "keeper" in server.VOICES
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_updates_changed_voice(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        _write_profile_json(str(tmp_path), "updater", backend="fake", ref_text="before")
        r = client.post("/reload")
        assert server.VOICES["updater"].ref_text == "before"
        _write_profile_json(str(tmp_path), "updater", backend="fake", ref_text="after")
        r = client.post("/reload")
        assert r.status_code == 200
        assert server.VOICES["updater"].ref_text == "after"
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_malformed_json_logs_and_skips(client, tmp_path, monkeypatch):
    """Malformed JSON is logged and skipped via _build_voice_profile returning None;
    reload still succeeds with 200 for the other good profiles."""
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        _write_profile_json(str(tmp_path), "good", backend="fake")
        with open(os.path.join(str(tmp_path), "bad.json"), "w") as f:
            f.write("{not valid json")
        r = client.post("/reload")
        assert r.status_code == 200
        assert "good" in server.VOICES
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_abort_when_prepare_voice_raises(client, tmp_path, monkeypatch):
    """If prepare_voice raises, reload aborts atomically — existing VOICES unmutated."""
    import backends as _backends
    import soundfile as sf, numpy as np
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True

    pre_wav = str(tmp_path / "pre-ref.wav")
    sf.write(pre_wav, np.zeros(24000, dtype=np.float32), 24000)
    backend = _backends.get("fake")
    prep = backend.prepare_voice(pre_wav, "pre text", {})
    server.VOICES["pre"] = server.VoiceProfile(
        name="pre", backend="fake", ref_audio=pre_wav, ref_text="pre text",
        session_id=None, emotion="neutral", quality=None, duration_s=None,
        confidence=None, sequence=None, extras={}, prepared=prep,
    )

    original = backend.prepare_voice
    def failing_prepare(ref, txt, extras):
        if ref.endswith("boom-ref.wav"):
            raise RuntimeError("simulated prepare failure")
        return original(ref, txt, extras)
    monkeypatch.setattr(backend, "prepare_voice", failing_prepare)

    try:
        _write_profile_json(str(tmp_path), "ok_one", backend="fake")
        _write_profile_json(str(tmp_path), "boom", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 500
        body = r.json()
        assert body["status"] == "failed"
        assert len(body["errors"]) >= 1
        assert "pre" in server.VOICES         # pre-existing voice NOT mutated
        assert "ok_one" not in server.VOICES  # atomic abort — no mutation
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_abort_cleans_tracked_temps(client, tmp_path, monkeypatch):
    """When reload aborts, temp files from profiles built before the failure must be deleted."""
    import backends as _backends
    import tempfile as _tempfile
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True

    sentinel = os.path.join(_tempfile.gettempdir(), "reload-abort-sentinel.tmp")
    with open(sentinel, "wb") as f:
        f.write(b"x")

    backend = _backends.get("fake")
    from backends.base import PreparedVoice, _read_only

    def prepare_with_sentinel(ref, txt, extras):
        if "succeed" in ref:
            return PreparedVoice(
                ref_audio_path=ref, ref_text=txt, extras=_read_only(dict(extras)),
                cleanup_paths=(sentinel,),
            )
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "prepare_voice", prepare_with_sentinel)

    try:
        _write_profile_json(str(tmp_path), "succeed", backend="fake")
        _write_profile_json(str(tmp_path), "fail", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 500
        assert not os.path.exists(sentinel), "rollback did not clean tracked cleanup_paths"
    finally:
        server._clone_enabled = False
        server.VOICES.clear()
        try:
            os.remove(sentinel)
        except OSError:
            pass


def test_reload_abort_cleans_owned_temp_audio(client, tmp_path, monkeypatch):
    """When reload aborts mid-batch, a PreparedVoice with owns_temp_audio=True
    must have its ref_audio_path deleted during rollback."""
    import backends as _backends
    import tempfile as _tempfile
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True

    owned_ref = os.path.join(_tempfile.gettempdir(), "reload-owned-ref.wav")
    with open(owned_ref, "wb") as f:
        f.write(b"x")

    backend = _backends.get("fake")
    from backends.base import PreparedVoice, _read_only

    def prepare_with_owned_temp(ref, txt, extras):
        if "succeed" in ref:
            return PreparedVoice(
                ref_audio_path=owned_ref,
                ref_text=txt,
                extras=_read_only(dict(extras)),
                owns_temp_audio=True,
            )
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "prepare_voice", prepare_with_owned_temp)

    try:
        _write_profile_json(str(tmp_path), "succeed", backend="fake")
        _write_profile_json(str(tmp_path), "fail", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 500
        assert not os.path.exists(owned_ref), \
            "rollback did not delete ref_audio_path for owns_temp_audio=True PreparedVoice"
    finally:
        server._clone_enabled = False
        server.VOICES.clear()
        try:
            os.remove(owned_ref)
        except OSError:
            pass


# ──────────── Voice-family lang routing tests ────────────

def _make_voice_in_voices(name, family, supported_langs, backend_alias="fake"):
    """Inject a fake VoiceProfile into server.VOICES with a specific family + lang capability.
    Hijacks the existing FakeBackend alias for `backend_alias` to advertise `supported_langs`."""
    import backends as _backends
    b = _backends.get(backend_alias)
    # Override supported_langs on this specific FakeBackend instance.
    b.supported_langs = tuple(supported_langs)
    prep = b.prepare_voice("/tmp/x.wav", "ref text", {})
    profile = server.VoiceProfile(
        name=name, backend=backend_alias, ref_audio="/tmp/x.wav", ref_text="ref text",
        session_id=None, emotion="neutral", quality=None, duration_s=None,
        confidence=None, sequence=None, extras={}, prepared=prep,
        family=family,
    )
    server.VOICES[name] = profile


def test_lang_routing_swaps_within_family(client):
    """Request lang=zh against an en-only voice routes to a zh-capable family member."""
    server.VOICES.clear()
    _make_voice_in_voices("alpha-en", family="alpha", supported_langs=("en",), backend_alias="qwen3-0.6b")
    _make_voice_in_voices("alpha-zh", family="alpha", supported_langs=("en", "zh"), backend_alias="voxcpm-1.5")
    try:
        r = client.get("/synthesize", params={"text": "Ni hao", "voice": "alpha-en", "lang": "zh"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "audio/wav"
        # X-Backend reports the routed backend
        assert r.headers.get("x-backend") == "voxcpm-1.5"
    finally:
        server.VOICES.clear()


def test_lang_routing_no_family_match_returns_400(client):
    """No voice in the family supports the requested lang → 400."""
    server.VOICES.clear()
    _make_voice_in_voices("alpha-en", family="alpha", supported_langs=("en",), backend_alias="qwen3-0.6b")
    try:
        r = client.get("/synthesize", params={"text": "Bonjour", "voice": "alpha-en", "lang": "fr"})
        assert r.status_code == 400
        body = r.json()
        assert "supported_langs" in body
        # The message should call out the family
        assert "alpha" in body["error"]
    finally:
        server.VOICES.clear()


def test_lang_routing_ignores_voice_with_no_family(client):
    """family=None → no routing; unsupported lang returns 400 with original-backend message."""
    server.VOICES.clear()
    _make_voice_in_voices("loner", family=None, supported_langs=("en",), backend_alias="qwen3-0.6b")
    # Also register a zh-capable family member that would route IF loner had a family.
    _make_voice_in_voices("zh-helper", family="other", supported_langs=("en", "zh"), backend_alias="voxcpm-1.5")
    try:
        r = client.get("/synthesize", params={"text": "Hi", "voice": "loner", "lang": "zh"})
        assert r.status_code == 400
        body = r.json()
        # Must NOT include the "family" message
        assert "family" not in body["error"]
        assert body["voice_backend"] == "qwen3-0.6b"
    finally:
        server.VOICES.clear()


def test_lang_routing_unchanged_when_lang_supported(client):
    """If the resolved voice already supports the requested lang, no routing occurs."""
    server.VOICES.clear()
    _make_voice_in_voices("alpha-en", family="alpha", supported_langs=("en", "zh"), backend_alias="qwen3-0.6b")
    _make_voice_in_voices("alpha-other", family="alpha", supported_langs=("en", "zh"), backend_alias="voxcpm-1.5")
    try:
        r = client.get("/synthesize", params={"text": "hi", "voice": "alpha-en", "lang": "en"})
        assert r.status_code == 200
        assert r.headers.get("x-backend") == "qwen3-0.6b"  # original, not routed
    finally:
        server.VOICES.clear()


# --- Chatterbox backend unit tests ---


def test_chatterbox_validate_extras_allows_cfg_weight_and_exaggeration():
    """Chatterbox should accept cfg_weight and exaggeration as valid extras."""
    from backends.chatterbox import ChatterboxBackend

    be = ChatterboxBackend()
    # Should not raise
    be.validate_extras({"cfg_weight": 0.7, "exaggeration": 0.5})
    be.validate_extras({"cfg_weight": 0.9})
    be.validate_extras({"exaggeration": 0.3})
    be.validate_extras({})


def test_chatterbox_validate_extras_rejects_unknown():
    """Chatterbox should reject extras it doesn't recognize."""
    from backends.chatterbox import ChatterboxBackend

    be = ChatterboxBackend()
    try:
        be.validate_extras({"unknown_key": 1})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unknown_key" in str(e)


def test_chatterbox_prepare_voice_preserves_extras(tmp_path):
    """prepare_voice should preserve extras into PreparedVoice."""
    import soundfile as sf
    import numpy as np
    from backends.chatterbox import ChatterboxBackend

    ref_wav = tmp_path / "ref.wav"
    sf.write(str(ref_wav), np.zeros(24000, dtype=np.float32), 24000)
    be = ChatterboxBackend()
    pv = be.prepare_voice(str(ref_wav), "hello", {"cfg_weight": 0.8, "exaggeration": 0.4})
    assert pv.extras["cfg_weight"] == 0.8
    assert pv.extras["exaggeration"] == 0.4
    assert pv.data is not None


def test_chatterbox_synthesize_forwards_lang_and_defaults(monkeypatch, tmp_path):
    """synthesize should forward lang_code, cfg_weight, and exaggeration to generate_audio."""
    pytest.importorskip("mlx_audio")
    from backends.chatterbox import ChatterboxBackend, _DEFAULT_CFG_WEIGHT, _DEFAULT_EXAGGERATION
    from backends.base import PreparedVoice, _read_only

    be = ChatterboxBackend()
    be._model = "fake-model"  # bypass load

    captured_kwargs = {}

    def fake_generate_audio(**kwargs):
        captured_kwargs.update(kwargs)
        # Write a tiny WAV so synthesize can read it back
        import numpy as np
        import soundfile as sf
        path = os.path.join(kwargs["output_path"], "out_0.wav")
        sf.write(path, np.zeros(2400, dtype=np.float32), 24000)
        return path

    # generate_audio is imported locally inside synthesize(), so patch at source
    monkeypatch.setattr("mlx_audio.tts.generate.generate_audio", fake_generate_audio)

    # Without extras — should use defaults
    pv = PreparedVoice(
        ref_audio_path=str(tmp_path / "ref.wav"),
        ref_text="hello",
        extras=_read_only({}),
    )
    be.synthesize("test text", pv, "es")

    assert captured_kwargs["lang_code"] == "es"
    assert captured_kwargs["cfg_weight"] == _DEFAULT_CFG_WEIGHT
    assert captured_kwargs["exaggeration"] == _DEFAULT_EXAGGERATION

    # With explicit extras — should override defaults
    captured_kwargs.clear()
    pv2 = PreparedVoice(
        ref_audio_path=str(tmp_path / "ref.wav"),
        ref_text="hello",
        extras=_read_only({"cfg_weight": 0.9, "exaggeration": 0.3}),
    )
    be.synthesize("test text", pv2, "fr")

    assert captured_kwargs["lang_code"] == "fr"
    assert captured_kwargs["cfg_weight"] == 0.9
    assert captured_kwargs["exaggeration"] == 0.3
