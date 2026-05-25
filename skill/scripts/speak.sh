#!/usr/bin/env bash
#
# speak.sh — synthesize text and play it via Afterwords
#
# Usage: speak.sh "text to speak" [voice]
#
# If no voice is given, resolves from .afterwords files:
#   1. Project .afterwords (hermes: or default: entry)
#   2. Global ~/.afterwords (hermes: or default: entry)
#   3. Server default voice
#
set -euo pipefail

TEXT="${1:?Usage: speak.sh \"text\" [voice]}"
VOICE="${2:-}"
PORT=7860
OUT="/tmp/afterwords-output-$$.wav"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Resolve voice from .afterwords if not specified
if [ -z "$VOICE" ]; then
    # Try project .afterwords
    AW_FILE=""
    if [ -f "./.afterwords" ]; then
        AW_FILE="./.afterwords"
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
            VOICE=$(grep -v '^[[:space:]]*$\|^[[:space:]]*#' "$AW_FILE" | head -1 | tr -d '[:space:]' 2>/dev/null)
        fi
    fi
fi

# URL-encode the text
ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$TEXT")

# Check server
if ! curl -s --max-time 2 "localhost:$PORT/health" >/dev/null 2>&1; then
    echo "Error: Afterwords server not responding on port $PORT" >&2
    echo "Start it with: afterwords start" >&2
    exit 1
fi

# Build URL
URL="localhost:$PORT/synthesize?text=$ENCODED"
if [ -n "$VOICE" ]; then
    VOICE_ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$VOICE")
    URL="${URL}&voice=${VOICE_ENCODED}"
    echo "Using voice: $VOICE"
fi

# Synthesize
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$OUT" "$URL")

if [ "$HTTP_CODE" != "200" ]; then
    echo "Synthesis failed (HTTP $HTTP_CODE):" >&2
    cat "$OUT" >&2
    rm -f "$OUT"
    exit 1
fi

# Play
afplay "$OUT"
rm -f "$OUT"
