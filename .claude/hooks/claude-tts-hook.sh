#!/usr/bin/env bash
# Publish Claude Stop/SubagentStop speech through the durable, event-id queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${AFTERWORDS_PYTHON:-python3}"
INPUT=$(cat)
EVENT=$(printf '%s' "$INPUT" | "$PYTHON" "$RUNTIME_DIR/claude_session_hook.py")
[ -n "$EVENT" ] || exit 0

field() { printf '%s' "$EVENT" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1], ""))' "$1"; }
SESSION=$(field session)
EVENT_ID=$(field event_id)
PROJECT=$(field project)
TEXT=$(field text)
VOICE_AGENT=$(field voice_agent)
[ -n "$TEXT" ] || exit 0

cd "$RUNTIME_DIR"
printf '%s' "$TEXT" | PYTHONPATH="$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    AFTERWORDS_PYTHON="$PYTHON" "$PYTHON" -m watcher.queue \
    --agent claude --voice-agent "$VOICE_AGENT" --session "$SESSION" \
    --event-id "$EVENT_ID" --project "$PROJECT" \
    --state-dir "${AFTERWORDS_WATCH_STATE:-$HOME/Library/Application Support/Afterwords/watchers}"
