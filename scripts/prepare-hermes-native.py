#!/usr/bin/env python3
"""Stage the hash-checked native consumer bridge; never modify installed Hermes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--variant', choices=['m5', 'studio'], default='m5')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    stem = 'native-command-playback' + ('-studio' if args.variant == 'studio' else '')
    manifest = json.loads((repo/'hermes/patches'/f'{stem}.json').read_text())
    if args.out.exists():
        parser.error('output already exists; preserve previous preparation')
    for rel, hashes in manifest['files'].items():
        p = args.hermes_root/rel
        if hashlib.sha256(p.read_bytes()).hexdigest() != hashes['before_sha256']:
            parser.error(f'installed source changed: {rel}; rebase and retest the patch')
    args.out.mkdir(parents=True, mode=0o700)
    for rel in manifest['files']:
        p = args.out/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.hermes_root/rel, p)
    subprocess.run(['git', 'apply', '--unsafe-paths', str(repo/'hermes/patches'/f'{stem}.patch')],
                   cwd=args.out, check=True)
    shutil.copy2(repo/'hermes/afterwords_native.py', args.out/'afterwords_native.py')
    for rel, hashes in manifest['files'].items():
        assert hashlib.sha256((args.out/rel).read_bytes()).hexdigest() == hashes['after_sha256']
    (args.out/'preparation.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Prepared native consumer bridge:', args.out)


if __name__ == '__main__':
    main()
