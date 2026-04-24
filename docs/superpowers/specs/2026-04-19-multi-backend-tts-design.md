# Multi-Backend Cloning TTS — Design

**Date:** 2026-04-19
**Status:** Draft — revision 3 (addresses second-round Claude/Codex/Gemini findings)

## Overview

Afterwords currently hard-codes Qwen3-TTS-0.6B as its single synthesis backend. The 32 GB RAM upgrade (from 8 GB) removes the "one model at a time" constraint that originally justified a single-backend design, and the zero-shot cloning landscape now has several MLX-native alternatives worth keeping in the stable.

This spec introduces a `Backend` protocol, an explicit backend registry, and a per-voice backend field so that zero-shot cloning models can be swapped in with minimal code change. The deliverable is **infrastructure**: adding the next MLX-native cloning model (e.g., a future VoxCPM2-MLX or F5-TTS-MLX port) should be one new file plus one line of registration — not a rewrite. Four backends ship at launch to prove the abstraction; the voice catalog grows to include re-clones on the new backends so the quality difference is audible on the demo site.

The `GET /synthesize`, `POST /synthesize`, `POST /clone`, `DELETE /session/{id}`, and `GET /health` HTTP shapes continue to work for existing callers. The `/health` **adds** a `loaded_backends` field; it does **not** redefine the existing `backend` field (which stays as the literal tag `"mlx"` that it is today). Existing voices continue to work without any migration. Existing `.afterwords` files continue to work unchanged.

## Goals

1. **Swap-ability as a deliverable.** Adding backend N+1 requires one new file in `backends/` and one line in `backends/__init__.py:register_all()`. No edits to `server.py`, no changes to the HTTP surface.
2. **Ship four cloning backends at launch**, proving three different reference-text policies:
   - Qwen3-TTS 0.6B (current, stays as default for existing voices) — `ref_text` REQUIRED in the cloning path we use¹
   - Qwen3-TTS 1.7B (quality bump, same family) — `ref_text` REQUIRED¹
   - Chatterbox (MIT, `mlx-community/chatterbox-fp16` — the **multilingual** variant, not `chatterbox-turbo` which is EN-only) — `ref_text` OPTIONAL
   - VoxCPM 1.5 (44.1 kHz output, officially documented for English and Chinese²) — `ref_text` OPTIONAL (used in "Ultimate" cloning mode only)

¹ *Qwen3-TTS supports an `x_vector_only_mode` that doesn't need ref_text. We don't use it — our flow is always reference-wav-plus-transcript cloning. Backend instance correctly advertises `REQUIRED` for this usage; a future backend variant could advertise `OPTIONAL` if we opt in to `x_vector_only_mode` later.*

² *Do not conflate with VoxCPM2, which is a separate model (PyTorch-only, 30 languages, out of scope for this spec).*
3. **Re-clone a small set of flagship voices** onto the new backends so the quality/character difference is audible on the demo site.
4. **Preserve backwards compatibility.** Existing `voices/*.json` profiles without a `backend` field default to `qwen3-0.6b`. All current HTTP endpoints and error codes continue to behave as they do today.

## Non-Goals

- Preset-voice backends (Voxtral). Out of scope — different UX surface, deferred to a separate spec.
- PyTorch / CUDA-substitute fallbacks for non-MLX models (VoxCPM2, F5-TTS, Higgs Audio, IndexTTS-2). The abstraction is designed so they could slot in later, but no PyTorch runtime ships in v1.
- Surfacing VoxCPM-specific features (voice design from text, multilingual language tags, inline style control). The backend supports them via `synthesis_extras`; exposing them through `/synthesize`, the skill, or the CLI is a separate UX spec.
- LRU eviction / lazy-load / model swap-on-demand. With 32 GB RAM, all four backends preload at boot. Adds complexity we don't need.
- Multi-process isolation. Rejected during brainstorming — MLX Metal serialises on one GPU regardless, so multi-process buys very little and costs a lot.
- Hot-reload of voice profiles. `POST /clone` continues to register a voice at runtime, but adding new backends or new static profiles still requires a restart. See **Open questions**.

## Decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | Scope: 4 cloning backends (Qwen3 0.6B + 1.7B, Chatterbox, VoxCPM 1.5) | Three distinct `ref_text` policies; all MLX-native in `mlx-audio`; fits comfortably in 32 GB. |
| D2 | Voice profile pins to backend | Simplest, zero-migration; matches users' mental model. |
| D3 | Cloning flow: `--backend` flag, default `qwen3-1.7b`; `--all-backends` produces one profile per backend | Default scripting-friendly; opt-in comparison spread for demo A/B. |
| D4 | Primary goal: **swap-ability (infra)**, secondary: quality via re-clones | Architecture is the product; audible deliverable keeps it honest. |
| D5 | Approach: Backend Protocol + **explicit `register_all()`** at boot | Matches D4; testable (monkeypatch registry in tests); avoids brittle import side-effects. |
| D6 | Preload **all four** backends at boot, unconditionally | 32 GB easily fits ~10 GB of weights. Eager preload closes the `POST /clone` edge case where a runtime-clone defaults to a backend that had no static voices pointing at it (would otherwise 503). Simpler than per-reference preload. |

## Memory footprint (target machine, 32 GB unified)

| Backend | Approx. RAM loaded | Basis |
|---|---|---|
| Qwen3-TTS 0.6B (8-bit) | ~1.5 GB | observed in current server; matches 0.6B × 8-bit + KV + activations |
| Qwen3-TTS 1.7B (8-bit) | ~3.5 GB | 1.7B × 8-bit + overhead; scale from 0.6B observation |
| Chatterbox fp16 (multilingual variant) | ~1.6 GB | 0.8B × fp16; higher than the `chatterbox-turbo` 4-bit (~0.5 GB) but needed for multilingual support |
| VoxCPM 1.5 (bf16 native) | ~4 GB | 2B × bf16 ≈ 4 GB; matches model card |
| **Total (all four preloaded)** | **~10.6 GB** | |

Leaves ~20 GB headroom on a 32 GB machine for OS, browser, and other processes. All four can stay hot. No lazy-load required. Numbers are approximate; integration tests verify actual footprint during CI runs.

## File Structure

```
afterwords/
├── server.py                       (refactored — HTTP + global synth lock + dispatch + _resolve_voice)
├── backends/                       ← NEW
│   ├── __init__.py                 (registry + explicit register_all() + CLI helper entry)
│   ├── base.py                     (Backend protocol, RefTextPolicy enum, shared types)
│   ├── qwen3.py                    (0.6B and 1.7B; registered as two Backend instances)
│   ├── chatterbox.py
│   └── voxcpm.py
├── voices/*.json                   (optionally gains "backend" field + existing session/emotion/quality fields)
├── clone-voice.sh                  (gains --backend + --all-backends; calls `python -m backends list | max-sample-rate | slug <name>`)
├── tests/
│   ├── test_server.py              (existing; extended)
│   ├── test_backends.py            ← NEW (protocol shape + registry tests, no model load)
│   ├── test_voice_profiles.py      ← NEW (schema, default backend, backend-aware ref_text guard)
│   └── test_backends_integration.py ← NEW, @pytest.mark.integration (one short synth per backend; opt-in)
└── docs/superpowers/specs/2026-04-19-multi-backend-tts-design.md
```

## Component 1 — `backends/base.py`: the Backend protocol

```python
from __future__ import annotations
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable
from dataclasses import dataclass, field
import numpy as np


class RefTextPolicy(Enum):
    REQUIRED = "required"    # Qwen3 (our cloning path) — must have a transcript
    OPTIONAL = "optional"    # Chatterbox, VoxCPM — uses if present, works without
    IGNORED  = "ignored"     # a hypothetical future backend that can't use transcripts


@dataclass(frozen=True)
class PreparedVoice:
    """A voice after backend-specific preprocessing (e.g., resampling, embedding extraction).

    Invariants:
      - `ref_audio_path` may point to a resampled temp file owned by this PreparedVoice.
        If the backend creates such a file, it must set `owns_temp_audio = True` so the
        server knows to delete it during DELETE /session teardown.
      - `extras` must be a read-only Mapping. Backends that need mutable runtime state
        must allocate it per-call inside synthesize(), not store it in extras.
    """
    ref_audio_path: str
    ref_text: str | None
    extras: Mapping[str, object]   # read-only; wrap with MappingProxyType at construction
    owns_temp_audio: bool = False  # True if ref_audio_path was created by prepare_voice()
    cleanup_paths: tuple[str, ...] = ()  # additional temp artifacts to delete on teardown


@runtime_checkable
class Backend(Protocol):
    """Contract for a zero-shot cloning TTS backend."""

    name: str                   # unique registry key: "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5"
    display_name: str           # human-readable: "Qwen3-TTS 1.7B"
    sample_rate: int            # native output rate: 24000 (Qwen3, Chatterbox), 44100 (VoxCPM 1.5)
    ref_text_policy: RefTextPolicy
    supported_langs: tuple[str, ...]  # e.g., ("en", "zh", "ja", ...) — see per-backend module

    def load(self) -> None:
        """Load weights into memory. Idempotent. Must be thread-safe."""

    def validate_extras(self, extras: dict) -> None:
        """Raise ValueError for unknown / invalid extras keys. Called at profile-load time."""

    def prepare_voice(self, ref_audio_path: str, ref_text: str | None, extras: dict) -> PreparedVoice:
        """
        One-time preprocessing per voice profile. Called at profile-load time (after load()).
        May resample the reference audio (VoxCPM's 44.1 kHz), extract speaker embeddings, etc.
        Return value is cached in the VoiceProfile; passed to synthesize() on every request.
        """

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
    ) -> tuple[np.ndarray, int]:
        """
        Return (mono float32 audio, sample_rate).
        Caller holds the global synth lock.
        """
```

