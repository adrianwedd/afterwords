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
                    holder = pid.read_text().strip()
                    if not holder:
                        time.sleep(.05)
                        holder = pid.read_text().strip()
                    if holder:
                        os.kill(int(holder), 0)
                    else:
                        # An owner may be between mkdir and PID write. Leave it
                        # alone: skipping playback is safer than breaking a lease.
                        holder = 'unknown'
                except ProcessLookupError:
                    # Remove only an unchanged stale receipt and empty lock.
                    if pid.read_text().strip() == holder:
                        pid.unlink(missing_ok=True)
                        try: lock.rmdir()
                        except FileNotFoundError: pass
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
