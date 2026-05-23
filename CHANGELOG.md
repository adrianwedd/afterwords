# Changelog

All notable changes to Afterwords. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **lisa-simpson** voice family (commit `d18aca4`). Source: *Lisa the Skeptic*, Yeardley Smith, segment_start_s=42. Ships as the canonical trio (base + `qwen3-0.6b` + `qwen3-1.7b` siblings) sharing one reference WAV under `family: "lisa-simpson"`. Brings the gallery to **98 families / 294 profiles**.
- Demo gallery card for lisa-simpson on the [Pages site](https://adrianwedd.github.io/afterwords/) (`docs/audio/lisa-simpson.mp3`).
- **Parametrized schema validator** for every shipped `voices/*.json` (commit `b2cee38`). Checks required fields, that `reference_audio` resolves on disk, that the `backend` slug is registered, and that `reference_text` is non-empty for REQUIRED-policy backends. A malformed voice JSON now fails CI with a precise file-specific test ID.
- **Family-routing tiebreaker tests** pinning the documented `(duration_s, confidence, name)` ordering across `/reload` cycles. Two tests cover the higher-duration and equal-duration-higher-confidence branches.
- **Concurrency smoke test:** 6 workers × 18 requests against `FakeBackend`, asserting `_synth_lock` serialization holds and no synthesis leaks across requests.

### Changed

- Test suite grew from 186 to **491 unit + contract tests** (still no GPU required), driven by the schema validator + new regression guards.

### Security

- **Default bind to 127.0.0.1** (commit `0dba278`). `server.py` now defaults `--host` to loopback; the launchd-managed server is no longer reachable from other machines on the LAN by accident. `--allow-clone` continues to enforce its existing 127.0.0.1 rewrite as belt-and-braces.
- **`DELETE /session/{id}` input validation** — same `^[a-zA-Z0-9_-]{1,64}$` regex as `POST /clone`. Closes an asymmetry where a voice JSON that had gained a `session_id` field could be HTTP-deletable.
- **Backend-import isolation** — `register_all` now wraps each experimental backend's import + register in its own try/except. The primary Qwen3 path still fails loud; one broken experimental backend can no longer crash boot.
- **Hook regex hardening** — `setup.sh` and `.claude/hooks/codex-tts-worker.sh` now use `awk` exact-field comparison instead of `grep "^${AGENT}:"`, so an `AGENT` value cannot be interpreted as a regex.

### Fixed

- **Qwen3 long-input truncation** (commit `0dba278`) — `backends/qwen3.py::synthesize` now concatenates *all* sorted `out_*.wav` segments instead of only `wavs[0]`. Long inputs were being silently truncated to the first segment.
- **Qwen3 unavailability hint** — `load()` catches `ImportError`, sets `_unavailable_reason`, and logs at ERROR level with the brew-upgrade/venv-rebuild guidance from CLAUDE.md so the cause shows up directly in `afterwords logs`.
- **XTTS v2 + F5-TTS TOCTOU** — `prepare_voice` now buffers the reference audio bytes when possible; `synthesize` writes a tempfile from those bytes if available, falling back to the path otherwise. Closes the same DELETE-during-synthesis race that qwen3 already handled.

### Docs

- Reconciled voice counts, hook-chain references, and the Phase 1 lock-acquisition claim in the Hot-reload section (commit `f9db36c`).

## [1.0.0] — 2026-05-16

First tagged release. Local voice-cloning TTS server on Apple Silicon, with **Qwen3-TTS** as the recommended cloning path. Hot-reload, multi-language synthesis, optional Claude Code integration.

### Cloning backends (recommended path)

- Qwen3-TTS 0.6B (24 kHz, REQUIRED ref_text, multilingual: en/zh/ja/ko/es/fr/de/it/pt/ru)
- Qwen3-TTS 1.7B (24 kHz, REQUIRED ref_text, multilingual)

Sprint 1 listen-test (2026-05-16, three flagship voices: galadriel, picard, attenborough) confirmed Qwen3 as the only backend that produces clones consistently recognizable on the reference voices.

### Backend registry

The server's backend registry exposes 17 backends in total. Beyond the two recommended Qwen3 sizes:

- **Verified alternatives:** `voxtral` (preset voices), `soprotts` (English CPU-friendly Apache-2.0)
- **Scaffolded:** `openvoice-v2`, `f5-tts`, `cosyvoice2`, `gpt-sovits`, `xtts-v2`, `indextts-2`, `neutts-air`, `spark-tts`, `dia2`, `yourtts`, `firered-tts-2`, `sv2tts`, `mockingbird`. Code present and protocol-compliant; install paths on Apple Silicon vary.

### Removed (Sprint 1)

- `chatterbox` (Resemble AI fp16 multilingual)
- `voxcpm-1.5` (ModelBest 44.1 kHz)

Both failed Sprint 1 listen-tests on the flagship voices. VoxCPM additionally returned HTTP 500 on the launchd-managed server. Removed in commit `f03e826`. The chatterbox `lang_code` + `cfg_weight=0.7` fix (commit `6d9a412`) and the VoxCPM `ref_audio` kwarg fix (PR #16) shipped during development but did not produce listen-grade cloning fidelity.

### Server

- FastAPI + Uvicorn on `localhost:7860`. All synthesis serialized through `_synth_lock` — MLX Metal is single-GPU.
- Endpoints: `GET /health`, `GET /synthesize` (always); `POST /synthesize`, `POST /clone`, `POST /reload`, `DELETE /session/{id}` (gated by `--allow-clone`).
- **Voice-family routing:** profiles can declare `family: <stem>`; if a voice's backend doesn't support the requested lang, the server auto-routes to a same-family voice on a backend that does. Routing lookup under `_model_lock`.
- **Hot-reload:** `POST /reload` re-walks `voices/*.json` in three phases (build under `_synth_lock`, atomic abort on `prepare_voice` failure with full rollback of owned temp files, add-only commit under `_model_lock`). Add-only: a JSON deleted from disk does not evict its loaded profile — use `DELETE /session/{id}` or restart.

### Security

- realpath + dangerous-prefix check on all external-repo backends (gpt_sovits, spark_tts, mockingbird, sv2tts) — commit `c842fec`.
- Path-traversal and TOCTOU race fixes on `/clone` and synthesis (commits `dd7acd1`, `5289576`).
- Pinned `git+` source dependencies to specific HEAD SHAs to harden supply chain (commit `b6b365f`).
- `tests/test_backends.py::TestResolveRepoDir` — 8 security tests covering the realpath + expanduser path.

### Tests

- 186 unit + contract tests (no GPU required), runnable on CI without MLX.
- `tests/test_fidelity.py` — opt-in MFCC cloning-fidelity regression test (issue #70). 6 parametrized cases covering the three flagship voices on both Qwen3 sizes. Skipped on CI; skipped locally if the launchd server is running on `:7860`. Run with `afterwords stop && pytest -m integration tests/test_fidelity.py`. Multi-agent QA (Hermes/Gemini/Codex) drove the test's design — initial version had three critical DSP bugs that were fixed before merge.

### Claude Code integration (optional, installed by `setup.sh` when Claude Code is detected)

- Stop hook (`~/.claude/hooks/tts-hook.sh`) speaks every assistant response via the local server.
- Per-project `.afterwords` voice override with optional per-agent mapping.
- Claude Code skill at `skill/SKILL.md` for natural-language TTS commands.

### Tooling

- `afterwords` CLI (start/stop/restart/status/logs/voices/clone/reload/uninstall), symlinked to `/usr/local/bin` by `setup.sh`.
- launchd-managed service plist.
- `clone-voice.sh` YouTube-sourced zero-shot voice cloning.

### Voice references

97 unique flagship voice families included, each with `{name}-ref.wav` (~15s) + `{name}.json` (metadata + transcript). Four voices (clara-oswald, gulley, loki, the-doctor) are scoped to v1.0.0 with deferred trim-threshold tuning per Phase 4 backlog (annotated in `04b7215`, marker keyword normalized to `WONTFIX` in `e35c434`).

### Platform

Apple Silicon Mac only (M1+), 16 GB RAM minimum (32 GB recommended for full backend registry), Python 3.11+, macOS (uses launchd, afplay).
