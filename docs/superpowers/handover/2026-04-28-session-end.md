# Session handover — 2026-04-28

> Notes for the next Claude session. Read this first; everything below is what *just* shipped, what *almost* shipped, and what's queued.

## TL;DR

7 PRs landed on `main` today (#10 → #17). Repo is green: 82 tests passing, 4 backends loaded, 50+ voices, demo site live at https://adrianwedd.github.io/afterwords/. The big technical story today was multi-backend follow-through (hot-reload, multilingual groundwork, voice-family routing) plus an embarrassing-but-fixed VoxCPM cloning bug discovered during operator audition. Three concrete follow-ups remain — all in **issue #14** and the listening side of **issue #5**.

## What shipped today

| PR | One-line |
|---|---|
| #10 | Multi-backend follow-through (22 commits): hot-reload, multilingual groundwork, demo Backend Comparison section, 9 per-backend flagship JSONs |
| #11 | Operator follow-ups: bash-3.2 script compat, VoxCPM generator handling, 12 demo MP3s |
| #12 | Pinned `pytest>=9.0.3` (Dependabot CVE) + 2 VoxCPM regression tests |
| #13 | Voice-family lang routing (closes #9): `galadriel?lang=zh` auto-routes within family |
| #15 | Pulled non-cloning backends from demo comparison after operator listen-test revealed VoxCPM/Chatterbox weren't cloning |
| #16 | Real VoxCPM cloning fix: kwarg rename + `mx.array` load. Cloning now engages the reference |
| #17 | Comprehensive docs sweep (README/CLAUDE/AGENTS/site) to reflect everything above |

## What's queued (in priority order)

### 1. Listen-test VoxCPM, then restore demo column
**File**: `/tmp/voxcpm-audition/{picard,galadriel,attenborough}-voxcpm-15-FIXED.wav` (regenerate via the running server if missing).
**Compare against**: `voices/{name}-ref.wav`.
**If they sound like the references**: regenerate via `scripts/gen-comparison-audio.sh` (will need to enable VoxCPM rows in the script's BACKENDS array) and restore the VoxCPM column to the comparison cards in `docs/index.html`.
**If they don't**: leave the demo as-is. VoxCPM stays loaded but undocumented as a clone-quality option. Document in #14.

### 2. Listen-test Chatterbox, decide its fate
**File**: `/tmp/voxcpm-audition/{picard,galadriel,attenborough}-chatterbox-FIXED.wav`.
**Integration is correct** (verified by code inspection + 3 distinct shasums per reference). The question is the model itself — `mlx-community/chatterbox-fp16` is the multilingual variant; original Resemble Chatterbox (English only) may be a stronger cloner. Options if quality is poor: (a) tune `exaggeration`/`cfg_weight` extras, (b) switch `MODEL_ID` to the non-multilingual variant and shrink `supported_langs` to `("en",)`, (c) document Chatterbox as low-fidelity in the backend table and remove from the demo permanently.

### 3. Add a perceptual cloning-fidelity test
Today's `tests/test_backends_integration.py` only asserts `audio.size > sr * 0.1` — it confirms audio came out, not that it cloned the reference. A real test would compute MFCC cross-correlation between the reference WAV and the synth output, with a threshold (e.g. > 0.6 cosine similarity on speaker-embedding vectors). Without this, latent integration bugs like the VoxCPM kwarg one go undetected. Reasonable scope: 1-2 hours, opt-in via `pytest -m integration`.

### 4. Voxtral TTS backend (Issue #5)
Surprise finding today: `mlx-audio` already ships a `voxtral_tts` model directory. Issue #5's "pending MLX port" framing was stale. Adding it as an Afterwords backend is the standard one-file pattern. **Do first**: inspect `mlx_audio/tts/models/voxtral_tts/voxtral_tts.py` for the actual HuggingFace `MODEL_ID` and confirm what model family it is — "Voxtral" is also Mistral's STT model name, so there's some risk this is mis-labelled.

### 5. Other latent backends to audition
The local `mlx-audio` package has 16 cloning-capable backends (signature inspection — they take `ref_audio` or `audio_prompt`). Most plausible additions for variety/quality: **IndexTTS** (Bilibili, broadcast-quality cloning), **Sesame CSM** (1B, conversational, Apache 2.0), **Spark-TTS** (LLM-driven cloning), **F5-TTS** (flow-matching, multilingual). Add only after #1-#4 above; resist the temptation to keep adding backends without first verifying cloning quality.

## Operational notes

- **Server is live** at `localhost:7860`, started today via `afterwords restart` after PR #16 merged. All 4 backends loaded; 54 voices including the 9 family-routable flagships. PID may have changed since this writing — `afterwords status` to check.
- **Voice-family routing is currently dead code in production.** All 4 backends advertise overlapping `supported_langs` (Qwen3 covers everything Chatterbox/VoxCPM cover), so the routing fallback never fires for legitimate requests. Either prune Qwen3's `supported_langs` to what its actual model card claims, OR add a backend with non-overlapping language coverage. Mentioned in #14.
- **Hermes research died** mid-token-budget when we tried it for "evaluate cloning models." Its output is at `/private/tmp/.../bltsafh20.output` (1 line). Use Codex or a Claude general-purpose subagent for the next research pass; Gemini works once authed.
- **Pre-existing `/tmp/setup-output*.log` files** are gitignored now (PR #11). Safe to ignore.

## Repo state cheatsheet

```bash
# Tests
pip install -r requirements-dev.txt && pytest                 # 82 passing

# Server
afterwords status                                              # health, voices, backends
afterwords restart                                             # picks up code/config changes
afterwords reload                                              # picks up new voices/*.json without restart
curl localhost:7860/health | jq .loaded_backends               # lang capabilities per backend

# Demo
cd docs && python3 -m http.server 8765                         # local preview of GitHub Pages site
```

## Known traps

- **macOS bash is 3.2** (`/usr/bin/env bash`). Don't use `declare -A` or other bash 4+ features in shell scripts. Found this the hard way in `scripts/gen-comparison-audio.sh` (PR #11 fix).
- **Lock-acquisition order is invariant: `_synth_lock` → `_model_lock`.** Anything that takes them in the opposite order will deadlock with `/clone` Phase 1→2 or `/reload`. Documented in CLAUDE.md.
- **VoxCPM `prepare_voice` writes a temp WAV to `tempfile.gettempdir()`.** Server's lifespan shutdown deletes them; startup `_sweep_orphaned_temp_files()` cleans crash-orphans. If something restarts mid-sweep, you can get the "Error opening voxcpm-ref-*.wav" error we hit earlier today — fix is a clean restart.
- **mlx-audio kwargs differ per model.** Don't assume "ref_audio" is universal. VoxCPM uses `ref_audio` as an mx.array (not path), Chatterbox accepts `ref_audio` as path-or-array via the wrapper, Qwen3 uses `lang_code=lang`. Always read the actual model's `generate()` signature before integrating.
- **`afterwords reload` returns 404 on the launchd-managed server** because that server runs without `--allow-clone`. Restart picks up voice JSON changes without the flag; if you want hot reload, add `--allow-clone` to `~/Library/LaunchAgents/com.afterwords.tts-server.plist` args.
- **Reference transcripts can drift from reference audio.** `clone-voice.sh` populates `reference_text` from Whisper at clone time, but if a clip gets re-trimmed later (or the source had a longer subtitle than the audio segment), the JSON transcript can claim content the WAV doesn't contain. This degrades cloning conditioning (especially for Qwen3 REQUIRED-policy backends — model is told the reference contains text it doesn't). Fixed in PR #19 for attenborough; audit the rest of `voices/*.json` if cloning quality seems weak. Quick check: `python3 -c "from faster_whisper import WhisperModel; m=WhisperModel('base.en'); s,_=m.transcribe('voices/NAME-ref.wav'); print(' '.join(x.text for x in s))"` and diff against the JSON.

## Reading order for next session

1. This file.
2. `docs/superpowers/specs/2026-04-24-sprint-followthrough-design.md` — the source-of-truth design for everything that shipped this week.
3. Issues #5 and #14 on GitHub for the queued work.
4. `CLAUDE.md` for current project conventions (lock order, family-routing semantics, hot-reload algorithm).

## Don't forget

- `afterwords` is the user's flagship public repo today. Keep the bar high on PR descriptions and demo-site honesty. The "we shipped something that wasn't actually voice-cloning" lesson from today is *exactly* the kind of thing that erodes trust if it sticks around.
- The user is on a weekly Claude quota. Don't burn it on speculative refactors or new feature work without explicit approval — the queue above is enough for several focused sessions.
