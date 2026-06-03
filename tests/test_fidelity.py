"""MFCC cloning-fidelity test — guards against silent voice-cloning regressions.

This is a coarse smoke test, not a perceptual judge. Perceptual fidelity is
verified by the human listen-tests documented under Sprint 1 of the v1.0.0
roadmap. The test catches the *class* of regression where a backend silently
falls back to its default voice (e.g. the VoxCPM `ref_audio` kwarg rename
from #14), but it will not catch subtle accent drift or prosody bugs.

Design notes (informed by multi-agent QA, 2026-05-16):
- Reference and synthesized audio are resampled to a common 16 kHz before
  MFCC extraction. Without this, comparing 24 kHz Qwen3/Chatterbox output
  against a 44.1 kHz reference (or VoxCPM's 44.1 kHz output against a 24 kHz
  reference) compares MFCCs over different frequency bands.
- MFCC coefficient 0 (log-energy / loudness) is dropped. It dominates the
  vector norm and would let any non-silent audio score >0.9 against any
  reference, defeating the regression check.
- The test synthesizes each profile's *own* reference_text, not a generic
  phrase. MFCCs are phoneme-sensitive; matching content reduces variance
  unrelated to speaker identity.
- A running afterwords server would compete with this test for the single
  Metal device — the test detects that and skips with a clear message
  rather than OOMing or producing flaky results.

Skipped on CI (requires MLX + downloaded weights). Run locally with:
    afterwords stop
    pytest -m integration tests/test_fidelity.py
"""
from __future__ import annotations

import json
import os
import socket

import numpy as np
import pytest

import backends


pytestmark = pytest.mark.integration

librosa = pytest.importorskip("librosa")
soundfile = pytest.importorskip("soundfile")


VOICES_DIR = os.path.join(os.path.dirname(__file__), "..", "voices")
COMMON_SR = 16000  # standard sample rate for speaker analysis

# Coefficient 0 is log-energy and dominates the cosine; we slice [1:n_mfcc].
N_MFCC = 13

# Empirically uncalibrated floor — TODO calibrate after first live run during
# Sprint 1 listen-test session. Set conservatively to catch only catastrophic
# regressions (silence, wrong-speaker fallback). Lower than expected because
# even matching content has phonetic variance.
SIMILARITY_FLOOR = 0.55


FIDELITY_CASES = [
    ("qwen3-0.6b", "galadriel-qwen3-06b"),
    ("qwen3-1.7b", "galadriel-qwen3-17b"),
    ("qwen3-0.6b", "picard-qwen3-06b"),
    ("qwen3-1.7b", "picard-qwen3-17b"),
    ("qwen3-0.6b", "attenborough-qwen3-06b"),
    ("qwen3-1.7b", "attenborough-qwen3-17b"),
]


def _server_running(port: int = 7860) -> bool:
    """Return True if a TCP listener is bound on localhost:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


@pytest.fixture(scope="module", autouse=True)
def _skip_if_server_running():
    """The launchd-managed server holds ~10 GB of Metal memory. This test
    process would try to load another ~10 GB, causing OOM on 16 GB machines
    and Metal contention everywhere. Skip cleanly with an actionable hint."""
    if _server_running():
        pytest.skip(
            "afterwords server is running on :7860 — Metal contention would "
            "make this test flaky. Stop it first: `afterwords stop`."
        )


@pytest.fixture(scope="module")
def registered():
    backends.reset_for_tests()
    backends.register_all(with_17b=True)
    yield
    backends.reset_for_tests()


def _load_profile(profile_name: str) -> tuple[str, str]:
    """Return (ref_audio_path, ref_text) for a voices/*.json profile."""
    with open(os.path.join(VOICES_DIR, f"{profile_name}.json")) as f:
        profile = json.load(f)
    ref_path = os.path.join(VOICES_DIR, profile["reference_audio"])
    ref_text = profile.get("reference_text", "")
    return ref_path, ref_text


def _to_mono_16k(wav: np.ndarray, sr: int) -> np.ndarray:
    """Downmix to mono and resample to COMMON_SR so MFCCs are comparable."""
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    wav = wav.astype(np.float32)
    if sr != COMMON_SR:
        wav = librosa.resample(wav, orig_sr=sr, target_sr=COMMON_SR)
    return wav


def _spectral_mfcc(wav: np.ndarray) -> np.ndarray:
    """Mean-pooled MFCC[1:] — drops the log-energy coefficient so cosine
    reflects spectral shape, not loudness."""
    mfcc = librosa.feature.mfcc(y=wav, sr=COMMON_SR, n_mfcc=N_MFCC)
    return mfcc.mean(axis=1)[1:]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    assert na > 0 and nb > 0, "zero-norm MFCC vector — input is silent"
    return float(np.dot(a, b) / (na * nb))


@pytest.mark.parametrize("backend_name,profile_name", FIDELITY_CASES)
def test_clone_resembles_reference(registered, backend_name, profile_name):
    ref_path, ref_text = _load_profile(profile_name)
    if not ref_text:
        pytest.skip(f"{profile_name} has no reference_text — cannot match phonemes")

    ref_wav_raw, ref_sr = soundfile.read(ref_path, dtype="float32")
    ref_wav = _to_mono_16k(ref_wav_raw, ref_sr)

    backend = backends.get(backend_name)
    backend.load()
    backend.validate_extras({})
    prepared = backend.prepare_voice(ref_path, ref_text, {})
    # Synthesize the reference text so phonetic content matches.
    out_raw, out_sr = backend.synthesize(ref_text, prepared, lang="en")
    out_wav = _to_mono_16k(out_raw, out_sr)

    ref_mfcc = _spectral_mfcc(ref_wav)
    out_mfcc = _spectral_mfcc(out_wav)
    sim = _cosine(ref_mfcc, out_mfcc)

    assert sim >= SIMILARITY_FLOOR, (
        f"{backend_name}/{profile_name}: cosine={sim:.3f} below floor "
        f"{SIMILARITY_FLOOR}. Likely a silent cloning regression."
    )
