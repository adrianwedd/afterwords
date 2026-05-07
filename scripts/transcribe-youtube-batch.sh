#!/usr/bin/env bash
# Batch-transcribe YouTube videos using parakeet.
# Downloads audio with yt-dlp, transcribes with transcribe.py --backend parakeet,
# saves word-level JSON to transcripts/youtube/<video_id>.json.
#
# Usage:
#   ./scripts/transcribe-youtube-batch.sh [VIDEO_ID ...]
#   # Or pipe a file of IDs (one per line):
#   cat video-ids.txt | xargs ./scripts/transcribe-youtube-batch.sh
#
# Skips IDs that already have a transcript.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/python3"
TRANSCRIBE="$REPO_DIR/scripts/transcribe.py"
OUT_DIR="$REPO_DIR/transcripts/youtube"
TMPDIR_BASE="$(mktemp -d /tmp/yt-transcribe-XXXXXX)"

mkdir -p "$OUT_DIR"

cleanup() { rm -rf "$TMPDIR_BASE"; }
trap cleanup EXIT

is_valid_video_id() {
  [[ "$1" =~ ^[A-Za-z0-9_-]{11}$ ]]
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift

  "$@" &
  local cmd_pid=$!
  local elapsed=0

  while kill -0 "$cmd_pid" 2>/dev/null; do
    if (( elapsed >= timeout_seconds )); then
      kill "$cmd_pid" 2>/dev/null || true
      sleep 1
      kill -9 "$cmd_pid" 2>/dev/null || true
      wait "$cmd_pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
    ((elapsed++)) || true
  done

  wait "$cmd_pid"
}

fsync_file() {
  "$VENV" - "$1" <<'PY'
import os
import sys

path = sys.argv[1]
fd = os.open(path, os.O_RDONLY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
}

process_video() {
  local VID="$1"

  if ! is_valid_video_id "$VID"; then
    echo "  [FAIL] $VID — invalid YouTube video ID"
    return 1
  fi

  local OUT_FILE="$OUT_DIR/$VID.json"
  local TMP_OUT="$OUT_DIR/.$VID.json.tmp"
  local WORK_DIR="$TMPDIR_BASE/$VID"

  if [[ -f "$OUT_FILE" ]]; then
    echo "  [skip] $VID — already transcribed"
    return 2
  fi

  mkdir -p "$WORK_DIR"
  rm -f "$TMP_OUT"

  # Download audio
  if ! run_with_timeout 300 yt-dlp \
      --quiet \
      -x --audio-format wav --audio-quality 0 \
      --no-playlist \
      -o "$WORK_DIR/audio.%(ext)s" \
      "https://www.youtube.com/watch?v=$VID" 2>&1; then
    echo "  [FAIL] $VID — yt-dlp download failed"
    return 1
  fi

  local AUDIO_FILE
  AUDIO_FILE="$(ls "$WORK_DIR"/audio.wav 2>/dev/null || ls "$WORK_DIR"/audio.*.wav 2>/dev/null | head -1 || true)"
  if [[ -z "$AUDIO_FILE" ]]; then
    echo "  [FAIL] $VID — no wav produced"
    return 1
  fi

  # Normalize to 16kHz mono
  local NORM_FILE="$WORK_DIR/norm.wav"
  if ! run_with_timeout 300 ffmpeg -y -i "$AUDIO_FILE" -ar 16000 -ac 1 "$NORM_FILE" -loglevel error 2>&1; then
    echo "  [FAIL] $VID — ffmpeg normalize failed"
    return 1
  fi

  # Transcribe
  if run_with_timeout 300 "$VENV" "$TRANSCRIBE" "$NORM_FILE" \
      --backend parakeet \
      --out "$TMP_OUT" \
      --stats 2>&1; then
    if [[ ! -s "$TMP_OUT" ]]; then
      echo "  [FAIL] $VID — transcription produced no output"
      rm -f "$TMP_OUT"
      return 1
    fi
    fsync_file "$TMP_OUT"
    mv -f "$TMP_OUT" "$OUT_FILE"
    echo "  [ok]   $VID → $OUT_FILE"
  else
    echo "  [FAIL] $VID — transcription failed"
    rm -f "$TMP_OUT"
    return 1
  fi

  # Clean up this video's tmp files immediately to save disk
  rm -rf "$WORK_DIR"
  return 0
}

VIDEO_IDS=("$@")

if [[ ${#VIDEO_IDS[@]} -eq 0 ]]; then
  echo "Usage: $0 VIDEO_ID [VIDEO_ID ...]" >&2
  exit 1
fi

DONE=0; SKIP=0; FAIL=0; TOTAL=${#VIDEO_IDS[@]}

for VID in "${VIDEO_IDS[@]}"; do
  echo ""
  echo "  [$((DONE + FAIL + SKIP + 1))/$TOTAL] $VID"

  if process_video "$VID"; then
    ((DONE++)) || true
  else
    status=$?
    if [[ $status -eq 2 ]]; then
      ((SKIP++)) || true
    else
      ((FAIL++)) || true
    fi
  fi
done

echo ""
echo "Done: $DONE  Skipped: $SKIP  Failed: $FAIL  Total: $TOTAL"

if (( FAIL > 0 )); then
  exit 1
fi
