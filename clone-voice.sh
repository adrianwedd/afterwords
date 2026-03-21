#!/usr/bin/env bash
#
# Clone a voice from a YouTube clip.
#
# Usage:
#   bash clone-voice.sh                       # interactive
#   bash clone-voice.sh URL NAME [START]      # semi-interactive (confirms transcript)
#   bash clone-voice.sh URL NAME START --yes  # fully non-interactive
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source .venv/bin/activate 2>/dev/null || { echo "Run setup.sh first"; exit 1; }

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*"; exit 1; }
ask()   { echo -en "${BOLD}$*${NC} "; }

YT_URL="${1:-}"
VOICE_NAME="${2:-}"
START_S="${3:-}"
AUTO_YES=false
[[ "${4:-}" == "--yes" ]] && AUTO_YES=true

# Temp file cleanup
TMPFILES=()
cleanup() { rm -f "${TMPFILES[@]}" 2>/dev/null; }
trap cleanup EXIT

echo
echo -e "${BOLD}Voice Cloner${NC} — extract a voice from a YouTube clip"
echo

# Get URL
if [ -z "$YT_URL" ]; then
    ask "YouTube URL:"
    read -r YT_URL
fi
[ -z "$YT_URL" ] && fail "No URL"

# Get voice name
if [ -z "$VOICE_NAME" ]; then
    ask "Voice name (letters, numbers, hyphens — e.g., galadriel, sam):"
    read -r VOICE_NAME
fi
# Sanitise: alphanumeric and hyphens only
VOICE_NAME=$(echo "${VOICE_NAME:-voice}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')
[ -z "$VOICE_NAME" ] && VOICE_NAME="voice"

# Download
info "Downloading audio..."
TMP_SRC="/tmp/clone-source-$$.wav"
TMPFILES+=("$TMP_SRC")
if ! yt-dlp -x --audio-format wav -o "$TMP_SRC" "$YT_URL" 2>&1 | tail -5; then
    fail "Download failed. Check the URL is valid and not private/age-restricted."
fi
DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_SRC" | cut -d. -f1)
ok "Downloaded (${DURATION}s)"

# Get start time
if [ -z "$START_S" ]; then
    echo
    echo -e "  Clip is ${BOLD}${DURATION}s${NC} long. We need a 15-second segment."
    echo -e "  Choose a section with ${BOLD}clear speech from one person${NC}."
    echo
    ask "Start time in seconds (default: 0):"
    read -r START_S
fi
START_S="${START_S:-0}"
[[ "$START_S" =~ ^[0-9]+$ ]] || fail "Start time must be a number"

# Extract + denoise
info "Extracting ${START_S}s → $((START_S + 15))s..."
TMP_SEG="/tmp/clone-segment-$$.wav"
TMPFILES+=("$TMP_SEG")
ffmpeg -y -i "$TMP_SRC" -ss "$START_S" -t 15 -ar 24000 -ac 1 "$TMP_SEG" 2>/dev/null

info "Denoising..."
mkdir -p voices
python3 - "$TMP_SEG" "voices/${VOICE_NAME}-ref.wav" <<'PYEOF'
import sys, soundfile as sf, noisereduce as nr, numpy as np
data, sr = sf.read(sys.argv[1])
reduced = nr.reduce_noise(y=data, sr=sr, stationary=True, prop_decrease=0.7)
peak = np.max(np.abs(reduced))
if peak > 0:
    reduced = reduced * (0.9 / peak)
sf.write(sys.argv[2], reduced, sr, subtype="PCM_16")
print(f"  {len(reduced)/sr:.1f}s, RMS={np.sqrt(np.mean(reduced**2)):.4f}")
PYEOF
ok "Reference saved: voices/${VOICE_NAME}-ref.wav"

# Transcribe
info "Transcribing..."
REF_TEXT=$(python3 - "voices/${VOICE_NAME}-ref.wav" <<'PYEOF'
import sys
try:
    from faster_whisper import WhisperModel
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "faster-whisper"])
    from faster_whisper import WhisperModel
model = WhisperModel("base.en", compute_type="int8")
segments, _ = model.transcribe(sys.argv[1])
print(" ".join(seg.text.strip() for seg in segments))
PYEOF
) || fail "Transcription failed"

if ! $AUTO_YES; then
    echo
    echo -e "  ${BOLD}Transcript:${NC}"
    echo -e "  ${CYAN}${REF_TEXT}${NC}"
    echo
    echo -e "  ${YELLOW}Verify this matches what you hear!${NC} Wrong transcripts = garbled voice."
    ask "Press Enter to accept, or type corrected transcript:"
    read -r CORRECTED
    [ -n "$CORRECTED" ] && REF_TEXT="$CORRECTED"
else
    echo -e "  Transcript: ${CYAN}${REF_TEXT}${NC}"
fi

# Save profile (safe JSON serialisation via Python — no shell interpolation)
python3 - "$VOICE_NAME" "$YT_URL" "$REF_TEXT" "$START_S" <<'PYEOF'
import json, sys
name, url, text, start = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
with open(f"voices/{name}.json", "w") as f:
    json.dump({"name": name, "source_url": url, "reference_audio": f"{name}-ref.wav",
               "reference_text": text, "segment_start_s": start}, f, indent=2)
PYEOF
ok "Profile saved: voices/${VOICE_NAME}.json"

# Test
echo
info "Testing synthesis..."
TEST_WAV="/tmp/clone-test-$$.wav"
TMPFILES+=("$TEST_WAV")
if curl -s --max-time 120 \
    "http://localhost:7860/synthesize?text=Hello.+I+am+${VOICE_NAME}.&voice=${VOICE_NAME}" \
    -o "$TEST_WAV" 2>/dev/null; then
    FSIZE=$(stat -f%z "$TEST_WAV" 2>/dev/null || echo 0)
    if [ "$FSIZE" -gt 1000 ]; then
        ok "Synthesis works!"
        afplay "$TEST_WAV" 2>/dev/null &
    elif [ "$FSIZE" -gt 0 ]; then
        # Might be a JSON error response
        BODY=$(cat "$TEST_WAV" 2>/dev/null)
        if echo "$BODY" | jq -e '.error' &>/dev/null; then
            ERR=$(echo "$BODY" | jq -r '.error')
            warn "Server returned error: ${ERR}"
        else
            warn "Server returned small file (${FSIZE} bytes). Voice may need adding to VOICES in server.py."
        fi
    else
        warn "Server returned empty response."
    fi
else
    warn "Server not responding at localhost:7860. Start it with: python server.py"
fi

echo
echo -e "${GREEN}━━━ Voice cloned ━━━${NC}"
echo
echo -e "  To use: ${CYAN}curl \"http://localhost:7860/synthesize?text=Hello&voice=${VOICE_NAME}\"${NC}"
echo -e "  To make default: edit ${CYAN}DEFAULT_VOICE${NC} in server.py and restart"
echo
