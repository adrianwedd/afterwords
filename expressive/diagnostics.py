"""Read-only system samples and exact call plans for private Fish diagnostics."""
import re
import subprocess
import time

from chunks import chunk_text
from expressive.generation import paragraph_segments


def call_plan(text, mode):
    if mode == 'external400':
        calls = chunk_text(text, max_chars=400)
    elif mode == 'native300':
        calls = [text]
    elif mode == 'paragraphs':
        calls = paragraph_segments(text)
    else:
        raise ValueError('unknown chunking condition')
    if ''.join(''.join(calls).split()) != ''.join(text.split()):
        raise ValueError('chunking changed spoken characters')
    return calls


def system_sample():
    import psutil
    vm = psutil.virtual_memory()
    row = {'monotonic': time.monotonic(), 'available_bytes': vm.available,
           'wired_bytes': getattr(vm, 'wired', None), 'swap_used_bytes': psutil.swap_memory().used,
           'cpu_percent': psutil.cpu_percent()}
    for name, command in [('vm_stat', ['vm_stat']),
                          ('pressure', ['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'])]:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        row[name] = result.stdout.strip() if result.returncode == 0 else None
    if row['vm_stat']:
        row['vm_counters'] = {k.strip(): int(v) for k, v in re.findall(r'^([^:\n]+):\s+(\d+)\.', row['vm_stat'], re.M)}
        match = re.search(r'page size of (\d+) bytes', row['vm_stat'])
        row['page_size'] = int(match.group(1)) if match else None
    return row


def admission(sample, cap_gib):
    reasons = []
    if sample['available_bytes'] < (cap_gib + 24)*1024**3:
        reasons.append(f'insufficient available memory: need {cap_gib + 24} GiB')
    if sample.get('pressure') != '1':
        reasons.append('memory pressure is not confirmed normal')
    return reasons


def resource_summary(samples):
    first, last = samples[0], samples[-1]
    out = {'samples': len(samples), 'available_min_bytes': min(s['available_bytes'] for s in samples),
           'available_start_bytes': first['available_bytes'], 'available_end_bytes': last['available_bytes'],
           'swap_used_start_bytes': first.get('swap_used_bytes'), 'swap_used_end_bytes': last.get('swap_used_bytes'),
           'pressure_levels': sorted({str(s.get('pressure')) for s in samples})}
    for counter in ('Swapins', 'Swapouts', 'Pageins', 'Pageouts'):
        if counter in first.get('vm_counters', {}) and counter in last.get('vm_counters', {}):
            out[counter.lower()+'_delta_bytes'] = (last['vm_counters'][counter]-first['vm_counters'][counter])*last['page_size']
    observed = [s for s in samples if 'llama_slots' in s]
    out['llama_observed_samples'] = len(observed)
    out['llama_busy_samples'] = sum(any(slot['is_processing'] for slot in s['llama_slots']) for s in observed)
    return out
