#!/usr/bin/env python3
"""
Extract a single continuous ~15-second segment from source audio for voice cloning.
No splicing — one clean window with complete sentences, single speaker, no music.
"""
import os
import sys
import argparse
import json
import math
import re
import subprocess
import numpy as np
import scipy.io.wavfile as wavfile
from scipy import signal
import noisereduce as nr

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Please install faster-whisper: pip install faster-whisper")
    sys.exit(1)

VOICE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def get_spectral_ratio(data, rate):
    """Mid/high energy ratio. < 4.0 typically indicates music."""
    if len(data) == 0:
        return 0.0
    f, Pxx = signal.welch(data, rate, nperseg=1024)
    mid_energy = np.sum(Pxx[(f >= 300) & (f <= 2000)])
    high_energy = np.sum(Pxx[(f > 2000) & (f <= 8000)])
    if high_energy == 0:
        return 0.0
    ratio = mid_energy / high_energy
    if not math.isfinite(ratio):
        return 0.0
    return ratio


def candidate_windows(segments, target_dur=15.0, min_dur=10.0, max_dur=20.0):
    """
    Enumerate continuous windows built from consecutive transcript segments,
    including every intermediate extension whose duration fits the bounds.
    Yields (score, window_start, window_end, text).
    """
    seg_list = list(segments)
    for i, start_seg in enumerate(seg_list):
        window_start = start_seg.start
        window_text_parts = [start_seg.text.strip()]
        window_end = start_seg.end

        j = i
        while True:
            duration = window_end - window_start
            if min_dur <= duration <= max_dur:
                full_text = " ".join(window_text_parts)
                word_count = len(full_text.split())
                dur_score = 1.0 - abs(duration - target_dur) / target_dur
                word_score = min(word_count / 40.0, 1.0)  # Cap at ~40 words
                yield (dur_score * 0.4 + word_score * 0.6,
                       window_start, window_end, full_text)

            j += 1
            if j >= len(seg_list):
                break
            next_seg = seg_list[j]
            if next_seg.start - window_end > 2.0:  # >2s silence = scene change
                break
            if next_seg.end - window_start > max_dur:
                break
            window_text_parts.append(next_seg.text.strip())
            window_end = next_seg.end


