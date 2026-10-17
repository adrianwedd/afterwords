#!/usr/bin/env python3
"""Run a fixed, bounded private matrix; never retry failed generations.

An explicit flag permits releasing only an idle expressive worker through its
existing guarded endpoint. The API and Vixen configuration are never restarted
or changed. Other processes and their models are never stopped.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference-profile', type=Path, required=True)
    p.add_argument('--long-text', type=Path, required=True)
    p.add_argument('--short-text', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--release-idle-sidecar', action='store_true')
    p.add_argument('--workload-url')
    p.add_argument('--observe-slots-url')
    p.add_argument('--wait-for-pid', type=int, help='Wait for this pre-existing render job to exit before any admission/release')
    p.add_argument('--wait-seconds', type=int, default=1800)
    p.add_argument('--idle-wait-seconds', type=int, default=180,
                   help='Bounded admission wait for an idle service; never retries a generation')
    p.add_argument('--case', action='append', help='Select named matrix conditions without repeating other takes')
    a = p.parse_args()
    if a.out.exists(): p.error('output exists; preserve previous matrices')
    a.out.mkdir(parents=True, mode=0o700)
    matrix = [dict(id='long-'+m, mode=m, text=a.long_text, frames=1600) for m in ('external400', 'native300', 'paragraphs')]
    matrix += [dict(id=f'budget-{n}', mode='native300', text=a.short_text, frames=n) for n in (128, 512, 1600)]
    if a.workload_url:
        matrix += [dict(id='short-concurrent', mode='native300', text=a.short_text, frames=1600, concurrent=True),
                   dict(id='short-after', mode='native300', text=a.short_text, frames=1600)]
    if a.case:
        if set(a.case)-{case['id'] for case in matrix}:
            p.error('unknown or unavailable matrix condition')
        matrix = [case for case in matrix if case['id'] in a.case]
    receipt = {'schema': 'afterwords-fish-matrix/1', 'status': 'running', 'attempts': []}
    def save():
        (a.out/'matrix.json').write_text(json.dumps(receipt, indent=2)+'\n')
    save()
    if a.wait_for_pid:
        import psutil
        try:
            protected = psutil.Process(a.wait_for_pid)
            identity = protected.create_time()
        except psutil.NoSuchProcess:
            protected, identity = None, None
        receipt['protected_job'] = {'pid': a.wait_for_pid, 'create_time': identity}
        deadline = time.monotonic() + a.wait_seconds
        while protected and protected.is_running() and protected.create_time() == identity:
            receipt['status'] = 'waiting_for_existing_render_job'
            save()
            if time.monotonic() >= deadline:
                receipt.update(status='not_admitted', reason='existing render job remains active; no interruption')
                save()
                return
            time.sleep(2)
        receipt['status'] = 'running'
        save()
    opener = build_opener(ProxyHandler({}))
    for case in matrix:
        out = a.out/case['id']
        command = [sys.executable, str(ROOT/'scripts/compare-fish-longform.py'),
                   '--reference-profile', str(a.reference_profile.resolve()), '--text-file', str(case['text'].resolve()),
                   '--out', str(out.resolve()), '--mode', case['mode'], '--max-frames', str(case['frames']), '--timeout', '360']
        if a.observe_slots_url: command += ['--observe-slots-url', a.observe_slots_url]
        if case.get('concurrent'): command += ['--workload-url', a.workload_url]
        row = {'id': case['id'], 'command': command, 'status': 'preflight'}
        receipt['attempts'].append(row)
        if a.release_idle_sidecar:
            try:
                with opener.open('http://127.0.0.1:7861/health', timeout=5) as response:
                    health = json.load(response)
                row['sidecar_before'] = health
                deadline = time.monotonic() + a.idle_wait_seconds
                quiet_since = None
                while time.monotonic() < deadline:
                    if health['pending'] == 0:
                        quiet_since = quiet_since or time.monotonic()
                        if time.monotonic()-quiet_since >= 5:
                            break
                    else:
                        quiet_since = None
                    time.sleep(1)
                    with opener.open('http://127.0.0.1:7861/health', timeout=5) as response:
                        health = json.load(response)
                row['sidecar_at_admission'] = health
                if health['pending']:
                    row.update(status='not_admitted', reason='active expressive requests; no interruption')
                    save()
                    continue
                if health['worker_alive']:
                    request = Request('http://127.0.0.1:7861/release', data=b'', method='POST')
                    with opener.open(request, timeout=5) as response:
                        row['idle_release'] = json.load(response)
            except Exception as exc:
                row.update(status='not_admitted', reason=str(exc))
                save()
                continue
        save()
        with (a.out/(case['id']+'.log')).open('x') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=ROOT)
            row.update(status='running', pid=process.pid)
            save()
            try:
                row['exit_code'] = process.wait(timeout=480)
                run_file = out/'run.json'
                row['status'] = json.loads(run_file.read_text())['status'] if run_file.exists() else 'failed_before_receipt'
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                row.update(status='supervisor_timeout', reason='diagnostic process group stopped; raw stream.f32 retained')
        save()
        print(json.dumps({'id': row['id'], 'status': row['status']}), flush=True)
    receipt['status'] = 'finished_attempts_not_qualification'
    save()


if __name__ == '__main__':
    main()
