import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import wave
from email.message import Message

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


restore = module('restore-vixen-seydoux')
audition = module('render-casting-auditions')
promote = module('promote-vixen-drama')
listening = module('build-casting-listening')


def config():
    return {'model': {'default': 'preserve-me'}, 'memory': {'enabled': True},
            'persona': 'Vixen', 'unrelated': {'nested': [1, 2]},
            'tts': {'provider': 'afterwords', 'providers': {'afterwords': {
                'type': 'command', 'voice': 'vixen-original-r1-live', 'command': 'old', 'timeout': 300}}},
            'hooks': {'post_llm_call': [
                {'command': 'env AFTERWORDS_PORT=17862 AFTERWORDS_VOICE=vixen-original-r1-live bash /existing/afterwords-post-llm.sh', 'timeout': 300},
                {'command': 'unrelated-hook', 'timeout': 12}], 'other_event': [{'command': 'preserve'}]}}


def test_restore_preserves_every_field_except_explicit_speech_overrides():
    original = config()
    result, hooks = restore.corrected(original)
    expected = copy.deepcopy(original)
    p = expected['tts']['providers']['afterwords']
    p['voice'] = 'seydoux'
    p['command'] = ('env AFTERWORDS_PORT=7860 AFTERWORDS_PLAYBACK_OWNER=hermes '
                    'bash ~/repos/afterwords/scripts/afterwords-tts-command.sh '
                    '{input_path} {output_path} {voice}')
    expected['hooks']['post_llm_call'][0]['command'] = 'env AFTERWORDS_PORT=7860 AFTERWORDS_VOICE=seydoux bash /existing/afterwords-post-llm.sh'
    assert result == expected
    assert original == config()
    assert len(hooks) == 1


def test_drama_promotion_round_trip_preserves_new_unrelated_work():
    original, _ = restore.corrected(config())
    result, rollback, hook = promote.transition(original)
    assert original['tts']['providers']['afterwords']['voice'] == 'seydoux'
    assert result['tts']['providers']['afterwords']['voice'] == promote.VOICE
    assert result['tts']['providers']['afterwords']['command'].endswith('{input_path} {output_path} {voice}')
    assert 'AFTERWORDS_PORT=17862 ' in hook['command']
    # Rollback restores speech fields, never an old whole profile.
    result['unrelated']['new_work'] = 'keep this'
    restored, _, _ = promote.transition(result, rollback)
    expected = copy.deepcopy(original)
    expected['unrelated']['new_work'] = 'keep this'
    assert restored == expected


def test_drama_promotion_refuses_unknown_route_and_ambiguous_hooks():
    original, _ = restore.corrected(config())
    original['tts']['providers']['afterwords']['voice'] = 'another-person'
    with pytest.raises(ValueError):
        promote.transition(original)
    original, _ = restore.corrected(config())
    original['hooks']['post_llm_call'].append(copy.deepcopy(original['hooks']['post_llm_call'][0]))
    with pytest.raises(ValueError):
        promote.transition(original)


def test_listening_refuses_mismatched_references_before_writing(tmp_path):
    pair = {'comparison_kind': 'matched-engine', 'reference_sha256': 'same',
            'baseline': {'reference_sha256': 'same'}, 'candidate': {'reference_sha256': 'other'}}
    selection = tmp_path/'selection.json'
    selection.write_text(json.dumps({'vixen': pair, 'performances': [pair]}))
    with pytest.raises(ValueError, match='identical reference'):
        listening.build(selection, tmp_path/'output')
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('change', ['provider', 'already-restored', 'unknown-hook'])
def test_restore_refuses_unexpected_state_instead_of_overwriting_it(change):
    c = config()
    if change == 'provider':
        c['tts']['provider'] = 'other'
    elif change == 'already-restored':
        c['tts']['providers']['afterwords']['voice'] = 'seydoux'
    else:
        c['hooks']['post_llm_call'][0]['command'] = 'unexpected'
    with pytest.raises(ValueError):
        restore.corrected(c)


def test_audition_word_comparison_retains_case_contractions_and_repetition():
    assert audition.words('**No.** No, I’m not rewriting that.') == ['No', 'No', 'I’m', 'not', 'rewriting', 'that']
    assert audition.words('No. No.') != audition.words('No.')
    assert audition.words('Maternal Gambit') != audition.words('maternal gambit')


@pytest.mark.parametrize('header', ['qwen3-0.6b', None, 'different-speaker-backend'])
def test_qwen_uses_its_actual_header_and_preserves_rejected_payloads(tmp_path, monkeypatch, header):
    text = tmp_path/'text.txt'; text.write_text('Keep my words.')
    reference = tmp_path/'reference.wav'; reference.write_bytes(b'bound-reference')
    payload = io.BytesIO()
    with wave.open(payload, 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0'*24000)
    raw = payload.getvalue()
    headers = Message()
    if header is not None:
        headers['X-Backend'] = header
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return raw
    Response.headers = headers
    class Opener:
        def open(self, request, timeout):
            assert 'voice=eartha-qwen3-06b' in request.full_url
            assert request.data is None
            return Response()
    monkeypatch.setattr(audition.urllib.request, 'build_opener', lambda *args: Opener())
    take = dict(id='bound', source_text=str(text), source_text_sha256=hashlib.sha256(text.read_bytes()).hexdigest(),
                start=0, end=len(text.read_text()), text=text.read_text(), reference=str(reference),
                reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(), reference_text='Reference.',
                backend='qwen3-0.6b', voice='eartha-qwen3-06b')
    plan = tmp_path/'plan.json'; plan.write_text(json.dumps({'takes': [take]}))
    out = tmp_path/'out'
    result = audition.render(plan, out)['takes'][0]
    assert (out/'bound-chunk1.wav').read_bytes() == raw
    assert result['chunks'][0]['headers'].get('X-Backend') == header
    assert result['status'] == ('generated_not_accepted' if header == 'qwen3-0.6b' else 'rejected_generation_failure')
    assert (out/'bound.wav').exists() == (header == 'qwen3-0.6b')
