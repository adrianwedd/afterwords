"""NeuTTS Air backend via Neuphonic's `neutts` package.

NeuTTS Air model weights are Apache-2.0. Review the upstream package and
model-card licenses before production or commercial use.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.neutts_air")

MODEL_ID = "neuphonic/neutts-air"
DEFAULT_BACKBONE_REPO = "neuphonic/neutts-air-q4-gguf"
DEFAULT_CODEC_REPO = "neuphonic/neucodec-onnx-decoder"
NATIVE_SR = 24000

_ALLOWED_EXTRAS: set[str] = set()


def _backbone_repo() -> str:
    return os.environ.get("NEUTTS_AIR_BACKBONE_REPO", DEFAULT_BACKBONE_REPO)


def _backbone_device() -> str:
    return os.environ.get("NEUTTS_AIR_BACKBONE_DEVICE", "cpu")


def _codec_repo() -> str:
    return os.environ.get("NEUTTS_AIR_CODEC_REPO", DEFAULT_CODEC_REPO)


def _codec_device() -> str:
    return os.environ.get("NEUTTS_AIR_CODEC_DEVICE", "cpu")


def _language() -> str | None:
    return os.environ.get("NEUTTS_AIR_LANGUAGE")


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


class NeuTTSAirBackend(BackendBase):
    name = "neutts-air"
    display_name = "NeuTTS Air (Apache-2.0)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def __init__(self):
        super().__init__()
        self._model = None
        self._backbone_repo = _backbone_repo()
        self._backbone_device = _backbone_device()
        self._codec_repo = _codec_repo()
        self._codec_device = _codec_device()
        self._language = _language()
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                from neutts import NeuTTS
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-neutts-air.txt"
                )
                log.warning("NeuTTS Air unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            backbone_repo = _backbone_repo()
            backbone_device = _backbone_device()
            codec_repo = _codec_repo()
            codec_device = _codec_device()
            language = _language()

            log.info(
                "loading %s with backbone %s on %s and codec %s on %s ...",
                MODEL_ID,
                backbone_repo,
                backbone_device,
                codec_repo,
                codec_device,
            )
            kwargs = {
                "backbone_repo": backbone_repo,
                "backbone_device": backbone_device,
                "codec_repo": codec_repo,
                "codec_device": codec_device,
            }
            if language:
                kwargs["language"] = language
            self._model = NeuTTS(**kwargs)
            self._backbone_repo = backbone_repo
            self._backbone_device = backbone_device
            self._codec_repo = codec_repo
            self._codec_device = codec_device
            self._language = language
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"NeuTTS Air does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        ref_text = ref_text.strip() if ref_text and ref_text.strip() else None
        prepared_extras = dict(extras)
        if self._model is not None:
            prepared_extras["ref_codes"] = self._model.encode_reference(ref_audio_path)
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(prepared_extras),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            if self._unavailable_reason:
                raise RuntimeError(f"NeuTTS Air is unavailable: {self._unavailable_reason}")
            raise RuntimeError("NeuTTSAirBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"neutts-air does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        ref_codes = prepared.extras.get("ref_codes")
        if ref_codes is None:
            ref_codes = self._model.encode_reference(prepared.ref_audio_path)

        audio = _to_numpy(self._model.infer(text, ref_codes, prepared.ref_text or ""))
        if not audio.size:
            raise RuntimeError("NeuTTS Air produced no output")
        return audio.astype(np.float32, copy=False), NATIVE_SR
