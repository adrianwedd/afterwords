#!/usr/bin/env bash
# Queue a Cursor IDE afterAgentResponse for Afterwords TTS.
#
# Cursor 1.7+ fires afterAgentResponse when the agent completes a response,
# passing the full assistant text in the `text` field. This adapter extracts
# it, strips markdown, and appends it to the common /tmp/claude-tts-queue/
# dir that the existing tts-worker.sh drains. The worker and all shared
# helpers (strip-markdown.py, chunk-text.py) are read from ~/.claude/hooks/.
#
# Wire-up: copy this file to ~/.claude/hooks/ and configure ~/.cursor/hooks.json:
#   {
#     "version": 1,
#     "hooks": {
#       "afterAgentResponse": [
#         {
#           "command": "bash ~/.claude/hooks/cursor-tts-hook.sh",
#           "type": "command",
#           "timeout": 10,
#           "failClosed": false
#         }
#       ]
#     }
#   }
#
# Voice per project: add a .afterwords file at the repo root, e.g.:
#   default: rimmer
#   cursor: lister
#
# Run `bash setup.sh` to install automatically when Cursor is detected.
set -uo pipefail

QUEUEDIR="/tmp/claude-tts-queue"
WORKER_PID="/tmp/claude-tts-worker.pid"
WORKER="$HOME/.claude/hooks/tts-worker.sh"
STRIP_MARKDOWN="$HOME/.claude/hooks/strip-markdown.py"

INPUT=$(cat)
[ -z "$INPUT" ] && exit 0

TEXT=$(printf '%s' "$INPUT" | jq -r '.text // empty' 2>/dev/null \
    | python3 "$STRIP_MARKDOWN" 2>/dev/null)
[ -z "$TEXT" ] && exit 0

# workspace_roots[0] is the project directory; fall back to $PWD.
PROJECT_DIR=$(printf '%s' "$INPUT" | jq -r '.workspace_roots[0] // empty' 2>/dev/null)
PROJECT_DIR="${PROJECT_DIR:-$PWD}"

AGENT="cursor"

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
