# Multi-Backend Cloning TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the single-backend TTS server into a Backend protocol + registry supporting four MLX-native cloning backends (Qwen3 0.6B/1.7B, Chatterbox, VoxCPM 1.5), so adding the next model is one new file.

**Architecture:** A `backends/` package exposes a `Backend` Protocol and an explicit `register_all()` registry. Each voice profile pins to a backend via a new `backend` JSON field (absent = `qwen3-0.6b` for back-compat). `server.py` preloads all four backends at boot, stores voices as `VoiceProfile` dataclasses carrying a cached `PreparedVoice`, and dispatches synthesis through the registry. The global `_synth_lock` stays (MLX Metal is single-GPU). HTTP shapes are preserved; `/health` adds a `loaded_backends` block.

**Tech Stack:** Python 3.11+, FastAPI, MLX via `mlx-audio`, soundfile, noisereduce, faster-whisper, pytest, Bash.

**Spec:** `docs/superpowers/specs/2026-04-19-multi-backend-tts-design.md`

## File Structure

Files created or modified during this plan:

```
backends/                           ← NEW package
├── __init__.py                     (registry: register_all, get, names, max_sample_rate, _slug)
├── __main__.py                     (CLI: list | max-sample-rate | slug <name>)
├── base.py                         (Backend Protocol, RefTextPolicy, PreparedVoice)
├── qwen3.py                        (Qwen3Backend — handles 0.6B and 1.7B via size param)
├── chatterbox.py                   (ChatterboxBackend — chatterbox-fp16 multilingual)
└── voxcpm.py                       (VoxCPMBackend — 44.1 kHz)

server.py                           ← HEAVILY modified (VoiceProfile, startup, dispatch, clone, health)
clone-voice.sh                      ← modified (--backend, --all-backends)
afterwords.sh                       ← modified (voices/status display)
voices/{picard,galadriel,attenborough}*.json  ← regenerated via --all-backends (manual step)
CLAUDE.md                           ← update memory/constraint notes

tests/
├── test_backends.py                ← NEW (protocol shape, registry, no model load)
├── test_voice_profiles.py          ← NEW (schema, default backend, ref_text policy)
├── test_backends_integration.py    ← NEW, @pytest.mark.integration (opt-in model load)
└── test_server.py                  ← extended (loaded_backends, 400 unknown voice, etc.)

docs/index.html                     ← Backend comparison section for demo site
```

---

### Task 1: Scaffold `backends/` package — base protocol, registry, CLI

**Files:**
- Create: `backends/base.py`
- Create: `backends/__init__.py`
- Create: `backends/__main__.py`

- [ ] **Step 1: Create `backends/base.py`**

```python
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
```

- [ ] **Step 2: Create `backends/__init__.py` — registry**

```python
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

    register(Qwen3Backend(size="0.6B"))
    register(Qwen3Backend(size="1.7B"))
    register(ChatterboxBackend())
    register(VoxCPMBackend())


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
```

- [ ] **Step 3: Create `backends/__main__.py` — CLI for clone-voice.sh**

```python
"""CLI used by clone-voice.sh to query registry state from Bash."""
from __future__ import annotations

import sys

from . import max_sample_rate, names, register_all, slug


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m backends <list|max-sample-rate|slug NAME>", file=sys.stderr)
        return 2

    register_all()
    cmd = argv[1]

    if cmd == "list":
        for n in names():
            print(n)
        return 0
    if cmd == "max-sample-rate":
        print(max_sample_rate())
        return 0
    if cmd == "slug":
        if len(argv) < 3:
            print("usage: python -m backends slug NAME", file=sys.stderr)
            return 2
        print(slug(argv[2]))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Commit**

```bash
git add backends/
git commit -m "feat(backends): scaffold Backend protocol + registry + CLI"
```

---

### Task 2: Implement `Qwen3Backend` (handles 0.6B and 1.7B)

**Files:**
- Create: `backends/qwen3.py`
- Test: `tests/test_backends.py` (will be created in Task 14; placeholder assert now)

- [ ] **Step 1: Create `backends/qwen3.py`**

```python
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
```

- [ ] **Step 2: Smoke test — import should work without loading the model**

Run: `python -c "from backends.qwen3 import Qwen3Backend; b = Qwen3Backend('0.6B'); print(b.name, b.sample_rate, b.ref_text_policy)"`
Expected output: `qwen3-0.6b 24000 RefTextPolicy.REQUIRED`

- [ ] **Step 3: Commit**

```bash
git add backends/qwen3.py
git commit -m "feat(backends): implement Qwen3Backend for 0.6B and 1.7B"
```

---

### Task 3: Implement `ChatterboxBackend`

**Files:**
- Create: `backends/chatterbox.py`

- [ ] **Step 1: Create `backends/chatterbox.py`**

```python
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


