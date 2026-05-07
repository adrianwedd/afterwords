#!/usr/bin/env python3
"""Compare faster-whisper vs parakeet on the same audio file.

Downloads a short YouTube clip (or uses a local file) and runs both backends,
reporting: RTF, word count, word error rate vs each other, and timestamp drift.

Usage:
    python scripts/compare-transcription.py audio.wav
    python scripts/compare-transcription.py --youtube URL [--duration 60]
    python scripts/compare-transcription.py --youtube URL --out-dir /tmp/compare/
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path

PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
WHISPER_MODEL = "large-v2"

# ANSI
GRN = "\033[0;32m"; YLW = "\033[0;33m"; RED = "\033[0;31m"
BLD = "\033[1m"; DIM = "\033[2m"; NC = "\033[0m"

def c(code: str, s: str) -> bool:
    return f"{code}{s}{NC}" if sys.stdout.isatty() else s


# ── Audio prep ─────────────────────────────────────────────────────────────────

def download_youtube(url: str, duration: int | None, out_dir: Path) -> Path:
    """Download audio from YouTube, optionally trimming to `duration` seconds."""
    out_path = out_dir / "source.wav"
    cmd = [
        "yt-dlp", "-x", "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", str(out_path.with_suffix("")),
        url,
    ]
    print(f"  Downloading: {url}", file=sys.stderr)
    subprocess.run(cmd, check=True, capture_output=True)

    # yt-dlp may add extension; find the wav
    wav = next(out_dir.glob("source*.wav"), None)
    if wav is None:
        raise FileNotFoundError("yt-dlp download produced no .wav file")

    if duration:
        trimmed = out_dir / "source_trim.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), "-t", str(duration),
             "-ar", "16000", "-ac", "1", str(trimmed)],
            check=True, capture_output=True,
        )
        wav.unlink()
        return trimmed

    # Normalise to 16kHz mono for fair comparison
    norm = out_dir / "source_norm.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav), "-ar", "16000", "-ac", "1", str(norm)],
        check=True, capture_output=True,
    )
    wav.unlink()
    return norm


def audio_duration(path: Path) -> float:
    try:
        import soundfile as sf
        return sf.info(str(path)).duration
    except Exception:
        return 0.0


# ── Transcription runners ──────────────────────────────────────────────────────

def run_whisper(audio_path: Path) -> tuple[list[dict], float]:
    from faster_whisper import WhisperModel
    t0 = time.perf_counter()
    model = WhisperModel(WHISPER_MODEL, compute_type="int8")
    segments, _ = model.transcribe(
        str(audio_path),
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
    return words, time.perf_counter() - t0


def run_parakeet(audio_path: Path) -> tuple[list[dict], float]:
    from mlx_audio.stt import load
    t0 = time.perf_counter()
    model = load(PARAKEET_MODEL)
    result = model.generate(str(audio_path), chunk_duration=60.0, overlap_duration=5.0)
    words = _merge_parakeet_tokens(result)
    return words, time.perf_counter() - t0


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


# ── Analysis ───────────────────────────────────────────────────────────────────

def word_list(words: list[dict]) -> list[str]:
    return [w["word"].lower().strip(".,!?;:\"'") for w in words if w["word"].strip()]


def similarity(a: list[str], b: list[str]) -> float:
    return SequenceMatcher(None, a, b).ratio()


def wer(ref: list[str], hyp: list[str]) -> float:
    """Levenshtein WER — treating one transcript as reference vs other as hypothesis."""
    r, h = ref, hyp
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1): d[i][0] = i
    for j in range(len(h) + 1): d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = d[i-1][j-1] if r[i-1] == h[j-1] else 1 + min(d[i-1][j], d[i][j-1], d[i-1][j-1])
    return d[len(r)][len(h)] / max(1, len(r))


def timestamp_drift(ww: list[dict], pw: list[dict]) -> float:
    """Mean absolute timestamp drift for words present in both (aligned by text)."""
    pw_map: dict[str, list[float]] = {}
    for w in pw:
        pw_map.setdefault(w["word"].lower(), []).append(w["start"])

    drifts = []
    for w in ww:
        key = w["word"].lower()
        if key in pw_map and pw_map[key]:
            drifts.append(abs(w["start"] - pw_map[key].pop(0)))

    return sum(drifts) / len(drifts) if drifts else 0.0


def print_side_by_side(ww: list[dict], pw: list[dict], n: int = 20) -> None:
    """Print first N words from each model side by side with timestamps."""
    print(f"\n  {'faster-whisper':40s}  {'parakeet':40s}")
    print(f"  {'-'*40}  {'-'*40}")
    for i in range(min(n, max(len(ww), len(pw)))):
        we = ww[i] if i < len(ww) else None
        pe = pw[i] if i < len(pw) else None
        wl = f"{we['word']:20s} [{we['start']:6.2f}–{we['end']:6.2f}]" if we else " " * 40
        pl = f"{pe['word']:20s} [{pe['start']:6.2f}–{pe['end']:6.2f}]" if pe else ""
        print(f"  {wl}  {pl}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("audio", nargs="?", help="Local audio file")
    group.add_argument("--youtube", "-y", metavar="URL", help="YouTube URL to download and test")
    ap.add_argument("--duration", "-d", type=int, default=120,
                    help="Seconds of audio to use when downloading (default: 120)")
    ap.add_argument("--out-dir", default=None, help="Save transcripts + audio here (default: /tmp/)")
    ap.add_argument("--skip-whisper", action="store_true", help="Only run parakeet")
    ap.add_argument("--skip-parakeet", action="store_true", help="Only run faster-whisper")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="transcribe-cmp-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n{c(BLD, 'Transcription comparison')}", file=sys.stderr)
    print(f"  Output dir: {out_dir}", file=sys.stderr)

    # ── Prepare audio ──────────────────────────────────────────────────────────
    if args.youtube:
        if not shutil.which("yt-dlp"):
            print("error: yt-dlp not found. brew install yt-dlp", file=sys.stderr)
            return 1
        if not shutil.which("ffmpeg"):
            print("error: ffmpeg not found. brew install ffmpeg", file=sys.stderr)
            return 1
        audio_path = download_youtube(args.youtube, args.duration, out_dir)
    else:
        src = Path(args.audio)
        if not src.exists():
            print(f"error: file not found: {src}", file=sys.stderr)
            return 1
        # Normalise to 16kHz mono for fair comparison
        audio_path = out_dir / "source_norm.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(audio_path)],
            check=True, capture_output=True,
        )

    dur = audio_duration(audio_path)
    print(f"  Audio: {audio_path.name}  ({dur:.1f}s)", file=sys.stderr)

    # ── Run models ─────────────────────────────────────────────────────────────
    whisper_words: list[dict] = []
    parakeet_words: list[dict] = []
    whisper_time = parakeet_time = 0.0

    if not args.skip_whisper:
        print(f"\n  Running {c(BLD, 'faster-whisper')} ({WHISPER_MODEL})...", file=sys.stderr)
        try:
            whisper_words, whisper_time = run_whisper(audio_path)
            wout = out_dir / "whisper.json"
            wout.write_text(json.dumps(whisper_words, indent=2, ensure_ascii=False) + "\n")
            print(f"  → {len(whisper_words)} words in {whisper_time:.1f}s  (RTF {whisper_time/dur:.2f}x)  saved: {wout.name}", file=sys.stderr)
        except Exception as e:
            print(f"  {c(RED, 'FAILED')}: {e}", file=sys.stderr)

    if not args.skip_parakeet:
        print(f"\n  Running {c(BLD, 'parakeet')} ({PARAKEET_MODEL.split('/')[-1]})...", file=sys.stderr)
        try:
            parakeet_words, parakeet_time = run_parakeet(audio_path)
            pout = out_dir / "parakeet.json"
            pout.write_text(json.dumps(parakeet_words, indent=2, ensure_ascii=False) + "\n")
            print(f"  → {len(parakeet_words)} words in {parakeet_time:.1f}s  (RTF {parakeet_time/dur:.2f}x)  saved: {pout.name}", file=sys.stderr)
        except Exception as e:
            print(f"  {c(RED, 'FAILED')}: {e}", file=sys.stderr)

    # ── Analysis ───────────────────────────────────────────────────────────────
    if whisper_words and parakeet_words:
        wl = word_list(whisper_words)
        pl = word_list(parakeet_words)
        sim = similarity(wl, pl)
        # WER in both directions (no ground truth, so each is reference for the other)
        wer_wp = wer(wl, pl)
        drift = timestamp_drift(whisper_words, parakeet_words)
        speedup = whisper_time / parakeet_time if parakeet_time else 0

        print(f"\n{c(BLD, '─── Results ───────────────────────────────')}")
        print(f"  {'Metric':<30} {'faster-whisper':>15} {'parakeet':>15}")
        print(f"  {'-'*60}")
        print(f"  {'Words':30} {len(whisper_words):>15} {len(parakeet_words):>15}")
        print(f"  {'Elapsed (s)':30} {whisper_time:>15.1f} {parakeet_time:>15.1f}")
        print(f"  {'Real-time factor':30} {whisper_time/dur:>14.2f}x {parakeet_time/dur:>14.2f}x")
        if parakeet_time > 0:
            print(f"  {'Parakeet speedup':30} {speedup:>14.1f}x {'':>15}")
        print(f"  {'-'*60}")
        print(f"  {'Transcript similarity':30} {sim:>14.1%} {'(shared)':>15}")
        print(f"  {'WER whisper→parakeet':30} {wer_wp:>14.1%}")
        print(f"  {'Mean timestamp drift':30} {drift:>14.3f}s")

        print_side_by_side(whisper_words, parakeet_words, n=25)

        # Verdict
        print(f"\n{c(BLD, '─── Verdict ────────────────────────────────')}")
        if wer_wp < 0.05:
            print(f"  {c(GRN, '✓')} Transcripts agree (WER < 5%) — both reliable")
        elif wer_wp < 0.15:
            print(f"  {c(YLW, '~')} Some divergence (WER {wer_wp:.0%}) — check side-by-side above")
        else:
            print(f"  {c(RED, '!')} High divergence (WER {wer_wp:.0%}) — one model may be struggling")

        if speedup >= 2:
            faster = "parakeet"
            print(f"  {c(GRN, '✓')} Parakeet is {speedup:.1f}x faster — prefer for production pipeline")
        elif speedup > 0 and speedup < 0.5:
            faster = "faster-whisper"
            print(f"  {c(GRN, '✓')} faster-whisper is {1/speedup:.1f}x faster on this hardware")
        else:
            print(f"  Speed comparable — either works")

        if drift > 0.5:
            print(f"  {c(YLW, '~')} Timestamp drift {drift:.2f}s — investigate before using for assembly")
        else:
            print(f"  {c(GRN, '✓')} Timestamps align within {drift:.2f}s — good for assembly")

    print(f"\n  Outputs in: {out_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
