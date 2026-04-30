"""XTTS v2 backend via Coqui TTS.

Coqui TTS code is MPL-2.0, but the XTTS v2 model weights are licensed under
the Coqui Public Model License (CPML). CPML restricts use to non-commercial
purposes; do not use this backend for commercial work unless you have separate
rights to compatible weights.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.xtts_v2")

MODEL_ID = "tts_models/multilingual/multi-dataset/xtts_v2"
NATIVE_SR = 24000
SUPPORTED_LANGS = (
    "en",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "pl",
    "tr",
    "ru",
    "nl",
    "cs",
    "ar",
    "zh",
    "hu",
    "ko",
    "ja",
    "hi",
)


def _device(torch) -> str:
    requested = os.environ.get("XTTS_V2_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda"
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
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class XTTSv2Backend(BackendBase):
    name = "xtts-v2"
    display_name = "XTTS v2 (CPML, non-commercial)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = SUPPORTED_LANGS

    def __init__(self):
        super().__init__()
        self._model = None
        self._device = None
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                import torch
                from TTS.api import TTS
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-xtts.txt"
                )
                log.warning("XTTS v2 unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            device = _device(torch)
            model_id = os.environ.get("XTTS_V2_MODEL", MODEL_ID)
            log.info("loading %s on %s ...", model_id, device)
            self._model = TTS(model_id, progress_bar=False).to(device)
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - set()
        if unknown:
            raise ValueError(f"XTTS v2 does not accept extras: {sorted(unknown)}")

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
                raise RuntimeError(f"XTTS v2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("XTTSv2Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"xtts-v2 does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        audio = self._model.tts(
            text=text,
            speaker_wav=prepared.ref_audio_path,
            language=lang,
        )
        if audio is None:
            raise RuntimeError("XTTS v2 produced no output")
        return _to_numpy(audio), self.sample_rate
