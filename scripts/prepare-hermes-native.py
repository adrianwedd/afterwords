#!/usr/bin/env python3
"""Stage or check the hash-checked native consumer bridge; never modify installed Hermes.

Staging always starts from the recorded pristine base, so it works on a host that has
never been patched, one carrying the current revision, and one still carrying a
superseded revision. Each file is verified against the manifest at every step; anything
the manifest does not recognise is refused rather than guessed at.

    prepare-hermes-native.py --hermes-root DIR --out NEW_DIR   # stage for review
    prepare-hermes-native.py --hermes-root DIR --check         # verify the live install
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_apply(cwd, patch, *, reverse=False, include=None):
    """Apply *patch* to plain files, even when *cwd* sits inside some other git repository.

    ``git apply`` otherwise switches to work-tree semantics for the enclosing repo and silently
    skips every path that is not repo-relative. Ceiling discovery at the parent keeps the
    destination treated as a plain directory, which is what staging needs.
    """
    cwd = Path(cwd)
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(cwd.resolve().parent)}
    cmd = ['git', 'apply', '--unsafe-paths']
    if reverse:
        cmd.append('-R')
    if include:
        cmd.append(f'--include={include}')
    return subprocess.run([*cmd, str(patch)], cwd=cwd, env=env, capture_output=True)


def base_from_git(root, rel, before):
    """The pristine file as committed upstream, when the checkout still carries it."""
    done = subprocess.run(['git', '-C', str(root), 'show', f'HEAD:{rel}'],
                          capture_output=True)
    if done.returncode == 0 and hashlib.sha256(done.stdout).hexdigest() == before:
        return done.stdout
    return None


def base_from_installed(root, rel, hashes, patch):
    """Recover the pristine file from an installed copy of this patch (current or superseded)."""
    installed = (root/rel).read_bytes()
    digest = hashlib.sha256(installed).hexdigest()
    if digest == hashes['before_sha256']:
        return installed
    if digest not in (hashes['after_sha256'], hashes.get('previous_after_sha256')):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp)/rel
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(installed)
        reversed_ok = git_apply(tmp, patch, reverse=True, include=rel).returncode == 0
        if reversed_ok and sha256(staged) == hashes['before_sha256']:
            return staged.read_bytes()
    return None


def resolve_base(root, rel, hashes, patch, parser):
    base = base_from_git(root, rel, hashes['before_sha256'])
    if base is None:
        base = base_from_installed(root, rel, hashes, patch)
    if base is None:
        parser.error(f'installed source changed: {rel}; rebase and retest the patch')
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--hermes-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, help='stage into this new directory')
    parser.add_argument('--check', action='store_true', help='verify the installed bridge instead')
    parser.add_argument('--variant', choices=['m5', 'studio'], default='m5')
    args = parser.parse_args()
    if bool(args.out) == args.check:
        parser.error('give exactly one of --out or --check')
    repo = Path(__file__).resolve().parents[1]
    stem = 'native-command-playback' + ('-studio' if args.variant == 'studio' else '')
    manifest = json.loads((repo/'hermes/patches'/f'{stem}.json').read_text())
    patch = repo/'hermes/patches'/f'{stem}.patch'
    helper = repo/'hermes/afterwords_native.py'
    expected_helper = manifest.get('helper', {}).get('sha256')
    if expected_helper and sha256(helper) != expected_helper:
        parser.error(f'{helper.name} does not match the manifest; update the manifest with the helper')

    if args.check:
        report = {'variant': args.variant, 'revision': manifest.get('revision'),
                  'hermes_root': str(args.hermes_root), 'files': {}, 'current': True}
        for rel, hashes in manifest['files'].items():
            installed = args.hermes_root/rel
            digest = sha256(installed) if installed.is_file() else None
            state = ('current' if digest == hashes['after_sha256'] else
                     'missing' if digest is None else
                     'pristine' if digest == hashes['before_sha256'] else
                     'superseded' if digest == hashes.get('previous_after_sha256') else
                     'changed')
            report['files'][rel] = state
            if state != 'current':
                report['current'] = False
        helper_path = args.hermes_root/(manifest.get('helper', {}).get('path', 'afterwords_native.py'))
        report['helper'] = ('current' if expected_helper and helper_path.is_file()
                            and sha256(helper_path) == expected_helper else 'missing/changed')
        if report['helper'] != 'current':
            report['current'] = False
        print(json.dumps(report, indent=2))
        return 0 if report['current'] else 1

    if args.out.exists():
        parser.error('output already exists; preserve previous preparation')
    bases = {rel: resolve_base(args.hermes_root, rel, hashes, patch, parser)
             for rel, hashes in manifest['files'].items()}
    args.out.mkdir(parents=True, mode=0o700)
    for rel, data in bases.items():
        p = args.out/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    applied = git_apply(args.out, patch)
    if applied.returncode != 0:
        parser.error('patch did not apply to the resolved base:\n'
                     + applied.stderr.decode('utf-8', 'replace').strip())
    shutil.copy2(helper, args.out/'afterwords_native.py')
    for rel, hashes in manifest['files'].items():
        assert sha256(args.out/rel) == hashes['after_sha256'], rel
    (args.out/'preparation.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Prepared native consumer bridge:', args.out)


if __name__ == '__main__':
    raise SystemExit(main())
