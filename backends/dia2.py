"""Dia2 backend via Nari Labs' streaming dialogue TTS runtime.

Dia2 code and model weights are Apache-2.0. Upstream is CUDA-first; Apple
Silicon users may need to set DIA2_DEVICE=mps/cpu depending on local PyTorch
support and upstream compatibility.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.dia2")

MODEL_ID = "nari-labs/Dia2-2B"
NATIVE_SR = 44100

_ALLOWED_EXTRAS = {
    "temperature",
    "top_k",
    "text_temperature",
    "text_top_k",
    "audio_temperature",
    "audio_top_k",
    "cfg_scale",
    "cfg_filter_k",
    "initial_padding",
    "use_cuda_graph",
    "use_torch_compile",
    "include_prefix",
    "verbose",
}


def _model_id() -> str:
    return os.environ.get("DIA2_MODEL_ID", MODEL_ID)


def _device(torch) -> str:
    requested = os.environ.get("DIA2_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _dtype() -> str:
    return os.environ.get("DIA2_DTYPE", "bfloat16")


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


def _script_for_speaker_one(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("[S1]") or stripped.startswith("[S2]"):
        return stripped
    return f"[S1] {stripped}"


class Dia2Backend(BackendBase):
    name = "dia2"
    display_name = "Dia2 (Nari Labs Apache-2.0)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def __init__(self):
        super().__init__()
        self._model = None
        self._GenerationConfig = None
        self._PrefixConfig = None
        self._SamplingConfig = None
        self._model_id = _model_id()
        self._device = None
        self._dtype = _dtype()
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                import torch
                from dia2 import Dia2, GenerationConfig, PrefixConfig, SamplingConfig
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-dia2.txt"
                )
                log.warning("Dia2 unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            model_id = _model_id()
            device = _device(torch)
            dtype = _dtype()
            log.info("loading %s on %s with dtype=%s ...", model_id, device, dtype)
            self._model = Dia2.from_repo(model_id, device=device, dtype=dtype)
            self._GenerationConfig = GenerationConfig
            self._PrefixConfig = PrefixConfig
            self._SamplingConfig = SamplingConfig
            self._model_id = model_id
            self.model_id = model_id
            self._device = device
            self._dtype = dtype
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"Dia2 does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in ("temperature", "text_temperature", "audio_temperature", "cfg_scale"):
            value = extras.get(key)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"Dia2 {key} must be numeric; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"Dia2 {key} must be > 0; got {value!r}")
        for key in ("top_k", "text_top_k", "audio_top_k", "cfg_filter_k", "initial_padding"):
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"Dia2 {key} must be an integer; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"Dia2 {key} must be > 0; got {value!r}")
        for key in ("use_cuda_graph", "use_torch_compile", "include_prefix", "verbose"):
            value = extras.get(key)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"Dia2 {key} must be boolean; got {value!r}")

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

    def _generation_config(self, extras: Mapping[str, object]):
        if self._GenerationConfig is None or self._PrefixConfig is None or self._SamplingConfig is None:
            raise RuntimeError("Dia2Backend.synthesize called before load()")

        temperature = float(extras.get("temperature", 0.8))
        top_k = int(extras.get("top_k", 50))
        text_sampling = self._SamplingConfig(
            temperature=float(extras.get("text_temperature", temperature)),
            top_k=int(extras.get("text_top_k", top_k)),
        )
        audio_sampling = self._SamplingConfig(
            temperature=float(extras.get("audio_temperature", temperature)),
            top_k=int(extras.get("audio_top_k", top_k)),
        )
        return self._GenerationConfig(
            text=text_sampling,
            audio=audio_sampling,
            cfg_scale=float(extras.get("cfg_scale", 2.0)),
            cfg_filter_k=int(extras.get("cfg_filter_k", 50)),
            initial_padding=int(extras.get("initial_padding", 2)),
            prefix=self._PrefixConfig(
                speaker_1=None,
                speaker_2=None,
                include_audio=bool(extras.get("include_prefix", False)),
            ),
            use_cuda_graph=bool(extras.get("use_cuda_graph", False)),
            use_torch_compile=bool(extras.get("use_torch_compile", False)),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            if self._unavailable_reason:
                raise RuntimeError(f"Dia2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("Dia2Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"dia2 does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        config = self._generation_config(prepared.extras)
        result = self._model.generate(
            _script_for_speaker_one(text),
            config=config,
            prefix_speaker_1=prepared.ref_audio_path,
            include_prefix=bool(prepared.extras.get("include_prefix", False)),
            verbose=bool(prepared.extras.get("verbose", False)),
        )
        waveform = getattr(result, "waveform", result)
        audio = _to_numpy(waveform)
        if not audio.size:
            raise RuntimeError("Dia2 produced no output")
        return audio.astype(np.float32, copy=False), int(getattr(result, "sample_rate", self.sample_rate))
