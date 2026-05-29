# Hermes Agent TTS Integration — Afterwords

Hermes speaks every response aloud via Afterwords TTS. Two hook systems
cover all session types; voice is resolved per-project or globally.

---

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │              Hermes Agent                     │
                    │                                               │
  Direct CLI ──────│ post_llm_call (shell hook)                    │
  sessions          │   → afterwords-post-llm.sh                   │
                    │     → strip-markdown.py → chunk-text.py      │
                    │     → curl /synthesize (pipelined) → afplay  │
                    │                                               │
  Local/gateway ───│ agent:end (native hook)                       │
  CLI contexts      │   → handler.py (async)                       │
                    │     → strip_markdown() → chunk_text()        │
                    │     → aiohttp /synthesize (pipelined) → afplay│
                    └──────────────────────────────────────────────┘
```

Both paths resolve voice from `.afterwords` files, then hit
`http://127.0.0.1:7860/synthesize?text=…&voice=…`.

---

## 1. Shell Hook — `post_llm_call`

Fires during direct CLI sessions (the `hermes` command in a terminal).

**Config** (`~/.hermes/config.yaml`):

```yaml
hooks:
  post_llm_call:
  - command: bash /Users/adrian/repos/afterwords/scripts/afterwords-post-llm.sh
    timeout: 60
hooks_auto_accept: true
```

**Script** (`afterwords/scripts/afterwords-post-llm.sh`):

- Reads JSON payload from stdin (`assistant_response`, `cwd`, `platform`)
- Strips markdown (via `strip-markdown.py`), splits into ~200-char sentence chunks
  (via `chunk-text.py`)
- Checks Afterwords server health (`/health`)
- Resolves voice from `.afterwords` files
- **Pipelined playback**: synthesize chunk N+1 in background while
  `afplay` plays chunk N, then trim leading silence with `ffmpeg`
- Exits silently if the server is down

**Payload** (from Hermes shell hooks system):

```json
{
  "hook_event_name": "post_llm_call",
  "session_id": "...",
  "cwd": "/Users/adrian/repos/afterwords",
  "extra": {
    "assistant_response": "Hello! How can I help?",
    "platform": "cli"
  }
}
```

---

## 2. Native Hook — `agent:end`

Fires via Hermes's Python hook system. The installed handler currently
speaks only `cli`, `local`, or empty platform contexts and skips messaging
platforms to avoid double-notification; messaging audio is handled by the
command TTS provider.

**Location**: `~/.hermes/hooks/afterwords-tts/`

```
afterwords-tts/
├── HOOK.yaml        # name, description, events
└── handler.py       # async def handle(event_type, context)
```

**HOOK.yaml**:

```yaml
name: afterwords-tts
description: Auto-speak Hermes agent responses via local Afterwords TTS server
events:
  - agent:end
```

**handler.py** key behaviours:

- Async — uses `aiohttp` to call the Afterwords server
- Filters: only speaks for `cli`, `local`, or empty platform (avoids
  double-notification on Telegram/Discord)
- Strips markdown (built-in), truncates to 1000 chars, then splits into
  ~200-char sentence chunks (`chunk_text()`)
- **Pipelined playback**: synthesizes chunk N+1 via aiohttp while playing
  chunk N via `afplay`; trims leading silence with `ffmpeg`; overlaps
  synthesis and playback for ~2s latency-to-first-audio
- Resolves voice from `.afterwords` files (project then global)
- Writes WAV to `/tmp/`, cleans up after playback
- Fail-silent: errors log to `afterwords-tts` logger but never crash the hook

**Context** (from Hermes at `agent:end`):

```python
{
    "platform": "local",       # Platform enum value
    "user_id": "...",
    "chat_id": "...",
    "session_id": "...",
    "message": "...",           # User's message (truncated)
    "cwd": "",                 # From TERMINAL_CWD env var
    "response": "Agent response text..."  # handler strips/truncates to 1000 chars
}
```

---

## 3. Voice Resolution

Priority (first match wins):

| Priority | Source | Lookup order within file |
|----------|--------|--------------------------|
| 1 | Project `.afterwords` | agent key → `default:` fallback |
| 2 | Global `~/.afterwords` | agent key → `default:` fallback → single voice |
| 3 | Server default | `galadriel` (from `/health` endpoint) |

**`~/.afterwords` (global fallback):**

```
# Global Afterwords voice config
default: galadriel
hermes: data
```

**Project `.afterwords` example (afterwords repo):**

```
default: galadriel
hermes: data
codex: seven-of-nine
agy: samantha
gemini: marla
feature-dev:code-reviewer: spock
feature-dev:code-architect: picard
feature-dev:code-explorer: attenborough
superpowers:code-reviewer: spock
natalie-ws25: vixen
```

