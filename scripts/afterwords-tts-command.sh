#!/usr/bin/env bash
#
# afterwords-tts-command.sh — Command provider for Hermes TTS
#
# Called by Hermes's command-type TTS provider system.
# Reads text from {input_path}, resolves voice from .afterwords files,
# synthesizes via Afterwords server, writes WAV to {output_path}.
#
# Architecture:
#   - On CLI: fires synthesis + playback in the background via a detached
#     subshell, writes a silent placeholder WAV, and returns immediately.
#     This prevents text output from being delayed by audio generation.
#     The background subshell acquires the shared play lock
#     (/tmp/afterwords-play.lock) to coordinate with other agents.
#   - On messaging platforms (Telegram/Discord): runs synchronously to
#     produce the real audio file for attachment delivery.
#
# Placeholders provided by Hermes:
#   {input_path}  / {text_path} — temp file containing the text to speak
#   {output_path} — path where the audio file must be written
#   {voice}       — voice name from config (may be empty)
#   {format}      — output format (wav, mp3, etc.)
#
set -euo pipefail

TEXT_PATH="${1:?Usage: afterwords-tts-command.sh <input_path> <output_path> [voice]}"
OUTPUT_PATH="${2:?Missing output_path}"
CONFIG_VOICE="${3:-}"

PORT=7860

# Read the text
TEXT=$(cat "$TEXT_PATH" 2>/dev/null || true)
if [ -z "$TEXT" ]; then
    echo "Error: empty input text" >&2
    exit 1
fi

# Resolve voice: config voice → project .afterwords (agent key → default:) → global ~/.afterwords (agent key → default:) → server default
VOICE="$CONFIG_VOICE"

