"""Integration tests — actually load each backend + synth a short clip.

Opt-in:
    pytest -m integration tests/test_backends_integration.py

Requires MLX + ~10 GB RAM + network (first run downloads weights).
"""
from __future__ import annotations

import os

import numpy as np
import pytest

import backends


pytestmark = pytest.mark.integration


SHORT_REF = os.path.join(
    os.path.dirname(__file__), "..", "voices", "galadriel-ref.wav"
)
SHORT_REF_TEXT = "In the beginning."


@pytest.fixture(scope="module")
def registered():
    backends.reset_for_tests()
    backends.register_all()
    yield
    backends.reset_for_tests()


@pytest.mark.parametrize("backend_name", [
    "qwen3-0.6b",
    "qwen3-1.7b",
    "voxtral",
])
def test_backend_loads_and_synthesizes_short_clip(registered, backend_name):
    b = backends.get(backend_name)
    b.load()
    b.validate_extras({})
    prepared = b.prepare_voice(SHORT_REF, SHORT_REF_TEXT, {})
    audio, sr = b.synthesize("Hello.", prepared, lang="en")
    assert isinstance(audio, np.ndarray)
    assert audio.ndim == 1
    assert sr == b.sample_rate
    assert audio.size > sr * 0.1  # at least 100ms of audio
