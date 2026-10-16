#!/usr/bin/env python3
"""Measure the existing complete-WAV API against selected exact suite texts.

No playback, external sends, routing changes, retries or acoustic acceptance.
HTTP response latency is not native-model time to first generated chunk.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[1]


def sha(raw): return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', required=True)
    parser.add_argument('--case', action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--suite', type=Path, default=ROOT/'qa/expressive-voice/cases/suite.v1.json')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('invalid loopback port')
    cases = json.loads(args.suite.read_text())['cases']
    by_id = {case['id']: case for case in cases}
    if len(set(args.case)) != len(args.case) or set(args.case)-by_id.keys():
        parser.error('duplicate or unknown case')
    if any('turns' in by_id[name] for name in args.case):
        parser.error('dialogue requires independently routed voices; do not flatten it')
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('preserve prior attempts; choose an empty output folder')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f'http://127.0.0.1:{args.port}'
    with opener.open(base+'/health',timeout=5) as response: health=json.load(response)
    if not health.get('ready') or args.voice not in health.get('voices',[]):
        parser.error('server not ready or voice absent')
    args.out.mkdir(parents=True,exist_ok=True)
    run = {'voice':args.voice,'endpoint':base,'suite_sha256':sha(args.suite.read_bytes()),
           'health_before':health,'status':'incomplete','cases':[],
           'limitations':['Native TTFA and peak model memory are not observable through this full-file API.',
                          'Delivery controls are not applied: this measures the selected voice defaults.',
                          'Generation and ASR do not certify acoustic quality.']}
    path=args.out/'run.json'
    def record(): path.write_text(json.dumps(run,indent=2)+'\n')
    record()
    try:
        for name in args.case:
            text=by_id[name]['text']
            receipt={'case':name,'text_sha256':sha(text.encode()),'status':'incomplete',
                     'acoustic_acceptance':'unverified'}
            run['cases'].append(receipt);record()
            (args.out/(name+'.txt')).write_text(text)
            url=base+'/synthesize?'+urllib.parse.urlencode({'voice':args.voice,'text':text,'lang':'en'})
            start=time.perf_counter()
            with opener.open(url,timeout=180) as response:
                receipt['response_headers_seconds']=time.perf_counter()-start
                receipt['headers']=dict(response.headers)
                if response.headers.get_content_type()!='audio/wav':raise ValueError('expected WAV response')
                raw=response.read(50*1024**2+1)
            elapsed=time.perf_counter()-start
            if len(raw)>50*1024**2:raise ValueError('oversized response')
            with wave.open(io.BytesIO(raw)) as audio:
                rate=audio.getframerate();frames=audio.getnframes()
                if frames==0 or audio.getnchannels()!=1 or audio.getsampwidth()!=2:raise ValueError('invalid PCM16 mono audio')
                if len(audio.readframes(frames)) != frames*2:raise ValueError('truncated PCM payload')
            (args.out/(name+'.wav')).write_bytes(raw)
            receipt.update(status='generated_not_listening_verified',audio_sha256=sha(raw),
                           sample_rate=rate,samples=frames,duration_seconds=frames/rate,
                           full_audio_seconds=elapsed,end_to_end_rtf=elapsed/(frames/rate))
            record();print(name,json.dumps(receipt),flush=True)
        run['status']='generated_not_listening_verified'
    except BaseException as exc:
        run['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally: record()


if __name__=='__main__':main()
