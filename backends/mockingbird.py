"""MockingBird backend via babysor's SV2TTS-derived PyTorch runtime.

MockingBird extends the classic encoder + Tacotron synthesizer + WaveRNN
vocoder architecture with a Chinese-focused training/tooling stack. This
backend never downloads source or checkpoints; it only loads local files.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Mapping

import numpy as np

from .base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

log = logging.getLogger("backends.mockingbird")

MODEL_ID = "babysor/MockingBird"
NATIVE_SR = 22050
DEFAULT_BASE_DIR = Path(__file__).resolve().parent / "extras" / "mockingbird"
DEFAULT_REPO_DIR = DEFAULT_BASE_DIR / "MockingBird"
DEFAULT_MODEL_DIR = DEFAULT_BASE_DIR / "saved_models" / "default"
DEFAULT_ENCODER_PATH = DEFAULT_MODEL_DIR / "encoder.pt"
DEFAULT_SYNTHESIZER_PATH = DEFAULT_MODEL_DIR / "synthesizer.pt"
DEFAULT_VOCODER_PATH = DEFAULT_MODEL_DIR / "vocoder.pt"
SUPPORTED_LANGS = ("zh", "en")

_ALLOWED_EXTRAS = {"vocoder_target", "vocoder_overlap", "vocoder_batched"}
_RUNTIME_MODULES = (
    "encoder",
    "synthesizer",
    "vocoder",
)


def _repo_dir() -> Path:
    return Path(os.environ.get("MOCKINGBIRD_REPO_DIR", DEFAULT_REPO_DIR)).expanduser()


def _encoder_path() -> Path:
    return Path(os.environ.get("MOCKINGBIRD_ENCODER_PATH", DEFAULT_ENCODER_PATH)).expanduser()


def _synthesizer_path() -> Path:
    return Path(os.environ.get("MOCKINGBIRD_SYNTHESIZER_PATH", DEFAULT_SYNTHESIZER_PATH)).expanduser()


def _vocoder_path() -> Path:
    return Path(os.environ.get("MOCKINGBIRD_VOCODER_PATH", DEFAULT_VOCODER_PATH)).expanduser()


def _encoder_device(torch) -> str:
    requested = os.environ.get("MOCKINGBIRD_ENCODER_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _add_repo_to_path(repo_dir: Path) -> None:
    repo = str(repo_dir)
    if repo_dir.is_dir() and repo not in sys.path:
        sys.path.insert(0, repo)


def _module_path(module) -> Path | None:
    file = getattr(module, "__file__", None)
    if not file:
        return None
    return Path(file).resolve()


def _evict_conflicting_runtime_modules(repo_dir: Path) -> None:
    """Avoid reusing SV2TTS modules that share MockingBird's top-level names."""
    resolved_repo = repo_dir.resolve()
    for name in _RUNTIME_MODULES:
        module_names = [key for key in sys.modules if key == name or key.startswith(f"{name}.")]
        for module_name in module_names:
            module = sys.modules.get(module_name)
            module_path = _module_path(module) if module is not None else None
            if module_path is not None and resolved_repo not in module_path.parents:
                sys.modules.pop(module_name, None)


def _to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def _no_progress(*args) -> None:
    return None


