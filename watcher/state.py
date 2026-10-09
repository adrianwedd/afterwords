"""Private, atomic persistent watcher state and single-process ownership."""
import fcntl
import json
import os
from pathlib import Path
import tempfile


def state_root() -> Path:
    root = Path(os.environ.get('AFTERWORDS_WATCH_STATE',
        str(Path.home() / 'Library/Application Support/Afterwords/watchers')))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def save(path: Path, value: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    # Fail closed on corrupt state: silently discarding it can replay speech.
    return json.loads(path.read_text())


def lock(path: Path):
    stream = path.open('a')
    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return stream
