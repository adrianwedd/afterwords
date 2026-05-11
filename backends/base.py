"""Backend protocol shared by all cloning TTS backends."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

import numpy as np


class RefTextPolicy(Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    IGNORED = "ignored"


def _read_only(d: Mapping[str, object] | dict | None) -> Mapping[str, object]:
    """Return a read-only view of a mapping. Used by PreparedVoice / VoiceProfile."""
    return MappingProxyType(dict(d or {}))


@dataclass(frozen=True)
class PreparedVoice:
    ref_audio_path: str
    ref_text: str | None
    extras: Mapping[str, object]
    owns_temp_audio: bool = False
    cleanup_paths: tuple[str, ...] = ()
    # Backends may store pre-loaded in-memory data (e.g. a pre-converted mx.array)
    # to avoid re-reading ref_audio_path at synthesize() time, eliminating the TOCTOU
    # window with DELETE /session which removes the backing file.
    data: object = None

    def __post_init__(self):
        # Enforce immutability contract — backends may pass dict, we wrap here.
        if not isinstance(self.extras, MappingProxyType):
            object.__setattr__(self, "extras", _read_only(self.extras))


@runtime_checkable
class Backend(Protocol):
    name: str
    display_name: str
    sample_rate: int
    ref_text_policy: RefTextPolicy
    supported_langs: tuple[str, ...]

    def load(self) -> None: ...
    def validate_extras(self, extras: Mapping[str, object]) -> None: ...
    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice: ...
    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]: ...


class BackendBase:
    """Optional convenience base — backends can subclass for a threadsafe load()."""

    _load_lock: threading.Lock
    _loaded: bool

    def __init__(self):
        self._load_lock = threading.Lock()
        self._loaded = False

    def _ensure_loaded(self, do_load):
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            do_load()
            self._loaded = True
