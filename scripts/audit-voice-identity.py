#!/usr/bin/env python3
"""Measure local speaker-embedding similarity without certifying voice identity.

CPU-only ECAPA-TDNN; explicit mono/resampling, bounded windows, exact hashes.
Similarity scores are comparison evidence, not calibrated clone-quality grades.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

MODEL = 'speechbrain/spkrec-ecapa-voxceleb'
REVISION = '0f99f2d0ebe89ac095bcc5903c4dd8f72b367286'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--reference',type=Path,action='append',required=True)
    parser.add_argument('--audio',type=Path,action='append',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('preserve prior measurements; output exists')
    if args.snapshot.name!=REVISION:parser.error('use the pinned encoder snapshot')
    for name in ['hyperparams.yaml','embedding_model.ckpt','classifier.ckpt','mean_var_norm_emb.ckpt','label_encoder.txt']:
        if not (args.snapshot/name).is_file():parser.error('speaker encoder snapshot incomplete')
    os.environ['HF_HUB_OFFLINE']='1'
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier
    from importlib.metadata import version
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    receipt={'model':MODEL,'revision':REVISION,'device':'cpu','threads':4,
             'embedding_weights_sha256':sha(args.snapshot/'embedding_model.ckpt'),
             'hyperparams_sha256':sha(args.snapshot/'hyperparams.yaml'),
             'versions':{name:version(name) for name in ['torch','torchaudio','speechbrain']},
             'acoustic_acceptance':'unverified','status':'incomplete','references':[], 'audio':[],
             'limitations':['Cosine similarity is not a calibrated identity or acting-quality verdict.',
                            'Emotion, phonetic content, recording channel and short windows affect scores.',
                            'No listening, pronunciation or expressiveness acceptance is implied.']}
    started=time.perf_counter()
    try:
        model=EncoderClassifier.from_hparams(source=str(args.snapshot),
             savedir=str(args.out.parent/('speaker-encoder-'+REVISION)),
             overrides={'pretrained_path':str(args.snapshot)},run_opts={'device':'cpu'})
        def load(path):
            samples,rate=sf.read(path,dtype='float32',always_2d=True)
            if samples.shape[1] not in (1,2) or not np.isfinite(samples).all():raise ValueError('invalid mono/stereo samples')
            if not 1<=len(samples)/rate<=300:raise ValueError('audio duration outside1–300seconds')
            tensor=torch.from_numpy(samples.mean(axis=1))
            if rate!=16000:tensor=torchaudio.functional.resample(tensor,rate,16000)
            return tensor,{'path':str(path),'sha256':sha(path),'duration_seconds':len(samples)/rate,
                           'source_sample_rate':rate,'source_channels':samples.shape[1],
                           'analysis_sample_rate':16000,'conversion':'channel mean then resample to16kHz'}
        def embed(tensor):
            with torch.inference_mode():return model.encode_batch(tensor.unsqueeze(0)).reshape(-1)
        references=[]
        for path in args.reference:
            tensor,meta=load(path)
            if len(tensor)>16000*30:raise ValueError('reference exceeds30seconds')
            references.append(embed(tensor));receipt['references'].append(meta)
        for path in args.audio:
            tensor,meta=load(path);meta['windows']=[]
            for offset in range(0,len(tensor),16000*10):
                segment=tensor[offset:offset+16000*10]
                if len(segment)<16000:
                    meta['windows'].append({'start_seconds':offset/16000,'duration_seconds':len(segment)/16000,
                                            'status':'unmeasured_under_one_second'});continue
                embedding=embed(segment)
                scores=[float(torch.nn.functional.cosine_similarity(embedding,ref,dim=0)) for ref in references]
                meta['windows'].append({'start_seconds':offset/16000,'duration_seconds':len(segment)/16000,
                                        'cosine_to_references':scores})
            receipt['audio'].append(meta)
            print(path.name,[row.get('cosine_to_references') for row in meta['windows']],flush=True)
        receipt['status']='measured_not_listening_verified'
    except BaseException as exc:
        receipt['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        receipt['analysis_seconds']=time.perf_counter()-started
        args.out.write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':main()
