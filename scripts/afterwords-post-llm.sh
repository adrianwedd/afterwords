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
AFTERWORDS_HEALTH="$AFTERWORDS_URL/health"
TTS_ENDPOINT="$AFTERWORDS_URL/synthesize"
CHUNK_CHARS=200

# ── Read payload ──────────────────────────────────────────────────────────
PAYLOAD=$(cat)
# Gateway emits flat: {"platform":"discord","response":"...","session_id":"..."}
# CLI emits nested: {"extra":{"assistant_response":"...","platform":"..."}}
TEXT=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d.get('response', '') or d.get('extra', {}).get('assistant_response', '')
print(t[:1000])
" 2>/dev/null || true)
CWD=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('cwd', '') or d.get('extra', {}).get('cwd', ''))
" 2>/dev/null || true)
PLATFORM=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('platform', '') or d.get('extra', {}).get('platform', ''))
" 2>/dev/null || true)
CHAT_ID=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('chat_id', '') or d.get('extra', {}).get('chat_id', ''))
" 2>/dev/null || true)

# ── Platform routing ──────────────────────────────────────────────────────
# CLI/local: play audio locally via afplay
# Messaging platforms: synthesize full audio, send as attachment via hermes send
MSG_PLATFORM=false
case "$PLATFORM" in
    telegram|discord) MSG_PLATFORM=true ;;
    slack|signal|matrix|whatsapp|email|sms|feishu|wecom|yuanbao) exit 0 ;;
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

# ── Messaging platform path: synthesize full audio, send as attachment ──
if $MSG_PLATFORM; then
    # Concatenate all chunks into one text for single synthesize call
    SINGLE_WAV=$(mktemp /tmp/afterwords-msg-XXXXXX.wav)
    ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$CLEAN" 2>/dev/null || true)
    [ -z "$ENC" ] && exit 0

    HTTP_CODE=$(curl -s -w "%{http_code}" -o "$SINGLE_WAV" "${TTS_ENDPOINT}?text=${ENC}${VOICE_PARAM}" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ] && [ -s "$SINGLE_WAV" ]; then
        # Archive as MP3 — filename derived from spoken text
        STAMP=$(date +%Y%m%d-%H%M%S)
        SLUG=$(printf '%s' "$CLEAN" | python3 -c "
import sys, re
t = sys.stdin.read().strip().lower()
t = re.sub(r'[^a-z0-9]+', '-', t)
t = t.strip('-')[:60]
print(t or 'voice')
" 2>/dev/null || echo "voice")
        ARCHIVE_DIR="$HOME/.hermes/tts-archive"
        mkdir -p "$ARCHIVE_DIR"
        ARCHIVE_MP3="${ARCHIVE_DIR}/${SLUG}-${STAMP}.mp3"
        lame --quiet -V 2 "$SINGLE_WAV" "$ARCHIVE_MP3" 2>/dev/null || true
        printf '%s\n' "$CLEAN" > "${ARCHIVE_MP3%.mp3}.txt" 2>/dev/null || true

        # Pre-seed the feed watcher's seen-set so it does NOT re-send this
        # archived file. The watcher keys hermes-archive files by bare filename
        # (see tts-feed-send.py: `name in new_seen`). We add that marker here so
        # the inline send below is the single delivery for this response.
        SEEN_FILE="$HOME/.hermes/tts-feed-seen.json"
        python3 -c "
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
marker = sys.argv[2]
try:
    seen = set(json.loads(p.read_text())) if p.exists() else set()
except Exception:
    seen = set()
seen.add(marker)
p.parent.mkdir(parents=True, exist_ok=True)
# Atomic swap: temp file in the SAME dir, then os.replace() so a crash
# mid-write cannot truncate tts-feed-seen.json (which would make the
# watcher re-send the entire backlog on its next load_seen()).
import os
tmp = p.with_suffix(p.suffix + '.tmp')
tmp.write_text(json.dumps(sorted(seen), indent=2))
os.replace(tmp, p)
" "$SEEN_FILE" "${SLUG}-${STAMP}.mp3" 2>/dev/null || true

        # Convert to OGG for Telegram voice message
        OGG_FILE="${SINGLE_WAV%.wav}.ogg"
        ffmpeg -y -i "$SINGLE_WAV" -c:a libopus -b:a 64k "$OGG_FILE" 2>/dev/null || true

        # Copy to audio_cache (MEDIA: allowed dir) for delivery
        AUDIO_CACHE_DIR="$HOME/.hermes/audio_cache"
        mkdir -p "$AUDIO_CACHE_DIR"

        # Reply into the ORIGINATING chat when we know it: hermes send supports
        # `platform:chat_id`. Fall back to the platform home channel otherwise.
        if [ -n "$CHAT_ID" ]; then
            SEND_TARGET="${PLATFORM}:${CHAT_ID}"
        else
            SEND_TARGET="${PLATFORM}"
        fi

        # Send to the originating platform using MEDIA: tag for proper attachment delivery
        case "$PLATFORM" in
            telegram)
                OGG_CACHE="$AUDIO_CACHE_DIR/${SLUG}-${STAMP}.ogg"
                cp "$OGG_FILE" "$OGG_CACHE" 2>/dev/null || true
                hermes send -t "$SEND_TARGET" "MEDIA:$OGG_CACHE" 2>/dev/null || true
                ;;
            discord)
                MP3_CACHE="$AUDIO_CACHE_DIR/${SLUG}-${STAMP}.mp3"
                cp "$ARCHIVE_MP3" "$MP3_CACHE" 2>/dev/null || true
                hermes send -t "$SEND_TARGET" "MEDIA:$MP3_CACHE" 2>/dev/null || true
                ;;
        esac

        rm -f "$SINGLE_WAV" "$OGG_FILE"
    else
        rm -f "$SINGLE_WAV"
    fi
    exit 0
fi

# ── CLI: Chunked pipeline: synth N+1 while playing N ────────────────────
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
            [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null
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
        [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null
    fi
    rm -f "$PREV_WAV"
fi

# ── Outbound/CLI external delivery is owned by the feed watcher ─────────────
# Local sessions (no originating chat) do NOT send inline from this hook.
# tts-feed-send.py watches ~/.hermes/tts-archive + ~/.claude/tts-archive and
# delivers to the platform home channel, gated by an explicit `send_to:`
# opt-in (env AFTERWORDS_SEND_TO, or a send_to: line in .afterwords / ~/.afterwords).
# Merely having a .afterwords (a local-playback voice config) is NOT consent to
# broadcast externally. See docs/hermes-integration.md.
