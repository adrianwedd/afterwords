#!/usr/bin/env bash
# Watch the current Codex session JSONL and enqueue final answers for TTS.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="${SCRIPT_DIR}/codex-tts-hook.sh"
THREAD_ID="${1:-${CODEX_THREAD_ID:-}}"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"

if [ -z "$THREAD_ID" ]; then
    echo "CODEX_THREAD_ID is not set. Run this inside Codex CLI or pass a thread id." >&2
    exit 1
fi

SESSION_FILE=$(rg -l "\"id\":\"${THREAD_ID}\"" "$HOME/.codex/sessions" -g '*.jsonl' 2>/dev/null | head -1)
if [ -z "$SESSION_FILE" ]; then
    echo "Could not find Codex session file for thread ${THREAD_ID}." >&2
    exit 1
fi

echo "Watching ${SESSION_FILE}" >&2
tail -n 0 -F "$SESSION_FILE" | while IFS= read -r line; do
    printf '%s\n' "$line" | PROJECT_DIR="$PROJECT_DIR" bash "$HOOK"
done