if [ -z "$VOICE" ]; then
    # Try project .afterwords
    AW_FILE=""
    CWD="$(pwd)"
    if [ -f "$CWD/.afterwords" ]; then
        AW_FILE="$CWD/.afterwords"
    elif [ -f "$HOME/.afterwords" ]; then
        AW_FILE="$HOME/.afterwords"
    fi

    if [ -n "$AW_FILE" ]; then
        if grep -q ':' "$AW_FILE" 2>/dev/null; then
            # Mapping mode. Split on the final colon so keys may contain colons.
            VOICE=$(awk -v agent="hermes" '
                function trim(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
                /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
                {
                    pos = 0
                    for (i = 1; i <= length($0); i++) {
                        if (substr($0, i, 1) == ":") pos = i
                    }
                    if (!pos) next
                    key = trim(substr($0, 1, pos - 1))
                    val = trim(substr($0, pos + 1))
                    if (key == agent) { print val; found = 1; exit }
                    if (key == "default" && fallback == "") fallback = val
                }
                END { if (!found && fallback != "") print fallback }
            ' "$AW_FILE" 2>/dev/null)
        else
            # Simple mode: first non-empty non-comment line
            VOICE=$(grep -v '^[[:space:]]*$\|^[[:space:]]*#' "$AW_FILE" | head -1 | tr -d '[:space:]' 2>/dev/null || true)
        fi
    fi
fi

# URL-encode the text (strip markdown and truncate to 1000 chars)
CLEANED=$(echo "$TEXT" | sed 's/`//g; s/\*//g; s/_//g' | cut -c 1-1000)
ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CLEANED")

# Build URL
URL="http://127.0.0.1:${PORT}/synthesize?text=${ENCODED}"
if [ -n "$VOICE" ]; then
    VOICE_ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$VOICE")
    URL="${URL}&voice=${VOICE_ENCODED}"
fi

# ── Platform detection ────────────────────────────────────────────────
# HERMES_SESSION_PLATFORM is set by the gateway on messaging platforms.
# If unset or "cli"/"local", we're on CLI — fire async to avoid blocking.
ASYNC=false
if [ -z "${HERMES_SESSION_PLATFORM:-}" ] || [ "$HERMES_SESSION_PLATFORM" = "cli" ] || [ "$HERMES_SESSION_PLATFORM" = "local" ]; then
    ASYNC=true
fi

if $ASYNC; then
    # ── CLI mode: async synthesis + playback ──────────────────────────
    # Write a minimal valid WAV (0.1s silence, 24kHz, 16-bit mono) as
    # placeholder so Hermes's TTS framework gets a valid output file
    # immediately. Then fire the real synthesis + afplay in a background
    # subshell that coordinates via the shared play lock.
    python3 -c "
import struct, sys
sr, bits, ch = 24000, 16, 1
n_samples = int(sr * 0.1)
data_size = n_samples * ch * (bits // 8)
fmt_size = 16
riff_size = 4 + (8 + fmt_size) + (8 + data_size)
with open(sys.argv[1], 'wb') as f:
    f.write(b'RIFF')
    f.write(struct.pack('<I', riff_size))
    f.write(b'WAVE')
    f.write(b'fmt ')
    f.write(struct.pack('<I', fmt_size))
    f.write(struct.pack('<HHIIHH', 1, ch, sr, sr*ch*(bits//8), ch*(bits//8), bits))
    f.write(b'data')
    f.write(struct.pack('<I', data_size))
    f.write(b'\x00' * data_size)
" "$OUTPUT_PATH"

    # Fire synthesis + playback in background (fully detached)
    (
        MUTE_FILE="/tmp/afterwords-muted"   # `afterwords mute` toggles this; skip local playback when present
        PLAY_LOCK="/tmp/afterwords-play.lock"
        PLAY_PID="/tmp/afterwords-play.pid"
        
        # Acquire play lock (mkdir-based for atomicity)
        WAITED=0
        while ! mkdir "$PLAY_LOCK" 2>/dev/null; do
            HOLDER=$(cat "$PLAY_PID" 2>/dev/null || true)
            if [ -z "$HOLDER" ]; then sleep 0.05; HOLDER=$(cat "$PLAY_PID" 2>/dev/null || true); fi
            if [ -z "$HOLDER" ] || ! kill -0 "$HOLDER" 2>/dev/null; then
                rm -rf "$PLAY_LOCK" "$PLAY_PID"
                continue
            fi
            WAITED=$((WAITED + 1))
            if [ "$WAITED" -ge 200 ]; then
                exit 0  # Give up silently
            fi
            sleep 0.3
        done
        bash -c 'echo $PPID' > "$PLAY_PID"

        # Synthesize
        TMP_WAV=$(mktemp /tmp/afterwords-cmd-XXXXXX.wav)
        HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TMP_WAV" "$URL" 2>/dev/null || echo "000")

        if [ "$HTTP_CODE" = "200" ] && [ -s "$TMP_WAV" ]; then
            # Play
            [ -f "$MUTE_FILE" ] || afplay "$TMP_WAV" 2>/dev/null || true

            # Archive as MP3 + text sidecar — filename derived from spoken text
            STAMP=$(date +%Y%m%d-%H%M%S)
            ARCHIVE_DIR="$HOME/.hermes/tts-archive"
            mkdir -p "$ARCHIVE_DIR"
            SLUG=$(printf '%s' "$CLEANED" | python3 -c "
import sys, re
t = sys.stdin.read().strip().lower()
t = re.sub(r'[^a-z0-9]+', '-', t)
t = t.strip('-')[:60]
print(t or 'voice')
" 2>/dev/null || echo "voice")
            ARCHIVE_MP3="${ARCHIVE_DIR}/${SLUG}-${STAMP}.mp3"
            lame --quiet -V 2 "$TMP_WAV" "$ARCHIVE_MP3" 2>/dev/null || true
            printf '%s\n' "$CLEANED" > "${ARCHIVE_MP3%.mp3}.txt" 2>/dev/null || true

            rm -f "$TMP_WAV"
        else
            rm -f "$TMP_WAV"
        fi

        # Release play lock
        rm -f "$PLAY_PID"
        rm -rf "$PLAY_LOCK"
    ) &

    # Return immediately — text output won't be blocked
    exit 0
fi

# ── Non-CLI platforms (Telegram, Discord): synchronous ─────────────────
# These platforms need the actual audio file for attachment delivery.
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$OUTPUT_PATH" "$URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" != "200" ]; then
    echo "Afterwords TTS failed (HTTP $HTTP_CODE)" >&2
    rm -f "$OUTPUT_PATH"
    exit 1
fi

# Verify output
if [ ! -s "$OUTPUT_PATH" ]; then
    echo "Afterwords TTS produced empty output" >&2
    exit 1
fi

# Archive as MP3 + text sidecar — filename derived from spoken text
STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_DIR="$HOME/.hermes/tts-archive"
mkdir -p "$ARCHIVE_DIR"
SLUG=$(printf '%s' "$CLEANED" | python3 -c "
import sys, re
t = sys.stdin.read().strip().lower()
t = re.sub(r'[^a-z0-9]+', '-', t)
t = t.strip('-')[:60]
print(t or 'voice')
" 2>/dev/null || echo "voice")
ARCHIVE_MP3="${ARCHIVE_DIR}/${SLUG}-${STAMP}.mp3"
lame --quiet -V 2 "$OUTPUT_PATH" "$ARCHIVE_MP3" 2>/dev/null || true
printf '%s\n' "$CLEANED" > "${ARCHIVE_MP3%.mp3}.txt" 2>/dev/null || true