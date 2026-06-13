# Changelog

All notable changes to Afterwords. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.5] — 2026-06-13

Sprint 6 — CLI expansion from a server-management tool into a voice-curation workbench.

### Added

- **Analysis subcommands** — `afterwords transcribe`, `qa`, `trim`, and `compare`: thin bash passthroughs to the QA scripts, all now emitting `--json`, meaningful exit codes, and TTY-gated colour markers.
- **`afterwords refine`** — 4-step QA pipeline (qa → compare → trim → qa) that chains the analysis scripts through their stable exit codes.
- **Auto-refine after clone** — `clone-voice.sh` runs `refine` automatically on success; `--quick` keeps the fast path.
- **`afterwords update`** — self-update via `git pull` (warns instead of silently ignoring a pip failure; `--check` dry-run makes no working-tree, package, or server changes).
- **`afterwords mute`** — toggle playback on/off without stopping synthesis.
- **`afterwords audit --archive`** — pair-audit the `tts-archive` (text/audio) alongside the voice gallery.
- **`--ai` flag + `docs/ai-guide.md`** — machine-readable guidance for agent-driven workflows.
- **Local-file clone** — `clone-voice.sh` accepts a local audio file, with flag-filtered positionals and `source_basename` recorded in the voice JSON.
- **Help redesign** — `afterwords` help reorganised into six sections, including a new Analysis group.
- **Acceptance-criteria tests** — `tests/test_cli_expansion.py` and `tests/test_script_polish.py`.

### Changed

- **`qa-voices.py`, `trim-silence-gaps.py`, `compare-transcription.py`** gained `--json` output, exit codes, and TTY markers so `refine` can consume them as stable contracts.
- **Maintainer-internal scripts moved to `scripts/internal/`** (CI workflow and references updated).

### Fixed

- **5 UX issues** flagged in external CLI review.
- **Honest `[y/N]` prompt label** for the destructive trim step in `refine`.

## [1.0.4] — 2026-06-04

### Added

- **`afterwords configure`** — new subcommand to toggle the Qwen3-1.7B model for the launchd service without editing plists by hand. `afterwords configure --with-1.7b` writes `~/.afterwords-server`, regenerates the plist, and reloads launchd; `--no-1.7b` reverts. `afterwords status` shows `1.7B: enabled` when set. `bash setup.sh` picks up the config on reinstall.
- **Cursor IDE hook** — `~/.claude/hooks/cursor-tts-hook.sh` auto-configured by `setup.sh` when Cursor 1.7+ is detected. Fires on `afterAgentResponse` events; uses `cursor` as the agent key for `.afterwords` voice overrides.
- **Red Dwarf gallery** — 5 new voice families (Arnold Rimmer, Dave Lister, The Cat, Holly, Kryten) cloned from in-character BBC monologues. Brings the gallery to **103 families / 284 profiles**.
- **`requirements-clone.txt`** — cloning-only dependencies (`faster-whisper`, `noisereduce`) split out of `requirements.txt`. `setup.sh --server-only` installs the server-only subset; `clone-voice.sh` checks for the clone deps and prints a helpful message if missing.

### Changed

- **holly reclone** — new reference from the April Fool clip (pure solo speech, no crowd noise). Higher fidelity than the previous source.
- **Architecture docs expanded** — `docs/architecture/` now covers all six agent integrations (Claude Code, Codex, AGy, Gemini CLI, Cursor, Hermes) and harness details for each. Previously covered only three.

### Fixed

- **tegan-jovanka synthesis garble** — reference clip now splices only clean solo-speech windows (spectral heuristic + noisereduce per chunk), eliminating the music bleed that caused Qwen3 to hallucinate phonemes.
- **OG metadata voice count** — `og:description` and README updated from 275 → 284 after the Red Dwarf addition.

## [1.0.3] — 2026-05-30

### Added

- **Opt-in prune for `POST /reload`** (`afterwords reload --prune`). Evicts
  gallery voices whose JSON has been deleted from disk, freeing their prepared
  temp artifacts. Scoped to file-originated voices (`session_id is None`);
  session-cloned voices are never pruned (use `DELETE /session/{id}`). The reload
  response gains a `removed[]` field. Default (`prune=false`) is unchanged
  add-only behavior. New tests cover removal, session exemption, temp freeing,
  on-disk-keep precision, atomic abort, and lang-routing exclusion.

### Removed

- **`inspector-morse` and `francis-urquhart` voices** — sub-threshold references
  (RMS 0.0404 / 0.0536) the project chose not to reclone. Gallery is now
  **98 families / 275 profiles**.

### Fixed

