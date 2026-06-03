# Afterwords — Local Voice-Cloning TTS Server

**[Listen to the voice demos →](https://adrianwedd.github.io/afterwords/)** &nbsp; [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/adrianwedd/afterwords/blob/main/colab/afterwords_comparison.ipynb)

Clone any voice from a 15-second YouTube clip and run it locally on your Mac. Use it as a standalone TTS API, or wire it into any AI coding harness — **Claude Code**, **Codex CLI**, **Cursor**, **Gemini CLI / Antigravity (agy)**, or **Hermes Agent** — to hear every response spoken aloud. **100 flagship voice families** (281 profiles across backend variants) on **the Qwen3-TTS cloning path** (0.6B + 1.7B, the recommended backends), plus **2 verified alternatives** (Voxtral, SoproTTS) and **13 scaffolded backends** (OpenVoice v2, F5-TTS, CosyVoice2, GPT-SoVITS, XTTS v2, IndexTTS-2, NeuTTS Air, Spark-TTS, Dia2, YourTTS, SV2TTS, MockingBird, FireRedTTS-2) that load correctly but have known installation issues on Apple Silicon — see the [Backend Status](#backend-status) table for details.

No cloud API. No subscription. No data leaves your machine. The voice comes from a 15-second audio sample — yours, a friend's, or anyone on YouTube.

## Quick Start

```bash
git clone https://github.com/adrianwedd/afterwords.git
cd afterwords
bash setup.sh
```

The setup script checks prerequisites, creates a venv, walks you through cloning a voice from YouTube, and starts the server. If Claude Code is detected (or you choose to install it), the script also wires up a Stop hook so Claude speaks every response.

For a server-only install with no Claude Code integration:

```bash
bash setup.sh --server-only
```

## With Claude Code

Claude Code has [`/voice`](https://docs.anthropic.com/en/docs/claude-code/voice-dictation) — hold Space to dictate prompts. But it's input only. Claude can hear you; you can't hear Claude. This project adds the missing half: **text-to-speech output**. Together, `/voice` input + TTS output = full voice conversations with Claude Code.

If Claude Code isn't installed, setup will offer to install it (requires Node.js; setup installs that too if needed via Homebrew).

## With Codex CLI

Codex CLI (`@openai/codex`) doesn't expose a Stop-hook event the way Claude Code does, so the integration uses a watcher instead: it polls the active session JSONL under `~/.codex/sessions`, extracts final assistant answers, and queues them for synthesis. Inside an interactive Codex session (where `$CODEX_THREAD_ID` is set):

```bash
afterwords codex-hook start    # daemon follows this session, speaks final answers
afterwords codex-hook status   # check
afterwords codex-hook stop
```

The tested working configuration is:

1. Start or verify the server:
   ```bash
   afterwords status
   afterwords start
   ```
2. From the same interactive Codex CLI session you want spoken, start the watcher:
   ```bash
   afterwords codex-hook start
   afterwords codex-hook status
   ```
3. Leave that Codex session running. The watcher process is detached under launchd's normal process tree (`PPID 1`) and follows only the current `$CODEX_THREAD_ID`.
4. On each final assistant answer, the watcher reads the matching `~/.codex/sessions/.../rollout-*.jsonl`, extracts `phase=final_answer`, writes an item under `/tmp/codex-tts-queue-$CODEX_THREAD_ID/`, synthesizes through `localhost:7860/synthesize`, plays with `afplay`, and archives audio/text under `~/.codex/tts-archive/`.

You can also run the session setup helper from inside Codex:

```bash
bash setup-codex.sh
```

That checks `$CODEX_THREAD_ID`, `python3`, `rg`, and `curl`; ensures the Codex hook scripts are executable; starts the server if needed; then runs `afterwords codex-hook start`.

The watcher needs `ripgrep` (`brew install ripgrep`) to locate the session file. Setup auto-detects Codex and prints these commands when it finishes; you don't have to memorize them.

Voice routing uses the same `.afterwords` mapping format as Claude hooks. Codex session JSONL does not normally include an `agent_type`, so the watcher assigns the synthetic agent key `codex`. For example:

```text
default: seven-of-nine
codex: spock
```

If no `codex:` entry exists, it falls back to `default:`. If neither exists, it falls back to the server default voice from `/health`.

For watcher debugging, run `afterwords codex-hook status`; it reports stale pid files and shows the tail of `/tmp/codex-tts-watch.log` when the watcher is not running. `afterwords codex-hook start --diagnose` prints the thread id, session file it would watch, hook path, and sample event detection without starting the daemon. The most common startup failures are `$CODEX_THREAD_ID` not being exported, or Codex not having created the first session event yet, so no `~/.codex/sessions/.../rollout-*.jsonl` file matches the thread id.

Useful checks:

```bash
afterwords status
afterwords codex-hook status
tail -40 /tmp/codex-tts-watch.log
ls -lt ~/.codex/tts-archive | head
ps -p "$(cat /tmp/codex-tts-watch.pid)" -o pid=,ppid=,stat=,command=
```

Trade-offs vs Claude Code: this depends on Codex's local session file format and on `$CODEX_THREAD_ID` being exported, both undocumented contracts that may shift between Codex versions. API-hosted or non-interactive Codex environments may reap long-lived background watcher processes; use the watcher from a real interactive Codex CLI terminal. For non-interactive Codex (`codex exec`), prefer wrapping with `--output-last-message <FILE>` and feeding the file to `/synthesize` directly — cleaner and version-stable.

## With Gemini CLI

Gemini CLI ships hook support, including a `gemini hooks migrate --from-claude` subcommand. Tempting — but in our testing it has a silent-write bug: when run from `$HOME` it reports success but leaves `~/.gemini/settings.json` unchanged (it writes via `setValue("Workspace", ...)` which is read-only when cwd == home). Even when the migrate succeeds elsewhere, the resulting config wouldn't work for TTS because the **payload schema differs**: Claude sends `last_assistant_message`, Gemini sends `prompt_response`.

So we ship a small adapter instead. `setup.sh` installs `~/.claude/hooks/gemini-tts-hook.sh` (it normalises `prompt_response` → the existing Claude tts-hook + worker chain) and prints the JSON snippet to add to `~/.gemini/settings.json`:

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/gemini-tts-hook.sh",
            "timeout": 120000
          }
        ]
      }
    ]
  }
}
```

Two things to know:

- Gemini fires `AfterAgent` (analogue of Claude's `Stop`); there's no clean `SubagentStop` analogue, so per-agent voice mapping via `.afterwords` is Claude-only for now.
- The adapter writes into Claude's TTS queue directory (`/tmp/claude-tts-queue/`) and the same worker drains both Claude and Gemini sessions atomically. No coordination needed.

Test: `gemini -p "say hi"` should speak the response via Afterwords using your default voice.

## With Antigravity CLI (agy)

Antigravity CLI (`agy`), the successor to Gemini CLI, supports hooks defined in `~/.gemini/config/hooks.json`. Unlike Gemini CLI's manual snippet configuration, `setup.sh` automatically detects `agy` and registers/updates the hook configuration programmatically.

During execution, `agy` fires the `Stop` event when the reasoning loop terminates. It passes a JSON payload containing `transcriptPath` (the path to the conversation's `transcript.jsonl` file) on `stdin`.

We process this with two files:
1. `~/.claude/hooks/agy-session-hook.py` — reads the `transcript.jsonl` file backwards to extract the final model response content, filtering out intermediate tool execution logs.
2. `~/.claude/hooks/agy-tts-hook.sh` — receives the hook payload, runs the python parser, pipes it through the markdown stripper, sets the agent to `agy`, and queues it.

### Personalizing the Voice

The hook sets the agent key to `agy`. This enables you to map a specific voice for `agy` sessions in your `.afterwords` file:

```text
default: seven-of-nine
agy: spock
```

If no `agy:` voice is defined, it will automatically fall back to the `default:` voice.

Test: `agy --print "say hello"` should speak the response via Afterwords.

## With Hermes Agent

Hermes has a full three-path integration. Setup does not auto-configure Hermes — add each path manually as shown below.

**1. Shell hook (`post_llm_call`)** fires on every direct CLI response. In `~/.hermes/config.yaml`:

```yaml
hooks:
  post_llm_call:
  - command: bash /path/to/afterwords/scripts/afterwords-post-llm.sh
    timeout: 60
