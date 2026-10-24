#!/usr/bin/env bash
#
# afterwords-tts-command.sh — Command provider for Hermes TTS
#
# Called by Hermes's command-type TTS provider system.
# Reads text from {input_path}, speaks it in the voice Hermes passes as {voice},
# synthesizes via the Afterwords server, and writes the REAL synthesized
# artifact to {output_path}.
#
# CONTRACT — on every platform, exit 0 means: the audio at {output_path} is the
# speech for the text in {input_path}. Hermes enforces only "a non-empty file
# exists at the configured output path" (tools/tts_command_provider.py), so that
# artifact is the only thing a caller can judge delivery by. A silent placeholder
# satisfies the check while delivering none of the speech — which is exactly the
# failure this script used to have: on CLI it wrote 0.1s of silence and fired real
# synthesis into a detached subshell, so the speech reached only
# ~/.hermes/tts-archive/, where the sole reader is a paused cron job (issue #120).
#
# The contract is therefore all-or-nothing against the CHUNK COUNT, not against
# non-emptiness:
#   * every chunk present  → artifact + exit 0
#   * some chunks missing  → artifact (the survivors, best-effort) + exit 1
#   * no usable chunk      → no artifact + exit 1
# Exit status is the only signal the caller reads: Hermes raises on a non-zero
# exit, and it has no partial-result contract, so a partial artifact reported as
# success would be the same lie at smaller scale.
#
# Architecture:
#   - Chunked synthesis through the canonical chunks.py (~400-char sentence
#     chunks), each requested with the previous one still in flight, so synthesis
#     pipelines behind playback the same way the other surfaces do.
#   - Chunks are concatenated (stdlib `wave`, ffmpeg fallback) into one WAV at
#     {output_path}, so a long reply arrives at the caller complete.
#   - Local playback is mute-guarded (/tmp/afterwords-muted) and coordinated via
#     the shared play lock (/tmp/afterwords-play.lock + .pid). Playback is
#     best-effort: it can be muted or skipped, but it never gates the artifact.
#   - Archive MP3 + text sidecar under ~/.hermes/tts-archive/ (unchanged), written
#     from the artifact that was actually delivered.
#   - Per-chunk progress is emitted on stderr: it is the diagnostic record, and it
#     keeps Hermes's IDLE timeout (120s, reset on any provider output) alive while
#     the server serialises synthesis.
#
# Placeholders provided by Hermes:
#   {input_path}  / {text_path} — temp file containing the text to speak
#   {output_path} — path where the audio file must be written
#   {voice}       — tts.providers.afterwords.voice of the serving profile (REQUIRED)
#   {format}      — output format (wav, mp3, etc.)
#
set -euo pipefail

TEXT_PATH="${1:?Usage: afterwords-tts-command.sh <input_path> <output_path> <voice>}"
OUTPUT_PATH="${2:?Missing output_path}"
CONFIG_VOICE="${3:-}"

# Hermes native /voice owns playback of its returned sentence artifacts.
# Caller-scoped ownership wins over the historical profile-wide setting.
# A native consumer must identify this call, rather than silencing every tool.
PLAYBACK_OWNER="provider"
case "${AFTERWORDS_TTS_CALLER:-tool}" in
    native) PLAYBACK_OWNER="hermes" ;;
    tool|gateway) ;;
    *) echo "Error: invalid AFTERWORDS_TTS_CALLER" >&2; exit 2 ;;
esac
LEGACY_PLAYBACK_OWNER="${AFTERWORDS_PLAYBACK_OWNER:-provider}"
case "$LEGACY_PLAYBACK_OWNER" in
    provider|hermes) ;;
    *) echo "Error: AFTERWORDS_PLAYBACK_OWNER must be provider or hermes" >&2; exit 2 ;;
esac

# Opt-in profile-local loopback port; existing default remains unchanged.
PORT="${AFTERWORDS_PORT:-7860}"
case "$PORT" in
    ''|*[!0-9]*) echo "Error: AFTERWORDS_PORT must be a local TCP port" >&2; exit 2 ;;