- **Duplicate voice assignment** — `ronan` was the default voice in two unrelated
  repos (`evolve-evolution` and `adrianwedd-ops`); `adrianwedd-ops` reassigned to
  a unique voice (`mckenna`).

## [1.0.2] — 2026-05-30

### Added

- **Redesigned GitHub Pages homepage** (Surface 1, commit `126a329`) — rebuilt `docs/index.html`, added a styled `docs/404.html`, local-themed favicons, and an OpenGraph preview image. The OG-metadata drift guard (`scripts/check-og-metadata.py`) keeps the advertised voice count in sync with the shipped gallery.
- **mckenna** and **dalai-lama** voices (commit `cfb5ecf`). Each ships as a single `qwen3-1.7b` profile with its own reference WAV. Brings the gallery to **100 families / 281 profiles**.
- **Opt-in external TTS delivery** — `scripts/tts-feed-send.py` is now the sole owner of outbound/CLI audio delivery from the archive, gated behind a `send_to:` directive in `.afterwords` (or the `AFTERWORDS_SEND_TO` env var). Accepts only `telegram` / `discord`; absent the opt-in, nothing leaves the machine. (commits `a9d19e1`, `278fee8`)
- **Tests for `tts-feed-send.py`** — `tests/test_tts_feed_send.py` (15 tests): chunk-stem parsing, seen-state round-trip, dry-run sends nothing, full `send_to` resolver matrix. Suite now **522** unit + contract tests.

### Changed

- **Single-owner messaging delivery, split by direction** — inbound/gateway replies are sent inline by the hook to the *originating* chat (`hermes send -t <platform>:<chat_id>`); outbound/CLI responses are delivered from the archive by the feed watcher to the home channel. Replaces three overlapping send paths with one owner per direction. (commits `a9d19e1`, `278fee8`)
- `.gitignore` now ignores the `.wrangler/` and `.playwright-mcp/` tool caches (commit `28390f2`).

### Fixed

- **Duplicate / triple-send of the same audio** — the hook's inline send, the CLI tail, and the feed watcher could each deliver the same response. Now exactly one delivery per response per platform, enforced by a pre-seeded, atomically-written `tts-feed-seen.json` (read-merge-write so a marker added by the hook mid-pass survives the watcher's write). (commits `a9d19e1`, `278fee8`)
- **Wrong-recipient gateway replies** — the hook extracted `chat_id` but never used it, so inbound replies landed in the platform home channel instead of the originating chat. Now threaded through as `-t <platform>:<chat_id>`. (commit `a9d19e1`)
- **Voice-count drift** — og:description, README, and the demo-site claimed 296 voices; the shipped (git-tracked) gallery is **281** (15 private `muse*` / `vixen*` profiles are gitignored and not distributed). Corrected to 281. (commit `acac4c0`)

### Security

- **Egress requires explicit opt-in** — external chat delivery no longer fires on the mere presence of a `.afterwords` file (a local-playback config most repos carry); without a `send_to:` directive, zero external sends occur and local playback is unaffected. Closes the privacy gap raised in the messaging security review (`docs/security/2026-05-29-hermes-messaging-review.md`, reviewed clean — no HIGH/MEDIUM findings). Untrusted text remains URL-encoded before HTTP and slug-whitelisted before filesystem use; all `subprocess.run` calls stay list-form (no `shell=True`).

## [1.0.1] — 2026-05-23

### Added

