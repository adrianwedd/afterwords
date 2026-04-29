#!/bin/bash
# Afterwords TTS wrapper for Hermes
# Direct HTTP call to local Afterwords server

set -e

TEXT="${1:-Hello from Hermes}"
VOICE="${2:-}"  # Optional: specific voice name
AFTERWORDS_URL="http://127.0.0.1:7860"

# Check if Afterwords server is running
if ! curl -s --max-time 2 "${AFTERWORDS_URL}/health" >/dev/null 2>&1; then
    echo "⚠️  Afterwords server not running at ${AFTERWORDS_URL}" >&2
    echo "Start with: cd ~/repos/afterwords && python server.py" >&2
    exit 1
fi

# URL encode the text
ENCODED=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$TEXT" 2>/dev/null || echo "$TEXT")

# Build URL with optional voice
URL="${AFTERWORDS_URL}/synthesize?text=${ENCODED}"
if [ -n "$VOICE" ]; then
    URL="${URL}&voice=${VOICE}"
fi

# Fetch and play
WAVFILE="/tmp/hermes-afterwords-$$.wav"
if curl -s --max-time 90 "$URL" -o "$WAVFILE" 2>/dev/null; then
    FILESIZE=$(stat -f%z "$WAVFILE" 2>/dev/null || echo 0)
    if [ "$FILESIZE" -gt 1000 ]; then
        # Trim silence like the original hook does
        TRIMMED="/tmp/hermes-afterwords-trimmed-$$.wav"
        if ffmpeg -y -ss 0.1 -i "$WAVFILE" -c copy "$TRIMMED" 2>/dev/null; then
            mv "$TRIMMED" "$WAVFILE"
        fi
        rm -f "$TRIMMED"

        # Play audio (afplay is macOS default)
        afplay "$WAVFILE" 2>/dev/null || echo "Audio saved to $WAVFILE (could not play)"
        rm -f "$WAVFILE"
        exit 0
    fi
fi

rm -f "$WAVFILE"
echo "⚠️  TTS generation failed" >&2
exit 1
