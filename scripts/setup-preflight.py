#!/usr/bin/env python3
"""Read-only baseline installation checks. Never install or alter configuration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request


def writable_ancestor(path):
    while not path.exists():
        path = path.parent
    return os.access(path, os.W_OK)


def main():
    repo = Path(sys.argv[1])
    failures = []
    for path in (repo, Path.home() / 'Library/LaunchAgents', Path('/usr/local/bin')):
        writable = writable_ancestor(path)
        print(f'{path}: writable ancestor={writable}')
        if not writable:
            print('  Installation may require sudo for this destination.')
    free = shutil.disk_usage(repo).free / 2**30
    print(f'Free disk: {free:.1f} GiB (reserve at least 6 GiB for baseline environment/model/cache)')
    if free < 6:
        failures.append('insufficient free disk')
    print('macOS:', subprocess.check_output(['sw_vers', '-productVersion'], text=True).strip())
    result = subprocess.run(['lsof', '-nP', '-tiTCP:7860', '-sTCP:LISTEN'], capture_output=True, text=True)
    if result.stdout.strip():
        try:
            with urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3) as response:
                health = json.load(response)
            if health.get('service') != 'afterwords':
                failures.append('port 7860 listener does not identify as Afterwords')
            else:
                print('Existing Afterwords service detected; installation will replace its launchd configuration.')
        except Exception:
            failures.append('port 7860 is occupied by an unidentified listener')
    else:
        print('Port 7860: free')
    for failure in failures:
        print('FAIL:', failure, file=sys.stderr)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
