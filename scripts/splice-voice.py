#!/usr/bin/env python3
import os
import sys
import argparse
import json
import numpy as np
import scipy.io.wavfile as wavfile
from scipy import signal
from scipy.signal.windows import hann
import noisereduce as nr
import re

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Please install faster-whisper: pip install faster-whisper")
    sys.exit(1)

def apply_fade(chunk, rate, fade_ms=30):
    fade_len = int(rate * fade_ms / 1000)
    if len(chunk) < fade_len * 2:
        return chunk
    window = hann(fade_len * 2)
    fade_in = window[:fade_len]
    fade_out = window[fade_len:]
    chunk[:fade_len] = chunk[:fade_len] * fade_in
    chunk[-fade_len:] = chunk[-fade_len:] * fade_out
    return chunk

def get_spectral_ratio(data, rate):
    if len(data) == 0:
        return 0.0
    f, Pxx = signal.welch(data, rate, nperseg=1024)
    mid_energy = np.sum(Pxx[(f >= 300) & (f <= 2000)])
    high_energy = np.sum(Pxx[(f > 2000) & (f <= 8000)])
    if high_energy == 0:
        return 999.0
    return mid_energy / high_energy

def main():
    parser = argparse.ArgumentParser(description="Splice difficult voices automatically.")
    parser.add_argument("--wav", required=True, help="Input RAW audio file")
    parser.add_argument("--voice", required=True, help="Target voice name (e.g. robocop)")
    parser.add_argument("--match", default="", help="If provided, only include transcript segments containing this substring (case-insensitive).")
    parser.add_argument("--reject-music", action="store_true", help="Reject segments with spectral mid/high ratio < 4.0")
    
    args = parser.parse_args()
    
    print("Transcribing with faster-whisper...")
    model = WhisperModel("base.en", compute_type="int8")
    segments_gen, _ = model.transcribe(args.wav)
    
    rate, data = wavfile.read(args.wav)
    if len(data.shape) > 1:
        data = data.mean(axis=1).astype(np.float32)
    else:
        data = data.astype(np.float32)
        
    spliced_chunks = []
    full_text = []
    first_start = None
    
    gap_len = int(rate * 150 / 1000)
    gap = np.zeros(gap_len, dtype=np.float32)
    
    print("Analyzing segments...")
    for seg in segments_gen:
        text = seg.text.strip()
        
        if args.match and not re.search(args.match, text, re.IGNORECASE):
            continue
            
        pad_start = 0.100
        pad_end = 0.250
        s_idx = int(max(0, seg.start - pad_start) * rate)
        e_idx = int(min(len(data)/rate, seg.end + pad_end) * rate)
        chunk = data[s_idx:e_idx]
        
        if args.reject_music:
            ratio = get_spectral_ratio(chunk, rate)
            if ratio < 4.0:
                print(f"  [REJECTED MUSIC {ratio:.1f}] {text}")
                continue
                
        print(f"  [KEPT] {text}")
        if first_start is None:
            first_start = seg.start
        
        # Noisereduce per chunk
        chunk = nr.reduce_noise(y=chunk, sr=rate, prop_decrease=0.8)
        chunk = apply_fade(chunk, rate, 30)
        
        spliced_chunks.append(chunk)
        full_text.append(text)
        
    if not spliced_chunks:
        print("Error: No segments matched the criteria.")
        sys.exit(1)
        
    final_audio = []
    for i, chunk in enumerate(spliced_chunks):
        final_audio.append(chunk)
        if i < len(spliced_chunks) - 1:
            final_audio.append(gap)
            
    final_audio = np.concatenate(final_audio)
    
    # RMS normalization
    rms = np.sqrt(np.mean(final_audio**2))
    target_rms = 0.075
    if rms > 0:
        final_audio *= (target_rms / rms)
        
    final_audio = np.clip(final_audio, -1.0, 1.0)
    final_audio_16 = (final_audio * 32767).astype(np.int16)
    
    repo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    ref_wav = os.path.join(repo_root, f"voices/{args.voice}-ref.wav")
    wavfile.write(ref_wav, rate, final_audio_16)
    print(f"\nSaved reference audio to {ref_wav}")
    
    # Re-transcribe the final spliced audio to get the exact text match
    print("Re-transcribing final spliced audio for exact reference_text match...")
    final_segments, _ = model.transcribe(ref_wav)
    exact_text = " ".join([s.text.strip() for s in final_segments])
    print(f"Final exact reference_text: {exact_text}")
    
    # Update JSONs
    updated = False
    voices_dir = os.path.join(repo_root, "voices")
    for fname in os.listdir(voices_dir):
        if (fname == f"{args.voice}.json" or fname.startswith(f"{args.voice}-")) and fname.endswith(".json"):
            path = os.path.join(voices_dir, fname)
            with open(path, "r") as f:
                profile = json.load(f)
            
            profile["reference_text"] = exact_text
            profile["segment_start_s"] = first_start
            profile["notes"] = profile.get("notes", "") + " [Auto-spliced with splice-voice.py]"
            
            with open(path, "w") as f:
                json.dump(profile, f, indent=2)
            updated = True
            print(f"Updated {path}")
            
    if not updated:
        print(f"Warning: No JSON profiles found for {args.voice}. Ensure you created the voice first.")

if __name__ == "__main__":
    main()
