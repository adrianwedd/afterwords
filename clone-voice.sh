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

# Single source of truth for local-file-vs-URL detection (shared by the
# real flow below and the --check-source test hook). Strips an optional
# file:// scheme, then tests for an existing file.
_is_local_source() { [ -f "${1#file://}" ]; }

# Test hook: print the resolved source kind and exit before any venv/IO work.
if [[ " $* " == *" --check-source "* ]]; then
    if _is_local_source "${1:-}"; then echo "local-file"; else echo "youtube"; fi
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source .venv/bin/activate 2>/dev/null || { echo -e "\033[0;31m✗\033[0m Run setup.sh first"; exit 1; }
python3 -c "import faster_whisper" 2>/dev/null || {
    echo -e "\033[0;31m✗\033[0m Cloning deps not installed. Run: pip install -r requirements-clone.txt"
    exit 1
}

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; DIM='\033[2m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "  ${CYAN}▸${NC} $*"; }
ok()    { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "  ${RED}✗${NC} $*"; exit 1; }
ask()   { echo -en "  ${BOLD}$*${NC} "; }
rule()  { echo -e "${DIM}  ─────────────────────────────────────────${NC}"; }

_T0=$(date +%s)

AUTO_YES=false
QUICK=false
BACKEND_NAME=""
ALL_BACKENDS=false

# Separate positionals from flags. --backend consumes the following token.
POSITIONAL=()
skip_next=false
all=("$@")
for ((i=0; i<${#all[@]}; i++)); do
    arg="${all[i]}"
    if $skip_next; then skip_next=false; continue; fi
    case "$arg" in
        --yes)          AUTO_YES=true ;;
        --quick)        QUICK=true ;;
        --all-backends) ALL_BACKENDS=true ;;
        --check-source) ;;                       # handled at top of file
        --backend=*)    BACKEND_NAME="${arg#--backend=}" ;;
        --backend)      BACKEND_NAME="${all[i+1]:-}"; skip_next=true ;;
        --*)            warn "Ignoring unknown flag: $arg" ;;
        *)              POSITIONAL+=("$arg") ;;
    esac
done

YT_URL="${POSITIONAL[0]:-}"
VOICE_NAME="${POSITIONAL[1]:-}"
START_S="${POSITIONAL[2]:-}"

# Query registry via Python (registry lives in backends/__main__.py)
if ! AVAILABLE_BACKENDS=$(python3 -m backends list 2>/dev/null); then
    fail "Could not query backends — is the venv active and backends/ present?"
fi
MAX_SR=$(python3 -m backends max-sample-rate 2>/dev/null || echo 24000)

# Default backend
[ -z "$BACKEND_NAME" ] && BACKEND_NAME="qwen3-0.6b"

# Validate chosen backend (unless --all-backends, which uses all registered)
if [ "$ALL_BACKENDS" = false ]; then
    if ! echo "$AVAILABLE_BACKENDS" | grep -qx "$BACKEND_NAME"; then
        fail "Unknown backend: $BACKEND_NAME. Available: $(echo "$AVAILABLE_BACKENDS" | tr '\n' ' ')"
    fi
fi