class ChatterboxBackend(BackendBase):
    name = "chatterbox"
    display_name = "Chatterbox (fp16, multilingual)"
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
        unknown = set(extras) - set()
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
            extras=_read_only({}),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("ChatterboxBackend.synthesize called before load()")
        from mlx_audio.tts.generate import generate_audio
        with tempfile.TemporaryDirectory() as tmpdir:
            kwargs = dict(
                text=text,
                model=self._model,
                ref_audio=prepared.ref_audio_path,
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
```

- [ ] **Step 2: Smoke test**

Run: `python -c "from backends.chatterbox import ChatterboxBackend; b = ChatterboxBackend(); print(b.name, b.sample_rate, b.ref_text_policy)"`
Expected: `chatterbox 24000 RefTextPolicy.OPTIONAL`

- [ ] **Step 3: Commit**

```bash
git add backends/chatterbox.py
git commit -m "feat(backends): implement ChatterboxBackend (fp16 multilingual)"
```

---

### Task 4: Implement `VoxCPMBackend` (44.1 kHz, resamples references)

**Files:**
- Create: `backends/voxcpm.py`

- [ ] **Step 1: Create `backends/voxcpm.py`**

```python
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
_ALLOWED_EXTRAS = {"cfg_value", "inference_timesteps", "style_prompt"}


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
```

- [ ] **Step 2: Smoke test**

Run: `python -c "from backends.voxcpm import VoxCPMBackend; b = VoxCPMBackend(); print(b.name, b.sample_rate, b.ref_text_policy)"`
Expected: `voxcpm-1.5 44100 RefTextPolicy.OPTIONAL`

- [ ] **Step 3: Verify the registry wires up**

Run: `python -m backends list`
Expected:
```
chatterbox
qwen3-0.6b
qwen3-1.7b
voxcpm-1.5
```

Run: `python -m backends max-sample-rate`
Expected: `44100`

Run: `python -m backends slug voxcpm-1.5`
Expected: `voxcpm-15`

- [ ] **Step 4: Commit**

```bash
git add backends/voxcpm.py
git commit -m "feat(backends): implement VoxCPMBackend with 44.1 kHz resample"
```

---

### Task 5: Add `VoiceProfile` dataclass + rewrite profile loader

**Files:**
- Modify: `server.py:22-63` (imports + voice loading)
- Modify: `server.py:50` (VOICES type)

- [ ] **Step 1: Add imports and `VoiceProfile` dataclass near top of server.py, just below existing imports (after line 26)**

```python
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

import backends
from backends.base import PreparedVoice, RefTextPolicy, _read_only


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    backend: str
    ref_audio: str
    ref_text: str | None
    session_id: str | None
    emotion: str
    quality: str | None
    duration_s: float | None
    confidence: float | None
    sequence: int | None
    extras: Mapping[str, object]
    prepared: PreparedVoice

    def __post_init__(self):
        if not isinstance(self.extras, MappingProxyType):
            object.__setattr__(self, "extras", _read_only(self.extras))
```

- [ ] **Step 2: Change `VOICES` type annotation at `server.py:50`**

Replace:
```python
VOICES: dict[str, tuple[str, str]] = {}
```

With:
```python
VOICES: dict[str, VoiceProfile] = {}
```

- [ ] **Step 3: Replace the voice auto-discovery loop at `server.py:52-63` with backend-aware loader**

Replace the block:
```python
for _profile in glob.glob(os.path.join(_VOICES_DIR, "*.json")):
    try:
        with open(_profile) as _f:
            _p = json.load(_f)
        _name = os.path.splitext(os.path.basename(_profile))[0]
        if _name.endswith("-profile"):
            _name = _name[:-8]
        _ref = os.path.join(_VOICES_DIR, f"{_name}-ref.wav")
        if os.path.exists(_ref) and _p.get("reference_text"):
            VOICES[_name] = (_ref, _p["reference_text"])
    except Exception:
        pass
```

With:
```python
def _load_voice_profiles() -> None:
    """Walk voices/*.json and populate VOICES. Called after backends are loaded."""
    for profile_path in glob.glob(os.path.join(_VOICES_DIR, "*.json")):
        try:
            with open(profile_path) as f:
                p = json.load(f)
        except Exception as exc:
            log.warning("voice profile unreadable: %s: %s", profile_path, exc)
            continue

        stem = os.path.splitext(os.path.basename(profile_path))[0]
        if stem.endswith("-profile"):
            stem = stem[:-8]
        name = p.get("name") or stem
        backend_name = p.get("backend", "qwen3-0.6b")

        try:
            backend = backends.get(backend_name)
        except KeyError:
            log.warning(
                "voice %r references unregistered backend %r — skipping",
                name, backend_name,
            )
            continue

        ref_rel = p.get("reference_audio", f"{stem}-ref.wav")
        ref_audio = os.path.join(_VOICES_DIR, ref_rel)
        if not os.path.exists(ref_audio):
            log.warning("voice %r missing ref audio %s — skipping", name, ref_audio)
            continue

        ref_text = p.get("reference_text") or None
        if backend.ref_text_policy == RefTextPolicy.REQUIRED and not ref_text:
            log.warning(
                "voice %r: backend %r REQUIRES ref_text but profile has none — skipping",
                name, backend_name,
            )
            continue

        extras = p.get("synthesis_extras", {}) or {}
        try:
            backend.validate_extras(extras)
        except ValueError as exc:
            log.warning("voice %r: invalid extras: %s — skipping", name, exc)
            continue

        try:
            prepared = backend.prepare_voice(ref_audio, ref_text, extras)
        except Exception as exc:
            log.warning("voice %r: prepare_voice failed: %s — skipping", name, exc)
            continue

        VOICES[name] = VoiceProfile(
            name=name,
            backend=backend_name,
            ref_audio=ref_audio,
            ref_text=ref_text,
            session_id=p.get("session_id"),
            emotion=p.get("emotion", "neutral"),
            quality=p.get("quality"),
            duration_s=p.get("duration_s"),
            confidence=p.get("transcript_confidence"),
            sequence=p.get("sequence"),
            extras=_read_only(extras),
            prepared=prepared,
        )
```

Note: this function is **defined** here but called from `main()` in Task 8 — not at module import time.

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "refactor(server): add VoiceProfile dataclass + backend-aware profile loader"
```

---

### Task 6: Rewrite `_resolve_voice` to return `VoiceProfile`

**Files:**
- Modify: `server.py:130-165`

- [ ] **Step 1: Replace `_resolve_voice` at `server.py:130-165` with VoiceProfile-returning version**

Replace the whole function body with:

```python
def _resolve_voice(voice: str, emotion: str | None = None) -> VoiceProfile | None:
    """Return VoiceProfile for a voice name, honouring session palettes + emotion fallback."""
    # Exact match first
    if voice in VOICES:
        profile = VOICES[voice]
        if emotion is None or profile.emotion == emotion:
            return profile

    # Session palette lookup — match by VoiceProfile.session_id field
    if emotion:
        candidates = [
            p for p in VOICES.values()
            if p.session_id == voice and p.emotion == emotion
        ]
        if candidates:
            return max(
                candidates,
                key=lambda p: (p.duration_s or 0, p.confidence or 0),
            )
        session_entries = [p for p in VOICES.values() if p.session_id == voice]
        if session_entries:
            return max(
                session_entries,
                key=lambda p: (p.duration_s or 0, p.confidence or 0),
            )

    return VOICES.get(voice)
```

**Semantic note for reviewers:** the old implementation used `k.startswith(f"{session_id}-")` (prefix match on the dict key). The new version uses `p.session_id == voice` (equality on the JSON field). Runtime-cloned voices already set `session_id` explicitly via `_register_voice`, so behaviour is equivalent for cloned voices. Static voice profiles that lack a `session_id` JSON field will not participate in palette lookup — this is the intended cleanup.

- [ ] **Step 2: Commit**

```bash
git add server.py
git commit -m "refactor(server): _resolve_voice returns VoiceProfile, uses session_id field"
```

---

### Task 7: Rewrite `_synthesize_audio` to dispatch through registry

**Files:**
- Modify: `server.py:210-261` (`_synthesize_audio`)
- Modify: `server.py:264-284` (GET /synthesize) — pass `VoiceProfile`
- Modify: `server.py:293-311` (POST /synthesize) — pass `VoiceProfile`

- [ ] **Step 1: Replace `_synthesize_audio` at `server.py:210-261` with:**

```python
def _synthesize_audio(text: str, profile: VoiceProfile) -> Response:
    """Core synthesis — dispatches to the voice's pinned backend."""
    log.info("synthesize: %d chars, voice=%s, backend=%s",
             len(text), profile.name, profile.backend)
    try:
        backend = backends.get(profile.backend)
    except KeyError:
        log.error("voice %r references unknown backend %r at dispatch time",
                  profile.name, profile.backend)
        return JSONResponse(
            {"error": f"backend not loaded: {profile.backend}"},
            status_code=500,
        )

    t0 = time.time()
    try:
        with _synth_lock:
            data, sr = backend.synthesize(text, profile.prepared)
    except Exception as exc:
        log.error("synthesis failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "synthesis failed"}, status_code=500)

    elapsed = time.time() - t0
    duration = len(data) / sr if sr else 0

    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    log.info(
        "done: %.1fs audio in %.1fs (RTF=%.2fx)",
        duration, elapsed, elapsed / duration if duration > 0 else 0,
    )
    return Response(
        content=buf.read(),
        media_type="audio/wav",
        headers={
            "X-Synthesis-Time": f"{elapsed:.3f}",
            "X-Duration": f"{duration:.3f}",
            "X-Sample-Rate": str(sr),
            "X-Backend": profile.backend,
        },
    )
```

- [ ] **Step 2: Update `GET /synthesize` at `server.py:264-284` — change the resolve call site**

Find:
```python
resolved = _resolve_voice(voice)
if resolved is None:
    return JSONResponse(
        {"error": f"unknown voice: {voice}", "available": sorted(VOICES.keys())},
        status_code=400)

return _synthesize_audio(text, resolved, voice)
```

Replace with:
```python
profile = _resolve_voice(voice)
if profile is None:
    return JSONResponse(
        {"error": f"unknown voice: {voice}", "available": sorted(VOICES.keys())},
        status_code=400)

return _synthesize_audio(text, profile)
```

- [ ] **Step 3: Update `POST /synthesize` at `server.py:293-311` identically**

Find:
```python
resolved = _resolve_voice(body.voice, emotion=body.emotion)
if resolved is None:
    return JSONResponse(
        {"error": f"unknown voice: {body.voice}", "available": sorted(VOICES.keys())},
        status_code=400)

return _synthesize_audio(body.text, resolved, body.voice)
```

Replace with:
```python
profile = _resolve_voice(body.voice, emotion=body.emotion)
if profile is None:
    return JSONResponse(
        {"error": f"unknown voice: {body.voice}", "available": sorted(VOICES.keys())},
        status_code=400)

return _synthesize_audio(body.text, profile)
```

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "refactor(server): dispatch synthesis through Backend registry"
```

---

### Task 8: Rewrite `main()` startup sequence — register, load all, load voices, warmup

**Files:**
- Modify: `server.py:113-127` (delete `_get_model`)
- Modify: `server.py:168-194` (`_warmup` — adjust for new dispatch)
- Modify: `server.py:458-502` (`main()`)

- [ ] **Step 1: Delete `_get_model` at `server.py:113-127`** — per-backend loading is owned by Backend instances. The function block can be removed entirely.

- [ ] **Step 2: Replace `_warmup` at `server.py:168-194` with:**

```python
def _warmup():
    """Prime MLX caches by generating a tiny synth against the default voice."""
    profile = VOICES.get(DEFAULT_VOICE)
    if profile is None:
        log.warning("default voice '%s' not loaded — skipping warmup", DEFAULT_VOICE)
        return
    backend = backends.get(profile.backend)
    log.info("warming up with %s (backend=%s)...", DEFAULT_VOICE, profile.backend)
    t0 = time.time()
    try:
        with _synth_lock:
            backend.synthesize("Hello.", profile.prepared)
        log.info("warmup done in %.1fs", time.time() - t0)
    except Exception as exc:
        log.warning("warmup failed (non-fatal): %s", exc)
```

- [ ] **Step 3: Rewrite the startup block in `main()` at `server.py:458-502`**

Find the block that currently reads:
```python
missing = [v for v, (p, _) in VOICES.items() if not os.path.exists(p)]
for vname in missing:
    log.warning("Reference audio not found for '%s' — skipping", vname)
    del VOICES[vname]
if not VOICES:
    log.error("No voices available — add ref WAVs to voices/")
    raise SystemExit(1)
if DEFAULT_VOICE not in VOICES:
    DEFAULT_VOICE = next(iter(VOICES))
    log.warning("Default voice pruned — using '%s'", DEFAULT_VOICE)

log.info("afterwords starting on %s:%d", args.host, args.port)
log.info("model: %s", MODEL_ID)
log.info("voices: %d loaded (default: %s)", len(VOICES), DEFAULT_VOICE)

if not args.no_warmup:
    try:
        _warmup()
    except Exception as exc:
        log.error("Failed to load model: %s", exc)
        log.error("Check your network connection — first run downloads ~1.5 GB")
        raise SystemExit(1)
_ready.set()
```

Replace with:
```python
# 1. Register all backends.
backends.register_all()
log.info("registered backends: %s", backends.names())

# 2. Load all backend weights (unconditional preload, per design D6).
#    Sequential + logged — takes 60-180s cold; operator visibility matters.
import time as _time
for bname in backends.names():
    b = backends.get(bname)
    t0 = _time.time()
    log.info("loading backend %s (%s)...", bname, b.display_name)
    try:
        b.load()
    except Exception as exc:
        log.error("backend %s failed to load: %s", bname, exc, exc_info=True)
        raise SystemExit(1)
    log.info("backend %s loaded in %.1fs", bname, _time.time() - t0)

# 3. Walk voices/*.json — profile loader calls prepare_voice() (can need loaded weights).
_load_voice_profiles()

# 4. Prune voices whose ref audio vanished between load attempts (defensive).
missing = [v for v, p in VOICES.items() if not os.path.exists(p.ref_audio)]
for vname in missing:
    log.warning("Reference audio not found for '%s' — skipping", vname)
    del VOICES[vname]
if not VOICES:
    log.error("No voices available — add ref WAVs to voices/")
    raise SystemExit(1)
if DEFAULT_VOICE not in VOICES:
    DEFAULT_VOICE = next(iter(VOICES))
    log.warning("Default voice pruned — using '%s'", DEFAULT_VOICE)

log.info("afterwords starting on %s:%d", args.host, args.port)
log.info("voices: %d loaded (default: %s)", len(VOICES), DEFAULT_VOICE)

# 5. Warmup (skippable via --no-warmup; does NOT skip backend loads — those are mandatory per D6).
if not args.no_warmup:
    try:
        _warmup()
    except Exception as exc:
        log.warning("warmup encountered an error: %s", exc)
_ready.set()
```

Note: `--no-warmup` still exists and still skips the warmup synth, but no longer skips backend loading. This preserves D6's "always loaded post-startup" guarantee.

- [ ] **Step 4: Smoke test — start the server**

Run: `python server.py --no-warmup` (in a separate terminal)
Expected in logs:
- `registered backends: ['chatterbox', 'qwen3-0.6b', 'qwen3-1.7b', 'voxcpm-1.5']`
- one `loading backend ...` line per backend
- one `backend X loaded in Ys` line per backend
- `voices: N loaded (default: galadriel)`

Run: `curl localhost:7860/health | jq .default_voice` (while server is up)
Expected: `"galadriel"`

Stop server (Ctrl-C).

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "refactor(server): startup preloads all backends then loads voices"
```

---

### Task 9: Add `loaded_backends` to `/health`

**Files:**
- Modify: `server.py:197-207`

- [ ] **Step 1: Replace the `/health` handler at `server.py:197-207` with:**

```python
@app.get("/health")
def health():
    # Compute voice counts per backend for observability.
    counts: dict[str, int] = {}
    for profile in VOICES.values():
        counts[profile.backend] = counts.get(profile.backend, 0) + 1

    loaded_backends = {}
    for bname in backends.names():
        b = backends.get(bname)
        loaded_backends[bname] = {
            "loaded": True,  # post-startup, all registered backends are loaded (D6)
            "voice_count": counts.get(bname, 0),
            "sample_rate": b.sample_rate,
            "display_name": b.display_name,
        }

    # Default backend's model id — preserves legacy `model` field semantics.
    default_profile = VOICES.get(DEFAULT_VOICE)
    default_backend_name = default_profile.backend if default_profile else "qwen3-0.6b"
    try:
        default_model_id = getattr(
            backends.get(default_backend_name), "model_id", default_backend_name
        )
    except KeyError:
        default_model_id = default_backend_name

    return {
        "status": "ok",
        "model": default_model_id,   # unchanged semantics — default backend's underlying model
        "backend": "mlx",             # unchanged — literal runtime tag
        "model_loaded": _ready.is_set(),
        "ready": _ready.is_set(),
        "voices": sorted(VOICES.keys()),
        "default_voice": DEFAULT_VOICE,
        "loaded_backends": loaded_backends,
    }
```

- [ ] **Step 2: Smoke test**

Run: `python server.py --no-warmup` (separate terminal)
Run: `curl -s localhost:7860/health | jq .`
Expected JSON contains:
- `"backend": "mlx"` (unchanged)
- `"model": "..."` (unchanged, now resolves to default backend's model_id)
- `"loaded_backends"` with four keys: `chatterbox`, `qwen3-0.6b`, `qwen3-1.7b`, `voxcpm-1.5`

Stop server.

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(server): /health adds loaded_backends block (legacy fields preserved)"
```

---

### Task 10: Rewrite `_register_voice` and `_unregister_session` for `VoiceProfile` + cleanup manifest

**Files:**
- Modify: `server.py:78-92` (`_register_voice`)
- Modify: `server.py:95-110` (`_unregister_session`)
- Modify: `server.py:74-75` (delete `_voice_metadata` global)

- [ ] **Step 1: Delete `_voice_metadata` global at `server.py:74-75`**

Remove:
```python
# Voice metadata registry: name → {emotion, duration_s, confidence, session_id}
_voice_metadata: dict[str, dict] = {}
```

All metadata now lives on `VoiceProfile`.

- [ ] **Step 2: Replace `_register_voice` at `server.py:78-92` with:**

```python
def _register_voice(
    name: str,
    backend_name: str,
    ref_audio: str,
    ref_text: str | None,
    prepared: PreparedVoice,
    emotion: str = "neutral",
    metadata: dict | None = None,
):
    """Thread-safe runtime voice registration. Builds a VoiceProfile."""
    meta = metadata or {}
    profile = VoiceProfile(
        name=name,
        backend=backend_name,
        ref_audio=ref_audio,
        ref_text=ref_text,
        session_id=meta.get("session_id") or (name.rsplit("-", 1)[0] if "-" in name else name),
        emotion=emotion,
        quality=meta.get("quality"),
        duration_s=meta.get("duration_s"),
        confidence=meta.get("confidence"),
        sequence=meta.get("sequence"),
        extras=_read_only(meta.get("extras", {})),
        prepared=prepared,
    )
    with _model_lock:
        VOICES[name] = profile
```

- [ ] **Step 3: Replace `_unregister_session` at `server.py:95-110` with:**

```python
def _unregister_session(session_id: str):
    """Remove all voice profiles for a session + their files + any backend cleanup artifacts."""
    with _model_lock:
        to_remove = [
            name for name, profile in VOICES.items()
            if profile.session_id == session_id
        ]
        for name in to_remove:
            profile = VOICES.pop(name)
            # Delete backend-created temp artifacts (resampled refs, cached embeddings).
            for path in profile.prepared.cleanup_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if profile.prepared.owns_temp_audio:
                try:
                    os.remove(profile.prepared.ref_audio_path)
                except OSError:
                    pass
            # Delete the checked-in voice assets (unchanged behaviour).
            for ext in ("-ref.wav", ".json"):
                path = os.path.join(_VOICES_DIR, f"{name}{ext}")
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
```

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "refactor(server): _register_voice + _unregister_session use VoiceProfile, clean manifests"
```

---

### Task 11: Update `POST /clone` — backend form field, two-phase locking

**Files:**
- Modify: `server.py:314-445`

This task resolves Gemini's round-3 sequence paradox: transcription is CPU-only and MUST run between two lock phases, not inside one.

- [ ] **Step 1: Update `POST /clone` handler at `server.py:314-445`**

Find the function signature:
```python
@app.post("/clone")
async def clone_voice_endpoint(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    emotion: str = Form("neutral"),
    transcript: str | None = Form(None),
):
```

Replace with:
```python
@app.post("/clone")
async def clone_voice_endpoint(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    emotion: str = Form("neutral"),
    transcript: str | None = Form(None),
    backend: str = Form("qwen3-1.7b"),
):
```

- [ ] **Step 2: Add backend validation near the top of the handler, after the `audio_bytes` check**

Find:
```python
audio_bytes = await audio.read()
if len(audio_bytes) < 1000:
    return JSONResponse({"error": "audio too short"}, status_code=400)
```

Immediately after, add:
```python
try:
    backend_obj = backends.get(backend)
except KeyError:
    return JSONResponse(
        {"error": f"unknown backend: {backend}", "available": backends.names()},
        status_code=400,
    )
```

- [ ] **Step 3: Restructure the denoise / transcribe / prepare sequence into three phases**

Find the existing body of the try block (the big `try: import tempfile ... os.unlink(tmp_in_path)` block spanning roughly `server.py:334-424`).

Replace everything from `try:` through `_register_voice(...)` with:

```python
    try:
        import tempfile
        import noisereduce as nr

        # Save uploaded audio to temp file.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
            tmp_in.write(audio_bytes)
            tmp_in_path = tmp_in.name

        # --- Phase 1: denoise under _synth_lock (noisereduce may touch Metal) ---
        with _synth_lock:
            data, sr_in = sf.read(tmp_in_path)
            if data.ndim > 1:
                data = data.mean(axis=1)
            reduced = nr.reduce_noise(y=data, sr=sr_in, stationary=True, prop_decrease=0.7)
            peak = np.max(np.abs(reduced))
            if peak > 0:
                reduced = reduced * (0.9 / peak)
        # --- lock released ---

        duration_s = len(reduced) / sr_in
        if duration_s < 1.0:
            os.unlink(tmp_in_path)
            return JSONResponse(
                {"error": "audio too short after processing (< 1s)"},
                status_code=400,
            )

        quality = "rough" if duration_s < 5 else "developing" if duration_s < 15 else "good"

        # --- Phase 2: CPU-only work (no lock) — write WAV + transcribe ---
        ref_path = os.path.join(_VOICES_DIR, f"{session_id}-{len([k for k in VOICES if k.startswith(f'{session_id}-')]) + 1:03d}-ref.wav")
        voice_name = os.path.basename(ref_path)[:-len("-ref.wav")]
        seq = int(voice_name.rsplit("-", 1)[-1])

        tmp_ref = ref_path + ".tmp"
        sf.write(tmp_ref, reduced, sr_in, format="WAV", subtype="PCM_16")
        os.rename(tmp_ref, ref_path)

        transcript_confidence = 0.0
        if not transcript:
            try:
                from faster_whisper import WhisperModel
                whisper = WhisperModel("base.en", compute_type="int8")
                segments, _ = whisper.transcribe(tmp_in_path)
                words = []
                for seg in segments:
                    for w in seg.words or []:
                        words.append(w.word.strip())
                transcript = " ".join(words)
                transcript_confidence = 0.8
            except Exception as exc:
                log.warning("transcription failed, using empty transcript: %s", exc)
                transcript = ""
        else:
            transcript_confidence = 0.9

        # REQUIRED-policy backends need a transcript.
        if backend_obj.ref_text_policy == RefTextPolicy.REQUIRED and not transcript:
            os.unlink(tmp_in_path)
            return JSONResponse(
                {"error": f"backend {backend} requires ref_text; transcription failed"},
                status_code=400,
            )

        # --- Phase 3: validate_extras + prepare_voice under _synth_lock (both may touch Metal) ---
        extras: dict = {}
        with _synth_lock:
            try:
                backend_obj.validate_extras(extras)
            except ValueError as exc:
                os.unlink(tmp_in_path)
                return JSONResponse(
                    {"error": f"invalid extras for backend {backend}: {exc}"},
                    status_code=400,
                )
            try:
                prepared = backend_obj.prepare_voice(ref_path, transcript or None, extras)
            except Exception as exc:
                log.error("prepare_voice failed: %s", exc, exc_info=True)
                os.unlink(tmp_in_path)
                return JSONResponse(
                    {"error": f"prepare_voice failed: {exc}"},
                    status_code=500,
                )
        # --- lock released ---

        # Save profile JSON with backend field.
        profile_path = os.path.join(_VOICES_DIR, f"{voice_name}.json")
        tmp_profile = profile_path + ".tmp"
        with open(tmp_profile, "w") as f:
            json.dump({
                "name": voice_name,
                "backend": backend,
                "session_id": session_id,
                "emotion": emotion,
                "reference_audio": os.path.basename(ref_path),
                "reference_text": transcript,
                "quality": quality,
                "duration_s": round(duration_s, 1),
                "transcript_confidence": round(transcript_confidence, 2),
                "sequence": seq,
            }, f, indent=2)
        os.rename(tmp_profile, profile_path)

        # Register in runtime registry.
        _register_voice(
            voice_name,
            backend_name=backend,
            ref_audio=ref_path,
            ref_text=transcript or None,
            prepared=prepared,
            emotion=emotion,
            metadata={
                "session_id": session_id,
                "quality": quality,
                "duration_s": duration_s,
                "confidence": transcript_confidence,
                "sequence": seq,
            },
        )

        os.unlink(tmp_in_path)
        log.info(
            "cloned: %s (backend=%s, session=%s, emotion=%s, quality=%s, %.1fs)",
            voice_name, backend, session_id, emotion, quality, duration_s,
        )

        return {
            "voice": voice_name,
            "backend": backend,
            "emotion": emotion,
            "quality": quality,
            "transcript_confidence": round(transcript_confidence, 2),
            "duration_s": round(duration_s, 1),
            "sequence": seq,
        }
    except Exception as exc:
        log.error("clone failed: %s", exc, exc_info=True)
        return JSONResponse({"error": f"clone failed: {exc}"}, status_code=500)
```

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat(server): POST /clone accepts backend field; two-phase locking"
```

---

### Task 12: `clone-voice.sh` — `--backend` and `--all-backends` flags

**Files:**
- Modify: `clone-voice.sh`

- [ ] **Step 1: Add argument parsing near the top of `clone-voice.sh`**

After the existing `AUTO_YES=false` / `[[ "${4:-}" == "--yes" ]] && AUTO_YES=true` lines (around `clone-voice.sh:31-32`), add:

```bash
# Parse --backend and --all-backends flags from any position
BACKEND_NAME=""
ALL_BACKENDS=false
for arg in "$@"; do
    case "$arg" in
        --backend=*) BACKEND_NAME="${arg#--backend=}" ;;
        --backend) ;;  # handled via next arg below
        --all-backends) ALL_BACKENDS=true ;;
    esac
