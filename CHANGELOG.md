# Changelog

All notable changes to Afterwords. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

90+ flagship voice families included, each with `{name}-ref.wav` (~15s) + `{name}.json` (metadata + transcript). Four voices (clara-oswald, gulley, loki, the-doctor) are scoped to v1.0.0 with deferred trim-threshold tuning per Phase 4 backlog (commit `04b7215`).

### Platform

Apple Silicon Mac only (M1+), 16 GB RAM minimum (32 GB recommended for full backend registry), Python 3.11+, macOS (uses launchd, afplay).
