import hashlib
import json
import wave

import pytest

from expressive.library import library_plan, install_aliases


def fixture(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    wav = source/'actor-ref.wav'
    with wave.open(str(wav), 'wb') as f:
        f.setparams((1, 2, 24000, 24000, 'NONE', 'not compressed'))
        f.writeframes(b'\0\0'*24000)
    digest = hashlib.sha256(wav.read_bytes()).hexdigest()
    (source/'actor.json').write_text(json.dumps({'reference_audio': wav.name, 'reference_text': 'Literal words.'}))
    snapshot = {'records': [{'wav': wav.name, 'final_disposition': 'ACCEPTED',
                            'audio': {'sha256': digest}, 'profiles': [{'reference_text': 'Literal words.'}]}]}
    accepted = {'records': [{'wav': wav.name, 'sha256': digest, 'status': 'accepted'}]}
    return source, snapshot, accepted


def test_alias_reuses_inode_and_is_idempotent(tmp_path):
    source, snapshot, accepted = fixture(tmp_path)
    before = (source/'actor.json').read_bytes()
    plan = library_plan(source, snapshot, accepted)
    target = tmp_path/'target'
    assert len(install_aliases(plan, target)) == 2
    assert install_aliases(plan, target) == []
    assert (source/'actor-ref.wav').samefile(target/'actor-ref.wav')
    profile = json.loads((target/'fish-actor.json').read_text())
    assert profile['synthesis_extras']['qwen_fallback'] is False
    assert profile['reference_text'] == 'Literal words.'
    assert (source/'actor.json').read_bytes() == before


def test_changed_transcript_or_audio_is_excluded(tmp_path):
    source, snapshot, accepted = fixture(tmp_path)
    (source/'actor.json').write_text(json.dumps({'reference_audio': 'actor-ref.wav', 'reference_text': 'Invented.'}))
    assert library_plan(source, snapshot, accepted)['compatible'] == 0
    (source/'actor-ref.wav').write_bytes(b'changed')
    assert library_plan(source, snapshot, accepted)['compatible'] == 0


def test_collision_preserves_assets_before_install(tmp_path):
    source, snapshot, accepted = fixture(tmp_path)
    target = tmp_path/'target'
    target.mkdir()
    collision = target/'fish-actor.json'
    collision.write_text('existing')
    with pytest.raises(ValueError, match='conflicting'):
        install_aliases(library_plan(source, snapshot, accepted), target)
    assert collision.read_text() == 'existing'
    assert not (target/'actor-ref.wav').exists()


@pytest.mark.parametrize("backend", [None, "", "qwen3-0.6b"])
def test_default_qwen_backend_accepts_literal_reference(tmp_path, backend):
    source, snapshot, accepted = fixture(tmp_path)
    profile = source / 'actor.json'
    data = json.loads(profile.read_text())
    data['backend'] = backend
    profile.write_text(json.dumps(data))
    assert library_plan(source, snapshot, accepted)['compatible'] == 1
