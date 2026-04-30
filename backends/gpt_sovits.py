"""GPT-SoVITS backend via RVC-Boss GPT-SoVITS.

GPT-SoVITS upstream code is MIT licensed. The default public weights from
lj1995/GPT-SoVITS are published for the upstream project; verify any
third-party fine-tuned weights before commercial use.
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.gpt_sovits")

MODEL_ID = "lj1995/GPT-SoVITS"
NATIVE_SR = 32000
SUPPORTED_LANGS = ("en", "zh", "ja", "ko", "yue")
DEFAULT_REPO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backends",
    "extras",
    "gpt-sovits",
    "GPT-SoVITS",
)

_ALLOWED_EXTRAS = {
    "prompt_lang",
    "prompt_language",
    "text_language",
    "how_to_cut",
    "top_k",
    "top_p",
    "temperature",
    "speed",
    "sample_steps",
    "pause_second",
}

_INT_EXTRAS = {"top_k", "sample_steps"}
_FLOAT_EXTRAS = {"top_p", "temperature", "speed", "pause_second"}


def _get_tts_wav_import():
    try:
        from GPT_SoVITS.inference import get_tts_wav

        return get_tts_wav
    except ImportError:
        from GPT_SoVITS.inference_webui import get_tts_wav

        return get_tts_wav


def _repo_dir() -> str:
    return os.environ.get("GPT_SOVITS_REPO_DIR", DEFAULT_REPO_DIR)


def _to_numpy(audio) -> np.ndarray:
    if isinstance(audio, tuple) and len(audio) == 2:
        audio = audio[1]
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def _coerce_chunk(chunk) -> tuple[np.ndarray, int | None]:
    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], (int, np.integer)):
        return _to_numpy(chunk[1]), int(chunk[0])
    if isinstance(chunk, Mapping):
        audio = chunk.get("audio", chunk.get("wav", chunk.get("tts_speech")))
        if audio is None:
            raise RuntimeError("GPT-SoVITS produced an invalid output chunk")
        sr = chunk.get("sample_rate", chunk.get("sr"))
        return _to_numpy(audio), int(sr) if sr is not None else None
    return _to_numpy(chunk), None


class GPTSoVITSBackend(BackendBase):
    name = "gpt-sovits"
    display_name = "GPT-SoVITS (MIT)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = SUPPORTED_LANGS

    def __init__(self):
        super().__init__()
        self._get_tts_wav = None
        self._repo_dir = _repo_dir()
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            repo_dir = _repo_dir()
            if os.path.isdir(repo_dir) and repo_dir not in sys.path:
                sys.path.insert(0, repo_dir)
            try:
                self._get_tts_wav = _get_tts_wav_import()
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-gpt-sovits.txt, clone GPT-SoVITS to "
                    f"{repo_dir!r} or set GPT_SOVITS_REPO_DIR, and configure weights"
                )
                log.warning("GPT-SoVITS unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            self._repo_dir = repo_dir
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"GPT-SoVITS does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in ("prompt_lang", "prompt_language", "text_language", "how_to_cut"):
            value = extras.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"GPT-SoVITS {key} must be a string; got {value!r}")
        for key in ("prompt_lang", "prompt_language", "text_language"):
            value = extras.get(key)
            if value is not None and value not in self.supported_langs:
                raise ValueError(
                    f"GPT-SoVITS {key} must be one of {self.supported_langs}; got {value!r}"
                )
        for key in _INT_EXTRAS:
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"GPT-SoVITS {key} must be an integer; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"GPT-SoVITS {key} must be > 0; got {value!r}")
        for key in _FLOAT_EXTRAS:
            value = extras.get(key)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"GPT-SoVITS {key} must be numeric; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"GPT-SoVITS {key} must be > 0; got {value!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        if not ref_text or not ref_text.strip():
            raise ValueError("GPT-SoVITS requires reference_text aligned with reference audio")
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
        if self._get_tts_wav is None:
            if self._unavailable_reason:
                raise RuntimeError(f"GPT-SoVITS is unavailable: {self._unavailable_reason}")
            raise RuntimeError("GPTSoVITSBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"gpt-sovits does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        if not prepared.ref_text:
            raise RuntimeError("GPT-SoVITS prepared voice is missing reference_text")

        prompt_language = str(
            prepared.extras.get("prompt_language", prepared.extras.get("prompt_lang", lang))
        )
        text_language = str(prepared.extras.get("text_language", lang))
        if prompt_language not in self.supported_langs:
            raise ValueError(
                "GPT-SoVITS prompt_language must be one of "
                f"{self.supported_langs}; got {prompt_language!r}"
            )
        if text_language not in self.supported_langs:
            raise ValueError(
                "GPT-SoVITS text_language must be one of "
                f"{self.supported_langs}; got {text_language!r}"
            )

        kwargs = {
            "ref_wav_path": prepared.ref_audio_path,
            "prompt_text": prepared.ref_text,
            "prompt_language": prompt_language,
            "text": text,
            "text_language": text_language,
        }
        for key in (
            "how_to_cut",
            "top_k",
            "top_p",
            "temperature",
            "speed",
            "sample_steps",
            "pause_second",
        ):
            if key in prepared.extras:
                kwargs[key] = prepared.extras[key]

        output = self._get_tts_wav(**kwargs)
        if isinstance(output, Iterator):
            chunks = output
        elif isinstance(output, list):
            chunks = output
        else:
            chunks = (output,)
        audio_chunks = []
        sample_rate = None
        for chunk in chunks:
            audio, chunk_sr = _coerce_chunk(chunk)
            if audio.size:
                audio_chunks.append(audio)
            if chunk_sr is not None:
                sample_rate = chunk_sr

        if not audio_chunks:
            raise RuntimeError("GPT-SoVITS produced no output")
        audio = audio_chunks[0] if len(audio_chunks) == 1 else np.concatenate(audio_chunks)
        return audio.astype(np.float32, copy=False), int(sample_rate or self.sample_rate)
