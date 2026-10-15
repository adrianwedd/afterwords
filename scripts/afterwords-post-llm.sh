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
CHUNK_CHARS=400

# Portable file size in bytes. `stat -f%z` is BSD (macOS) only and `stat -c%s` is
# GNU only, so neither alone is safe: without a fallback the size check below read
# 0 on Linux and every chunk was synthesized a second time.
file_size() {
    local n
    n=$(wc -c < "$1" 2>/dev/null | tr -d '[:space:]')
    case "$n" in
        ''|*[!0-9]*) echo 0 ;;
        *) echo "$n" ;;
    esac
}

# ── Read payload ──────────────────────────────────────────────────────────
PAYLOAD=$(cat)
# Gateway emits flat: {"platform":"discord","response":"...","session_id":"..."}
# CLI emits nested: {"extra":{"assistant_response":"...","platform":"..."}}
TEXT=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d.get('response', '') or d.get('extra', {}).get('assistant_response', '')
print(t)
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

# Direct CLI can share a config with a gateway native hook. Select the shell
# scope explicitly to avoid duplicate local playback or external delivery.
case "${AFTERWORDS_SHELL_SCOPE:-all}" in
    all) ;;
    cli)
        # Hermes maps gateway LOCAL to cli for agent hooks. Its process marker
        # distinguishes those turns from direct CLI, which owns shell speech.
        [ "$PLATFORM" = "cli" ] && [ "${_HERMES_GATEWAY:-}" != "1" ] || exit 0
        ;;
    *) echo "afterwords: invalid AFTERWORDS_SHELL_SCOPE" >&2; exit 1 ;;
esac

