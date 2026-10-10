"""Install only desktop watchers; never configure or restart the TTS server."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
FILES = ('watcher/__init__.py', 'watcher/state.py', 'watcher/queue.py', 'watcher/drain.py',
         'codex/afterwords-codex-watch.py', 'opencode/afterwords-opencode-watch.py',
         'opencode/tts-hook-opencode.sh', '.claude/hooks/codex-tts-hook.sh',
         '.claude/hooks/codex-tts-worker.sh', 'codex_session_hook.py',
         'strip_markdown.py', 'chunk_text.py')


def control(*args, check=True):
    return subprocess.run(['launchctl', *args], check=check, capture_output=True, text=True)


def unload(domain, label, plist):
    if control('print', f'{domain}/{label}', check=False).returncode == 0:
        control('bootout', domain, str(plist))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'restart', 'status', 'uninstall'))
    parser.add_argument('agent', choices=('codex', 'opencode', 'all'))
    parser.add_argument('--home', type=Path, default=Path.home(), help='Isolated acceptance HOME')
    parser.add_argument('--label-prefix', default='au.wedd.afterwords', help='Isolated acceptance labels')
    parser.add_argument('--sessions', type=Path)
    parser.add_argument('--db', type=Path)
    args = parser.parse_args(argv)
    home = args.home.resolve()
    root = home / 'Library/Application Support/Afterwords/watchers'
    runtime = root / 'runtime'
    agents = ('codex', 'opencode') if args.agent == 'all' else (args.agent,)
    domain = f'gui/{os.getuid()}'
    if args.action == 'install' and 'codex' in agents and home == Path.home():
        pidfile = Path('/tmp/codex-tts-watch.pid')
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text().strip()), 0)
            except (OSError, ValueError):
                pass
            else:
                raise SystemExit('Stop the per-session Codex watcher before installing global coverage.')
    if args.action == 'install':
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        staged = root / 'runtime.new'
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(mode=0o700)
        for relative in FILES:
            dest = staged / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative, dest)
        # Stop only these watcher labels before upgrading their private runtime.
        # Both share helpers, so briefly stop any installed sibling as well.
        installed = []
        for agent in ('codex', 'opencode'):
            plist = home / 'Library/LaunchAgents' / f'{args.label_prefix}-{agent}-watch.plist'
            if plist.exists():
                installed.append((agent, plist))
                unload(domain, f'{args.label_prefix}-{agent}-watch', plist)
        old = root / 'runtime.old'
        if old.exists():
            shutil.rmtree(old)
        if runtime.exists():
            runtime.rename(old)
        staged.rename(runtime)
        for agent, plist in installed:
            if agent not in agents:
                control('bootstrap', domain, str(plist))
        if old.exists():
            shutil.rmtree(old)
    for agent in agents:
        label = f'{args.label_prefix}-{agent}-watch'
        plist = home / 'Library/LaunchAgents' / f'{label}.plist'
        if args.action == 'install':
            extra = []
            if agent == 'codex' and args.sessions:
                extra = ['--sessions', str(args.sessions.resolve())]
            if agent == 'opencode' and args.db:
                extra = ['--db', str(args.db.resolve())]
            values = {'Label': label,
                'ProgramArguments': [sys.executable, str(runtime / agent / f'afterwords-{agent}-watch.py'), *extra],
                'WorkingDirectory': str(runtime), 'RunAtLoad': True, 'KeepAlive': True,
                'ThrottleInterval': 5,
                'EnvironmentVariables': {'HOME': str(home), 'AFTERWORDS_WATCH_STATE': str(root),
                    'AFTERWORDS_PYTHON': sys.executable,
                    'PATH': '/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
                'StandardOutPath': str(root / f'{agent}.log'),
                'StandardErrorPath': str(root / f'{agent}.log')}
            plist.parent.mkdir(parents=True, exist_ok=True)
            unload(domain, f'{args.label_prefix}-{agent}-watch', plist)
            plist.write_bytes(plistlib.dumps(values))
            plist.chmod(0o600)
            control('bootstrap', domain, str(plist))
        elif args.action == 'restart':
            control('kickstart', '-k', f'{domain}/{label}')
        elif args.action == 'status':
            result = control('print', f'{domain}/{label}', check=False)
            print(result.stdout or result.stderr, end='')
            if result.returncode:
                return result.returncode
        elif args.action == 'uninstall':
            unload(domain, f'{args.label_prefix}-{agent}-watch', plist)
            plist.unlink(missing_ok=True)
            # Retain private offsets/receipts/archive on uninstall so reinstall
            # does not replay old messages. Source runtime is removed when last
            # watcher is removed; state can be manually deleted when inactive.
    if args.action == 'uninstall' and not any(
        (home / 'Library/LaunchAgents' / f'{args.label_prefix}-{a}-watch.plist').exists()
        for a in ('codex', 'opencode')):
        shutil.rmtree(runtime, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
