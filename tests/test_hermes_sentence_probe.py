"""Process-boundary safeguards for the real-reply smoke probe (no inference)."""
import json
import os
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-hermes-sentence-route.py'


def test_real_reply_deadline_reaps_a_stalled_bootstrap(tmp_path):
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'config.yaml').write_text('{}')
    hermes = tmp_path / 'hermes'
    hermes.mkdir()
    (hermes / 'cli.py').write_text('import time\ntime.sleep(30)\n')
    output = tmp_path / 'output'
    result = subprocess.run(
        [sys.executable, str(SCRIPT), '--hermes-root', str(hermes), '--out', str(output),
         '--agent-prompt', 'A bounded test', '--deadline', '1'],
        env={**os.environ, 'HERMES_HOME': str(profile)}, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 124, result.stderr
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['status'] == 'incomplete'
    assert receipt['worker_reaped'] is True
    assert not list(output.glob('*.wav'))


def test_existing_attempt_is_preserved(tmp_path):
    output = tmp_path / 'previous'
    output.mkdir()
    receipt = output / 'receipt.json'
    receipt.write_text('{"status":"prior failure"}')
    result = subprocess.run(
        [sys.executable, str(SCRIPT), '--hermes-root', str(tmp_path), '--out', str(output),
         '--agent-prompt', 'Must not start'], capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 2
    assert receipt.read_text() == '{"status":"prior failure"}'
