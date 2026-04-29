#!/usr/bin/env bash
#
# Normalize loudness of all docs/audio/*.mp3 to target -18 LUFS, -1.5 dBTP.
# Two-pass ffmpeg loudnorm for accuracy. Operates in-place via temp file swap.
#
# Usage:
#   bash scripts/loudnorm-demo-audio.sh                 # process all
#   bash scripts/loudnorm-demo-audio.sh docs/audio/picard.mp3   # one file
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_I="-18"
TARGET_TP="-1.5"
TARGET_LRA="11"

normalize() {
    local src="$1"
    local tmp="${src}.tmp.mp3"

    # Pass 1: measure
    local measure
    measure=$(ffmpeg -i "$src" -af \
        "loudnorm=I=${TARGET_I}:TP=${TARGET_TP}:LRA=${TARGET_LRA}:print_format=json" \
        -f null - 2>&1 | sed -n '/^{$/,/^}$/p')

    [ -z "$measure" ] && { echo "✗ $src — could not measure"; return 1; }

    local input_i input_tp input_lra input_thresh target_offset
    input_i=$(echo "$measure" | python3 -c "import sys,json; print(json.load(sys.stdin)['input_i'])")
    input_tp=$(echo "$measure" | python3 -c "import sys,json; print(json.load(sys.stdin)['input_tp'])")
    input_lra=$(echo "$measure" | python3 -c "import sys,json; print(json.load(sys.stdin)['input_lra'])")
    input_thresh=$(echo "$measure" | python3 -c "import sys,json; print(json.load(sys.stdin)['input_thresh'])")
    target_offset=$(echo "$measure" | python3 -c "import sys,json; print(json.load(sys.stdin)['target_offset'])")

    # Pass 2: apply with measured values for precision
    ffmpeg -y -loglevel error -i "$src" -af \
        "loudnorm=I=${TARGET_I}:TP=${TARGET_TP}:LRA=${TARGET_LRA}:measured_I=${input_i}:measured_TP=${input_tp}:measured_LRA=${input_lra}:measured_thresh=${input_thresh}:offset=${target_offset}:linear=true:print_format=summary" \
        -ar 44100 -c:a libmp3lame -q:a 2 "$tmp"

    mv "$tmp" "$src"
    printf "  ✓ %-25s in=%6.1f LUFS, tp=%6.2f dB → target %s LUFS\n" "$(basename "$src")" "$input_i" "$input_tp" "$TARGET_I"
}

if [ $# -gt 0 ]; then
    targets=("$@")
else
    targets=()
    for f in "$REPO_ROOT"/docs/audio/*.mp3 "$REPO_ROOT"/docs/audio/comparison/*.mp3; do
        [ -f "$f" ] && targets+=("$f")
    done
fi

echo "loudness-normalising ${#targets[@]} file(s) to ${TARGET_I} LUFS / ${TARGET_TP} dBTP..."
for f in "${targets[@]}"; do
    normalize "$f" || echo "  ✗ failed: $f"
done
