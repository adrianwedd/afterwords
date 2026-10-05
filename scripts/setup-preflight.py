#!/usr/bin/env python3
"""Read-only baseline installation checks. Never install or alter configuration."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import urllib.request


def writable_ancestor(path):
    while not path.exists():
        path = path.parent
    return os.access(path, os.W_OK)


def check_port(repo):
    """Require both owning process identity and HTTP service identity."""
    try:
        result = subprocess.run(
            ['lsof', '-nP', '-tiTCP:7860', '-sTCP:LISTEN'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f'cannot establish port ownership: {exc}']
    if not result.stdout.strip():
        if result.returncode == 1 and not result.stderr.strip():
            print('Port 7860: free')
            return []
        return ['cannot establish port ownership: unexpected lsof result']
    if result.returncode != 0:
        return ['cannot establish port ownership: lsof failed']
    expected = (repo / 'server.py').resolve()
    for pid in set(result.stdout.split()):
        if not pid.isdigit():
            return ['cannot establish port ownership: invalid PID']
        try:
            process = subprocess.run(['ps', '-p', pid, '-o', 'command='],
                                     capture_output=True, text=True, timeout=5)
            command = process.stdout.strip()
            prefix = f'{repo / ".venv/bin/python3"} {repo / "server.py"}'
            venv_owned = command == prefix or command.startswith(prefix + ' ')
            argv = shlex.split(command)
            owned = (process.returncode == 0 and len(argv) >= 2
                     and Path(argv[0]).name.startswith('python')
                     and Path(argv[1]).is_absolute()
                     and Path(argv[1]).resolve() == expected)
            owned = process.returncode == 0 and (owned or venv_owned)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            owned = False
        if not owned:
            return [f"port 7860 conflict: PID {pid} is not this checkout's Afterwords server"]
    try:
        with urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3) as response:
            health = json.load(response)
        if health.get('service') != 'afterwords':
            return ['port 7860 listener does not identify as Afterwords']
    except Exception:
        return ['port 7860 is occupied by an unidentified or unreachable listener']
    print('Existing Afterwords service detected; installation will replace its launchd configuration.')
    return []


def main():
    repo = Path(sys.argv[1])
    failures = []
    for path in (repo, Path.home() / 'Library/LaunchAgents', Path('/usr/local/bin')):
        writable = writable_ancestor(path)
        print(f'{path}: writable ancestor={writable}')
        if not writable:
            print('  Not writable; the CLI destination may require sudo. Other destinations require corrected ownership.')
    free = shutil.disk_usage(repo).free / 2**30
    print(f'Free disk: {free:.1f} GiB (reserve at least 6 GiB for baseline environment/model/cache)')
    if free < 6:
        failures.append('insufficient free disk')
    print('macOS:', subprocess.check_output(['sw_vers', '-productVersion'], text=True).strip())
    failures.extend(check_port(repo))
    for failure in failures:
        print('FAIL:', failure, file=sys.stderr)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
