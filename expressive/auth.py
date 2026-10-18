"""Private file-based credentials for machine-to-machine sidecar requests."""
import os
from pathlib import Path
import re
import stat


def token_path():
    return Path(os.environ.get('AFTERWORDS_SIDECAR_TOKEN_FILE',
                               str(Path.home()/'.local/state/afterwords/expressive-sidecar.token')))


def authorization_headers():
    path = token_path()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='ascii') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('sidecar credential must be a private owned regular file')
        token = stream.read(257).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise ValueError('invalid sidecar credential')
    return {'Authorization': 'Bearer ' + token}
