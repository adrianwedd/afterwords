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


def authenticate_request(request, ports=(7861,)):
    import hmac
    from fastapi import HTTPException
    if not request.client or request.client.host not in ('127.0.0.1', '::1'):
        raise HTTPException(403, 'local service only')
    hosts = {f'{host}:{port}' for host in ('127.0.0.1', 'localhost', '[::1]') for port in ports}
    if request.headers.get('host', '').lower() not in hosts:
        raise HTTPException(403, 'invalid service host')
    if 'origin' in request.headers:
        raise HTTPException(403, 'browser origins are not admitted')
    try:
        expected = authorization_headers()['Authorization']
    except (OSError, ValueError, UnicodeError):
        raise HTTPException(503, 'expressive authentication unavailable') from None
    supplied = request.headers.get('authorization', '')
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, 'expressive authentication required')


def api_headers(url):
    from urllib.parse import urlsplit
    target = urlsplit(url)
    if (target.scheme == 'http' and target.hostname in ('127.0.0.1', 'localhost', '::1')
            and target.port in (7862, 17862)):
        return authorization_headers()
    return {}


def main():
    """Write private curl headers for the two established expressive API routes."""
    import argparse
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--curl-headers', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    # Legacy/non-expressive endpoints never receive the private capability.
    # If not installed yet, let the API report its bounded authentication error.
    if args.port not in (7862, 17862) or not token_path().exists():
        return
    try:
        headers = authorization_headers()
        fd = os.open(args.curl_headers, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('Authorization: ' + headers['Authorization'] + '\n')
    except (OSError, ValueError, UnicodeError):
        parser.exit(2, 'expressive authentication unavailable\n')


if __name__ == '__main__':
    main()