esac
if [ "${#PORT}" -gt 5 ] || (( 10#$PORT < 1 || 10#$PORT > 65535 )); then
    echo "Error: AFTERWORDS_PORT must be between 1 and 65535" >&2
    exit 2
fi
PORT=$((10#$PORT))
AFTERWORDS_URL="http://127.0.0.1:${PORT}"
TTS_ENDPOINT="${AFTERWORDS_URL}/synthesize"

# Read the text
TEXT=$(cat "$TEXT_PATH" 2>/dev/null || true)
if [ -z "$TEXT" ]; then
    echo "Error: empty input text" >&2
    exit 1
fi

# ── Speaking profile ──────────────────────────────────────────────────
# Hermes runs this command with HERMES_HOME set to the profile it is serving
# (~/.hermes for the default profile, ~/.hermes/profiles/<name> otherwise). It is
# the only identity this process receives, so everything profile-specific below
# (voice requirement, archive location, evidence log) keys off it.
PROFILE_HOME="${HERMES_HOME:-$HOME/.hermes}"
PROFILE_HOME="${PROFILE_HOME%/}"

# ── Who delivers this artifact ────────────────────────────────────────
# A gateway turn's audio is delivered by that gateway, with the serving
# profile's own bot; only a direct CLI turn is spoken (and relayed) from here.
# HERMES_SESSION_PLATFORM alone cannot tell them apart: the gateway clears it
# before the post-handler auto-TTS that answers voice-message input, so those
# replies arrived looking like CLI — played on this Mac and re-relayed by the
# feed poller. The gateway process marker (_HERMES_GATEWAY=1, inherited by this
# command) is the reliable signal; the platform name is kept for messaging
# contexts outside a gateway process.
DELIVERY="cli"
case "${HERMES_SESSION_PLATFORM:-}" in
    ""|cli|local|desktop) ;;
    *) DELIVERY="gateway" ;;
esac
if [ "$DELIVERY" = "cli" ] && [ "${_HERMES_GATEWAY:-}" = "1" ]; then
    case "${HERMES_SESSION_SOURCE:-}" in
        cli|tui|desktop|oneshot) ;;
        *) DELIVERY="gateway" ;;
    esac
fi
[ "${AFTERWORDS_TTS_CALLER:-}" != "gateway" ] || DELIVERY="gateway"
case "$PROFILE_HOME" in
    */profiles/*) PROFILE="${PROFILE_HOME##*/}" ;;
    *) PROFILE="default" ;;
esac

# ── Voice: the profile's tts.providers.afterwords.voice, passed as {voice} ──
# There is exactly one authoritative setting per profile and NO fallback. This
# used to fall back to .afterwords under the hardcoded "hermes" agent key, then
# to the server default — so a profile whose provider block lacked `voice:`
# silently spoke with the default profile's voice (Vixen as seven-of-nine,
# 2026-10-15). An unresolved voice is a configuration error and fails visibly.
VOICE="$CONFIG_VOICE"
if [ -z "$VOICE" ]; then
    printf 'afterwords: no voice configured for Hermes profile "%s" (%s): set tts.providers.afterwords.voice and keep {voice} in the command template — refusing to fall back to another voice\n' \
        "$PROFILE" "$PROFILE_HOME/config.yaml" >&2
    mkdir -p "$PROFILE_HOME/logs" 2>/dev/null || true
    printf '%s profile=%s voice= platform=%s outcome=failed:no-voice-configured pid=%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "$PROFILE" "${HERMES_SESSION_PLATFORM:-}/$DELIVERY" "$$" \
        >> "$PROFILE_HOME/logs/afterwords-command.log" 2>/dev/null || true
    exit 2
fi

# ── Canonical strip + chunk helpers ────────────────────────────────────
# ONE implementation each, at the repo root: strip_markdown.py and chunks.py.
# Resolution mirrors scripts/afterwords-post-llm.sh and the gateway handler:
#   $AFTERWORDS_REPO → walk up for a dir holding both modules → ~/.claude/hooks
#     (shims there resolve back to the repo).
AFTERWORDS_REPO_ROOT=""
if [ -n "${AFTERWORDS_REPO:-}" ] \
   && [ -f "$AFTERWORDS_REPO/strip_markdown.py" ] && [ -f "$AFTERWORDS_REPO/chunks.py" ]; then
    AFTERWORDS_REPO_ROOT="$AFTERWORDS_REPO"
else
    _probe="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
# setup.sh-installed helper dir (shims that resolve back to the repo).
if [ -z "$STRIP_SCRIPT" ] && [ -f "$HOME/.claude/hooks/strip-markdown.py" ]; then
    STRIP_SCRIPT="$HOME/.claude/hooks/strip-markdown.py"
