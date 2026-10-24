"""The cancellable transport must not swallow the sidecar's diagnostic body.

`request_wav` raised HTTPError with an empty BytesIO, so a sidecar 503 arrived
upstream as `503:` — status preserved, reason gone. This pins the body.
"""
import http.client
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expressive import transport  # noqa: E402


class FakeResponse:
    def __init__(self, status, body, content_type="application/json"):
        self.status = status
        self.reason = "Service Unavailable" if status != 200 else "OK"
        self._body = body
        self.headers = http.client.HTTPMessage()
        self.headers["Content-Type"] = content_type

    def read(self, *a):
        return self._body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


class FakeConnection:
    def __init__(self, response):
        self._response = response
        self.sock = None

    def connect(self):
        pass

    def request(self, *a, **k):
        pass

    def getresponse(self):
        return self._response

    def close(self):
        pass


def test_sidecar_503_body_reaches_the_caller(monkeypatch):
    body = json.dumps({"detail": "RuntimeError: text segment 0 generated no audio"}).encode()
    monkeypatch.setattr(http.client, "HTTPConnection",
                        lambda *a, **k: FakeConnection(FakeResponse(503, body)))
    import threading
    with pytest.raises(urllib.error.HTTPError) as caught:
        transport.request_wav(b"{}", threading.Event())
    assert caught.value.code == 503
    assert b"generated no audio" in caught.value.read()


def test_successful_wav_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(http.client, "HTTPConnection",
                        lambda *a, **k: FakeConnection(FakeResponse(200, b"RIFFxxxx", "audio/wav")))
    import threading
    assert transport.request_wav(b"{}", threading.Event()) == b"RIFFxxxx"


def test_cancellation_still_wins(monkeypatch):
    body = b'{"detail":"x"}'
    monkeypatch.setattr(http.client, "HTTPConnection",
                        lambda *a, **k: FakeConnection(FakeResponse(503, body)))
    import threading
    event = threading.Event()
    event.set()
    with pytest.raises(transport.SynthesisCancelled):
        transport.request_wav(b"{}", event)
