#!/usr/bin/env python3
"""Package retained acceptance recordings for local listening; never approve them."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import wave

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(handoff, out):
    handoff, out = Path(handoff), Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('preserve existing evidence: output must be empty')
    inventory = json.loads((handoff/'inventory.json').read_text())
    cast = json.loads((handoff/'cast-reference-inventory.json').read_text())
    showcase = {c['id']: c for c in json.loads(
        (ROOT/'qa/expressive-voice/showcase-source-6/manifest.json').read_text())['clips']}
    clips, sources = [], {}

    def recording(item, path, expected):
        path = Path(path)
        if sha(path) != expected:
            raise ValueError(f'stale audio: {path}')
        with wave.open(str(path)) as wav:
            if wav.getsampwidth() != 2 or wav.getnchannels() != 1 or not wav.getnframes():
                raise ValueError(f'expected nonempty PCM16 mono: {path}')
            item['duration_seconds'] = wav.getnframes()/wav.getframerate()
            item['sample_rate'] = wav.getframerate()
        item.update(audio=f'audio/{expected}.wav', audio_sha256=expected)
        sources[expected] = path
        return item

    judgements = {
        1: 'Compare comic timing, dry understatement, natural pauses, intelligibility and voice stability on identical words.',
        2: 'Compare excitement, sadness and anger: do the emotions sound distinct and believable while preserving the same speaker and every word?',
        3: 'Does this sound recognisably like Vixen’s signature voice? Judge identity, accent, warmth, phrasing and natural delivery. This is the retained configured reply, not proof of live playback.',
        4: 'Judge recognisable character, distinction from the other models, pronunciation, pacing and exact words. Compare with the matching reference below.',
        5: 'Judge the complete request/answer transition, sustained character, conversational pacing, chunk joins, long pauses and completeness through the ending.',
    }
    for source in inventory['showcase']:
        item = dict(source)
        original = showcase[item['id']]
        if any(original[k] != item[k] for k in ('audio_sha256', 'text_sha256')):
            raise ValueError('stale showcase binding')
        for key in ('backend', 'permission', 'acoustic_acceptance'):
            item[key] = original.get(key, 'unverified')
        path = Path(item['text'])
        if sha(path) != item['text_sha256']:
            raise ValueError(f'stale text: {path}')
        item['text'] = path.read_text()
        item['judge'] = judgements[item['part']]
        item['bindings'] = [c for c in inventory['collection_unique_audio_text_voice_bindings']
                            if c['audio_sha256'] == item['audio_sha256']]
        clips.append(recording(item, source['audio'], source['audio_sha256']))
    # Each candidate binding must be represented by the exact showcase bytes/text.
    for binding in inventory['collection_unique_audio_text_voice_bindings']:
        if sha(Path(binding['audio']).parent/'manifest.json') != inventory['candidate_manifest_sha256']:
            raise ValueError('stale Collection manifest')
        if sha(binding['audio']) != binding['audio_sha256']:
            raise ValueError('stale Collection audio')
        if not any(c['audio_sha256'] == binding['audio_sha256'] and
                   c['text_sha256'] == binding['text_sha256'] for c in clips):
            raise ValueError('Collection binding missing from listening page')
    for i, ref in enumerate(cast['references']):
        provenance = json.loads(Path(ref['provenance']).read_text())['generation']
        ref_text_sha = hashlib.sha256(ref['reference_text'].encode()).hexdigest()
        if provenance['audio_sha256'] != ref['reference_sha256'] or provenance['text_sha256'] != ref_text_sha:
            raise ValueError('stale reference provenance')
        item = dict(id=f'cast-{i}', part=6,
                    label=f"{ref['character']} · {ref['recorded_model_id']}",
                    text=ref['reference_text'], text_sha256=ref_text_sha,
                    backend=provenance['model'], permission='Original synthetic reference; private review only.',
                    acoustic_acceptance='pending', provenance_sha256=sha(ref['provenance']),
                    judge=f"{ref['direction']} Judge recognisability, distinctness, consistency and naturalness; reference listening alone does not approve a response.",
                    bindings=[], voice_key=ref['canonical_key'])
        clips.append(recording(item, ref['reference'], ref['reference_sha256']))
    data = dict(clips=clips, inventory_sha256=sha(handoff/'inventory.json'),
                cast_inventory_sha256=sha(handoff/'cast-reference-inventory.json'),
                candidate_manifest_sha256=inventory['candidate_manifest_sha256'],
                word_flags=Path(inventory['word_flags']).read_text())
    # Complete validation precedes output; originals and receipts stay untouched.
    out.mkdir(parents=True, exist_ok=True)
    (out/'audio').mkdir()
    for digest, source in sources.items():
        shutil.copyfile(source, out/'audio'/f'{digest}.wav')
    template = (ROOT/'expressive/showcase/acceptance.html').read_text()
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    (out/'index.html').write_text(template.replace('__MANIFEST__', encoded))
    for name in ('acceptance.js', 'acceptance.css'):
        shutil.copyfile(ROOT/'expressive/showcase'/name, out/name)
    (out/'manifest.json').write_text(json.dumps(data, indent=2)+'\n')
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff', type=Path, default=ROOT/'var/expressive-voice/acceptance-handoff-1')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.handoff, args.out)
    print(f"Packaged {len(result['clips'])} labelled recordings; acceptance remains pending.")
