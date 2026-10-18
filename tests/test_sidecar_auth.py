"""Browser-origin and credential checks happen before any model side effect."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient
from expressive import sidecar
from expressive.auth import authorization_headers


@pytest.mark.parametrize('route', ['/synthesize', '/release'])
@pytest.mark.parametrize('attack', ['missing', 'wrong', 'origin', 'null-origin', 'rebound-host', 'remote-client'])
def test_untrusted_requests_never_reach_worker(monkeypatch, sidecar_credentials, route, attack):
    synth = AsyncMock(side_effect=AssertionError('unauthorised model work'))
    stop = AsyncMock(side_effect=AssertionError('unauthorised worker release'))
    monkeypatch.setattr(sidecar.pool, 'synthesize', synth)
    monkeypatch.setattr(sidecar.pool, 'stop', stop)
    headers = dict(sidecar_credentials)
    host = 'http://127.0.0.1:7861'
    peer = ('127.0.0.1', 123)
    if attack == 'missing': headers = {}
    elif attack == 'wrong': headers['Authorization'] = 'Bearer wrong'
    elif attack == 'origin': headers['Origin'] = 'https://attacker.invalid'
    elif attack == 'null-origin': headers['Origin'] = 'null'
    elif attack == 'rebound-host': host = 'http://attacker.invalid:7861'
    elif attack == 'remote-client': peer = ('192.0.2.10', 123)
    response = TestClient(sidecar.app, base_url=host, client=peer).post(route, content=b'{}', headers=headers)
    assert response.status_code in (401, 403)
    synth.assert_not_called()
    stop.assert_not_called()


def test_authenticated_release_and_synthesis_keep_contract(monkeypatch, sidecar_credentials):
    monkeypatch.setattr(sidecar.pool, 'pending', 0)
    stop = AsyncMock()
    synth = AsyncMock(return_value=(b'RIFF-captured-test-audio', {'samples': 100}))
    monkeypatch.setattr(sidecar.pool, 'stop', stop)
    monkeypatch.setattr(sidecar.pool, 'synthesize', synth)
    client = TestClient(sidecar.app, base_url='http://127.0.0.1:7861', client=('127.0.0.1',123))
    assert client.post('/release', headers=sidecar_credentials).status_code == 200
    response = client.post('/synthesize', headers=sidecar_credentials,
                           json={'text':'Hello.', 'reference_wav':'test', 'reference_text':'Words.'})
    assert response.status_code == 200 and response.content == b'RIFF-captured-test-audio'
    assert response.headers['X-Afterwords-Backend'] == 'fish-drama3'
    stop.assert_awaited_once()
    synth.assert_awaited_once()


@pytest.mark.parametrize('problem', ['missing', 'public', 'symlink'])
def test_credential_file_fails_closed(tmp_path, monkeypatch, problem):
    path = tmp_path/'token'
    if problem != 'missing':
        path.write_text('x'*43)
        path.chmod(0o644 if problem=='public' else 0o600)
    if problem == 'symlink':
        link = tmp_path/'link'
        link.symlink_to(path)
        path = link
    monkeypatch.setenv('AFTERWORDS_SIDECAR_TOKEN_FILE', str(path))
    with pytest.raises((OSError, ValueError)):
        authorization_headers()


def test_plain_adapter_sends_private_auth(tmp_path, monkeypatch, sidecar_credentials):
    import io
    import urllib.request
    from email.message import Message
    from unittest.mock import Mock
    import numpy as np
    import soundfile as sf
    from backends.fish_drama3 import FishDrama3Backend
    reference = tmp_path/'ref.wav'
    sf.write(reference, np.zeros(24000), 24000)
    wav = io.BytesIO()
    sf.write(wav, np.full(4410, .1), 44100, format='WAV')
    response = Mock()
    response.headers = Message()
    response.headers['Content-Type'] = 'audio/wav'
    response.read.return_value = wav.getvalue()
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=response)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: opener)
    backend = FishDrama3Backend()
    profile = backend.prepare_voice(str(reference), 'Reference words.', {'qwen_fallback':False})
    audio, rate = backend.synthesize('Hello.', profile, 'en')
    assert rate == 44100 and len(audio) == 4410
    request = opener.open.call_args.args[0]
    assert request.get_header('Authorization') == sidecar_credentials['Authorization']


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('attack', ['missing', 'wrong', 'origin', 'rebound-host', 'remote-client'])
def test_expressive_api_rejects_requests_before_credentialed_proxy(monkeypatch, sidecar_credentials,
                                                                  ready_server, sample_voice, method, attack):
    import server
    from unittest.mock import Mock
    monkeypatch.setattr(server, '_require_expressive_auth', True)
    proxy = Mock(side_effect=AssertionError('unauthorised credentialed proxy'))
    monkeypatch.setattr(server, '_synthesize_for_request', proxy)
    headers = dict(sidecar_credentials)
    host, peer = 'http://127.0.0.1:7862', ('127.0.0.1',123)
    if attack == 'missing': headers = {}
    elif attack == 'wrong': headers['Authorization'] = 'Bearer wrong'
    elif attack == 'origin': headers['Origin'] = 'https://attacker.invalid'
    elif attack == 'rebound-host': host = 'http://attacker.invalid:7862'
    elif attack == 'remote-client': peer = ('192.0.2.10',123)
    response = TestClient(server.app, base_url=host, client=peer).request(
        method, '/synthesize', headers=headers, params={'text':'Hello.', 'voice':sample_voice})
    assert response.status_code in (401,403)
    proxy.assert_not_called()


@pytest.mark.parametrize('port', [7862,17862])
def test_authenticated_api_routes_preserve_synthesis(monkeypatch, sidecar_credentials,
                                                    ready_server, sample_voice, port):
    import server
    monkeypatch.setattr(server, '_require_expressive_auth', True)
    client = TestClient(server.app, base_url=f'http://127.0.0.1:{port}', client=('127.0.0.1',123))
    assert client.get('/health').status_code == 200
    response = client.get('/synthesize', params={'text':'Hello.', 'voice':sample_voice}, headers=sidecar_credentials)
    assert response.status_code == 200 and response.content.startswith(b'RIFF')


def test_curl_header_file_is_private_and_never_contains_token_in_argv(tmp_path, sidecar_credentials):
    import os,subprocess,sys
    script = Path(__file__).resolve().parents[1]/'expressive/auth.py'
    output = tmp_path/'curl.headers'
    command = [sys.executable,str(script),'--port','17862','--curl-headers',str(output)]
    result = subprocess.run(command,capture_output=True,text=True,check=True)
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.read_text() == 'Authorization: '+sidecar_credentials['Authorization']+'\n'
    assert not result.stdout and not result.stderr
    assert sidecar_credentials['Authorization'] not in ' '.join(command)
    other = tmp_path/'other.headers'
    subprocess.run([sys.executable,str(script),'--port','7860','--curl-headers',str(other)],check=True)
    assert not other.exists()