hooks_auto_accept: true
```

**2. Native Python hook (`agent:end`)** via Hermes's gateway hook system, installed at `~/.hermes/hooks/afterwords-tts/`. Only speaks on CLI/local contexts; skips Telegram/Discord automatically to avoid double-notification.

**3. Command provider** handles explicit TTS calls (`/voice tts`, `text_to_speech` tool) and messaging-platform audio. In `~/.hermes/config.yaml`:

```yaml
tts:
  provider: afterwords
  providers:
    afterwords:
      type: command
      command: 'bash ~/repos/afterwords/scripts/afterwords-tts-command.sh {input_path} {output_path} {voice}'
      output_format: wav
```

On CLI the command script returns instantly (silent placeholder WAV) and plays audio in a detached background subshell — text output is never delayed. On messaging platforms it runs synchronously for audio-file attachment delivery.

All three paths resolve voice from `.afterwords` files using `hermes` as the agent key and acquire the shared play lock (`/tmp/afterwords-play.lock`) to coordinate with Claude/Codex/AGy workers. The native hook (`handler.py`) and command provider archive MP3 + text sidecar to `~/.hermes/tts-archive/`; the shell hook (`afterwords-post-llm.sh`) is playback-only and does not archive.

```
hermes: data
default: galadriel
```

## With Cursor

Cursor 1.7+ fires an `afterAgentResponse` hook when the agent completes a response, passing the full assistant text in the `text` field. Setup auto-detects Cursor and installs the hook; or wire it up manually:

1. Copy `cursor-tts-hook.sh` to `~/.claude/hooks/`
2. Add to `~/.cursor/hooks.json`:

```json
{
  "version": 1,
  "hooks": {
    "afterAgentResponse": [
      {
        "command": "bash ~/.claude/hooks/cursor-tts-hook.sh",
        "type": "command",
        "timeout": 10,
        "failClosed": false
      }
    ]
  }
}
```

The hook reuses the same TTS worker queue (`/tmp/claude-tts-queue/`) and `tts-worker.sh` as the Claude Code integration. Voice is resolved from `.afterwords` using the agent key `cursor`.

```
cursor: lister
default: galadriel
```

## Without an AI Harness

The TTS server is a plain HTTP API. Use it from any tool, script, or application:

```bash
# Synthesize speech
curl "http://localhost:7860/synthesize?text=Hello+world&voice=galadriel" -o hello.wav
afplay hello.wav