Parsers split on the last `:` so keys may contain colons and both
`key: value` and `key:value` are accepted.

**Config-level voice** (`~/.hermes/config.yaml`):

```yaml
tts:
  provider: afterwords
  edge:
    voice: en-US-AriaNeural
```

The `provider: afterwords` tells the built-in Hermes TTS command system
to delegate to `scripts/afterwords-tts-command.sh`. This is separate from
the hooks — it handles explicit `/speak` commands or the `tts` tool, not
auto-speak on every response.

---

## 4. Command Provider

`afterwords/scripts/afterwords-tts-command.sh` — called by Hermes's command TTS provider system
for explicit `/voice tts` calls, the `text_to_speech` tool, and messaging-platform audio delivery.

Usage:

```bash
bash afterwords-tts-command.sh <input_path> <output_path> [voice]
```

**CLI mode (default when `$HERMES_SESSION_PLATFORM` is unset/`cli`/`local`):**
- Writes a silent placeholder WAV (0.1s) and returns immediately — text output is not delayed
- Fires real synthesis + `afplay` in a detached background subshell
- Acquires shared play lock (`/tmp/afterwords-play.lock`) to coordinate with other agents

**Messaging-platform mode (Telegram, Discord, etc.):**
- Runs synchronously; produces the real audio file for attachment delivery

Both paths:
- Strip basic markdown (`sed`), truncate to 1000 chars
- Resolve voice: config arg → project `.afterwords` (`hermes` key → `default:`) → global `~/.afterwords`
- Archive MP3 + text sidecar to `~/.hermes/tts-archive/` (best-effort)
- Exit non-zero on synthesis failure (messaging path only; CLI path is fire-and-forget)

---

## 5. Afterwords Server

Managed by launchd, auto-starts on login.

```bash
afterwords start     # start via launchd
afterwords stop      # stop server
afterwords restart   # restart
afterwords status     # health, PID, loaded voices
afterwords voices     # list available voices (--demo to play samples)
afterwords reload     # rescan voices/ without restart
```

- Endpoint: `http://127.0.0.1:7860`
- Default voice: `galadriel`
- Primary backend: `qwen3-0.6b` (155 voices) + `qwen3-1.7b` (100 voices)
- All synthesis serialised through `_synth_lock` (single Metal GPU)

---

## 6. File Locations

| File | Purpose |
|------|---------|
| `~/.hermes/config.yaml` | Shell hook config, TTS provider, auto-accept |
| `~/.hermes/hooks/afterwords-tts/HOOK.yaml` | Native hook manifest |
| `~/.hermes/hooks/afterwords-tts/handler.py` | Native hook handler (async, chunked) |
| `~/.hermes/tts-archive/` | MP3 + text sidecar archive (native hook + command provider; shell hook is playback-only) |
| `afterwords/scripts/afterwords-post-llm.sh` | Shell hook script (chunked pipeline) |
| `afterwords/scripts/afterwords-tts-command.sh` | Command provider (async CLI / sync messaging) |
| `afterwords/scripts/chunk-text.py` | Sentence-boundary text chunker |
| `afterwords/scripts/strip-markdown.py` | Markdown stripper for TTS |
| `~/.afterwords` | Global voice config |
| `<project>/.afterwords` | Per-project voice config |
| `afterwords/voices/` | Voice profiles (JSON + reference WAV) |

---

## 7. Troubleshooting

| Symptom | Check |
|---------|-------|
| No voice on CLI | `afterwords status` — is server running? |
| No voice on Telegram | Check Hermes TTS provider config (`tts.provider: afterwords`) and platform delivery; the native hook intentionally skips messaging platforms |
| Wrong voice | Check project `.afterwords` then `~/.afterwords` — first match wins |
| Hook not loading | Ensure `HOOK.yaml` + `handler.py` in `~/.hermes/hooks/afterwords-tts/` |
| Native hook not updated | Restart gateway: `kill $(pgrep -f 'hermes.*gateway.*run')` then reconnect — hooks load at startup |
| Audio plays but first chunk delayed | Old un-chunked hook — both `afterwords-post-llm.sh` and `handler.py` should split text into ~200-char chunks |
| Shell hook blocked | `hermes hooks list` — should show `✓ allowed`. Set `hooks_auto_accept: true` |
| Shell hook timeout | The shell hook plays audio synchronously (blocks until afplay finishes); long responses can exceed the configured 60s timeout — raise `timeout: 120` in config.yaml or use the command provider instead |
| Server down silently | Both hooks exit silently when `/health` fails — check `afterwords status` |
