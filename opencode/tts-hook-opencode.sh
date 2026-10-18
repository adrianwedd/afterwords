#!/usr/bin/env bash
# Publish one completed OpenCode message into the shared speech worker.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
exec "${AFTERWORDS_PYTHON:-python3}" -m watcher.queue --agent opencode \
    --session "$1" --event-id "$2" --project "${3:-}" \
    --state-dir "${AFTERWORDS_WATCH_STATE:-$HOME/Library/Application Support/Afterwords/watchers}"
