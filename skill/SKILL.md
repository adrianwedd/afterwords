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

- Apple Silicon Mac only (M1+), macOS, 8GB+ RAM
- Model peaks at ~6GB unified memory — no concurrent models on 8GB machines
- All synthesis is serialised (one request at a time) — MLX Metal crashes on concurrent GPU access
- Max text length: 5000 characters per request
- Audio output: 24kHz mono WAV (PCM_16)
- `--allow-clone` endpoints require the server to be started with that flag (auto-binds to 127.0.0.1 for security)
