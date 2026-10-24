"""Validate isolated service definitions and both tunnel transport choices."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('probe', [0, 255, 'timeout'])
def test_tunnel_selects_transport_without_changing_identity(monkeypatch, probe):
    module = load('expressive-m5-tunnel')
    monkeypatch.setattr('sys.argv', ['tunnel', '--peer', 'm5-tb', '--tailscale-ip', '100.114.8.87'])
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if '-G' in command:
            return SimpleNamespace(stdout='hostkeyalias m5\n')
        if probe == 'timeout':
            raise subprocess.TimeoutExpired(command, 15)
        return SimpleNamespace(returncode=probe)
    monkeypatch.setattr(module.subprocess, 'run', run)
    executed = []
    monkeypatch.setattr(module.os, 'execv', lambda path, command: executed.append(command))
    module.main()
    command = executed[0]
    assert command[-1] == 'm5-tb'
    assert 'StrictHostKeyChecking=yes' in command
    assert 'BatchMode=yes' in command
    assert '127.0.0.1:17862:127.0.0.1:7862' in command
    assert ('HostName=100.114.8.87' in command) == (probe != 0)


def test_fallback_rejects_lan_address():
    with pytest.raises(ValueError, match='Tailscale'):
        load('expressive-m5-tunnel').connection_args('m5-tb', '192.168.0.249')


def test_services_preserve_default_server_and_isolate_dependencies(tmp_path):
    plists = dict(load('prepare-expressive-services').service_plists(tmp_path, 'm5-tb', '100.114.8.87'))
    assert len(plists) == 3
    api = plists['net.afterwords.expressive.api']
    sidecar = plists['net.afterwords.expressive.sidecar']
    assert api['ProgramArguments'][3] == '7862'
    assert '7860' not in api['ProgramArguments']
    assert sidecar['ProgramArguments'][0].endswith('.venv-drama3/bin/python')
    assert api['ProgramArguments'][0].endswith('.venv/bin/python')
    # A cleared HF cache must cost a Qwen re-download, not a failed start.
    assert 'HF_HUB_OFFLINE' not in api['EnvironmentVariables']
    for config in plists.values():
        assert config['KeepAlive'] is True
        assert config['ThrottleInterval'] == 10
        assert 'setup.sh' not in ' '.join(config['ProgramArguments'])


def test_expressive_api_leaves_caller_authentication_off():
    # The API is reachable only on loopback and the private network; callers
    # such as lulzbench send no credential, so the gate stays opt-in.
    plists = dict(load('prepare-expressive-services').service_plists(ROOT, 'm5-tb', '100.114.8.87'))
    assert 'AFTERWORDS_REQUIRE_EXPRESSIVE_AUTH' not in plists['net.afterwords.expressive.api']['EnvironmentVariables']
