"""Concurrent audits must not overwrite one another's retained evidence."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import threading


def test_concurrent_audits_have_exactly_one_receipt_owner(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'scripts/audit-expressive-audio.py'
    spec = importlib.util.spec_from_file_location('audit_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    barrier = threading.Barrier(2)
    output = tmp_path / 'audit.json'
    def attempt(owner):
        barrier.wait()
        try:
            module.reserve_receipt(output, {'owner': owner})
            return owner
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [owner for owner in pool.map(attempt, ['first', 'second']) if owner]
    assert len(winners) == 1
    assert json.loads(output.read_text()) == {'owner': winners[0], 'status': 'incomplete'}
