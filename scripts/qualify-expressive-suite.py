#!/usr/bin/env python3
"""Run the fixed expressive test suite with real reference conditioning.

Records generation evidence, never automatic acoustic acceptance. Each output
folder is one preserved attempt. An unavailable test is not a passing test.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from expressive.contracts import MODEL,REVISION,SOURCE_REVISION,directed_text,validate_options


def sha(data):return hashlib.sha256(data).hexdigest()


def compile_case(case):
    if 'turns' in case:
        text=' '.join(t['text'] for t in case['turns'])
        performance=' '.join(f"<|speaker:{t['speaker']}|> {t['text']}" for t in case['turns'])
        return text,performance,True
    return case['text'],directed_text(case['text'],validate_options({'cues':case.get('cues',[])})),False


def case_inputs(case, chunked_long=False):
    text, performance, dialogue = compile_case(case)
    if not chunked_long or case['id'] != 'long-response':
        return [performance]
    if dialogue or case.get('cues'):
        raise ValueError('chunked long-response requires plain single-speaker text')
    from chunks import chunk_text
    segments = chunk_text(text, max_chars=400)
    if ''.join(''.join(segments).split()) != ''.join(text.split()):
        raise ValueError('chunking changed non-whitespace transcript characters')
    return segments


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--references-json',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--suite',type=Path,default=ROOT/'qa/expressive-voice/cases/suite.v1.json')
    p.add_argument('--model',default=MODEL)
    p.add_argument('--revision',default=REVISION)
    p.add_argument('--case',action='append')
    p.add_argument('--chunked-long',action='store_true',
                   help='Use canonical 400-character independent calls for long-response')
    p.add_argument('--temperature',type=float,default=.7)
    p.add_argument('--top-p',type=float,default=.7)
    p.add_argument('--seed',type=int,default=20261016)
    args=p.parse_args()
    pins=json.loads((ROOT/'qa/expressive-voice/pins.json').read_text())['models']
    if pins.get(args.model)!=args.revision:p.error('model/revision pair must match recorded pins')
    options=validate_options({'temperature':args.temperature,'top_p':args.top_p,'seed':args.seed})
    cases=json.loads(args.suite.read_text())['cases']
    if args.case:
        if set(args.case)-{c['id'] for c in cases}:p.error('unknown case id')
        cases=[c for c in cases if c['id'] in args.case]
    try:
        inputs = {case['id']: case_inputs(case, args.chunked_long) for case in cases}
    except ValueError as exc:
        p.error(str(exc))
    refs=json.loads(args.references_json.read_text())['references']
    if any('turns' in c for c in cases) and len(refs)<2:p.error('dialogue requires two distinct references')
    for ref in refs:
        if sha(Path(ref['path']).read_bytes())!=ref['sha256'] or not ref['text'].strip():
            p.error('reference bytes or transcript invalid')
    if args.out.exists() and any(args.out.iterdir()):p.error('preserve previous attempts; choose an empty output folder')
    import psutil
    available=psutil.virtual_memory().available/1024**3
    caps={'mlx-community/fish-audio-drama-3-4bit':40,'mlx-community/fish-audio-drama-3-3bit':36,
          'mlx-community/fish-audio-drama-3-8bit':56,'mlx-community/fish-audio-drama-3-bf16':88}
    cap=caps.get(args.model)
    if cap is None:p.error('no memory admission budget for this model')
    if available < cap+24:p.error(f'insufficient headroom: {available:.1f} GiB available; {cap+24} required')
    from expressive.resources import acquire_model_lease
    acquire_model_lease()
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from expressive.contracts import installed_model
    from mlx_audio.tts.utils import load_model
    mx.set_memory_limit(cap*1024**3);mx.set_cache_limit(2*1024**3)
    args.out.mkdir(parents=True,exist_ok=True)
    run={'model':args.model,'revision':args.revision,'implementation_revision':SOURCE_REVISION,
         'qualifier_sha256':sha(Path(__file__).read_bytes()),
         'suite_sha256':sha(args.suite.read_bytes()),'seed':args.seed,'references':refs,
         'available_memory_before_gib':available,'memory_cap_gib':cap,'status':'loading','cases':[]}
    run['long_text_mode'] = 'canonical400' if args.chunked_long else 'native_single_call_diagnostic'
    if args.chunked_long:
        run['chunker_sha256'] = sha((ROOT/'chunks.py').read_bytes())
    run_path=args.out/'run.json'
    run_path.write_text(json.dumps(run,indent=2)+'\n')
    started=time.perf_counter()
    try:
        model=load_model(str(installed_model(args.model,args.revision)))
        run.update(load_seconds=time.perf_counter()-started,load_peak_metal_bytes=mx.get_peak_memory())
        original=model._frames
        def checked(*a,**kw):
            n=0
            for frame in original(*a,**kw):
                n+=1
                if time.perf_counter()-generation_started>300:raise TimeoutError('case deadline exceeded')
                yield frame
            if n>=1600:raise RuntimeError('frame budget exhausted without verified EOS')
        model._frames=checked
        for case in cases:
            text,performance,dialogue=compile_case(case)
            receipt={'case':case['id'],'text':text,'text_sha256':sha(text.encode()),
                     'model_input':performance,'model_input_sha256':sha(performance.encode()),
                     'controls':options,'status':'incomplete','acoustic_acceptance':'unverified',
                     'synthesis_segments':[]}
            run['cases'].append(receipt)
            run_path.write_text(json.dumps(run,indent=2)+'\n')
            mx.random.seed(args.seed);mx.reset_peak_memory()
            generation_started=time.perf_counter();arrays=[];arrivals=[];samples=0
            audio_refs=[r['path'] for r in refs[:2]] if dialogue else refs[0]['path']
            ref_texts=[f"<|speaker:{i}|> {r['text']}" for i,r in enumerate(refs[:2])] if dialogue else refs[0]['text']
            for index, segment in enumerate(inputs[case['id']], 1):
                mx.random.seed(args.seed)
                segment_started=time.perf_counter();segment_arrays=[]
                detail={'index':index,'text':segment,'text_sha256':sha(segment.encode()),
                        'status':'incomplete','start_sample':samples}
                receipt['synthesis_segments'].append(detail)
                run_path.write_text(json.dumps(run,indent=2)+'\n')
                for result in model.generate(text=segment,ref_audio=audio_refs,ref_text=ref_texts,
                        stream=True,first_chunk_frames=4,max_tokens=1600,temperature=args.temperature,
                        top_p=args.top_p,top_k=30):
                    if model.sample_rate != 44100:raise RuntimeError('unexpected model sample rate')
                    audio=np.asarray(result.audio,dtype=np.float32)
                    if audio.ndim!=1 or not np.isfinite(audio).all():raise RuntimeError('invalid audio')
                    if len(audio):
                        if not segment_arrays:detail['ttfa_seconds']=time.perf_counter()-segment_started
                        arrivals.append(time.perf_counter()-generation_started)
                        arrays.append(audio);segment_arrays.append(audio);samples+=len(audio)
                    if samples>44100*300:raise RuntimeError('case audio exceeds five minutes')
                if not segment_arrays:raise RuntimeError('empty synthesis segment')
                detail.update(status='generated_not_listening_verified',end_sample=samples,
                              generation_seconds=time.perf_counter()-segment_started)
                if len(inputs[case['id']])>1:
                    segment_path=args.out/f"{case['id']}-chunk{index:02}.wav"
                    sf.write(segment_path,np.concatenate(segment_arrays),44100,subtype='PCM_16')
                    detail.update(file=segment_path.name,audio_sha256=sha(segment_path.read_bytes()))
                run_path.write_text(json.dumps(run,indent=2)+'\n')
            if not arrays:raise RuntimeError('empty output')
            audio=np.concatenate(arrays);elapsed=time.perf_counter()-generation_started
            path=args.out/(case['id']+'.wav');sf.write(path,audio,model.sample_rate,subtype='PCM_16')
            receipt.update(status='generated_not_listening_verified',audio_sha256=sha(path.read_bytes()),
                samples=len(audio),sample_rate=model.sample_rate,duration_seconds=len(audio)/model.sample_rate,
                generation_seconds=elapsed,ttfa_seconds=arrivals[0],chunk_arrival_seconds=arrivals,
                rtf=elapsed/(len(audio)/model.sample_rate),peak_metal_bytes=mx.get_peak_memory(),
                process_rss_after_bytes=psutil.Process().memory_info().rss,
                available_memory_after_bytes=psutil.virtual_memory().available)
            print(case['id'],f"TTFA {arrivals[0]:.3f}s; RTF {receipt['rtf']:.3f}",flush=True)
            run_path.write_text(json.dumps(run,indent=2)+'\n')
        run['status']='generated_not_listening_verified'
    except BaseException as exc:
        run.update(status='incomplete',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        run['wall_seconds']=time.perf_counter()-started
        run_path.write_text(json.dumps(run,indent=2)+'\n')


if __name__=='__main__':main()
