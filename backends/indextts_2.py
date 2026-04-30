"""IndexTTS-2 backend via index-tts.

IndexTTS-2 uses the bilibili Model Use License
(`LicenseRef-Bilibili-IndexTTS`), which includes usage restrictions. Review
the upstream license before production or commercial use.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.indextts_2")

MODEL_ID = "IndexTeam/IndexTTS-2"
NATIVE_SR = 22050
DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backends",
    "extras",
    "indextts-2",
    "checkpoints",
)

_ALLOWED_EXTRAS = {
    "emo_alpha",
    "emo_audio_prompt",
    "emo_text",
    "emo_vector",
    "interval_silence",
    "length_penalty",
    "max_mel_tokens",
    "max_text_tokens_per_segment",
    "num_beams",
    "repetition_penalty",
    "temperature",
    "top_k",
    "top_p",
    "use_emo_text",
    "use_random",
}
_FLOAT_EXTRAS = {
    "emo_alpha",
    "interval_silence",
    "length_penalty",
    "repetition_penalty",
    "temperature",
    "top_p",
}
_INT_EXTRAS = {"max_mel_tokens", "max_text_tokens_per_segment", "num_beams", "top_k"}
_EMOTION_VECTOR_LEN = 8


def _model_dir() -> str:
    return os.environ.get("INDEXTTS2_MODEL_DIR", DEFAULT_MODEL_DIR)


def _cfg_path(model_dir: str) -> str:
    return os.environ.get("INDEXTTS2_CFG_PATH", os.path.join(model_dir, "config.yaml"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _device(torch) -> str:
    requested = os.environ.get("INDEXTTS2_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch, "xpu", None) is not None and torch.xpu.is_available():
        return "xpu"
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


def _coerce_infer_output(output) -> tuple[np.ndarray, int]:
    if output is None:
        raise RuntimeError("IndexTTS-2 produced no output")
    if isinstance(output, tuple) and len(output) == 2:
        sr, audio = output
        return _to_numpy(audio), int(sr)
    if isinstance(output, Mapping):
        audio = output.get("audio", output.get("wav", output.get("tts_speech")))
        if audio is None:
            raise RuntimeError("IndexTTS-2 produced an invalid output")
        sr = output.get("sample_rate", output.get("sr", NATIVE_SR))
        return _to_numpy(audio), int(sr)
    return _to_numpy(output), NATIVE_SR


class IndexTTS2Backend(BackendBase):
    name = "indextts-2"
    display_name = "IndexTTS-2 (bilibili Model Use License)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "zh")

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_dir = _model_dir()
        self._cfg_path = _cfg_path(self._model_dir)
        self._device = None
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                import torch
                from indextts.infer_v2 import IndexTTS2
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-indextts.txt"
                )
                log.warning("IndexTTS-2 unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            model_dir = _model_dir()
            cfg_path = _cfg_path(model_dir)
            if not os.path.exists(cfg_path):
                self._unavailable_reason = (
                    "IndexTTS-2 checkpoints not found. Download "
                    f"{MODEL_ID} to {model_dir!r} or set INDEXTTS2_MODEL_DIR."
                )
                log.warning("IndexTTS-2 unavailable: %s", self._unavailable_reason)
                return

            device = _device(torch)
            log.info("loading %s from %s on %s ...", MODEL_ID, model_dir, device)
            self._model = IndexTTS2(
                cfg_path=cfg_path,
                model_dir=model_dir,
                device=device,
                use_fp16=_env_bool("INDEXTTS2_FP16", False),
                use_cuda_kernel=_env_bool("INDEXTTS2_CUDA_KERNEL", False),
                use_deepspeed=_env_bool("INDEXTTS2_DEEPSPEED", False),
                use_accel=_env_bool("INDEXTTS2_ACCEL", False),
                use_torch_compile=_env_bool("INDEXTTS2_TORCH_COMPILE", False),
            )
            self._model_dir = model_dir
            self._cfg_path = cfg_path
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"IndexTTS-2 does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in _FLOAT_EXTRAS:
            value = extras.get(key)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"IndexTTS-2 {key} must be numeric; got {value!r}")
        for key in _INT_EXTRAS:
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"IndexTTS-2 {key} must be an integer; got {value!r}")
        for key in ("emo_audio_prompt", "emo_text"):
            value = extras.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"IndexTTS-2 {key} must be a string; got {value!r}")
        for key in ("use_emo_text", "use_random"):
            value = extras.get(key)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"IndexTTS-2 {key} must be boolean; got {value!r}")

        if extras.get("emo_alpha") is not None and not 0 <= extras["emo_alpha"] <= 1:
            raise ValueError(f"IndexTTS-2 emo_alpha must be between 0 and 1; got {extras['emo_alpha']!r}")
        for key in ("interval_silence",):
            if extras.get(key) is not None and extras[key] < 0:
                raise ValueError(f"IndexTTS-2 {key} must be >= 0; got {extras[key]!r}")
        for key in ("temperature", "top_p"):
            if extras.get(key) is not None and extras[key] <= 0:
                raise ValueError(f"IndexTTS-2 {key} must be > 0; got {extras[key]!r}")
        for key in ("max_mel_tokens", "max_text_tokens_per_segment", "num_beams", "top_k"):
            if extras.get(key) is not None and extras[key] <= 0:
                raise ValueError(f"IndexTTS-2 {key} must be > 0; got {extras[key]!r}")

        emo_vector = extras.get("emo_vector")
        if emo_vector is not None:
            if (
                isinstance(emo_vector, (str, bytes))
                or not isinstance(emo_vector, Sequence)
                or len(emo_vector) != _EMOTION_VECTOR_LEN
            ):
                raise ValueError(
                    "IndexTTS-2 emo_vector must be a sequence of "
                    f"{_EMOTION_VECTOR_LEN} numeric values"
                )
            for value in emo_vector:
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        "IndexTTS-2 emo_vector must contain numeric values; "
                        f"got {value!r}"
                    )
                if value < 0:
                    raise ValueError(
                        "IndexTTS-2 emo_vector values must be >= 0; "
                        f"got {value!r}"
                    )

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
                raise RuntimeError(f"IndexTTS-2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("IndexTTS2Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"indextts-2 does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        kwargs = {
            "spk_audio_prompt": prepared.ref_audio_path,
            "text": text,
            "output_path": None,
            "verbose": False,
        }
        for key in _ALLOWED_EXTRAS:
            if key in prepared.extras:
                kwargs[key] = prepared.extras[key]

        output = self._model.infer(**kwargs)
        audio, sample_rate = _coerce_infer_output(output)
        if not audio.size:
            raise RuntimeError("IndexTTS-2 produced no output")
        return audio.astype(np.float32, copy=False), sample_rate
