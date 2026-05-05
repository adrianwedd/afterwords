#!/usr/bin/env bash
# Queue a Codex final answer for Afterwords TTS.
#
# Per-session isolation: queue and worker-pid paths include CODEX_THREAD_ID so
# multiple parallel Codex sessions each have their own queue and worker.
#
# Queue format: one JSON file per item in $QUEUEDIR/. File creation is atomic
# on POSIX, so no locking is needed for the write side.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SESSION_ID="${CODEX_THREAD_ID:-global}"
QUEUEDIR="/tmp/codex-tts-queue-${SESSION_ID}"
WORKER_PID="/tmp/codex-tts-worker-${SESSION_ID}.pid"
WORKER="${SCRIPT_DIR}/codex-tts-worker.sh"

INPUT=$(cat)
TEXT=$(printf '%s' "$INPUT" | python3 "${REPO_DIR}/codex_session_hook.py" --strip-markdown 2>/dev/null)
[ -z "$TEXT" ] && exit 0

PROJECT_DIR="${PROJECT_DIR:-$PWD}"
AGENT="${AGENT_TYPE:-}"

mkdir -p "$QUEUEDIR"
ITEM="${QUEUEDIR}/$(date +%Y%m%d%H%M%S%3N)-${RANDOM}.json"
python3 -c "
import json, sys
print(json.dumps({'project_dir': sys.argv[1], 'agent': sys.argv[2], 'text': sys.argv[3]}))
" "$PROJECT_DIR" "$AGENT" "$TEXT" > "$ITEM"

if [ -f "$WORKER_PID" ]; then
    EXISTING=$(cat "$WORKER_PID" 2>/dev/null)
    if [ -n "$EXISTING" ] && kill -0 "$EXISTING" 2>/dev/null; then
        exit 0
    fi
    rm -f "$WORKER_PID"
fi

nohup bash "$WORKER" >/dev/null 2>&1 &
