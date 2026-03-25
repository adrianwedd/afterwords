---
name: afterwords
description: "Local voice-cloning TTS for Claude Code on Apple Silicon. Use this skill whenever the user wants to speak text aloud, synthesize speech, play audio of text, hear something in a character voice, list or preview available voices, clone a new voice from YouTube, check TTS server status, set a per-project voice, or configure agent-to-voice mappings. Also use when the user mentions 'afterwords', 'TTS', 'text to speech', 'voice clone', 'speak this', 'say this', 'read aloud', or asks about available character voices."
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
research-analyst: clara-oswald
benchmark-operator: amy-pond
```

The `default:` key is the fallback. Agent names map to Claude Code subagent types (from the Stop hook's `agent_type` field). Built-in types like `Explore`, `Plan`, and `general-purpose` are silently skipped by the hook.

To set a project voice, write or edit `.afterwords` in the project root. Restart is not needed — the hook reads it fresh each time.

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

## Constraints

- Apple Silicon Mac only (M1+), macOS, 8GB+ RAM
- Model peaks at ~6GB unified memory — no concurrent models on 8GB machines
- All synthesis is serialised (one request at a time) — MLX Metal crashes on concurrent GPU access
- Max text length: 5000 characters per request
- Audio output: 24kHz mono WAV (PCM_16)
