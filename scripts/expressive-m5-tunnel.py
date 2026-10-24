#!/usr/bin/env python3
"""Maintain a loopback-only M5 reverse forward under a process supervisor.

The primary SSH alias must pin a HostKeyAlias. Tailscale fallback preserves
that same identity and host-key pin; no old LAN address is inferred.
"""
import argparse
import ipaddress
import os
import re
import subprocess

SSH = '/usr/bin/ssh'


def connection_args(alias, tailscale_ip):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', alias):
        raise ValueError('invalid SSH alias')
    if ipaddress.ip_address(tailscale_ip) not in ipaddress.ip_network('100.64.0.0/10'):
        raise ValueError('fallback must be a Tailscale IPv4 address')
    common = [SSH, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
              '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1',
              '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
              '-o', 'ExitOnForwardFailure=yes']
    return common, common + ['-o', f'HostName={tailscale_ip}']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--peer', required=True)
    parser.add_argument('--tailscale-ip', required=True)
    parser.add_argument('--remote-port', type=int, default=17862)
    parser.add_argument('--route', choices=('auto', 'direct', 'tailscale'), default='auto')
    args = parser.parse_args()
    if not 1024 <= args.remote_port <= 65535:
        parser.error('remote port must be 1024–65535')
    try:
        direct, fallback = connection_args(args.peer, args.tailscale_ip)
    except ValueError as exc:
        parser.error(str(exc))
    resolved = subprocess.run([SSH, '-G', args.peer], check=True, capture_output=True, text=True)
    config = dict(line.split(None, 1) for line in resolved.stdout.splitlines() if ' ' in line)
    if config.get('hostkeyalias', 'none') == 'none':
        parser.error('peer alias must pin HostKeyAlias for both transports')
    route = args.route
    if route == 'auto':
        try:
            probe = subprocess.run(direct + [args.peer, 'true'], timeout=15, check=False)
            route = 'direct' if probe.returncode == 0 else 'tailscale'
        except subprocess.TimeoutExpired:
            route = 'tailscale'
    command = (direct if route == 'direct' else fallback) + [
        '-N', '-R', f'127.0.0.1:{args.remote_port}:127.0.0.1:7862', args.peer]
    print(f'expressive tunnel: {route}; remote loopback port {args.remote_port}', flush=True)
    os.execv(SSH, command)


if __name__ == '__main__':
    main()
