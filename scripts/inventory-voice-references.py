#!/usr/bin/env python3
"""Read-only, standard-library inventory suitable for execution over SSH stdin.

Full output contains private profile names and literal transcripts. Retain it
privately. WAV metadata compatibility is not transcript or speaker verification.
"""
import hashlib
import json
from pathlib import Path
import sys
import wave


def inventory(folder):
    folder = Path(folder).resolve()
    rows = []
    for path in sorted(folder.glob('*.json')):
        row = {'profile': path.name}
        rows.append(row)
        try:
            p = json.loads(path.read_text())
            name = p.get('reference_audio', path.stem+'-ref.wav')
            ref = (folder/name).resolve()
            row.update(reference=name, backend=p.get('backend', 'qwen3-0.6b'),
                       reference_text=p.get('reference_text'), source_url=p.get('source_url'))
            if not ref.is_relative_to(folder):
                raise ValueError('reference escapes voice directory')
            raw = ref.read_bytes()
            row.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            with wave.open(str(ref)) as f:
                row.update(channels=f.getnchannels(), sample_rate=f.getframerate(),
                           duration_seconds=f.getnframes()/f.getframerate(), sample_width=f.getsampwidth())
            reasons = []
            if len(raw) > 4*1024**2: reasons.append('reference exceeds 4 MiB')
            if row['channels'] not in (1, 2): reasons.append('unsupported channel count')
            if not 1 <= row['duration_seconds'] <= 30: reasons.append('duration outside 1–30 seconds')
            if row['sample_rate'] > 192000: reasons.append('sample rate exceeds 192 kHz')
            if not isinstance(row['reference_text'], str) or not row['reference_text'].strip():
                reasons.append('missing transcript')
            row['metadata_issues'] = reasons
            row['status'] = 'metadata_incompatible' if reasons else 'needs_verified_transcript_and_pcm_validation'
        except (OSError, ValueError, TypeError, wave.Error, EOFError) as exc:
            row.update(status='unavailable_or_unsupported', error=str(exc))
    return {'schema': 'afterwords-reference-inventory/1', 'directory': str(folder), 'profiles': rows}


if __name__ == '__main__':
    print(json.dumps(inventory(sys.argv[1]), indent=2, ensure_ascii=False))
