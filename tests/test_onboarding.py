"""Baseline onboarding regressions, without model loads or host mutation."""
import builtins
import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf

import backends
import server
from backends.qwen3 import Qwen3Backend

REPO = Path(__file__).resolve().parents[1]


def test_baseline_selection(monkeypatch):
    monkeypatch.delenv('AFTERWORDS_BACKENDS', raising=False)
    assert server._selected_backends(False) == {'qwen3-0.6b'}
    assert server._selected_backends(True) == {'qwen3-0.6b', 'qwen3-1.7b'}
    monkeypatch.setenv('AFTERWORDS_BACKENDS', 'fake')
    assert server._selected_backends(False) == {'fake'}
    monkeypatch.setenv('AFTERWORDS_BACKENDS', 'typo')
    with pytest.raises(ValueError):
        server._selected_backends(False)


def test_health_does_not_claim_registered_backend_loaded(client, monkeypatch):
    monkeypatch.setattr(server, '_backend_states', {
        'qwen3-0.6b': dict(state='failed', available=False, loaded=False, error='missing dependency'),
        'fake': dict(state='loaded', available=True, loaded=True, error=None),
    })
    body = client.get('/health').json()
    assert body['service'] == 'afterwords'
    states = body['loaded_backends']
    assert states['qwen3-0.6b']['loaded'] is False
    assert states['qwen3-0.6b']['error'] == 'missing dependency'
    assert states['qwen3-1.7b']['state'] == 'registered'
    assert states['qwen3-1.7b']['available'] is None
    assert states['fake']['loaded'] is True


def test_missing_qwen_dependency_is_failed_load(monkeypatch):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name.startswith('mlx_audio'):
            raise ImportError('simulated missing mlx-audio')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    backend = Qwen3Backend('0.6B')
    with pytest.raises(RuntimeError, match='mlx-audio not importable'):
        backend.load()
    assert backend._loaded is False
    assert backend._model is None


def test_warmup_failure_is_not_swallowed(sample_voice, monkeypatch):
    monkeypatch.setattr(server, 'DEFAULT_VOICE', sample_voice)
    def broken(*args, **kwargs):
        raise RuntimeError('synthesis failed')
    monkeypatch.setattr(backends.get('fake'), 'synthesize', broken)
    with pytest.raises(RuntimeError, match='synthesis failed'):
        server._warmup()


def test_plist_creates_destination_and_escapes_paths(tmp_path):
    repo = tmp_path / 'A & B <checkout>'
    path = tmp_path / 'new/LaunchAgents/server.plist'
    subprocess.run([sys.executable, str(REPO / 'scripts/write-server-plist.py'),
                    '--path', str(path), '--repo', str(repo), '--backends', 'qwen3-0.6b,fake'], check=True)
    data = plistlib.loads(path.read_bytes())
    assert data['ProgramArguments'][1] == str(repo / 'server.py')
    assert data['EnvironmentVariables']['AFTERWORDS_BACKENDS'] == 'qwen3-0.6b,fake'
    assert not list(path.parent.glob('.afterwords-*'))


def test_setup_unknown_flag_exits_before_mutation(tmp_path):
    result = subprocess.run(['bash', str(REPO / 'setup.sh'), '--typo'],
                            env={**os.environ, 'HOME': str(tmp_path)}, capture_output=True)
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


def test_wav_acceptance_rejects_silent_and_invalid_audio(tmp_path):
    spec = importlib.util.spec_from_file_location('validate_wav', REPO / 'scripts/validate-wav.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'speech.wav'
    sf.write(path, np.zeros(24000), 24000)
    with pytest.raises(ValueError, match='silent'):
        module.validate(path)
    sf.write(path, np.sin(np.arange(24000) / 20) * .2, 24000)
    module.validate(path)
    path.write_text('not a WAV')
    with pytest.raises(Exception):
        module.validate(path)


def test_foreign_listener_is_never_stopped(tmp_path):
    stub = tmp_path / 'bin'
    stub.mkdir()
    for name, body in {
        'lsof': 'echo 987654',
        'ps': 'echo "/usr/bin/python3 /other/server.py"',
        'kill': 'echo unsafe-kill; exit 99',
        'launchctl': 'echo unsafe-launchctl; exit 99',
    }.items():
        path = stub / name
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)
    for command in ('start', 'stop', 'status'):
        result = subprocess.run(['bash', str(REPO / 'afterwords.sh'), command],
                                env={**os.environ, 'PATH': str(stub) + ':' + os.environ['PATH'],
                                     'AFTERWORDS_NO_LAUNCHCTL': '1', 'HOME': str(tmp_path)},
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert 'conflict' in result.stdout
        assert 'unsafe-' not in result.stdout


def test_regenerated_plist_preserves_explicit_backend_selection(tmp_path):
    path = tmp_path / 'server.plist'
    base = [sys.executable, str(REPO / 'scripts/write-server-plist.py'),
            '--path', str(path), '--repo', str(tmp_path)]
    subprocess.run(base + ['--backends', 'qwen3-0.6b,fake'], check=True)
    subprocess.run(base, check=True)
    assert plistlib.loads(path.read_bytes())['EnvironmentVariables']['AFTERWORDS_BACKENDS'] == 'qwen3-0.6b,fake'


def test_gallery_reload_without_upload_permissions(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, '_clone_enabled', False)
    monkeypatch.setattr(server, '_reload_enabled', True)
    monkeypatch.setattr(server, '_VOICES_DIR', str(tmp_path))
    assert client.post('/reload').status_code == 200
    assert client.post('/synthesize', json={'text': 'hi', 'voice': 'testvoice'}).status_code == 404
    assert client.delete('/session/example').status_code == 404
    assert client.post('/clone', data={'session_id': 'example'},
                       files={'audio': ('ref.wav', b'not decoded when disabled', 'audio/wav')}).status_code == 404


@pytest.mark.parametrize('host,enabled', [('', True), ('127.0.0.1', True), ('192.168.0.2', False)])
def test_gallery_reload_plist_default_is_local(tmp_path, host, enabled):
    path = tmp_path / 'server.plist'
    subprocess.run([sys.executable, str(REPO / 'scripts/write-server-plist.py'),
                    '--path', str(path), '--repo', str(tmp_path), '--host', host], check=True)
    argv = plistlib.loads(path.read_bytes())['ProgramArguments']
    assert ('--allow-reload' in argv) is enabled


def test_reload_cli_propagates_http_error(tmp_path):
    stub = tmp_path / 'bin'
    stub.mkdir()
    curl = stub / 'curl'
    curl.write_text('#!/bin/bash\necho "disabled endpoint"\nexit 22\n')
    curl.chmod(0o755)
    result = subprocess.run(['bash', str(REPO / 'afterwords.sh'), 'reload'],
                            env={**os.environ, 'PATH': str(stub) + ':' + os.environ['PATH']},
                            capture_output=True, text=True)
    assert result.returncode != 0
