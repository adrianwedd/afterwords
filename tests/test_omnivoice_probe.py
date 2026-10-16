"""The alternative-model probe must fail closed before unbounded inference."""
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/benchmark-omnivoice.py'


def test_hard_deadline_stops_a_stalled_dependency_before_model_load(tmp_path):
    fake_modules = tmp_path / 'modules'
    fake_modules.mkdir()
    (fake_modules / 'psutil.py').write_text('import time\ntime.sleep(30)\n')
    text = tmp_path / 'text.txt'
    text.write_text('The committee is late.')
    reference = tmp_path / 'reference.wav'
    reference.write_bytes(b'not loaded: the process must stop before decoding')
    output = tmp_path / 'attempt.wav'
    result = subprocess.run(
        [sys.executable, str(SCRIPT), '--text-file', str(text), '--reference', str(reference),
         '--reference-text-file', str(text), '--output', str(output), '--timeout', '1'],
        env={**os.environ, 'PYTHONPATH': str(fake_modules)}, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 124, result.stderr
    receipt = json.loads(output.with_suffix('.json').read_text())
    assert receipt['status'] == 'incomplete'
    assert receipt['worker_reaped'] is True
    assert not output.exists()
