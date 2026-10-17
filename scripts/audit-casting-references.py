#!/usr/bin/env python3
"""Inventory source custody and prior QA; never turn metrics into artistic approval."""
import argparse
import hashlib
import json
from pathlib import Path
import wave

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(lulzbench, peer_inventory=None):
    acceptance = json.loads((ROOT/'qa/voice-reference-remediation/final-acceptance.json').read_text())
    accepted = {r['wav']: r for r in acceptance['records']}
    library = {}
    for path in sorted((ROOT/'voices').glob('*.json')):
        profile = json.loads(path.read_text())
        name = profile.get('reference_audio', path.stem+'-ref.wav')
        wav = path.parent/name
        row = library.setdefault(name, {'reference': name, 'profiles': [], 'source_urls': [],
                                       'identity_permission': 'no grant established by this audit'})
        row['profiles'].append(path.name)
        if profile.get('source_url') and profile['source_url'] not in row['source_urls']:
            row['source_urls'].append(profile['source_url'])
        if 'sha256' in row or not wav.is_file():
            continue
        row['sha256'] = digest(wav)
        try:
            with wave.open(str(wav)) as audio:
                row['duration_seconds'] = audio.getnframes()/audio.getframerate()
                row['channels'] = audio.getnchannels()
        except wave.Error:
            row['format_requires_decoder'] = True
        prior = accepted.get(name, {})
        matched = prior.get('sha256') == row['sha256'] and prior.get('status') == 'accepted'
        row['quality_evidence'] = 'prior reference QA matches current bytes' if matched else 'not established'
        if matched:
            row['prior_adjudication'] = prior['adjudication']
            row['prior_evidence'] = prior['evidence']
        row['artistic_quality'] = 'not established by corpus integrity QA'
    registry = json.loads((lulzbench/'audio/casting.v1.json').read_text())
    originals = []
    for voice in [*[e['voice'] for e in registry['models'].values()], registry['announcer']]:
        path = lulzbench/voice['provenance']['receipt_file']
        receipt = json.loads(path.read_text())
        generation = receipt['generation']
        wav = ROOT/voice['reference_file']
        originals.append({'character': voice['character'], 'reference': voice['afterwords_voice'],
                          'reference_sha256': voice['reference_sha256'],
                          'current_bytes_match': wav.is_file() and digest(wav) == voice['reference_sha256'],
                          'receipt': voice['provenance']['receipt_file'],
                          'receipt_sha256_matches': digest(path) == voice['provenance']['receipt_sha256'],
                          'origin': voice['provenance']['source'],
                          'generator_model': generation['model'],
                          'generator_revision': generation.get('model_revision'),
                          'seed': generation['seed'], 'conditioning': generation.get('reference_conditioning'),
                          'quality': 'rejected as current ensemble by operator; individual artistic quality unestablished',
                          'prior_acoustic_status': generation.get('acoustic_acceptance'),
                          'identity_basis': receipt['reference_rights_basis'],
                          'publication': 'not admitted; retain existing gates'})
    directions = json.loads((ROOT/'qa/expressive-voice/casting-directions.v2.json').read_text())
    replacements = []
    for d in directions['performances']:
        profile = json.loads((ROOT/f"voices/{d['reference']}.json").read_text())
        row = library[profile['reference_audio']]
        replacements.append({'character': d['character'], 'reference': d['reference'],
                             'reference_sha256_matches': row['sha256'] == d['reference_sha256'],
                             'source_urls': row['source_urls'], 'quality_evidence': row['quality_evidence'],
                             'identity_permission': row['identity_permission'],
                             'text_model': d['run'], 'synthesis_engine': d['backend']})
    result = {'schema': 'casting-reference-audit/1', 'library': list(library.values()),
            'registry': originals, 'private_replacements': replacements,
            'limitations': ['Prior corpus QA establishes reference integrity for matching bytes, not memorable acting.',
                            'A source URL, model license, or possession of a recording is not an identity permission record.',
                            'No identity grant has been supplied for the selected character clones; private audition only.',
                            'No public registry, receipt, or deployment is changed.']}
    if peer_inventory:
        # The host's full inventory includes private profiles/transcripts. Retain
        # that source privately and publish only aggregate custody information.
        rows = json.loads(peer_inventory.read_text())
        unique = {r['reference']: r for r in rows if 'reference' in r}
        known = {r['sha256'] for r in library.values() if 'sha256' in r}
        matched = sum(r['sha256'] in known for r in unique.values())
        result['m5_library'] = {'profiles': len(rows), 'unique_references': len(unique),
                                'canonical_accepted_hash_matches': matched,
                                'outside_canonical_qa': len(unique)-matched,
                                'scope': 'Full host inventory retained privately; additional references are not admitted by this audit.'}
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lulzbench', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--peer-inventory', type=Path, help='Private M5 inventory JSON; emit aggregate counts only')
    a = p.parse_args()
    result = audit(a.lulzbench, a.peer_inventory)
    with a.out.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'references': len(result['library']), 'registry_characters': len(result['registry']),
                      'prior_qa_matches': sum(r.get('quality_evidence') == 'prior reference QA matches current bytes'
                                              for r in result['library'])}))