fi
if [ -z "$CHUNK_SCRIPT" ] && [ -f "$HOME/.claude/hooks/chunk-text.py" ]; then
    CHUNK_SCRIPT="$HOME/.claude/hooks/chunk-text.py"
fi

# Strip markdown via the canonical implementation. No truncation: the artifact
# carries the whole reply.
CLEANED=""
if [ -n "$STRIP_SCRIPT" ] && [ -f "$STRIP_SCRIPT" ]; then
    CLEANED=$(printf '%s' "$TEXT" | python3 "$STRIP_SCRIPT" 2>/dev/null || true)
fi
if [ -z "$CLEANED" ]; then
    # Canonical stripper unavailable → speak the raw text rather than
    # substituting a different (shell-sed) rule set.
    printf '%s command-provider strip helper unresolved (%s); using raw text\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "${STRIP_SCRIPT:-none}" \
        >> "${TMPDIR:-/tmp}/afterwords-hermes-hook.log" 2>/dev/null || true
    CLEANED="$TEXT"
fi

# Portable file size in bytes: `stat -f%z` is BSD-only, `stat -c%s` GNU-only.
file_size() {
    local n
    n=$(wc -c < "$1" 2>/dev/null | tr -d '[:space:]')
    case "$n" in
        ''|*[!0-9]*) echo 0 ;;
        *) echo "$n" ;;
    esac
}

# Concatenate chunk WAVs into $1 in order. Refuses (non-zero) unless every
# source chunk is readable and shares one set of parameters.
concat_wavs() {
    python3 - "$@" <<'PY'
import os
import sys
import wave

dest, srcs = sys.argv[1], sys.argv[2:]
if not srcs:
    sys.exit("no source chunks")

params = None
frames = []
for path in srcs:
    try:
        with wave.open(path, "rb") as handle:
            current = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate())
            if params is None:
                params = current
            elif current != params:
                sys.exit(f"chunk parameters differ: {path} {current} != {params}")
            frames.append(handle.readframes(handle.getnframes()))
    except Exception as exc:
        sys.exit(f"cannot read chunk {path}: {exc}")

tmp = f"{dest}.tmp"
try:
    with wave.open(tmp, "wb") as out:
        out.setnchannels(params[0])
        out.setsampwidth(params[1])
        out.setframerate(params[2])
        for frame in frames:
            out.writeframes(frame)
    os.replace(tmp, dest)
except Exception as exc:
    sys.exit(f"cannot write {dest}: {exc}")
PY
}

# Build the URL (single-request fallback paths)
ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CLEANED")
URL="http://127.0.0.1:${PORT}/synthesize?text=${ENCODED}"
if [ -n "$VOICE" ]; then
    VOICE_ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$VOICE")
    URL="${URL}&voice=${VOICE_ENCODED}"
fi

# Per-request evidence: which profile asked for which voice, and what came back.
# Lives in the speaking profile's own logs so each bot's record is separable.
EVIDENCE_LOG="$PROFILE_HOME/logs/afterwords-command.log"
TEXT_SHA=$(printf '%s' "$CLEANED" | shasum -a 256 2>/dev/null | cut -c1-12)
log_evidence() {
    # $1 = outcome (ok / partial / failed:<reason>), $2 = artifact bytes
    mkdir -p "${EVIDENCE_LOG%/*}" 2>/dev/null || true
    printf '%s profile=%s voice=%s platform=%s chars=%s sha=%s outcome=%s bytes=%s pid=%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "$PROFILE" "$VOICE" "${HERMES_SESSION_PLATFORM:-}/$DELIVERY" \
        "${#CLEANED}" "${TEXT_SHA:-?}" "$1" "${2:-0}" "$$" >> "$EVIDENCE_LOG" 2>/dev/null || true
}

# Archive location is scoped to the speaking profile, and to who delivers.
#   * CLI turns: $PROFILE_HOME/tts-archive. For the default profile that is
#     ~/.hermes/tts-archive, which tts-feed-send.py relays with the DEFAULT
#     profile's bot — correct only for default-profile speech, so a named
#     profile never writes there.
#   * Messaging turns: the gateway already delivered this artifact with the
#     serving profile's own bot. Writing it into the relayed directory made the
#     feed poller send it a second time with the default bot (Vixen's voice
#     arriving from the Hermes bot). Those are kept in a non-relayed subdir.
ARCHIVE_DIR="$PROFILE_HOME/tts-archive"
if [ "$DELIVERY" = "gateway" ]; then
    ARCHIVE_DIR="$PROFILE_HOME/tts-archive/gateway-delivered"
