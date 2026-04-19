# Multi-Backend Cloning TTS — Design

**Date:** 2026-04-19
**Status:** Draft (pending QA review)

## Overview

Afterwords currently hard-codes Qwen3-TTS-0.6B as its single synthesis backend. The 32 GB RAM upgrade (from 8 GB) removes the "one model at a time" constraint that originally justified a single-backend design, and the zero-shot cloning landscape now has several MLX-native alternatives worth keeping in the stable.

This spec introduces a Backend protocol, a backend registry, and a per-voice backend field so that zero-shot cloning models can be swapped in with minimal code change. The deliverable is **infrastructure**: adding the next MLX-native cloning model (e.g., a future VoxCPM2-MLX or F5-TTS-MLX port) should be one new file plus one line of registration — not a rewrite. Four backends ship at launch to prove the abstraction; the voice catalog grows to include re-clones on the new backends so the quality difference is audible on the demo site.

The `/synthesize` and `/health` HTTP shapes do not change. Existing voices continue to work without any migration. Existing `.afterwords` files continue to work unchanged.

## Goals

1. **Swap-ability as a deliverable.** Adding backend N+1 requires one new file in `backends/` and one line in `backends/__init__.py`. No edits to `server.py`, no changes to the HTTP surface.
2. **Ship four cloning backends at launch**, proving three different input contracts:
   - Qwen3-TTS 0.6B (current, stays as default for existing voices)
   - Qwen3-TTS 1.7B (quality bump, same family)
   - Chatterbox Turbo (MIT, ref_wav-only)
   - VoxCPM 1.5 (48 kHz studio quality, ref_wav + optional style prompt)
3. **Re-clone a small set of flagship voices** onto the new backends so the quality/character difference is audible on the demo site.
4. **Preserve backwards compatibility.** Existing `voices/*.json` profiles without a `backend` field default to `qwen3-0.6b`. Existing hook, skill, CLI, and `.afterwords` behaviour is unchanged.

## Non-Goals

- Preset-voice backends (Voxtral). Out of scope — different UX surface, deferred to a separate spec.
- PyTorch / CUDA-substitute fallbacks for non-MLX models (VoxCPM2, F5-TTS, Higgs Audio, IndexTTS-2). The abstraction is designed so they could slot in later, but no PyTorch runtime ships in v1.
- Surfacing VoxCPM-specific features (voice design from text, multilingual language tags, inline style control). The backend supports them via `extras`; exposing them through `/synthesize`, the skill, or the CLI is a separate UX spec.
- LRU eviction / lazy-load / model swap-on-demand. With 32 GB RAM, all four backends preload at boot. Adds complexity we don't need.
- Multi-process isolation (one uvicorn per backend). Rejected during brainstorming — MLX Metal serialises on one GPU regardless, so multi-process buys very little and costs a lot.

## Decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | Scope: 4 cloning backends (Qwen3 0.6B + 1.7B, Chatterbox, VoxCPM 1.5) | Three distinct input contracts represented; all MLX-native in `mlx-audio`; fits comfortably in 32 GB. |
| D2 | Voice profile pins to backend | Simplest, zero-migration; matches users' mental model ("Picard voice = a specific artifact"). |
| D3 | Cloning flow: `--backend` flag, default `qwen3-1.7b`; `--all-backends` produces one profile per backend | Default scripting-friendly; opt-in comparison spread for demo A/B. |
| D4 | Primary goal: **swap-ability (infra)**, secondary: quality via re-clones | Architecture is the product; audible deliverable keeps it honest. |
| D5 | Approach: Backend Protocol + auto-registering module registry | Matches D4; caps `server.py` size; each backend testable in isolation. |
| D6 | Preload all requested backends at boot | 32 GB makes lazy/LRU unnecessary; removes a whole complexity category. |

## File Structure

```
afterwords/
├── server.py                       (shrinks: HTTP + global synth lock + dispatch)
├── backends/                       ← NEW
│   ├── __init__.py                 (registry + auto-discovery via import)
│   ├── base.py                     (Backend protocol, shared types, SynthesisResult)
│   ├── qwen3.py                    (0.6B and 1.7B; registered as two Backend instances)
│   ├── chatterbox.py
│   └── voxcpm.py
├── voices/*.json                   (optionally gains "backend" field)
├── clone-voice.sh                  (gains --backend + --all-backends)
├── tests/
│   ├── test_server.py              (existing; extended)
│   ├── test_backends.py            ← NEW (protocol conformance, no model load)
│   └── test_voice_profiles.py      ← NEW (schema + default-backend back-compat)
└── docs/
    └── superpowers/specs/2026-04-19-multi-backend-tts-design.md
```

