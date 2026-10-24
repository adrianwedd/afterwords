"""Failure classification keeps its evidence (Afterwords API).

A synthesis exception used to leave this server as
`500 {"error": "synthesis failed"}` for every cause. That single string is why
1,253 queued failures in twenty minutes could not be told apart afterwards: the
reason existed at the sidecar and at the backend, and was discarded here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import classify_synthesis_error  # noqa: E402


def test_generic_wrapper_still_classifies_from_the_reason_it_wraps():
    kind, status = classify_synthesis_error(
        "expressive backend unavailable; fallback disabled "
        "(503: {\"detail\":\"insufficient memory headroom for Drama 3 worker\"})")
    assert kind == "resource_exhaustion"
    assert status == 503


def test_reference_problem_is_a_client_error_not_a_service_outage():
    kind, status = classify_synthesis_error("sidecar refused synthesis: 400 "
                                            "{\"detail\":\"reference transcript length invalid\"}")
    assert kind == "invalid_reference"
    assert status == 400


def test_worker_crash_is_distinct_from_memory_pressure():
    assert classify_synthesis_error("expressive worker exited before completion")[0] == "worker_crash"
    assert classify_synthesis_error("insufficient memory headroom")[0] == "resource_exhaustion"


def test_audio_validation_is_its_own_class():
    kind, status = classify_synthesis_error(
        "generated audio contains at least ten seconds of sustained silence")
    assert (kind, status) == ("audio_validation", 503)


def test_unknown_reason_is_not_invented():
    kind, status = classify_synthesis_error("something nobody has seen before")
    assert (kind, status) == ("upstream_error", 500)


def _failing_synthesis(monkeypatch, loopback):
    import server

    class Exploding:
        supported_langs = ("en",)

        def synthesize(self, text, prepared, lang):
            raise RuntimeError("insufficient memory headroom at /Users/someone/models")

    monkeypatch.setattr(server, "_enforce_host_check", loopback)
    monkeypatch.setattr(server.backends, "get", lambda name: Exploding())
    monkeypatch.setattr(server, "_route_for_lang", lambda profile, lang: profile)
    monkeypatch.setattr(server, "_run_in_ml_thread", lambda fn, *a: fn(*a))
    profile = type("P", (), {"name": "v", "backend": "qwen3-0.6b", "prepared": None})()
    response = server._synthesize_audio("hello", profile, "en")
    import json
    return response.status_code, json.loads(response.body)


import pytest  # noqa: E402


@pytest.mark.parametrize("loopback", [True, False])
def test_known_failure_never_degrades_to_the_bare_generic_body(monkeypatch, loopback):
    status, body = _failing_synthesis(monkeypatch, loopback)
    assert status == 503
    assert body["error_class"] == "resource_exhaustion"
    assert body["voice_backend"] == "qwen3-0.6b"


def test_reason_stays_in_the_log_not_the_response(monkeypatch, caplog):
    with caplog.at_level("ERROR", logger="tts"):
        status, body = _failing_synthesis(monkeypatch, loopback=True)
    assert "reason" not in body and "/Users/someone" not in str(body)
    assert "insufficient memory headroom" in caplog.text
    assert "[resource_exhaustion]" in caplog.text
