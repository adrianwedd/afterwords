"""Qwen3-TTS backend via mlx-audio. Handles 0.6B and 1.7B variants."""
from __future__ import annotations

import glob
import logging
import os
import tempfile
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
        self._unavailable_reason: str | None = None

    def load(self) -> None:
        def _do():
            try:
                from mlx_audio.tts import load_model
            except ImportError as exc:
                # Primary cloning path — log at ERROR (not WARNING) so operators
                # see this clearly in `afterwords logs`. The most common cause is a
                # broken venv after a brew Python minor-version bump; see CLAUDE.md.
                self._unavailable_reason = (
                    f"mlx-audio not importable ({exc}); "
                    "if Python was upgraded recently, run `bash setup.sh --server-only` "
                    "to rebuild the venv"
                )
                log.error("Qwen3 %s unavailable: %s", self.size, self._unavailable_reason)
                return
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
        # Read ref bytes now so synthesize() never re-reads from disk. Closes the
        # DELETE /session ↔ in-flight synth TOCTOU race (same pattern as Chatterbox).
        with open(ref_audio_path, "rb") as fh:
            ref_bytes = fh.read()
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only({}),
            data=ref_bytes,
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            if self._unavailable_reason:
                raise RuntimeError(f"Qwen3 {self.size} is unavailable: {self._unavailable_reason}")
            raise RuntimeError("Qwen3Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"qwen3 does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        from mlx_audio.tts.generate import generate_audio
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use buffered bytes from prepare_voice() to avoid reading the original
            # file at synthesis time (guards against DELETE /session TOCTOU race).
            if prepared.data is not None:
                ref_path = os.path.join(tmpdir, "ref.wav")
                with open(ref_path, "wb") as fh:
                    fh.write(prepared.data)
            else:
                ref_path = prepared.ref_audio_path
            generate_audio(
                text=text,
                model=self._model,
                ref_audio=ref_path,
                ref_text=prepared.ref_text,
                lang_code=lang,
                output_path=tmpdir,
                file_prefix="out",
                verbose=False,
            )
            wavs = sorted(glob.glob(os.path.join(tmpdir, "out_*.wav")))
            if not wavs:
                raise RuntimeError("Qwen3 produced no output")
            # Long inputs are split by generate_audio into out_0000.wav,
            # out_0001.wav, …; concatenate so the caller gets full audio.
            arrays = []
            sr = None
            for w in wavs:
                d, s = sf.read(w)
                if sr is None:
                    sr = s
                elif s != sr:
                    raise RuntimeError(
                        f"Qwen3 produced mismatched sample rates: {sr} vs {s}"
                    )
                arrays.append(d)
            if len(arrays) > 1:
                log.info("qwen3: concatenated %d segments", len(arrays))
            data = arrays[0] if len(arrays) == 1 else np.concatenate(arrays)
            return np.asarray(data, dtype=np.float32), sr
