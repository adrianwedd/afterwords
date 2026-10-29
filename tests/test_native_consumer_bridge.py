"""Native ownership is task local; the actual consumer honours mute and leases."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('afterwords_native', REPO/'hermes/afterwords_native.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_ownership_does_not_leak_between_callers():
    def check(native):
        if native:
            return bridge.native_synthesis(bridge.command_environment)
        return bridge.command_environment()
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(check, [True, False]*20))
    for native, row in zip([True, False]*20, rows):
        assert row == ({'AFTERWORDS_TTS_CALLER': 'native', 'HERMES_SESSION_PLATFORM': 'cli',
                        'HERMES_SESSION_SOURCE': 'cli'} if native else {})
    assert bridge.command_environment() == {}


def test_consumer_releases_lease_on_playback_error(tmp_path):
    lock, pid = tmp_path/'play.lock', tmp_path/'play.pid'
    def fail(path):
        assert lock.is_dir() and pid.read_text() == str(os.getpid())
        raise RuntimeError('captured consumer failure')
    with pytest.raises(RuntimeError):
        bridge.native_playback(fail, 'artifact.wav', mute=tmp_path/'mute', lock=lock, pid=pid)
    assert not lock.exists() and not pid.exists()


@pytest.mark.parametrize('mode', ['audible', 'muted', 'occupied'])
def test_staged_installed_sentence_consumer(tmp_path, mode):
    root = Path.home()/'.hermes/hermes-agent'
    py = next(iter(sorted((Path.home()/'.hermes/tools').glob('python-3.*/bin/python3'))), None)
    sp = next(iter(sorted((Path.home()/'.hermes/installs').glob('*/environments/*/venv/lib/python3.*/site-packages'))), None)
    if not (py and sp and root.is_dir()):
        pytest.skip('installed Hermes runtime unavailable')
    staged = tmp_path/'staged'
    subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                    '--hermes-root', str(root), '--out', str(staged)], check=True, capture_output=True)
    driver = tmp_path/'driver.py'
    driver.write_text(r'''
import importlib.util, json, os, sys, threading
from pathlib import Path
from types import SimpleNamespace
root, sp, staged, directory, mode = sys.argv[1:]
sys.path[:0] = [staged, root, sp]
import afterwords_native as bridge
from tools import voice_mode
spec = importlib.util.spec_from_file_location('tools.tts_command_provider', Path(staged)/'tools/tts_command_provider.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
spec = importlib.util.spec_from_file_location('tools.tts_tool_speaker', Path(staged)/'tools/tts_tool_speaker.py')
speaker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speaker)
directory = Path(directory)
lock, pid, mute = directory/'lock', directory/'pid', directory/'mute'
os.environ.update(AFTERWORDS_PLAY_LOCK=str(lock), AFTERWORDS_PLAY_PID=str(pid), AFTERWORDS_MUTE_FILE=str(mute))
if mode == 'muted': mute.touch()
if mode == 'occupied':
    lock.mkdir(); pid.write_text(str(os.getpid()))
plays=[]; calls=[]
def tool(**kwargs):
    calls.append(bridge.command_environment())
    result=provider.run_command_provider('printf \'%s:%s\' \"$AFTERWORDS_TTS_CALLER\" \"$HERMES_SESSION_SOURCE\"', timeout=5)
    assert result.returncode==0 and result.stdout=='native:cli', result.stderr
    path=Path(kwargs['output_path']); path.write_bytes(b'captured speech artifact')
    return json.dumps({'success':True, 'file_path':str(path)})
def play(path):
    assert lock.is_dir() and pid.read_text()==str(os.getpid())
    plays.append(Path(path).read_bytes().decode())
    return True
speaker._origin=lambda:SimpleNamespace(text_to_speech_tool=tool)
voice_mode.play_audio_file=play
original=bridge.native_playback
bridge.native_playback=lambda function,path:original(function,path,timeout=.1)
pipeline=speaker._SyncSentencePipeline(threading.Event())
pipeline.speak('First captured sentence.')
pipeline.speak('Second captured sentence.')
pipeline.close()
assert len(calls)==2 and all(row.get('AFTERWORDS_TTS_CALLER')=='native' for row in calls)
assert len(plays)==(2 if mode=='audible' else 0)
assert bridge.command_environment()=={}
assert lock.exists()==(mode=='occupied')
assert pid.exists()==(mode=='occupied')
print(json.dumps({'mode':mode,'syntheses':len(calls),'playback_calls':len(plays),'external_messages_sent':0}))
''')
    result = subprocess.run([str(py), '-I', str(driver), str(root), str(sp), str(staged), str(tmp_path), mode],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])['playback_calls'] == (2 if mode=='audible' else 0)


@pytest.mark.parametrize('variant', ['m5', 'studio'])
def test_preparation_refuses_source_drift_without_creating_output(tmp_path, variant):
    root = tmp_path/'hermes'
    (root/'tools').mkdir(parents=True)
    source = root/'tools/tts_command_provider.py'
    source.write_text('# unrelated or concurrently changed source\n')
    output = tmp_path/'staged'
    result = subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                             '--variant', variant, '--hermes-root', str(root), '--out', str(output)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'installed source changed' in result.stderr
    assert not output.exists()
    assert source.read_text() == '# unrelated or concurrently changed source\n'


@pytest.mark.parametrize('pid_file', [False, True])
def test_empty_stale_lease_is_recovered_after_recheck(tmp_path, pid_file):
    lock, pid = tmp_path/'lock', tmp_path/'pid'
    lock.mkdir()
    if pid_file:
        pid.touch()
    calls = []
    bridge.native_playback(calls.append, 'speech', mute=tmp_path/'mute', lock=lock, pid=pid, timeout=.2)
    assert calls == ['speech']
    assert not lock.exists() and not pid.exists()


def test_owner_publishing_pid_during_recheck_is_preserved(tmp_path, monkeypatch):
    lock, pid = tmp_path/'lock', tmp_path/'pid'
    lock.mkdir()
    monkeypatch.setattr(bridge.time, 'sleep', lambda seconds: pid.write_text(str(os.getpid())))
    calls = []
    bridge.native_playback(calls.append, 'speech', mute=tmp_path/'mute', lock=lock, pid=pid, timeout=0)
    assert not calls
    assert lock.exists() and pid.read_text() == str(os.getpid())

def _stage_sandbox(tmp_path, staged, root):
    """Shadow only the four patched consumers, keep every sibling module beside them.

    A staged tree has no ``__init__.py``, so a bare ``sys.path`` entry loses to the real package.
    Mirror each package as symlinks to the installed tree and replace just the staged files.
    """
    sandbox = tmp_path/'sandbox'
    patched = {rel for rel in
               ('tools/tts_command_provider.py', 'tools/tts_tool_speaker.py',
                'hermes_cli/cli_voice_mixin.py', 'hermes_cli/voice.py')}
    for package in ('tools', 'hermes_cli'):
        (sandbox/package).mkdir(parents=True)
        for child in (root/package).iterdir():
            link = sandbox/package/child.name
            rel = f'{package}/{child.name}'
            if rel in patched:
                link.write_bytes((staged/rel).read_bytes())
            else:
                link.symlink_to(child)
    return sandbox


# --- bridge absence and incompleteness must fail before any audio work -------------------

GUARD_DRIVER = r"""
import json, sys
root, staged, sp, mode, lock = sys.argv[1:6]
sys.path[:0] = [staged, root, sp]
import hermes_cli.voice as voice
calls = {'synth': 0, 'play': 0}
def synth(**kwargs):
    calls['synth'] += 1
    return json.dumps({'success': True, 'file_path': kwargs['output_path']})