PROFILE=$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('profile', '') or d.get('extra', {}).get('profile', ''))
" 2>/dev/null || true)
# Payload profile is not always present on every fire type. HERMES_HOME
# follows the routed profile (agent/shell_hooks.py builds hook-child env from
# it), so an empty payload falls back to the profile the gateway launched with.
if [ -z "$PROFILE" ]; then
    PROFILE=$(python3 -c "
import os
home = os.environ.get('HERMES_HOME', '').rstrip('/')
if '/profiles/' in home:
    print(home.rsplit('/', 1)[-1])
" 2>/dev/null || true)
fi
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
# Canonical helpers live in the repo root (strip_markdown.py, chunks.py). Every
# Hermes surface loads those, so the shell path cannot drift from the gateway
# hook. Resolution mirrors hermes/hooks/afterwords-tts/handler.py:
#   $AFTERWORDS_REPO → walk up for a dir holding both modules → ~/.claude/hooks
#     (shims there resolve back to the repo).
AFTERWORDS_REPO_ROOT=""
if [ -n "${AFTERWORDS_REPO:-}" ] && [ -f "$AFTERWORDS_REPO/strip_markdown.py" ] && [ -f "$AFTERWORDS_REPO/chunks.py" ]; then
    AFTERWORDS_REPO_ROOT="$AFTERWORDS_REPO"
else
    _probe="$SCRIPT_DIR"
    while [ -n "$_probe" ] && [ "$_probe" != "/" ]; do
        if [ -f "$_probe/strip_markdown.py" ] && [ -f "$_probe/chunks.py" ]; then
            AFTERWORDS_REPO_ROOT="$_probe"; break
        fi
        _probe=$(dirname "$_probe")
    done
fi

STRIP_SCRIPT=""
CHUNK_SCRIPT=""
if [ -n "$AFTERWORDS_REPO_ROOT" ]; then
    STRIP_SCRIPT="$AFTERWORDS_REPO_ROOT/strip_markdown.py"
    CHUNK_SCRIPT="$AFTERWORDS_REPO_ROOT/chunks.py"
fi
# Fall back to the setup.sh-installed helper dir (shims that resolve back to the
# repo). If neither resolves, the canonical modules are unreachable → log and
# skip rather than speaking with a different rule set.
if [ -z "$STRIP_SCRIPT" ] && [ -f "$HOME/.claude/hooks/strip-markdown.py" ]; then
    STRIP_SCRIPT="$HOME/.claude/hooks/strip-markdown.py"
fi
if [ -z "$CHUNK_SCRIPT" ] && [ -f "$HOME/.claude/hooks/chunk-text.py" ]; then
    CHUNK_SCRIPT="$HOME/.claude/hooks/chunk-text.py"
fi
HOOK_LOG="${TMPDIR:-/tmp}/afterwords-hermes-hook.log"
[ -f /tmp/aw-debug-on ] && exec 2>>/tmp/aw-hook-trace.log && set -x
if [ -z "$STRIP_SCRIPT" ] || [ -z "$CHUNK_SCRIPT" ]; then
    printf '%s strip/chunk helper unresolved (repo=%s) — skipping TTS\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "${AFTERWORDS_REPO_ROOT:-none}" >> "$HOOK_LOG" 2>/dev/null || true
    exit 0
fi

CLEAN=$(printf '%s' "$TEXT" | python3 "$STRIP_SCRIPT" 2>>"$HOOK_LOG" || true)
if [ -z "$CLEAN" ]; then
    # Canonical stripper missing/failed → log it, do not silently substitute a
    # weaker stripper (that is how this path drifted from the gateway hook).
    printf '%s canonical strip failed (%s) — skipping TTS\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "$STRIP_SCRIPT" >> "$HOOK_LOG" 2>/dev/null || true
    exit 0
fi

# ── Check server health ────────────────────────────────────────────────────
if ! curl -s --max-time 2 "$AFTERWORDS_HEALTH" > /dev/null 2>&1; then
    exit 0  # Server not running, fail silently
fi

# ── Resolve voice ──────────────────────────────────────────────────────────
# Priority: project .afterwords (agent key → default:) → global ~/.afterwords (agent key → default:) → server default
resolve_voice() {
# Voice key follows the firing profile (payload "profile", resolved by the
# gateway at fire time). The default profile speaks as the "hermes" agent;
# named profiles (vixen, ...) use their own key, falling back to hermes.
    local agent="$PROFILE"
    case "$agent" in ""|"default"|"hermes") agent="hermes" ;;
    esac

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
    # ── Dedup: skip if we already sent audio for this exact text recently ──
    # Compaction/retry loops can re-fire this hook with the same response text
    # hundreds of times. Hash the text to detect duplicates and throttle.
    # /tmp is shared: refuse a symlinked or foreign-owned dedup dir (same
    # hardening as the queue dirs) — but proceed WITHOUT dedup rather than
    # dropping the send.
    DEDUP_DIR="/tmp/afterwords-dedup"
    DEDUP_OK=true
    if [ -L "$DEDUP_DIR" ]; then
        DEDUP_OK=false
    else
        mkdir -p "$DEDUP_DIR" 2>/dev/null || true
        chmod 700 "$DEDUP_DIR" 2>/dev/null || true
        # stat -f%u is BSD (macOS); stat -c%u is GNU (Linux)
        DEDUP_UID=$(stat -f%u "$DEDUP_DIR" 2>/dev/null || stat -c%u "$DEDUP_DIR" 2>/dev/null || echo "")
        if [ ! -d "$DEDUP_DIR" ] || [ "$DEDUP_UID" != "$(id -u)" ]; then
            DEDUP_OK=false
        fi
    fi
    DEDUP_FILE=""
    if $DEDUP_OK; then
        # Expire stale markers so the dir does not accumulate forever
        find "$DEDUP_DIR" -type f -mmin +60 -delete 2>/dev/null || true
        TEXT_HASH=$(printf '%s' "$CLEAN" | python3 -c "
import sys, hashlib
print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:16])
" 2>/dev/null || echo "$(date +%s)$$")
        DEDUP_FILE="${DEDUP_DIR}/${PLATFORM}-${TEXT_HASH}"
        NOW_S=$(date +%s)
        # Atomic claim via noclobber: concurrent re-fires with the same text
        # race on this create, so create-or-fail picks a single winner instead
        # of a check-then-write gap letting several through.
        if ! (set -o noclobber; printf '%s\n' "$NOW_S" > "$DEDUP_FILE") 2>/dev/null; then
            # Marker already exists: skip if we sent this text in the last 60s
            # stat -f%m is BSD (macOS); stat -c%Y is GNU (Linux)
            FILE_S=$(stat -f%m "$DEDUP_FILE" 2>/dev/null || stat -c%Y "$DEDUP_FILE" 2>/dev/null || echo 0)
            AGE_S=$(( NOW_S - FILE_S ))
            if [ "$AGE_S" -lt 60 ]; then
                exit 0
            fi
            # Stale marker: refresh it and proceed
            printf '%s\n' "$NOW_S" > "$DEDUP_FILE" 2>/dev/null || true
        fi
    fi

    # Messaging delivery runs DETACHED: the hook returns instantly (inside the
