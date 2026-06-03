# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Afterwords is a local voice-cloning TTS server on Apple Silicon. The recommended cloning path is MLX-based **Qwen3-TTS 0.6B** (default); 1.7B loads via `--with-1.7b` for higher-fidelity clones. Additional backends (Voxtral, OpenVoice, F5-TTS, etc.) are available but not endorsed for cloning fidelity. The server is a standalone HTTP API usable from any tool. When Claude Code is installed, a Stop hook automatically speaks every response.

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

# Run the optional MFCC cloning-fidelity test (skipped if the server is up,
# since it loads ~10 GB of Metal models in its own process):
afterwords stop
pip install -r requirements-dev.txt  # includes librosa
pytest -m integration tests/test_fidelity.py
afterwords start

# If pytest fails with "bad interpreter" after brew upgrade, recreate the venv:
bash setup.sh --server-only
```

Verify changes with `pytest` (no GPU required). Run a single test with `pytest tests/test_server.py::test_health_returns_ok`.

**Note:** Homebrew Python minor-version upgrades (e.g. 3.14.3 → 3.14.4) break the `.venv` symlink. If you see `bad interpreter: .venv/bin/python3.14: no such file or directory`, run `bash setup.sh --server-only` to recreate the venv.

## Architecture

The server (server.py) and voice cloning (clone-voice.sh) are fully independent of Claude Code. The Claude Code integration is an optional layer installed by setup.sh when Claude Code is detected. Six agent integrations share the same queue and play-lock infrastructure.

1. **server.py** — FastAPI/Uvicorn TTS server on `localhost:7860`. Preloads cloning backends via `backends.register_all()` at startup, serializes all synthesis through `_synth_lock` (MLX Metal is not thread-safe across backends). Voice profiles pin to a backend via the `backend` JSON field; dispatch is `backend = backends.get(profile.backend); backend.synthesize(text, profile.prepared, lang)`. Voices are auto-discovered JSON profiles from `voices/`. Endpoints: `GET /health` (always available; exposes `loaded_backends[*].supported_langs`), `GET /synthesize?text=...&voice=...&lang=en` (always), and four endpoints gated by `--allow-clone`: `POST /synthesize` (JSON body with optional `emotion` + `lang`), `POST /clone` (multipart audio upload), `POST /reload` (rescan `voices/*.json`, atomic add-only — see Hot-reload), `DELETE /session/{id}` (remove cloned-session voices + temp files). Lifespan context manager handles shutdown cleanup.

2. **Claude Code hooks** (`~/.claude/hooks/`, optional) — `tts-hook.sh` fires on Stop events, extracts response text, passes through `strip-markdown.py`, and writes a JSON item atomically to `/tmp/claude-tts-queue/` (per-file queue; atomic `tmp+mv` eliminates the race window of a flat-file queue). `tts-worker.sh` claims items one at a time via `mv *.json → *.claimed`, resolves voice from `.afterwords` (using `AGENT`), splits into ~200-char sentence chunks, pipelines synthesis+playback (synth N+1 while playing N via `afplay`), archives as MP3 to `~/.claude/tts-archive/`. Only installed when Claude Code is present.

3. **Codex CLI watcher** (`.claude/hooks/codex-tts-watch.sh`, repo-local) — Codex has no Stop-hook API, so `afterwords codex-hook start` runs a detached watcher for the current `$CODEX_THREAD_ID`. It polls the matching `~/.codex/sessions/.../rollout-*.jsonl`, extracts final assistant messages, queues JSON items under `/tmp/codex-tts-queue-$CODEX_THREAD_ID/`, and `codex-tts-worker.sh` synthesizes through `localhost:7860`, plays via `afplay`, and archives under `~/.codex/tts-archive/`. Uses `codex` as the agent key. Start from a real interactive terminal; API-hosted/non-interactive sessions may reap long-lived background processes.

4. **AGy (Antigravity CLI) hook** (`~/.claude/hooks/agy-tts-hook.sh`, optional) — registered in `~/.gemini/config/hooks.json` under `"afterwords-tts"`. Fires on `Stop` events with a JSON payload containing `transcriptPath`. Uses `agy-session-hook.py` to parse the transcript backwards for the final model response text, then queues it for synthesis. Uses `agy` as the agent key.

5. **Gemini CLI hook** (`~/.claude/hooks/gemini-tts-hook.sh`, optional) — Gemini's `AfterAgent` payload uses `.prompt_response` rather than `.last_assistant_message`; this adapter normalises it and re-emits in Claude queue format so `tts-worker.sh` drains both sources without modification. Wire-up: reference it from `~/.gemini/settings.json`. Uses `gemini` as the agent key.

6. **Cursor IDE hook** (`~/.claude/hooks/cursor-tts-hook.sh`, optional) — fires on Cursor 1.7+'s `afterAgentResponse` event. Wire-up: copy to `~/.claude/hooks/` and add to `~/.cursor/hooks.json`:
   ```json
   {"version":1,"hooks":{"afterAgentResponse":[{"command":"bash ~/.claude/hooks/cursor-tts-hook.sh","type":"command","timeout":10,"failClosed":false}]}}
   ```
   Uses `cursor` as the agent key. `bash setup.sh` installs it automatically when Cursor is detected.

7. **Hermes Agent TTS** (`~/.hermes/hooks/afterwords-tts/` + `scripts/`) — Three-path integration; none is auto-configured by setup.sh. (a) Shell hook (`afterwords-post-llm.sh`) fires on `post_llm_call`, strips markdown, pipelines synthesis+playback. (b) Native Python hook (`handler.py`) fires on `agent:end`, async chunked pipeline via `aiohttp`, archives MP3+txt to `~/.hermes/tts-archive/`; only speaks on CLI/local platforms. Play lock fix: `_pid_alive()` uses `try/except` around `os.kill(pid, 0)` — `os.kill` returns `None` on success, never test the return value directly. (c) Command provider (`afterwords-tts-command.sh`): on CLI writes a silent placeholder WAV immediately (non-blocking) then synthesizes in a detached subshell; on messaging platforms runs synchronously for audio attachment delivery.

8. **Voice profiles** (`voices/`) — Each voice is a `{name}-ref.wav` (15s reference clip, ~700KB) + `{name}.json` (metadata with transcript). Created by `clone-voice.sh` which downloads from YouTube, extracts a segment, denoises with noisereduce, and transcribes with faster-whisper.

**Splicing references for difficult voices:** When no single 15s window contains a clean solo vocal (background music, multiple speakers, crowd noise), the correct approach is: (1) download the full clip as WAV, (2) run faster-whisper across the whole file to get timestamped segments, (3) use a spectral mid/high-ratio heuristic to flag music-contaminated windows (ratio < ~4.0 indicates music), (4) extract only the clean solo-speaker windows, apply noisereduce per chunk, add 30ms fades, concatenate with 150ms silence gaps, (5) write the spliced WAV directly to `voices/{name}-ref.wav`, (6) set `reference_text` to only the words in the spliced audio. The `segment_start_s` field in the JSON should reflect the earliest source segment used.

9. **Claude Code skill** (`skill/`) — A SKILL.md that enables natural-language TTS commands ("say this in picard's voice", "list voices", "set project voice"). Includes `scripts/speak.sh` helper for synthesis + playback.

**Play lock convention:** All six agent integrations (Claude Code, Codex, AGy, Gemini CLI, Cursor, Hermes) share `/tmp/afterwords-play.lock` (mkdir for atomicity) and `/tmp/afterwords-play.pid` (a separate PID file, not inside the lock dir). Each worker acquires the lock before playing audio and releases after. Stale lock detection: if the PID file is empty (TOCTOU window between mkdir and PID write), implementations do a 50ms recheck before clearing. The PID file must be at `/tmp/afterwords-play.pid`, NOT inside the lock directory. To clear a stuck lock: `rm -rf /tmp/afterwords-play.lock /tmp/afterwords-play.pid`.

**Per-project voice override:** A `.afterwords` file in any repo root sets the voice for that project. Two formats: a bare voice name (legacy), or an agent-to-voice mapping (`key: voice-name`, one per line) with `default:` as fallback. Supported agent keys:

| Key | Integration |
|-----|-------------|
| `default` | Fallback for all agents |
| subagent type (e.g. `feature-dev:code-architect`) | Claude Code — reads `agent_type` from Stop event; built-in types (Explore, Plan, general-purpose) are silently skipped |
| `codex` | Codex CLI watcher |
| `agy` | Antigravity CLI |
| `gemini` | Gemini CLI |
| `cursor` | Cursor IDE |
| `hermes` | Hermes Agent (also checks global `~/.afterwords`) |

Each hook falls back to `~/.afterwords` (global) before using the server's default voice.

## Backends

The `backends/` package exposes a `Backend` Protocol (in `backends/base.py`) and a registry (`backends/__init__.py`). Each backend is a single Python file implementing `load / validate_extras / prepare_voice / synthesize`. Registered shipped backends:

| Name | Size | Sample rate | ref_text policy |
|------|------|-------------|-----------------|
| `qwen3-0.6b` | 0.6B | 24 kHz | REQUIRED |
| `qwen3-1.7b` | 1.7B | 24 kHz | REQUIRED |

These two are the **recommended cloning path**. The registry also exposes 15 other backends (voxtral, openvoice-v2, f5-tts, cosyvoice2, gpt-sovits, xtts-v2, indextts-2, neutts-air, spark-tts, dia2, yourtts, firered-tts-2, sv2tts, mockingbird, soprotts) for experimentation, but listen-tests (2026-05-16, Sprint 1) confirmed Qwen3 as the only backend that produces clones consistently recognizable on the flagship voices. Chatterbox + VoxCPM were removed entirely in commit f03e826 — they failed the listen-test, and VoxCPM additionally returned HTTP 500 on the launchd-managed server.

Each backend has a `supported_langs: tuple[str, ...]` advertising what BCP-47 codes it accepts. Backend.synthesize takes a required `lang: str` parameter and raises `ValueError` for unsupported codes — server maps that to HTTP 400 with `voice_backend` + `supported_langs` in the body.

Adding a backend: create `backends/newmodel.py` implementing the Backend protocol, then add one line to `register_all()` in `backends/__init__.py`. The registry CLI (`python -m backends list | max-sample-rate | slug <name>`) is used by `clone-voice.sh` to stay backend-aware.

## Voice-family routing

Voice profiles can declare an optional `family: str` field (e.g. `"family": "picard"` on `picard.json`, `picard-qwen3-17b.json`, etc.). When a caller asks for a lang the voice's backend doesn't support, the server auto-routes to a same-family voice on a backend that does. The lookup runs under `_model_lock` to avoid racing with `/reload` Phase 3. Tiebreaker is `(duration_s or 0, confidence or 0, name)` for deterministic selection across `/reload` cycles. Voices with `family=None` (most gallery voices, all session-cloned voices) are never routed and never used as routing targets.

## Hot-reload

`POST /reload` (gated by `--allow-clone`) re-walks `voices/*.json` in three phases:
1. Build new VoiceProfile per JSON on the dedicated MLX thread (`_run_in_ml_thread`, a single-worker executor) so `prepare_voice` Metal ops are serialized with in-flight synthesis without holding `_synth_lock` and blocking unrelated work. Track every profile's cleanup_paths + owns_temp_audio for rollback.
2. **Atomic abort** — if any prepare_voice raises, delete every tracked temp file and return 500 with errors[]. VOICES is unchanged.
3. **Add-only commit** under `_model_lock`: `VOICES[name] = profile` for each successful build. Voices whose JSON disappeared from disk are NOT removed (use `DELETE /session/{id}` or restart).

`POST /reload?prune=true` (CLI: `afterwords reload --prune`) additionally evicts
**gallery voices whose JSON has been deleted from disk**. Prune is scoped to
file-originated voices — a voice is prunable iff `VoiceProfile.session_id is None`
(every git-tracked gallery JSON omits `session_id`; `/clone` always sets it).
Session-cloned voices are never pruned; remove them with `DELETE /session/{id}`.
The keep-set is the names of JSON files present on disk this reload, so a
present-but-unbuildable JSON keeps its voice. The response includes `removed[]`.
Default (`prune=false`) is unchanged add-only behavior.

CLI: `afterwords reload` curls the endpoint and pretty-prints the response.

## Key Constraints

- Qwen3 0.6B preloads at boot by default (~1.5 GB). Pass `--with-1.7b` to server.py to also load 1.7B (~3.5 GB total). Additional backends also preload if their deps are installed. Designed for 32 GB unified memory; 16 GB works for the default 0.6B-only path.
- All synthesis is serialized through `_synth_lock` — MLX Metal is single-GPU, regardless of backend
- Voice reference files (`.wav`) and profiles (`.json`) are tracked in git — shipped with the repo for the demo site and default server voices
- `setup.sh` conditionally installs hooks into `~/.claude/` (only when Claude Code is present) and a launchd plist (always)
- `afterwords.sh` is a pure-bash CLI wrapper (no venv needed) symlinked to `/usr/local/bin/afterwords` by setup.sh — handles start/stop/restart/status/logs/voices/clone/uninstall
- Shell scripts use macOS-specific tools throughout (afplay, mkdir-based locking, launchd)
