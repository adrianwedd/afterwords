#!/usr/bin/env python3
"""Merge owned Claude/AGy registrations without interpreting hook mentions."""
import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('afterwords_removal', Path(__file__).with_name('remove-integrations.py'))
removal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(removal)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('agent', choices=('claude', 'agy'))
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--command', required=True)
    args = parser.parse_args()
    raw = args.settings.read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('unsupported settings structure')
    entry = {'type':'command', 'command':args.command}
    if args.agent == 'claude':
        entry.update(timeout=120, **{'async':True})
        hooks = data['hooks'] = data.get('hooks') or {}
        for event in ('Stop', 'SubagentStop'):
            kept = removal.prune(hooks.get(event) or [], args.home, args.repo,
                                 ('tts-hook.sh', 'claude-tts-hook.sh'))
            hooks[event] = kept + [{'hooks':[dict(entry)]}]
    else:
        entry['timeout'] = 120000
        hooks = data['afterwords-tts'] = data.get('afterwords-tts') or {}
        kept = removal.prune(hooks.get('Stop') or [], args.home, args.repo,
                             ('agy-tts-hook.sh',))
        hooks['Stop'] = kept + [entry]
    removal.apply_plans([(args.settings, raw, data)])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