# List available voices
curl http://localhost:7860/health | jq .voices
```

Integrate with Cursor, Windsurf, shell scripts, web apps — anything that can make an HTTP request.

## Adding More Voices

```bash
bash clone-voice.sh
# or non-interactive:
bash clone-voice.sh "https://youtube.com/watch?v=..." galadriel 30
```

The script downloads the audio, extracts a 15-second segment, denoises it, transcribes with Whisper, and saves a voice profile. Each voice is just a 700 KB WAV file — adding voices costs zero extra memory.

### Auditing voice profiles

If you hand-edit a `voices/*.json` `reference_text` after cloning (e.g. to correct Whisper mishearings), you can drift the transcript away from what the trimmed audio actually says — which degrades cloning fidelity. The audit tool re-transcribes every reference WAV and flags drift:

```bash
afterwords audit               # report only
afterwords audit --fix         # overwrite reference_text with fresh Whisper output for flagged voices
afterwords audit --voice picard
```

Flags raised: phantom canonical text (transcript materially longer than what's heard), mid-word truncation, mid-clip silence gaps ≥1.5s, and impossible char/sec ratios. Exits non-zero when any voice is flagged, so it's safe to wire into CI.

## Switching Voices

**Per-project** — drop a `.afterwords` file in any repo:

```bash
echo "snape" > .afterwords     # this project uses Snape
echo "galadriel" > .afterwords # this one uses Galadriel
```

**Per-agent** — map agent names to voices (one per line):

```
# .afterwords
default: data
clara-oswald: clara-oswald
donna-noble: donna-noble
k9: k9
Explore: spock
```

When Claude Code spawns a subagent, the hook reads its `agent_type` and looks up the voice from the mapping. If no match is found, it falls back to `default:`, then to the server's default voice. Built-in subagent types (Explore, Plan, general-purpose) are silently skipped.

The hook reads this before each synthesis. No server restart needed.

**Global default** — edit `DEFAULT_VOICE` in `server.py` and restart:

```bash
afterwords restart
```

**Per-request:**

```bash
curl "http://localhost:7860/synthesize?text=Hello&voice=samantha" -o hello.wav
```

**Newly cloned voices** are auto-discovered on server restart, OR pick them up without a restart:

```bash
afterwords reload   # rescans voices/, adds new profiles, no synthesis interruption
```

`reload` is add-only and atomic — if any new profile fails validation, the whole reload aborts and the previous voice set stays intact.

## Languages

The backends advertise different language support. Ask `/health` to see what each one offers:

```bash
curl -s localhost:7860/health | jq '.loaded_backends | to_entries[] | {backend: .key, langs: .value.supported_langs}'
```

Pass `lang=` on a synthesis request when you want a non-English language:

```bash
curl "http://localhost:7860/synthesize?text=Ni+hao&voice=galadriel&lang=zh" -o hello-zh.wav
```

If the voice's backend doesn't support the requested language, and the voice belongs to a *family* (e.g. `picard`, `picard-qwen3-17b` both have `family: picard` in their JSON), the server auto-routes to a same-family voice on a backend that does support it. If no family member supports the language, you get a clean 400 with the list of supported languages.

## Claude Code Skill

A Claude Code skill is included in `skill/` that enables natural-language TTS commands:

```
"say 'the spice must flow' in a dramatic voice"
"what voices are available?"
"set this project to use river-song"
```

The skill handles voice selection, server health checks, synthesis, and playback. Install it by pointing Claude Code at the `skill/SKILL.md` file or adding it as a plugin.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Your Mac (Apple Silicon, 16 GB+)                               │
│                                                                  │
│  ┌──────────────────────────┐                                    │
│  │  Multi-Backend TTS       │  ← MLX Qwen3 + 15 alt backends    │
│  │  localhost:7860           │  ← 281 voice profiles (100 fam)   │
│  │  /synthesize?text=...     │  ← ~20s per sentence (Qwen3)      │
│  └────────────┬─────────────┘                                    │
│               │  shared play lock (/tmp/afterwords-play.lock)    │
│  ┌────────────┼──────────────────────────────────────────────┐   │
│  │            │   Four CLI integrations (all coordinated)    │   │
│  │  ┌─────────┴──────────┐   ┌────────────────────────────┐  │   │
│  │  │  Claude Code       │   │  Codex CLI                 │  │   │
│  │  │  Stop hook →       │   │  JSONL watcher →           │  │   │
│  │  │  tts-hook.sh       │   │  codex-tts-hook.sh         │  │   │
│  │  └────────────────────┘   └────────────────────────────┘  │   │
│  │  ┌─────────────────────┐  ┌────────────────────────────┐  │   │
│  │  │  Hermes Agent       │  │  Antigravity CLI (agy)     │  │   │
│  │  │  post_llm_call +    │  │  Stop hook →               │  │   │
│  │  │  agent:end hooks    │  │  agy-tts-hook.sh           │  │   │
│  │  └─────────────────────┘  └────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────┐  ┌─────────────────────────────┐  │
│  │  Claude Code /voice      │  │  .afterwords voice routing  │  │
│  │  (hold Space to dictate) │  │  per-project, per-agent     │  │
│  │  Speech → Text input     │  │  agent: voice-name          │  │
│  └──────────────────────────┘  └─────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**`/voice`** handles input: you speak, Claude hears text.
**This project** handles output: any of the four CLIs responds, you hear speech.
All four integrations share the play lock — simultaneous audio is coordinated to prevent overlap.

## How It Works

### Voice Cloning (Zero-Shot)

No training or fine-tuning. The recommended path is **Qwen3-TTS** at two sizes (0.6B + 1.7B from Alibaba, multilingual: en/zh/ja/ko/es/fr/de/it/pt/ru). The server extracts speaker embeddings from 15-second reference clips and generates new speech in that voice. Voxtral 4B is a verified preset-voice alternative; SoproTTS is a verified CPU-friendly Apache-2.0 backend for lightweight English zero-shot cloning. Chatterbox and VoxCPM were removed in commit f03e826 after Sprint 1 listen-tests on three flagship voices showed both failing to clone reference identity recognizably.

The following optional backends have working code but currently have installation issues on Apple Silicon (dep-resolution errors, missing build deps, or source repos not bundled). Each is tracked in the issue tracker. OpenVoice v2 is a PyTorch/MeloTTS backend for zero-shot multilingual cloning in en/es/fr/zh/ja/ko. F5-TTS is a PyTorch backend using the flow-matching DiT `F5TTS_v1_Base` model for en/zh; its default pretrained weights are CC-BY-NC 4.0 and are not for commercial use. CosyVoice2-0.5B is an Apache-2.0 PyTorch backend for multilingual zero-shot cloning. GPT-SoVITS is an MIT-licensed PyTorch backend for few-shot cloning in en/zh/ja/ko/yue. XTTS v2 is a Coqui TTS backend for 17-language zero-shot cloning; its CPML weights are non-commercial only. IndexTTS-2 is a PyTorch backend for expressive en/zh zero-shot cloning with emotion controls. NeuTTS Air is an Apache-2.0 CPU-first backend for English zero-shot cloning via Neuphonic's `neutts` package. Spark-TTS is an LLM+BiCodec PyTorch backend for en/zh zero-shot cloning; its published 0.5B weights are CC-BY-NC-SA 4.0 and non-commercial. Dia2 is an Apache-2.0 PyTorch backend for English dialogue-oriented voice conditioning with `[S1]`/`[S2]` speaker tags. YourTTS is an open-source Coqui VITS backend for lightweight en/fr/pt-BR zero-shot cloning at 16 kHz. FireRedTTS-2 is an Apache-2.0 PyTorch backend for long conversational and podcast-style multilingual zero-shot cloning. SV2TTS is an open-source PyTorch backend using the classic Real-Time Voice Cloning encoder + Tacotron + WaveRNN pipeline for English. MockingBird is an open-source Chinese-focused SV2TTS-derived backend.

#### Backend Status

**Verified** backends clone voices end-to-end on Apple Silicon (tested). **Scaffolded** backends have working code but known installation issues — see linked issues for status.

| Backend | Status | License | Languages | Sample rate | Reference text |
|---------|--------|---------|-----------|-------------|----------------|
| `qwen3-0.6b`, `qwen3-1.7b` | ✅ recommended | model-dependent | en/zh/ja/ko/es/fr/de/it/pt/ru | 24 kHz | required |
| `voxtral` | ✅ verified (preset voices) | model-dependent | preset voices | 24 kHz | ignored |
| `soprotts` | ✅ verified | Apache-2.0 | en | 24 kHz | optional |
| `openvoice-v2` | 🔧 scaffolded | MIT | en/es/fr/zh/ja/ko | 22.05 kHz | optional |
| `f5-tts` | 🔧 scaffolded | CC-BY-NC default weights | en/zh | 24 kHz | required |
| `cosyvoice2` | 🔧 scaffolded | Apache-2.0 | en/zh/ja/ko/de/es/fr/it/ru | 24 kHz | required |
| `gpt-sovits` | 🔧 scaffolded | MIT | en/zh/ja/ko/yue | 32 kHz | required |
| `xtts-v2` | 🔧 scaffolded | CPML, non-commercial only | en/es/fr/de/it/pt/pl/tr/ru/nl/cs/ar/zh/hu/ko/ja/hi | 24 kHz | optional |
| `indextts-2` | 🔧 scaffolded | LicenseRef-Bilibili-IndexTTS | en/zh | 22.05 kHz | optional |
| `neutts-air` | 🔧 scaffolded | Apache-2.0 | en | 24 kHz | optional |
| `spark-tts` | 🔧 scaffolded | Apache-2.0 code; CC-BY-NC-SA 4.0 weights | en/zh | 24 kHz | optional |
| `dia2` | 🔧 scaffolded | Apache-2.0 | en | 44 kHz | optional |
| `yourtts` | 🔧 scaffolded | Open source | en/fr/pt-BR | 16 kHz | optional |
| `firered-tts-2` | 🔧 scaffolded | Apache-2.0 | en/zh/ja/ko/fr/de/ru | 24 kHz | optional |
| `sv2tts` | 🔧 scaffolded | Open source | en | 22.05 kHz | optional |
| `mockingbird` | 🔧 scaffolded | Open source | zh/en | 22.05 kHz | optional |

Voice profiles pin to a specific backend via the `backend` JSON field. The shipped flagship voices (picard, galadriel, attenborough) have per-backend variants so you can compare clone fidelity across models — Qwen3 sizes are the most reliable cloners in the current stack; see the [demo site](https://adrianwedd.github.io/afterwords/) for audible comparison.

### The Server

FastAPI + Uvicorn serving WAV audio over HTTP. Backends load once at startup; each voice is a reference WAV + transcript string. All synthesis serialised via `_synth_lock` (MLX Metal is single-GPU regardless of backend). VOICES dict mutation is guarded by a separate `_model_lock`. Lock-acquisition order is always `_synth_lock` → `_model_lock` to avoid deadlock.

```
GET  /health
       → {"status":"ok", "ready":true, "voices":[...],
          "loaded_backends": {"qwen3-0.6b": {"loaded":true, "voice_count":..., "supported_langs":[...]}, ...}}

       Current backend ids:
       qwen3-0.6b, qwen3-1.7b, voxtral, openvoice-v2, f5-tts, cosyvoice2,
       gpt-sovits, xtts-v2, indextts-2, neutts-air, spark-tts, dia2, yourtts, firered-tts-2,
       sv2tts, mockingbird, soprotts

GET  /synthesize?text=Hello&voice=galadriel&lang=en
       → audio/wav (16-bit PCM)
       → X-Backend, X-Synthesis-Time, X-Duration headers
       → 400 if voice unknown OR lang unsupported (returns supported_langs)
       → 503 if warming up

POST /synthesize          (--allow-clone only)
       Body: {"text":..., "voice":..., "emotion":..., "lang":"en"}
       → audio/wav, same status codes as GET

POST /clone               (--allow-clone only)
       multipart: audio file, session_id, emotion, transcript?, backend?
       → JSON {voice, backend, emotion, quality, sequence, ...}

POST /reload              (--allow-clone only)
       → JSON {status, reloaded:[names], errors:[]} on success (200)
       → JSON {status:"failed", errors:[...]}        on abort   (500)
       Add-only, atomic — if any voice fails to prepare, no changes committed.

DELETE /session/{id}      (--allow-clone only)
       → removes all voices for that session, cleans up temp files
```

### The Hook

Claude Code's [Stop hook](https://docs.anthropic.com/en/docs/claude-code/hooks) fires after every response. The hook extracts the response text, strips markdown, and atomically writes a JSON item to the shared queue directory (`/tmp/claude-tts-queue/`). A background worker with `mkdir`-based locking (macOS has no `flock`) claims items one at a time and prevents overlapping audio via a shared play lock (`/tmp/afterwords-play.lock`) coordinated across all four CLI integrations.

### The Queue

Fast conversations generate responses faster than TTS can synthesise. The worker processes up to 10 queued items, discarding oldest when it overflows. Text is split into ~200-character sentence chunks; synthesis of chunk N+1 runs in the background while chunk N plays — latency to first audio is ~2 seconds regardless of response length.

Each chunk is archived as an MP3 plus a sidecar TXT file under the CLI's own archive directory:

| CLI | Archive directory | Notes |
|-----|-------------------|-------|
| Claude Code | `~/.claude/tts-archive/` | |
| Codex CLI | `~/.codex/tts-archive/` | |
| AGy | `~/.claude/tts-archive/` | shares Claude Code's worker |
| Hermes (native hook + command provider) | `~/.hermes/tts-archive/` | shell hook is playback-only |

Archiving requires `lame` (`brew install lame`).

> **Privacy note:** sidecar `.txt` files contain the exact text spoken — including code snippets and file paths. They persist on local disk and are never uploaded. Clean with `rm ~/.claude/tts-archive/*.txt` or remove the `lame ... && printf ...` block from `~/.claude/hooks/tts-worker.sh` to disable archiving entirely.

## Requirements

- Apple Silicon Mac (M1/M2/M3/M4), 16 GB+ RAM (32 GB recommended)
- Python 3.11+
- ~2 GB disk (model weights + venv)
- Claude Code (optional — for automatic TTS on responses; setup offers to install it)

## File Map

```
afterwords/
├── setup.sh                  ← one-command setup (detects/installs Claude Code)
├── afterwords.sh             ← CLI for server management (symlinked to PATH)
├── clone-voice.sh            ← add more voices from YouTube
├── server.py                 ← multi-voice TTS server
├── strip_markdown.py         ← text cleaner for TTS (Python-importable)
├── chunk_text.py             ← sentence-boundary chunker (Python-importable)
├── codex_session_hook.py     ← Codex JSONL parser (strip + agent-type extraction)
├── agy_session_hook.py       ← AGy transcript parser (last model response)
├── tests/                    ← pytest suite (505+ tests, no GPU needed)
├── backends/                 ← Backend Protocol + concrete backends + registry CLI
├── scripts/
│   ├── afterwords-post-llm.sh      ← Hermes post_llm_call hook (chunked pipeline)
│   ├── afterwords-tts-command.sh   ← Hermes command TTS provider
│   ├── strip-markdown.py           ← CLI version (called from shell hooks)
│   ├── chunk-text.py               ← CLI version (called from shell hooks)
│   ├── reclone-flagship.py         ← reclone a voice from scratch
│   ├── gen-comparison-audio.sh     ← generate backend-comparison samples
│   └── audit-archive.py            ← audit ~/.*/tts-archive/ MP3s + sidecars
├── docs/                     ← demo site + reference docs (GitHub Pages)
├── requirements.txt          ← runtime deps
├── requirements-dev.txt      ← test deps (pytest>=9.0.3, httpx)
├── skill/                    ← Claude Code skill for natural-language TTS
│   ├── SKILL.md              ← skill instructions
│   └── scripts/speak.sh     ← synthesize + play helper
├── voices/
│   ├── galadriel-ref.wav     ← 15s reference (Cate Blanchett, LOTR)
│   ├── samantha-ref.wav      ← (Scarlett Johansson, Her)
│   ├── amy-pond-ref.wav      ← (Karen Gillan, Doctor Who)
│   └── ...                   ← 98 families / 275 profiles; flagships have per-backend variants
└── README.md

