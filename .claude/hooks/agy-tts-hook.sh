#!/usr/bin/env bash
# Publish Antigravity Stop speech through the durable, event-id queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${AFTERWORDS_PYTHON:-python3}"
INPUT=$(cat)
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcriptPath // empty' 2>/dev/null)
[ -n "$TRANSCRIPT" ] || exit 0
PROJECT=$(printf '%s' "$INPUT" | jq -r '.workspacePaths[0] // empty' 2>/dev/null)
EVENT=$("$PYTHON" "$RUNTIME_DIR/agy_session_hook.py" --json "$TRANSCRIPT")
[ -n "$EVENT" ] || exit 0
TEXT=$(printf '%s' "$EVENT" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("text", ""))')
EVENT_ID=$(printf '%s' "$EVENT" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("event_id", ""))')
[ -n "$TEXT" ] && [ -n "$EVENT_ID" ] || exit 0

cd "$RUNTIME_DIR"
printf '%s' "$TEXT" | PYTHONPATH="$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    AFTERWORDS_PYTHON="$PYTHON" "$PYTHON" -m watcher.queue \
    --agent agy --session "$TRANSCRIPT" --event-id "$EVENT_ID" \
    --project "$PROJECT" --state-dir "${AFTERWORDS_WATCH_STATE:-$HOME/Library/Application Support/Afterwords/watchers}"
