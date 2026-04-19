"""Qwen3-TTS backend via mlx-audio. Handles 0.6B and 1.7B variants."""
from __future__ import annotations

import glob
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import soundfile as sf

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.qwen3")

_MODEL_IDS = {
    "0.6B": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
    "1.7B": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
}


class Qwen3Backend(BackendBase):
    display_name_template = "Qwen3-TTS {size}"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.REQUIRED  # our cloning path always uses ref_text
    supported_langs = ("en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru")

    def __init__(self, size: str):
        super().__init__()
        if size not in _MODEL_IDS:
            raise ValueError(f"Qwen3 size must be one of {list(_MODEL_IDS)}")
        self.size = size
        self.name = f"qwen3-{size.lower()}"
        self.display_name = self.display_name_template.format(size=size)
        self.model_id = _MODEL_IDS[size]
        self._model = None

    def load(self) -> None:
        def _do():
            from mlx_audio.tts import load_model
            log.info("loading %s ...", self.model_id)
            self._model = load_model(self.model_id)
        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        # Qwen3 has no per-voice extras we consume today.
        unknown = set(extras) - set()
        if unknown:
            raise ValueError(f"Qwen3 does not accept extras: {sorted(unknown)}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        if not ref_text:
            raise ValueError("Qwen3 REQUIRES ref_text for cloning")
        # Qwen3 accepts 24 kHz refs natively — no resample needed.
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only({}),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("Qwen3Backend.synthesize called before load()")
        from mlx_audio.tts.generate import generate_audio
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_audio(
                text=text,
                model=self._model,
                ref_audio=prepared.ref_audio_path,
                ref_text=prepared.ref_text,
                lang_code="en",
                output_path=tmpdir,
                file_prefix="out",
                verbose=False,
            )
            wavs = sorted(glob.glob(os.path.join(tmpdir, "out_*.wav")))
            if not wavs:
                raise RuntimeError("Qwen3 produced no output")
            data, sr = sf.read(wavs[0])
            return np.asarray(data, dtype=np.float32), sr
