#!/usr/bin/env bash
# Drain the per-session Codex TTS queue and synthesize each item.
#
# Queue: directory of JSON files ($QUEUEDIR). Each file holds one item.
# Claiming: atomic mv to *.claimed prevents two workers racing on the same item.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SESSION_ID="${CODEX_THREAD_ID:-global}"
QUEUEDIR="/tmp/codex-tts-queue-${SESSION_ID}"
PIDFILE="/tmp/codex-tts-worker-${SESSION_ID}.pid"
LOCKDIR="/tmp/codex-tts-worker-${SESSION_ID}.lock"
TTS_URL="http://127.0.0.1:7860/synthesize"
ARCHIVE_DIR="$HOME/.codex/tts-archive"
MAX_QUEUE=10

PLAY_LOCK="/tmp/afterwords-play.lock"
PLAY_PID="/tmp/afterwords-play.pid"
acquire_play_lock() {
    local w=0
    while ! mkdir "$PLAY_LOCK" 2>/dev/null; do
        local h; h=$(cat "$PLAY_PID" 2>/dev/null)
        if [ -z "$h" ]; then sleep 0.05; h=$(cat "$PLAY_PID" 2>/dev/null); fi
        if [ -z "$h" ] || ! kill -0 "$h" 2>/dev/null; then
            rm -rf "$PLAY_LOCK" "$PLAY_PID"
        else
            sleep 0.3; w=$((w+1)); [ "$w" -gt 200 ] && return 1
        fi
    done
    echo $$ > "$PLAY_PID"
}
release_play_lock() { rm -f "$PLAY_PID"; rm -rf "$PLAY_LOCK"; }

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
    # Prune excess items (keep newest MAX_QUEUE). Bash 3.2-compatible: no mapfile.
    COUNT=0
    while IFS= read -r EXCESS; do
        COUNT=$((COUNT + 1))
        [ "$COUNT" -gt "$MAX_QUEUE" ] && rm -f "$EXCESS"
    done < <(ls -1t "$QUEUEDIR"/*.json 2>/dev/null)

    # Claim oldest unclaimed item atomically via mv.
    ITEM=""
    while IFS= read -r CANDIDATE; do
        CLAIMED="${CANDIDATE%.json}.claimed"
        if mv "$CANDIDATE" "$CLAIMED" 2>/dev/null; then
            ITEM="$CLAIMED"
            break
        fi
    done < <(ls -1t "$QUEUEDIR"/*.json 2>/dev/null | tail -r 2>/dev/null || ls -1 "$QUEUEDIR"/*.json 2>/dev/null | sort)
    [ -z "$ITEM" ] && break

    # Parse JSON item. Use shlex.quote to emit a safe eval block — handles
    # newlines and special chars in text without shell delimiter tricks.
    ITEM_EVAL=$(python3 -c "
import json, sys, shlex
d = json.load(open(sys.argv[1]))
print('PROJECT_DIR=' + shlex.quote(d.get('project_dir','')))
print('AGENT=' + shlex.quote(d.get('agent','')))
print('TEXT=' + shlex.quote(d.get('text','')))
" "$ITEM" 2>/dev/null) || { rm -f "$ITEM"; continue; }
    eval "$ITEM_EVAL"
    rm -f "$ITEM"
    [ -z "${TEXT:-}" ] && continue

    ENCODED=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$TEXT" 2>/dev/null) || continue
    STAMP=$(date +%Y%m%d-%H%M%S)-$$-$RANDOM

    VOICE=""
    AW_FILE=""
    if [ -n "$PROJECT_DIR" ] && [ -f "$PROJECT_DIR/.afterwords" ]; then
        AW_FILE="$PROJECT_DIR/.afterwords"
    elif [ -f "$HOME/.afterwords" ]; then
        AW_FILE="$HOME/.afterwords"
    fi

    if [ -n "$AW_FILE" ]; then
        if grep -q ':' "$AW_FILE" 2>/dev/null; then
            # Mapping mode. Split on the final colon so keys may contain colons.
            VOICE=$(awk -v agent="$AGENT" '
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
                    if (agent != "" && key == agent) { print val; found = 1; exit }
                    if (key == "default" && fallback == "") fallback = val
                }
                END { if (!found && fallback != "") print fallback }
            ' "$AW_FILE" 2>/dev/null)
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

    acquire_play_lock || continue
    CHUNK_SCRIPT="${REPO_DIR}/chunk_text.py"
    [ -f "$CHUNK_SCRIPT" ] || CHUNK_SCRIPT="$HOME/.claude/hooks/chunk-text.py"
    CHUNK_DIR="/tmp/codex-tts-chunks-${SESSION_ID}-$$"
    mkdir -p "$CHUNK_DIR"

    ARCHIVE_BASE="$ARCHIVE_DIR/${VOICE:-default}-${STAMP}"
    printf '%s\n' "$TEXT" > "${ARCHIVE_BASE}.txt"

    # Collect sentence-boundary chunks (Bash 3.2-compatible: no mapfile).
    NCHUNKS=0
    while IFS= read -r CHUNK; do
        [ -z "$CHUNK" ] && continue
        NCHUNKS=$((NCHUNKS + 1))
        printf '%s' "$CHUNK" > "${CHUNK_DIR}/${NCHUNKS}.txt"
    done < <([ -f "$CHUNK_SCRIPT" ] && python3 "$CHUNK_SCRIPT" <<< "$TEXT" 2>/dev/null \
             || printf '%s\n' "$TEXT")

    PREV_WAV=""
    SYNTH_PID=""
    CHUNK_I=1
    while [ "$CHUNK_I" -le "$NCHUNKS" ]; do
        CHUNK=$(cat "${CHUNK_DIR}/${CHUNK_I}.txt")
        CURR_WAV="${CHUNK_DIR}/${CHUNK_I}.wav"
        ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$CHUNK" 2>/dev/null) || { CHUNK_I=$((CHUNK_I+1)); continue; }

        [ -n "$SYNTH_PID" ] && { wait "$SYNTH_PID"; SYNTH_PID=""; }

        # Start next synth in background — overlaps with playback of previous chunk.
        curl -s --max-time 60 "${TTS_URL}?text=${ENC}${VOICE_PARAM}" -o "$CURR_WAV" 2>/dev/null &
        SYNTH_PID=$!

        if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
            FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
            if [ "$FILESIZE" -gt 1000 ]; then
                TRIMMED="${PREV_WAV%.wav}.trimmed.wav"
                ffmpeg -y -ss 0.1 -i "$PREV_WAV" -c copy "$TRIMMED" 2>/dev/null \
                    && mv "$TRIMMED" "$PREV_WAV" || rm -f "$TRIMMED"
                lame --quiet -V 2 "$PREV_WAV" "${ARCHIVE_BASE}-c$((CHUNK_I-1)).mp3" 2>/dev/null || true
                afplay "$PREV_WAV" 2>/dev/null
            fi
            rm -f "$PREV_WAV"
        fi

        PREV_WAV="$CURR_WAV"
        CHUNK_I=$((CHUNK_I + 1))
    done

    [ -n "$SYNTH_PID" ] && wait "$SYNTH_PID"
    if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
        FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
        if [ "$FILESIZE" -gt 1000 ]; then
            TRIMMED="${PREV_WAV%.wav}.trimmed.wav"
            ffmpeg -y -ss 0.1 -i "$PREV_WAV" -c copy "$TRIMMED" 2>/dev/null \
                && mv "$TRIMMED" "$PREV_WAV" || rm -f "$TRIMMED"
            lame --quiet -V 2 "$PREV_WAV" "${ARCHIVE_BASE}-c${NCHUNKS}.mp3" 2>/dev/null || true
            afplay "$PREV_WAV" 2>/dev/null
        fi
        rm -f "$PREV_WAV"
    fi

    rm -rf "$CHUNK_DIR"
    release_play_lock
done
