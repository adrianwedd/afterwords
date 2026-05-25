---
name: afterwords
description: "Local voice-cloning TTS on Apple Silicon. Trigger when the user wants to: speak/say/read text aloud, synthesize speech, hear a voice sample, list or preview voices, clone a voice from YouTube or audio, check or fix TTS server issues, set a per-project voice (.afterwords file), configure agent-to-voice mappings, use the emotion palette API, or programmatically clone via POST /clone. Keywords: afterwords, TTS, text-to-speech, voice clone, speak this, say this, read aloud, voice preview. Do NOT trigger for: general audio editing, music, speech-to-text/transcription, or unrelated server tasks."
---

# Afterwords — Local Voice-Cloning TTS

Afterwords is a local TTS server running Qwen3-TTS (0.6B, 8-bit quantised) on Apple Silicon via MLX. It does zero-shot voice cloning from ~15-second reference WAVs — no fine-tuning, no cloud API, all on-device.

The server runs on `localhost:7860` managed by launchd. The CLI is `afterwords` (or `bash <repo>/afterwords.sh` if not symlinked).

## Quick reference

| What | How |
|------|-----|
| Speak text | `curl "localhost:7860/synthesize?text=Hello&voice=galadriel" -o /tmp/tts.wav && afplay /tmp/tts.wav` |
| Server health | `curl -s localhost:7860/health` |
| List voices | `curl -s localhost:7860/health \| python3 -c "import sys,json; [print(v) for v in sorted(json.load(sys.stdin)['voices'])]"` |
| Start server | `bash <repo>/afterwords.sh start` |
| Stop server | `bash <repo>/afterwords.sh stop` |
| Restart server | `bash <repo>/afterwords.sh restart` |
| Server status | `bash <repo>/afterwords.sh status` |
| Clone voice | `bash <repo>/clone-voice.sh "https://youtube.com/watch?v=..." voicename 30` |
| Tail logs | `bash <repo>/afterwords.sh logs` |

Replace `<repo>` with the afterwords repo path (find it with: `find ~/repos -name afterwords.sh -path "*/afterwords/*" -not -path "*/.venv/*" 2>/dev/null | head -1 | xargs dirname`).

## Speaking text aloud

To synthesize and play text:

1. Check the server is running: `curl -s localhost:7860/health`
2. If not running, start it: `bash <repo>/afterwords.sh start` (wait ~15s for model warmup)
3. Synthesize: `curl -s "localhost:7860/synthesize?text=<url-encoded-text>&voice=<voice>" -o /tmp/afterwords-output.wav`
4. Play: `afplay /tmp/afterwords-output.wav`

The `/synthesize` endpoint accepts:
- `text` (required): up to 5000 characters
- `voice` (optional): voice name from the loaded voices list; defaults to `galadriel`

For long text (>500 chars), synthesis can take 30-60 seconds. The server serialises all synthesis requests — MLX Metal is not thread-safe.

When the user asks to "speak" or "say" something, always use the full flow: synthesize to a temp WAV, then play with `afplay`. URL-encode the text parameter properly — use Python's `urllib.parse.quote()` for text with special characters.

## Voice selection

Voices are loaded from `<repo>/voices/` — each voice is a `{name}-ref.wav` (reference clip) + `{name}.json` (metadata with transcript). The server auto-discovers them at startup.

To help the user pick a voice, query `/health` and show the voice list. The shipped voices include characters from film, TV, and sci-fi — suggest voices that match the tone the user wants (e.g., authoritative → picard/galadriel, playful → loki/depp, robotic → k9/data).

## Per-project voice override

A `.afterwords` file in any repo root sets the default voice for that project. Two formats:

**Simple (single voice):**
```
galadriel
```

**Agent mapping (one per line):**
```
default: the-doctor
hermes: seven-of-nine
research-analyst: clara-oswald
benchmark-operator: amy-pond
```

