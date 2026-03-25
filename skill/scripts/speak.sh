#!/usr/bin/env bash
#
# speak.sh — synthesize text and play it via Afterwords
#
# Usage: speak.sh "text to speak" [voice]
#
set -euo pipefail

TEXT="${1:?Usage: speak.sh \"text\" [voice]}"
VOICE="${2:-galadriel}"
PORT=7860
OUT="/tmp/afterwords-output-$$.wav"

# URL-encode the text
ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$TEXT")

# Check server
if ! curl -s --max-time 2 "localhost:$PORT/health" >/dev/null 2>&1; then
    echo "Error: Afterwords server not responding on port $PORT" >&2
    echo "Start it with: afterwords start" >&2
    exit 1
fi

# Synthesize
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$OUT" "localhost:$PORT/synthesize?text=$ENCODED&voice=$VOICE")

if [ "$HTTP_CODE" != "200" ]; then
    echo "Synthesis failed (HTTP $HTTP_CODE):" >&2
    cat "$OUT" >&2
    rm -f "$OUT"
    exit 1
fi

# Play
afplay "$OUT"
rm -f "$OUT"