# Temp file cleanup
TMPFILES=()
cleanup() { [ ${#TMPFILES[@]} -gt 0 ] && rm -rf "${TMPFILES[@]}" 2>/dev/null; true; }
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

# Detect local file — skip yt-dlp if $YT_URL is an existing file path (file:// ok)
LOCAL_FILE=false
SOURCE_BASENAME=""
if _is_local_source "$YT_URL"; then
    LOCAL_FILE=true
    YT_URL="${YT_URL#file://}"
    SOURCE_BASENAME=$(basename "$YT_URL")
fi

if $LOCAL_FILE; then
    TMP_SRC="$YT_URL"
    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_SRC" 2>/dev/null | cut -d. -f1) || DURATION="unknown"
    [[ "$DURATION" =~ ^[0-9]+$ ]] || DURATION="unknown"
    ok "Using local file: ${SOURCE_BASENAME} (${DURATION}s)"
else
    # Download
    info "Downloading audio..."
    TMP_DL_DIR=$(mktemp -d)
    TMP_SRC="$TMP_DL_DIR/source.wav"
    TMPFILES+=("$TMP_DL_DIR")
    if ! yt-dlp -x --audio-format wav -o "$TMP_DL_DIR/source.%(ext)s" "$YT_URL" 2>&1 | tail -5; then
        fail "Download failed. Check the URL is valid and not private/age-restricted."
    fi
    # yt-dlp may leave intermediate files; find the final wav
    [ -f "$TMP_SRC" ] || TMP_SRC=$(find "$TMP_DL_DIR" -name '*.wav' -print -quit)
    [ -f "$TMP_SRC" ] || fail "Download produced no audio file. Check the URL."
    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_SRC" 2>/dev/null | cut -d. -f1)
    [[ "$DURATION" =~ ^[0-9]+$ ]] || DURATION="unknown"
    if [[ "$DURATION" == "unknown" ]]; then
        ok "Downloaded"
    else
        ok "Downloaded (${DURATION}s)"
    fi
fi

# Energy analysis — show expressiveness heatmap to help pick the best segment
if [ -z "$START_S" ] && [[ "$DURATION" =~ ^[0-9]+$ ]] && [ "$DURATION" -gt 15 ]; then
    echo
    echo -e "  ${BOLD}Energy map${NC} ${DIM}(louder = more expressive, pick the brightest solo section)${NC}"
    echo
    python3 - "$TMP_SRC" "$DURATION" <<'PYEOF'
import sys, soundfile as sf, numpy as np

data, sr = sf.read(sys.argv[1])
if data.ndim > 1:
    data = data.mean(axis=1)
duration = int(sys.argv[2])

# 2-second windows
window = sr * 2
energies = []
for i in range(0, len(data) - window, window):
    rms = np.sqrt(np.mean(data[i:i+window]**2))
    energies.append(rms)

if not energies:
    sys.exit(0)

max_e = max(energies)
if max_e == 0:
    sys.exit(0)

# ANSI colours: dim → cyan → green → yellow → bright
levels = [
    ('\033[2m', '░'),      # very quiet
    ('\033[0;36m', '▒'),   # quiet
    ('\033[0;32m', '▓'),   # moderate
    ('\033[0;33m', '█'),   # loud
    ('\033[1;33m', '█'),   # very loud
]

# Find peak regions for recommendation
peak_threshold = max_e * 0.7
peak_starts = []
for i, e in enumerate(energies):
    if e >= peak_threshold:
        sec = i * 2
        if not peak_starts or sec - peak_starts[-1] > 10:
            peak_starts.append(sec)

# Print heatmap in rows of 30 bars (60 seconds per row)
bars_per_row = 30
for row_start in range(0, len(energies), bars_per_row):
    row = energies[row_start:row_start + bars_per_row]
    sec_start = row_start * 2
    sec_end = min(sec_start + bars_per_row * 2, duration)

    # Time label
    line = f'  \033[2m{sec_start:4d}s\033[0m '

    # Energy bars
    for e in row:
        norm = e / max_e
        if norm < 0.15:
            col, ch = levels[0]
        elif norm < 0.35:
            col, ch = levels[1]
        elif norm < 0.55:
            col, ch = levels[2]
        elif norm < 0.75:
            col, ch = levels[3]
        else:
            col, ch = levels[4]
        line += f'{col}{ch}\033[0m'

    line += f' \033[2m{sec_end}s\033[0m'
    print(line)

# Suggest peaks
if peak_starts:
    suggestions = ', '.join(f'{s}s' for s in peak_starts[:5])
    print(f'\n  \033[0;33m★\033[0m Expressive peaks at: \033[1m{suggestions}\033[0m')
PYEOF
    echo
fi

# Get start time
if [ -z "$START_S" ]; then
    echo
    if [[ "$DURATION" == "unknown" ]]; then
        echo -e "  We need a 15-second segment."
    else
        echo -e "  Clip is ${BOLD}${DURATION}s${NC} long. We need a 15-second segment."
    fi
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
ffmpeg -y -i "$TMP_SRC" -ss "$START_S" -t 15 -ar "$MAX_SR" -ac 1 "$TMP_SEG" 2>/dev/null

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

# Transcribe with word-level timestamps
info "Transcribing..."
TRANSCRIPT_OUTPUT=$(python3 - "voices/${VOICE_NAME}-ref.wav" <<'PYEOF'
import sys, json
try:
    from faster_whisper import WhisperModel
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "faster-whisper"])
    from faster_whisper import WhisperModel

model = WhisperModel("base.en", compute_type="int8")
segments, _ = model.transcribe(sys.argv[1], word_timestamps=True)

words = []
full_text = []
for seg in segments:
    for w in seg.words:
        words.append({"start": w.start, "end": w.end, "word": w.word.strip(), "conf": w.probability})
        full_text.append(w.word.strip())

# Print timestamped words for display
for w in words:
    conf_indicator = "" if w["conf"] > 0.8 else " ?"
    print(f'  \033[2m[{w["start"]:5.1f}s]\033[0m {w["word"]}{conf_indicator}', end='')
print()

# Print separator then full text for capture
print("---FULLTEXT---")
print(" ".join(full_text))
PYEOF
) || fail "Transcription failed"

# Split output: timestamped display (already printed) and full text
REF_TEXT=$(echo "$TRANSCRIPT_OUTPUT" | sed -n '/---FULLTEXT---/,$ p' | tail -1)
# Show the timestamped words
echo "$TRANSCRIPT_OUTPUT" | sed '/---FULLTEXT---/,$ d'

[ -z "$(echo "$REF_TEXT" | tr -d '[:space:]')" ] && fail "Transcript is empty — the clip may not contain speech. Try a different segment."

if ! $AUTO_YES; then
    echo
    echo -e "  ${BOLD}Full transcript:${NC}"
    echo -e "  ${CYAN}${REF_TEXT}${NC}"
    echo
    echo -e "  ${YELLOW}Verify this matches what you hear!${NC} Wrong transcripts = garbled voice."
    ask "Press Enter to accept, or type corrected transcript:"
    read -r CORRECTED
    [ -n "$CORRECTED" ] && REF_TEXT="$CORRECTED"
else
    echo -e "  Transcript: ${CYAN}${REF_TEXT}${NC}"
fi

# Save profile(s). If --all-backends, emit one JSON per registered backend (same ref WAV).
if [ "$ALL_BACKENDS" = true ]; then
    DEFAULT_BACKEND="qwen3-0.6b"
    # Default-backend profile uses the plain voice_name
    python3 - "$VOICE_NAME" "$YT_URL" "$REF_TEXT" "$START_S" "$DEFAULT_BACKEND" "$LOCAL_FILE" "$SOURCE_BASENAME" <<'PYEOF'
import json, sys
name, url, text, start, backend = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
is_local = sys.argv[6] == "true"
source_basename = sys.argv[7]
profile = {
    "name": name,
    "backend": backend,
    "source_url": "local-file" if is_local else url,
    "reference_audio": f"{name}-ref.wav",
    "reference_text": text,
    "segment_start_s": start,
}
if is_local and source_basename:
    profile["source_basename"] = source_basename
with open(f"voices/{name}.json", "w") as f:
    json.dump(profile, f, indent=2)
PYEOF
    ok "Profile saved: voices/${VOICE_NAME}.json (backend: $DEFAULT_BACKEND)"

    # Slugged profiles for the other backends — share the same ref WAV
    while IFS= read -r _b; do
        [ "$_b" = "$DEFAULT_BACKEND" ] && continue
        _slug=$(python3 -m backends slug "$_b")
        _alt_name="${VOICE_NAME}-${_slug}"
        python3 - "$VOICE_NAME" "$_alt_name" "$YT_URL" "$REF_TEXT" "$START_S" "$_b" "$LOCAL_FILE" "$SOURCE_BASENAME" <<'PYEOF'
import json, sys
voice_name, alt_name, url, text, start, backend = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6]
is_local = sys.argv[7] == "true"
source_basename = sys.argv[8]
profile = {
    "name": alt_name,
    "backend": backend,
    "source_url": "local-file" if is_local else url,
    "reference_audio": f"{voice_name}-ref.wav",
    "reference_text": text,
    "segment_start_s": start,
}
if is_local and source_basename:
    profile["source_basename"] = source_basename
