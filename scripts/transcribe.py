#!/usr/bin/env python3
"""Transcribe audio to word-level timestamps.

Supports two backends:
  faster-whisper  — CTranslate2, large-v2 by default, battle-tested accuracy
  parakeet        — mlx-audio parakeet-tdt-0.6b-v2, Metal-native on Apple Silicon

Output is a JSON array of {word, start, end} objects, always in seconds.

Usage:
    python scripts/transcribe.py audio.wav
    python scripts/transcribe.py audio.wav --backend parakeet
    python scripts/transcribe.py audio.wav --backend faster-whisper --model large-v2
    python scripts/transcribe.py audio.wav --out transcript.json
    yt-dlp -x --audio-format wav -o audio.wav "URL" && python scripts/transcribe.py audio.wav
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
WHISPER_MODEL_DEFAULT = "large-v2"


# ── Output format ──────────────────────────────────────────────────────────────

def words_to_json(words: list[dict]) -> str:
    """Stable JSON output: list of {word, start, end} dicts."""
    return json.dumps(words, indent=2, ensure_ascii=False)


# ── faster-whisper backend ─────────────────────────────────────────────────────

def transcribe_whisper(audio_path: str, model_name: str) -> tuple[list[dict], float]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed: pip install faster-whisper", file=sys.stderr)
        sys.exit(1)

    t0 = time.perf_counter()
    model = WhisperModel(model_name, compute_type="int8")
    segments, _ = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )

    words = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if text:
                words.append({"word": text, "start": round(w.start, 3), "end": round(w.end, 3)})

    elapsed = time.perf_counter() - t0
    return words, elapsed


# ── parakeet backend ───────────────────────────────────────────────────────────

def transcribe_parakeet(audio_path: str) -> tuple[list[dict], float]:
    try:
        from mlx_audio.stt import load
    except ImportError:
        print("mlx-audio not installed: pip install mlx-audio", file=sys.stderr)
        sys.exit(1)

    t0 = time.perf_counter()
    model = load(PARAKEET_MODEL)
    result = model.generate(audio_path, chunk_duration=60.0, overlap_duration=5.0)

    words = _merge_parakeet_tokens(result)

    elapsed = time.perf_counter() - t0
    return words, elapsed


# ── Parakeet token merger ──────────────────────────────────────────────────────

def _merge_parakeet_tokens(result) -> list[dict]:
    """Merge sub-word tokens into words using leading-space as word-boundary marker."""
    words = []
    cur_text = ""
    cur_start = 0.0
    cur_end = 0.0

    def flush():
        nonlocal cur_text, cur_start, cur_end
        word = cur_text.strip()
        if word:
            words.append({"word": word, "start": round(cur_start, 3), "end": round(cur_end, 3)})
        cur_text = ""

    for sentence in result.sentences:
        for token in sentence.tokens:
            raw = token.text
            if not raw:
                continue
            starts_new_word = raw.startswith(" ")
            if starts_new_word and cur_text:
                flush()
                cur_text = raw.lstrip(" ")
                cur_start = token.start
            elif not cur_text:
                cur_text = raw.lstrip(" ")
                cur_start = token.start
            else:
                cur_text += raw
            cur_end = token.end

    flush()
    return words


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", help="Path to audio file (wav, mp3, m4a, ...)")
    ap.add_argument("--backend", choices=["faster-whisper", "parakeet"], default="faster-whisper",
                    help="Transcription backend (default: faster-whisper)")
    ap.add_argument("--model", default=WHISPER_MODEL_DEFAULT,
                    help=f"faster-whisper model name (default: {WHISPER_MODEL_DEFAULT})")
    ap.add_argument("--out", "-o", help="Output JSON file (default: stdout)")
    ap.add_argument("--stats", action="store_true", help="Print timing + word count to stderr")
    args = ap.parse_args()

    audio_path = str(Path(args.audio).resolve())
    if not Path(audio_path).exists():
        print(f"error: file not found: {audio_path}", file=sys.stderr)
        return 1

    if args.backend == "parakeet":
        words, elapsed = transcribe_parakeet(audio_path)
    else:
        words, elapsed = transcribe_whisper(audio_path, args.model)

    out = words_to_json(words)

    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)

    if args.stats:
        audio_dur = _audio_duration(audio_path)
        rtf = elapsed / audio_dur if audio_dur else 0
        print(
            f"backend={args.backend}  words={len(words)}  "
            f"elapsed={elapsed:.1f}s  audio={audio_dur:.1f}s  RTF={rtf:.2f}x",
            file=sys.stderr,
        )

    return 0


def _audio_duration(path: str) -> float:
    try:
        import soundfile as sf
        info = sf.info(path)
        return info.duration
    except Exception:
        return 0.0


if __name__ == "__main__":
    sys.exit(main())
