"""Supervise one reliable queue worker with a crash-released process lock."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys


def main():
    worker, queue = Path(sys.argv[1]), Path(sys.argv[2])
    with (queue / 'worker.lock').open('a') as ownership:
        try:
            fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        # A killed worker can leave a claimed event. No other worker owns this
        # queue now, so recover it before draining. Done receipts never replay.
        for path in queue.glob('*.claimed'):
            path.rename(path.with_suffix('.json'))
        return subprocess.run(['bash', str(worker)], pass_fds=(ownership.fileno(),),
                              env=os.environ).returncode


if __name__ == '__main__':
    raise SystemExit(main())
