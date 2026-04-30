"""Backend registry. Populated by register_all() at server startup."""
from __future__ import annotations

from .base import Backend, PreparedVoice, RefTextPolicy, _read_only  # noqa: F401

_REGISTRY: dict[str, Backend] = {}
_SLUG_REGISTRY: dict[str, str] = {}


def _slug(name: str) -> str:
    """Filename-safe slug for --all-backends output. Currently: drop dots."""
    return name.replace(".", "")


def register(backend: Backend) -> None:
    if backend.name in _REGISTRY:
        raise ValueError(f"backend {backend.name!r} already registered")
    slug = _slug(backend.name)
    if slug in _SLUG_REGISTRY:
        raise ValueError(
            f"backend slug collision: {slug!r} used by both "
            f"{_SLUG_REGISTRY[slug]!r} and {backend.name!r}"
        )
    _REGISTRY[backend.name] = backend
    _SLUG_REGISTRY[slug] = backend.name


def register_all() -> None:
    """Register every shipped backend. Called once at server startup."""
    # Imports inside function to avoid importing model libs at package import time.
    from .qwen3 import Qwen3Backend
    from .chatterbox import ChatterboxBackend
    from .voxcpm import VoxCPMBackend
    from .voxtral import VoxtralBackend
    from .openvoice_v2 import OpenVoiceV2Backend
    from .f5_tts import F5TTSBackend
    from .cosyvoice2 import CosyVoice2Backend
    from .gpt_sovits import GPTSoVITSBackend

    register(Qwen3Backend(size="0.6B"))
    register(Qwen3Backend(size="1.7B"))
    register(ChatterboxBackend())
    register(VoxCPMBackend())
    register(VoxtralBackend())
    register(OpenVoiceV2Backend())
    register(F5TTSBackend())
    register(CosyVoice2Backend())
    register(GPTSoVITSBackend())


def reset_for_tests() -> None:
    """Clear the registry. For unit tests only — never call in production."""
    _REGISTRY.clear()
    _SLUG_REGISTRY.clear()


def get(name: str) -> Backend:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown backend {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def names() -> list[str]:
    return sorted(_REGISTRY)


def max_sample_rate() -> int:
    if not _REGISTRY:
        return 24000
    return max(b.sample_rate for b in _REGISTRY.values())


def slug(name: str) -> str:
    return _slug(name)
