#!/usr/bin/env bash
#
# Generate backend-comparison MP3s for the demo site.
# Calls GET /synthesize for each (voice, backend) pair and encodes to MP3.
#
# Prerequisites:
#   - Server running on localhost:7860 with all 4 backends loaded
#   - scripts/reclone-flagship.py has been run (per-backend profiles exist)
#   - `lame` installed: brew install lame
#
# Usage:
#   bash scripts/gen-comparison-audio.sh           # skip-if-exists
#   bash scripts/gen-comparison-audio.sh --force   # overwrite existing
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPO_ROOT/docs/audio/comparison"
mkdir -p "$OUT_DIR"

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

SENTENCE="You are absolutely right. Your Claude Code session could sound like me."

VOICES=("picard" "galadriel" "attenborough")
# Parallel arrays: BACKENDS[i] -> SLUGS[i]. macOS bash 3.2 lacks associative arrays.
BACKENDS=("qwen3-0.6b" "qwen3-1.7b")
SLUGS=("qwen3-06b"    "qwen3-17b")

for voice in "${VOICES[@]}"; do
    for i in "${!BACKENDS[@]}"; do
        backend="${BACKENDS[$i]}"
        slug="${SLUGS[$i]}"
        # Default-backend profile uses the raw voice name; others use voice-slug
        if [[ "$backend" == "qwen3-0.6b" ]]; then
            voice_name="$voice"
        else
            voice_name="${voice}-${slug}"
        fi

        out_mp3="$OUT_DIR/${voice}-${slug}.mp3"
        if [[ -f "$out_mp3" ]] && [[ "$FORCE" != true ]]; then
            echo "[skip] $out_mp3"
            continue
        fi

        echo "[gen]  $voice_name -> $out_mp3"
        tmp_wav=$(mktemp -t afterwords-comparison.XXXXXX.wav)
        trap 'rm -f "$tmp_wav"' EXIT

        # URL-encode the sentence for a GET query.
        encoded=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$SENTENCE")

        if ! curl -sf "localhost:7860/synthesize?text=${encoded}&voice=${voice_name}" -o "$tmp_wav"; then
            echo "[error] failed to synth $voice_name" >&2
            rm -f "$tmp_wav"
            exit 1
        fi

        lame -V2 --quiet "$tmp_wav" "$out_mp3"
        rm -f "$tmp_wav"
    done
done

echo ""
echo "Done. MP3s in $OUT_DIR"
ls -lh "$OUT_DIR"
