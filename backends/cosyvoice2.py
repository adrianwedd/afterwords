"""CosyVoice2-0.5B backend via FunAudioLLM CosyVoice.

CosyVoice upstream code and CosyVoice2-0.5B weights are Apache-2.0 licensed.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.cosyvoice2")

MODEL_ID = "FunAudioLLM/CosyVoice2-0.5B"
NATIVE_SR = 24000
DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backends",
    "extras",
    "cosyvoice2",
    "CosyVoice2-0.5B",
)

_ALLOWED_EXTRAS = {"speed", "text_frontend"}


def _model_dir() -> str:
    return os.environ.get("COSYVOICE2_MODEL_DIR", DEFAULT_MODEL_DIR)


def _to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class CosyVoice2Backend(BackendBase):
    name = "cosyvoice2"
    display_name = "CosyVoice2-0.5B (Apache-2.0)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("en", "zh", "ja", "ko", "de", "es", "fr", "it", "ru")

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_dir = _model_dir()
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            model_dir = _model_dir()
            if not os.path.exists(model_dir):
                self._unavailable_reason = (
                    "CosyVoice2 model directory not found. Download "
                    f"{MODEL_ID} to {model_dir!r} or set COSYVOICE2_MODEL_DIR."
                )
                log.warning("CosyVoice2 unavailable: %s", self._unavailable_reason)
                return

            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                from cosyvoice.cli.cosyvoice import CosyVoice2
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-cosyvoice2.txt"
                )
                log.warning("CosyVoice2 unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            log.info("loading %s from %s ...", MODEL_ID, model_dir)
            self._model = CosyVoice2(model_dir)
            self._model_dir = model_dir
            self.sample_rate = int(getattr(self._model, "sample_rate", NATIVE_SR))
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"CosyVoice2 does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        speed = extras.get("speed")
        if speed is not None and not isinstance(speed, (int, float)):
            raise ValueError(f"CosyVoice2 speed must be numeric; got {speed!r}")
        if speed is not None and speed <= 0:
            raise ValueError(f"CosyVoice2 speed must be > 0; got {speed!r}")
        text_frontend = extras.get("text_frontend")
        if text_frontend is not None and not isinstance(text_frontend, bool):
            raise ValueError(f"CosyVoice2 text_frontend must be boolean; got {text_frontend!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        if not ref_text or not ref_text.strip():
            raise ValueError("CosyVoice2 requires reference_text aligned with reference audio")
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text.strip(),
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
                raise RuntimeError(f"CosyVoice2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("CosyVoice2Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"cosyvoice2 does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        if not prepared.ref_text:
            raise RuntimeError("CosyVoice2 prepared voice is missing reference_text")

        chunks = []
        for output in self._model.inference_zero_shot(
            text,
            prepared.ref_text,
            prepared.ref_audio_path,
            stream=False,
            speed=float(prepared.extras.get("speed", 1.0)),
            text_frontend=bool(prepared.extras.get("text_frontend", True)),
        ):
            if not isinstance(output, Mapping) or "tts_speech" not in output:
                raise RuntimeError("CosyVoice2 produced an invalid output chunk")
            chunks.append(_to_numpy(output["tts_speech"]))

        if not chunks:
            raise RuntimeError("CosyVoice2 produced no output")
        audio = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
        return audio.astype(np.float32, copy=False), int(getattr(self._model, "sample_rate", NATIVE_SR))
