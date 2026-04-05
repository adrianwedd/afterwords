from unittest.mock import MagicMock, patch

import numpy as np
from starlette.testclient import TestClient

import server


class _Chunk:
    def __init__(self, audio, sample_rate=24000):
        self.audio = audio
        self.sample_rate = sample_rate


def _fake_generate(**kwargs):
    yield _Chunk(np.zeros(2400, dtype=np.float32), 24000)


def test_health_returns_ok():
    with TestClient(server.app) as client:
        server._ready.set()
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mode"] == "preset-voices-only"


def test_voices_lists_default():
    with TestClient(server.app) as client:
        response = client.get("/voices")
        assert response.status_code == 200
        data = response.json()
        assert data["default_voice"] == server.DEFAULT_VOICE
        assert server.DEFAULT_VOICE in data["voices"]


def test_synthesize_returns_wav():
    fake_model = MagicMock()
    fake_model.generate.side_effect = _fake_generate
    with patch("server._get_model", return_value=fake_model):
        with TestClient(server.app) as client:
            server._ready.set()
            response = client.post(
                "/synthesize",
                json={"text": "Hello from Voxtral", "voice": server.DEFAULT_VOICE},
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "audio/wav"
            assert "x-synthesis-time" in response.headers


def test_synthesize_rejects_unknown_voice():
    with TestClient(server.app) as client:
        server._ready.set()
        response = client.post(
            "/synthesize",
            json={"text": "Hello", "voice": "not-a-voice"},
        )
        assert response.status_code == 400
        assert "unknown voice" in response.json()["error"]