def play(path):
    calls['play'] += 1
    return True
voice.text_to_speech_tool = synth
voice.play_audio_file = play
if mode == 'absent':
    sys.modules['afterwords_native'] = None
else:
    import types
    sys.modules['afterwords_native'] = types.SimpleNamespace(native_synthesis=lambda *a, **k: None)
try:
    voice._speak_whole_file('Bridge probe.')
except RuntimeError as exc:
    calls['error'] = str(exc)
else:
    calls['error'] = None
calls['lock'] = __import__('pathlib').Path(lock).exists()
print(json.dumps(calls))
"""


def _guard_probe(tmp_path, mode):
    root = Path.home()/'.hermes/hermes-agent'
    py = next(iter(sorted((Path.home()/'.hermes/tools').glob('python-3.*/bin/python3'))), None)
    sp = next(iter(sorted((Path.home()/'.hermes/installs').glob('*/environments/*/venv/lib/python3.*/site-packages'))), None)
    if not (py and sp and root.is_dir()):
        pytest.skip('installed Hermes runtime unavailable')
    staged = tmp_path/'staged'
    subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                    '--hermes-root', str(root), '--out', str(staged)], check=True, capture_output=True)
    sandbox = _stage_sandbox(tmp_path, staged, root)
    driver = tmp_path/'guard.py'
    driver.write_text(GUARD_DRIVER)
    lock = tmp_path/'lock'
    result = subprocess.run([str(py), '-I', str(driver), str(root), str(sandbox), str(sp), mode, str(lock)],
                            capture_output=True, text=True, timeout=60,
                            env={**__import__('os').environ, 'AFTERWORDS_PLAY_LOCK': str(lock),
                                 'AFTERWORDS_PLAY_PID': str(tmp_path/'pid')})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def test_absent_bridge_fails_before_synthesis_or_playback(tmp_path):
    """A missing shim must stop the consumer before it synthesises or plays anything."""
    row = _guard_probe(tmp_path, 'absent')
    assert row['error'] and 'afterwords_native is not importable' in row['error']
    assert row['error'].count('prepare-hermes-native.py') == 1
    assert row['synth'] == 0 and row['play'] == 0 and row['lock'] is False


def test_incomplete_bridge_fails_before_playback(tmp_path):
    """A shim that lost native_playback is a changed dependency, not a degraded one."""
    row = _guard_probe(tmp_path, 'incomplete')
    assert row['error'] and 'afterwords_native is missing' in row['error']
    assert 'native_playback' in row['error'] and 'command_environment' in row['error']
    assert row['synth'] == 0 and row['play'] == 0 and row['lock'] is False


SENTENCE_GUARD_DRIVER = r"""
import json, sys, threading
from pathlib import Path
from types import SimpleNamespace
root, staged, sp = sys.argv[1:4]
sys.path[:0] = [staged, root, sp]
import types
sys.modules['afterwords_native'] = None
from tools import tts_tool_speaker as speaker
calls = {'synth': 0, 'play': 0}
def tool(**kwargs):
    calls['synth'] += 1
    return json.dumps({'success': True, 'file_path': kwargs['output_path']})
