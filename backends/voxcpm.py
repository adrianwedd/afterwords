"""VoxCPM 1.5 TTS backend via mlx-audio. 44.1 kHz native; resamples refs at prepare."""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from typing import Mapping

import numpy as np
import soundfile as sf

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.voxcpm")

MODEL_ID = "mlx-community/VoxCPM1.5"
NATIVE_SR = 44100
_ALLOWED_EXTRAS = {"cfg_value", "inference_timesteps"}


def _resample_cpu(audio: np.ndarray, in_sr: int, out_sr: int) -> np.ndarray:
    """CPU-only linear resampler. Cheap, no Metal; safe to run without synth lock."""
    if in_sr == out_sr:
        return audio
    duration = audio.shape[0] / in_sr
    n_out = int(round(duration * out_sr))
    t_in = np.linspace(0, duration, audio.shape[0], endpoint=False, dtype=np.float64)
    t_out = np.linspace(0, duration, n_out, endpoint=False, dtype=np.float64)
    if audio.ndim == 1:
        return np.interp(t_out, t_in, audio).astype(np.float32)
    resampled = np.stack(
        [np.interp(t_out, t_in, audio[:, ch]) for ch in range(audio.shape[1])],
        axis=-1,
    )
    return resampled.astype(np.float32)


class VoxCPMBackend(BackendBase):
    name = "voxcpm-1.5"
    display_name = "VoxCPM 1.5"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "zh")

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
            raise ValueError(
                f"VoxCPM does not accept extras: {sorted(unknown)}; allowed: {sorted(_ALLOWED_EXTRAS)}"
            )

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        data, sr = sf.read(ref_audio_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr == NATIVE_SR:
            return PreparedVoice(
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                extras=_read_only(dict(extras)),
            )
        # CPU-only resample; safe outside _synth_lock.
        resampled = _resample_cpu(data.astype(np.float32), sr, NATIVE_SR)
        tmpdir = tempfile.gettempdir()
        out_path = os.path.join(tmpdir, f"voxcpm-ref-{uuid.uuid4().hex}.wav")
        sf.write(out_path, resampled, NATIVE_SR, subtype="PCM_16")
        return PreparedVoice(
            ref_audio_path=out_path,
            ref_text=ref_text,
            extras=_read_only(dict(extras)),
            owns_temp_audio=True,
            cleanup_paths=(out_path,),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("VoxCPMBackend.synthesize called before load()")
        # mlx-audio's VoxCPM backend: forward relevant extras.
        kwargs = dict(
            text=text,
            reference_wav_path=prepared.ref_audio_path,
        )
        if prepared.ref_text:
            kwargs["prompt_text"] = prepared.ref_text
        for k in ("cfg_value", "inference_timesteps"):
            if k in prepared.extras:
                kwargs[k] = prepared.extras[k]
        audio = self._model.generate(**kwargs)
        if hasattr(audio, "tolist"):
            audio = np.asarray(audio.tolist(), dtype=np.float32)
        else:
            audio = np.asarray(audio, dtype=np.float32)
        return audio.reshape(-1), NATIVE_SR
