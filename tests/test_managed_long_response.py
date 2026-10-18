"""Long speech survives durable publication and the installed chunker boundary."""
import io
import json
from pathlib import Path
import subprocess
import sys

from watcher import queue

REPO = Path(__file__).resolve().parents[1]


def test_durable_queue_keeps_the_entire_long_response(tmp_path, monkeypatch):
    text = ('A sentence worth retaining in full. ' * 200) + 'Unique ending survives.'
    original = queue.enqueue
    def capture(root, agent, session, event_id, project, cleaned, worker, voice_agent):
        return original(root, agent, session, event_id, project, cleaned, None, voice_agent)
    monkeypatch.setattr(queue, 'enqueue', capture)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(text))
    monkeypatch.setattr(sys, 'argv', ['queue', '--agent', 'claude', '--session', 'session',
                                   '--event-id', 'event', '--project', '/project', '--state-dir', str(tmp_path)])
    assert queue.main() == 0
    stored = json.loads(next(tmp_path.rglob('event-*.json')).read_text())
    assert stored['text'] == text
    assert len(stored['text']) > 5000


def test_staged_runtime_chunks_more_than_server_limit(tmp_path):
    subprocess.run([sys.executable, '-m', 'watcher.manage', 'stage', 'all', '--home', str(tmp_path)],
                   cwd=REPO, check=True, capture_output=True)
    runtime = tmp_path/'Library/Application Support/Afterwords/watchers/runtime'
    text = ('A complete sentence must survive. ' * 200) + 'The final unique sentence.'
    result = subprocess.run([sys.executable, str(runtime/'chunk_text.py')], input=text,
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    chunks = result.stdout.splitlines()
    assert len(chunks) > 10
    assert all(len(chunk) <= 400 for chunk in chunks)
    assert ' '.join(chunks) == text
