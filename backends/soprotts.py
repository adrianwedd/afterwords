"""Sopro TTS backend via samuel-vitorino/sopro.

Sopro is a small Apache-2.0 English zero-shot cloning model. Upstream exposes
both a raw reference-audio path and a prepared-reference API; this backend
prepares the reference when the model is loaded and falls back to path-based
synthesis if a PreparedVoice was created before load().
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.soprotts")

MODEL_ID = "samuel-vitorino/sopro"
NATIVE_SR = 24000
SUPPORTED_LANGS = ("en",)

_ALLOWED_EXTRAS = {
    "anti_loop",
    "max_frames",
    "min_gen_frames",
    "ref_seconds",
    "style_strength",
    "temperature",
    "top_p",
}
_NUMERIC_EXTRAS = {"ref_seconds", "style_strength", "temperature", "top_p"}
_INTEGER_EXTRAS = {"max_frames", "min_gen_frames"}


def _device() -> str:
    return os.environ.get("SOPROTTS_DEVICE", "cpu")


def _to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class SoproTTSBackend(BackendBase):
    name = "soprotts"
    display_name = "SoproTTS v1.5 (Apache-2.0)"
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
                from sopro import SoproTTS
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-soprotts.txt"
                )
                log.warning("SoproTTS unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            device = _device()
            model_id = os.environ.get("SOPROTTS_MODEL", MODEL_ID)
            log.info("loading %s on %s ...", model_id, device)
            self._model = SoproTTS.from_pretrained(model_id, device=device)
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"SoproTTS does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in _NUMERIC_EXTRAS:
            value = extras.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise ValueError(f"SoproTTS {key} must be numeric; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"SoproTTS {key} must be > 0; got {value!r}")
        top_p = extras.get("top_p")
        if top_p is not None and top_p > 1:
            raise ValueError(f"SoproTTS top_p must be <= 1; got {top_p!r}")
        for key in _INTEGER_EXTRAS:
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"SoproTTS {key} must be an integer; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"SoproTTS {key} must be > 0; got {value!r}")
        anti_loop = extras.get("anti_loop")
        if anti_loop is not None and not isinstance(anti_loop, bool):
            raise ValueError(f"SoproTTS anti_loop must be boolean; got {anti_loop!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        if self._unavailable_reason:
            raise RuntimeError(f"SoproTTS is unavailable: {self._unavailable_reason}")

        prepared_extras = dict(extras)
        if self._model is not None:
            ref_kwargs = {"ref_audio_path": ref_audio_path}
            if "ref_seconds" in extras:
                ref_kwargs["ref_seconds"] = float(extras["ref_seconds"])
            prepared_extras["ref"] = self._model.prepare_reference(**ref_kwargs)

        ref_text = ref_text.strip() if ref_text and ref_text.strip() else None
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
                raise RuntimeError(f"SoproTTS is unavailable: {self._unavailable_reason}")
            raise RuntimeError("SoproTTSBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"soprotts does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        kwargs = {
            key: prepared.extras[key]
            for key in (
                "anti_loop",
                "max_frames",
                "min_gen_frames",
                "style_strength",
                "temperature",
                "top_p",
            )
            if key in prepared.extras
        }
        if "ref" in prepared.extras:
            kwargs["ref"] = prepared.extras["ref"]
        else:
            kwargs["ref_audio_path"] = prepared.ref_audio_path
            if "ref_seconds" in prepared.extras:
                kwargs["ref_seconds"] = float(prepared.extras["ref_seconds"])

        audio = self._model.synthesize(text, **kwargs)
        if audio is None:
            raise RuntimeError("SoproTTS produced no output")
        audio_np = _to_numpy(audio)
        if audio_np.size == 0:
            raise RuntimeError("SoproTTS produced no output")
        return audio_np, self.sample_rate
