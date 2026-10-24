"""Supervise reliable queue work; retry only bounded pre-playback failures."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def _attempts(path):
    try:
        return max(0, int(json.loads(path.read_text()).get('attempts', 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def _record_attempt(path, attempts):
    original = path.stat()
    data = json.loads(path.read_text())
    data['attempts'] = attempts
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.retry-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _supervise(worker, queue, ownership):
    """Drain while holding the lock; return (exit code, events seen last run)."""
    exhausted = False
    while True:
        # .playing is terminal: sound may have reached the speakers.
        for path in queue.glob('*.claimed'):
            path.rename(path.with_suffix('.json'))
        before = {path.stem: _attempts(path) for path in queue.glob('*.json')}
        result = subprocess.run(['bash', str(worker)], pass_fds=(ownership.fileno(),),
                                env=os.environ).returncode
        claimed = list(queue.glob('*.claimed'))
        if not claimed:
            return result or int(exhausted), set(before)
        retry = False
        for path in claimed:
            attempts = max(_attempts(path), before.get(path.stem, 0) + 1)
            try:
                _record_attempt(path, attempts)
            except (OSError, ValueError, TypeError):
                attempts = 3  # retain malformed evidence, never loop forever
            if attempts >= 3:
                path.rename(path.with_suffix('.failed'))
                exhausted = True
            else:
                retry = True
        # Hook-only queues need their own retries, independently per event.
        # Continue other queued work even when one event exhausted its budget.
        if not retry and not any(queue.glob('*.json')):
            return result or 1, set(before)
        time.sleep(.3)


def main():
    worker, queue = Path(sys.argv[1]), Path(sys.argv[2])
    result = 0
    while True:
        with (queue / 'worker.lock').open('a') as ownership:
            try:
                fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return result
            result, seen = _supervise(worker, queue, ownership)
        # An event published after the worker's last scan found this lock held,
        # so its own drain returned. Recheck after releasing: either we drain it
        # or the supervisor that took the lock will. Events the worker already
        # saw and left pending (for example, server down) do not loop.
        if not {path.stem for path in queue.glob('*.json')} - seen:
            return result

if __name__ == '__main__':
    raise SystemExit(main())
