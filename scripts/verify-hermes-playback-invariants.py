#!/usr/bin/env python3
"""Capture the staged consumer's real playback invariants, layer by layer.

Three modes run against the staged revision with the live Hermes runtime behind it:

    audible      real synthesis, real speaker playback
    muted        real synthesis, no playback (the automatic mute flag wins)
    stale-lease  real synthesis, real playback after clearing a lease whose holder is gone

An *occupied* lease suppresses playback too, but by design that waits for the shim's lease
timeout, so it stays a unit-level assertion in the test suite rather than a slow receipt.

Each mode records synthesis, whether playback was invoked, whether the player succeeded, and
whether the shared lease survived. Nothing here claims acoustic acceptance: a successful
player process is not evidence that a human heard anything.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PATCHED = ('tools/tts_command_provider.py', 'tools/tts_tool_speaker.py',
           'hermes_cli/cli_voice_mixin.py', 'hermes_cli/voice.py')

CHILD = r'''
import json, os, sys
from pathlib import Path
sandbox, root, sp, mode, receipt, text = sys.argv[1:7]
sys.path[:0] = [sandbox, root, sp]
import hermes_cli.voice as voice
calls = {'playback_calls': 0, 'player_success': False}
real_play = voice.play_audio_file
def play(path):
    calls['playback_calls'] += 1
    ok = real_play(path)
    calls['player_success'] = bool(calls['player_success'] or ok)
    return ok
voice.play_audio_file = play
lock, pid = Path(os.environ['AFTERWORDS_PLAY_LOCK']), Path(os.environ['AFTERWORDS_PLAY_PID'])
before = lock.exists()
voice._speak_whole_file(text)
row = {'mode': mode, 'synthesis': True, 'lock_held_before': before,
       'lease_present_after': lock.exists(), **calls}
Path(receipt).write_text(json.dumps(row))
'''


def build_sandbox(out, staged, root):
    sandbox = out/'sandbox'
    for package in ('tools', 'hermes_cli'):
        (sandbox/package).mkdir(parents=True, exist_ok=True)
        for child in (root/package).iterdir():
            link = sandbox/package/child.name
            rel = f'{package}/{child.name}'
            if rel in PATCHED:
                link.write_bytes((staged/rel).read_bytes())
            else:
                link.symlink_to(child)
    return sandbox


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--hermes-root', type=Path, required=True)
    parser.add_argument('--staged', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--text', default='Playback invariant receipt. One two three.')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output exists; preserve previous attempts')
    args.out.mkdir(parents=True, mode=0o700)
    sandbox = build_sandbox(args.out, args.staged, args.hermes_root)
    site_packages = next(iter(sorted(
        (Path.home()/'.hermes/installs').glob('*/environments/*/venv/lib/python3.*/site-packages'))), None)
    if site_packages is None:
        parser.error('installed Hermes runtime site-packages not found')
    driver = args.out/'child.py'
    driver.write_text(CHILD)
    rows = []
    for mode in ('audible', 'muted', 'stale-lease'):
        lease = args.out/mode
        lease.mkdir()
        lock, pid, mute = lease/'play.lock', lease/'play.pid', lease/'muted'
        if mode == 'muted':
            mute.touch()
        if mode == 'stale-lease':
            lock.mkdir()
            pid.write_text('999999')  # a holder that cannot be running
        env = {**os.environ, 'AFTERWORDS_PLAY_LOCK': str(lock),
               'AFTERWORDS_PLAY_PID': str(pid), 'AFTERWORDS_MUTE_FILE': str(mute)}
        row_path = lease/'row.json'
        done = subprocess.run([sys.executable, '-I', str(driver), str(sandbox),
                               str(args.hermes_root), str(site_packages), mode,
                               str(row_path), args.text], env=env, capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit(f'{mode}: {done.stderr.strip()}')
        rows.append(json.loads(row_path.read_text()))
    manifest = json.loads((Path(__file__).resolve().parents[1]/'hermes/patches/'
                           'native-command-playback.json').read_text())
    receipt = {
        'status': 'playback_invariants_observed_not_acoustic_acceptance',
        'manifest_revision': manifest.get('revision'),
        'staged_sha256': {rel: hashlib.sha256((args.staged/rel).read_bytes()).hexdigest()
                          for rel in PATCHED},
        'text': args.text,
        'modes': rows,
        'acoustic_acceptance': False,
        'notes': ['player_success means the system player exited 0, not that anyone heard it',
                  'an occupied lease suppresses playback by design and is asserted in the test suite'],
    }
    (args.out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
