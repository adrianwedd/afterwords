#!/usr/bin/env python3
"""Prepare a private sidecar credential file without installing it or printing it."""
import argparse
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.out.is_absolute():
        parser.error('use an absolute protected output path')
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        parser.error('output exists; preserve the existing credential')
    with os.fdopen(fd, 'w') as stream:
        stream.write(secrets.token_urlsafe(32)+'\n')
    print('Prepared private credential file:', args.out)


if __name__ == '__main__':
    main()
