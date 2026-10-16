#!/usr/bin/env python3
"""Generate original, unconditioned reference candidates; never overwrite attempts.

No person/celebrity prompt or reference is used. This creates candidates and
provenance receipts, not automatic listening or transcript acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from expressive.contracts import MODEL, REVISION, SOURCE_REVISION

TEXT = ('The committee has reviewed the situation. Apparently, the situation has also reviewed the committee. '
        'We are taking a short break while everyone considers what that means. Please keep your questions, '
        'your coffee, and your remaining optimism close at hand.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',action='append',required=True,help='candidate-name:seed; repeat for a batch')
    p.add_argument('--out',type=Path,default=Path('qa/expressive-voice/original-reference-candidates'))
    args=p.parse_args()
    candidates=[]
    import re
    for value in args.name:
        name,seed=value.rsplit(':',1)
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',name):
            p.error('candidate names must be lowercase slugs')
        seed=int(seed)
        if not 0<=seed<2**32:
            p.error('seed out of range')
        if (args.out/(name+'.wav')).exists() or (args.out/(name+'.json')).exists():
            p.error('candidate already exists; preserve previous attempts')
        if any(n==name for n,_ in candidates):
            p.error('duplicate candidate name')
        candidates.append((name,seed))
    import psutil
    if psutil.virtual_memory().available<64*1024**3:
        raise RuntimeError('insufficient memory headroom')
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from huggingface_hub import snapshot_download
    from mlx_audio.tts.utils import load_model
    mx.set_memory_limit(40*1024**3);mx.set_cache_limit(2*1024**3)
    from expressive.resources import acquire_model_lease
    acquire_model_lease()
    started=time.perf_counter()
    model=load_model(snapshot_download(MODEL,revision=REVISION,local_files_only=True))
    load=time.perf_counter()-started
    original=model._frames
    def checked(*a,**kw):
        n=0
        for frame in original(*a,**kw):
            n+=1
            if time.perf_counter()-generation_start>180:
                raise TimeoutError('reference generation exceeded cooperative deadline')
            yield frame
        if n>=800:
            raise RuntimeError('frame limit reached without verified EOS')
    model._frames=checked
    args.out.mkdir(parents=True,exist_ok=True)
    for name,seed in candidates:
        receipt=dict(name=name,seed=seed,model=MODEL,model_revision=REVISION,
                     implementation_revision=SOURCE_REVISION,reference_conditioning=None,
                     intended_text=TEXT,text_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
                     provenance='original unconditioned synthetic candidate; no person reference or identity prompt',
                     acoustic_acceptance='unverified',transcript_acceptance='unverified',load_seconds=load,status='incomplete')
        mx.random.seed(seed);mx.reset_peak_memory()
        generation_start=time.perf_counter()
        try:
            chunks=[];first=None
            for result in model.generate(text=TEXT,stream=True,first_chunk_frames=4,max_tokens=800,
                                          temperature=.7,top_p=.7,top_k=30):
                chunk=np.asarray(result.audio,dtype=np.float32)
                if not np.isfinite(chunk).all():raise RuntimeError('nonfinite audio')
                if chunk.size:
                    if first is None:first=time.perf_counter()-generation_start
                    chunks.append(chunk)
            if not chunks:raise RuntimeError('no audio')
            audio=np.concatenate(chunks);duration=len(audio)/model.sample_rate
            if not 1<=duration<=30:raise RuntimeError('reference duration outside 1–30 seconds')
            path=args.out/(name+'.wav');sf.write(path,audio,model.sample_rate,subtype='PCM_16')
            elapsed=time.perf_counter()-generation_start
            receipt.update(status='generated_not_listening_verified',sample_rate=model.sample_rate,
                samples=len(audio),duration_seconds=duration,generation_seconds=elapsed,
                ttfa_seconds=first,rtf=elapsed/duration,peak_metal_bytes=mx.get_peak_memory(),
                audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            print(name,receipt['status'],flush=True)
        except BaseException as exc:
            receipt['error']=f'{type(exc).__name__}: {exc}'
            raise
        finally:
            (args.out/(name+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':main()
