"""Regression coverage for session identity, split records and durable delivery."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from watcher.queue import enqueue
from watcher.state import load, save

REPO = Path(__file__).resolve().parents[1]


def module(agent):
    spec = importlib.util.spec_from_file_location(agent, REPO / agent / f'afterwords-{agent}-watch.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def record(text):
    return json.dumps({'type': 'response_item', 'payload': {'type': 'message',
        'role': 'assistant', 'phase': 'final_answer', 'content': [
        {'type': 'output_text', 'text': text}]}}, ensure_ascii=False).encode() + b'\n'


def meta(session, cwd):
    # Sanitized real rollout session_meta topology; filename deliberately has no
    # identity so a filename-derived session cannot accidentally pass.
    return json.dumps({'type': 'session_meta', 'payload': {'id': session,
        'cwd': cwd, 'originator': 'codex_cli_rs', 'cli_version': '0.0.test',
        'source': 'cli', 'model_provider': 'openai'}}).encode() + b'\n'


@pytest.mark.parametrize('split', [1, 37, -2, -1])
def test_partial_record_survives_restart_and_emits_once(tmp_path, split):
    codex = module('codex')
    path = tmp_path / 'unexpected-name.jsonl'
    path.write_bytes(meta('session-a', '/project/a'))
    state = {}; events = []
    codex.poll(path, state, lambda *event: events.append(event))
    line = record('Café acceptance.')
    if split == 37:
        split = line.index('é'.encode()) + 1  # split within a UTF-8 codepoint
    with path.open('ab') as f: f.write(line[:split])
    codex.poll(path, state, lambda *event: events.append(event))
    assert not events
    statefile = tmp_path / 'state.json'; save(statefile, state)
    state = load(statefile)  # termination and restart between chunks
    with path.open('ab') as f: f.write(line[split:])
    codex.poll(path, state, lambda *event: events.append(event))
    save(statefile, state)
    codex.poll(path, load(statefile), lambda *event: events.append(event))
    assert len(events) == 1
    assert events[0][0] == 'session-a'
    assert events[0][2:] == ('/project/a', 'Café acceptance.')


def test_sessions_separate_identical_answers_and_queue_receipts(tmp_path):
    codex = module('codex'); state = {}; events = []
    for session in ('a', 'b'):
        path = tmp_path / f'{session}.jsonl'
        path.write_bytes(meta(session, f'/project/{session}') + record('Same answer.'))
        codex.poll(path, state, lambda *event: events.append(event))
    assert [x[0] for x in events] == ['a', 'b']
    targets = [enqueue(tmp_path, 'codex', *event) for event in events]
    assert targets[0].parent != targets[1].parent
    for event, target in zip(events, targets):
        assert json.loads(target.read_text())['agent'] == 'codex'
        target.rename(target.with_suffix('.claimed'))
        enqueue(tmp_path, 'codex', *event)
        assert not target.exists()
        target.with_suffix('.claimed').rename(target.with_suffix('.done'))
        enqueue(tmp_path, 'codex', *event)
        assert not target.exists()


def test_enqueue_failure_does_not_advance_and_crash_retry_is_idempotent(tmp_path):
    codex = module('codex'); path = tmp_path / 'rollout.jsonl'; state = {}
    path.write_bytes(meta('a', '/a') + record('A durable answer.'))
    def fail(*event): raise OSError('enqueue failed')
    with pytest.raises(OSError): codex.poll(path, state, fail)
    assert state[str(path)]['offset'] == len(meta('a', '/a'))
    def deliver(*event): enqueue(tmp_path, 'codex', *event)
    # Simulate queue publication followed by termination before saving offsets.
    before = json.loads(json.dumps(state))
    codex.poll(path, state, deliver)
    codex.poll(path, before, deliver)
    assert len(list((tmp_path / 'queues').rglob('*.json'))) == 1


def test_truncation_resets_offset_and_missing_identity_fails_closed(tmp_path):
    codex = module('codex'); path = tmp_path / 'rollout.jsonl'; state = {}; events = []
    path.write_bytes(meta('a', '/a') + record('A' * 1000))
    codex.poll(path, state, lambda *e: events.append(e))
    path.write_bytes(meta('b', '/b') + record('B'))
    codex.poll(path, state, lambda *e: events.append(e))
    with path.open('ab') as f: f.write(record('C'))
    codex.poll(path, state, lambda *e: events.append(e))
    assert [e[3] for e in events] == ['A' * 1000, 'B', 'C']
    other = tmp_path / 'no-meta.jsonl'; other.write_bytes(record('Unsafe identity'))
    with pytest.raises(ValueError): codex.poll(other, state, lambda *e: events.append(e))


def database(path):
    con = sqlite3.connect(path)
    con.executescript('CREATE TABLE session_v2 (id TEXT PRIMARY KEY, directory TEXT); '
        'CREATE TABLE session_message (id TEXT PRIMARY KEY, session_id TEXT, type TEXT, seq INTEGER, data TEXT);'
        "INSERT INTO session_v2 VALUES ('s', '/project');")
    return con


def assistant(text, completed=False):
    return json.dumps({'time': {'created': 1, 'completed': 2 if completed else None},
                      'content': [{'type': 'text', 'text': text}]})


def test_opencode_waits_for_completion_and_delivers_each_message(tmp_path):
    opencode = module('opencode'); db = tmp_path / 'db.sqlite'; con = database(db)
    con.execute('INSERT INTO session_message VALUES (?, ?, ?, ?, ?)',
                ('m1', 's', 'assistant', 1, assistant('Streaming'))); con.commit()
    state = {}; events = []
    opencode.poll(db, state, lambda *e: events.append(e))  # installation baseline
    assert not events
    con.execute('UPDATE session_message SET data=? WHERE id=?', (assistant('First.', True), 'm1'))
    con.execute('INSERT INTO session_message VALUES (?, ?, ?, ?, ?)',
                ('m2', 's', 'assistant', 2, assistant('Second.', True))); con.commit()
    def fail(*event): raise OSError('hook missing')
    with pytest.raises(OSError): opencode.poll(db, state, fail)
    assert state['seen'] == []
    opencode.poll(db, state, lambda *e: events.append(e))
    opencode.poll(db, json.loads(json.dumps(state)), lambda *e: events.append(e))
    assert [(e[1], e[3]) for e in events] == [('m1', 'First.'), ('m2', 'Second.')]
    con.close()


def test_fresh_install_skips_completed_history_but_follows_partial(tmp_path):
    codex = module('codex'); path = tmp_path / 'rollout.jsonl'; state = {}; events = []
    line = record('After installation.')
    path.write_bytes(meta('a', '/a') + record('Old history.') + line[:-1])
    codex.poll(path, state, lambda *e: events.append(e), fresh=True)
    assert not events
    with path.open('ab') as f: f.write(b'\n')
    codex.poll(path, state, lambda *e: events.append(e))
    assert [e[3] for e in events] == ['After installation.']


def test_installer_lifecycle_isolated_home_and_boot_registration(tmp_path, monkeypatch):
    import plistlib
    from watcher import manage
    home = tmp_path / 'fresh home'; calls = []
    def control(*args, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='state = running\n', stderr='')
    monkeypatch.setattr(manage, 'control', control)
    options = ['all', '--home', str(home), '--label-prefix', 'test.afterwords',
               '--sessions', str(home / 'sessions'), '--db', str(home / 'opencode.db')]
    for action in ('install', 'install', 'restart', 'status'):
        assert manage.main([action, *options]) == 0
    root = home / 'Library/Application Support/Afterwords/watchers'
    for agent in ('codex', 'opencode'):
        plist = home / 'Library/LaunchAgents' / f'test.afterwords-{agent}-watch.plist'
        config = plistlib.loads(plist.read_bytes())
        assert config['RunAtLoad'] and config['KeepAlive']
        assert config['EnvironmentVariables']['HOME'] == str(home)
        assert Path(config['ProgramArguments'][1]).is_file()
    assert (root / 'runtime/opencode/tts-hook-opencode.sh').is_file()
    assert not (home / '.claude/settings.json').exists()
    assert not (home / '.afterwords-server').exists()
    assert not list((root / 'runtime').rglob('*.wav'))
    assert not (root / 'runtime/.afterwords').exists()
    save(root / 'codex.json', {'private-progress': 12})
    assert manage.main(['uninstall', *options]) == 0
    assert not (root / 'runtime').exists()
    assert load(root / 'codex.json') == {'private-progress': 12}
    assert manage.main(['uninstall', *options]) == 0
    assert all('tts-server' not in ' '.join(call) for call in calls)


def test_opencode_hook_runs_without_machine_local_helpers(tmp_path):
    # Install copied, explicitly enumerated runtime in a fresh HOME, stub only
    # the audio worker so this test cannot touch the live synthesis endpoint.
    import os
    import shutil
    from watcher.manage import FILES
    runtime = tmp_path / 'runtime'
    for relative in FILES:
        dest = runtime / relative; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, dest)
    (runtime / '.claude/hooks/codex-tts-worker.sh').write_text('#!/bin/bash\nexit 0\n')
    state = tmp_path / 'state'
    env = {**os.environ, 'HOME': str(tmp_path), 'AFTERWORDS_WATCH_STATE': str(state),
           'AFTERWORDS_PYTHON': sys.executable}
    for _ in range(2):
        result = subprocess.run(['bash', str(runtime / 'opencode/tts-hook-opencode.sh'),
            'session-1', 'message-1', '/project'], input='An OpenCode answer.',
            capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
    queued = list(state.rglob('event-*.json'))
    assert len(queued) == 1
    assert json.loads(queued[0].read_text()) == {
        'agent': 'opencode', 'project_dir': '/project', 'text': 'An OpenCode answer.'}


def test_sanitized_real_metadata_and_completed_message_fixtures(tmp_path):
    fixture = REPO / 'tests/fixtures/desktop-watchers'
    path = tmp_path / 'filename-is-not-a-session.jsonl'
    meta_bytes = (fixture / 'codex-session-meta.json').read_bytes()
    # Pretty fixture serialized to the actual one-record-per-line format.
    path.write_bytes(json.dumps(json.loads(meta_bytes)).encode() + b'\n' + record('Fixture answer.'))
    events = []; module('codex').poll(path, {}, lambda *e: events.append(e))
    assert events[0][0] == '00000000-0000-4000-8000-000000000001'
    data = json.loads((fixture / 'opencode-completed-message.json').read_text())
    con = database(tmp_path / 'fixture.db')
    con.execute('INSERT INTO session_message VALUES (?, ?, ?, ?, ?)',
        ('fixture-message', 's', 'assistant', 1, json.dumps(data))); con.commit()
    events = []; module('opencode').poll(tmp_path / 'fixture.db', {'seen': []}, lambda *e: events.append(e))
    assert events[0][3] == 'A sanitized OpenCode answer.'
    con.close()


def worker_stubs(tmp_path):
    import os
    bindir = tmp_path / 'bin'; bindir.mkdir()
    stubs = {
        'stat': '#!/bin/bash\ncase "$1" in -f%u) id -u ;; -f%z) wc -c < "$2" ;; esac\n',
        'curl': '#!/bin/bash\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then out="$2"; shift; fi; shift; done\n[ -z "${out:-}" ] || head -c 2048 /dev/zero > "$out"\n',
        'afplay': '#!/bin/bash\nexit 0\n',
        'lame': '#!/bin/bash\ncp "${@: -2:1}" "${@: -1}"\n',
    }
    for name, source in stubs.items():
        path = bindir / name; path.write_text(source); path.chmod(0o755)
    home = tmp_path / 'home'; home.mkdir(); (home / '.afterwords').write_text('codex: testvoice\n')
    queue = tmp_path / 'queue'; queue.mkdir()
    env = {**os.environ, 'HOME': str(home), 'PATH': f"{bindir}:{os.environ['PATH']}",
           'CODEX_THREAD_ID': 'desktop-regression', 'AFTERWORDS_QUEUE_DIR': str(queue),
           'AFTERWORDS_RELIABLE_QUEUE': '1', 'AFTERWORDS_ARCHIVE_DIR': str(tmp_path / 'archive'),
           'AFTERWORDS_PLAY_LOCK': str(tmp_path / 'play.lock'),
           'AFTERWORDS_PLAY_PID': str(tmp_path / 'play.pid')}
    item = queue / 'event-test.json'
    item.write_text(json.dumps({'agent': 'codex', 'project_dir': str(home), 'text': 'A speech probe.'}))
    return env, queue, bindir


def test_worker_failure_retains_claim_for_retry_then_commits_receipt(tmp_path):
    env, queue, bindir = worker_stubs(tmp_path)
    (bindir / 'curl').write_text('#!/bin/bash\nexit 7\n')
    worker = REPO / '.claude/hooks/codex-tts-worker.sh'
    result = subprocess.run(['bash', str(worker)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert (queue / 'event-test.claimed').exists()
    assert not (queue / 'event-test.done').exists()
    (bindir / 'curl').write_text('#!/bin/bash\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then out="$2"; shift; fi; shift; done\n[ -z "${out:-}" ] || head -c 2048 /dev/zero > "$out"\n')
    result = subprocess.run([sys.executable, '-m', 'watcher.drain', str(worker), str(queue)],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (queue / 'event-test.done').exists()
    assert len(list((tmp_path / 'archive').glob('*.mp3'))) == 1


def test_worker_encoder_failure_does_not_commit_done(tmp_path):
    env, queue, bindir = worker_stubs(tmp_path)
    (bindir / 'lame').write_text('#!/bin/bash\nexit 1\n')
    result = subprocess.run(['bash', str(REPO / '.claude/hooks/codex-tts-worker.sh')],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert (queue / 'event-test.claimed').exists()
    assert not (queue / 'event-test.done').exists()


def test_actual_watcher_termination_between_writer_chunks(tmp_path):
    import os
    import shutil
    import time
    from watcher.manage import FILES
    runtime = tmp_path / 'runtime'
    for relative in FILES:
        dest = runtime / relative; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, dest)
    (runtime / '.claude/hooks/codex-tts-worker.sh').write_text('#!/bin/bash\nexit 0\n')
    sessions = tmp_path / 'sessions/2026/01/01'; sessions.mkdir(parents=True)
    path = sessions / 'rollout-ambiguous.jsonl'
    path.write_bytes(meta('restart-fixture', '/test/project'))
    root = tmp_path / 'state'
    env = {**os.environ, 'HOME': str(tmp_path), 'AFTERWORDS_WATCH_STATE': str(root),
           'AFTERWORDS_PYTHON': sys.executable}
    cmd = [sys.executable, str(runtime / 'codex/afterwords-codex-watch.py'), '--sessions', str(tmp_path / 'sessions')]
    subprocess.run([*cmd, '--once'], env=env, check=True, capture_output=True)
    line = record('A complete answer survives termination.')
    with path.open('ab') as stream: stream.write(line[:50])
    process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        time.sleep(.2)
        assert process.poll() is None
    finally:
        process.terminate(); process.communicate(timeout=5)
    with path.open('ab') as stream: stream.write(line[50:])
    for _ in range(2):
        subprocess.run([*cmd, '--once'], env=env, check=True, capture_output=True)
    queued = list(root.rglob('event-*.json'))
    assert len(queued) == 1
    assert json.loads(queued[0].read_text())['text'] == 'A complete answer survives termination.'


def test_worker_termination_preserves_claim_and_releases_drain_lock(tmp_path):
    import os
    import signal
    import time
    env, queue, bindir = worker_stubs(tmp_path)
    marker = tmp_path / 'synthesis-started'
    (bindir / 'curl').write_text(f'#!/bin/bash\ntouch "{marker}"\nsleep 30\n')
    worker = REPO / '.claude/hooks/codex-tts-worker.sh'
    cmd = [sys.executable, '-m', 'watcher.drain', str(worker), str(queue)]
    process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists()
        assert (queue / 'event-test.claimed').exists()
        assert not (queue / 'event-test.done').exists()
    finally:
        os.killpg(process.pid, signal.SIGTERM); process.communicate(timeout=5)
    (bindir / 'curl').write_text('#!/bin/bash\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then out="$2"; shift; fi; shift; done\n[ -z "${out:-}" ] || head -c 2048 /dev/zero > "$out"\n')
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (queue / 'event-test.done').exists()


def test_initial_baseline_crash_does_not_replay_unscanned_history(tmp_path, monkeypatch):
    codex = module('codex'); sessions = tmp_path / 'sessions/2026/01/01'; sessions.mkdir(parents=True)
    for session in ('a', 'b'):
        (sessions / f'rollout-{session}.jsonl').write_bytes(meta(session, '/test') + record('Old history.'))
    root = tmp_path / 'state'; root.mkdir()
    monkeypatch.setattr(codex, 'state_root', lambda: root)
    monkeypatch.setattr(codex, 'resume', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['watcher', '--once', '--sessions', str(tmp_path / 'sessions')])
    real_save = codex.save
    def crash_after_first_file(path, state):
        real_save(path, state)
        raise SystemExit('power loss during initial sweep')
    monkeypatch.setattr(codex, 'save', crash_after_first_file)
    with pytest.raises(SystemExit): codex.main()
    assert not load(root / 'codex.json')['_initialized']
    monkeypatch.setattr(codex, 'save', real_save)
    deliveries = []
    monkeypatch.setattr(codex.subprocess, 'run', lambda *args, **kwargs: deliveries.append(kwargs['input']))
    assert codex.main() == 0
    assert not deliveries
    assert load(root / 'codex.json')['_initialized']
