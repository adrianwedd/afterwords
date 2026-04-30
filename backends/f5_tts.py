"""F5-TTS backend via SWivid F5-TTS.

F5-TTS uses a flow-matching Diffusion Transformer (DiT) backbone. Upstream
code is MIT licensed, but the default pretrained F5-TTS model weights are
CC-BY-NC 4.0 due to the Emilia training data, so this backend is not suitable
for commercial use unless you configure different weights with a compatible
license.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.f5_tts")

MODEL_ID = "SWivid/F5-TTS/F5TTS_v1_Base"
NATIVE_SR = 24000

_ALLOWED_EXTRAS = {
    "target_rms",
    "cross_fade_duration",
    "sway_sampling_coef",
    "cfg_strength",
    "nfe_step",
    "speed",
    "fix_duration",
    "seed",
}

_FLOAT_EXTRAS = {
    "target_rms",
    "cross_fade_duration",
    "sway_sampling_coef",
    "cfg_strength",
    "speed",
    "fix_duration",
}


def _device(torch) -> str:
    requested = os.environ.get("F5TTS_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch, "xpu", None) is not None and torch.xpu.is_available():
        return "xpu"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class F5TTSBackend(BackendBase):
    name = "f5-tts"
    display_name = "F5-TTS v1 Base (DiT, CC-BY-NC)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("en", "zh")

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
                from f5_tts.api import F5TTS
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-f5tts.txt"
                )
                log.warning("F5-TTS unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            device = _device(torch)
            model = os.environ.get("F5TTS_MODEL", "F5TTS_v1_Base")
            hf_cache_dir = os.environ.get("F5TTS_HF_CACHE_DIR") or None
            log.info("loading %s on %s ...", model, device)
            self._model = F5TTS(model=model, device=device, hf_cache_dir=hf_cache_dir)
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"F5-TTS does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in _FLOAT_EXTRAS:
            value = extras.get(key)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"F5-TTS {key} must be numeric; got {value!r}")
        for key in ("nfe_step", "seed"):
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"F5-TTS {key} must be an integer; got {value!r}")
        if extras.get("nfe_step") is not None and extras["nfe_step"] <= 0:
            raise ValueError(f"F5-TTS nfe_step must be > 0; got {extras['nfe_step']!r}")
        if extras.get("speed") is not None and extras["speed"] <= 0:
            raise ValueError(f"F5-TTS speed must be > 0; got {extras['speed']!r}")
        if extras.get("target_rms") is not None and extras["target_rms"] <= 0:
            raise ValueError(f"F5-TTS target_rms must be > 0; got {extras['target_rms']!r}")
        if extras.get("cross_fade_duration") is not None and extras["cross_fade_duration"] < 0:
            raise ValueError(
                "F5-TTS cross_fade_duration must be >= 0; "
                f"got {extras['cross_fade_duration']!r}"
            )
        if extras.get("cfg_strength") is not None and extras["cfg_strength"] <= 0:
            raise ValueError(f"F5-TTS cfg_strength must be > 0; got {extras['cfg_strength']!r}")
        if extras.get("fix_duration") is not None and extras["fix_duration"] <= 0:
            raise ValueError(f"F5-TTS fix_duration must be > 0; got {extras['fix_duration']!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        if not ref_text or not ref_text.strip():
            raise ValueError("F5-TTS requires reference_text for reliable voice alignment")
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
                raise RuntimeError(f"F5-TTS is unavailable: {self._unavailable_reason}")
            raise RuntimeError("F5TTSBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"f5-tts does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        if not prepared.ref_text:
            raise RuntimeError("F5-TTS prepared voice is missing reference_text")

        kwargs = {
            "ref_file": prepared.ref_audio_path,
            "ref_text": prepared.ref_text,
            "gen_text": text,
            "show_info": log.debug,
            "progress": None,
        }
        for key in _ALLOWED_EXTRAS:
            if key in prepared.extras:
                kwargs[key] = prepared.extras[key]

        wav, sr, _spec = self._model.infer(**kwargs)
        if wav is None:
            raise RuntimeError("F5-TTS produced no output")
        return np.asarray(wav, dtype=np.float32).reshape(-1), int(sr)
