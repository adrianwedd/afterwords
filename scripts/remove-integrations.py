#!/usr/bin/env python3
"""Detect/remove setup-owned hook registrations; retain helper code and private data."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('tts-hook.sh', 'claude-tts-hook.sh', 'agy-tts-hook.sh',
         'gemini-tts-hook.sh', 'cursor-tts-hook.sh')


def owned_command(command, home, repo, names=NAMES):
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if words and words[0] == 'env': words.pop(0)
    while words and re.match(r'^[A-Za-z_]\w*=', words[0]): words.pop(0)
    if words and words[0] in ('bash', '/bin/bash', '/usr/bin/bash'): words.pop(0)
    if len(words) != 1: return False
    target = words[0]
    for prefix in ('~/', '$HOME/', '${HOME}/'):
        if target.startswith(prefix):
            target = str(home/target[len(prefix):])
            break
    allowed = {str(directory/name) for directory in (
        home/'.claude/hooks', repo/'.claude/hooks',
        home/'Library/Application Support/Afterwords/watchers/runtime/.claude/hooks') for name in names}
    return os.path.normpath(target) in allowed


DROP = object()


def prune(node, home, repo, names=NAMES):
    if isinstance(node, list):
        items = [prune(item, home, repo, names) for item in node]
        return [item for item in items if item is not DROP]
    if isinstance(node, dict):
        if node.get('type', 'command') == 'command' and owned_command(node.get('command'), home, repo, names):
            return DROP
        result = {key:prune(value, home, repo, names) for key,value in node.items()}
        result = {key:value for key,value in result.items() if value is not DROP}
        if node.get('hooks') and result.get('hooks') == []:
            return DROP
        return result
    return node


def plans(home, repo):
    result = []
    for relative, key in (('.claude/settings.json','hooks'), ('.gemini/settings.json','hooks'),
                          ('.cursor/hooks.json','hooks'), ('.gemini/config/hooks.json','afterwords-tts')):
        path = home/relative
        if not path.exists(): continue
        raw = path.read_bytes()
        data = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(data, dict): raise ValueError('unsupported settings structure')
        if key not in data: continue
        changed = prune(data[key], home, repo)
        if changed == data[key]: continue
        data[key] = {} if changed is DROP else changed
        result.append((path, raw, data))
    return result


def apply_plans(changes):
    for path, before, after in changes:
        if path.read_bytes() != before:
            raise ValueError('settings changed during removal preparation')
        mode = path.stat().st_mode & 0o777
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.afterwords-remove-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(after, stream, indent=2, ensure_ascii=False)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if path.read_bytes() != before:
                raise ValueError('settings changed during removal preparation')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['detect','remove'])
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        changes = plans(args.home, args.repo)
        if args.action == 'detect':
            watchers = any((args.home/'Library/LaunchAgents'/f'au.wedd.afterwords-{agent}-watch.plist').exists()
                           for agent in ('codex','opencode'))
            return 0 if changes or watchers else 1
        apply_plans(changes)
    except (OSError, ValueError, TypeError):
        parser.exit(2, 'Could not safely inspect/update setup-managed hook settings; no success claimed.\n')
    print(f'Removed setup-managed registrations from {len(changes)} settings file(s); helper code/data retained.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
