"""Tests for the Afterwords FastAPI server.

All tests use a mocked ML model — no GPU, no model download,
no network access. The mock generates a tiny valid WAV file
to exercise the full synthesis response path.
"""
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
