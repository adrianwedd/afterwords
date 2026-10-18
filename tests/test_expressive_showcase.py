import hashlib
import importlib.util
import json
from pathlib import Path
import wave
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('showcase_builder', ROOT/'scripts/build-expressive-showcase.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def fixture(tmp_path):
    wav = tmp_path/'source.wav'
    with wave.open(str(wav),'wb') as output:
        output.setparams((1,2,24000,0,'NONE','not compressed'))
        output.writeframes(b'\0\0'*2400)
    text = tmp_path/'source.txt';text.write_text('</script><script>alert(1)</script>')
    manifest = tmp_path/'input.json'
    item = dict(id='comparison',part=1,label='Fixture',backend='fixture',audio='source.wav',
                text='source.txt',audio_sha256=hashlib.sha256(wav.read_bytes()).hexdigest(),
                text_sha256=hashlib.sha256(text.read_bytes()).hexdigest())
    manifest.write_text(json.dumps({'clips':[item]}))
    return manifest, wav, text


def test_build_preserves_bytes_and_escapes_embedded_transcript(tmp_path):
    source, wav, text = fixture(tmp_path)
    out = tmp_path/'build'
    result = builder.build(source,out)
    clip = result['clips'][0]
    assert (out/clip['audio']).read_bytes() == wav.read_bytes()
    assert clip['text'] == text.read_text()
    assert text.read_text() not in (out/'index.html').read_text()
    assert '\\u003c/script>' in (out/'index.html').read_text()
    with pytest.raises(ValueError, match='preserve prior'):
        builder.build(source,out)


@pytest.mark.parametrize('changed', ['audio','text'])
def test_stale_evidence_fails_before_creating_build(tmp_path, changed):
    source, wav, text = fixture(tmp_path)
    target = wav if changed=='audio' else text
    target.write_bytes(target.read_bytes()+b'changed')
    with pytest.raises(ValueError, match='stale'):
        builder.build(source,tmp_path/'build')
    assert not (tmp_path/'build').exists()
