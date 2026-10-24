"""Caller-scoped bridge for the installed Hermes native speaker.

Installed alongside the matching Hermes consumer patch; never changes process
wide ownership variables. Ordinary command tools retain provider playback.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import time

_native = ContextVar('afterwords_native_speaker', default=False)


def native_synthesis(function, *args, **kwargs):
    token = _native.set(True)
    try:
        return function(*args, **kwargs)
    finally:
        _native.reset(token)


def command_environment():
    if not _native.get():
        return {}
    return {'AFTERWORDS_TTS_CALLER': 'native',
            'HERMES_SESSION_PLATFORM': 'cli', 'HERMES_SESSION_SOURCE': 'cli'}


@contextmanager
def playback_lease(*, mute=None, lock=None, pid=None, timeout=60):
    mute = Path(mute or os.environ.get('AFTERWORDS_MUTE_FILE', '/tmp/afterwords-muted'))
    lock = Path(lock or os.environ.get('AFTERWORDS_PLAY_LOCK', '/tmp/afterwords-play.lock'))
    pid = Path(pid or os.environ.get('AFTERWORDS_PLAY_PID', '/tmp/afterwords-play.pid'))
    deadline = time.monotonic() + timeout
    owned = False
    try:
        while not mute.exists():
            try:
                lock.mkdir()
                owned = True
                pid.write_text(str(os.getpid()))
                break
            except FileExistsError:
                try:
                    lease = lock.stat()
                    def read_holder():
                        try:
                            return pid.read_text().strip()
                        except FileNotFoundError:
                            return ''
                    holder = read_holder()
                    if not holder:
                        time.sleep(.05)
                        holder = read_holder()
                    if not holder:
                        # Match the shared convention: recheck the empty PID
                        # window, then clear only the same unchanged empty lease.
                        current = lock.stat()
                        if (current.st_dev, current.st_ino) == (lease.st_dev, lease.st_ino) and not read_holder():
                            pid.unlink(missing_ok=True)
                            lock.rmdir()
                        continue
                    try:
                        os.kill(int(holder), 0)
                    except ProcessLookupError:
                        current = lock.stat()
                        if ((current.st_dev, current.st_ino) == (lease.st_dev, lease.st_ino)
                                and read_holder() == holder):
                            pid.unlink(missing_ok=True)
                            lock.rmdir()
                        continue
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    break
                time.sleep(.05)
        yield owned and not mute.exists()
    finally:
        if owned:
            if pid.exists() and pid.read_text().strip() == str(os.getpid()):
                pid.unlink(missing_ok=True)
                lock.rmdir()


def native_playback(function, path, **lease_options):
    with playback_lease(**lease_options) as allowed:
        return function(path) if allowed else False
