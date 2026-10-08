#!/usr/bin/env python3
"""Apply a root-approved correction discovered during fresh corpus acceptance.

Previous deliveries and exact operations remain reconstructable in Git and the
revision record. This validates bytes and evidence, never perceptual judgment.
"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import numpy as np
import soundfile as sf
from listen_voice_corpus import parsed_observation
from voice_corpus import inspect_audio


def revise(root, plan):
    qa = root / 'qa/voice-reference-remediation'
    manifest_path = qa / 'changes.json'
    manifest = json.loads(manifest_path.read_text())
    change = next(c for c in manifest['changes'] if c['wav'] == plan['wav'])
    wav = root / 'voices' / plan['wav']
    before = inspect_audio(wav)
    assert plan['approved'] is True and plan['adjudication'].strip()
    final_status = plan.get('final_status', 'accepted')
    assert final_status in ('accepted', 'pending', 'needs adjudication')
    assert before == change['resulting_audio'] and before['sha256'] == plan['expected_sha256']
    snapshot_path = qa / 'final-snapshot.json'
    snapshot = json.loads(snapshot_path.read_text())
    record = next(r for r in snapshot['records'] if r['wav'] == plan['wav'])
    assert record['audio'] == before
    candidate = Path(plan.get('candidate', wav))
    after = inspect_audio(candidate)
    operation = plan['operation']
    old_bytes = subprocess.check_output(['git', 'show', change['delivery_commit'] + ':voices/' + plan['wav']], cwd=root)
    assert hashlib.sha256(old_bytes).hexdigest() == before['sha256']
    if operation['type'] == 'lossless_current_pcm_slice':
        s, e = operation['start_frame'], operation['end_frame_exclusive']
        assert 0 <= s < e <= before['frames'] and e-s == after['frames']
        x, rate = sf.read(io.BytesIO(old_bytes), dtype='int16', always_2d=True)
        y, yr = sf.read(candidate, dtype='int16', always_2d=True)
        assert rate == yr == operation['sample_rate'] and before['subtype'] == after['subtype'] == 'PCM_16'
        assert np.array_equal(y, x[s:e])
    else:
        assert operation['type'] == 'text_only' and after == before
    evidence = []
    for index, source in enumerate(plan['native_result_evidence']):
        source = Path(source)
        o = json.loads(source.read_text())
        assert o['native_audio_proven'] and o['exit_code'] == 0 and o['transcript_scope'] == 'full'
        assert o['result']['status'] == 'SUCCESS' and parsed_observation(o['result']) is not None
        assert o['source_sha256'] == after['sha256'] and o['attachment_evidence']
        assert all(e['media_sha256'] == after['sha256'] for e in o['attachment_evidence'])
        assert o['wav'] == record['anonymous_wav']
        dest = qa / 'final-evidence' / f"{record['index']:03d}-{after['sha256'][:16]}-revision-{index+1}.json"
        evidence.append((source, dest))
    discovery = []
    for index, source in enumerate(plan.get('native_discovery_evidence', [])):
        source = Path(source)
        o = json.loads(source.read_text())
        assert o['native_audio_proven'] and o['exit_code'] == 0 and o['transcript_scope'] == 'full'
        assert o['result']['status'] == 'SUCCESS' and parsed_observation(o['result']) is not None
        assert o['source_sha256'] == before['sha256']
        dest = qa / 'final-evidence' / f"{record['index']:03d}-{before['sha256'][:16]}-discovery-{index+1}.json"
        discovery.append((source, dest))
    updates = []
    for profile in change['profiles']:
        path = root / profile['path']
        data = json.loads(path.read_text())
        assert data['reference_text'] == profile['new_reference_text'] and data['reference_audio'] == plan['wav']
        data['reference_text'] = plan['reference_text']
        if 'segment_start_s' in plan:
            data['segment_start_s'] = plan['segment_start_s']
        if 'notes' in plan:
            data['notes'] = plan['notes']
        updates.append((path, data, profile))
    revision = {'previous_delivery_commit': change['delivery_commit'], 'previous_audio': before,
                'previous_operation': copy.deepcopy(change['operation']),
                'previous_profiles': copy.deepcopy(change['profiles']),
                'previous_native_result_evidence': change['native_result_evidence'],
                'operation': operation, 'resulting_audio': after,
                'adjudication': plan['adjudication'], 'native_evidence': [str(dst.relative_to(root)) for _, dst in evidence],
                'discovery_native_evidence': [str(dst.relative_to(root)) for _, dst in discovery]}
    if 'transcript_resolution' in change:
        revision['previous_transcript_resolution'] = change.pop('transcript_resolution')
    change.setdefault('post_remediation_revisions', []).append(revision)
    change['resulting_audio'] = after
    change['native_result_evidence'] = revision['native_evidence'][0]
    change['adjudication'] += '\nFresh final correction: ' + plan['adjudication']
    if operation['type'] == 'lossless_current_pcm_slice':
        change['operation'] = {'type': 'replacement', 'sample_rate': after['sample_rate'],
            'source_start_frame': operation['start_frame'], 'source_end_frame_exclusive': operation['end_frame_exclusive'],
            'source_frame_origin': 'previous committed admitted reference: ' + revision['previous_delivery_commit'],
            'source_sha256': before['sha256'], 'conversion': 'Lossless PCM16 slice of previous admitted reference; original publisher/render recipe retained in post_remediation_revisions.'}
        change['deterministic_qa']['sample_exact_slice'] = True
        shutil.copyfile(candidate, wav)
    for source, dest in evidence + discovery:
        shutil.copyfile(source, dest)
    for path, data, profile in updates:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        profile['new_reference_text'] = data['reference_text']
        profile['new_segment_start_s'] = data.get('segment_start_s')
    record['audio'] = after
    for pr in record['profiles']:
        path = root / pr['path']
        pr['profile_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        pr['reference_text'] = json.loads(path.read_text())['reference_text']
    record['native_listening'] = 'fresh revision reviewed'
    record['transcript_verification'] = plan.get('transcript_status', 'root adjudicated fresh literal text')
    decisions_path = qa / 'final-acceptance.json'
    decisions = json.loads(decisions_path.read_text())
    verdict = next(r for r in decisions['records'] if r['wav'] == plan['wav'])
    verdict.update({'sha256': after['sha256'], 'status': final_status,
        'native_qa_verdict': plan.get('native_qa_verdict', 'passed after fresh root correction'),
        'transcript_status': plan.get('transcript_status', 'matched root-adjudicated literal words'), 'evidence': revision['native_evidence'],
        'adjudication': plan['adjudication'], 'deterministic_qa': {'audio_integrity': True,
            'production_hash_match': True, 'profile_relationships_consistent': True,
            'samples_at_full_scale': after['samples_at_full_scale']}})
    for path, obj in [(manifest_path, manifest), (snapshot_path, snapshot), (decisions_path, decisions)]:
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    mirror = Path(plan['mirror']) / 'voices' / record['anonymous_wav']
    shutil.copyfile(wav, mirror)
    assert hashlib.sha256(mirror.read_bytes()).hexdigest() == after['sha256']
    print('Revised', plan['wav'], '; commit and bind the revised delivery before reporting delivery.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    revise(args.root.resolve(), json.loads(args.plan.read_text()))
