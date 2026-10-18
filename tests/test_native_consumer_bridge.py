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
