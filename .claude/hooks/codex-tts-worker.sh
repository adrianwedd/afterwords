#!/usr/bin/env bash
set -uo pipefail

QUEUE="/tmp/codex-tts-queue.txt"
PIDFILE="/tmp/codex-tts-worker.pid"
LOCKDIR="/tmp/codex-tts-worker.lock"
TTS_URL="http://127.0.0.1:7860/synthesize"
ARCHIVE_DIR="$HOME/.codex/tts-archive"
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

    RAW_LINE=$(head -1 "$QUEUE" 2>/dev/null)
    [ -z "$RAW_LINE" ] && break

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

    PROJECT_DIR=$(printf '%s' "$RAW_LINE" | cut -f1)
    AGENT=$(printf '%s' "$RAW_LINE" | cut -f2)
    LINE=$(printf '%s' "$RAW_LINE" | cut -f3-)
    [ -z "$LINE" ] && continue

    ENCODED=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$LINE" 2>/dev/null) || continue
    STAMP=$(date +%Y%m%d-%H%M%S)

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

    VOICE_PARAM=""
    [ -n "$VOICE" ] && VOICE_PARAM="&voice=${VOICE}"

    WAVFILE="/tmp/codex-tts-$$.wav"
    if curl -s --max-time 90 "${TTS_URL}?text=${ENCODED}${VOICE_PARAM}" -o "$WAVFILE" 2>/dev/null; then
        FILESIZE=$(stat -f%z "$WAVFILE" 2>/dev/null || echo 0)
        if [ "$FILESIZE" -gt 1000 ]; then
            TRIMMED="/tmp/codex-tts-trimmed-$$.wav"
            if ffmpeg -y -ss 0.1 -i "$WAVFILE" -c copy "$TRIMMED" 2>/dev/null; then
                mv "$TRIMMED" "$WAVFILE"
            fi
            rm -f "$TRIMMED"
            lame --quiet -V 2 "$WAVFILE" "$ARCHIVE_DIR/${VOICE:-default}-${STAMP}.mp3" 2>/dev/null
            afplay "$WAVFILE" 2>/dev/null
        fi
    fi

    rm -f "$WAVFILE"
done

rm -f "$QUEUE" "$QUEUE.tmp"