- **lisa-simpson** voice family (commit `d18aca4`). Source: *Lisa the Skeptic*, Yeardley Smith, segment_start_s=42. Ships as the canonical trio (base + `qwen3-0.6b` + `qwen3-1.7b` siblings) sharing one reference WAV under `family: "lisa-simpson"`. Brings the gallery to **98 families / 294 profiles**.
- Demo gallery card for lisa-simpson on the [Pages site](https://adrianwedd.github.io/afterwords/) (`docs/audio/lisa-simpson.mp3`).
- **Parametrized schema validator** for every shipped `voices/*.json` (commit `b2cee38`). Checks required fields, that `reference_audio` resolves on disk, that the `backend` slug is registered, and that `reference_text` is non-empty for REQUIRED-policy backends. A malformed voice JSON now fails CI with a precise file-specific test ID.
- **Family-routing tiebreaker tests** pinning the documented `(duration_s, confidence, name)` ordering used by lang-routing selection. Two tests cover the higher-duration and equal-duration-higher-confidence branches.
- **Concurrency smoke test:** 6 workers × 18 requests against `FakeBackend`, asserting `_synth_lock` serialization holds and no synthesis leaks across requests.

### Changed

- Test suite grew from 186 to **491 unit + contract tests** (still no GPU required), driven by the schema validator + new regression guards.
- `.gitignore` now ignores `*.profraw` (LLVM coverage artefact from `default.profraw`).
- `requirements-dev.txt` pins `mlx-audio>=0.4,<0.4.1` on Darwin; `mlx-audio` 0.4.1+ regresses Qwen3-1.7B ICL.
- **Play-lock PID portability** (PR #76) — `afterwords-tts-command.sh` now uses `bash -c 'echo $PPID'` to write the background subshell PID (portable on macOS bash 3.2). Replaces the previous `$$`-based approach that wrote the parent shell PID and allowed a second agent to start audio before synthesis finished.
- **`mktemp` for temp WAVs** (PR #76) — `afterwords-tts-command.sh` uses `mktemp /tmp/afterwords-cmd-XXXXXX.wav` instead of the `$$`-suffixed path. Avoids collisions between concurrent agents.
- **Stale-lock 50ms recheck** (PR #76) — `afterwords-tts-command.sh` waits 50ms before clearing a lock whose PID file is empty, reducing the TOCTOU window between `mkdir` and PID write.
- **`eval` removed from Codex TTS worker** (PR #76) — `codex-tts-worker.sh` replaced `eval` on queue content with direct `python3` field extraction. Queue content can no longer be interpreted as shell code.
- **`--server-only` hook gate** (PR #76) — `setup.sh` now correctly skips the shared-hooks block, Gemini block, and AGy block when `--server-only` is passed.
- **`lsof` filtered to LISTEN sockets** (PR #75) — `afterwords.sh` `server_pid()` now passes `-s TCP:LISTEN` to `lsof`, preventing false positives from ESTABLISHED connections to the server port.

### Security

- **Default bind to 127.0.0.1** (commit `0dba278`). `server.py` now defaults `--host` to loopback; the launchd-managed server is no longer reachable from other machines on the LAN by accident. `--allow-clone` continues to enforce its existing 127.0.0.1 rewrite as belt-and-braces.
- **`DELETE /session/{id}` input validation** — same `^[a-zA-Z0-9_-]{1,64}$` regex as `POST /clone`. Closes an asymmetry where a voice JSON that had gained a `session_id` field could be HTTP-deletable.
- **Backend-import isolation** — `register_all` now wraps each experimental backend's import + register in its own try/except. The primary Qwen3 path still fails loud; one broken experimental backend can no longer crash boot.
- **Hook regex hardening** — `setup.sh` and `.claude/hooks/codex-tts-worker.sh` now use `awk` exact-field comparison instead of `grep "^${AGENT}:"`, so an `AGENT` value cannot be interpreted as a regex.
- **XTTS v2 + F5-TTS TOCTOU** — `prepare_voice` now buffers the reference audio bytes when possible; `synthesize` writes a tempfile from those bytes if available, falling back to the path otherwise. Closes the same DELETE-during-synthesis race that qwen3 already handled in commit `5289576`.

### Fixed

- **Qwen3 long-input truncation** (commit `0dba278`) — `backends/qwen3.py::synthesize` now concatenates *all* sorted `out_*.wav` segments instead of only `wavs[0]`. Long inputs were being silently truncated to the first segment.
- **Qwen3 unavailability hint** — `load()` catches `ImportError`, sets `_unavailable_reason`, and logs at ERROR level with the brew-upgrade/venv-rebuild guidance from CLAUDE.md so the cause shows up directly in `afterwords logs`.
- **Dia2 sample-rate typo** — `NATIVE_SR` corrected from `44000` to `44100`; the wrong value would cause a subtle pitch shift when `result.sample_rate` was absent.
- **Voxtral missing-lang guard** — `_DEFAULT_VOICE_BY_LANG` lookup changed to `.get(lang, "casual_male")`; a future `supported_langs` addition without a matching dict key could previously KeyError past the server's `ValueError` handler.
- **`/clone` tempfile leak** — `sf.write` + `os.rename` in the clone path now wrapped in `try/except` so `tmp_ref` is cleaned up when `sf.write` fails.

### Docs

- Reconciled voice counts, hook-chain references, and the Phase 1 lock-acquisition claim in the Hot-reload section (commit `f9db36c`).
- `docs/youtube-revoicing-pipeline.md` — corrected nonexistent CLI flags (`--name`/`--file`), removed reference to nonexistent `afterwords speak` command, fixed port `8000 → 7860` and endpoint `/synthesise → /synthesize` (commit `013e46d`).
- `AGENTS.md` — fixed backend count (17 → 15 remaining after Chatterbox + VoxCPM removal), dropped unnecessary `PYTHONPATH=.` prefix on pytest commands.

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
