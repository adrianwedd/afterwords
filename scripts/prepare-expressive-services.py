#!/usr/bin/env python3
"""Prepare isolated Studio launchd plists; does not load jobs or stop services."""
import argparse
from pathlib import Path
import plistlib

ROOT = Path(__file__).resolve().parents[1]


def service_plists(root, peer, tailscale_ip):
    logs = root / 'var/expressive-voice/services'
    common = {'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
              'ProcessType': 'Background', 'WorkingDirectory': str(root)}
    commands = {
        'sidecar': [str(root / '.venv-drama3/bin/python'), '-m', 'expressive.sidecar'],
        'api': [str(root / '.venv/bin/python'), str(root / 'server.py'), '--port', '7862',
                '--voices-dir', str(root / 'var/expressive-voice/voices'), '--allow-reload'],
        'm5': [str(root / '.venv/bin/python'), str(root / 'scripts/expressive-m5-tunnel.py'),
               '--peer', peer, '--tailscale-ip', tailscale_ip],
    }
    for name, command in commands.items():
        label = f'net.afterwords.expressive.{name}'
        env = {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin', 'HF_HUB_OFFLINE': '1'}
        if name == 'api':
            env['AFTERWORDS_BACKENDS'] = 'qwen3-0.6b,fish-drama3'
            # Qwen loads from the HF cache; offline would make clearing it fatal.
            del env['HF_HUB_OFFLINE']
        yield label, {**common, 'Label': label, 'ProgramArguments': command,
                      'EnvironmentVariables': env,
                      'StandardOutPath': str(logs / f'{name}.log'),
                      'StandardErrorPath': str(logs / f'{name}.log')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--peer', required=True)
    parser.add_argument('--tailscale-ip', required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('use a new output directory; preserve existing service definitions')
    args.out.mkdir(parents=True)
    for label, data in service_plists(ROOT, args.peer, args.tailscale_ip):
        path = args.out / f'{label}.plist'
        path.write_bytes(plistlib.dumps(data))
        print(path)


if __name__ == '__main__':
    main()
