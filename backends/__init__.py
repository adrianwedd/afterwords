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


def register_all(with_17b: bool = False) -> None:
    """Register shipped backends. Called once at server startup.

    qwen3-0.6b is always registered (primary cloning path; failure is fatal).
    qwen3-1.7b is opt-in via with_17b=True (pass --with-1.7b to server.py).
    Every experimental backend is isolated — import/instantiation failure logs
    an error and skips, leaving the rest of the registry intact.
    """
    import importlib
    import logging
    log = logging.getLogger("backends")

    # qwen3-0.6b — primary path. Fail loud.
    from .qwen3 import Qwen3Backend
    register(Qwen3Backend(size="0.6B"))

    if with_17b:
        register(Qwen3Backend(size="1.7B"))

    # Experimental backends — each isolated.
    _experimental = (
        ("voxtral", "VoxtralBackend"),
        ("openvoice_v2", "OpenVoiceV2Backend"),
        ("f5_tts", "F5TTSBackend"),
        ("cosyvoice2", "CosyVoice2Backend"),
        ("gpt_sovits", "GPTSoVITSBackend"),
        ("xtts_v2", "XTTSv2Backend"),
        ("indextts_2", "IndexTTS2Backend"),
        ("neutts_air", "NeuTTSAirBackend"),
        ("spark_tts", "SparkTTSBackend"),
        ("dia2", "Dia2Backend"),
        ("yourtts", "YourTTSBackend"),
        ("firered_tts_2", "FireRedTTS2Backend"),
        ("sv2tts", "SV2TTSBackend"),
        ("mockingbird", "MockingBirdBackend"),
        ("soprotts", "SoproTTSBackend"),
    )
    for module_name, class_name in _experimental:
        try:
            mod = importlib.import_module(f".{module_name}", package=__package__)
            register(getattr(mod, class_name)())
        except Exception as exc:
            log.error("backend %s failed to register: %s: %s",
                      module_name, type(exc).__name__, exc)


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
