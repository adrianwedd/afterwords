"""Voxtral TTS backend via mlx-audio."""
from __future__ import annotations

import logging
import types
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.voxtral")

MODEL_ID = "mlx-community/Voxtral-4B-TTS-2603-mlx-bf16"
NATIVE_SR = 24000

VOICE_PRESETS = (
    "casual_male",
    "casual_female",
    "cheerful_female",
    "neutral_male",
    "neutral_female",
    "fr_male",
    "fr_female",
    "es_male",
    "es_female",
    "de_male",
    "de_female",
    "it_male",
    "it_female",
    "pt_male",
    "pt_female",
    "nl_male",
    "nl_female",
    "ar_male",
    "hi_male",
    "hi_female",
)

_DEFAULT_VOICE_BY_LANG = {
    "en": "casual_male",
    "fr": "fr_male",
    "es": "es_male",
    "de": "de_male",
    "it": "it_male",
    "pt": "pt_male",
    "nl": "nl_male",
    "ar": "ar_male",
    "hi": "hi_male",
}

_ALLOWED_EXTRAS = {"voice", "temperature", "top_k", "top_p", "max_tokens"}


def _audio_to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "tolist"):
        return np.asarray(audio.tolist(), dtype=np.float32)
    return np.asarray(audio, dtype=np.float32)


class VoxtralBackend(BackendBase):
    name = "voxtral"
    display_name = "Voxtral 4B TTS"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("en", "fr", "es", "de", "it", "pt", "nl", "ar", "hi")

    def __init__(self):
        super().__init__()
        self._model = None
        self._unavailable_reason: str | None = None

    def load(self) -> None:
        def _do():
            try:
                from mlx_audio.tts import load_model
            except ImportError as exc:
                self._unavailable_reason = (
                    f"optional dependencies are not installed: {exc}; "
                    "install mlx-audio and mistral-common[audio]"
                )
                log.warning("Voxtral unavailable: %s", self._unavailable_reason)
                return
            log.info("loading %s ...", MODEL_ID)
            try:
                self._model = load_model(MODEL_ID)
            except (RuntimeError, Exception) as exc:
                self._unavailable_reason = str(exc)
                log.warning("Voxtral unavailable: %s", self._unavailable_reason)
        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"Voxtral does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        voice = extras.get("voice")
        if voice is not None and voice not in VOICE_PRESETS:
            raise ValueError(
                f"Voxtral voice must be one of {VOICE_PRESETS}; got {voice!r}"
            )

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=None,
            extras=_read_only(dict(extras)),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._unavailable_reason:
            raise RuntimeError(f"Voxtral is unavailable: {self._unavailable_reason}")
        if self._model is None:
            raise RuntimeError("VoxtralBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"voxtral does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        # _DEFAULT_VOICE_BY_LANG covers supported_langs today; .get() with a safe
        # fallback prevents KeyError → HTTP 500 if the two ever diverge.
        kwargs = dict(
            text=text,
            voice=prepared.extras.get(
                "voice",
                _DEFAULT_VOICE_BY_LANG.get(lang, "casual_male"),
            ),
            verbose=False,
        )
        for key in ("temperature", "top_k", "top_p", "max_tokens"):
            if key in prepared.extras:
                kwargs[key] = prepared.extras[key]

        result = self._model.generate(**kwargs)
        if isinstance(result, types.GeneratorType):
            chunks = []
            sample_rates = set()
            for gr in result:
                chunks.append(_audio_to_numpy(gr.audio).reshape(-1))
                if hasattr(gr, "sample_rate"):
                    sample_rates.add(gr.sample_rate)
            if not chunks:
                raise RuntimeError("Voxtral produced no audio chunks")
            sr = sample_rates.pop() if len(sample_rates) == 1 else NATIVE_SR
            return np.concatenate(chunks).astype(np.float32, copy=False), sr

        if hasattr(result, "audio"):
            sr = getattr(result, "sample_rate", NATIVE_SR)
            return _audio_to_numpy(result.audio).reshape(-1), sr
        return _audio_to_numpy(result).reshape(-1), NATIVE_SR
