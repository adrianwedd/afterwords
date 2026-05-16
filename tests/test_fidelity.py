"""MFCC cloning-fidelity test — would catch silent voice-cloning regressions.

Skipped on CI (requires MLX + downloaded weights). Run locally with:
    pytest -m integration tests/test_fidelity.py
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

import backends


pytestmark = pytest.mark.integration

librosa = pytest.importorskip("librosa")
soundfile = pytest.importorskip("soundfile")


VOICES_DIR = os.path.join(os.path.dirname(__file__), "..", "voices")
PHRASE = "The quick brown fox jumps over the lazy dog."


FIDELITY_CASES = [
    ("qwen3-0.6b", "galadriel-qwen3-06b"),
    ("qwen3-1.7b", "galadriel-qwen3-17b"),
    ("chatterbox", "galadriel-chatterbox"),
    ("voxcpm-1.5", "galadriel-voxcpm-15"),
    ("qwen3-0.6b", "picard-qwen3-06b"),
    ("chatterbox", "picard-chatterbox"),
    ("voxcpm-1.5", "picard-voxcpm-15"),
]


SIMILARITY_FLOOR = 0.30


@pytest.fixture(scope="module")
def registered():
    backends.reset_for_tests()
    backends.register_all()
    yield
    backends.reset_for_tests()


def _load_profile(profile_name: str) -> tuple[str, str]:
    with open(os.path.join(VOICES_DIR, f"{profile_name}.json")) as f:
        profile = json.load(f)
    ref_path = os.path.join(VOICES_DIR, profile["reference_audio"])
    ref_text = profile.get("reference_text", "")
    return ref_path, ref_text


def _mean_mfcc(wav: np.ndarray, sr: int) -> np.ndarray:
    mfcc = librosa.feature.mfcc(y=wav.astype(np.float32), sr=sr, n_mfcc=13)
    return mfcc.mean(axis=1)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


@pytest.mark.parametrize("backend_name,profile_name", FIDELITY_CASES)
def test_clone_resembles_reference(registered, backend_name, profile_name):
    ref_path, ref_text = _load_profile(profile_name)

    ref_wav, ref_sr = soundfile.read(ref_path, dtype="float32")
    if ref_wav.ndim > 1:
        ref_wav = ref_wav.mean(axis=1)

    backend = backends.get(backend_name)
    backend.load()
    backend.validate_extras({})
    prepared = backend.prepare_voice(ref_path, ref_text, {})
    out, out_sr = backend.synthesize(PHRASE, prepared, lang="en")

    ref_mfcc = _mean_mfcc(ref_wav, ref_sr)
    out_mfcc = _mean_mfcc(out, out_sr)
    sim = _cosine(ref_mfcc, out_mfcc)

    assert sim >= SIMILARITY_FLOOR, (
        f"{backend_name}/{profile_name}: cosine={sim:.3f} below floor "
        f"{SIMILARITY_FLOOR}. Likely a silent cloning regression."
    )
