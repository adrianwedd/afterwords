#!/usr/bin/env python3
"""Build a simple private A/B listening page from a four-performance selection."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import wave

ROOT = Path(__file__).resolve().parents[1]


def build(selection, out):
    selection, out = Path(selection), Path(out)
    if out.exists():
        raise ValueError('preserve previous listening pages')
    data = json.loads(selection.read_text())
    if len(data['performances']) != 4:
        raise ValueError('present exactly four performances')
    assets = {}
    for pair in [data['vixen'], *data['performances']]:
        for key in ('baseline', 'candidate'):
            clip = pair[key]
            if clip['text_sha256'] != hashlib.sha256(pair['text'].encode()).hexdigest():
                raise ValueError('A/B text mismatch')
            path = Path(clip['audio'])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != clip['audio_sha256']:
                raise ValueError('stale recording')
            with wave.open(str(path)) as wav:
                if wav.getsampwidth() != 2 or wav.getnchannels() != 1 or not wav.getnframes():
                    raise ValueError('invalid listening WAV')
                clip['duration_seconds'] = wav.getnframes()/wav.getframerate()
            assets[digest] = path
            clip['audio'] = f'audio/{digest}.wav'
    out.mkdir(parents=True)
    (out/'audio').mkdir()
    for digest, path in assets.items():
        shutil.copyfile(path, out/'audio'/f'{digest}.wav')
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    (out/'index.html').write_text((ROOT/'expressive/showcase/casting.html').read_text().replace('__MANIFEST__', encoded))
    for name in ('casting.js', 'acceptance.css'):
        shutil.copyfile(ROOT/'expressive/showcase'/name, out/name)
    (out/'manifest.json').write_text(json.dumps(data, indent=2)+'\n')
    return data


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selection', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    build(a.selection, a.out)
