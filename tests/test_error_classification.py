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


def test_known_failure_never_degrades_to_the_bare_generic_body():
    """The handler must carry reason + error_class; this asserts the contract
    the handler is written against, without booting the server."""
    import inspect
    import server

    source = inspect.getsource(server._synthesize_audio)
    assert '"reason": detail' in source
    assert '"error_class": category' in source
