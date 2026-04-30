"""FireRedTTS-2 backend via FireRedTeam's PyTorch runtime.

FireRedTTS-2 is Apache-2.0 and targets long-form conversational speech. This
backend uses upstream monologue generation for Afterwords' single-reference
voice profiles.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.firered_tts_2")

MODEL_ID = "FireRedTeam/FireRedTTS2"
NATIVE_SR = 24000
DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backends",
    "extras",
    "firered-tts-2",
    "FireRedTTS2",
)
SUPPORTED_LANGS = ("en", "zh", "ja", "ko", "fr", "de", "ru")

_ALLOWED_EXTRAS = {"temperature", "topk", "top_k"}


def _model_dir() -> str:
    return os.environ.get("FIRERED_TTS_2_MODEL_DIR", DEFAULT_MODEL_DIR)


def _device(torch) -> str:
    requested = os.environ.get("FIRERED_TTS_2_DEVICE")
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
    audio = np.asarray(audio)
    if np.issubdtype(audio.dtype, np.integer):
        max_value = float(np.iinfo(audio.dtype).max)
        audio = audio.astype(np.float32) / max_value
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def _coerce_output(output) -> tuple[np.ndarray, int]:
    if output is None:
        raise RuntimeError("FireRedTTS-2 produced no output")
    if isinstance(output, tuple) and len(output) == 2:
        sample_rate, audio = output
        return _to_numpy(audio), int(sample_rate)
    if isinstance(output, Mapping):
        audio = output.get("audio", output.get("waveform", output.get("wav")))
        if audio is None:
            raise RuntimeError("FireRedTTS-2 produced an invalid output")
        sample_rate = output.get("sample_rate", output.get("sr", NATIVE_SR))
        return _to_numpy(audio), int(sample_rate)
    return _to_numpy(output), NATIVE_SR


class FireRedTTS2Backend(BackendBase):
    name = "firered-tts-2"
    display_name = "FireRedTTS-2 (Apache-2.0)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = SUPPORTED_LANGS

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_dir = _model_dir()
        self._device = None
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                import torch
                from fireredtts2.fireredtts2 import FireRedTTS2
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-firered-tts-2.txt"
                )
                log.warning("FireRedTTS-2 unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            model_dir = _model_dir()
            if not os.path.isdir(model_dir):
                self._unavailable_reason = (
                    "FireRedTTS-2 model directory not found. Download "
                    f"{MODEL_ID} to {model_dir!r} or set FIRERED_TTS_2_MODEL_DIR."
                )
                log.warning("FireRedTTS-2 unavailable: %s", self._unavailable_reason)
                return

            device = _device(torch)
            log.info("loading %s from %s on %s ...", MODEL_ID, model_dir, device)
            self._model = FireRedTTS2(
                pretrained_dir=model_dir,
                gen_type="monologue",
                device=device,
            )
            self._model_dir = model_dir
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"FireRedTTS-2 does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        if "topk" in extras and "top_k" in extras:
            raise ValueError("FireRedTTS-2 accepts either topk or top_k, not both")
        temperature = extras.get("temperature")
        if temperature is not None and not isinstance(temperature, (int, float)):
            raise ValueError(f"FireRedTTS-2 temperature must be numeric; got {temperature!r}")
        if temperature is not None and temperature <= 0:
            raise ValueError(f"FireRedTTS-2 temperature must be > 0; got {temperature!r}")
        for key in ("topk", "top_k"):
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"FireRedTTS-2 {key} must be an integer; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"FireRedTTS-2 {key} must be > 0; got {value!r}")

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
                raise RuntimeError(f"FireRedTTS-2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("FireRedTTS2Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"firered-tts-2 does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        kwargs = {
            "text": text,
            "prompt_wav": prepared.ref_audio_path,
            "prompt_text": prepared.ref_text,
        }
        if "temperature" in prepared.extras:
            kwargs["temperature"] = prepared.extras["temperature"]
        if "topk" in prepared.extras:
            kwargs["topk"] = prepared.extras["topk"]
        if "top_k" in prepared.extras:
            kwargs["topk"] = prepared.extras["top_k"]

        audio, sample_rate = _coerce_output(self._model.generate_monologue(**kwargs))
        if not audio.size:
            raise RuntimeError("FireRedTTS-2 produced no output")
        return audio.astype(np.float32, copy=False), sample_rate