### Design notes

- **`Protocol` over ABC** — duck-typed, no inheritance required, pyright still catches shape violations. Backends can subclass whatever helper base class they want internally.
- **`RefTextPolicy` enum over `needs_ref_text: bool`.** The old boolean conflates "required" with "rejected." Chatterbox uses `ref_text` when present but works fine without it — that's the middle state (`OPTIONAL`). The profile-loader at startup and the cloning flow both branch on this.
- **`validate_extras()` runs at profile-load, not at request time.** Extras live in the voice's JSON, not the HTTP request — catching typos at boot prevents latent 500s.
- **`prepare_voice()` owns one-time preprocessing.** Resampling VoxCPM's reference from 24 kHz (the extractor's default) to 44.1 kHz happens once and is cached inside `PreparedVoice`. Closes the finding that `load()` has nowhere to put per-voice work.
- **`prepare_voice()` must be called AFTER `load()`** for backends that need model weights to prepare a voice (e.g., embedding extraction). Startup sequence in Component 4 enforces this ordering.
- **`prepare_voice()` runs under `_synth_lock` when called at request time** (runtime `POST /clone`). At boot, the synth lock isn't needed because no synthesis is in flight yet — but any runtime call (clone, future hot-reload) must acquire it. Component 5 specifies this explicitly.
- **`PreparedVoice` is read-only and carries its own cleanup manifest.** `extras` is `Mapping[str, object]` — backends constructing a `PreparedVoice` should wrap their extras dict with `MappingProxyType` so downstream code can't mutate them. Mutable per-call state is allocated inside `synthesize()`, never stored in `PreparedVoice`. Temp files created by `prepare_voice()` are listed in `cleanup_paths` and deleted by `DELETE /session` / session teardown — see Component 5.
- **`synthesize()` takes a `PreparedVoice`, not raw paths.** Decouples the server from the reference-audio storage format.
- **`load()` is idempotent and thread-safe.** Each Backend owns a private init lock; `server.py`'s global `_synth_lock` covers synthesis regardless of backend.

## Component 2 — `backends/__init__.py`: explicit registry

```python
from .base import Backend, RefTextPolicy, PreparedVoice

_REGISTRY: dict[str, Backend] = {}
_SLUG_REGISTRY: dict[str, str] = {}  # slug → backend name, for uniqueness enforcement

def _slug(name: str) -> str:
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
    """Explicitly register every shipped backend. Called once at server startup."""
    from .qwen3 import Qwen3Backend
    from .chatterbox import ChatterboxBackend
    from .voxcpm import VoxCPMBackend
    register(Qwen3Backend(size="0.6B"))
    register(Qwen3Backend(size="1.7B"))
    register(ChatterboxBackend())
    register(VoxCPMBackend())

def get(name: str) -> Backend:
    if name not in _REGISTRY:
        raise KeyError(f"unknown backend {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]

def names() -> list[str]:
    return sorted(_REGISTRY)

def max_sample_rate() -> int:
    """Highest native sample rate across registered backends — used by clone-voice.sh."""
    if not _REGISTRY:
        return 24000
    return max(b.sample_rate for b in _REGISTRY.values())
```

**Bash ↔ Python boundary.** `backends/__main__.py` provides a CLI so `clone-voice.sh` can query the registry:

