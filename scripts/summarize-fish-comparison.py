#!/usr/bin/env python3
"""Summarize retained diagnostic receipts; never manufacture acceptance."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists(): p.error('preserve previous summaries; choose a new output')
    identity_path = a.root/'identity-audit.json'
    identity = json.loads(identity_path.read_text())
    speakers = {r['sha256']: r for r in identity['audio']}
    result = {'schema': 'afterwords-fish-comparison-summary/1',
              'created_at': datetime.now(timezone.utc).isoformat(), 'human_listening': 'not performed',
              'acoustic_acceptance': 'unverified', 'private_evidence_root': str(a.root),
              'identity_audit_sha256': sha(identity_path), 'identity_references': identity['references'],
              'attempts': [], 'matrices': [], 'limitations': [
                  'One long script, one reference and one seed; not a general reliability qualification.',
                  'Word edits are CPU ASR measurements, not proven auditory errors.',
                  'Identity embeddings include silence windows and are not calibrated identity judgements.',
                  'Internal TTFA is not first audible playback.',
                  'Long-form ambient inference was not successfully observed; no compute-isolation claim.',
                  'Controlled workload is a short overlap pilot; no reliable general inference slowdown estimate.']}
    for matrix in sorted(a.root.glob('*/matrix.json')):
        m = json.loads(matrix.read_text())
        result['matrices'].append({'path': str(matrix.relative_to(a.root)), 'sha256': sha(matrix),
                                   'status': m['status'], 'conditions': [
                                       {k:r[k] for k in ('id', 'status', 'reason') if k in r} for r in m['attempts']]})
    for path in sorted(a.root.glob('*/*/run.json')):
        r = json.loads(path.read_text())
        row = {'receipt': str(path.relative_to(a.root)), 'receipt_sha256': sha(path)}
        for key in ('created_at', 'ended_at', 'status', 'error', 'actual_backend', 'model', 'revision',
                    'quantisation', 'checkpoint_quantization', 'loaded_quantization', 'qwen_fallback',
                    'reference_sha256', 'reference_text_sha256', 'conditioning_sha256', 'seed',
                    'mode', 'max_frames_per_native_chunk', 'implementation_sha256', 'native_chunker_sha256',
                    'source_hashes', 'text', 'text_sha256', 'calls', 'native_chunks', 'waveform',
                    'audio_sha256', 'load_seconds', 'generation_seconds', 'ttfa_seconds', 'peak_metal_bytes',
                    'resources', 'rtf', 'generation_start_monotonic', 'generation_end_monotonic', 'workload'):
            if key in r: row[key] = r[key]
        audit = path.parent/'word-audit-mainenv.json'
        if audit.exists():
            w = json.loads(audit.read_text())
            row['word_audit'] = {'path': str(audit.relative_to(a.root)), 'sha256': sha(audit),
                                 'status': w['status'], 'transcriber': w['transcriber'],
                                 'comparison': w.get('word_comparison')}
            row['word_edit_counts'] = dict(Counter(e['operation'] for e in w.get('word_comparison', {}).get('edits', [])))
        if r.get('audio_sha256') in speakers:
            windows = [w for w in speakers[r['audio_sha256']]['windows'] if 'cosine_to_references' in w]
            scores = [w['cosine_to_references'] for w in windows]
            row['identity'] = {'measured_windows': len(scores),
                               'intended_reference_ranks_first': sum(s[0] > max(s[1:]) for s in scores),
                               'intended_cosine_min': min(s[0] for s in scores),
                               'intended_cosine_max': max(s[0] for s in scores),
                               'windows': windows}
        if 'calls' in r.get('workload', {}):
            for call in row['workload']['calls']:
                call['fish_generation_overlap_seconds'] = max(0, min(call['end_monotonic'], r['generation_end_monotonic'])
                    - max(call['start_monotonic'], r['generation_start_monotonic']))
        result['attempts'].append(row)
    alias_path = a.root/'alias-http.json'
    if alias_path.exists():
        result['alias_http'] = json.loads(alias_path.read_text())
        result['alias_http']['receipt_sha256'] = sha(alias_path)
    result['early_admission_probe'] = json.loads((a.root/'admission-refusal-1/run.json').read_text())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({'receipts': len(result['attempts']), 'matrices': len(result['matrices'])}))


if __name__ == '__main__':
    main()