The `default:` key is the fallback. Agent names map to the agent processing the request:
- **Hermes hook:** uses `hermes` as the agent key
- **Claude Code hook:** uses the subagent type from the Stop event's `agent_type` field (built-in types like `Explore`, `Plan`, `general-purpose` are silently skipped)

### Voice resolution for Hermes Agent

The Hermes hook resolves voice in this priority order (first match wins):

1. **Project `.afterwords`** — looks for `hermes:` in mapping mode, then `default:`, then simple voice
2. **Global `~/.afterwords`** — same format, same resolution logic
3. **Server default** — whatever the Afterwords server returns from `/health`

To set a Hermes-specific voice:

- **Per-project:** add `hermes: voice-name` to the project's `.afterwords`
- **Global fallback:** edit `~/.afterwords` and add `hermes: voice-name`

No restart needed — the hook reads `.afterwords` files fresh on every response.

### Example `~/.afterwords` (global)

```
# Global default for Hermes Agent
default: galadriel
hermes: seven-of-nine
```

### Example project `.afterwords` (per-repo)

```
default: picard
hermes: spock
```

When Hermes is running in a project directory with a `.afterwords` file, the project file takes precedence over the global `~/.afterwords`.

## Hermes Agent integration

Afterwords integrates with Hermes Agent via **three mechanisms**, each covering different use cases:

### 1. TTS command provider (recommended for messaging + explicit TTS)

Afterwords is registered as a command-type TTS provider in `~/.hermes/config.yaml`. This powers `/voice tts`, the `text_to_speech` tool, and messaging-platform audio delivery.

Config (already set up):
```yaml
tts:
  provider: afterwords
  providers:
    afterwords:
      type: command
      command: 'bash ~/repos/afterwords/scripts/afterwords-tts-command.sh {input_path} {output_path} {voice}'
      output_format: wav
```

The command script (`scripts/afterwords-tts-command.sh`) automatically resolves voice from `.afterwords` files:
- **CLI sessions:** writes a silent placeholder WAV immediately (text output not delayed), then synthesizes + plays via `afplay` in a detached background subshell; archives MP3 + text sidecar to `~/.hermes/tts-archive/`
- **Messaging platforms (Telegram/Discord):** runs synchronously, writes real audio to `{output_path}` for attachment delivery
- If `{voice}` is empty, resolves from project `.afterwords` (hermes key → default:) → global `~/.afterwords` → server default
- Strips basic markdown and truncates to 1000 chars before synthesis

To switch back to Edge TTS: `hermes config set tts.provider edge`

### 2. Shell/native hooks (auto-speak local CLI sessions)

The shell hook in `~/.hermes/config.yaml` fires on `post_llm_call` for direct Hermes CLI sessions. The native `afterwords-tts` hook at `~/.hermes/hooks/afterwords-tts/` fires on `agent:end` events and currently speaks only local/CLI platform contexts. These hooks:
- Strips markdown from responses before speaking
- Truncates to 1000 characters before synthesis
- Resolves voice from `.afterwords` files (project → global → server default)
- Plays via `afplay` on macOS
- Skip messaging platforms to avoid double-speech (the command provider handles those)
- Fails silently if the Afterwords server isn't running

The native hook uses `TERMINAL_CWD` env var for project-level voice resolution when event context does not include a working directory. Restart gateway after native hook changes: `hermes gateway restart`

### 3. Explicit synthesis helpers

For manual or skill-driven use:

```bash
# Speak.sh — resolves voice from .afterwords files
bash <repo>/skill/scripts/speak.sh "Hello, I am Hermes." seven-of-nine

# Or use the text_to_speech tool in a Hermes session (uses the command provider)
```

### Switching voices

- **Per-project:** add `hermes: voice-name` to the project's `.afterwords`
- **Global fallback:** edit `~/.afterwords` and set `hermes: voice-name`
- **Temporary:** use `/voice tts` in a session to toggle auto-speak on/off