# reply-turn budget) and a background job does the synth+send with no turn
# timeout above it. A wedged server delays voice notes; it can no longer
# blackhole them, block the turn, or die mid-send to the 30s callback cap.
    STAMP_ID="$$-$(date +%s)"
    STAMP=$(date +%Y%m%d-%H%M%S)
    SLUG=$(printf '%s' "$CLEAN" | python3 -c "
import sys, re
t = sys.stdin.read().strip().lower()
t = re.sub(r'[^a-z0-9]+', '-', t)
t = t.strip('-')[:60]
print(t or 'voice')
" 2>/dev/null || echo "voice")
    ARCHIVE_DIR="$HOME/.hermes/tts-archive"
    AUDIO_CACHE_DIR="$HOME/.hermes/audio_cache"
    mkdir -p "$ARCHIVE_DIR" "$AUDIO_CACHE_DIR"
    if [ -n "$CHAT_ID" ]; then
        SEND_TARGET="${PLATFORM}:${CHAT_ID}"
    else
        SEND_TARGET="$PLATFORM"
    fi
    # Dual-send guard: a reply that already carries an audio-delivery marker
    # (agent-managed voice notes) must not ALSO be auto-synthesized here.
    # Tested against the RAW PAYLOAD — the stripper consumes markers from CLEAN.
    case "$PAYLOAD" in
        *"[[audio_as_voice]]"*|*"MEDIA:"*) exit 0 ;;
    esac

    JOB_DIR="$HOME/.hermes/cache/aw-jobs"
    mkdir -p "$JOB_DIR"
    JOB_SCRIPT="$JOB_DIR/aw-send-$STAMP_ID.sh"
    CHLIST="$JOB_DIR/chunks-$STAMP_ID.txt"
    printf '%s' "$CLEAN" | python3 -c "
import sys, re
t = sys.stdin.read().strip()
parts, buf = [], ''
for para in re.split(r'(?<=[.!?]) +|\n+', t):
    if buf and len(buf) + 1 + len(para) > 380:
        parts.append(buf); buf = para
    else:
        buf = (buf + ' ' + para).strip()
if buf: parts.append(buf)
for p_ in parts[:6]:
    print(p_.replace('\n', ' '))
" > "$CHLIST" 2>/dev/null || true
    [ -s "$CHLIST" ] || printf '%s' "$CLEAN" | head -c 380 > "$CHLIST"

    # Hand the job its parameters as exported env: with set -u active in the
    # parent, an UNQUOTED heredoc expands $JOB_LOG at write time and dies
    # unbound — leaving an EMPTY job file (the exact silent-vixen bug). A
    # quoted heredoc plus env passing has no runtime expansion at all.
    export AW_PROFILE="${PROFILE:-}"
    export AW_JOB_ID="$STAMP_ID" AW_SLUG="$SLUG" AW_STAMP="$STAMP" \
        AW_ARCHIVE="$ARCHIVE_DIR" AW_CACHE="$AUDIO_CACHE_DIR" \
        AW_TARGET="$SEND_TARGET" AW_ENDPOINT="$TTS_ENDPOINT" \
        AW_VOICE="$VOICE_PARAM" AW_DEDUP="${DEDUP_FILE:-}" AW_CHLIST="$CHLIST"

    cat > "$JOB_SCRIPT" <<'JOBEOF'
#!/bin/bash
# Detached afterwords delivery job (spawned by afterwords-post-llm.sh)
JOB_LOG="$HOME/.hermes/cache/aw-jobs/job-$AW_JOB_ID.log"
echo "$(date '+%H:%M:%S') job $AW_JOB_ID start target=$AW_TARGET" >> "$JOB_LOG"
MSG_WORKDIR=$(mktemp -d /tmp/afterwords-msg.XXXXXX)
CHUNK_N=0
while IFS= read -r CHUNK; do
    [ -z "$CHUNK" ] && continue
    CHUNK_ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$CHUNK" 2>/dev/null || true)
    [ -z "$CHUNK_ENC" ] && continue
    CHUNK_WAV="$MSG_WORKDIR/chunk-$CHUNK_N.wav"
    CHUNK_OGG="$AW_CACHE/${AW_SLUG}-${AW_STAMP}-c${CHUNK_N}.ogg"
    HTTP=$(curl -s --max-time 120 -w "%{http_code}" -o "$CHUNK_WAV" "${AW_ENDPOINT}?text=${CHUNK_ENC}${AW_VOICE}" 2>/dev/null || echo "000")
    if [ "$HTTP" = "200" ] && [ -s "$CHUNK_WAV" ]; then
        ffmpeg -y -i "$CHUNK_WAV" -c:a libopus -b:a 64k "$CHUNK_OGG" 2>/dev/null || true
        lame --quiet -V 2 "$CHUNK_WAV" "${AW_ARCHIVE}/${AW_SLUG}-${AW_STAMP}-c${CHUNK_N}.mp3" 2>/dev/null || true
        printf '%s\n' "$CHUNK" > "${AW_ARCHIVE}/${AW_SLUG}-${AW_STAMP}-c${CHUNK_N}.txt" 2>/dev/null || true
        SEND_OK=false
        for ATTEMPT in 1 2 3; do
            if [ -n "$AW_PROFILE" ] && [ "$AW_PROFILE" != "default" ]; then
                HERMES_SEND=(hermes -p "$AW_PROFILE" send)
            else
                HERMES_SEND=(hermes send)
            fi
            if "${HERMES_SEND[@]}" -t "$AW_TARGET" "MEDIA:$CHUNK_OGG" >>"$JOB_LOG" 2>&1; then
                SEND_OK=true; break
            fi
            echo "$(date '+%H:%M:%S') chunk$CHUNK_N send attempt $ATTEMPT failed" >> "$JOB_LOG"
            sleep 15
        done
        if $SEND_OK; then
            echo "$(date '+%H:%M:%S') chunk$CHUNK_N sent" >> "$JOB_LOG"
        else
            echo "$(date '+%H:%M:%S') chunk$CHUNK_N PERMANENT send failure" >> "$JOB_LOG"
            [ -n "$AW_DEDUP" ] && rm -f "$AW_DEDUP"
        fi
    fi
    CHUNK_N=$((CHUNK_N + 1))