done
# Also accept `--backend NAME` split form
for ((i=1; i<=$#; i++)); do
    if [ "${!i}" = "--backend" ]; then
        j=$((i+1))
        BACKEND_NAME="${!j:-}"
    fi
done

# Query registry via Python for available backends + max sample rate
if ! AVAILABLE_BACKENDS=$(python -m backends list 2>/dev/null); then
    fail "Could not query backends — is the venv active?"
fi
MAX_SR=$(python -m backends max-sample-rate 2>/dev/null || echo 24000)

# Default backend if not specified
[ -z "$BACKEND_NAME" ] && BACKEND_NAME="qwen3-1.7b"

# Validate backend unless we're doing --all-backends
if [ "$ALL_BACKENDS" = false ]; then
    if ! echo "$AVAILABLE_BACKENDS" | grep -qx "$BACKEND_NAME"; then
        fail "Unknown backend: $BACKEND_NAME. Available: $(echo "$AVAILABLE_BACKENDS" | tr '\n' ' ')"
    fi
fi
```

- [ ] **Step 2: Update the reference-extraction step to use `$MAX_SR`**

Find the existing `ffmpeg` or `sox` call that writes the `-ref.wav`. (Look for a line creating a file named `${VOICE_NAME}-ref.wav` from the extracted segment.) Change the target sample rate to `$MAX_SR` — typically via adding `-ar "$MAX_SR"` to ffmpeg args.

If the current extraction doesn't specify a sample rate, add one now. Example:
```bash
ffmpeg -i "$TMP_SRC" -ss "$START_S" -t "$DURATION" -ar "$MAX_SR" -ac 1 "$VOICES_DIR/${VOICE_NAME}-ref.wav"
```

- [ ] **Step 3: Update the JSON-profile write step to include `"backend"` field and honour `--all-backends`**

Find the existing block that writes `${VOICES_DIR}/${VOICE_NAME}.json`. Replace it with:

```bash
write_profile() {
    local _name="$1" _backend="$2" _out="$3"
    cat > "$_out" <<EOF
{
  "name": "$_name",
  "backend": "$_backend",
  "source_url": "$YT_URL",
  "reference_audio": "${VOICE_NAME}-ref.wav",
  "reference_text": $TRANSCRIPT_JSON,
  "segment_start_s": $START_S
}
EOF
}

if [ "$ALL_BACKENDS" = true ]; then
    # Default backend gets the unslugged filename
    DEFAULT_BACKEND="qwen3-1.7b"
    write_profile "$VOICE_NAME" "$DEFAULT_BACKEND" "$VOICES_DIR/${VOICE_NAME}.json"
    ok "Wrote $VOICE_NAME.json (backend: $DEFAULT_BACKEND)"
    for _b in $AVAILABLE_BACKENDS; do
        [ "$_b" = "$DEFAULT_BACKEND" ] && continue
        _slug=$(python -m backends slug "$_b")
        _alt_name="${VOICE_NAME}-${_slug}"
        _alt_json="$VOICES_DIR/${_alt_name}.json"
        # Re-use the same -ref.wav; only JSON differs
        cat > "$_alt_json" <<EOF
{
  "name": "$_alt_name",
  "backend": "$_b",
  "source_url": "$YT_URL",
  "reference_audio": "${VOICE_NAME}-ref.wav",
  "reference_text": $TRANSCRIPT_JSON,
  "segment_start_s": $START_S
}
EOF
        ok "Wrote ${_alt_name}.json (backend: $_b)"
    done
else
    write_profile "$VOICE_NAME" "$BACKEND_NAME" "$VOICES_DIR/${VOICE_NAME}.json"
    ok "Wrote $VOICE_NAME.json (backend: $BACKEND_NAME)"
fi
```

Note: assumes an existing `$TRANSCRIPT_JSON` variable holding the JSON-escaped transcript string. If the current script builds the transcript inline, factor it out into `$TRANSCRIPT_JSON` first.

- [ ] **Step 4: Smoke test (dry — only if you already have a short local source)**

Run: `bash clone-voice.sh --help 2>&1 | head -5` — should not error.

Run (after server restart to pick up new voices): `afterwords voices` — any newly-cloned voice should show its backend.

- [ ] **Step 5: Commit**

```bash
git add clone-voice.sh
git commit -m "feat(clone-voice): add --backend and --all-backends flags"
```

---

### Task 13: `afterwords.sh` — backend column in `voices`, backends section in `status`

**Files:**
- Modify: `afterwords.sh`

- [ ] **Step 1: Locate the `voices` subcommand in `afterwords.sh` and update the listing**

Find the block handling `afterwords voices` (likely a `case "voices" ... esac` arm). Replace the voice-listing logic with:

```bash
voices)
    if [ ! -d "$VOICES_DIR" ]; then
        echo "No voices directory."
        exit 1
    fi
    # Print with backend column, parsed from JSON
    printf "%-30s %s\n" "VOICE" "BACKEND"
    printf "%-30s %s\n" "-----" "-------"
    for _json in "$VOICES_DIR"/*.json; do
        [ -f "$_json" ] || continue
        _name=$(basename "$_json" .json)
        _backend=$(jq -r '.backend // "qwen3-0.6b"' "$_json" 2>/dev/null || echo "?")
        printf "%-30s %s\n" "$_name" "$_backend"
    done
    ;;
```

- [ ] **Step 2: Locate the `status` subcommand and add a backends section**

Find the `status` arm. After the existing server-health print, add:

```bash
    # Per-backend status from /health.loaded_backends
    echo
    echo "Backends:"
    curl -s "http://localhost:$PORT/health" 2>/dev/null | \
        jq -r '.loaded_backends | to_entries[] | "  \(.key)  — \(.value.voice_count) voices, \(.value.sample_rate) Hz"' || \
        echo "  (could not read backend status)"
```

- [ ] **Step 3: Commit**

```bash
git add afterwords.sh
git commit -m "feat(cli): afterwords voices shows backend; status shows per-backend load"
```

---

### Task 14: Add `tests/test_backends.py` — protocol shape + registry, no model load

**Files:**
- Create: `tests/test_backends.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for the backends/ registry + protocol — no model load."""
from __future__ import annotations

import pytest

import backends
from backends.base import Backend, PreparedVoice, RefTextPolicy, _read_only


@pytest.fixture(autouse=True)
def _clean_registry():
    backends.reset_for_tests()
    yield
    backends.reset_for_tests()


def test_register_all_populates_four_backends():
    backends.register_all()
    assert set(backends.names()) == {
        "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5",
    }


def test_each_registered_backend_satisfies_protocol():
    backends.register_all()
    for name in backends.names():
        b = backends.get(name)
        assert isinstance(b, Backend)
        assert isinstance(b.sample_rate, int) and b.sample_rate > 0
        assert isinstance(b.ref_text_policy, RefTextPolicy)
        assert isinstance(b.name, str) and b.name == name


def test_duplicate_register_raises():
    backends.register_all()
    b = backends.get("chatterbox")
    with pytest.raises(ValueError, match="already registered"):
        backends.register(b)


def test_slug_collision_raises():
    backends.register_all()
    class _Fake:
        name = "voxcpm-15"  # slugs to "voxcpm-15", collides with voxcpm-1.5
        display_name = "fake"
        sample_rate = 16000
        ref_text_policy = RefTextPolicy.OPTIONAL
        supported_langs = ()
        def load(self): pass
        def validate_extras(self, e): pass
        def prepare_voice(self, *a, **k): raise NotImplementedError
        def synthesize(self, *a, **k): raise NotImplementedError
    with pytest.raises(ValueError, match="slug collision"):
        backends.register(_Fake())


def test_get_unknown_raises():
    backends.register_all()
    with pytest.raises(KeyError, match="unknown backend"):
        backends.get("nope")


def test_max_sample_rate_reflects_voxcpm():
    backends.register_all()
    assert backends.max_sample_rate() == 44100


def test_slug_strips_dots():
    assert backends.slug("voxcpm-1.5") == "voxcpm-15"
    assert backends.slug("qwen3-0.6b") == "qwen3-06b"
    assert backends.slug("chatterbox") == "chatterbox"


def test_prepared_voice_extras_are_readonly():
    pv = PreparedVoice(
        ref_audio_path="/tmp/x.wav",
        ref_text=None,
        extras={"a": 1},
    )
    with pytest.raises(TypeError):
        pv.extras["b"] = 2  # MappingProxyType blocks mutation


def test_prepared_voice_wraps_plain_dict():
    pv = PreparedVoice(ref_audio_path="/tmp/x.wav", ref_text=None, extras={"a": 1})
    # __post_init__ should have wrapped in MappingProxyType
    from types import MappingProxyType
    assert isinstance(pv.extras, MappingProxyType)
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_backends.py -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_backends.py
git commit -m "test(backends): protocol + registry + PreparedVoice immutability"
```

---

### Task 15: Add `tests/test_voice_profiles.py` — loader semantics

**Files:**
- Create: `tests/test_voice_profiles.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for VoiceProfile loading and backend-aware profile discovery."""
from __future__ import annotations

import json
import os

import pytest

import backends


@pytest.fixture(autouse=True)
def _load_registry():
    backends.reset_for_tests()
    backends.register_all()
    yield
    backends.reset_for_tests()


def _write_profile(tmp_path, name: str, **fields):
    """Helper: write a voices/*.json + a minimal -ref.wav next to it."""
    import soundfile as sf
    import numpy as np

    json_path = tmp_path / f"{name}.json"
    ref_path = tmp_path / f"{name}-ref.wav"
    sf.write(str(ref_path), np.zeros(24000, dtype=np.float32), 24000)
    payload = {
        "name": name,
        "reference_audio": f"{name}-ref.wav",
        **fields,
    }
    json_path.write_text(json.dumps(payload))
    return json_path, ref_path


def test_profile_without_backend_field_defaults_to_qwen3_06b(tmp_path, monkeypatch):
    from server import _load_voice_profiles, VOICES, _VOICES_DIR
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "legacy", reference_text="hello world")
    _load_voice_profiles()
    assert "legacy" in VOICES
    assert VOICES["legacy"].backend == "qwen3-0.6b"


def test_profile_with_explicit_backend_honoured(tmp_path, monkeypatch):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "new", backend="chatterbox")  # no ref_text — Chatterbox OPTIONAL
    _load_voice_profiles()
    assert "new" in VOICES
    assert VOICES["new"].backend == "chatterbox"


def test_profile_unknown_backend_skipped(tmp_path, monkeypatch, caplog):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "future", backend="some-future-model", reference_text="x")
    _load_voice_profiles()
    assert "future" not in VOICES
    assert "unregistered backend" in caplog.text


def test_profile_required_policy_without_ref_text_skipped(tmp_path, monkeypatch, caplog):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "qwen3voice", backend="qwen3-0.6b")  # no ref_text
    _load_voice_profiles()
    assert "qwen3voice" not in VOICES
    assert "REQUIRES ref_text" in caplog.text


def test_profile_optional_policy_without_ref_text_kept(tmp_path, monkeypatch):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(tmp_path, "chatvoice", backend="chatterbox")
    _load_voice_profiles()
    assert "chatvoice" in VOICES
    assert VOICES["chatvoice"].ref_text is None


def test_profile_with_unknown_extras_skipped(tmp_path, monkeypatch, caplog):
    from server import _load_voice_profiles, VOICES
    monkeypatch.setattr("server._VOICES_DIR", str(tmp_path))
    VOICES.clear()
    _write_profile(
        tmp_path, "badextras",
        backend="qwen3-0.6b",
        reference_text="x",
        synthesis_extras={"bogus_key": 1},
    )
    _load_voice_profiles()
    assert "badextras" not in VOICES
    assert "invalid extras" in caplog.text
```

- [ ] **Step 2: Run tests (these exercise `prepare_voice`, which for Qwen3/Chatterbox doesn't load the model — just wraps paths). VoxCPM would resample; these tests don't exercise VoxCPM.**

Run: `pytest tests/test_voice_profiles.py -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_voice_profiles.py
git commit -m "test(voices): VoiceProfile loader honours backend + ref_text policy"
```

---

### Task 16: Extend `tests/test_server.py` — loaded_backends, 400 on unknown voice

**Files:**
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add these tests to the existing `tests/test_server.py`**

Append at the end of the file:

```python
def test_health_includes_loaded_backends(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "mlx"  # legacy field unchanged
    assert "loaded_backends" in body
    assert set(body["loaded_backends"].keys()) >= {
        "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5",
    }
    for name, info in body["loaded_backends"].items():
        assert info["loaded"] is True
        assert isinstance(info["voice_count"], int)
        assert isinstance(info["sample_rate"], int)


def test_health_preserves_legacy_fields(client):
    resp = client.get("/health")
    body = resp.json()
    for key in ("status", "model", "backend", "model_loaded", "ready", "voices", "default_voice"):
        assert key in body


def test_synthesize_unknown_voice_returns_400(client):
    resp = client.get("/synthesize?text=hi&voice=nonexistent-voice-zzzz")
    assert resp.status_code == 400
    body = resp.json()
    assert "unknown voice" in body["error"]
    assert isinstance(body["available"], list)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_server.py -v`
Expected: all tests PASS (including existing ones)

- [ ] **Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test(server): /health loaded_backends + 400 on unknown voice"
```

---

### Task 17: Add `tests/test_backends_integration.py` — opt-in per-backend synth

**Files:**
- Create: `tests/test_backends_integration.py`

- [ ] **Step 1: Write the file — one short synth per backend, marked integration**

```python
"""Integration tests — actually load each backend + synth a short clip.

Opt-in:
    pytest -m integration tests/test_backends_integration.py

Requires MLX + ~10 GB RAM + network (first run downloads weights).
"""
from __future__ import annotations

import os

import numpy as np
import pytest

import backends


pytestmark = pytest.mark.integration


SHORT_REF = os.path.join(
    os.path.dirname(__file__), "..", "voices", "galadriel-ref.wav"
)
SHORT_REF_TEXT = "In the beginning."


@pytest.fixture(scope="module")
def registered():
    backends.reset_for_tests()
    backends.register_all()
    yield
    backends.reset_for_tests()


@pytest.mark.parametrize("backend_name", [
    "qwen3-0.6b",
    "qwen3-1.7b",
    "chatterbox",
    "voxcpm-1.5",
])
def test_backend_loads_and_synthesizes_short_clip(registered, backend_name):
    b = backends.get(backend_name)
    b.load()
    b.validate_extras({})
    prepared = b.prepare_voice(SHORT_REF, SHORT_REF_TEXT, {})
    audio, sr = b.synthesize("Hello.", prepared)
    assert isinstance(audio, np.ndarray)
    assert audio.ndim == 1
    assert sr == b.sample_rate
    assert audio.size > sr * 0.1  # at least 100ms of audio
```

- [ ] **Step 2: Register `integration` marker in `pytest.ini` if not already present**

Ensure `pytest.ini` contains:
```ini
[pytest]
markers =
    integration: slow tests that load real models; run with `pytest -m integration`
```

- [ ] **Step 3: Default `pytest` must skip these** — the marker + `pytestmark` at file level + the existing `pytest.ini` default (usually `-m 'not integration'`) handle this. Verify:

Run: `pytest -v` (no `-m integration`)
Expected: integration tests do NOT run.

Run: `pytest -m integration -v` (manual — takes 3-5 minutes first time)
Expected: 4 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_backends_integration.py pytest.ini
git commit -m "test(backends): opt-in integration test per backend"
```

---

### Task 18: Update `CLAUDE.md` — multi-backend architecture notes

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Replace the "Key Constraints" memory/concurrency bullet**

Find the bullet that currently says:
```
- Model peaks at ~6 GB unified memory; no room for concurrent models on 8 GB machines
```

Replace with:
```
- Four cloning backends (Qwen3 0.6B + 1.7B, Chatterbox, VoxCPM 1.5) preload at boot (~10 GB total). Requires 16 GB+ unified memory; designed for 32 GB.
- All synthesis is serialized through `_synth_lock` — MLX Metal is single-GPU, regardless of backend
```

- [ ] **Step 2: Update the "Architecture" section's server.py description**

Find the paragraph that starts "**server.py** — FastAPI/Uvicorn TTS server..." and update the model description:

Old:
```
Lazy-loads the Qwen3-TTS model once (`_model_lock`), serializes all synthesis through `_synth_lock` (MLX Metal is not thread-safe).
```

New:
```
Preloads four cloning backends via `backends.register_all()` at startup, serializes all synthesis through `_synth_lock` (MLX Metal is not thread-safe across backends). Voice profiles pin to a backend via the `backend` JSON field; dispatch is `backend = backends.get(profile.backend); backend.synthesize(text, profile.prepared)`.
```

- [ ] **Step 3: Add a new "Backends" section after "Architecture"**

```markdown
## Backends

The `backends/` package exposes a `Backend` Protocol (in `backends/base.py`) and a registry (`backends/__init__.py`). Each backend is a single Python file implementing `load / validate_extras / prepare_voice / synthesize`. Registered shipped backends:

| Name | Size | Sample rate | ref_text policy |
|------|------|-------------|-----------------|
| `qwen3-0.6b` | 0.6B | 24 kHz | REQUIRED |
| `qwen3-1.7b` | 1.7B | 24 kHz | REQUIRED |
| `chatterbox` | 0.8B (fp16) | 24 kHz | OPTIONAL |
| `voxcpm-1.5` | 2B (bf16) | 44.1 kHz | OPTIONAL |

Adding a backend: create `backends/newmodel.py` implementing the Backend protocol, then add one line to `register_all()` in `backends/__init__.py`. The registry CLI (`python -m backends list | max-sample-rate | slug <name>`) is used by `clone-voice.sh` to stay backend-aware.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): multi-backend architecture + memory constraints"
```

---

### Task 19: Manual step — re-clone flagship voices + update demo site

**Files:**
- Manual: clone 3 voices on all 4 backends
- Modify: `docs/index.html` (add backend comparison section)

This task is operator-driven; it produces the audible deliverable.

- [ ] **Step 1: Restart the server to pick up the new backends**

```bash
afterwords restart
afterwords status
```

Expected: "Backends:" section shows four entries, all with voice_count ≥ 0.

- [ ] **Step 2: Re-clone three flagship voices with --all-backends**

For each of `picard`, `galadriel`, `attenborough`:

```bash
# Use the YouTube URL from the existing voices/<name>.json source_url field
SOURCE_URL=$(jq -r '.source_url' voices/picard.json)
START=$(jq -r '.segment_start_s' voices/picard.json)
bash clone-voice.sh "$SOURCE_URL" picard-v2 "$START" --all-backends
```

Repeat for `galadriel` and `attenborough`. This produces `picard-v2.json` (default backend, Qwen3-1.7B) plus `picard-v2-qwen3-06b.json`, `picard-v2-chatterbox.json`, `picard-v2-voxcpm-15.json`.

Restart server: `afterwords restart`.

- [ ] **Step 3: Verify each backend synthesizes its version of each voice**

```bash
for V in picard-v2 picard-v2-qwen3-06b picard-v2-chatterbox picard-v2-voxcpm-15; do
    curl -s "localhost:7860/synthesize?text=The%20line%20must%20be%20drawn%20here&voice=$V" -o "/tmp/${V}.wav"
    echo "$V: $(soxi -D /tmp/${V}.wav)s"
done
```

Expected: all four WAVs generated, each with a positive duration.

- [ ] **Step 4: Update `docs/index.html` — add a "Backend Comparison" section**

Near the existing voice-demo section, add:

```html
<section class="backend-comparison">
  <h2>Same voice, four backends</h2>
  <p>Picard's "The line must be drawn here" rendered by each of Afterwords' four cloning backends.</p>
  <table>
    <tr>
      <th>Backend</th>
      <th>Preview</th>
    </tr>
    <tr>
      <td>Qwen3-TTS 1.7B</td>
      <td><audio controls src="audio/picard-v2.mp3"></audio></td>
    </tr>
    <tr>
      <td>Qwen3-TTS 0.6B</td>
      <td><audio controls src="audio/picard-v2-qwen3-06b.mp3"></audio></td>
    </tr>
    <tr>
      <td>Chatterbox (multilingual)</td>
      <td><audio controls src="audio/picard-v2-chatterbox.mp3"></audio></td>
    </tr>
    <tr>
      <td>VoxCPM 1.5 (44.1 kHz)</td>
      <td><audio controls src="audio/picard-v2-voxcpm-15.mp3"></audio></td>
    </tr>
  </table>
</section>
```

Render the MP3s by converting the WAVs from Step 3 (`ffmpeg -i in.wav -b:a 96k out.mp3`) into `docs/audio/`.

- [ ] **Step 5: Commit**

```bash
git add voices/picard-v2* voices/galadriel-v2* voices/attenborough-v2* docs/index.html docs/audio/
git commit -m "feat(demo): flagship voices re-cloned on all backends + comparison section"
```

---

## Self-review

After writing this plan I checked spec coverage:

- Backend Protocol + registry (Component 1–2): Tasks 1–4
- `VoiceProfile` dataclass + loader (Component 3): Task 5
- Dispatch + `_resolve_voice` + `/health` (Component 4): Tasks 6, 7, 9
- Startup sequence (Component 4): Task 8
- `POST /clone` + `DELETE /session` + `_register_voice` + `_unregister_session` (Component 5): Tasks 10, 11
- `clone-voice.sh` (Component 6): Task 12
- CLI + skill (Component 7): Task 13
- `server.py` change table coverage (Component 8): Tasks 5–11 collectively touch every row
- Error handling (spec "Error handling" table): covered in Tasks 5, 6, 7, 11
- Testing (spec "Testing" section): Tasks 14, 15, 16, 17
- Acceptance criteria 1–11: Tasks 14–19 collectively

**Type consistency:** `VoiceProfile`, `PreparedVoice`, `Backend`, `RefTextPolicy` names are consistent across all tasks. `_register_voice` signature (Task 10) matches its call sites in Task 11 (POST /clone).

**Remaining operator notes** (from R3 reviewer feedback, carried into implementer context):
1. Startup takes 60–180s cold — Task 8 adds per-backend progress logging.
2. `POST /clone` two-phase lock is explicit in Task 11; transcription runs CPU-only between phases.
3. `MappingProxyType` enforcement lives in `PreparedVoice.__post_init__` (Task 1) and has test coverage (Task 14).
4. `--no-warmup` only skips the warmup synth, not backend loads (explicitly noted in Task 8).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-19-multi-backend-tts.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
