#!/usr/bin/env bash
#
# afterwords-tts-command.sh — Command provider for Hermes TTS
#
# Called by Hermes's command-type TTS provider system.
# Reads text from {input_path}, resolves voice from .afterwords files,
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
#   {voice}       — voice name from config (may be empty)
#   {format}      — output format (wav, mp3, etc.)
#
set -euo pipefail

TEXT_PATH="${1:?Usage: afterwords-tts-command.sh <input_path> <output_path> [voice]}"
OUTPUT_PATH="${2:?Missing output_path}"
CONFIG_VOICE="${3:-}"

PORT=7860
AFTERWORDS_URL="http://127.0.0.1:${PORT}"
TTS_ENDPOINT="${AFTERWORDS_URL}/synthesize"

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

archive_mp3_sidecar() {
    # $1 = the WAV actually delivered. Archive MP3 + text sidecar of spoken text.
    local src="$1" stamp archive_dir slug archive_mp3
    stamp=$(date +%Y%m%d-%H%M%S)
    archive_dir="$HOME/.hermes/tts-archive"
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
# HERMES_SESSION_PLATFORM is set by the gateway on messaging platforms.
# If unset or "cli"/"local", we're on CLI — chunked local synthesis + playback.
ASYNC=false
if [ -z "${HERMES_SESSION_PLATFORM:-}" ] || [ "$HERMES_SESSION_PLATFORM" = "cli" ] || [ "$HERMES_SESSION_PLATFORM" = "local" ]; then
    ASYNC=true
fi

if $ASYNC; then
    # ── CLI mode: synthesize the real artifact, play locally as it lands ──
    MUTE_FILE="/tmp/afterwords-muted"   # `afterwords mute` toggles this; skip local playback when present
    PLAY_LOCK="/tmp/afterwords-play.lock"
    PLAY_PID="/tmp/afterwords-play.pid"
    PLAY_OK=true

    # Acquire the shared play lock (mkdir-based for atomicity). Failing to get it
    # costs local playback only — never the artifact.
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
            PLAY_OK=false
            printf 'afterwords: play lock held for ~60s — skipping local playback\n' >&2
            break
        fi
        sleep 0.3
    done
    if $PLAY_OK; then
        bash -c 'echo $PPID' > "$PLAY_PID" 2>/dev/null || true
    fi

    CHUNK_DIR=$(mktemp -d "/tmp/afterwords-cmd-XXXXXX")
    release_play_lock() {
        rm -f "$PLAY_PID"
        rm -rf "$PLAY_LOCK"
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

    synth_chunk() {
        # $1 = destination WAV, $2 = text. The timeout must cover SYNTHESIS: the
        # server serialises it (single-GPU) and requests queue behind each other.
        local out="$1" text="$2"
        local t="${AFTERWORDS_TTS_TIMEOUT:-180}"
        if [ -n "${VOICE:-}" ]; then
            curl -s --max-time "$t" -G --data-urlencode "text=${text}" --data-urlencode "voice=${VOICE}" -o "$out" "$TTS_ENDPOINT" 2>/dev/null || true
        else
            curl -s --max-time "$t" -G --data-urlencode "text=${text}" -o "$out" "$TTS_ENDPOINT" 2>/dev/null || true
        fi
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
                if [ "$PREV_SIZE" -le 1000 ]; then
                    synth_chunk "$PREV_WAV" "${CHUNKS[$((IDX - 2))]}"
                    PREV_SIZE=$(file_size "$PREV_WAV")
                fi
                if [ "$PREV_SIZE" -gt 1000 ] && $PLAY_OK; then
                    [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null
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
            [ -f "$MUTE_FILE" ] || afplay "$LAST_WAV" 2>/dev/null
        fi
    fi

    # ── Deliver the real artifact to {output_path} ──────────────────────
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
            exit 1
        fi
    fi

    archive_mp3_sidecar "$OUTPUT_PATH"
    printf 'afterwords: delivered %s bytes to %s (%d chunk(s))\n' \
        "$(file_size "$OUTPUT_PATH")" "$OUTPUT_PATH" "$NCHUNKS" >&2
    $PARTIAL && exit 1
    exit 0
fi

# ── Non-CLI platforms (Telegram, Discord): synchronous single request ──
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

archive_mp3_sidecar "$OUTPUT_PATH"
