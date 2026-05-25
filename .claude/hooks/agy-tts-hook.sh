#!/usr/bin/env bash
# Queue an Antigravity CLI (agy) assistant response for Afterwords TTS.
#
# Antigravity fires Stop with a JSON payload that contains transcriptPath and
# workspacePaths. This hook extracts the final answer from the transcript file,
# sets AGENT="agy", and appends it to the common Claude/Gemini/agy TTS queue.
#
set -uo pipefail

QUEUEDIR="/tmp/claude-tts-queue"
WORKER_PID="/tmp/claude-tts-worker.pid"
WORKER="$HOME/.claude/hooks/tts-worker.sh"

INPUT=$(cat)
[ -z "$INPUT" ] && exit 0

TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcriptPath // empty' 2>/dev/null)
[ -z "$TRANSCRIPT_PATH" ] && exit 0

PROJECT_DIR=$(printf '%s' "$INPUT" | jq -r '.workspacePaths[0] // empty' 2>/dev/null)
PROJECT_DIR="${PROJECT_DIR:-$PWD}"

# Resolve the absolute path of this script's directory to find the python helper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TEXT=$(python3 "${SCRIPT_DIR}/agy-session-hook.py" "$TRANSCRIPT_PATH" 2>/dev/null \
    | python3 "${SCRIPT_DIR}/strip-markdown.py" 2>/dev/null)
[ -z "$TEXT" ] && exit 0

AGENT="agy"

mkdir -p "$QUEUEDIR"
ITEM="${QUEUEDIR}/$(date +%s)-${RANDOM}.json"
ITEM_TMP="${ITEM}.tmp"
python3 -c "
import json, sys
print(json.dumps({'project_dir': sys.argv[1], 'agent': sys.argv[2], 'text': sys.argv[3]}))
" "$PROJECT_DIR" "$AGENT" "$TEXT" > "$ITEM_TMP" && mv "$ITEM_TMP" "$ITEM"

if [ -f "$WORKER_PID" ]; then
    EXISTING=$(cat "$WORKER_PID" 2>/dev/null)
    if [ -n "$EXISTING" ] && kill -0 "$EXISTING" 2>/dev/null; then
        exit 0
    fi
    rm -f "$WORKER_PID"
fi

nohup bash "$WORKER" >/dev/null 2>&1 &
