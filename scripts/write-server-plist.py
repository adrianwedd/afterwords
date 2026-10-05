#!/usr/bin/env python3
"""Generate a launchd plist atomically, with XML-safe paths and backend selection."""
import argparse
import os
from pathlib import Path
import plistlib
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--host', default='')
    parser.add_argument('--bind-public', action='store_true')
    parser.add_argument('--with-1.7b', dest='with_17b', action='store_true')
    parser.add_argument('--backends', default='')
    parser.add_argument('--gallery-reload', choices=('auto', 'true', 'false'), default='auto')
    args = parser.parse_args()
    repo = Path(args.repo)
    command = [str(repo / '.venv/bin/python3'), str(repo / 'server.py')]
    if args.with_17b:
        command.append('--with-1.7b')
    if args.host:
        command.extend(['--host', args.host])
        if args.bind_public:
            command.append('--bind-public')
    local = args.host in ('', '127.0.0.1', 'localhost', '::1')
    if args.gallery_reload == 'true' or (args.gallery_reload == 'auto' and local):
        if not local:
            parser.error('gallery reload requires a loopback bind')
        command.append('--allow-reload')
    path = Path(args.path)
    previous = {}
    if path.exists():
        try:
            previous = plistlib.loads(path.read_bytes())
        except Exception:
            pass
    selected = args.backends or previous.get('EnvironmentVariables', {}).get('AFTERWORDS_BACKENDS') or 'qwen3-0.6b'
    data = dict(Label='com.afterwords.tts-server', ProgramArguments=command,
                EnvironmentVariables={'AFTERWORDS_BACKENDS': selected},
                RunAtLoad=True, KeepAlive=True,
                StandardOutPath='/tmp/claude-tts-server.log',
                StandardErrorPath='/tmp/claude-tts-server.log')
    path = Path(args.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.afterwords-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            plistlib.dump(data, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    main()
