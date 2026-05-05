#!/usr/bin/env bash
# Drain the per-session Codex TTS queue and synthesize each item.
#
# Queue: directory of JSON files ($QUEUEDIR). Each file holds one item.
# Claiming: atomic mv to *.claimed prevents two workers racing on the same item.
set -uo pipefail

SESSION_ID="${CODEX_THREAD_ID:-global}"
QUEUEDIR="/tmp/codex-tts-queue-${SESSION_ID}"
PIDFILE="/tmp/codex-tts-worker-${SESSION_ID}.pid"
LOCKDIR="/tmp/codex-tts-worker-${SESSION_ID}.lock"
TTS_URL="http://127.0.0.1:7860/synthesize"
ARCHIVE_DIR="$HOME/.codex/tts-archive"
MAX_QUEUE=10

mkdir -p "$ARCHIVE_DIR" "$QUEUEDIR"

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
    # Prune excess items (keep newest MAX_QUEUE).
    mapfile -t ALL_ITEMS < <(ls -1t "$QUEUEDIR"/*.json 2>/dev/null)
    TOTAL="${#ALL_ITEMS[@]}"
    if [ "$TOTAL" -gt "$MAX_QUEUE" ]; then
        for OLD in "${ALL_ITEMS[@]:$MAX_QUEUE}"; do
            rm -f "$OLD"
        done
    fi

    # Claim oldest unclaimed item atomically.
    ITEM=""
    for CANDIDATE in $(ls -1t "$QUEUEDIR"/*.json 2>/dev/null | tail -r); do
        CLAIMED="${CANDIDATE%.json}.claimed"
        if mv "$CANDIDATE" "$CLAIMED" 2>/dev/null; then
            ITEM="$CLAIMED"
            break
        fi
    done
    [ -z "$ITEM" ] && break

    # Parse JSON item.
    PARSED=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get('project_dir',''))
print(d.get('agent',''))
print(d.get('text',''))
" "$ITEM" 2>/dev/null) || { rm -f "$ITEM"; continue; }
    PROJECT_DIR=$(printf '%s' "$PARSED" | sed -n '1p')
    AGENT=$(printf '%s' "$PARSED" | sed -n '2p')
    TEXT=$(printf '%s' "$PARSED" | sed -n '3,$p')
    rm -f "$ITEM"
    [ -z "$TEXT" ] && continue

    ENCODED=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$TEXT" 2>/dev/null) || continue
    STAMP=$(date +%Y%m%d-%H%M%S)-$$-$RANDOM

    VOICE=""
    AW_FILE="$PROJECT_DIR/.afterwords"
    if [ -n "$PROJECT_DIR" ] && [ -f "$AW_FILE" ]; then
        if grep -q ':' "$AW_FILE" 2>/dev/null; then
            if [ -n "$AGENT" ]; then
                VOICE=$(grep "^${AGENT}:" "$AW_FILE" 2>/dev/null | head -1 | cut -d: -f2- | tr -d '[:space:]')
            fi
            [ -z "$VOICE" ] && VOICE=$(grep "^default:" "$AW_FILE" 2>/dev/null | head -1 | cut -d: -f2- | tr -d '[:space:]')
        else
            VOICE=$(head -1 "$AW_FILE" 2>/dev/null | tr -d '[:space:]')
        fi
    fi

    if [ -z "$VOICE" ]; then
        VOICE=$(curl -s --max-time 2 "${TTS_URL%/synthesize}/health" 2>/dev/null \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_voice',''))" 2>/dev/null || true)
    fi

    # URL-encode voice name to handle special characters.
    VOICE_PARAM=""
    if [ -n "$VOICE" ]; then
        VOICE_ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$VOICE" 2>/dev/null) || VOICE_ENC="$VOICE"
        VOICE_PARAM="&voice=${VOICE_ENC}"
    fi

    WAVFILE="/tmp/codex-tts-${SESSION_ID}-$$.wav"
    if curl -s --max-time 90 "${TTS_URL}?text=${ENCODED}${VOICE_PARAM}" -o "$WAVFILE" 2>/dev/null; then
        FILESIZE=$(stat -f%z "$WAVFILE" 2>/dev/null || echo 0)
        if [ "$FILESIZE" -gt 1000 ]; then
            TRIMMED="/tmp/codex-tts-trimmed-${SESSION_ID}-$$.wav"
            if ffmpeg -y -ss 0.1 -i "$WAVFILE" -c copy "$TRIMMED" 2>/dev/null; then
                mv "$TRIMMED" "$WAVFILE"
            fi
            rm -f "$TRIMMED"
            ARCHIVE_BASE="$ARCHIVE_DIR/${VOICE:-default}-${STAMP}"
            if lame --quiet -V 2 "$WAVFILE" "$ARCHIVE_BASE.mp3" 2>/dev/null; then
                printf '%s\n' "$TEXT" > "$ARCHIVE_BASE.txt"
            fi
            afplay "$WAVFILE" 2>/dev/null
        fi
    fi

    rm -f "$WAVFILE"
done
