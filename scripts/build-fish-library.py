#!/usr/bin/env python3
"""Plan/install private Fish aliases; never alter Qwen profiles or routing."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from expressive.library import library_plan, install_aliases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT/'voices')
    p.add_argument('--snapshot', type=Path, default=ROOT/'qa/voice-reference-remediation/final-snapshot.json')
    p.add_argument('--acceptance', type=Path, default=ROOT/'qa/voice-reference-remediation/final-acceptance.json')
    p.add_argument('--target', type=Path, default=ROOT/'var/expressive-voice/voices')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    # Claim receipt before any installation. An existing attempt is never reused.
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x') as stream:
        stream.write('{"status":"incomplete"}\n')
    result = library_plan(a.source, json.loads(a.snapshot.read_text()), json.loads(a.acceptance.read_text()))
    result['status'] = 'planned'
    a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    if a.apply:
        result.update(status='installing', created=[])
        a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
        try:
            install_aliases(result, a.target, result['created'])
            result['status'] = 'installed'
        except Exception as exc:
            result.update(status='failed', error=str(exc))
            raise
        finally:
            a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'compatible', 'excluded')}))


if __name__ == '__main__':
    main()
