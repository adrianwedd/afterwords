#!/usr/bin/env python3
"""Mechanical speech acceptance; listening is still required for fidelity."""
import sys
import numpy as np
import soundfile as sf


def validate(path):
    audio, rate = sf.read(path)
    if rate <= 0 or audio.size == 0 or not np.isfinite(audio).all():
        raise ValueError('empty or invalid audio')
    if len(audio) / rate < 0.1 or np.max(np.abs(audio)) <= 0.0001:
        raise ValueError('audio is too short or silent')
    print(f'Valid audio: {len(audio) / rate:.2f}s at {rate} Hz; listen to confirm complete speech.')


if __name__ == '__main__':
    validate(sys.argv[1])
