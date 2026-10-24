#!/usr/bin/env python3
"""Local audio-model observations, explicitly separate from human listening.

The pinned Qwen2-Audio implementation truncates individual inputs at 30 seconds.
This tool covers the whole source in explicit nonoverlapping 20-second segments.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MODEL='mlx-community/Qwen2-Audio-7B-Instruct-4bit'
REVISION='c65570002626f41b4dc08b7b54f42f99f3e82e7f'
PROMPT=('Describe the audible vocal delivery in this audio: pace, pitch variation, pauses, '
        'emotional tone, non-speech vocal sounds, and any audible unnatural artifacts. '
        'Base observations on the sound, not on the subject of the words. Do not infer a real '
        'person identity. Distinguish clear observations from uncertainty. Be concise.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('preserve previous assessments; output exists')
    import psutil
    if psutil.virtual_memory().available<40*1024**3:parser.error('insufficient memory headroom')
    from expressive.resources import acquire_model_lease
    acquire_model_lease()
    os.environ['HF_HUB_OFFLINE']='1'
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import mlx.core as mx
    from mlx_audio.stt.utils import load_model
    from expressive.contracts import SOURCE_REVISION, installed_model
    mx.set_memory_limit(16*1024**3);mx.set_cache_limit(1024**3)
    source,rate=sf.read(args.audio,dtype='float32',always_2d=True)
    if source.shape[1] not in (1,2) or not np.isfinite(source).all():parser.error('invalid audio')
    if not 1<=len(source)/rate<=300:parser.error('audio duration must be1–300seconds')
    receipt={'model':MODEL,'revision':REVISION,'implementation_revision':SOURCE_REVISION,
             'audio_sha256':hashlib.sha256(args.audio.read_bytes()).hexdigest(),
             'source_duration_seconds':len(source)/rate,'source_sample_rate':rate,
             'source_channels':source.shape[1],'prompt':PROMPT,'temperature':0,'max_tokens':192,
             'status':'incomplete','segments':[],'human_listening':'not performed',
             'observer_qualification':'failed_all_zero_silence_control; judgments unsuitable for acceptance',
             'acoustic_acceptance':'unverified','limitations':[
                 'This pinned model/prompt reported speech and artifacts in all-zero PCM; delivery claims are untrusted.',
                 'Automated audio-model observations can be wrong or influenced by lexical content.',
                 'Segment boundaries limit assessment of timing across sentences and the whole performance.',
                 'This is not human listening acceptance or a calibrated quality score.']}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    def record():args.out.write_text(json.dumps(receipt,indent=2)+'\n')
    record();started=time.perf_counter()
    try:
        model=load_model(str(installed_model(MODEL,REVISION)))
        receipt['load_seconds']=time.perf_counter()-started
        for start in range(0,len(source),20*rate):
            piece=source[start:start+20*rate].mean(axis=1)
            divisor=math.gcd(rate,16000)
            audio=resample_poly(piece,16000//divisor,rate//divisor).astype(np.float32)
            row={'start_seconds':start/rate,'duration_seconds':len(piece)/rate,
                 'analysis_sample_rate':16000,'analysis_samples':len(audio),
                 'analysis_f32_sha256':hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest(),
                 'status':'incomplete'}
            receipt['segments'].append(row);record()
            mx.random.seed(20261016);mx.reset_peak_memory();tick=time.perf_counter()
            result=model.generate(audio,prompt=PROMPT,max_tokens=192,temperature=0,verbose=False)
            row.update(observation=result.text,analysis_seconds=time.perf_counter()-tick,
                       peak_metal_bytes=mx.get_peak_memory(),status='automated_observation')
            tokens=getattr(result,'generation_tokens',None)
            row['generation_tokens']=tokens
            if tokens is not None and tokens>=192:row['status']='possibly_truncated_observation'
            record();print(json.dumps(row),flush=True)
        receipt['status']='automated_observations_not_listening_acceptance'
    except BaseException as exc:
        receipt['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        receipt['wall_seconds']=time.perf_counter()-started;record()


if __name__=='__main__':main()
