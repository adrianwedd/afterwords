#!/usr/bin/env bash
# Queue a Codex final answer for Afterwords TTS.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
QUEUE="/tmp/codex-tts-queue.txt"
WORKER_PID="/tmp/codex-tts-worker.pid"
WORKER="${SCRIPT_DIR}/codex-tts-worker.sh"

INPUT=$(cat)
TEXT=$(printf '%s' "$INPUT" | python3 "${REPO_DIR}/codex_session_hook.py" --strip-markdown 2>/dev/null)
[ -z "$TEXT" ] && exit 0

PROJECT_DIR="${PROJECT_DIR:-$PWD}"
AGENT="${AGENT_TYPE:-}"

printf '%s\t%s\t%s\n' "$PROJECT_DIR" "$AGENT" "$TEXT" >> "$QUEUE"

if [ -f "$WORKER_PID" ]; then
    EXISTING=$(cat "$WORKER_PID" 2>/dev/null)
    if [ -n "$EXISTING" ] && kill -0 "$EXISTING" 2>/dev/null; then
        exit 0
    fi
    rm -f "$WORKER_PID"
fi

nohup bash "$WORKER" >/dev/null 2>&1 &