elif [ "$PLAYBACK_OWNER" = "hermes" ]; then
    ARCHIVE_DIR="$PROFILE_HOME/tts-archive/consumer-delivered"
fi

archive_mp3_sidecar() {
    # $1 = the WAV actually delivered. Archive MP3 + text sidecar of spoken text.
    local src="$1" stamp archive_dir slug archive_mp3
    stamp=$(date +%Y%m%d-%H%M%S)
    archive_dir="$ARCHIVE_DIR"
    mkdir -p "$archive_dir" 2>/dev/null || true
    slug=$(printf '%s' "$CLEANED" | python3 -c "
import sys, re
t = sys.stdin.read().strip().lower()
t = re.sub(r'[^a-z0-9]+', '-', t)
t = t.strip('-')[:60]
print(t or 'voice')
" 2>/dev/null || echo "voice")
    archive_mp3="${archive_dir}/${slug}-${stamp}.mp3"
    lame --quiet -V 2 "$src" "$archive_mp3" 2>/dev/null || true
    printf '%s\n' "$CLEANED" > "${archive_mp3%.mp3}.txt" 2>/dev/null || true
}

# ── Platform detection ────────────────────────────────────────────────
# Direct CLI → chunked local synthesis + playback. Gateway → synchronous artifact.
ASYNC=false
if [ "$DELIVERY" = "cli" ]; then
    ASYNC=true
fi

# All platforms assemble every chunk. Only CLI may play locally.
MUTE_FILE="${AFTERWORDS_MUTE_FILE:-/tmp/afterwords-muted}"   # `afterwords mute` toggles this; skip local playback when present
PLAY_LOCK="${AFTERWORDS_PLAY_LOCK:-/tmp/afterwords-play.lock}"
PLAY_PID="${AFTERWORDS_PLAY_PID:-/tmp/afterwords-play.pid}"
PLAY_OK=false
if $ASYNC && [ "$PLAYBACK_OWNER" = "provider" ]; then PLAY_OK=true; fi
PLAY_LOCK_OWNED=false

# Acquire the shared play lock (mkdir-based for atomicity). Failing to get it
# costs local playback only — never the artifact.
WAITED=0
while $PLAY_OK && ! mkdir "$PLAY_LOCK" 2>/dev/null; do
    HOLDER=$(cat "$PLAY_PID" 2>/dev/null || true)
    if [ -z "$HOLDER" ]; then sleep 0.05; HOLDER=$(cat "$PLAY_PID" 2>/dev/null || true); fi
    if [ -z "$HOLDER" ] || ! kill -0 "$HOLDER" 2>/dev/null; then
        rm -rf "$PLAY_LOCK" "$PLAY_PID"
        continue
    fi
    WAITED=$((WAITED + 1))
    if [ "$WAITED" -ge 200 ]; then
        PLAY_OK=false
        printf 'afterwords: play lock held for ~60s — skipping local playback\n' >&2
        break
    fi
    sleep 0.3
done
if $PLAY_OK; then
    PLAY_LOCK_OWNED=true
    bash -c 'echo $PPID' > "$PLAY_PID" 2>/dev/null || true
fi

CHUNK_DIR=$(mktemp -d "/tmp/afterwords-cmd-XXXXXX")
release_play_lock() {
    if $PLAY_LOCK_OWNED; then
        rm -f "$PLAY_PID"
        rm -rf "$PLAY_LOCK"
    fi
    rm -rf "$CHUNK_DIR"
}
trap release_play_lock EXIT

# Split into ~400-char sentence chunks via the canonical chunker. If it is
# unreachable, speak the whole reply as one chunk rather than a weaker splitter.
CHUNKS=()
if [ -n "$CHUNK_SCRIPT" ] && [ -f "$CHUNK_SCRIPT" ]; then
    while IFS= read -r CHUNK_LINE; do
        [ -z "$CHUNK_LINE" ] && continue
        CHUNKS+=("$CHUNK_LINE")
    done < <(printf '%s' "$CLEANED" | python3 "$CHUNK_SCRIPT" 2>/dev/null || true)
fi
if [ "${#CHUNKS[@]}" -eq 0 ]; then
    printf '%s command-provider chunk helper unresolved (%s); speaking as one chunk\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "${CHUNK_SCRIPT:-none}" \
        >> "${TMPDIR:-/tmp}/afterwords-hermes-hook.log" 2>/dev/null || true
    CHUNKS=("$CLEANED")
fi
NCHUNKS=${#CHUNKS[@]}

CURL_AUTH=()
if [ -n "$AFTERWORDS_REPO_ROOT" ] && [ -f "$AFTERWORDS_REPO_ROOT/expressive/auth.py" ]; then
    python3 "$AFTERWORDS_REPO_ROOT/expressive/auth.py" --port "$PORT" \
        --curl-headers "$CHUNK_DIR/auth.headers" || exit 2
    [ ! -f "$CHUNK_DIR/auth.headers" ] || CURL_AUTH=(-H "@$CHUNK_DIR/auth.headers")
fi

synth_chunk() {
    # $1 = destination WAV, $2 = text. The timeout must cover SYNTHESIS: the
    # server serialises it (single-GPU) and requests queue behind each other.
    local out="$1" text="$2"
    # The HTTP status lands beside the WAV ($out.status) so a server rejection
    # (e.g. `unknown voice`) is reported as such, not as a missing chunk.
    local t="${AFTERWORDS_TTS_TIMEOUT:-180}" code
    if [ -n "${VOICE:-}" ]; then
        code=$(curl ${CURL_AUTH[@]+"${CURL_AUTH[@]}"} -s --max-time "$t" -w "%{http_code}" -G --data-urlencode "text=${text}" --data-urlencode "voice=${VOICE}" -o "$out" "$TTS_ENDPOINT" 2>/dev/null) || true
    else
        code=$(curl ${CURL_AUTH[@]+"${CURL_AUTH[@]}"} -s --max-time "$t" -w "%{http_code}" -G --data-urlencode "text=${text}" -o "$out" "$TTS_ENDPOINT" 2>/dev/null) || true
    fi
    printf '%s' "${code:-000}" > "${out}.status"
}

# 4xx is the server refusing the request itself; retrying cannot help.
chunk_rejected() {
    case "$(cat "${1}.status" 2>/dev/null)" in 4??) return 0 ;; esac
    return 1
}

WAVS=()
IDX=0
for CHUNK in "${CHUNKS[@]}"; do
    IDX=$((IDX + 1))
    CURR_WAV="${CHUNK_DIR}/${IDX}.wav"
    WAVS+=("$CURR_WAV")

    # Current chunk synthesizes in the background...
    synth_chunk "$CURR_WAV" "$CHUNK" &
    CURR_PID=$!

    # ...while the previous one plays: latency-to-first-audio is one chunk's
    # synthesis, not the whole reply's.
    if [ "$IDX" -gt 1 ]; then
        PREV_WAV="${CHUNK_DIR}/$((IDX - 1)).wav"
        if [ -f "$PREV_WAV" ]; then
            PREV_SIZE=$(file_size "$PREV_WAV")
            if [ "$PREV_SIZE" -le 1000 ] && ! chunk_rejected "$PREV_WAV"; then
                synth_chunk "$PREV_WAV" "${CHUNKS[$((IDX - 2))]}"
                PREV_SIZE=$(file_size "$PREV_WAV")
            fi
            if [ "$PREV_SIZE" -gt 1000 ] && $PLAY_OK; then
                [ "$PLAYBACK_OWNER" = "hermes" ] || [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null || printf 'afterwords: local playback failed; retaining synthesized artifact\n' >&2
            fi
        fi
    fi
    wait "$CURR_PID" 2>/dev/null || true
    printf 'afterwords: synthesized chunk %d/%d (%s bytes)\n' \
        "$IDX" "$NCHUNKS" "$(file_size "$CURR_WAV")" >&2
done

# The loop above only plays the chunk *before* each new one; play the last.
LAST_WAV="${CHUNK_DIR}/${IDX}.wav"
if [ -f "$LAST_WAV" ] && $PLAY_OK; then
    if [ "$(file_size "$LAST_WAV")" -gt 1000 ]; then
        [ "$PLAYBACK_OWNER" = "hermes" ] || [ -f "$MUTE_FILE" ] || afplay "$LAST_WAV" 2>/dev/null || printf 'afterwords: local playback failed; retaining synthesized artifact\n' >&2
    fi
fi

# ── Deliver the real artifact to {output_path} ──────────────────────
# A server rejection fails the whole request with the server's reason (e.g.
# `unknown voice: <name>`) — never a retry with a different voice.
for WAV in "${WAVS[@]}"; do
    if chunk_rejected "$WAV"; then
        HTTP_CODE=$(cat "${WAV}.status")
        echo "Afterwords TTS failed (HTTP $HTTP_CODE, profile=$PROFILE, voice=$VOICE): $(head -c 200 "$WAV" 2>/dev/null)" >&2
        rm -f "$OUTPUT_PATH"
        log_evidence "failed:http-$HTTP_CODE" 0
        exit 1
    fi
done

DELIVERED=""
NONEMPTY=()
for WAV in "${WAVS[@]}"; do
    if [ -f "$WAV" ] && [ "$(file_size "$WAV")" -gt 1000 ]; then
        NONEMPTY+=("$WAV")
    fi
done

# Success requires ALL chunks: "the audio at {output_path} is the speech for
# the input" only holds when none is missing. Comparing the usable count to
# NCHUNKS — not merely testing whether the count is 1 — is what separates "a
# one-chunk reply" from "1 of 5 chunks survived", two states that otherwise
# take the same code path and report the same exit status.
PARTIAL=false
if [ "${#NONEMPTY[@]}" -eq "$NCHUNKS" ]; then
    if [ "${#NONEMPTY[@]}" -eq 1 ]; then
        cp "${NONEMPTY[0]}" "$OUTPUT_PATH"
        DELIVERED="$OUTPUT_PATH"
    elif concat_wavs "$OUTPUT_PATH" "${NONEMPTY[@]}"; then
        DELIVERED="$OUTPUT_PATH"
    elif command -v ffmpeg >/dev/null 2>&1; then
        printf 'afterwords: stdlib concat failed — falling back to ffmpeg\n' >&2
        CONCAT_LIST="${CHUNK_DIR}/concat.txt"
        for WAV in "${NONEMPTY[@]}"; do
            printf "file '%s'\n" "$WAV" >> "$CONCAT_LIST"
        done
        if ffmpeg -v error -f concat -safe 0 -i "$CONCAT_LIST" -c copy -y "$OUTPUT_PATH" 2>/dev/null \
           && [ "$(file_size "$OUTPUT_PATH")" -gt 1000 ]; then
            DELIVERED="$OUTPUT_PATH"
        fi
    fi
fi

if [ -z "$DELIVERED" ]; then
    # Short of the full speech. The artifact is still written when any chunk
    # survived — forensics beat nothing — but the exit status must carry the
    # failure: a caller that has no partial-result contract reads exit 0 as
    # "this is the speech", which is the same lie the placeholder told.
    PARTIAL=true
    printf 'afterwords: incomplete audio (%d/%d chunks usable)\n' \
        "${#NONEMPTY[@]}" "$NCHUNKS" >&2
    if [ "${#NONEMPTY[@]}" -ge 1 ]; then
        if [ "${#NONEMPTY[@]}" -eq 1 ] || ! concat_wavs "$OUTPUT_PATH" "${NONEMPTY[@]}"; then
            cp "${NONEMPTY[0]}" "$OUTPUT_PATH"
        fi
        printf 'afterwords: delivered PARTIAL audio (%d/%d chunks) — exiting non-zero\n' \
            "${#NONEMPTY[@]}" "$NCHUNKS" >&2
    else
        rm -f "$OUTPUT_PATH"
        log_evidence "failed:no-usable-chunk" 0
        exit 1
    fi
fi

archive_mp3_sidecar "$OUTPUT_PATH"
printf 'afterwords: delivered %s bytes to %s (%d chunk(s))\n' \
    "$(file_size "$OUTPUT_PATH")" "$OUTPUT_PATH" "$NCHUNKS" >&2
if $PARTIAL; then
    log_evidence "partial" "$(file_size "$OUTPUT_PATH")"
    exit 1
fi
log_evidence "ok" "$(file_size "$OUTPUT_PATH")"
exit 0
