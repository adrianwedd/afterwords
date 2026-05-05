#!/usr/bin/env bash
# Watch the current Codex session JSONL and enqueue final answers for TTS.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="${SCRIPT_DIR}/codex-tts-hook.sh"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CODEX_WATCH_LOG="${CODEX_WATCH_LOG:-/tmp/codex-tts-watch.log}"
DIAGNOSE=0

if [ "${1:-}" = "--diagnose" ]; then
    DIAGNOSE=1
    shift
fi

THREAD_ID="${1:-${CODEX_THREAD_ID:-}}"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$CODEX_WATCH_LOG"
}

describe_event() {
    python3 -c '
import json
import sys

try:
    event = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    print("invalid-json")
    raise SystemExit(0)

payload = event.get("payload") or {}
parts = ["type={}".format(event.get("type", ""))]
for key in ("type", "role", "phase"):
    value = payload.get(key)
    if value:
        parts.append("payload_{}={}".format(key, value))
print(" ".join(parts))
'
}

detect_sample_event() {
    printf '%s\n' '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"diagnostic sample"}]}}' |
        python3 "${REPO_DIR}/codex_session_hook.py" 2>/dev/null
}

if [ -z "$THREAD_ID" ]; then
    log "CODEX_THREAD_ID is not set. Run this inside Codex CLI or pass a thread id."
    if [ "$DIAGNOSE" -eq 1 ]; then
        echo "CODEX_THREAD_ID is not set. Run this inside Codex CLI or pass a thread id."
        echo "Log: ${CODEX_WATCH_LOG}"
    fi
    exit 2
fi

SESSION_FILE=$(rg -l "\"id\":\"${THREAD_ID}\"" "$HOME/.codex/sessions" -g '*.jsonl' 2>/dev/null | head -1)

if [ "$DIAGNOSE" -eq 1 ]; then
    echo "Codex watcher diagnose"
    echo "Thread: ${THREAD_ID}"
    echo "Sessions root: ${HOME}/.codex/sessions"
    echo "Session file: ${SESSION_FILE:-not found}"
    echo "Project dir: ${PROJECT_DIR}"
    echo "Hook: ${HOOK}"
    echo "Log: ${CODEX_WATCH_LOG}"
    if [ "$(detect_sample_event)" = "diagnostic sample" ]; then
        echo "Sample event detection: ok"
    else
        echo "Sample event detection: failed"
        exit 4
    fi
    [ -n "$SESSION_FILE" ] || exit 3
    exit 0
fi

if [ -z "$SESSION_FILE" ]; then
    log "no session file found for thread ${THREAD_ID}"
    exit 3
fi

log "watching ${SESSION_FILE} for thread ${THREAD_ID}"
tail -n 0 -F "$SESSION_FILE" | while IFS= read -r line; do
    summary=$(printf '%s\n' "$line" | describe_event)
    log "event ${summary}"
    AGENT=$(printf '%s\n' "$line" | python3 "${REPO_DIR}/codex_session_hook.py" --agent-type 2>/dev/null || true)
    printf '%s\n' "$line" | PROJECT_DIR="$PROJECT_DIR" CODEX_THREAD_ID="$THREAD_ID" AGENT_TYPE="$AGENT" bash "$HOOK"
done
