"""Idempotent publication into the existing speech worker queue.

Event files retain their identity as .json -> .claimed -> .done. This guarantees
one queue publication across watcher restarts, not exactly-once audible output
(an external playback side effect cannot be atomically committed).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def enqueue(root: Path, agent: str, session: str, event_id: str,
            project: str, text: str, worker: Path | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    queue = root / 'queues' / agent / hashlib.sha256(session.encode()).hexdigest()
    queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    queue.chmod(0o700)
    name = 'event-' + hashlib.sha256(event_id.encode()).hexdigest()
    target = queue / (name + '.json')
    # One watcher per agent, guarded by a process lock. Atomic names also make
    # retries after enqueue-but-before-offset-save harmless.
    if not any((queue / (name + ext)).exists() for ext in ('.json', '.claimed', '.done')):
        fd, tmp = tempfile.mkstemp(dir=queue, prefix='.pending-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'project_dir': project, 'agent': agent, 'text': text}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(tmp, target)
        except FileExistsError:
            pass
        finally:
            os.unlink(tmp)
    if worker is not None:
        env = dict(os.environ, CODEX_THREAD_ID=hashlib.sha256(session.encode()).hexdigest(),
                   AFTERWORDS_QUEUE_DIR=str(queue), AFTERWORDS_RELIABLE_QUEUE='1',
                   AFTERWORDS_ARCHIVE_DIR=str(Path.home() / f'.{agent}' / 'tts-archive'))
        # Worker locking is shared with all launches for this queue. It drains
        # independently; the durable event remains if this launch fails.
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
        subprocess.Popen([os.environ.get('AFTERWORDS_PYTHON', sys.executable),
                          '-m', 'watcher.drain', str(worker), str(queue)], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=False)
    return target


def main() -> int:
    import argparse
    from strip_markdown import strip_markdown
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', required=True, choices=('codex', 'opencode'))
    parser.add_argument('--session', required=True)
    parser.add_argument('--event-id', required=True)
    parser.add_argument('--project', default='')
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    import sys
    text = strip_markdown(sys.stdin.read())
    if text.strip():
        worker = Path(__file__).resolve().parents[1] / '.claude/hooks/codex-tts-worker.sh'
        enqueue(args.state_dir, args.agent, args.session, args.event_id,
                args.project, text, worker)
    return 0


def resume(root: Path, agent: str) -> None:
    worker = Path(__file__).resolve().parents[1] / '.claude/hooks/codex-tts-worker.sh'
    for queue in (root / 'queues' / agent).glob('*'):
        if not any(queue.glob('*.json')) and not any(queue.glob('*.claimed')):
            continue
        env = dict(os.environ, CODEX_THREAD_ID=queue.name,
            AFTERWORDS_QUEUE_DIR=str(queue), AFTERWORDS_RELIABLE_QUEUE='1',
            AFTERWORDS_ARCHIVE_DIR=str(Path.home() / f'.{agent}' / 'tts-archive'),
            PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        subprocess.Popen([os.environ.get('AFTERWORDS_PYTHON', sys.executable),
            '-m', 'watcher.drain', str(worker), str(queue)], env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=False)


if __name__ == '__main__':
    raise SystemExit(main())
