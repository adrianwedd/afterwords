"""Chunk assembly must preserve all PCM and fail on incompatible responses."""
import importlib.util
import io
from pathlib import Path
import wave

import pytest

spec = importlib.util.spec_from_file_location('http_probe', Path(__file__).resolve().parents[1]/'scripts/benchmark-afterwords-http.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def wav(frames, rate=24000):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(frames)
    return out.getvalue()


def test_assembly_preserves_order_and_every_sample():
    first, second = b'\x01\x00'*20, b'\x02\x00'*30
    result = probe.combine_wavs([wav(first), wav(second)])
    with wave.open(io.BytesIO(result)) as audio:
        assert audio.getframerate() == 24000
        assert audio.getnframes() == 50
        assert audio.readframes(50) == first+second


def test_assembly_rejects_rate_change_and_truncated_chunk():
    good = wav(b'\x01\x00'*20)
    with pytest.raises(ValueError, match='sample rates'):
        probe.combine_wavs([good, wav(b'\x02\x00'*30, 44100)])
    with pytest.raises(ValueError, match='truncated'):
        probe.combine_wavs([good, good[:-2]])
