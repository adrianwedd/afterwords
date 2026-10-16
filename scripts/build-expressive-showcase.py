#!/usr/bin/env python3
"""Build a private static listening page from hash-bound audio evidence.

Does not synthesize, publish, or certify acoustic quality. Use an empty output
folder per build so previous listening candidates remain reproducible.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import wave

ROOT = Path(__file__).resolve().parents[1]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build(manifest_path, out):
    manifest_path, out = Path(manifest_path), Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('preserve prior showcase builds; output must be empty')
    source = json.loads(manifest_path.read_text())
    clips = []
    ids = set()
    for item in source['clips']:
        if item['id'] in ids or type(item['part']) is not int or item['part'] not in range(1, 6):
            raise ValueError('duplicate clip id or invalid showcase part')
        ids.add(item['id'])
        audio = (manifest_path.parent / item['audio']).resolve()
        text = (manifest_path.parent / item['text']).read_text()
        raw = audio.read_bytes()
        if digest(raw) != item['audio_sha256'] or digest(text.encode()) != item['text_sha256']:
            raise ValueError(f"stale audio or text: {item['id']}")
        with wave.open(str(audio)) as wav:
            if wav.getnframes() == 0 or wav.getsampwidth() != 2 or wav.getnchannels() != 1:
                raise ValueError('showcase requires nonempty PCM16 mono WAV')
            duration = wav.getnframes() / wav.getframerate()
            rate = wav.getframerate()
        clips.append({**item, 'text': text, 'audio': f"audio/{item['audio_sha256']}.wav",
                      'duration_seconds': duration, 'sample_rate': rate,
                      '_source': audio})
    # Validate every input before creating the build, including failed-attempt evidence.
    out.mkdir(parents=True, exist_ok=True)
    (out/'audio').mkdir()
    for clip in clips:
        shutil.copyfile(clip.pop('_source'), out/clip['audio'])
    data = {'title': source.get('title', 'Expressive voices'), 'clips': clips,
            'notice': 'Private listening candidate. Playing audio does not establish acoustic acceptance.',
            'source_manifest_sha256': digest(manifest_path.read_bytes())}
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    template = (ROOT/'expressive/showcase/index.html').read_text()
    (out/'index.html').write_text(template.replace('__MANIFEST__', encoded))
    (out/'manifest.json').write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
    for name in ['showcase.js', 'showcase.css']:
        shutil.copyfile(ROOT/'expressive/showcase'/name, out/name)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.manifest, args.out)
    print(f"Built {len(result['clips'])} clips in {args.out}; listening acceptance remains separate")
