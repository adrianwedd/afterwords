"""Read-only preflight must fail closed on unknown/foreign port owners."""
import importlib.util
import io
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def preflight():
    spec = importlib.util.spec_from_file_location('setup_preflight', REPO / 'scripts/setup-preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('scenario', ['missing', 'timeout', 'error', 'foreign', 'spoofed', 'multiple'])
def test_port_ownership_failure_is_not_reported_free(preflight, monkeypatch, tmp_path, scenario):
    def run(argv, **kwargs):
        if argv[0] == 'lsof':
            if scenario == 'missing':
                raise FileNotFoundError('lsof')
            if scenario == 'timeout':
                raise subprocess.TimeoutExpired(argv, 5)
            if scenario == 'error':
                return SimpleNamespace(returncode=2, stdout='', stderr='failed')
            return SimpleNamespace(returncode=0, stdout='11 12' if scenario == 'multiple' else '11', stderr='')
        path = tmp_path / 'server.py' if scenario in ('spoofed', 'multiple') and argv[2] == '11' else Path('/foreign/server.py')
        return SimpleNamespace(returncode=0, stdout=f'/usr/bin/python3 {path}', stderr='')
    monkeypatch.setattr(preflight.subprocess, 'run', run)
    monkeypatch.setattr(preflight.urllib.request, 'urlopen', lambda *a, **k: io.StringIO('{"service":"other"}'))
    assert preflight.check_port(tmp_path)


def test_port_free_requires_expected_lsof_exit(preflight, monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr=''))
    assert preflight.check_port(tmp_path) == []


def test_existing_service_in_checkout_with_spaces(preflight, monkeypatch, tmp_path):
    repo = tmp_path / 'A & B checkout'
    def run(argv, **kwargs):
        if argv[0] == 'lsof':
            return SimpleNamespace(returncode=0, stdout='11', stderr='')
        return SimpleNamespace(returncode=0, stdout=f'{repo}/.venv/bin/python3 {repo}/server.py --allow-reload', stderr='')
    monkeypatch.setattr(preflight.subprocess, 'run', run)
    monkeypatch.setattr(preflight.urllib.request, 'urlopen', lambda *a, **k: io.StringIO('{"service":"afterwords"}'))
    assert preflight.check_port(repo) == []


def test_cli_directory_checked_before_installation(preflight, monkeypatch, tmp_path):
    destination = tmp_path / 'missing/bin'
    monkeypatch.setenv('PATH', str(destination))
    assert preflight.check_cli_destination(destination, tmp_path) == []
    assert not destination.exists()
    monkeypatch.setenv('PATH', '/usr/bin')
    assert preflight.check_cli_destination(destination, tmp_path)


def test_cli_destination_does_not_overwrite_other_installation(preflight, monkeypatch, tmp_path):
    monkeypatch.setenv('PATH', str(tmp_path))
    (tmp_path / 'afterwords').write_text('foreign CLI')
    assert preflight.check_cli_destination(tmp_path, tmp_path)


@pytest.mark.parametrize('version,unlocked,allowed', [
    ((3, 10), False, False), ((3, 10), True, False),
    ((3, 11), False, True), ((3, 12), False, True),
    ((3, 13), False, True), ((3, 14), False, True),
    ((3, 15), False, False), ((3, 15), True, True),
])
def test_python_policy_matches_locked_installer(preflight, version, unlocked, allowed):
    assert (preflight.check_python_version(version, unlocked) == []) is allowed


def test_preflight_rejects_reusable_unsupported_venv(preflight, monkeypatch, tmp_path):
    venv = tmp_path / '.venv/bin/python3'
    venv.parent.mkdir(parents=True)
    venv.write_text('placeholder')
    monkeypatch.setattr(preflight.sys, 'version_info', (3, 14))
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='[3, 15]'))
    errors = preflight.check_install_python(tmp_path)
    assert any('existing venv' in error for error in errors)
    assert preflight.check_install_python(tmp_path, unlocked=True) == []
