#!/usr/bin/env bash
# afterwords-post-llm.sh — Shell hook for Hermes post_llm_call
# Speaks the LLM response via Afterwords TTS with chunked pipelining:
#   1. Strip markdown, split into ~200-char sentence chunks
#   2. Synthesize chunk N+1 while playing chunk N (overlap)
#   3. Resolve voice from .afterwords files
#
# Payload JSON on stdin: {"hook_event_name":"post_llm_call","session_id":"...","cwd":"...","extra":{"assistant_response":"..."}}
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AFTERWORDS_URL="http://127.0.0.1:7860"

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
AFTERWORDS_HEALTH="$AFTERWORDS_URL/health"
TTS_ENDPOINT="$AFTERWORDS_URL/synthesize"
CHUNK_CHARS=200

# ── Read payload ──────────────────────────────────────────────────────────
PAYLOAD=$(cat)
TEXT=$(printf '%s' "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('extra',{}).get('assistant_response','')[:1000])" 2>/dev/null || true)
CWD=$(printf '%s' "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd','') or d.get('extra',{}).get('cwd',''))" 2>/dev/null || true)
PLATFORM=$(printf '%s' "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('extra',{}).get('platform',''))" 2>/dev/null || true)

# Only speak for CLI / local sessions (avoid double-notification on Telegram etc.)
case "$PLATFORM" in
    telegram|discord|slack|signal|matrix|whatsapp|email|sms|feishu|wecom|yuanbao) exit 0 ;;
esac

[ -z "$TEXT" ] && exit 0

# ── Strip markdown ─────────────────────────────────────────────────────────
CLEAN=$(printf '%s' "$TEXT" | python3 "$SCRIPT_DIR/strip-markdown.py" 2>/dev/null || printf '%s' "$TEXT")
[ -z "$CLEAN" ] && exit 0

# ── Check server health ────────────────────────────────────────────────────
if ! curl -s --max-time 2 "$AFTERWORDS_HEALTH" > /dev/null 2>&1; then
    exit 0  # Server not running, fail silently
fi

# ── Resolve voice ──────────────────────────────────────────────────────────
# Priority: project .afterwords (agent key → default:) → global ~/.afterwords (agent key → default:) → server default
resolve_voice() {
    local agent="hermes"
    local voice=""
    local aw_file=""

    # CWD from payload, then pwd, then home
    local cwd="${CWD:-$(pwd)}"
    if [ -n "$cwd" ] && [ -f "${cwd}/.afterwords" ]; then
        aw_file="${cwd}/.afterwords"
    elif [ -f "$HOME/.afterwords" ]; then
        aw_file="$HOME/.afterwords"
    fi

    if [ -n "$aw_file" ] && grep -q ':' "$aw_file" 2>/dev/null; then
        voice=$(awk -v agent="$agent" '
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
        ' "$aw_file" 2>/dev/null)
    elif [ -n "$aw_file" ]; then
        voice=$(grep -v '^[[:space:]]*$\|^[[:space:]]*#' "$aw_file" | head -1 | tr -d '[:space:]' 2>/dev/null || true)
    fi

    echo "${voice}"
}

VOICE=$(resolve_voice)
VOICE_PARAM=""
if [ -n "$VOICE" ]; then
    VOICE_ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$VOICE" 2>/dev/null || echo "")
    [ -n "$VOICE_ENC" ] && VOICE_PARAM="&voice=${VOICE_ENC}"
fi

# ── Chunked pipeline: synth N+1 while playing N ─────────────────────────
acquire_play_lock || exit 0
CHUNK_DIR=$(mktemp -d "/tmp/hermes-tts-chunks-XXXXXX")
trap 'rm -rf "$CHUNK_DIR"; release_play_lock' EXIT

# Split text into sentence-boundary chunks
CHUNKS=()
while IFS= read -r CHUNK; do
    [ -z "$CHUNK" ] && continue
    CHUNKS+=("$CHUNK")
done < <(printf '%s' "$CLEAN" | python3 "$SCRIPT_DIR/chunk-text.py" 2>/dev/null || printf '%s\n' "$CLEAN")

NCHUNKS=${#CHUNKS[@]}
[ "$NCHUNKS" -eq 0 ] && exit 0

PREV_WAV=""
SYNTH_PID=""

for i in $(seq 1 "$NCHUNKS"); do
    CHUNK="${CHUNKS[$((i-1))]}"
    CURR_WAV="${CHUNK_DIR}/${i}.wav"
    ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$CHUNK" 2>/dev/null || { continue; })

    # Wait for previous synth to finish so PREV_WAV is fully written
    [ -n "$SYNTH_PID" ] && { wait "$SYNTH_PID" 2>/dev/null; SYNTH_PID=""; }

    # Start current synth in background — overlaps with playback of previous chunk
    curl -s --max-time 60 "${TTS_ENDPOINT}?text=${ENC}${VOICE_PARAM}" -o "$CURR_WAV" 2>/dev/null &
    SYNTH_PID=$!

    # Play previous chunk while current one synthesizes
    if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
        FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
        if [ "$FILESIZE" -gt 1000 ]; then
            # Trim leading silence for snappier playback
            TRIMMED="${PREV_WAV%.wav}.trimmed.wav"
            ffmpeg -y -ss 0.1 -i "$PREV_WAV" -c copy "$TRIMMED" 2>/dev/null \
                && mv "$TRIMMED" "$PREV_WAV" || rm -f "$TRIMMED"
            afplay "$PREV_WAV" 2>/dev/null
        fi
        rm -f "$PREV_WAV"
    fi

    PREV_WAV="$CURR_WAV"
done

# Wait for and play the last chunk
[ -n "$SYNTH_PID" ] && wait "$SYNTH_PID" 2>/dev/null
if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
    FILESIZE=$(stat -f%z "$PREV_WAV" 2>/dev/null || echo 0)
    if [ "$FILESIZE" -gt 1000 ]; then
        TRIMMED="${PREV_WAV%.wav}.trimmed.wav"
        ffmpeg -y -ss 0.1 -i "$PREV_WAV" -c copy "$TRIMMED" 2>/dev/null \
            && mv "$TRIMMED" "$PREV_WAV" || rm -f "$TRIMMED"
        afplay "$PREV_WAV" 2>/dev/null
    fi
    rm -f "$PREV_WAV"
fi