~/.claude/                    ← only with Claude Code integration
├── settings.json             ← Stop + SubagentStop hooks registered here
└── hooks/
    ├── tts-hook.sh           ← queue response for TTS (Claude Code)
    ├── tts-worker.sh         ← process JSON queue, play audio (shared by Claude/AGy/Gemini)
    ├── strip-markdown.py     ← clean text for TTS
    ├── chunk-text.py         ← sentence-boundary text splitter
    ├── gemini-tts-hook.sh    ← Gemini CLI adapter (normalises prompt_response)
    ├── agy-tts-hook.sh       ← AGy Stop hook adapter
    ├── agy-session-hook.py   ← AGy transcript parser
    ├── codex-tts-hook.sh     ← Codex per-session hook
    ├── codex-tts-worker.sh   ← Codex per-session worker (independent queue)
    └── codex-tts-watch.sh    ← Codex JSONL session watcher daemon

~/.hermes/
├── hooks/afterwords-tts/     ← Hermes native Python hook (agent:end)
│   ├── HOOK.yaml
│   └── handler.py
└── tts-archive/              ← Hermes MP3 + txt sidecars

~/.claude/tts-archive/        ← Claude/AGy/Gemini MP3 + txt sidecars
~/.codex/tts-archive/         ← Codex MP3 + txt sidecars

