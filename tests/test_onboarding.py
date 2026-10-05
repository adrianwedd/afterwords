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


@pytest.mark.parametrize('flags', [['--cli-dir'], ['--cli-dir=relative'], ['--cli-dir', 'relative']])
def test_invalid_cli_destination_fails_before_installation(tmp_path, flags):
    result = subprocess.run(['bash', str(REPO / 'setup.sh'), *flags],
                            env={**os.environ, 'HOME': str(tmp_path)}, capture_output=True)
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


def test_cli_installs_to_explicit_user_directory_without_sudo(tmp_path):
    import shlex
    destination = tmp_path / 'local tools/bin'
    source = (REPO / 'setup.sh').read_text()
    start = source.index('# Install CLI to PATH')
    end = source.index('# ── Verify', start)
    stub = tmp_path / 'stub'
    stub.mkdir()
    (stub / 'sudo').write_text('#!/bin/bash\necho unexpected-sudo >&2\nexit 99\n')
    (stub / 'sudo').chmod(0o755)
    script = 'set -euo pipefail\ninfo() { :; }; ok() { :; }; warn() { :; }; fail() { exit 1; }\nCYAN=; NC=; DIM=\n'
    script += f'SCRIPT_DIR={shlex.quote(str(REPO))}\nCLI_DIR={shlex.quote(str(destination))}\nCLI_DIR_EXPLICIT=true\n'
    result = subprocess.run(['bash', '-c', script + source[start:end]],
                            env={**os.environ, 'PATH': str(destination) + ':' + str(stub) + ':' + os.environ['PATH']},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'unexpected-sudo' not in result.stderr
    assert (destination / 'afterwords').is_symlink()
    assert (destination / 'afterwords').resolve() == REPO / 'afterwords.sh'


@pytest.mark.parametrize('size', ['0.6B', '1.7B'])
def test_qwen_load_uses_fixed_hub_revision(monkeypatch, size):
    from types import ModuleType
    tts = ModuleType('mlx_audio.tts')
    calls = []
    tts.load_model = lambda model_id, **kwargs: calls.append((model_id, kwargs)) or object()
    monkeypatch.setitem(sys.modules, 'mlx_audio', ModuleType('mlx_audio'))
    monkeypatch.setitem(sys.modules, 'mlx_audio.tts', tts)
    backend = Qwen3Backend(size)
    backend.load()
    assert calls == [(backend.model_id, {'revision': backend.model_revision})]
    assert len(backend.model_revision) == 40
    assert backend._loaded is True


@pytest.mark.parametrize('version,unlocked,expected', [('311', False, 0), ('314', False, 0), ('999', False, 1), ('999', True, 0)])
def test_baseline_installer_requires_known_lock_unless_explicitly_unlocked(tmp_path, version, unlocked, expected):
    source = (REPO / 'setup.sh').read_text()
    start = source.index('VENV_VERSION=$(python3')
    end = source.index('\nif $CLONING;', start)
    script = 'set -euo pipefail\nwarn() { :; }; fail() { exit 1; }\n'
    script += f'python3() {{ echo {version}; }}\n'
    script += 'pip() { printf "%s\\n" "$@"; }\n'
    script += f'UNLOCKED={str(unlocked).lower()}\n'
    result = subprocess.run(['bash', '-c', script + source[start:end]],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == expected, result.stderr
    if expected == 0:
        assert ('--require-hashes' in result.stdout) is (not unlocked)
        assert ('requirements.txt' in result.stdout) is unlocked


@pytest.mark.parametrize('minor,unlocked,allowed', [(11, False, True), (14, False, True), (15, False, False), (15, True, True), (10, True, False)])
def test_setup_python_gate_rejects_unsupported_version_before_mutation(tmp_path, minor, unlocked, allowed):
    import shlex
    source = (REPO / 'setup.sh').read_text()
    start = source.index('# Python check')
    end = source.index('PY_ARCH=', start)
    # Execute the actual shell gate using a Python wrapper that reports a simulated version.
    wrapper = tmp_path / 'python3'
    wrapper.write_text(f'''#!{sys.executable}
import sys
from collections import namedtuple
code = sys.argv[2]
sys.argv = ['-c'] + sys.argv[3:]
sys.version_info = namedtuple('Version', 'major minor micro releaselevel serial')(3, {minor}, 0, 'final', 0)
exec(code)
''')
    wrapper.chmod(0o755)
    script = f'UNLOCKED={str(unlocked).lower()}\nCYAN=; NC=; RED=\n'
    script += 'ok() { :; }; fail() { echo "$*" >&2; exit 1; }\n'
    result = subprocess.run(['bash', '-c', script + source[start:end]],
                            env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH']},
                            capture_output=True, text=True)
    assert (result.returncode == 0) is allowed, result.stderr
    assert list(tmp_path.iterdir()) == [wrapper]
    if minor == 15 and not unlocked:
        assert 'experimental --unlocked' in result.stderr


@pytest.mark.parametrize('server_path,owned', [(str(REPO / 'server.py'), True), ('/foreign/server.py', False)])
def test_cli_owns_framework_python_only_for_this_checkout(tmp_path, server_path, owned):
    stub = tmp_path / 'bin'
    stub.mkdir()
    scripts = {
        'lsof': 'echo 987654',
        'ps': f'echo "/opt/homebrew/Python.framework/Resources/Python.app/Contents/MacOS/Python {server_path} --allow-reload"',
        'curl': "echo '{\"service\":\"afterwords\",\"ready\":true,\"voices\":[],\"loaded_backends\":{}}'",
    }
    for name, content in scripts.items():
        path = stub / name
        path.write_text('#!/bin/bash\n' + content + '\n')
        path.chmod(0o755)
    result = subprocess.run(['bash', str(REPO / 'afterwords.sh'), 'status'],
                            env={**os.environ, 'PATH': str(stub) + ':' + os.environ['PATH'],
                                 'AFTERWORDS_NO_LAUNCHCTL': '1'}, capture_output=True, text=True)
    assert (result.returncode == 0) is owned, result.stdout + result.stderr
    assert ('conflict' in result.stdout) is (not owned)
