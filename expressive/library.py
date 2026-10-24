"""Opt-in Fish aliases bound to audited audio and literal transcripts."""
import hashlib
import json
import os
from pathlib import Path

from expressive.reference import normalize_reference


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def library_plan(source, snapshot, acceptance):
    source = Path(source).resolve()
    accepted = {r['wav']: r for r in acceptance['records'] if r['status'] == 'accepted'}
    verified = {r['wav']: r for r in snapshot['records'] if r['final_disposition'] == 'ACCEPTED'}
    rows = []
    for name, evidence in sorted(accepted.items()):
        row = {'reference': name, 'status': 'excluded', 'profiles': []}
        rows.append(row)
        try:
            path = source / name
            if path.resolve().parent != source or Path(name).name != name:
                raise ValueError('reference escapes source directory')
            raw = path.read_bytes()
            row['reference_sha256'] = sha(raw)
            if sha(raw) != evidence['sha256'] or verified[name]['audio']['sha256'] != sha(raw):
                raise ValueError('reference bytes differ from accepted audit')
            _, conversion = normalize_reference(raw)
            texts = {p['reference_text'] for p in verified[name]['profiles']}
            if len(texts) != 1 or not next(iter(texts)).strip():
                raise ValueError('audit has conflicting or empty literal transcripts')
            text = next(iter(texts))
            for profile_path in sorted(source.glob('*.json')):
                profile = json.loads(profile_path.read_text())
                if profile.get('reference_audio', profile_path.stem + '-ref.wav') != name:
                    continue
                backend = profile.get('backend') or 'qwen3-0.6b'
                if not isinstance(backend, str) or not backend.startswith('qwen3-'):
                    continue
                if profile.get('reference_text') != text:
                    raise ValueError(f'{profile_path.name}: transcript differs from accepted literal words')
                row['profiles'].append(profile_path.name)
            if not row['profiles']:
                raise ValueError('no matching Qwen profile')
            alias = 'fish-' + Path(name).stem.removesuffix('-ref')
            profile = {'name': alias, 'backend': 'fish-drama3', 'reference_audio': name,
                       'reference_text': text, 'synthesis_extras': {'qwen_fallback': False},
                       'reference_sha256': sha(raw),
                       'transcript_sha256': sha(text.encode()),
                       'reference_evidence': 'qa/voice-reference-remediation/final-acceptance.json',
                       'notes': 'Private opt-in alias; original recording, no public release grant.'}
            row.update(status='compatible', alias=alias, profile=profile,
                       conditioning_conversion=conversion,
                       source_path=str(path), transcript_sha256=sha(text.encode()))
        except (OSError, ValueError, KeyError) as exc:
            row['reason'] = str(exc)
    return {'schema': 'afterwords-fish-library/1', 'references': rows,
            'compatible': sum(r['status'] == 'compatible' for r in rows),
            'excluded': sum(r['status'] != 'compatible' for r in rows)}


def install_aliases(plan, target, created=None):
    """Add profiles and hard links only; preflight all collisions before writing.

    Hard links satisfy the server's same-directory custody rule without copying
    recordings. Different filesystems fail explicitly; never fall back to copying.
    """
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    desired = {}
    for row in plan['references']:
        if row['status'] != 'compatible':
            continue
        raw = Path(row['source_path']).read_bytes()
        if sha(raw) != row['reference_sha256']:
            raise ValueError('reference changed after planning')
        recording = target / row['reference']
        profile = target / (row['alias'] + '.json')
        encoded = (json.dumps(row['profile'], indent=2, ensure_ascii=False) + '\n').encode()
        for path, data in ((recording, raw), (profile, encoded)):
            if path.is_symlink() or (path.exists() and path.read_bytes() != data):
                raise ValueError(f'preserve existing conflicting asset: {path}')
        if os.stat(row['source_path']).st_dev != target.stat().st_dev:
            raise ValueError('hard-link target must be on the same filesystem as the original WAV')
        desired[recording] = (row['source_path'], None)
        desired[profile] = (None, encoded)
    if created is None:
        created = []
    for path, (source, encoded) in desired.items():
        if path.exists():
            continue
        if source:
            os.link(source, path)
        else:
            with path.open('xb') as stream:
                stream.write(encoded)
        created.append(str(path))
    return created