## Component 1 — `backends/base.py`: the Backend protocol

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable
import numpy as np

@runtime_checkable
class Backend(Protocol):
    """Contract for a zero-shot cloning TTS backend."""

    name: str                # unique registry key: "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5"
    display_name: str        # human-readable: "Qwen3-TTS 1.7B"
    sample_rate: int         # native output rate, e.g., 24000 or 48000
    needs_ref_text: bool     # True = ref_text required; False = ignored if provided
    supported_langs: tuple[str, ...]  # e.g., ("en", "zh", "ja", ...)

    def load(self) -> None:
        """Load weights into memory. Idempotent. Must be thread-safe."""

    def synthesize(
        self,
        text: str,
        ref_wav_path: str,
        ref_text: str | None,
        **extras,   # e.g., style_prompt, cfg_value, timesteps — per-backend kwargs
    ) -> tuple[np.ndarray, int]:
        """Return (mono float32 audio, sample_rate). Caller holds the global synth lock."""
```

### Design notes

- **`Protocol` over ABC** — duck-typed, no inheritance required, pyright still catches shape violations. Keeps each backend class free to subclass anything (e.g., an `mlx_audio` loader helper).
- **`**extras`** for per-backend kwargs is deliberate. Typing each one would force protocol changes every time a new model ships with novel knobs. Each backend validates its own `extras` keys and raises `ValueError` for unknown ones.
- **`load()` is idempotent and thread-safe.** Each Backend owns a private init lock; `server.py`'s global `_synth_lock` is orthogonal and covers all synthesis regardless of backend.
- **Return shape is `(np.ndarray, sample_rate)`.** Server re-encodes to WAV (PCM_16 at the model's native SR). No forced resampling — if different backends return different SRs, the WAV reports the true SR; clients handle that today already.

## Component 2 — `backends/__init__.py`: the registry

```python
from .base import Backend

_REGISTRY: dict[str, Backend] = {}

def register(backend: Backend) -> None:
    if backend.name in _REGISTRY:
        raise ValueError(f"backend {backend.name!r} already registered")
    _REGISTRY[backend.name] = backend