```python
# python -m backends list            → one backend name per line
# python -m backends max-sample-rate → integer, used for reference extraction
# python -m backends slug <name>     → filename-safe slug for --all-backends
```

Adding backend N+1: create `backends/newmodel.py` implementing the protocol, add one line to `register_all()`. No import-side-effect magic. Testable because `register_all()` can be monkeypatched in unit tests.

## Component 3 — Voice profile schema

Current schema (for reference):
```json
{
  "name": "amy-pond",
  "source_url": "...",
  "reference_audio": "amy-pond-ref.wav",
  "reference_text": "...",
  "segment_start_s": 5
}
```

Runtime-cloned voice schema (already in use by `POST /clone`, unchanged):
```json
{
  "name": "session-001",
  "session_id": "session",
  "emotion": "neutral",
  "reference_audio": "session-001-ref.wav",
  "reference_text": "...",
  "quality": "good",
  "duration_s": 18.3,
  "transcript_confidence": 0.9,
  "sequence": 1
}
```

New additive fields (all optional; fully back-compat):
```json
{
  "backend": "qwen3-1.7b",          // absent → "qwen3-0.6b" default
  "synthesis_extras": {              // per-backend kwargs; schema checked at load
    "cfg_value": 2.0
  }
}
```

### `VoiceProfile` dataclass (in `server.py`)

```python
@dataclass(frozen=True)
class VoiceProfile:
    name: str
    backend: str                       # defaults to "qwen3-0.6b" when JSON field absent
    ref_audio: str                     # filesystem path (absolute)
    ref_text: str | None               # None is valid iff backend.ref_text_policy != REQUIRED
    session_id: str | None             # preserved from existing session clones
    emotion: str                       # "neutral" if absent
    quality: str | None                # "rough"/"developing"/"good" for clone-derived voices
    duration_s: float | None
    confidence: float | None           # transcript_confidence
    sequence: int | None
    extras: Mapping[str, object]       # synthesis_extras, already validated against the backend
    prepared: PreparedVoice            # result of backend.prepare_voice() — computed at load
```

The `Mapping` type matches the `PreparedVoice.extras` guarantee: once a `VoiceProfile` is assembled, its extras are read-only for the rest of its lifetime.

### Load-time behaviour

The `server.py` `VOICES` dict changes from `{name: (ref_audio, ref_text)}` to `{name: VoiceProfile}`. The exact per-profile sequence is specified in Component 4's Startup section (step 3a–e); it runs **after** all backends have loaded their weights.

**Profile identity:** the dict key is the **JSON `"name"` field** if present, else the filename stem. Current `server.py` uses filename stem; new loader must check both for parity. Documented explicitly because it's a source of foot-guns.

## Component 4 — Server dispatch and lifecycle

### Startup sequence

The ordering is deliberate: backends load weights **before** any profile calls `prepare_voice()`, because preparation may depend on loaded weights (e.g., embedding extraction).

1. `backends.register_all()` — populates registry.
2. For each registered backend, call `backend.load()` sequentially. All four backends preload unconditionally (see D6). Any `load()` failure is fatal: log traceback, `SystemExit(1)`.
3. Walk `voices/*.json` and, for each profile, do in order:
   a. Resolve the `backend` field (default `"qwen3-0.6b"`). If backend not registered → log warning + skip.
   b. Validate `ref_text` against the backend's `RefTextPolicy`. If REQUIRED and missing → skip.
   c. `backend.validate_extras(synthesis_extras)`. On `ValueError` → log + skip.
   d. `backend.prepare_voice(ref_audio, ref_text, extras)` → `PreparedVoice`. On exception → log + skip.
   e. Assemble `VoiceProfile` (with the `PreparedVoice` cached) and store in `VOICES`.
4. `_warmup()` against the default voice (uses the already-cached `PreparedVoice` and the already-loaded backend).
5. `_ready.set()` after warmup.

**Rationale for unconditional preload.** An earlier revision loaded only "referenced" backends, but this creates a race: `POST /clone` with the default `qwen3-1.7b` backend on an install that previously had only 0.6B profiles would 503. Preloading all four costs ~10 GB of memory (fine on 32 GB) and eliminates the class entirely.

### `_resolve_voice()` — preserved, extended

The existing function at `server.py:130–165` handles session-palette lookup and emotion fallback. Its contract is preserved; only its return type changes:

