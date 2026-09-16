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
MAX_QUEUE=25

MUTE_FILE="/tmp/afterwords-muted"   # `afterwords mute` toggles this; skip local playback when present
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

mkdir -p "$ARCHIVE_DIR"
if [ -L "$QUEUEDIR" ]; then
  echo "afterwords: $QUEUEDIR is a symlink — refusing to use it" >&2
  exit 1
fi
mkdir -p "$QUEUEDIR"
chmod 700 "$QUEUEDIR" 2>/dev/null || true
if [ ! -d "$QUEUEDIR" ] || [ "$(stat -f%u "$QUEUEDIR" 2>/dev/null)" != "$(id -u)" ]; then
  echo "afterwords: $QUEUEDIR is not a directory we own — refusing to use it" >&2
  exit 1
fi

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
    # Coalesce backlog: keep only the newest pending item so TTS stays current.
    NEWEST=""
    COUNT=0
    while IFS= read -r CAND; do
        COUNT=$((COUNT + 1))
        if [ -z "$NEWEST" ]; then
            NEWEST="$CAND"
        else
            rm -f "$CAND"
        fi
    done < <(ls -1t "$QUEUEDIR"/*.json 2>/dev/null)
    if [ "$COUNT" -gt "$MAX_QUEUE" ]; then
        EXTRA=0
        while IFS= read -r EXCESS; do
            EXTRA=$((EXTRA + 1))
            [ "$EXTRA" -gt "$MAX_QUEUE" ] && rm -f "$EXCESS"
        done < <(ls -1t "$QUEUEDIR"/*.json 2>/dev/null)
    fi

    # Claim the remaining (newest) item atomically via mv.
    ITEM=""
    if [ -n "$NEWEST" ] && [ -f "$NEWEST" ]; then
        CLAIMED="${NEWEST%.json}.claimed"
        if mv "$NEWEST" "$CLAIMED" 2>/dev/null; then
            ITEM="$CLAIMED"
        fi
    fi
    if [ -z "$ITEM" ]; then
        while IFS= read -r CANDIDATE; do
            CLAIMED="${CANDIDATE%.json}.claimed"
            if mv "$CANDIDATE" "$CLAIMED" 2>/dev/null; then
                ITEM="$CLAIMED"
                break
            fi
        done < <(ls -1t "$QUEUEDIR"/*.json 2>/dev/null)
    fi
    [ -z "$ITEM" ] && break

    # Parse JSON item fields directly — avoids eval on queue content.
    PROJECT_DIR=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('project_dir',''))" "$ITEM" 2>/dev/null) || { rm -f "$ITEM"; continue; }
    AGENT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('agent',''))" "$ITEM" 2>/dev/null) || true
    TEXT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('text',''))" "$ITEM" 2>/dev/null) || { rm -f "$ITEM"; continue; }
    ATTEMPTS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('attempts',0))" "$ITEM" 2>/dev/null) || true
    rm -f "$ITEM"
    [ -z "${TEXT:-}" ] && continue
    ATTEMPTS=${ATTEMPTS:-0}

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

    # Never silently drop speech if another agent holds the play lock —
    # re-queue and retry after a brief backoff (capped to avoid wedged locks).
    if ! acquire_play_lock; then
        NEXT_ATTEMPTS=$((ATTEMPTS + 1))
        if [ "$NEXT_ATTEMPTS" -ge 3 ]; then
            echo "afterwords: dropping codex TTS item after $NEXT_ATTEMPTS lock waits" >&2
            continue
        fi
        REQUEUE="${QUEUEDIR}/$(date +%s%N 2>/dev/null || date +%s)-requeue-${RANDOM}.json"
        python3 -c "
import json, sys
print(json.dumps({
    'project_dir': sys.argv[1],
    'agent': sys.argv[2],
    'text': sys.argv[3],
    'attempts': int(sys.argv[4]),
}))
" "$PROJECT_DIR" "$AGENT" "$TEXT" "$NEXT_ATTEMPTS" > "${REQUEUE}.tmp" && mv "${REQUEUE}.tmp" "$REQUEUE"
        sleep 2
        continue
    fi
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

    synth_chunk() {
        local out="$1" text="$2"
        if [ -n "${VOICE:-}" ]; then
            curl -s --max-time 60 -G                 --data-urlencode "text=${text}"                 --data-urlencode "voice=${VOICE}"                 -o "$out" "$TTS_URL" 2>/dev/null || true
        else
            curl -s --max-time 60 -G                 --data-urlencode "text=${text}"                 -o "$out" "$TTS_URL" 2>/dev/null || true
        fi
    }

    PREV_WAV=""
    PREV_TEXT=""
    PREV_ARCH=""
    SYNTH_PID=""
    CHUNK_I=1
    while [ "$CHUNK_I" -le "$NCHUNKS" ]; do
        CHUNK=$(cat "${CHUNK_DIR}/${CHUNK_I}.txt")
        CURR_WAV="${CHUNK_DIR}/${CHUNK_I}.wav"

        [ -n "$SYNTH_PID" ] && { wait "$SYNTH_PID"; SYNTH_PID=""; }

        # Start next synth in background — overlaps with playback of previous chunk.
        synth_chunk "$CURR_WAV" "$CHUNK" &
        SYNTH_PID=$!

        if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
            FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
            if [ "$FILESIZE" -le 1000 ] && [ -n "$PREV_TEXT" ]; then
                synth_chunk "$PREV_WAV" "$PREV_TEXT"
                FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
            fi
            if [ "$FILESIZE" -gt 1000 ]; then
                [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null
                if [ -n "$PREV_ARCH" ]; then
                    (lame --quiet -V 2 "$PREV_WAV" "$PREV_ARCH" 2>/dev/null; rm -f "$PREV_WAV") &
                else
                    rm -f "$PREV_WAV"
                fi
            else
                rm -f "$PREV_WAV"
            fi
        fi

        PREV_WAV="$CURR_WAV"
        PREV_TEXT="$CHUNK"
        PREV_ARCH="${ARCHIVE_BASE}-c${CHUNK_I}.mp3"
        CHUNK_I=$((CHUNK_I + 1))
    done

    [ -n "$SYNTH_PID" ] && wait "$SYNTH_PID"
    if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
        FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
        if [ "$FILESIZE" -le 1000 ] && [ -n "$PREV_TEXT" ]; then
            synth_chunk "$PREV_WAV" "$PREV_TEXT"
            FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
        fi
        if [ "$FILESIZE" -gt 1000 ]; then
            [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null
            if [ -n "$PREV_ARCH" ]; then
                (lame --quiet -V 2 "$PREV_WAV" "$PREV_ARCH" 2>/dev/null; rm -f "$PREV_WAV") &
            else
                rm -f "$PREV_WAV"
            fi
        else
            rm -f "$PREV_WAV"
        fi
    fi

    wait 2>/dev/null || true
    rm -rf "$CHUNK_DIR"
    release_play_lock
done
