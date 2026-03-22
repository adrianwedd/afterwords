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
    path, text = result
    assert isinstance(path, str)
    assert isinstance(text, str)


def test_resolve_voice_unknown():
    result = server._resolve_voice("definitely_not_a_voice")
    assert result is None
