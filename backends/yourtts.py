"""YourTTS backend via Coqui TTS.

YourTTS is Coqui's older lightweight multilingual VITS-based zero-shot cloning
model. It uses the same ``TTS.api.TTS`` package as XTTS v2, but the model is
open source and outputs 16 kHz audio.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.yourtts")

MODEL_ID = "tts_models/multilingual/multi-dataset/your_tts"
NATIVE_SR = 16000
SUPPORTED_LANGS = ("en", "fr", "pt-BR")
_COQUI_LANGS = {
    "en": "en",
    "fr": "fr-fr",
    "pt-BR": "pt-br",
}


def _device(torch) -> str:
    requested = os.environ.get("YOURTTS_DEVICE")
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


class YourTTSBackend(BackendBase):
    name = "yourtts"
    display_name = "YourTTS (Coqui VITS, open source)"
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
                    "install requirements-yourtts.txt"
                )
                log.warning("YourTTS unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            device = _device(torch)
            model_id = os.environ.get("YOURTTS_MODEL", MODEL_ID)
            log.info("loading %s on %s ...", model_id, device)
            self._model = TTS(model_id, progress_bar=False).to(device)
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - set()
        if unknown:
            raise ValueError(f"YourTTS does not accept extras: {sorted(unknown)}")

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
                raise RuntimeError(f"YourTTS is unavailable: {self._unavailable_reason}")
            raise RuntimeError("YourTTSBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"yourtts does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        audio = self._model.tts(
            text=text,
            speaker_wav=prepared.ref_audio_path,
            language=_COQUI_LANGS[lang],
        )
        if audio is None:
            raise RuntimeError("YourTTS produced no output")
        audio_np = _to_numpy(audio)
        if audio_np.size == 0:
            raise RuntimeError("YourTTS produced no output")
        return audio_np, self.sample_rate
