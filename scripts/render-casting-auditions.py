#!/usr/bin/env python3
"""Render a small, explicit private audition plan through the existing sidecar.

No profile changes, retries, text rewrites, acceptance receipts or publication.
The plan binds every excerpt to a complete captured model response and retains
both failed and successful attempts. Direction consists only of request-local cues.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chunks import chunk_text
from expressive.contracts import validate_options, directed_text
from expressive.auth import authorization_headers


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def words(text):
    return re.findall(r"\w+(?:['’]\w+)*", text)


def render(plan_path, out):
    plan_path, out = Path(plan_path), Path(out)
    plan = json.loads(plan_path.read_text())
    if out.exists():
        raise ValueError('preserve all previous attempts: output already exists')
    if not 1 <= len(plan['takes']) <= 10:
        raise ValueError('audition plan must contain 1–10 takes')
    prepared = []
    for take in plan['takes']:
        source = Path(take['source_text']).read_text()
        if sha(source.encode()) != take['source_text_sha256']:
            raise ValueError('captured response changed')
        if 'run' in take:
            record_path = Path(take['source_record'])
            if sha(record_path.read_bytes()) != take['source_record_sha256']:
                raise ValueError('public source record changed')
            record = json.loads(record_path.read_text())
            attempt = record['attempts'][take.get('attempt_index', 0)]
            if (record['run'] != take['run'] or record['specimen_id'] != take['specimen_id']
                    or attempt.get('capture_status') != 'complete' or attempt.get('truncated')
                    or attempt['response_text'] != source):
                raise ValueError('excerpt is not bound to the captured model response')
        excerpt = source[take['start']:take['end']]
        if words(excerpt) != words(take['text']):
            raise ValueError('audition changed original words')
        reference = Path(take['reference']).read_bytes()
        if sha(reference) != take['reference_sha256']:
            raise ValueError('reference changed')
        options = validate_options(take.get('performance', {}))
        directed_text(take['text'], options)
        if take.get('backend') == 'qwen3-0.6b' and (options['cues'] or not take.get('voice')):
            raise ValueError('Qwen auditions need an explicit voice and cannot apply Drama cues')
        segments = chunk_text(take['text'], max_chars=400)
        if words(' '.join(segments)) != words(take['text']):
            raise ValueError('chunking changed words')
        prepared.append((take, reference, options, segments))
    out.mkdir(parents=True)
    receipt = dict(status='running', plan_sha256=sha(plan_path.read_bytes()), takes=[])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def save():
        (out/'run.json').write_text(json.dumps(receipt, indent=2)+'\n')
    for take, reference, options, segments in prepared:
        row = dict(take, status='incomplete', chunks=[])
        receipt['takes'].append(row); save()
        started = time.monotonic()
        try:
            arrays, params, cursor = [], None, 0
            for index, segment in enumerate(segments):
                offset = take['text'].find(segment, cursor)
                if offset < 0:
                    raise ValueError('chunk cannot be bound to excerpt')
                cursor = offset+len(segment)
                local = dict(options, cues=[dict(c, offset=c['offset']-offset) for c in options['cues']
                                           if offset <= c['offset'] < cursor])
                payload = dict(text=segment, reference_text=take['reference_text'],
                               reference_wav=base64.b64encode(reference).decode(), performance=local)
                is_qwen = take.get('backend') == 'qwen3-0.6b'
                if is_qwen:
                    query = urllib.parse.urlencode(dict(text=segment, voice=take['voice'], lang='en'))
                    request = urllib.request.Request('http://127.0.0.1:7860/synthesize?'+query)
                else:
                    request = urllib.request.Request('http://127.0.0.1:7861/synthesize',
                        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **authorization_headers()})
                with opener.open(request, timeout=185) as response:
                    raw = response.read()
                    headers = dict(response.headers)
                    chunk_path = out/f"{take['id']}-chunk{index+1}.wav"
                    chunk_path.write_bytes(raw)
                    row['chunks'].append(dict(file=chunk_path.name, text=segment,
                        audio_sha256=sha(raw), headers=headers, performance=local))
                    save()
                    expected_backend = 'qwen3-0.6b' if is_qwen else 'fish-drama3'
                    backend_header = 'X-Backend' if is_qwen else 'X-Afterwords-Backend'
                    if response.headers.get(backend_header) != expected_backend:
                        raise ValueError('unexpected delivered backend; no substitution allowed')
                with wave.open(io.BytesIO(raw)) as wav:
                    actual = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
                    if actual != (1, 2, 24000 if is_qwen else 44100) or (params is not None and actual != params):
                        raise ValueError('invalid audition WAV format')
                    params = actual
                    arrays.append(wav.readframes(wav.getnframes()))
            path = out/f"{take['id']}.wav"
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((*params, 0, 'NONE', 'not compressed'))
                wav.writeframes(b''.join(arrays))
            row.update(status='generated_not_accepted', audio=path.name, audio_sha256=sha(path.read_bytes()),
                       duration_seconds=sum(map(len, arrays))/2/params[2])
            print(take['id'], row['status'], round(row['duration_seconds'], 2), flush=True)
        except Exception as exc:
            row.update(status='rejected_generation_failure', error=f'{type(exc).__name__}: {exc}')
            if isinstance(exc, urllib.error.HTTPError):
                row['server_error'] = exc.read(65536).decode(errors='replace')
            print(take['id'], row['error'], flush=True)
        finally:
            row['wall_seconds'] = time.monotonic()-started; save()
    receipt['status'] = 'auditions_retained_no_acceptance'
    save()
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    render(a.plan, a.out)