done < "$AW_CHLIST"
rm -rf "$MSG_WORKDIR"
grep -q "PERMANENT" "$JOB_LOG" 2>/dev/null || rm -f "$AW_CHLIST" "$0"
JOBEOF
    chmod +x "$JOB_SCRIPT"
    nohup bash "$JOB_SCRIPT" >/dev/null 2>&1 &
    disown || true
    exit 0
fi

# ── CLI: Chunked pipelinefi

# ── CLI: Chunked pipeline
# ── CLI: Chunked pipeline
# ── CLI: Chunked pipeline: synth N+1 while playing N ────────────────────
acquire_play_lock || exit 0
CHUNK_DIR=$(mktemp -d "/tmp/hermes-tts-chunks-XXXXXX")
trap 'rm -rf "$CHUNK_DIR"; release_play_lock' EXIT

# Split text into sentence-boundary chunks
CHUNKS=()
while IFS= read -r CHUNK; do
    [ -z "$CHUNK" ] && continue
    CHUNKS+=("$CHUNK")
done < <(printf '%s' "$CLEAN" | python3 "$CHUNK_SCRIPT" 2>>"$HOOK_LOG" || true)

NCHUNKS=${#CHUNKS[@]}
[ "$NCHUNKS" -eq 0 ] && exit 0

synth_chunk() {
    local out="$1" text="$2"
    # Timeout must cover SYNTHESIS, not just transfer. The server serialises
    # synthesis (single-GPU) and this loop keeps a second request in flight while
    # the current chunk plays, so a request can wait behind a full synthesis
    # (~18s per 400-char chunk measured). 60s was marginal; override with
    # AFTERWORDS_TTS_TIMEOUT (seconds).
    local t="${AFTERWORDS_TTS_TIMEOUT:-180}"
    if [ -n "${VOICE:-}" ]; then
        curl -s --max-time "$t" -G             --data-urlencode "text=${text}"             --data-urlencode "voice=${VOICE}"             -o "$out" "$TTS_ENDPOINT" 2>/dev/null || true
    else
        curl -s --max-time "$t" -G             --data-urlencode "text=${text}"             -o "$out" "$TTS_ENDPOINT" 2>/dev/null || true
    fi
}

PREV_WAV=""
PREV_TEXT=""
SYNTH_PID=""

for i in $(seq 1 "$NCHUNKS"); do
    CHUNK="${CHUNKS[$((i-1))]}"
    CURR_WAV="${CHUNK_DIR}/${i}.wav"

    # Wait for previous synth to finish so PREV_WAV is fully written
    [ -n "$SYNTH_PID" ] && { wait "$SYNTH_PID" 2>/dev/null; SYNTH_PID=""; }

    # Start current synth in background — overlaps with playback of previous chunk
    synth_chunk "$CURR_WAV" "$CHUNK" &
    SYNTH_PID=$!

    # Play previous chunk while current one synthesizes
    if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
        FILESIZE=$(file_size "$PREV_WAV")
        if [ "$FILESIZE" -le 1000 ] && [ -n "$PREV_TEXT" ]; then
            synth_chunk "$PREV_WAV" "$PREV_TEXT"
            FILESIZE=$(file_size "$PREV_WAV")
        fi
        if [ "$FILESIZE" -gt 1000 ]; then
            [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null
        fi
        rm -f "$PREV_WAV"
    fi

    PREV_WAV="$CURR_WAV"
    PREV_TEXT="$CHUNK"
done

# Wait for and play the last chunk
[ -n "$SYNTH_PID" ] && wait "$SYNTH_PID" 2>/dev/null
if [ -n "$PREV_WAV" ] && [ -f "$PREV_WAV" ]; then
    FILESIZE=$(file_size "$PREV_WAV")
    if [ "$FILESIZE" -le 1000 ] && [ -n "$PREV_TEXT" ]; then
        synth_chunk "$PREV_WAV" "$PREV_TEXT"
        FILESIZE=$(file_size "$PREV_WAV")
    fi
    if [ "$FILESIZE" -gt 1000 ]; then
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