with open(f"voices/{alt_name}.json", "w") as f:
    json.dump(profile, f, indent=2)
PYEOF
        ok "Profile saved: voices/${_alt_name}.json (backend: $_b)"
    done <<< "$AVAILABLE_BACKENDS"
else
    python3 - "$VOICE_NAME" "$YT_URL" "$REF_TEXT" "$START_S" "$BACKEND_NAME" "$LOCAL_FILE" "$SOURCE_BASENAME" <<'PYEOF'
import json, sys
name, url, text, start, backend = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
is_local = sys.argv[6] == "true"
source_basename = sys.argv[7]
profile = {
    "name": name,
    "backend": backend,
    "source_url": "local-file" if is_local else url,
    "reference_audio": f"{name}-ref.wav",
    "reference_text": text,
    "segment_start_s": start,
}
if is_local and source_basename:
    profile["source_basename"] = source_basename
with open(f"voices/{name}.json", "w") as f:
    json.dump(profile, f, indent=2)
PYEOF
    ok "Profile saved: voices/${VOICE_NAME}.json (backend: $BACKEND_NAME)"
fi

# Test
echo
info "Testing synthesis..."
TEST_WAV="/tmp/clone-test-$$.wav"
TMPFILES+=("$TEST_WAV")
if curl -s --max-time 120 \
    "http://127.0.0.1:7860/synthesize?text=Hello.+I+am+${VOICE_NAME}.&voice=${VOICE_NAME}" \
    -o "$TEST_WAV" 2>/dev/null; then
    FSIZE=$(stat -f%z "$TEST_WAV" 2>/dev/null || echo 0)
    if [ "$FSIZE" -gt 1000 ]; then
        ok "Synthesis works!"
        afplay "$TEST_WAV" 2>/dev/null

    elif [ "$FSIZE" -gt 0 ]; then
        # Might be a JSON error response
        BODY=$(cat "$TEST_WAV" 2>/dev/null)
        if echo "$BODY" | jq -e '.error' &>/dev/null; then
            ERR=$(echo "$BODY" | jq -r '.error')
            warn "Server returned error: ${ERR}"
        else
            warn "Server returned small file. Restart the server to pick up new voices."
        fi
    else
        warn "Server returned empty response."
    fi
else
    warn "Server not responding. Restart: launchctl unload ~/Library/LaunchAgents/com.afterwords.tts-server.plist && launchctl load ~/Library/LaunchAgents/com.afterwords.tts-server.plist"
fi

_ELAPSED=$(( $(date +%s) - _T0 ))
echo
rule
echo
echo -e "  ${GREEN}${BOLD}✓ ${VOICE_NAME} cloned${NC}  ${DIM}(${_ELAPSED}s)${NC}"
echo
echo -e "  ${DIM}use now${NC}        echo \"${VOICE_NAME}\" > .afterwords"
echo -e "  ${DIM}make default${NC}   edit DEFAULT_VOICE in server.py + restart"
echo -e "  ${DIM}test${NC}           curl \"localhost:7860/synthesize?text=Hello&voice=${VOICE_NAME}\" -o test.wav && afplay test.wav"
echo
