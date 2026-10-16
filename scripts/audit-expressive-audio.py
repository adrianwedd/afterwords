#!/usr/bin/env python3
"""Local CPU Whisper + waveform audit. Does not certify acting or voice identity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from expressive.audio_audit import waveform,word_errors


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audio',type=Path,required=True)
    p.add_argument('--text-file',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--whisper-snapshot',type=Path,required=True,help='existing local faster-whisper snapshot; no downloads')
    args=p.parse_args()
    if args.out.exists():p.error('preserve previous audit receipts; output already exists')
    if not (args.whisper_snapshot/'model.bin').is_file():p.error('local Whisper weights missing')
    os.environ['HF_HUB_OFFLINE']='1'
    import soundfile as sf
    from faster_whisper import WhisperModel
    from importlib.metadata import version
    audio,rate=sf.read(args.audio,dtype='float32')
    channels=1 if audio.ndim==1 else audio.shape[1]
    if channels not in (1,2):p.error('only mono/stereo source audio supported')
    analysis_audio=audio if channels==1 else audio.mean(axis=1)
    expected=args.text_file.read_text()
    receipt={'schema':'afterwords-acoustic-measurement/1','audio_sha256':hashlib.sha256(args.audio.read_bytes()).hexdigest(),
             'text_sha256':hashlib.sha256(expected.encode()).hexdigest(),'expected_text':expected,
             'waveform':waveform(analysis_audio,rate),'source_channels':channels,
             'analysis_conversion':'stereo-mean-to-mono' if channels==2 else 'none','acoustic_acceptance':'unverified',
             'limitations':['ASR disagreements require audio review; they are not proven synthesis errors.',
                            'No judgement of character identity, emotional intent, pronunciation or comic timing is implied.'],
             'transcriber':{'snapshot':str(args.whisper_snapshot.resolve()),'device':'cpu','compute_type':'int8','cpu_threads':4,'faster_whisper_version':version('faster-whisper'),
                            'ctranslate2_version':version('ctranslate2'),'weights_sha256':file_hash(args.whisper_snapshot/'model.bin')}}
    start=time.perf_counter()
    try:
        model=WhisperModel(str(args.whisper_snapshot),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
        segments,info=model.transcribe(str(args.audio),language='en',beam_size=5,word_timestamps=True,
                                      vad_filter=False,condition_on_previous_text=False)
        rows=[]
        for s in segments:
            rows.append({'start':s.start,'end':s.end,'text':s.text,'avg_logprob':s.avg_logprob,
                         'no_speech_probability':s.no_speech_prob,
                         'words':[{'word':w.word,'start':w.start,'end':w.end,'probability':w.probability} for w in s.words or []]})
        heard=' '.join(r['text'].strip() for r in rows)
        receipt.update(status='measured_not_listening_verified',transcript=heard,segments=rows,
                       word_comparison=word_errors(expected,heard),language=info.language)
    except BaseException as exc:
        receipt.update(status='incomplete',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        receipt['analysis_seconds']=time.perf_counter()-start
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':receipt['status'],'wer':receipt['word_comparison']['wer'],
                      'duration':receipt['waveform']['duration_seconds']},indent=2))


if __name__=='__main__':main()
