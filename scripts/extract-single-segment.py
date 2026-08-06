#!/usr/bin/env python3
"""
Extract a single continuous ~15-second segment from source audio for voice cloning.
No splicing — one clean window with complete sentences, single speaker, no music.
"""
import os
import sys
import argparse
import json
import numpy as np
import scipy.io.wavfile as wavfile
from scipy import signal
import noisereduce as nr

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Please install faster-whisper: pip install faster-whisper")
    sys.exit(1)


def get_spectral_ratio(data, rate):
    """Mid/high energy ratio. < 4.0 typically indicates music."""
    if len(data) == 0:
        return 0.0
    f, Pxx = signal.welch(data, rate, nperseg=1024)
    mid_energy = np.sum(Pxx[(f >= 300) & (f <= 2000)])
    high_energy = np.sum(Pxx[(f > 2000) & (f <= 8000)])
    if high_energy == 0:
        return 999.0
    return mid_energy / high_energy


def find_best_window(segments, rate, total_samples, target_dur=15.0, min_dur=10.0, max_dur=20.0):
    """
    Scan all segments and find the best continuous window of ~target_dur seconds.
    Returns (start_sample, end_sample, text, start_time, spectral_ratio).
    """
    seg_list = list(segments)
    if not seg_list:
        return None

    best_score = -1
    best_window = None

    # Try each segment as a starting point
    for i, start_seg in enumerate(seg_list):
        window_start = start_seg.start
        window_text_parts = [start_seg.text.strip()]
        window_end = start_seg.end

        # Extend window with subsequent segments until we hit target duration
        for j in range(i + 1, len(seg_list)):
            next_seg = seg_list[j]
            gap = next_seg.start - window_end
            if gap > 2.0:  # Break on large gaps (>2s silence = scene change)
                break
            candidate_end = next_seg.end
            candidate_dur = candidate_end - window_start
            if candidate_dur > max_dur:
                break
            window_text_parts.append(next_seg.text.strip())
            window_end = candidate_end

        duration = window_end - window_start
        if duration < min_dur or duration > max_dur:
            continue

        # Extract audio chunk for spectral analysis
        s_idx = int(window_start * rate)
        e_idx = int(window_end * rate)
        if e_idx > total_samples:
            e_idx = total_samples
        chunk = np.zeros(e_idx - s_idx, dtype=np.float32)
        # We'll compute spectral ratio after loading data
        # For now, score on duration match and word count
        full_text = " ".join(window_text_parts)
        word_count = len(full_text.split())

        # Score: prefer ~15s, lots of words, no huge gaps
        dur_score = 1.0 - abs(duration - target_dur) / target_dur
        word_score = min(word_count / 40.0, 1.0)  # Cap at ~40 words
        score = dur_score * 0.4 + word_score * 0.6

        if score > best_score:
            best_score = score
            best_window = (window_start, window_end, full_text, s_idx, e_idx)

    return best_window


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

    args = parser.parse_args()

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
    segments, _ = model.transcribe(args.wav, word_timestamps=True)

    print("Finding best continuous window...")
    result = find_best_window(
        segments, rate, total_samples,
        target_dur=args.target_dur, min_dur=args.min_dur, max_dur=args.max_dur
    )

    if result is None:
        print("ERROR: No suitable window found. Try adjusting duration bounds.")
        sys.exit(1)

    window_start, window_end, full_text, s_idx, e_idx = result
    duration = window_end - window_start
    print(f"\nBest window: {window_start:.1f}s - {window_end:.1f}s ({duration:.1f}s)")
    print(f"Text: {full_text}")

    # Extract audio
    chunk = data[s_idx:e_idx].copy()

    # Spectral check
    ratio = get_spectral_ratio(chunk, rate)
    print(f"Spectral ratio (mid/high): {ratio:.1f}")

    if args.reject_music and ratio < 4.0:
        print(f"WARNING: Spectral ratio {ratio:.1f} < 4.0 — likely contains music!")
        print("Try a different source file or adjust --min-dur/--max-dur.")
        sys.exit(1)

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

    # Save reference WAV
    repo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    ref_wav = os.path.join(repo_root, f"voices/{args.voice}-ref.wav")
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

        with open(json_path, "w") as f:
            json.dump(profile, f, indent=2)
        print(f"Updated {json_path}")
    else:
        print(f"Warning: {json_path} not found — JSON not updated.")

    print("\nDone!")


if __name__ == "__main__":
    main()