```python
def _resolve_voice(voice: str, emotion: str | None = None) -> VoiceProfile | None:
    """
    Return the VoiceProfile for a voice name, considering session palettes and emotion fallback.
    Returns None if no match. Callers must 400 on None (to preserve existing API contract).
    """
    # Exact match
    if voice in VOICES:
        profile = VOICES[voice]
        if emotion is None or profile.emotion == emotion:
            return profile

    # Session palette lookup — find entries with matching session_id prefix + emotion
    if emotion:
        candidates = [p for p in VOICES.values()
                      if p.session_id == voice and p.emotion == emotion]
        if candidates:
            return max(candidates, key=lambda p: (p.duration_s or 0, p.confidence or 0))
        # No emotion match — fall back to best quality entry for this session
        session_entries = [p for p in VOICES.values() if p.session_id == voice]
        if session_entries:
            return max(session_entries, key=lambda p: (p.duration_s or 0, p.confidence or 0))

    return VOICES.get(voice)
```

### Dispatch

`_synthesize_audio(text, voice_name, emotion=None)`:

1. Before `_ready.is_set()` → `503 {"error": "server warming up, try again shortly"}` (unchanged — existing global gate at `server.py:275`).
2. `profile = _resolve_voice(voice_name, emotion)`. If `None` → `400 {"error": "unknown voice: ...", "available": [...]}` (matches current behaviour at `server.py:278, 305`).
3. `backend = backends.get(profile.backend)`. (Always loaded post-startup; D6.)
4. Acquire global `_synth_lock`.
5. Call `backend.synthesize(text, profile.prepared)`.
6. Encode audio → WAV PCM_16 at the returned SR. Return Response with `X-Synthesis-Time`, `X-Duration`, `X-Sample-Rate` headers (unchanged).

### `/health` changes — additive only

```json
{
  "status": "ok",
  "model": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",   // unchanged — the default backend's underlying model id
  "backend": "mlx",                                          // unchanged — the literal runtime tag
  "model_loaded": true,                                      // unchanged
  "ready": true,                                             // unchanged
  "voices": ["amy-pond", "attenborough", ...],               // unchanged — list of names
  "default_voice": "galadriel",                              // unchanged
  "loaded_backends": {                                       // NEW — per-backend status
    "qwen3-0.6b": {"loaded": true, "voice_count": 16, "sample_rate": 24000},
    "qwen3-1.7b": {"loaded": true, "voice_count": 4, "sample_rate": 24000},
    "chatterbox": {"loaded": true, "voice_count": 2, "sample_rate": 24000},
    "voxcpm-1.5": {"loaded": true, "voice_count": 2, "sample_rate": 44100}
  }
}
```

**No existing field is repurposed.** `backend` stays `"mlx"`. Consumers that read `backend` or `model` today keep working.

## Component 5 — Runtime cloning and session management

The existing `POST /clone` and `DELETE /session/{id}` endpoints continue to work. They gain backend awareness:

### `POST /clone` changes

- Accepts a new optional `backend` form field. Default: `"qwen3-1.7b"` (the newest high-quality Qwen3). Because D6 now preloads all four backends unconditionally, the default is never unloaded on a fresh install.
- The denoising pass at `server.py:344–352` is unchanged — it already holds `_synth_lock` (see `server.py:345`).
- **`validate_extras()` and `prepare_voice()` must run under `_synth_lock`.** Both may invoke Metal (embedding extraction, resampling through MLX ops) and can crash if they race with an in-flight synthesize. Concretely, the clone handler extends its existing `with _synth_lock:` block to cover denoise → validate_extras → prepare_voice as one critical section. Transcription (faster-whisper) does not need the lock — it runs on CPU via int8 — and can happen outside.
- The resulting `VoiceProfile` is stored in `VOICES` and persisted to `voices/{voice_name}.json` with a `backend` field populated.
- Response shape gains `"backend"` (matches the request).
- If the requested backend isn't registered → `400 {"error": "unknown backend: ...; available: [...]"}`. (A not-loaded-but-registered case is now impossible because D6 preloads all.)

### `DELETE /session/{id}` changes

Endpoint semantics unchanged — deletes all `VoiceProfile` entries whose `session_id == id`, plus their files. But the **implementation** changes with `VoiceProfile`:

- For each `VoiceProfile` being removed, also delete any artifacts listed in `profile.prepared.cleanup_paths`, and delete `profile.prepared.ref_audio_path` if `profile.prepared.owns_temp_audio` is true.
- This prevents backend-created temp artifacts (resampled WAVs, cached embeddings) from leaking over time.
- The existing JSON + `-ref.wav` deletion logic at `server.py:95–110` becomes backend-aware via this manifest.

