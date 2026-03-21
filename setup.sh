#!/usr/bin/env bash
#
# Voice Cloning Setup for Claude Code
#
# Gives Claude Code a cloned voice using Qwen3-TTS on Apple Silicon.
# Downloads a YouTube clip, extracts a 15-second reference, sets up
# the TTS server, and wires it into Claude Code as a Stop hook.
#
# Requirements: Apple Silicon Mac (M1+), 8 GB+ RAM, Python 3.11+
# Usage: bash setup.sh
#
set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*"; exit 1; }
ask()   { echo -en "${BOLD}$*${NC} "; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Temp file cleanup on any exit
TMPFILES=()
cleanup() { rm -f "${TMPFILES[@]}" 2>/dev/null; }
trap cleanup EXIT

# ── Step 0: Preflight checks ──────────────────────────────────────
echo
echo -e "${BOLD}Voice Cloning Setup for Claude Code${NC}"
echo -e "Gives Claude a cloned voice from a YouTube clip."
echo

# Apple Silicon check (allow Rosetta — MLX still works via arm64 Python)
ARCH=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)
if [[ "$ARCH" != *"Apple"* && "$(uname -m)" != "arm64" ]]; then
    fail "This requires Apple Silicon (M1/M2/M3/M4). Detected: ${ARCH}"
fi
ok "Apple Silicon detected"

# RAM check
RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
if ! [[ "$RAM_BYTES" =~ ^[0-9]+$ ]]; then
    warn "Could not detect RAM size. Proceeding anyway."
    RAM_GB="?"
else
    RAM_GB=$((RAM_BYTES / 1073741824))
    if [[ "$RAM_GB" -lt 8 ]]; then
        fail "Need 8 GB+ RAM. Detected: ${RAM_GB} GB"
    fi
fi
ok "${RAM_GB} GB RAM"

# Python check (need 3.11+)
if ! command -v python3 &>/dev/null; then
    fail "Python 3 not found. Install: brew install python"
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)')
if [[ "$PY_OK" != "1" ]]; then
    fail "Python 3.11+ required. Detected: ${PY_VER}. Upgrade: brew install python"
fi
ok "Python ${PY_VER}"

# ffmpeg check
if ! command -v ffmpeg &>/dev/null; then
    warn "ffmpeg not found — installing via Homebrew..."
    command -v brew &>/dev/null || fail "ffmpeg required. Install Homebrew first: https://brew.sh"
    brew install ffmpeg
fi
ok "ffmpeg"

# jq check
if ! command -v jq &>/dev/null; then
    warn "jq not found — installing via Homebrew..."
    command -v brew &>/dev/null || fail "jq required. Install Homebrew first: https://brew.sh"
    brew install jq
fi
ok "jq"

# yt-dlp check
if ! command -v yt-dlp &>/dev/null; then
    warn "yt-dlp not found — installing via pip..."
    pip3 install --user yt-dlp 2>/dev/null || pip install yt-dlp
fi
ok "yt-dlp"

# lame check (optional — for MP3 archiving)
if ! command -v lame &>/dev/null; then
    if command -v brew &>/dev/null; then
        warn "lame not found — installing via Homebrew (for MP3 archiving)..."
        brew install lame
    else
        warn "lame not found. Spoken responses won't be archived as MP3."
    fi
fi

echo

# ── Step 1: Python virtual environment ─────────────────────────────
info "Setting up Python environment..."
if [ -d ".venv" ]; then
    # Verify venv is functional
    if ! ".venv/bin/python3" -c "pass" 2>/dev/null; then
        warn "Existing .venv is broken — rebuilding..."
        rm -rf .venv
        python3 -m venv .venv
        ok "Rebuilt .venv"
    else
        ok ".venv exists and works"
    fi
else
    python3 -m venv .venv
    ok "Created .venv"
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet mlx-audio soundfile fastapi uvicorn noisereduce faster-whisper
ok "Python packages installed"
echo

# ── Step 2: Voice source ──────────────────────────────────────────
mkdir -p voices

