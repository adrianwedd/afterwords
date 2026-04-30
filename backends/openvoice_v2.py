"""OpenVoice v2 backend via MyShell OpenVoice + MeloTTS."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.openvoice_v2")

MODEL_ID = "myshell-ai/OpenVoiceV2"
NATIVE_SR = 22050
DEFAULT_CHECKPOINT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backends",
    "extras",
    "openvoice-v2",
    "checkpoints_v2",
)

_LANG_CONFIG = {
    "en": ("EN_NEWEST", "en-newest"),
    "es": ("ES", "es"),
    "fr": ("FR", "fr"),
    "zh": ("ZH", "zh"),
    "ja": ("JP", "jp"),
    "ko": ("KR", "kr"),
}

_ALLOWED_EXTRAS = {"speaker", "speed", "tau", "vad"}


def _checkpoint_dir() -> str:
    return os.environ.get("OPENVOICE_V2_CHECKPOINT_DIR", DEFAULT_CHECKPOINT_DIR)


def _device(torch) -> str:
    requested = os.environ.get("OPENVOICE_DEVICE")
    if requested:
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda:0"
    return "cpu"


def _speaker_slug(speaker_key: str) -> str:
    return speaker_key.lower().replace("_", "-")


class OpenVoiceV2Backend(BackendBase):
    name = "openvoice-v2"
    display_name = "OpenVoice v2"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = tuple(_LANG_CONFIG)

    def __init__(self):
        super().__init__()
        self._torch = None
        self._TTS = None
        self._se_extractor = None
        self._tone_color_converter = None
        self._tts_models: dict[str, object] = {}
        self._checkpoint_dir = _checkpoint_dir()
        self._device = None
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                import torch
                from melo.api import TTS
                from openvoice import se_extractor
                from openvoice.api import ToneColorConverter
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; "
                    "install requirements-openvoice.txt"
                )
                log.warning("OpenVoice v2 unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            checkpoint_dir = _checkpoint_dir()
            converter_dir = os.path.join(checkpoint_dir, "converter")
            config_path = os.path.join(converter_dir, "config.json")
            ckpt_path = os.path.join(converter_dir, "checkpoint.pth")
            if not os.path.exists(config_path) or not os.path.exists(ckpt_path):
                self._unavailable_reason = (
                    "OpenVoice v2 checkpoints not found. Download "
                    f"{MODEL_ID} to {checkpoint_dir!r} or set "
                    "OPENVOICE_V2_CHECKPOINT_DIR."
                )
                log.warning("OpenVoice v2 unavailable: %s", self._unavailable_reason)
                return

            device = _device(torch)
            log.info(
                "loading %s converter from %s on %s ...",
                MODEL_ID,
                checkpoint_dir,
                device,
            )
            converter = ToneColorConverter(config_path, device=device)
            converter.load_ckpt(ckpt_path)

            self._torch = torch
            self._TTS = TTS
            self._se_extractor = se_extractor
            self._tone_color_converter = converter
            self._checkpoint_dir = checkpoint_dir
            self._device = device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"OpenVoice v2 does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        speaker = extras.get("speaker")
        if speaker is not None:
            valid = tuple(sorted({default for _, default in _LANG_CONFIG.values()} | {
                "en-au", "en-br", "en-default", "en-india", "en-us"
            }))
            if speaker not in valid:
                raise ValueError(f"OpenVoice v2 speaker must be one of {valid}; got {speaker!r}")
        for key in ("speed", "tau"):
            value = extras.get(key)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"OpenVoice v2 {key} must be numeric; got {value!r}")
        speed = extras.get("speed")
        if speed is not None and speed <= 0:
            raise ValueError(f"OpenVoice v2 speed must be > 0; got {speed!r}")
        vad = extras.get("vad")
        if vad is not None and not isinstance(vad, bool):
            raise ValueError(f"OpenVoice v2 vad must be boolean; got {vad!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        if self._tone_color_converter is None or self._se_extractor is None:
            if self._unavailable_reason:
                raise RuntimeError(f"OpenVoice v2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("OpenVoiceV2Backend.prepare_voice called before load()")

        target_dir = tempfile.mkdtemp(prefix="openvoice-v2-se-")
        try:
            target_se, _audio_name = self._se_extractor.get_se(
                ref_audio_path,
                self._tone_color_converter,
                target_dir=target_dir,
                vad=bool(extras.get("vad", True)),
            )
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)
        prepared_extras = dict(extras)
        prepared_extras["target_se"] = target_se
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(prepared_extras),
        )

    def _tts_for(self, openvoice_lang: str):
        if openvoice_lang not in self._tts_models:
            self._tts_models[openvoice_lang] = self._TTS(
                language=openvoice_lang,
                device=self._device,
            )
        return self._tts_models[openvoice_lang]

    def _speaker_id(self, model, speaker_slug: str):
        speaker_ids = model.hps.data.spk2id
        for key, value in speaker_ids.items():
            if _speaker_slug(key) == speaker_slug:
                return value
        if len(speaker_ids) == 1:
            return next(iter(speaker_ids.values()))
        raise ValueError(
            f"OpenVoice v2 MeloTTS model has no speaker {speaker_slug!r}; "
            f"available: {tuple(speaker_ids)}"
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._tone_color_converter is None:
            if self._unavailable_reason:
                raise RuntimeError(f"OpenVoice v2 is unavailable: {self._unavailable_reason}")
            raise RuntimeError("OpenVoiceV2Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"openvoice-v2 does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        openvoice_lang, default_speaker = _LANG_CONFIG[lang]
        speaker_slug = str(prepared.extras.get("speaker", default_speaker))
        source_se_path = os.path.join(
            self._checkpoint_dir,
            "base_speakers",
            "ses",
            f"{speaker_slug}.pth",
        )
        if not os.path.exists(source_se_path):
            raise RuntimeError(f"OpenVoice v2 source speaker embedding not found: {source_se_path}")

        target_se = prepared.extras.get("target_se")
        if target_se is None:
            raise RuntimeError("OpenVoice v2 prepared voice is missing target speaker embedding")

        model = self._tts_for(openvoice_lang)
        speaker_id = self._speaker_id(model, speaker_slug)
        source_se = self._torch.load(source_se_path, map_location=self._device)
        speed = float(prepared.extras.get("speed", 1.0))
        tau = float(prepared.extras.get("tau", 0.3))

        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = os.path.join(tmpdir, "base.wav")
            model.tts_to_file(text, speaker_id, src_path, speed=speed)
            audio = self._tone_color_converter.convert(
                audio_src_path=src_path,
                src_se=source_se,
                tgt_se=target_se,
                output_path=None,
                tau=tau,
                message="@Afterwords",
            )

        if audio is None:
            raise RuntimeError("OpenVoice v2 produced no output")
        return np.asarray(audio, dtype=np.float32).reshape(-1), NATIVE_SR
