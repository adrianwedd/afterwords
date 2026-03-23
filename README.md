# Afterwords — Local Voice-Cloning TTS Server

**[Listen to the voice demos →](https://adrianwedd.github.io/afterwords/)**

Clone any voice from a 15-second YouTube clip and run it locally on your Mac. Use it as a standalone TTS API, or pair it with Claude Code to hear every response spoken aloud. 18 voices included.

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

## Without Claude Code

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

## Switching Voices

**Per-project** — drop a `.afterwords` file in any repo:

```bash
echo "snape" > .afterwords     # this project uses Snape
echo "galadriel" > .afterwords # this one uses Galadriel
```

The hook reads this before each synthesis. No server restart needed.

**Global default** — edit `DEFAULT_VOICE` in `server.py` and restart:

```bash
afterwords restart
```

**Per-request:**

```bash
curl "http://localhost:7860/synthesize?text=Hello&voice=samantha" -o hello.wav
```

Newly cloned voices are auto-discovered on server restart — no code edits needed to register them. Voice reference files are created during setup (not shipped in the repo).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Your Mac (Apple Silicon, 8 GB+)                            │
│                                                             │
│  ┌─────────────────────────┐                                │
│  │  Qwen3-TTS Server       │  ← MLX 8-bit, ~6 GB peak      │
│  │  localhost:7860          │  ← 15 voice profiles           │
│  │  /synthesize?text=...    │  ← ~20s per sentence           │
│  └─────────┬───────────────┘                                │
│            │                                                │
│  ┌─────────┴───────────────┐  ┌──────────────────────────┐  │
│  │  Claude Code Stop Hook  │  │  Claude Code /voice      │  │
│  │  ~/.claude/hooks/       │  │  (hold Space to dictate) │  │
│  │  tts-hook.sh            │  │  Speech → Text input     │  │
│  │  Text → Speech output   │  │  (built-in)              │  │
│  └─────────────────────────┘  └──────────────────────────┘  │
│                                                             │
│  Together: full voice conversation with Claude Code          │
└─────────────────────────────────────────────────────────────┘
```

**`/voice`** handles input: you speak, Claude hears text.
**This project** handles output: Claude responds, you hear speech.

## How It Works

### Voice Cloning (Zero-Shot)

No training or fine-tuning. [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) Base extracts a speaker embedding from a 15-second reference clip and generates new speech in that voice. The model runs on [MLX](https://github.com/ml-explore/mlx) — Apple's ML framework that fits the 0.6B model in 6 GB of unified memory.

### The Server

FastAPI + Uvicorn serving WAV audio over HTTP. The model loads once at startup; each voice is a reference WAV + transcript string. All synthesis serialised via a threading lock (MLX Metal crashes on concurrent GPU access).

```
GET /health
  → {"status":"ok", "ready":true, "voices":["galadriel","samantha",...]}

GET /synthesize?text=Hello&voice=galadriel
  → audio/wav (16-bit PCM)
  → 400 if voice unknown (returns available voices)
  → 503 if warming up
```

### The Hook

Claude Code's [Stop hook](https://docs.anthropic.com/en/docs/claude-code/hooks) fires after every response. The hook extracts the response text, strips markdown, queues it for synthesis, and plays the result through your speakers. A background worker with `mkdir`-based locking (macOS has no `flock`) prevents overlapping audio.

### The Queue

Fast Claude conversations generate responses faster than TTS can synthesise. The worker processes a queue (max 10 entries), trimming oldest entries when it overflows. Each response is also archived as MP3 in `~/.claude/tts-archive/` (requires `lame`).

## Requirements

- Apple Silicon Mac (M1/M2/M3/M4), 8 GB+ RAM
- Python 3.11+
- ~2 GB disk (model weights + venv)
- Claude Code (optional — for automatic TTS on responses; setup offers to install it)

## File Map

```
afterwords/
├── setup.sh              ← one-command setup (detects/installs Claude Code)
├── afterwords.sh         ← CLI for server management (symlinked to PATH)
├── clone-voice.sh        ← add more voices from YouTube
├── server.py             ← multi-voice TTS server
├── strip_markdown.py     ← text cleaner for TTS (also used by hooks)
├── tests/                ← pytest suite (26 tests, no GPU needed)
├── voices/
│   ├── galadriel-ref.wav ← 15s reference (Cate Blanchett, LOTR)
│   ├── samantha-ref.wav  ← (Scarlett Johansson, Her)
│   ├── avasarala-ref.wav ← (Shohreh Aghdashloo, The Expanse)
│   ├── vesper-ref.wav    ← (Eva Green, Casino Royale)
│   └── ...               ← 18 voices included
└── README.md

~/.claude/                    ← only with Claude Code integration
├── settings.json         ← Stop hook registered here
└── hooks/
    ├── tts-hook.sh       ← queue response for TTS
    ├── tts-worker.sh     ← process queue, play audio
    └── strip-markdown.py ← clean text for TTS

~/Library/LaunchAgents/
└── com.afterwords.tts-server.plist  ← auto-start on login
```

## Included Voices

| Voice | Source | Character |
|-------|--------|-----------|
| galadriel | Cate Blanchett, *LOTR* | Ethereal, ancient, otherworldly |
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
| picard | Patrick Stewart, *Star Trek* | Authoritative, measured |
| ronan | Ronan Keating, interview | Soft Irish, reflective |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No voice after Claude responds | `afterwords status` — if dead: `afterwords start` |
| "warming up" 503 | Wait ~30s after restart for model load + warmup |
| Voice sounds wrong/garbled | Re-clone with a better reference clip; verify transcript accuracy |
| 40+ seconds per request | Restart the server (model may be reloading per-request) |
| `/voice` not working | Enable with `/voice` command in Claude Code; requires Claude.ai account |
| Hook not firing | Open `/hooks` in Claude Code to verify; or restart session |
| New voice not available | Restart the server — voices are discovered on startup |
| Port 7860 already in use | Another instance is running, or another app uses the port |
| Model download fails | Check network; retry `python server.py` manually |
| MP3 archives missing | Install `lame` via `brew install lame` |

## Testing

```bash
pip install pytest httpx
pytest
```

Tests cover the server API (endpoint validation, error handling, voice resolution) and the strip-markdown text transform (every regex pattern, plus a golden test with a realistic Claude response). The server tests mock the ML model — no GPU or model download needed.

Run a single test:

```bash
pytest tests/test_strip_markdown.py::test_inline_code_keeps_content
```

## Managing the Server

```bash
afterwords start       # start the TTS server
afterwords stop        # stop the TTS server
afterwords restart     # restart after config changes
afterwords status      # show health, PID, loaded voices
afterwords logs        # tail the server log
afterwords voices      # list available voices
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

On 8 GB M1 MacBook Air:
- Model load: ~5s (cached) / ~5 min (first run, downloading 1.5 GB)
- Warmup synthesis: ~15s
- Per request: ~15s fixed overhead + ~0.5x real-time (~20s typical)
- Peak memory: ~6 GB
- Adding voices: zero extra memory (each is just a 700 KB WAV)

## Credits

- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) by Alibaba (Apache 2.0)
- [mlx-audio](https://github.com/Blaizzy/mlx-audio) by Blaizzy
- [MLX](https://github.com/ml-explore/mlx) by Apple
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/) by Anthropic
- Voice reference clips used under fair use for personal voice synthesis research

## Related

- [Voice Cloning with Qwen3-TTS and MLX on Apple Silicon](https://adrianwedd.com/blog/voice-cloning-qwen3-tts-mlx/) — the full tutorial
- [Giving a Robot Three Voices](https://adrianwedd.com/blog/giving-a-robot-three-voices/) — SPARK's multi-backend TTS architecture
- [SPARK](https://spark.wedd.au) — the robot this was built for