## Cloning a new voice

Use `clone-voice.sh` to create a voice from a YouTube video:

```bash
bash <repo>/clone-voice.sh "https://youtube.com/watch?v=..." voicename [start_seconds]
```

- Downloads audio via `yt-dlp`
- Extracts a ~15s segment starting at `start_seconds` (default: 30)
- Denoises with `noisereduce`
- Transcribes with `faster-whisper`
- Creates `voices/{name}-ref.wav` + `voices/{name}.json`
- Restart the server after cloning: `bash <repo>/afterwords.sh restart`

Tips for good clones:
- Pick segments with solo speech, no background music or other speakers
- 10-20 seconds of clear, expressive speech works best
- Emotional/dramatic deliveries clone better than flat narration
- The transcript in the JSON must accurately match the audio — mismatches degrade clone quality

## Server management

The server runs as a launchd service (`com.afterwords.tts-server`) that auto-starts on login and auto-restarts on crash. Model warmup takes ~15 seconds after start.

If the server doesn't respond:
1. Check status: `bash <repo>/afterwords.sh status`
2. Check logs: `bash <repo>/afterwords.sh logs`
3. Restart: `bash <repo>/afterwords.sh restart`
4. If launchd issues: `launchctl unload ~/Library/LaunchAgents/com.afterwords.tts-server.plist && launchctl load ~/Library/LaunchAgents/com.afterwords.tts-server.plist`

## Voice preview

To preview a voice, synthesize a short sample and play it:

```bash
bash <repo>/skill/scripts/speak.sh "You are absolutely right. Your Claude Code session could sound like me." snape
```

To preview all voices, query `/health` for the voice list and loop through:

```bash
for voice in $(curl -s localhost:7860/health | python3 -c "import sys,json; print(' '.join(sorted(json.load(sys.stdin)['voices'])))"); do
  echo "Playing: $voice"
  bash <repo>/skill/scripts/speak.sh "Hello, I am $voice." "$voice"
done
```

When a user asks to "hear" or "preview" a voice, synthesize a characteristic line and play it. Suggest voices based on the user's tone preference (authoritative: picard, attenborough, galadriel; playful: loki, depp; warm: eartha, samantha; robotic: data, k9; sci-fi: spock, han-solo).

## Programmatic cloning (--allow-clone)

When the server is started with `--allow-clone`, three additional endpoints are available. These are for programmatic/API-based cloning — distinct from the CLI `clone-voice.sh` which creates permanent voices.

**POST /clone** — Upload audio to create a session voice:
```bash
curl -X POST localhost:7860/clone \
  -F "audio=@sample.wav" \
  -F "session_id=my-voice" \
  -F "emotion=neutral"
```
Parameters: `audio` (WAV upload, required), `session_id` (required), `emotion` (optional, default "neutral"), `transcript` (optional, auto-transcribed if omitted).

**POST /synthesize** — JSON body with emotion support:
```bash
curl -X POST localhost:7860/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "voice": "my-voice", "emotion": "cheerful"}'
```
The `emotion` parameter selects a matching palette entry for the given session. Falls back to the best-quality entry if no match.

**DELETE /session/{session_id}** — Clean up session voices:
```bash
curl -X DELETE localhost:7860/session/my-voice
```

Session voices are ephemeral. Use `clone-voice.sh` for permanent voices that persist across server restarts.

## Constraints

- Apple Silicon Mac only (M1+), macOS, 16 GB+ RAM (32 GB recommended)
- Model peaks at ~6GB unified memory — no concurrent models on 8GB machines
- All synthesis is serialised (one request at a time) — MLX Metal crashes on concurrent GPU access
- Max text length: 5000 characters per request
- Audio output: 24kHz mono WAV (PCM_16)
- `--allow-clone` endpoints require the server to be started with that flag (auto-binds to 127.0.0.1 for security)
