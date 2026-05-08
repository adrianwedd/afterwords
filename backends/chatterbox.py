"""Chatterbox TTS backend (multilingual fp16 variant) via mlx-audio."""
from __future__ import annotations

import glob
import logging
import os
import tempfile
from typing import Mapping

import numpy as np
import soundfile as sf

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.chatterbox")

MODEL_ID = "mlx-community/chatterbox-fp16"

# cfg_weight controls how closely output matches the reference voice (higher =
# more similar, less natural). exaggeration controls expressiveness. Defaults
# chosen for good cloning fidelity: 0.7 cfg_weight (up from model default 0.5)
# and 0.5 exaggeration (model default).
_ALLOWED_EXTRAS = {"cfg_weight", "exaggeration"}
_DEFAULT_CFG_WEIGHT = 0.7
_DEFAULT_EXAGGERATION = 0.5


class ChatterboxBackend(BackendBase):
    name = "chatterbox"
    display_name = "Chatterbox (fp16, multilingual)"
    model_id = MODEL_ID
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko")

    def __init__(self):
        super().__init__()
        self._model = None

    def load(self) -> None:
        def _do():
            from mlx_audio.tts import load_model
            log.info("loading %s ...", MODEL_ID)
            self._model = load_model(MODEL_ID)
        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(f"Chatterbox does not accept extras: {sorted(unknown)}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        # Chatterbox accepts 24 kHz; ref_text is optional (used if present).
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(dict(extras)),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("ChatterboxBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"chatterbox does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        from mlx_audio.tts.generate import generate_audio
        with tempfile.TemporaryDirectory() as tmpdir:
            kwargs = dict(
                text=text,
                model=self._model,
                ref_audio=prepared.ref_audio_path,
                lang_code=lang,
                cfg_weight=prepared.extras.get("cfg_weight", _DEFAULT_CFG_WEIGHT),
                exaggeration=prepared.extras.get("exaggeration", _DEFAULT_EXAGGERATION),
                output_path=tmpdir,
                file_prefix="out",
                verbose=False,
            )
            if prepared.ref_text:
                kwargs["ref_text"] = prepared.ref_text
            generate_audio(**kwargs)
            wavs = sorted(glob.glob(os.path.join(tmpdir, "out_*.wav")))
            if not wavs:
                raise RuntimeError("Chatterbox produced no output")
            data, sr = sf.read(wavs[0])
            return np.asarray(data, dtype=np.float32), sr