def write_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def is_git_tracked(repo_root, rel_path):
    try:
        res = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--error-unmatch", rel_path],
            capture_output=True,
        )
        return res.returncode == 0
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Extract a single continuous ~15s segment for voice cloning."
    )
    parser.add_argument("--wav", required=True, help="Source audio file")
    parser.add_argument("--voice", required=True, help="Target voice name")
    parser.add_argument("--target-dur", type=float, default=15.0, help="Target duration in seconds")
    parser.add_argument("--min-dur", type=float, default=10.0, help="Minimum duration")
    parser.add_argument("--max-dur", type=float, default=20.0, help="Maximum duration")
    parser.add_argument("--reject-music", action="store_true", default=True,
                        help="Reject segments with spectral mid/high ratio < 4.0")
    parser.add_argument("--no-reject-music", dest="reject_music", action="store_false")
    parser.add_argument("--force", action="store_true",
                        help="Allow overwriting a git-tracked (shipped) reference WAV")

    args = parser.parse_args()

    if not VOICE_SLUG.match(args.voice):
        print(f"Error: --voice must be a lowercase slug ([a-z0-9-]), got: {args.voice!r}")
        sys.exit(1)
    if not (0 < args.min_dur <= args.target_dur <= args.max_dur):
        print("Error: duration bounds must satisfy 0 < --min-dur <= --target-dur <= --max-dur.")
        sys.exit(1)
    if not os.path.isfile(args.wav):
        print(f"Error: input file not found: {args.wav}")
        sys.exit(1)

    repo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    ref_rel = f"voices/{args.voice}-ref.wav"
    ref_wav = os.path.join(repo_root, ref_rel)
    if os.path.exists(ref_wav) and is_git_tracked(repo_root, ref_rel) and not args.force:
        print(f"Error: {ref_rel} is git-tracked (a shipped voice). Re-run with --force to overwrite.")
        sys.exit(1)

    print(f"Loading audio: {args.wav}")
    rate, data = wavfile.read(args.wav)
    if len(data.shape) > 1:
        data = data.mean(axis=1).astype(np.float32)
    else:
        data = data.astype(np.float32)

    total_samples = len(data)
    total_dur = total_samples / rate
    print(f"Duration: {total_dur:.1f}s, Sample rate: {rate}Hz")

    print("Transcribing with faster-whisper...")
    model = WhisperModel("base.en", compute_type="int8")
    segments, _ = model.transcribe(args.wav)

    print("Finding best continuous window...")
    candidates = sorted(
        candidate_windows(segments, target_dur=args.target_dur,
                          min_dur=args.min_dur, max_dur=args.max_dur),
        key=lambda c: c[0], reverse=True,
    )

    if not candidates:
        print("ERROR: No suitable window found. Try adjusting duration bounds.")
        sys.exit(1)

    # Walk candidates best-first; take the first that passes the music check
    # so one contaminated window doesn't abort when clean ones exist.
    chosen = None
    for score, window_start, window_end, full_text in candidates:
        s_idx = int(window_start * rate)
        e_idx = min(int(window_end * rate), total_samples)
        chunk = data[s_idx:e_idx]
        ratio = get_spectral_ratio(chunk, rate)
        if args.reject_music and ratio < 4.0:
            print(f"  [REJECTED MUSIC {ratio:.1f}] {window_start:.1f}s-{window_end:.1f}s")
            continue
        chosen = (window_start, window_end, full_text, s_idx, e_idx, ratio)
        break

    if chosen is None:
        print("ERROR: Every candidate window failed the music check (spectral ratio < 4.0).")
        print("Try a different source file, or pass --no-reject-music to override.")
        sys.exit(1)

    window_start, window_end, full_text, s_idx, e_idx, ratio = chosen
    duration = window_end - window_start
    print(f"\nBest window: {window_start:.1f}s - {window_end:.1f}s ({duration:.1f}s)")
    print(f"Text: {full_text}")
    print(f"Spectral ratio (mid/high): {ratio:.1f}")

    chunk = data[s_idx:e_idx].copy()

    # Noise reduction
    print("Applying noise reduction...")
    chunk = nr.reduce_noise(y=chunk, sr=rate, prop_decrease=0.8)

    # RMS normalization
    rms = np.sqrt(np.mean(chunk ** 2))
    target_rms = 0.075
    if rms > 0:
        chunk *= (target_rms / rms)

    chunk = np.clip(chunk, -1.0, 1.0)
    chunk_16 = (chunk * 32767).astype(np.int16)

    wavfile.write(ref_wav, rate, chunk_16)
    print(f"Saved reference audio: {ref_wav}")

    # Re-transcribe the extracted segment for exact text
    print("Re-transcribing extracted segment for exact reference_text...")
    final_segments, _ = model.transcribe(ref_wav)
    exact_text = " ".join([s.text.strip() for s in final_segments])
    print(f"Exact reference_text: {exact_text}")

    # Update JSON profile
    voices_dir = os.path.join(repo_root, "voices")
    json_path = os.path.join(voices_dir, f"{args.voice}.json")
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            profile = json.load(f)

        profile["reference_text"] = exact_text
        profile["segment_start_s"] = window_start
        profile["notes"] = (
            f"Single continuous segment {window_start:.1f}s-{window_end:.1f}s "
            f"({duration:.1f}s). Spectral ratio: {ratio:.1f}. "
            f"Noisereduce, RMS norm. [extract-single-segment.py]"
        )

        write_json_atomic(json_path, profile)
        print(f"Updated {json_path}")
    else:
        print(f"Warning: {json_path} not found — JSON not updated.")

    print("\nDone!")


if __name__ == "__main__":
    main()