def get(name: str) -> Backend:
    if name not in _REGISTRY:
        raise KeyError(f"unknown backend {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]

def names() -> list[str]:
    return sorted(_REGISTRY)

# Auto-discover — import each backend module; each registers at module load.
from . import qwen3, chatterbox, voxcpm  # noqa: F401, E402
```

Each backend module ends with:

```python
register(Qwen3Backend(size="0.6B"))
register(Qwen3Backend(size="1.7B"))
```

Adding backend N+1 is: create `backends/newmodel.py` implementing the protocol, add `from . import newmodel` to `__init__.py`. That's it.

## Component 3 — Voice profile schema

Current schema:
```json
{
  "name": "picard",
  "source_url": "...",
  "reference_audio": "picard-ref.wav",
  "reference_text": "...",
  "segment_start_s": 5
}
```

New schema (additive, fully back-compat):
```json
{
  "name": "picard",
  "backend": "qwen3-1.7b",            // NEW — absent = "qwen3-0.6b" (default)
  "source_url": "...",
  "reference_audio": "picard-ref.wav",
  "reference_text": "...",
  "segment_start_s": 5,
  "synthesis_extras": {                // NEW, OPTIONAL — per-backend kwargs
    "cfg_value": 2.0
  }
}
```

### Naming collision when re-cloning onto a new backend

Two profiles can't share a `name` (the server's `VOICES` dict key). Convention for re-clones: suffix the voice name with the backend — `picard-chatterbox.json`, `picard-voxcpm.json`. The original `picard.json` stays on Qwen3-0.6B. Users pick by calling the suffixed name. `--all-backends` produces the suffixed set plus leaves `{name}.json` pointing at whatever the default-backend clone produced.

### Load-time behaviour

`server.py`'s `VOICES` dict changes from `{name: (ref_audio, ref_text)}` to `{name: VoiceProfile}` where:

```python
@dataclass(frozen=True)
class VoiceProfile:
    name: str
    backend: str         # defaults to "qwen3-0.6b" when absent in JSON
    ref_audio: str
    ref_text: str | None   # None for Chatterbox, etc.
    extras: dict
```

Profiles whose `backend` names a backend not currently registered are **logged and skipped** (not fatal) — lets us ship a voice profile file before its backend is available.

## Component 4 — Server dispatch and lifecycle

### Startup

1. `backends/__init__.py` auto-imports all backend modules → registry populated.
2. Voice profiles are loaded from `voices/*.json` into `VOICES: dict[str, VoiceProfile]`. Profiles referencing unknown backends are logged + skipped.
3. For each backend **that has at least one voice profile referencing it**, call `backend.load()` sequentially. (Preload-all-on-demand; never load a backend no voice uses.)
4. `_ready.set()` after the last load finishes. Warmup synth (currently fires against default voice) now fires against the default voice's backend specifically.

### Synthesis dispatch

`_synthesize_audio(text, voice_name)`:

1. Look up `VoiceProfile` for `voice_name`. If missing → 404.
2. `backend = registry.get(profile.backend)`.
3. Acquire global `_synth_lock` (MLX Metal is not thread-safe across backends either — one GPU).
4. Call `backend.synthesize(text, profile.ref_audio, profile.ref_text, **profile.extras)`.
5. Encode audio → WAV PCM_16 at the returned SR. Return Response.

### `/health` additions

```json
{
  "status": "ok",
  "backends": {
    "qwen3-0.6b": {"loaded": true, "voices": 16},
    "qwen3-1.7b": {"loaded": true, "voices": 4},
    "chatterbox": {"loaded": true, "voices": 2},
    "voxcpm-1.5": {"loaded": true, "voices": 2}
  },
  "voices": [...],
  "ready": true
}
```

The legacy top-level `"model"` and `"backend": "mlx"` fields are retained with string values pointing at the default backend, for any existing consumer.

## Component 5 — Cloning workflow

`clone-voice.sh` gets:

- `--backend <name>` — default `qwen3-1.7b`. Validated against `backends/__init__.py names()`.
- `--all-backends` — runs the extraction once, then produces one JSON profile per registered backend. Skips backends that don't accept the reference (e.g., if future backend requires 48 kHz input and extractor only produced 24 kHz).

### Reference audio extraction per backend

VoxCPM prefers 48 kHz references; Qwen3 and Chatterbox work at 24 kHz. The extraction step uses the **highest sample rate any registered backend requires** (48 kHz if VoxCPM is in scope) and writes one `*-ref.wav` at that rate. Backends that want a lower SR resample internally on load — cheap, one-time cost.

Transcript generation (faster-whisper) runs once and is included in every JSON profile, even for backends where `needs_ref_text = False`. Keeps the schema uniform; storage cost is trivial.

### Naming

- Single-backend clone: `--name picard --backend voxcpm-1.5` → `picard.json` with `backend: "voxcpm-1.5"`. (The user *chose* that name; we don't second-guess.)
- `--all-backends --name picard` → produces `picard.json` (default backend) + one profile per other backend, suffixed with a **filename-safe backend slug** (lowercase alphanumerics + hyphens, dots removed):
  - `qwen3-0.6b` → `qwen3-06b` → `picard-qwen3-06b.json`
  - `qwen3-1.7b` → `qwen3-17b` → `picard-qwen3-17b.json`
  - `chatterbox` → `chatterbox` → `picard-chatterbox.json`
  - `voxcpm-1.5` → `voxcpm-15` → `picard-voxcpm-15.json`
  The slug rule is `name.replace(".", "")`. The `backend` field inside each JSON keeps the full registry name (`"voxcpm-1.5"`) — only the **filename** uses the slug.

Collision behaviour: if `picard.json` already exists, the script prompts to overwrite. With `--yes`, it overwrites silently.

## Component 6 — CLI & skill surface

### `afterwords` CLI

- `afterwords voices` — output gains a `backend` column. `--demo` unchanged.
- `afterwords clone` — passes through `--backend` and `--all-backends`.
- `afterwords status` — health response now includes the `backends` block; status formatter prints one line per backend.

### Claude Code skill

- `scripts/speak.sh` passes voice name through to `/synthesize` unchanged — backend is implicit via the voice profile, so the skill doesn't need any grammar change.
- New phrase recognised by the skill: "list backends" → calls `/health`, prints backend summary. (Minor addition; doesn't block v1 if skipped.)

### `.afterwords` format

Unchanged. A per-project voice override like `voice: picard-voxcpm` naturally routes through VoxCPM because the voice profile says so. No new `backend:` field needed.

## Error handling

| Situation | Handling |
|---|---|
| Voice name not in registry | 404 `{"error": "unknown voice: ...", "available": [...]}` (unchanged) |
| Voice profile references unregistered backend | Logged at startup, profile skipped. Voice not in `/voices` list. If referenced later (e.g., file added at runtime without reload), 404 with hint. |
| Backend `.load()` fails (weights download, OOM, etc.) | Fatal at startup. Logged with traceback; server exits non-zero. No half-loaded state. |
| Backend `.synthesize()` raises | Caught in `_synthesize_audio`, 500 `{"error": "synthesis failed"}` (same as today). Traceback logged. |
| Client passes unknown `extras` key for a backend | Backend's `synthesize()` raises `ValueError`; server returns 400. |
| `--all-backends` hits a backend that can't handle the reference | Log warning, skip that JSON output, continue with the rest. Don't fail the whole clone. |

## Testing

### `tests/test_backends.py`

- **Protocol conformance** — for each registered backend, `assert isinstance(b, Backend)` (works because `Backend` is `@runtime_checkable`). Assert `b.name`, `b.sample_rate`, `b.needs_ref_text` are populated with the expected types.
- **Registry uniqueness** — registering the same backend name twice raises `ValueError`.
- **Registry lookup** — `get("bogus")` raises `KeyError` with the available list in the message.
- **No model load in unit tests.** Backends' `.load()` and `.synthesize()` are NOT called. A separate opt-in `tests/test_backends_integration.py` marked `@pytest.mark.integration` can load models for manual runs — not part of default `pytest`.

### `tests/test_voice_profiles.py`

- Profile with `backend` field → parsed correctly.
- Profile without `backend` field → defaults to `qwen3-0.6b`.
- Profile with unknown backend → logged + skipped, not loaded into `VOICES`.
- Profile with `synthesis_extras` → round-trips to `VoiceProfile.extras`.

### `tests/test_server.py` extensions

- `/health` now contains `backends` dict.
- `GET /synthesize` with a voice whose backend isn't loaded → 503 with a clear message (this matches existing "warming up" behaviour).
- Legacy `/health` fields (`model`, `backend`) still present for back-compat.

### Manual / audible acceptance

- Re-clone three flagship voices (`picard`, `galadriel`, `attenborough`) onto all four backends.
- Demo site page gains a "Backend comparison" section playing the same line across the four renditions.
- Subjective listening: does VoxCPM 1.5 at 48 kHz sound better than Qwen3-0.6B? Does Chatterbox capture expressive nuance the others miss? Document findings in a follow-up PR, not this one.

## Acceptance criteria

1. `pytest` passes; `test_backends.py` and `test_voice_profiles.py` are new and green.
2. `GET /health` returns the new `backends` block; legacy fields still present.
3. `GET /synthesize?voice=picard` returns audio from Qwen3-0.6B (default backend for the existing profile).
4. A manually-added `voices/test-chatterbox.json` with `"backend": "chatterbox"` is loaded on restart and `GET /synthesize?voice=test-chatterbox` returns Chatterbox-synthesised audio.
5. `bash clone-voice.sh <url> testvoice 30 --backend voxcpm-1.5` produces `voices/testvoice.json` with `"backend": "voxcpm-1.5"` and a 48 kHz `testvoice-ref.wav`.
6. `bash clone-voice.sh <url> testvoice 30 --all-backends` produces four JSON profiles.
7. `afterwords status` shows per-backend load state.
8. `CLAUDE.md` is updated: the "6 GB peak, no room for concurrent models" note is replaced with a multi-backend paragraph, and the architecture section reflects the registry.
9. A short listening test comparing Picard across the four backends is linked from the demo site.

## Open questions / follow-ups (not blocking v1)

- **VoxCPM voice design.** VoxCPM can generate voices from text descriptions with no reference. That's a different UX (no voice profile, maybe no file at all). Deferred — own spec.
- **VoxCPM style prompts at request time.** Currently extras live in the voice profile. A future `GET /synthesize?voice=picard&style=cheerful` would let callers steer emotion per-request. Deferred.
- **Multilingual.** VoxCPM supports 30 languages; Qwen3 supports 10+; Chatterbox is EN-only. We currently hard-code `lang_code="en"` in the Qwen3 invocation. A `lang` parameter on `/synthesize` is a follow-up.
- **Hot-reload of voices.** Currently voices are read at startup. A `POST /reload` admin endpoint could let the cloning flow add voices without restart. Not blocking.
- **Migrating existing voices to Qwen3-1.7B.** Re-cloning 18 voices takes time. Do we migrate everything, or leave existing voices on 0.6B and only put new/flagship work on 1.7B? Design allows either — decision deferred to the migration PR.