class MockingBirdBackend(BackendBase):
    name = "mockingbird"
    display_name = "MockingBird (Chinese-focused SV2TTS, open source)"
    model_id = MODEL_ID
    sample_rate = NATIVE_SR
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = SUPPORTED_LANGS

    def __init__(self):
        super().__init__()
        self._encoder = None
        self._synthesizer = None
        self._vocoder = None
        self._model = None
        self._repo_dir = _repo_dir()
        self._encoder_device = None
        self._unavailable_reason = None

    def load(self) -> None:
        def _do():
            try:
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                import torch
            except ImportError as exc:
                self._unavailable_reason = (
                    "optional dependencies are not installed; install "
                    "requirements-mockingbird.txt"
                )
                log.warning("MockingBird unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            repo_dir = _repo_dir()
            _add_repo_to_path(repo_dir)
            _evict_conflicting_runtime_modules(repo_dir)
            try:
                from encoder import inference as encoder
                from synthesizer.inference import Synthesizer
                from vocoder import inference as vocoder
            except ImportError as exc:
                self._unavailable_reason = (
                    "MockingBird source is not importable. Clone "
                    f"{MODEL_ID} to {repo_dir!r} or set MOCKINGBIRD_REPO_DIR."
                )
                log.warning("MockingBird unavailable: %s (%s)", self._unavailable_reason, exc)
                return

            encoder_path = _encoder_path()
            synthesizer_path = _synthesizer_path()
            vocoder_path = _vocoder_path()
            missing = [
                str(path)
                for path in (encoder_path, synthesizer_path, vocoder_path)
                if not path.exists()
            ]
            if missing:
                self._unavailable_reason = (
                    "MockingBird checkpoint files not found. Provide encoder, "
                    "synthesizer, and vocoder .pt files under "
                    f"{DEFAULT_MODEL_DIR!r}, or set MOCKINGBIRD_*_PATH. Missing: {missing}"
                )
                log.warning("MockingBird unavailable: %s", self._unavailable_reason)
                return

            encoder_device = _encoder_device(torch)
            log.info("loading %s encoder on %s ...", MODEL_ID, encoder_device)
            encoder.load_model(encoder_path, device=encoder_device)
            log.info("loading %s synthesizer from %s ...", MODEL_ID, synthesizer_path)
            synthesizer = Synthesizer(synthesizer_path, verbose=False)
            if hasattr(synthesizer, "load"):
                synthesizer.load()
            log.info("loading %s vocoder from %s ...", MODEL_ID, vocoder_path)
            vocoder.load_model(vocoder_path, verbose=False)

            self._encoder = encoder
            self._synthesizer = synthesizer
            self._vocoder = vocoder
            self._model = (encoder, synthesizer, vocoder)
            self._repo_dir = repo_dir
            self._encoder_device = encoder_device
            self._unavailable_reason = None

        self._ensure_loaded(_do)

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        unknown = set(extras) - _ALLOWED_EXTRAS
        if unknown:
            raise ValueError(
                f"MockingBird does not accept extras: {sorted(unknown)}; "
                f"allowed: {sorted(_ALLOWED_EXTRAS)}"
            )
        for key in ("vocoder_target", "vocoder_overlap"):
            value = extras.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"MockingBird {key} must be an integer; got {value!r}")
            if value is not None and value <= 0:
                raise ValueError(f"MockingBird {key} must be > 0; got {value!r}")
        batched = extras.get("vocoder_batched")
        if batched is not None and not isinstance(batched, bool):
            raise ValueError(f"MockingBird vocoder_batched must be boolean; got {batched!r}")

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        self.validate_extras(extras)
        if self._encoder is None:
            if self._unavailable_reason:
                raise RuntimeError(f"MockingBird is unavailable: {self._unavailable_reason}")
            raise RuntimeError("MockingBirdBackend.prepare_voice called before load()")

        wav = self._encoder.preprocess_wav(ref_audio_path)
        speaker_embedding = self._encoder.embed_utterance(wav)
        prepared_extras = dict(extras)
        prepared_extras["speaker_embedding"] = np.asarray(speaker_embedding, dtype=np.float32)
        ref_text = ref_text.strip() if ref_text and ref_text.strip() else None
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(prepared_extras),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._synthesizer is None or self._vocoder is None:
            if self._unavailable_reason:
                raise RuntimeError(f"MockingBird is unavailable: {self._unavailable_reason}")
            raise RuntimeError("MockingBirdBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"mockingbird does not support lang={lang!r}; supported: {self.supported_langs}"
            )

        speaker_embedding = prepared.extras.get("speaker_embedding")
        if speaker_embedding is None:
            raise RuntimeError("MockingBird prepared voice is missing speaker_embedding")

        specs = self._synthesizer.synthesize_spectrograms(
            [text],
            [np.asarray(speaker_embedding, dtype=np.float32)],
        )
        if not specs:
            raise RuntimeError("MockingBird produced no spectrogram")

        audio = self._vocoder.infer_waveform(
            specs[0],
            batched=bool(prepared.extras.get("vocoder_batched", True)),
            target=int(prepared.extras.get("vocoder_target", 8000)),
            overlap=int(prepared.extras.get("vocoder_overlap", 800)),
            progress_callback=_no_progress,
        )
        audio_np = _to_numpy(audio)
        if audio_np.size == 0:
            raise RuntimeError("MockingBird produced no output")
        return audio_np, self.sample_rate
