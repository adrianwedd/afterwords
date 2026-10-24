#!/usr/bin/env python3
"""Bounded local Drama 3 probe. No playback, routing changes or external sends."""
import argparse
import hashlib
import json
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', default='mlx-community/fish-audio-drama-3-4bit')
    p.add_argument('--revision', default='cc639e27aba7edb73429d3e3806f471dcd79d316')
    p.add_argument('--text', required=True)
    p.add_argument('--reference', type=Path)
    p.add_argument('--reference-text')
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--seed', type=int, default=20261016)
    p.add_argument('--max-frames', type=int, default=1200)
    p.add_argument('--timeout', type=float, default=180)
    a = p.parse_args()
    if bool(a.reference) != bool(a.reference_text):
        p.error('reference and reference-text must be supplied together')
    if a.output.exists() or a.output.with_suffix('.json').exists():
        p.error('output exists; preserve previous attempts')
    import psutil
    cap = 56 if a.model.endswith('8bit') else 88 if a.model.endswith('bf16') else 40
    if psutil.virtual_memory().available < (cap + 24) * 1024**3:
        p.error('insufficient memory headroom for this benchmark')
    import mlx.core as mx
    mx.set_memory_limit(cap * 1024**3)
    mx.set_cache_limit(2 * 1024**3)
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.utils import load_model
    from expressive.contracts import installed_model
    a.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(model=a.model, revision=a.revision, text=a.text,
                   text_sha256=hashlib.sha256(a.text.encode()).hexdigest(), seed=a.seed,
                   status='incomplete', acoustic_acceptance='unverified',
                   reference=str(a.reference) if a.reference else None)
    if a.reference:
        receipt['reference_sha256'] = hashlib.sha256(a.reference.read_bytes()).hexdigest()
        receipt['reference_text'] = a.reference_text
    start = time.perf_counter()
    try:
        from expressive.resources import acquire_model_lease
        acquire_model_lease()
        path = str(installed_model(a.model, a.revision))
        mx.random.seed(a.seed)
        model = load_model(path)
        receipt['load_seconds'] = time.perf_counter() - start
        # Upstream silently ends at the frame budget. Fail closed instead.
        original_frames = model._frames
        def checked_frames(*args, **kwargs):
            count = 0
            for frame in original_frames(*args, **kwargs):
                count += 1
                if time.perf_counter() - generation_start > a.timeout:
                    raise TimeoutError('generation deadline exceeded')
                yield frame
            if count >= a.max_frames:
                raise RuntimeError('frame budget reached without verified EOS')
        model._frames = checked_frames
        generation_start = time.perf_counter()
        chunks = []
        timings = []
        for result in model.generate(text=a.text, ref_audio=str(a.reference) if a.reference else None,
                                     ref_text=a.reference_text, stream=True, first_chunk_frames=4,
                                     max_tokens=a.max_frames, temperature=0.7, top_p=0.7, top_k=30):
            audio = np.asarray(result.audio, dtype=np.float32)
            if not np.isfinite(audio).all():
                raise RuntimeError('nonfinite audio')
            if audio.size:
                timings.append(time.perf_counter() - generation_start)
                chunks.append(audio)
        if not chunks:
            raise RuntimeError('no audio')
        audio = np.concatenate(chunks)
        elapsed = time.perf_counter() - generation_start
        sf.write(a.output, audio, model.sample_rate, subtype='PCM_16')
        receipt.update(status='generated_not_listening_verified', sample_rate=model.sample_rate,
                       samples=len(audio), duration_seconds=len(audio)/model.sample_rate,
                       generation_seconds=elapsed, ttfa_seconds=timings[0],
                       rtf=elapsed/(len(audio)/model.sample_rate), chunk_arrival_seconds=timings,
                       peak_metal_bytes=mx.get_peak_memory(),
                       audio_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest())
    except BaseException as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        receipt['wall_seconds'] = time.perf_counter() - start
        a.output.with_suffix('.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    main()
