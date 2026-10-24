#!/usr/bin/env python3
"""Promote the reviewed Seydoux reference, or restore its prior speech fields.

Run with the installed Hermes environment on M5. Backups contain private config;
keep --out outside Git. No service restart and no external message delivery.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

VOICE = 'vixen-seydoux-drama-reviewed'
REFERENCE_SHA = 'a8bd5856cb6dfc1bc06dd0a49d9d146503fa9e7de25d308e0cae2cdacb438d44'


def transition(config, restore=None):
    result = copy.deepcopy(config)
    provider = result['tts']['providers']['afterwords']
    if result['tts']['provider'] != 'afterwords' or provider['type'] != 'command':
        raise ValueError('unexpected provider')
    hooks = [h for h in result.get('hooks', {}).get('post_llm_call', [])
             if 'afterwords-post-llm.sh' in h.get('command', '')]
    if len(hooks) != 1:
        raise ValueError('expected one Afterwords hook')
    hook = hooks[0]
    old = {'voice': provider['voice'], 'command': provider['command'], 'hook_command': hook['command']}
    if restore is not None:
        if provider['voice'] != VOICE or f'AFTERWORDS_VOICE={VOICE}' not in hook['command']:
            raise ValueError('current speech route differs from promoted route')
        provider['voice'], provider['command'] = restore['voice'], restore['command']
        hook['command'] = restore['hook_command']
    else:
        if provider['voice'] != 'seydoux' or 'AFTERWORDS_PORT=7860 ' not in provider['command']:
            raise ValueError('expected established Qwen/Seydoux route')
        if 'AFTERWORDS_PORT=7860 ' not in hook['command'] or 'AFTERWORDS_VOICE=seydoux ' not in hook['command']:
            raise ValueError('unexpected shell speech route')
        provider['voice'] = VOICE
        provider['command'] = ('env AFTERWORDS_PORT=17862 AFTERWORDS_PLAYBACK_OWNER=hermes '
                               'bash ~/repos/afterwords/scripts/afterwords-tts-command.sh '
                               '{input_path} {output_path} {voice}')
        hook['command'] = hook['command'].replace('AFTERWORDS_PORT=7860 ', 'AFTERWORDS_PORT=17862 ').replace(
            'AFTERWORDS_VOICE=seydoux ', f'AFTERWORDS_VOICE={VOICE} ')
    return result, old, hook


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hermes-root', type=Path, required=True)
    p.add_argument('--expected-config-sha256', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--restore-fields', type=Path)
    a = p.parse_args()
    home = Path(os.environ.get('HERMES_HOME', ''))
    if not home.is_absolute() or home.name != 'vixen':
        p.error('explicit existing Vixen profile required')
    sys.path.insert(0, str(a.hermes_root))
    import yaml
    from hermes_cli.config import atomic_config_write
    from agent.shell_hooks import register_from_config
    path = home/'config.yaml'
    raw = path.read_bytes()
    digest = lambda b: hashlib.sha256(b).hexdigest()
    if digest(raw) != a.expected_config_sha256:
        p.error('config changed; inspect again')
    restore = json.loads(a.restore_fields.read_text()) if a.restore_fields else None
    result, old, hook = transition(yaml.safe_load(raw), restore)
    port, voice = (7860, 'seydoux') if restore else (17862, VOICE)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/health', timeout=10) as response:
        health = json.load(response)
    if not health.get('ready') or voice not in health['voices']:
        p.error('target voice route unavailable')
    # Validate the retained identity even on rollback; never substitute a speaker.
    ref = Path.home()/'repos/afterwords/voices/seydoux-ref.wav'
    if digest(ref.read_bytes()) != REFERENCE_SHA:
        p.error('Seydoux reference changed')
    a.out.mkdir(parents=True, mode=0o700)
    for name, data in [('config-before.yaml', raw), ('speech-fields-before.json', json.dumps(old, indent=2).encode())]:
        dest = a.out/name
        dest.touch(mode=0o600, exist_ok=False)
        dest.write_bytes(data)
    if path.read_bytes() != raw:
        p.error('config changed before write')
    atomic_config_write(path, result)
    assert yaml.safe_load(path.read_text()) == result
    registered = register_from_config({'hooks': {'post_llm_call': [hook]}}, accept_hooks=True)
    receipt = dict(before_sha256=digest(raw), after_sha256=digest(path.read_bytes()),
                   voice=voice, port=port, reference_sha256=REFERENCE_SHA,
                   operation='rollback' if restore else 'promote',
                   registered_changed_hooks=len(registered), service_restarted=False,
                   changed_fields=['tts.providers.afterwords.voice', 'tts.providers.afterwords.command',
                                   'hooks.post_llm_call[Afterwords].command'])
    (a.out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