### `_register_voice()` changes

Signature gains `backend: str` **and** `prepared: PreparedVoice` parameters. Builds and stores a `VoiceProfile` (not a tuple) using both. Called by `POST /clone` (where prepared comes from the clone handler's own `prepare_voice()` call) and by the startup profile-load path (where prepared is computed during step 3d).

### `_unregister_session()` changes (at `server.py:95–110`)

Refactor to iterate `VOICES` by `session_id` on the new `VoiceProfile` objects, removing the legacy `_voice_metadata` global entirely (its fields now live on `VoiceProfile`). For each removed profile, perform the cleanup-manifest deletions described above in addition to the existing JSON + ref-WAV removal.

## Component 6 — Cloning workflow (shell)

`clone-voice.sh` changes:

- `--backend <name>` — default `qwen3-1.7b`. Validated by calling `python -m backends list` and grepping.
- `--all-backends` — runs the extraction once, then produces one JSON profile per registered backend (calling `python -m backends list`). **Skips** creating the slugged file for the default backend since the plain `{name}.json` already covers it. So for `--name picard --all-backends` with default `qwen3-1.7b`:
  - `picard.json` — default backend (`qwen3-1.7b`)
  - `picard-qwen3-06b.json` — `qwen3-0.6b`
  - `picard-chatterbox.json` — `chatterbox`
  - `picard-voxcpm-15.json` — `voxcpm-1.5`

### Reference audio extraction

Reference is extracted at `python -m backends max-sample-rate` (currently 44100, the VoxCPM rate). Backends with lower native SR resample once inside `prepare_voice()` — one-time cost at load, cached in `PreparedVoice`.

Transcript generation (faster-whisper) runs once and is included in every JSON profile, even for `OPTIONAL`-policy backends — uniform schema, trivial storage cost.

### Filename slug rule

Slug = `name.replace(".", "")`. Registered in `backends/__init__.py` with collision assertion. Current map:
- `qwen3-0.6b` → `qwen3-06b`
- `qwen3-1.7b` → `qwen3-17b`
- `chatterbox` → `chatterbox`
- `voxcpm-1.5` → `voxcpm-15`

The `backend` field inside each JSON always holds the full registry name (`"voxcpm-1.5"`); only filenames use the slug.

## Component 7 — CLI & skill surface

### `afterwords` CLI

- `afterwords voices` — output gains a `backend` column. The wrapper reads `voices/*.json` directly and uses `jq` to pull the `backend` field (defaulting to `qwen3-0.6b` if absent). No `/health` shape change required.
- `afterwords clone` — passes through `--backend` and `--all-backends`.
- `afterwords status` — continues to read `/health`; gains a "Backends" section printed from `loaded_backends`. The legacy "Model: ..." line still prints from the unchanged `model` field.

### Claude Code skill

- `scripts/speak.sh` — unchanged. Voice name implies backend via profile.
- `.afterwords` format — unchanged. Examples in docs continue to use bare voice names or `agent: voice` mappings (the spec doesn't introduce a `voice: picard-voxcpm` syntax; the user simply writes the slugged voice name, e.g., `voice: picard-voxcpm-15`).
- New optional phrase: "list backends" → calls `/health`, prints `loaded_backends` summary. Not blocking v1.

## Component 8 — Changes to `server.py` internals

Explicit list so no behaviour is lost during refactor:

| Line (current) | Change |
|---|---|
| `43` `MODEL_ID = "..."` | Remove. Each backend owns its own model id. Keep a module-level `DEFAULT_BACKEND = "qwen3-0.6b"` instead. |
| `50` `VOICES: dict[str, tuple[str, str]]` | Change type to `dict[str, VoiceProfile]`. |
| `52–63` voice auto-discovery loop | Rewrite per Component 3 load sequence. Drop the `if _p.get("reference_text")` guard — replace with backend-aware check. |
| `78–92` `_register_voice` | Add `backend: str` and `prepared: PreparedVoice` parameters. Build `VoiceProfile`, not a tuple. Remove writes to `_voice_metadata` — all metadata now lives on `VoiceProfile`. |
| `95–110` `_unregister_session` | Refactor to iterate `VOICES` by `VoiceProfile.session_id` instead of the `_voice_metadata` global (which is deleted). For each removed profile, delete `prepared.cleanup_paths` entries and (if `prepared.owns_temp_audio`) `prepared.ref_audio_path`. Retain existing JSON + ref-WAV deletion. |
| `113–127` `_get_model` | Delete. Per-backend loading is owned by each `Backend` instance. |
| `130–165` `_resolve_voice` | Keep logic; change return type to `VoiceProfile | None`. Update session/emotion scan to use profile fields directly. |
| `168–194` `_warmup` | Use default voice's backend. Call `backend.synthesize(prepared)` through the same dispatcher. |
| `197–207` `/health` | Add `loaded_backends` block per Component 4. Leave all existing fields untouched. |
| `210–261` `_synthesize_audio` | Take `VoiceProfile` not `(ref_audio, ref_text)`. Dispatch via `backends.get(profile.backend).synthesize(text, profile.prepared)`. |
| `264–284` `GET /synthesize` | No change to status codes. Update to pass `VoiceProfile` through. |
| `293–311` `POST /synthesize` | No change to status codes or clone-gating. Update to pass `VoiceProfile` through. |
| `314–445` `POST /clone` | Add `backend` form field (default `qwen3-1.7b`). **Extend existing `with _synth_lock:` block** to cover denoise → `validate_extras` → `prepare_voice` as one critical section (prevents Metal races with concurrent synthesis). Validate registered backend; 400 on unknown. Persist `backend` field in JSON. Pass `prepared` to `_register_voice`. |
| `448–455` `DELETE /session` | Endpoint signature unchanged. The underlying `_unregister_session` helper gains cleanup-manifest deletion (see its row above). |
| `458–502` `main()` | Call `backends.register_all()` first. Then call `backend.load()` for all four registered backends (unconditional, per D6). Then walk `voices/*.json` per Component 4 Startup step 3. Replace existing `_get_model()` + `_warmup()` call site with the new sequence. |

## Error handling

| Situation | Handling |
|---|---|
| Unknown voice in `GET /synthesize` | **400** `{"error": "unknown voice: ...", "available": [...]}` (matches current behaviour, contrary to prior draft). |
| Unknown voice in `POST /synthesize` | 400 (same, gated on `_clone_enabled`). |
| Voice profile references unregistered backend at startup | Logged + skipped. Voice not in `VOICES`. If it's the default voice, main() already handles "default voice pruned" case. |
| Profile has `ref_text_policy=REQUIRED` backend but empty `reference_text` | Logged + skipped at startup. |
| `validate_extras()` raises at startup | Logged + skipped at startup. |
| `prepare_voice()` raises at startup | Logged + skipped at startup. |
| Backend `.load()` fails at startup | Fatal. Log traceback; `SystemExit(1)`. No half-loaded state. |
| `backend.synthesize()` raises at request time | Caught in `_synthesize_audio`, 500 `{"error": "synthesis failed"}` (matches current). |
| `POST /clone` requests unknown backend | 400 `{"error": "unknown backend: ...; available: [...]}`. |
| `POST /clone` requests registered but not-loaded backend | N/A — D6 preloads all four backends unconditionally. Registered implies loaded. |
| `--all-backends` hits a backend whose `validate_extras({})` fails | Log warning, skip that JSON output, continue with the rest. Don't fail the whole clone. |

## Testing

### `tests/test_backends.py` — no model load

- Protocol conformance: `isinstance(b, Backend)` for every registered backend.
- Registry uniqueness: registering the same `name` twice raises `ValueError`; slug collision raises `ValueError`.
- `get("bogus")` raises `KeyError` with the available list.
- `max_sample_rate()` returns `max(b.sample_rate for b in registry)`.
- `ref_text_policy` enum values round-trip correctly.

### `tests/test_voice_profiles.py`

- Profile with explicit `backend` field → parsed correctly.
- Profile without `backend` → defaults to `qwen3-0.6b`.
- Profile with unknown backend → skipped, logged.
- Profile with `REQUIRED` backend but empty `reference_text` → skipped.
- Profile with `OPTIONAL` backend and empty `reference_text` → kept.
- Profile with `synthesis_extras` containing invalid key → `validate_extras` raises, profile skipped.
- Profile identity comes from JSON `"name"` when present, falls back to filename stem.

### `tests/test_server.py` — extensions

- `/health` contains `loaded_backends`.
- `/health` `backend` field is still `"mlx"` (not a backend-registry name).
- Unknown voice returns 400 (not 404).
- `GET /synthesize` before `_ready.is_set()` → 503 (existing behaviour, still correct). Post-ready, there is no "registered-but-unloaded" state by construction (D6).
- Legacy `/health` fields (`model`, `backend`, `model_loaded`) all still present.
- `POST /clone` with `backend=chatterbox` persists a profile with that field set.
- `POST /clone` with unknown backend → 400.

### `tests/test_backends_integration.py` — opt-in, `@pytest.mark.integration`

Per Codex: protocol-shape tests don't catch API drift in `mlx-audio`. This file has one test per backend that actually calls `load()` + one short `synthesize()` against a bundled short reference. Not run by default `pytest`; only when `-m integration` is passed. Useful for manual verification during mlx-audio upgrades.

### Manual / audible acceptance

- Re-clone three flagship voices (`picard`, `galadriel`, `attenborough`) with `--all-backends`.
- Demo site page gains a "Backend comparison" section playing the same line across the four renditions.
- Subjective listening: document findings in a follow-up PR, not this one.

## Acceptance criteria

1. `pytest` passes; `test_backends.py`, `test_voice_profiles.py`, and the extended `test_server.py` are green. `test_backends_integration.py` is green when run with `-m integration` (manual).
2. `GET /health` returns `loaded_backends`; all legacy fields (`model`, `backend`, `model_loaded`, `ready`, `voices`, `default_voice`) are present with their existing semantics.
3. `GET /synthesize?voice=picard` returns audio from Qwen3-0.6B (default backend for the existing profile).
4. `GET /synthesize?voice=bogus` returns **400** (not 404) with the `available` list — unchanged from today.
5. A manually-added `voices/test-chatterbox.json` with `"backend": "chatterbox"` and no `reference_text` field loads successfully (Chatterbox is OPTIONAL-policy).
6. `bash clone-voice.sh <url> testvoice 30 --backend voxcpm-1.5` produces `voices/testvoice.json` with `"backend": "voxcpm-1.5"` and a 44.1 kHz `testvoice-ref.wav`.
7. `bash clone-voice.sh <url> testvoice 30 --all-backends` produces `testvoice.json` (default backend) plus three slugged profiles (`testvoice-qwen3-06b.json`, `testvoice-chatterbox.json`, `testvoice-voxcpm-15.json`).
8. `POST /clone` with `backend=chatterbox` (server started with `--allow-clone`) creates a voice profile that synthesizes via Chatterbox.
9. `afterwords status` shows per-backend load state from `loaded_backends`. `afterwords voices` shows a `backend` column.
10. `CLAUDE.md` is updated: the "6 GB peak, no room for concurrent models" note is replaced with a multi-backend paragraph; the architecture section reflects the registry and `_resolve_voice` contract.
11. A short listening test comparing Picard across the four backends is linked from the demo site.

## Open questions / follow-ups (not blocking v1)

- **VoxCPM voice design.** VoxCPM can generate voices from text descriptions with no reference. Different UX (no profile file). Deferred — own spec.
- **VoxCPM style prompts at request time.** A future `GET /synthesize?voice=picard&style=cheerful` would let callers steer emotion per-request. Deferred.
- **Multilingual.** Qwen3 supports 10+ languages; Chatterbox (`chatterbox-fp16` variant) supports multilingual synthesis in mlx-audio (turbo variant is EN-only); VoxCPM 1.5 is EN/CN per its model card. We currently hard-code `lang_code="en"` in the Qwen3 invocation. A `lang` parameter on `/synthesize` is a follow-up; each backend's `supported_langs` is already populated.
- **Hot-reload of voice profiles.** Adding a new `voices/*.json` file without a restart isn't supported. A `POST /reload` admin endpoint is a later addition. **Any future hot-reload must hold `_synth_lock` around `backend.load()` / `backend.prepare_voice()` to prevent a load racing with an in-flight synthesis on the same GPU.**
- **Runtime clone using an unloaded backend.** Current plan: 503. Could be upgraded to on-demand `backend.load()` — but requires the synth-lock-around-load constraint above.
- **Migrating existing voices to Qwen3-1.7B.** Re-cloning 18 voices takes time. Do we migrate everything, or leave existing voices on 0.6B and put new/flagship work on 1.7B? Design allows either — decision deferred to the migration PR.
- **Tests that bundle a short reference WAV.** `test_backends_integration.py` needs a copyright-safe short reference. Use one of the existing repo voices (they're already tracked) rather than shipping new audio.
