# AGENTS.md

This file provides guidance to Codex CLI and other AI coding agents when working with code in this repository.

## Project Overview

Afterwords is a local voice-cloning TTS server on Apple Silicon. The recommended cloning path is MLX-based **Qwen3-TTS** at two sizes (0.6B + 1.7B); other registered backends are available for experimentation but not endorsed for cloning fidelity. The server is a standalone HTTP API usable from any tool. When Claude Code is installed, a Stop hook automatically speaks every response.

**Platform:** Apple Silicon Mac only (M1+), 16 GB+ RAM (32 GB recommended), Python 3.11+, macOS (uses launchd, afplay).

## Commands

```bash
# Setup — full (detects/offers Claude Code)
bash setup.sh

# Setup — server only, no Claude Code hooks
bash setup.sh --server-only

# Server management (CLI — symlinked to PATH by setup.sh)
afterwords start       # start via launchd
afterwords stop        # stop server
afterwords restart     # restart
afterwords status      # health, PID, loaded voices
afterwords logs        # tail server log
afterwords voices      # list voices (--demo to play samples)
afterwords clone       # clone a voice from YouTube
afterwords uninstall   # remove service + optionally hooks

# Run server manually (without launchd)
source .venv/bin/activate
python server.py [--port 7860]

# Clone a new voice (standalone, or via CLI above)
bash clone-voice.sh
bash clone-voice.sh "https://youtube.com/watch?v=..." voicename 30

# Test endpoints
curl localhost:7860/health
curl "localhost:7860/synthesize?text=Hello&voice=galadriel" -o test.wav

# Run tests (no GPU required)
pip install -r requirements-dev.txt
pytest

# Run a single test
pytest tests/test_server.py::test_health_returns_ok

# Reload voices without restarting (after editing voices/*.json or running clone-voice.sh)
afterwords reload
```

Verify changes with `pytest` (no GPU required).

## Architecture

The server (server.py) and voice cloning (clone-voice.sh) are fully independent of Claude Code. The Claude Code integration is an optional layer installed by setup.sh when Claude Code is detected.

1. **server.py** — FastAPI/Uvicorn TTS server on `localhost:7860`. Preloads cloning backends via `backends.register_all()` at startup, serializes all synthesis through `_synth_lock` (MLX Metal is not thread-safe across backends). Voice profiles pin to a backend via the `backend` JSON field; dispatch is `backend = backends.get(profile.backend); backend.synthesize(text, profile.prepared, lang)`. Voices are auto-discovered JSON profiles from `voices/`. Endpoints: `GET /health` (always; exposes `loaded_backends[*].supported_langs`), `GET /synthesize?text=...&voice=...&lang=en` (always), and `--allow-clone`-gated: `POST /synthesize` (JSON body), `POST /clone` (multipart upload), `POST /reload` (atomic add-only rescan), `DELETE /session/{id}`. Lang validation is per-backend; an unsupported lang raises `ValueError` mapped to HTTP 400 with `voice_backend` and `supported_langs`. Voice profiles can declare an optional `family` field; if a voice's backend doesn't support the requested lang, server auto-routes to a same-family voice on a backend that does (lookup under `_model_lock`). Lock-acquisition order is invariant: `_synth_lock` → `_model_lock`.

2. **Claude Code hooks** (`~/.claude/hooks/`, optional) — `tts-hook.sh` fires on Stop events, extracts response text, passes through `strip-markdown.py`, chunks via `chunk-text.py` (~2-sentence pieces), and appends tab-separated `CWD<TAB>AGENT<TAB>TEXT` lines to the queue. `tts-worker.sh` processes the queue (max 10 items) with `mkdir`-based locking (no `flock` on macOS), resolves the voice per chunk from `.afterwords` (using `AGENT`), plays WAV via `afplay`, archives as MP3. Only installed when Claude Code is present.

3. **Voice profiles** (`voices/`) — Each voice is a `{name}-ref.wav` (15s reference clip, ~700KB) + `{name}.json` (metadata with transcript). Created by `clone-voice.sh` which downloads from YouTube, extracts a segment, denoises with noisereduce, and transcribes with faster-whisper.

4. **Claude Code skill** (`skill/`) — A SKILL.md that enables natural-language TTS commands ("say this in picard's voice", "list voices", "set project voice"). Includes `scripts/speak.sh` helper for synthesis + playback.

**Per-project voice override:** A `.afterwords` file in any repo root sets the voice for that project (read by the hook before each synthesis). Supports two formats: a single voice name (legacy), or an agent-to-voice mapping (`agent-name: voice-name`, one per line, with `default:` as fallback). The hook reads `agent_type` from the Stop event payload to resolve per-agent voices. Built-in subagent types (Explore, Plan, general-purpose) are silently skipped.

## Backends

Registry at `backends/__init__.py`; one Python file per backend implementing the `Backend` protocol (`load / validate_extras / prepare_voice / synthesize`).

| Name | Size | Sample rate | ref_text policy |
|------|------|-------------|-----------------|
| `qwen3-0.6b` | 0.6B | 24 kHz | REQUIRED |
| `qwen3-1.7b` | 1.7B | 24 kHz | REQUIRED |

Cloning fidelity (verified 2026-05-16 listen-test): Qwen3 0.6B and 1.7B are the only endorsed cloning path. Chatterbox + VoxCPM failed listen-tests and were removed in commit f03e826. The registry still exposes 15 other backends for experimentation (voxtral, openvoice-v2, f5-tts, cosyvoice2, gpt-sovits, xtts-v2, indextts-2, neutts-air, spark-tts, dia2, yourtts, firered-tts-2, sv2tts, mockingbird, soprotts); consult the README backend-status table for current verification state.

## Key Constraints

- Qwen3 0.6B + 1.7B preload at boot (~3-4 GB total). Other registered backends also preload if their deps are installed. Designed for 32 GB unified memory; 16 GB works for the qwen3-only path.
- All synthesis is serialized through `_synth_lock` — MLX Metal is single-GPU, regardless of backend
- Voice reference files (`.wav`) and profiles (`.json`) are tracked in git — shipped with the repo for the demo site and default server voices
- `setup.sh` conditionally installs hooks into `~/.claude/` (only when Claude Code is present) and a launchd plist (always)
- `afterwords.sh` is a pure-bash CLI wrapper (no venv needed) symlinked to `/usr/local/bin/afterwords` by setup.sh — handles start/stop/restart/status/logs/voices/clone/uninstall
- Shell scripts use macOS-specific tools throughout (afplay, mkdir-based locking, launchd)