if [ -z "$(ls voices/*-ref.wav 2>/dev/null)" ]; then
    info "No voice profiles found. Let's create one."
    echo
    echo -e "  You need a ${BOLD}YouTube URL${NC} with someone speaking."
    echo -e "  The setup will extract a 15-second clip for voice cloning."
    echo -e "  ${YELLOW}Tips:${NC} Choose a clip with clear speech, minimal background noise,"
    echo -e "  and one speaker. Interviews and monologues work best."
    echo
    ask "YouTube URL:"
    read -r YT_URL
    [ -z "$YT_URL" ] && fail "No URL provided"

    TMP_SRC="/tmp/voice-setup-source-$$.wav"
    TMPFILES+=("$TMP_SRC")

    info "Downloading audio..."
    if ! yt-dlp -x --audio-format wav -o "$TMP_SRC" "$YT_URL" 2>&1 | tail -5; then
        fail "Download failed. Check the URL and try again."
    fi

    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_SRC" | cut -d. -f1)
    info "Clip duration: ${DURATION}s"
    echo
    echo -e "  We need a ${BOLD}15-second${NC} segment with clear speech from one person."
    ask "Start time in seconds (default: 0):"
    read -r START_S
    START_S="${START_S:-0}"
    # Sanitise: must be a number
    [[ "$START_S" =~ ^[0-9]+$ ]] || fail "Start time must be a number"

    ask "Voice name (letters, numbers, hyphens only — e.g., galadriel, sam):"
    read -r VOICE_NAME
    VOICE_NAME="${VOICE_NAME:-default}"
    # Sanitise: alphanumeric and hyphens only, no path traversal
    VOICE_NAME=$(echo "$VOICE_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')
    [ -z "$VOICE_NAME" ] && VOICE_NAME="voice"

    TMP_SEG="/tmp/voice-setup-segment-$$.wav"
    TMPFILES+=("$TMP_SEG")

    info "Extracting reference (${START_S}s → $((START_S+15))s)..."
    ffmpeg -y -i "$TMP_SRC" -ss "$START_S" -t 15 -ar 24000 -ac 1 "$TMP_SEG" 2>/dev/null

    info "Denoising..."
    python3 - "$TMP_SEG" "voices/${VOICE_NAME}-ref.wav" <<'PYEOF'
import sys, soundfile as sf, noisereduce as nr, numpy as np
data, sr = sf.read(sys.argv[1])
reduced = nr.reduce_noise(y=data, sr=sr, stationary=True, prop_decrease=0.7)
peak = np.max(np.abs(reduced))
if peak > 0:
    reduced = reduced * (0.9 / peak)
sf.write(sys.argv[2], reduced, sr, subtype="PCM_16")
print(f"  {len(reduced)/sr:.1f}s saved")
PYEOF
    ok "Reference audio ready"

    info "Transcribing with Whisper..."
    REF_TEXT=$(python3 - "voices/${VOICE_NAME}-ref.wav" <<'PYEOF'
import sys
from faster_whisper import WhisperModel
model = WhisperModel("base.en", compute_type="int8")
segments, _ = model.transcribe(sys.argv[1])
print(" ".join(seg.text.strip() for seg in segments))
PYEOF
    ) || fail "Transcription failed. Is faster-whisper installed?"

    echo
    echo -e "  ${BOLD}Transcript:${NC}"
    echo -e "  ${CYAN}${REF_TEXT}${NC}"
    echo
    echo -e "  ${YELLOW}Important:${NC} Verify this matches exactly what you hear."
    ask "Press Enter to accept, or type a corrected transcript:"
    read -r CORRECTED
    [ -n "$CORRECTED" ] && REF_TEXT="$CORRECTED"

    # Save profile using Python for safe JSON serialisation (no shell interpolation)
    python3 - "$VOICE_NAME" "$YT_URL" "$REF_TEXT" "$START_S" <<'PYEOF'
import json, sys
name, url, text, start = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
with open(f"voices/{name}.json", "w") as f:
    json.dump({"name": name, "source_url": url, "reference_audio": f"{name}-ref.wav",
               "reference_text": text, "segment_start_s": start}, f, indent=2)
PYEOF
    ok "Voice profile saved: voices/${VOICE_NAME}.json"
else
    ok "Voice profiles found:"
    for f in voices/*.json; do
        [ -f "$f" ] || continue
        name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$f" 2>/dev/null || basename "$f" .json)
        echo -e "    ${CYAN}${name}${NC}"
    done
fi
echo

# ── Step 3: Server check ──────────────────────────────────────────
info "Checking server voice registry..."
VOICE_FILES=$(ls voices/*-ref.wav 2>/dev/null | wc -l | tr -d ' ')
ok "${VOICE_FILES} voice file(s) in voices/"
if grep -q "^VOICES = {" server.py 2>/dev/null; then
    ok "server.py has multi-voice support"
else
    warn "server.py may need updating for multi-voice support."
fi
echo

# ── Step 4: Claude Code hooks ─────────────────────────────────────
info "Setting up Claude Code voice hook..."

HOOKS_DIR="$HOME/.claude/hooks"
mkdir -p "$HOOKS_DIR"

# Back up existing hooks if present
for hookfile in strip-markdown.py tts-hook.sh tts-worker.sh; do
    if [ -f "$HOOKS_DIR/$hookfile" ]; then
        cp "$HOOKS_DIR/$hookfile" "$HOOKS_DIR/$hookfile.bak"
    fi
done

# Strip-markdown helper
cat > "$HOOKS_DIR/strip-markdown.py" <<'PYEOF'
"""Strip markdown formatting from stdin for cleaner TTS."""
import re, sys
text = sys.stdin.read()
text = re.sub(r'```[\s\S]*?```', '', text)
text = re.sub(r'`[^`]+`', '', text)
text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M)
text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.M)
text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
text = re.sub(r'\n{2,}', '. ', text)
text = re.sub(r'\s+', ' ', text).strip()
print(text[:1000])
PYEOF

# TTS hook (fires on Stop event)
cat > "$HOOKS_DIR/tts-hook.sh" <<'HOOKEOF'
#!/usr/bin/env bash
# Queue Claude's last response for TTS.
QUEUE="/tmp/claude-tts-queue.txt"
WORKER_PID="/tmp/claude-tts-worker.pid"
WORKER="$HOME/.claude/hooks/tts-worker.sh"

TEXT=$(jq -r '.last_assistant_message // empty' 2>/dev/null \
    | python3 "$HOME/.claude/hooks/strip-markdown.py" 2>/dev/null)
[ -z "$TEXT" ] && exit 0

echo "$TEXT" >> "$QUEUE"

if [ -f "$WORKER_PID" ]; then
    EXISTING=$(cat "$WORKER_PID" 2>/dev/null)
    if [ -n "$EXISTING" ] && kill -0 "$EXISTING" 2>/dev/null; then
        exit 0
    fi
    rm -f "$WORKER_PID"
fi

nohup bash "$WORKER" >/dev/null 2>&1 &
HOOKEOF
chmod +x "$HOOKS_DIR/tts-hook.sh"

# TTS worker (processes queue)
cat > "$HOOKS_DIR/tts-worker.sh" <<'WORKEREOF'
#!/usr/bin/env bash
set -uo pipefail

QUEUE="/tmp/claude-tts-queue.txt"
PIDFILE="/tmp/claude-tts-worker.pid"
LOCKDIR="/tmp/claude-tts-worker.lock"
TTS_URL="http://localhost:7860/synthesize"
ARCHIVE_DIR="$HOME/.claude/tts-archive"
MAX_QUEUE=10

mkdir -p "$ARCHIVE_DIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
    if [ -f "$PIDFILE" ]; then
        HOLDER=$(cat "$PIDFILE" 2>/dev/null)
        if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
            exit 0
        fi
        rm -rf "$LOCKDIR"
        mkdir "$LOCKDIR" 2>/dev/null || exit 0
    else
        exit 0
    fi
fi

echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"; rm -rf "$LOCKDIR"' EXIT

while true; do
    [ -f "$QUEUE" ] || break
    [ -s "$QUEUE" ] || break

    LINE=$(head -1 "$QUEUE" 2>/dev/null)
    [ -z "$LINE" ] && break

    REMAINING=$(tail -n +2 "$QUEUE" 2>/dev/null)
    if [ -n "$REMAINING" ]; then
        echo "$REMAINING" > "$QUEUE.tmp" && mv "$QUEUE.tmp" "$QUEUE"
    else
        rm -f "$QUEUE"
    fi

    if [ -f "$QUEUE" ]; then
        LINES=$(wc -l < "$QUEUE" 2>/dev/null | tr -d ' ')
        if [ "${LINES:-0}" -gt "$MAX_QUEUE" ]; then
            tail -n "$MAX_QUEUE" "$QUEUE" > "$QUEUE.tmp" && mv "$QUEUE.tmp" "$QUEUE"
        fi
    fi

    ENCODED=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$LINE" 2>/dev/null) || continue
    STAMP=$(date +%Y%m%d-%H%M%S)

    # Per-project voice: .claude-voice file in cwd, else server default
    VOICE=""
    if [ -f ".claude-voice" ]; then
        VOICE=$(head -1 .claude-voice 2>/dev/null | tr -d '[:space:]')
    fi
    if [ -z "$VOICE" ]; then
        VOICE=$(curl -s --max-time 2 "${TTS_URL%/synthesize}/health" 2>/dev/null \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_voice','claude'))" 2>/dev/null || echo "claude")
    fi
    VOICE_PARAM=""
    [ -n "$VOICE" ] && VOICE_PARAM="&voice=${VOICE}"

    WAVFILE="/tmp/claude-tts-$$.wav"
    if curl -s --max-time 90 "${TTS_URL}?text=${ENCODED}${VOICE_PARAM}" -o "$WAVFILE" 2>/dev/null; then
        FILESIZE=$(stat -f%z "$WAVFILE" 2>/dev/null || echo 0)
        if [ "$FILESIZE" -gt 1000 ]; then
            TRIMMED="/tmp/claude-tts-trimmed-$$.wav"
            if ffmpeg -y -ss 0.1 -i "$WAVFILE" -c copy "$TRIMMED" 2>/dev/null; then
                mv "$TRIMMED" "$WAVFILE"
            fi
            rm -f "$TRIMMED"
            lame --quiet -V 2 "$WAVFILE" "$ARCHIVE_DIR/${VOICE}-${STAMP}.mp3" 2>/dev/null
            afplay "$WAVFILE" 2>/dev/null
        fi
    fi
    rm -f "$WAVFILE"
done

rm -f "$QUEUE" "$QUEUE.tmp"
WORKEREOF
chmod +x "$HOOKS_DIR/tts-worker.sh"

ok "Hook scripts installed (backups saved as *.bak)"

# ── Step 5: Wire into Claude Code settings ─────────────────────────
SETTINGS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"

HOOK_CMD="bash ~/.claude/hooks/tts-hook.sh"

if [ -f "$SETTINGS" ]; then
    if jq -e ".hooks.Stop[]?.hooks[]? | select(.command == \"$HOOK_CMD\")" "$SETTINGS" &>/dev/null; then
        ok "TTS hook already configured in settings.json"
    elif jq -e '.hooks.Stop' "$SETTINGS" &>/dev/null; then
        info "Appending TTS hook to existing Stop hooks..."
        TMPF=$(mktemp)
        TMPFILES+=("$TMPF")
        jq ".hooks.Stop[0].hooks += [{\"type\": \"command\", \"command\": \"$HOOK_CMD\", \"timeout\": 120, \"async\": true}]" "$SETTINGS" > "$TMPF" \
            && mv "$TMPF" "$SETTINGS"
        ok "TTS hook appended to existing Stop hooks"
    else
        info "Adding Stop hook to settings.json..."
        TMPF=$(mktemp)
        TMPFILES+=("$TMPF")
        jq ".hooks.Stop = [{\"hooks\": [{\"type\": \"command\", \"command\": \"$HOOK_CMD\", \"timeout\": 120, \"async\": true}]}]" "$SETTINGS" > "$TMPF" \
            && mv "$TMPF" "$SETTINGS"
        ok "Stop hook added"
    fi
else
    info "Creating settings.json with Stop hook..."
    cat > "$SETTINGS" <<SETTINGSEOF
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "$HOOK_CMD",
        "timeout": 120,
        "async": true
      }]
    }]
  }
}
SETTINGSEOF
    ok "settings.json created"
fi
echo

# ── Step 6: launchd service ────────────────────────────────────────
info "Setting up auto-start service..."

PLIST_NAME="com.claude-voice.tts-server"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"

cat > "$PLIST_PATH" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_PYTHON}</string>
        <string>${SCRIPT_DIR}/server.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key>
    <string>/tmp/claude-tts-server.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/claude-tts-server.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
ok "TTS server will auto-start on login"
echo

# ── Step 7: Verify ────────────────────────────────────────────────
info "Waiting for server..."
SERVER_OK=false
for i in $(seq 1 60); do
    if curl -s --max-time 2 http://localhost:7860/health | jq -e '.ready == true' &>/dev/null; then
        SERVER_OK=true
        break
    fi
    sleep 1
done

echo
if $SERVER_OK; then
    echo -e "${BOLD}${GREEN}━━━ Setup Complete ━━━${NC}"
else
    echo -e "${BOLD}${YELLOW}━━━ Setup Partially Complete ━━━${NC}"
    echo
    echo -e "  ${YELLOW}The TTS server is still starting (model download may be in progress).${NC}"
    echo -e "  Check: ${CYAN}curl http://localhost:7860/health${NC}"
    echo -e "  Logs:  ${CYAN}tail -f /tmp/claude-tts-server.log${NC}"
fi
echo
echo -e "  ${BOLD}TTS Server:${NC}    http://localhost:7860"
echo -e "  ${BOLD}Test:${NC}          curl \"http://localhost:7860/synthesize?text=Hello\" -o test.wav && afplay test.wav"
echo -e "  ${BOLD}Logs:${NC}          tail -f /tmp/claude-tts-server.log"
echo -e "  ${BOLD}Archives:${NC}      ls ~/.claude/tts-archive/"
echo
echo -e "  Claude Code will now ${BOLD}speak every response${NC}."
echo -e "  Pair with ${CYAN}/voice${NC} (hold Space to dictate) for full voice conversations."
echo
echo -e "  To add more voices:  ${CYAN}bash clone-voice.sh${NC}"
echo -e "  To change the voice: edit ${CYAN}DEFAULT_VOICE${NC} in server.py and restart"
echo -e "  To stop the voice:   ${CYAN}launchctl unload ~/Library/LaunchAgents/${PLIST_NAME}.plist${NC}"
echo
