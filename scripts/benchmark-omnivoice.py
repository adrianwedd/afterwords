#!/usr/bin/env python3
"""Pinned, reference-conditioned OmniVoice probe with a hard process deadline.

No routing changes, playback, implicit downloads, retries or listening verdict.
The implementation emits a complete waveform, not native streaming chunks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL = 'mlx-community/OmniVoice'
REVISION = 'defe4bdce0decb321d17e96a4774417be08022ea'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text-file', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--reference-text-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=int, choices=(32, 64), default=64)
    parser.add_argument('--direction', default='None')
    parser.add_argument('--seed', type=int, default=20261016)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    receipt_path = args.output.with_suffix('.json')
    if args.output.exists() or receipt_path.exists():
        parser.error('preserve previous attempts; output already exists')
    if not 1 <= args.timeout <= 600:
        parser.error('timeout must be between 1 and 600 seconds')
    if not args.worker:
        command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
        try:
            result = subprocess.run(command, timeout=args.timeout,
                                    env={**os.environ, 'HF_HUB_OFFLINE': '1'})
        except subprocess.TimeoutExpired:
            # subprocess.run kills and reaps its child before raising.
            receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
            receipt.update(status='incomplete', error='hard process deadline exceeded',
                           hard_timeout_seconds=args.timeout, worker_reaped=True)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
            raise SystemExit(124)
        raise SystemExit(result.returncode)

    from expressive.contracts import SOURCE_REVISION
    text = args.text_file.read_text()
    reference_text = args.reference_text_file.read_text()
    raw_reference = args.reference.read_bytes()
    if not text.strip() or not reference_text.strip():
        parser.error('nonempty target and reference transcripts required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(status='incomplete', model=MODEL, revision=REVISION,
                   implementation_revision=SOURCE_REVISION,
                   text=text, text_sha256=sha(text.encode()),
                   reference_sha256=sha(raw_reference), reference_text=reference_text,
                   steps=args.steps, direction=args.direction, seed=args.seed,
                   acoustic_acceptance='unverified', memory_cap_gib=24,
                   limitations=['First audio is the complete waveform; no native streaming.',
                                'Automatic duration estimation may truncate speech; audit the result.'])
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
    started = time.perf_counter()
    try:
        import psutil
        receipt['available_memory_before_gib'] = psutil.virtual_memory().available / 1024**3
        if receipt['available_memory_before_gib'] < 48:
            raise RuntimeError('insufficient memory headroom')
        import mlx.core as mx
        import numpy as np
        import soundfile as sf
        from huggingface_hub import snapshot_download
        from mlx_audio.tts.utils import load_model
        from mlx.utils import tree_flatten
        from expressive.reference import normalize_reference
        from expressive.resources import acquire_model_lease
        acquire_model_lease()
        mx.set_memory_limit(24 * 1024**3)
        mx.set_cache_limit(2 * 1024**3)
        conditioning, conversion = normalize_reference(raw_reference)
        receipt.update(reference_conversion=conversion, conditioning_sha256=sha(conditioning))
        load_started = time.perf_counter()
        model = load_model(snapshot_download(MODEL, revision=REVISION, local_files_only=True))
        receipt['load_seconds'] = time.perf_counter() - load_started
        receipt['parameter_dtypes'] = sorted({str(value.dtype) for _, value in tree_flatten(model.parameters())})
        if model.audio_tokenizer is None or model.text_tokenizer is None:
            raise RuntimeError('required tokenizer missing; refuse silent fallback')
        mx.random.seed(args.seed)
        mx.reset_peak_memory()
        with tempfile.TemporaryDirectory(prefix='afterwords-omnivoice-') as temporary:
            reference = Path(temporary)/'reference.wav'
            reference.write_bytes(conditioning)
            generation_started = time.perf_counter()
            pieces, arrivals = [], []
            for result in model.generate(text=text, language='en', instruct=args.direction,
                    ref_audio=str(reference), ref_text=reference_text,
                    ref_audio_max_duration_s=30, num_steps=args.steps):
                audio = np.asarray(result.audio, dtype=np.float32)
                if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
                    raise RuntimeError('invalid generated audio')
                pieces.append(audio)
                arrivals.append(time.perf_counter()-generation_started)
            if not pieces:
                raise RuntimeError('no audio generated')
            audio = np.concatenate(pieces)
            duration = len(audio)/model.sample_rate
            if not 1 <= duration <= 300:
                raise RuntimeError('output duration outside 1–300 seconds')
            elapsed = time.perf_counter()-generation_started
            sf.write(args.output, audio, model.sample_rate, subtype='PCM_16')
            receipt.update(status='generated_not_listening_verified', samples=len(audio),
                           sample_rate=model.sample_rate, duration_seconds=duration,
                           generation_seconds=elapsed, first_complete_audio_seconds=arrivals[0],
                           rtf=elapsed/duration, peak_metal_bytes=mx.get_peak_memory(),
                           audio_sha256=sha(args.output.read_bytes()))
    except BaseException as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        receipt['wall_seconds'] = time.perf_counter()-started
        receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    main()
