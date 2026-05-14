"""Spark-TTS backend via SparkAudio/Spark-TTS.

Spark-TTS upstream code is Apache-2.0, but the Spark-TTS-0.5B model weights
are CC-BY-NC-SA 4.0 and non-commercial. Review upstream license terms before
production use.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only, resolve_repo_dir

log = logging.getLogger("backends.spark_tts")

MODEL_ID = "SparkAudio/Spark-TTS-0.5B"
NATIVE_SR = 24000
DEFAULT_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backends",
    "extras",
    "spark-tts",
)
DEFAULT_REPO_DIR = os.path.join(DEFAULT_BASE_DIR, "Spark-TTS")
DEFAULT_MODEL_DIR = os.path.join(DEFAULT_BASE_DIR, "Spark-TTS-0.5B")

_ALLOWED_EXTRAS = {"temperature", "top_k", "top_p"}


def _repo_dir() -> str:
    return resolve_repo_dir(os.path.expanduser(os.environ.get("SPARK_TTS_REPO_DIR", DEFAULT_REPO_DIR)))


def _model_dir() -> str:
    return os.environ.get("SPARK_TTS_MODEL_DIR", DEFAULT_MODEL_DIR)


def _device(torch) -> str:
    requested = os.environ.get("SPARK_TTS_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda:0"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    audio = np.asarray(audio)
    if np.issubdtype(audio.dtype, np.integer):
        max_value = float(np.iinfo(audio.dtype).max)
        audio = audio.astype(np.float32) / max_value
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class SparkTTSBackend(BackendBase):
    name = "spark-tts"
    display_name = "Spark-TTS-0.5B (CC-BY-NC-SA 4.0 weights)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "zh")

    def __init__(self):
        super().__init__()
        self._model = None
        self._repo_dir = _repo_dir()
        self._model_dir = _model_dir()
        self._device = None
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            repo_dir = _repo_dir()
            model_dir = _model_dir()
            if os.path.isdir(repo_dir) and repo_dir not in sys.path:
                sys.path.insert(0, repo_dir)
            if not os.path.exists(os.path.join(model_dir, "config.yaml")):
                self._unavailable_reason = (
                    "Spark-TTS model directory not found. Download "
                    f"{MODEL_ID} to {model_dir!r} or set SPARK_TTS_MODEL_DIR."
                )
                log.warning("Spark-TTS unavailable: %s", self._unavailable_reason)
                return

            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                import torch
                from cli.SparkTTS import SparkTTS
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; install "
                    "requirements-spark-tts.txt and clone Spark-TTS to "
                    f"{repo_dir!r} or set SPARK_TTS_REPO_DIR"
                )
                log.warning("Spark-TTS unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            device = _device(torch)
            log.info("loading %s from %s on %s ...", MODEL_ID, model_dir, device)
            self._model = SparkTTS(Path(model_dir), device=torch.device(device))
            self._repo_dir = repo_dir
            self._model_dir = model_dir
            self._device = device
            self.sample_rate = int(getattr(self._model, "sample_rate", NATIVE_SR))
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"Spark-TTS does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in ("temperature", "top_p"):
            value = extras.get(key)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"Spark-TTS {key} must be numeric; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"Spark-TTS {key} must be > 0; got {value!r}")
        top_k = extras.get("top_k")
        if top_k is not None and (not isinstance(top_k, int) or isinstance(top_k, bool)):
            raise ValueError(f"Spark-TTS top_k must be an integer; got {top_k!r}")
        if top_k is not None and top_k <= 0:
            raise ValueError(f"Spark-TTS top_k must be > 0; got {top_k!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        ref_text = ref_text.strip() if ref_text and ref_text.strip() else None
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(extras),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            if self._unavailable_reason:
                raise RuntimeError(f"Spark-TTS is unavailable: {self._unavailable_reason}")
            raise RuntimeError("SparkTTSBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"spark-tts does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        kwargs = {
            "text": text,
            "prompt_speech_path": Path(prepared.ref_audio_path),
            "prompt_text": prepared.ref_text,
        }
        for key in ("temperature", "top_k", "top_p"):
            if key in prepared.extras:
                kwargs[key] = prepared.extras[key]

        audio = _to_numpy(self._model.inference(**kwargs))
        if not audio.size:
            raise RuntimeError("Spark-TTS produced no output")
        return audio.astype(np.float32, copy=False), int(getattr(self._model, "sample_rate", self.sample_rate))