~/Library/LaunchAgents/
└── com.afterwords.tts-server.plist  ← auto-start on login
```

## Included Voices

| Voice | Source | Character |
|-------|--------|-----------|
| attenborough | David Attenborough, *BBC Earth* | Warm, measured, wry narration |
| galadriel | Cate Blanchett, *LOTR* | Ethereal, ancient, otherworldly |
| han-solo | Harrison Ford, *Star Wars* | Sardonic, roguish confidence |
| samantha | Scarlett Johansson, *Her* | Warm, introspective AI |
| aurora | AURORA, *Shower Thoughts* | Dreamy, Norwegian, whimsical |
| audrey | Audrey Hepburn, 1961 | Elegant, transatlantic |
| marla | Helena Bonham Carter, *Fight Club* | Sardonic, darkly poetic |
| avasarala | Shohreh Aghdashloo, *The Expanse* | Gravelly, commanding |
| vesper | Eva Green, *Casino Royale* | French-accented, seductive |
| claudia | Claudia Black, *Dragon Age* | Australian, husky |
| eartha | Eartha Kitt, interview | Passionate purr |
| tilda | Tilda Swinton, interview | Crisp, dry wit |
| snape | Alan Rickman, *Harry Potter* | Velvet menace, slow burn |
| loki | Tom Hiddleston, *Avengers* | Theatrical, commanding |
| spock | Leonard Nimoy, *Star Trek* | Measured, logical deadpan |
| bardem | Javier Bardem, *Vicky Cristina Barcelona* | Warm, seductive Spanish |
| depp | Johnny Depp, interview | Languid, charming |
| data | Brent Spiner, *Star Trek TNG* | Precise, android curiosity |
| lisa-simpson | Yeardley Smith, *The Simpsons* | Earnest, thoughtful, idealistic |
| picard | Patrick Stewart, *Star Trek* | Authoritative, measured |
| ronan | Ronan Keating, interview | Soft Irish, reflective |

### Doctor Who Companion Voices

| Voice | Actor | Character |
|-------|-------|-----------|
| the-doctor | Tom Baker, *Day of the Doctor* | Warm, enigmatic Curator |
| amy-pond | Karen Gillan, *Angels Take Manhattan* | Fierce, emotional farewell |
| bill-potts | Pearl Mackie, *Twice Upon a Time* | Warm, defiant |
| clara-oswald | Jenna Coleman, *The Name of the Doctor* | Quick, clever |
| donna-noble | Catherine Tate, *Turn Left* | Bold, heartfelt |
| k9 | John Leeson, *Doctor Who* | Robotic, clipped |
| leela | Louise Jameson, Big Finish | Direct, warrior's clarity |
| martha-jones | Freema Agyeman, *Last of the Time Lords* | Confident, commanding |
| nyssa-of-traken | Sarah Sutton, *Terminus* | Gentle, precise |
| river-song | Alex Kingston, *Husbands of River Song* | Theatrical, knowing |
| romana | Lalla Ward, Big Finish | Regal, intellectual |
| rose-tyler | Billie Piper, *Parting of the Ways* | Ethereal, powerful |
| sarah-jane-smith | Elisabeth Sladen, *School Reunion* | Warm, investigative |
| tegan-jovanka | Janet Fielding, *Resurrection of the Daleks* | Blunt, emotional |
| yasmin-khan | Mandip Gill, *Power of the Doctor* | Quiet, heartfelt |

The full gallery includes 100 voice families spanning British comedy (Blackadder, Alan Partridge, Basil Fawlty, Malcolm Tucker, Father Ted, Geraldine, Patsy & Edina, Bernard Black…), American drama (Frasier, Columbo, Saul Goodman, Harvey Specter…), American sitcom (Lisa Simpson…), science communicators (Carl Sagan, Feynman, Brian Cox, Neil deGrasse Tyson…), and more. Run `afterwords voices --demo` to browse and hear samples.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No voice after Claude responds | `afterwords status` — if dead: `afterwords start` |
| "warming up" 503 | Wait ~30s after restart for model load + warmup |
| Voice sounds wrong/garbled | Re-clone with a better reference clip; verify transcript accuracy |
| 40+ seconds per request | Restart the server (model may be reloading per-request) |
| `/voice` not working | Enable with `/voice` command in Claude Code; requires Claude.ai account |
| Hook not firing (Claude) | Open `/hooks` in Claude Code to verify; or restart session |
| Hook not firing (Codex) | Check `$CODEX_THREAD_ID` is set; run `afterwords codex-hook status` |
| Hook not firing (AGy) | Verify `~/.gemini/config/hooks.json` has `afterwords-tts` entry; run `agy` from the project directory |
| Hook not firing (Gemini) | Check `~/.gemini/settings.json` has `AfterAgent` hook; ensure `gemini-tts-hook.sh` is executable |
| Hook not speaking (Hermes) | Check `afterwords status`; verify `hooks_auto_accept: true` in Hermes config |
| Two agents talking at once | Shared play lock in `/tmp/afterwords-play.lock` should prevent this; check for stale lock: `rm -rf /tmp/afterwords-play.lock /tmp/afterwords-play.pid` |
| New voice not available | Run `afterwords reload` or restart the server |
| Port 7860 already in use | Another instance is running, or another app uses the port |
| Model download fails | Check network; retry `python server.py` manually |
| MP3 archives missing | Install `lame` via `brew install lame` |

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover the server API (endpoint validation, error handling, voice resolution, hot-reload atomicity, lang routing across backend families), backend protocol conformance, the strip-markdown text transform, the `_cleanup_current_voices` lifecycle helper, AGy session hook parsing, voice-mapping resolution, and a parametrized schema validator that runs against every shipped voice profile in `voices/*.json`. 505+ tests pass without loading any real model — a `FakeBackend` fixture stands in. Real-model integration tests are opt-in via `pytest -m integration`.

Run a single test:

```bash
pytest tests/test_strip_markdown.py::test_inline_code_keeps_content
pytest tests/test_server.py -k reload         # all reload tests
pytest tests/test_server.py -k routing        # all family-routing tests
```

## Managing the Server

```bash
afterwords start       # start the TTS server
afterwords stop        # stop the TTS server
afterwords restart     # restart after config changes
afterwords status      # show health, PID, loaded voices
afterwords logs        # tail the server log
afterwords voices      # list available voices
afterwords reload      # pick up new voices without restarting (no synth interruption)
afterwords clone       # clone a new voice from YouTube
afterwords uninstall   # remove service and optionally hooks
```

The `afterwords` command is added to your PATH during setup. It wraps launchd service management, health checks, and voice operations into a single interface.

## Uninstalling

```bash
afterwords uninstall
```

This removes the launchd service and offers to remove Claude Code hooks. Voice profiles and server code remain in the repo directory. Setup is safe to re-run if anything breaks.

## Performance

On 32 GB M3 Max with the recommended Qwen3-only install:
- Startup: ~30s–2 min (backend load + warmup; longer when other backends are installed)
- Model load: ~5s (cached) / ~5 min (first run, downloading ~3 GB)
- Per request: ~15s fixed overhead + ~0.5x real-time (~20s typical)
- Peak memory: ~3–4 GB (Qwen3 0.6B + 1.7B only); higher if optional backends from the registry are installed and preloaded
- Adding voices: zero extra memory (each is just a 700 KB WAV)

## Credits

- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) by Alibaba (Apache 2.0)
- [mlx-audio](https://github.com/Blaizzy/mlx-audio) by Blaizzy
- [OpenVoice](https://github.com/myshell-ai/OpenVoice) and [MeloTTS](https://github.com/myshell-ai/MeloTTS) by MyShell (MIT)
- [Coqui TTS / XTTS v2](https://github.com/coqui-ai/TTS) by Coqui (code MPL-2.0; XTTS v2 weights CPML, non-commercial only)
- [MLX](https://github.com/ml-explore/mlx) by Apple
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/) by Anthropic
- Voice reference clips used under fair use for personal voice synthesis research

## Related

- [Voice Cloning with Qwen3-TTS and MLX on Apple Silicon](https://adrianwedd.com/blog/voice-cloning-qwen3-tts-mlx/) — the full tutorial
- [Giving a Robot Three Voices](https://adrianwedd.com/blog/giving-a-robot-three-voices/) — SPARK's multi-backend TTS architecture
- [SPARK](https://spark.wedd.au) — the robot this was built for
