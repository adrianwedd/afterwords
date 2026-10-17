#!/usr/bin/env python3
"""Restore Vixen's existing Seydoux speech route without changing her persona.

Run in the installed Hermes environment on the gateway host. Requires an exact
before-config hash and preserves a private backup. Does not restart any service.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request


def corrected(config):
    result = copy.deepcopy(config)
    provider = result['tts']['providers']['afterwords']
    if result['tts']['provider'] != 'afterwords' or provider['type'] != 'command':
        raise ValueError('unexpected Vixen provider; inspect before changing it')
    if provider['voice'] != 'vixen-original-r1-live':
        raise ValueError('expected the rejected synthetic Vixen route')
    provider['voice'] = 'seydoux'
    provider['command'] = ('env AFTERWORDS_PORT=7860 AFTERWORDS_PLAYBACK_OWNER=hermes '
                           'bash ~/repos/afterwords/scripts/afterwords-tts-command.sh '
                           '{input_path} {output_path} seydoux')
    changed = []
    for hook in result.get('hooks', {}).get('post_llm_call', []):
        if 'afterwords-post-llm.sh' in hook.get('command', ''):
            old = hook['command']
            if 'AFTERWORDS_VOICE=vixen-original-r1-live' not in old or 'AFTERWORDS_PORT=17862' not in old:
                raise ValueError('unexpected Vixen shell speech override')
            hook['command'] = old.replace('AFTERWORDS_PORT=17862', 'AFTERWORDS_PORT=7860').replace(
                'AFTERWORDS_VOICE=vixen-original-r1-live', 'AFTERWORDS_VOICE=seydoux')
            changed.append(hook)
    if len(changed) != 1:
        raise ValueError('expected exactly one legacy speech hook')
    return result, changed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hermes-root', type=Path, required=True)
    p.add_argument('--expected-config-sha256', required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    home = Path(os.environ.get('HERMES_HOME', ''))
    if not home.is_absolute() or home.name != 'vixen':
        p.error('set HERMES_HOME to the existing Vixen profile')
    sys.path.insert(0, str(args.hermes_root))
    import yaml
    from hermes_cli.config import atomic_config_write
    path = home/'config.yaml'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.expected_config_sha256:
        p.error('configuration changed; inspect current state')
    config = yaml.safe_load(raw)
    result, changed = corrected(config)
    profile = Path.home()/'repos/afterwords/voices/seydoux.json'
    voice = json.loads(profile.read_text())
    if voice['backend'] != 'qwen3-0.6b' or voice['reference_audio'] != 'seydoux-ref.wav':
        p.error('established Seydoux profile changed')
    reference = profile.parent/voice['reference_audio']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:7860/health', timeout=5) as response:
        health = json.load(response)
    if not health.get('ready') or 'seydoux' not in health['voices']:
        p.error('existing Qwen/Seydoux service unavailable; no speaker substitution')
    args.out.mkdir(parents=True, mode=0o700)
    backup = args.out/'config-before.yaml'
    backup.touch(mode=0o600, exist_ok=False)
    backup.write_bytes(raw)
    # Guard again after the health request; never restore an old whole config.
    if path.read_bytes() != raw:
        p.error('configuration changed before write')
    atomic_config_write(path, result)
    assert yaml.safe_load(path.read_text()) == result
    from agent.shell_hooks import register_from_config
    # The operator explicitly authorised this speech correction. Record only
    # the one changed hook through Hermes' native mechanism.
    registered = register_from_config({'hooks': {'post_llm_call': changed}}, accept_hooks=True)
    receipt = dict(before_sha256=hashlib.sha256(raw).hexdigest(),
                   after_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   voice='seydoux', backend='qwen3-0.6b', port=7860,
                   reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                   changed_fields=['tts.providers.afterwords.voice', 'tts.providers.afterwords.command',
                                   'hooks.post_llm_call[Afterwords].command'],
                   registered_changed_hooks=len(registered), service_restarted=False)
    (args.out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
