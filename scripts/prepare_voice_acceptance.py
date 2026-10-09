#!/usr/bin/env python3
"""Freeze the tracked production corpus and byte-identical anonymous QA inputs.

This prepares a fresh listening pass; it does not accept audio or transcripts.
Private on-disk files never enter the production scope.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from voice_corpus import inspect_audio


def prepare(root: Path, mirror: Path, output: Path, unchanged: list[str]):
    qa = root / 'qa/voice-reference-remediation'
    baseline = json.loads((qa / 'baseline.json').read_text())
    repairs = json.loads((qa / 'changes.json').read_text())
    known = {r['wav'] for r in baseline['records']}
    changed = {r['wav'] for r in repairs['changes']}
    excluded = {r['wav'] for r in repairs['exclusions'] if r['production_disposition'] == 'excluded'}
    kept = set(unchanged)
    assert not (changed & excluded or kept & (changed | excluded))
    assert known == changed | excluded | kept, 'Finish every individual disposition before the final pass'
    tracked = subprocess.check_output(['git', 'ls-files', 'voices'], cwd=root, text=True).splitlines()
    wavs = sorted(p for p in tracked if p.endswith('-ref.wav'))
    assert {Path(p).name for p in wavs} == known - excluded
    profiles = {}
    for path in tracked:
        if not path.endswith('.json'):
            continue
        data = json.loads((root / path).read_text())
        profiles.setdefault(data['reference_audio'], []).append({
            'path': path, 'profile_sha256': hashlib.sha256((root / path).read_bytes()).hexdigest(),
            'reference_text': data['reference_text']})
    assert set(profiles) == known - excluded, 'Missing reference or unexplained production orphan'
    assert not mirror.exists() and not output.exists(), 'Final QA must start with fresh output paths'
    records = []
    (mirror / 'voices').mkdir(parents=True)
    for index, path in enumerate(wavs, 1):
        ref = Path(path).name
        texts = {p['reference_text'] for p in profiles[ref]}
        assert len(texts) == 1 and next(iter(texts)).strip(), f'Divergent/empty profile text: {ref}'
        audio = inspect_audio(root / path)
        assert audio['duration_s'] >= 3 and audio['rms'] > 0, f'Unusable basic audio: {ref}'
        alias = f'clip-{index:03d}-ref.wav'
        shutil.copyfile(root / path, mirror / 'voices' / alias)
        assert hashlib.sha256((mirror / 'voices' / alias).read_bytes()).hexdigest() == audio['sha256']
        records.append({'index': index, 'wav': ref, 'anonymous_wav': alias,
                        'audio': audio, 'profiles': profiles[ref],
                        'native_listening': 'pending', 'transcript_verification': 'pending',
                        'final_disposition': 'pending'})
    result = {'schema_version': 1, 'production_commit': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'known_baseline_count': len(known), 'production_count': len(records),
        'excluded': sorted(excluded), 'unchanged_audio': sorted(kept),
        'scope': 'All tracked production WAVs and profiles; anonymous inputs verified byte-identical',
        'final_corpus_acceptance': 'pending fresh native listening and root adjudication', 'records': records}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(f'Prepared {len(records)} references; final acceptance remains pending.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unchanged', action='append', default=[])
    args = parser.parse_args()
    prepare(args.root, args.mirror, args.output, args.unchanged)