speaker._origin = lambda: SimpleNamespace(text_to_speech_tool=tool)
import tools.voice_mode as voice_mode
def play(path):
    calls['play'] += 1
    return True
voice_mode.play_audio_file = play
pipeline = speaker._SyncSentencePipeline(threading.Event())
pipeline.speak('Sentence without a bridge.')
pipeline.close()
print(json.dumps(calls))
"""


def test_sentence_pipeline_never_plays_without_the_bridge(tmp_path):
    """The pipeline swallows into a log line upstream; the invariant is that it must not play."""
    root = Path.home()/'.hermes/hermes-agent'
    py = next(iter(sorted((Path.home()/'.hermes/tools').glob('python-3.*/bin/python3'))), None)
    sp = next(iter(sorted((Path.home()/'.hermes/installs').glob('*/environments/*/venv/lib/python3.*/site-packages'))), None)
    if not (py and sp and root.is_dir()):
        pytest.skip('installed Hermes runtime unavailable')
    staged = tmp_path/'staged'
    subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                    '--hermes-root', str(root), '--out', str(staged)], check=True, capture_output=True)
    sandbox = _stage_sandbox(tmp_path, staged, root)
    driver = tmp_path/'sentence_guard.py'
    driver.write_text(SENTENCE_GUARD_DRIVER)
    result = subprocess.run([str(py), '-I', str(driver), str(root), str(sandbox), str(sp)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout.splitlines()[-1])
    assert row == {'synth': 0, 'play': 0}
    assert 'afterwords_native is not importable' in result.stderr


# --- preparation and checking across installed states -----------------------------------


def test_preparation_stages_over_a_superseded_installation(tmp_path):
    """The live checkout carries a patch already; staging must not need it to be pristine."""
    root = Path.home()/'.hermes/hermes-agent'
    if not (root/'hermes_cli/voice.py').is_file():
        pytest.skip('installed Hermes checkout unavailable')
    staged = tmp_path/'staged'
    subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                    '--hermes-root', str(root), '--out', str(staged)], check=True, capture_output=True)
    manifest = json.loads((REPO/'hermes/patches/native-command-playback.json').read_text())
    for rel, hashes in manifest['files'].items():
        import hashlib
        assert hashlib.sha256((staged/rel).read_bytes()).hexdigest() == hashes['after_sha256']
    assert '_afterwords_bridge' in (staged/'hermes_cli/voice.py').read_text()


def test_check_reports_current_superseded_and_changed(tmp_path):
    """--check is the post-update gate: it names the state instead of guessing."""
    root = Path.home()/'.hermes/hermes-agent'
    if not (root/'hermes_cli/voice.py').is_file():
        pytest.skip('installed Hermes checkout unavailable')
    staged = tmp_path/'staged'
    subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                    '--hermes-root', str(root), '--out', str(staged)], check=True, capture_output=True)
    fake = tmp_path/'fake-root'
    for rel in json.loads((REPO/'hermes/patches/native-command-playback.json').read_text())['files']:
        (fake/rel).parent.mkdir(parents=True, exist_ok=True)
        (fake/rel).write_bytes((staged/rel).read_bytes())
    (fake/'afterwords_native.py').write_bytes((staged/'afterwords_native.py').read_bytes())
    ok = subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                         '--hermes-root', str(fake), '--check'], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    assert json.loads(ok.stdout)['current'] is True
    with (fake/'hermes_cli/voice.py').open('a') as handle:
        handle.write('# local edit\n')
    bad = subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                          '--hermes-root', str(fake), '--check'], capture_output=True, text=True)
    assert bad.returncode == 1
    assert json.loads(bad.stdout)['files']['hermes_cli/voice.py'] == 'changed'
    superseded = subprocess.run([sys.executable, str(REPO/'scripts/prepare-hermes-native.py'),
                                 '--hermes-root', str(root), '--check'], capture_output=True, text=True)
    states = set(json.loads(superseded.stdout)['files'].values())
    assert states <= {'current', 'superseded', 'pristine'}, states
