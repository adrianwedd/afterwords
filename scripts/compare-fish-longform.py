#!/usr/bin/env python3
"""Bounded direct-model diagnostics. No Qwen, playback or routing changes.

Every invocation is a new retained attempt, including admission refusals.
Use an outer process timeout as protection against a stalled Metal operation.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from expressive.contracts import MODEL, REVISION
from expressive.diagnostics import admission, call_plan, system_sample, resource_summary


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--text-file', type=Path, required=True)
    p.add_argument('--reference-profile', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--mode', choices=['external400', 'native300', 'paragraphs'], required=True)
    p.add_argument('--max-frames', type=int, default=1600)
    p.add_argument('--seed', type=int, default=20261017)
    p.add_argument('--model', default=MODEL)
    p.add_argument('--revision', default=REVISION)
    p.add_argument('--timeout', type=float, default=360)
    p.add_argument('--workload-url', help='Controlled concurrent inference on an already resident idle loopback llama server')
    p.add_argument('--observe-slots-url', help='Read-only loopback llama slots telemetry, including Fish-only conditions')
    a = p.parse_args()
    pins = json.loads((ROOT/'qa/expressive-voice/pins.json').read_text())['models']
    if pins.get(a.model) != a.revision or a.model not in (MODEL, 'mlx-community/fish-audio-drama-3-8bit'):
        p.error('use a pinned 4-bit or 8-bit model/revision pair')
    if not 16 <= a.max_frames <= 4000 or not 0 < a.timeout <= 600:
        p.error('frame budget 16–4000; timeout 0–600 seconds')
    if a.out.exists():
        p.error('preserve previous attempts; output directory exists')
    # Restrict workload traffic to a numeric loopback address, no proxies/secrets.
    if a.workload_url:
        from urllib.parse import urlparse
        u = urlparse(a.workload_url)
        if u.scheme != 'http' or u.hostname != '127.0.0.1' or u.path != '/completion' or u.username or u.password or u.query:
            p.error('workload URL must be http://127.0.0.1:PORT/completion')
    if a.observe_slots_url:
        from urllib.parse import urlparse
        u = urlparse(a.observe_slots_url)
        if u.scheme != 'http' or u.hostname != '127.0.0.1' or u.path != '/slots' or u.username or u.password or u.query:
            p.error('slots URL must be http://127.0.0.1:PORT/slots')
    text = a.text_file.read_text()
    calls = call_plan(text, a.mode)
    profile = json.loads(a.reference_profile.read_text())
    reference = a.reference_profile.parent / profile['reference_audio']
    raw = reference.read_bytes()
    from expressive.reference import normalize_reference
    conditioning, conversion = normalize_reference(raw)
    if not profile.get('reference_text', '').strip():
        p.error('literal reference transcript required')
    a.out.mkdir(parents=True, mode=0o700)
    receipt = {'schema': 'afterwords-fish-longform/1', 'status': 'preflight',
               'created_at': datetime.now(timezone.utc).isoformat(),
               'actual_backend': 'not_started', 'requested_backend': 'fish-drama3', 'qwen_fallback': False,
               'model': a.model, 'revision': a.revision, 'quantisation': '8bit' if a.model.endswith('8bit') else '4bit',
               'mode': a.mode, 'seed': a.seed, 'max_frames_per_native_chunk': a.max_frames,
               'timeout_seconds': a.timeout, 'text': text, 'text_sha256': sha(text.encode()),
               'reference': str(reference.resolve()), 'reference_sha256': sha(raw),
               'reference_text': profile['reference_text'], 'reference_text_sha256': sha(profile['reference_text'].encode()),
               'conditioning_sha256': sha(conditioning), 'conditioning_conversion': conversion,
               'calls': [{'text': t, 'utf8_bytes': len(t.encode()), 'text_sha256': sha(t.encode())} for t in calls],
               'native_chunks': [], 'system_samples': [system_sample()],
               'acoustic_acceptance': 'unverified', 'workload': {'kind': 'resident_llama' if a.workload_url else 'none'},
               'source_hashes': {str(f.relative_to(ROOT)): sha(f.read_bytes()) for f in
                                 [Path(__file__), ROOT/'chunks.py', ROOT/'expressive/diagnostics.py']}}
    def save():
        # Atomic replacement only within this newly claimed attempt.
        temp = a.out/'run.json.tmp'
        temp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False)+'\n')
        temp.replace(a.out/'run.json')
    save()
    cap = 56 if a.model.endswith('8bit') else 40
    reasons = admission(receipt['system_samples'][0], cap)
    if reasons:
        receipt.update(status='not_admitted', reasons=reasons)
        save()
        return 2
    from expressive.resources import acquire_model_lease
    try:
        acquire_model_lease()
    except RuntimeError as exc:
        receipt.update(status='not_admitted', reasons=[str(exc)])
        save()
        return 2
    stop = threading.Event()
    unsafe = threading.Event()
    def monitor():
        while not stop.wait(2):
            row = system_sample()
            if a.observe_slots_url:
                from urllib.request import build_opener, ProxyHandler
                try:
                    with build_opener(ProxyHandler({})).open(a.observe_slots_url, timeout=2) as response:
                        slots = json.load(response)
                    row['llama_slots'] = [{'id': s['id'], 'is_processing': s['is_processing']} for s in slots]
                except Exception as exc:
                    row['slots_error'] = str(exc)
            receipt['system_samples'].append(row)
            if row.get('pressure') not in ('1',) or row['available_bytes'] < 16*1024**3:
                unsafe.set()
            first = receipt['system_samples'][0]
            delta = row.get('vm_counters', {}).get('Swapouts', 0) - first.get('vm_counters', {}).get('Swapouts', 0)
            if delta * row.get('page_size', 16384) > 256*1024**2:
                unsafe.set()
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    workload_thread = None
    started = time.perf_counter()
    try:
        os.environ['HF_HUB_OFFLINE'] = '1'
        import mlx.core as mx
        import numpy as np
        import soundfile as sf
        from huggingface_hub import snapshot_download
        from mlx_audio.tts.utils import load_model
        import mlx_audio.tts.models.fish_drama3.drama3 as implementation
        impl_path = Path(implementation.__file__)
        receipt['implementation_sha256'] = sha(impl_path.read_bytes())
        receipt['native_chunker_sha256'] = sha(impl_path.with_name('chunking.py').read_bytes())
        for call in receipt['calls']:
            call['planned_native_chunks'] = implementation.split_text(call['text'])
        receipt['native_history_policy'] = 'first chunk pinned; latest chunk retained; resets at each external call'
        mx.set_memory_limit(cap*1024**3)
        mx.set_cache_limit(2*1024**3)
        load_start = time.perf_counter()
        receipt['status'] = 'loading'
        save()
        snapshot = Path(snapshot_download(a.model, revision=a.revision, local_files_only=True))
        if (snapshot/'config.json').exists():
            config_raw = (snapshot/'config.json').read_bytes()
            quant = json.loads(config_raw).get('quantization', {})
            receipt['checkpoint_quantization'] = {
                'config_sha256': sha(config_raw), 'default_bits': quant.get('bits'),
                'group_size': quant.get('group_size'),
                'module_override_bits': dict(Counter(str(v['bits']) for v in quant.values()
                                                     if isinstance(v, dict) and 'bits' in v))}
        model = load_model(str(snapshot))
        if hasattr(model, 'named_modules'):
            quant_modules = [(name, module.bits) for name, module in model.named_modules()
                             if isinstance(getattr(module, 'bits', None), int)]
            receipt['loaded_quantization'] = {
                'module_bit_counts': dict(Counter(str(bits) for _, bits in quant_modules)),
                'examples': {str(bits): next(name for name, b in quant_modules if b == bits)
                             for bits in sorted({bits for _, bits in quant_modules})}}
        receipt.update(load_seconds=time.perf_counter()-load_start, actual_backend='fish-drama3')
        (a.out/'conditioning.wav').write_bytes(conditioning)
        if a.workload_url:
            from urllib.request import Request, build_opener, ProxyHandler
            opener = build_opener(ProxyHandler({}))
            slots_url = a.workload_url.rsplit('/', 1)[0]+'/slots'
            with opener.open(slots_url, timeout=5) as response:
                slots = json.load(response)
            if not isinstance(slots, list) or any(s.get('is_processing') for s in slots):
                raise RuntimeError('concurrent workload not admitted: resident server is busy or slots unknown')
            request_body = {'prompt': 'Explain how a lighthouse works in plain English.', 'n_predict': 128,
                            'temperature': 0, 'seed': a.seed, 'cache_prompt': False, 'id_slot': 0}
            receipt['workload'].update(url=a.workload_url, request=request_body, calls=[])
            try:
                with opener.open(a.workload_url.rsplit('/', 1)[0]+'/props', timeout=5) as response:
                    props = json.load(response)
                receipt['workload']['resident_model'] = {k: props[k] for k in ('model_path', 'model_alias', 'model_ftype', 'total_slots', 'build_info') if k in props}
            except Exception as exc:
                raise RuntimeError('cannot establish resident workload model identity') from exc
            def workload_call(phase):
                tick = time.perf_counter()
                row = {'phase': phase, 'start_monotonic': time.monotonic()}
                receipt['workload']['calls'].append(row)
                try:
                    req = Request(a.workload_url, data=json.dumps(request_body).encode(), headers={'Content-Type':'application/json'})
                    with opener.open(req, timeout=60) as response:
                        result = json.load(response)
                    row.update(status='completed', wall_seconds=time.perf_counter()-tick,
                               timings=result.get('timings'), tokens_predicted=result.get('tokens_predicted'),
                               model=result.get('model'), content_sha256=sha(result.get('content','').encode()))
                except Exception as exc:
                    row.update(status='failed', error=str(exc))
                row['end_monotonic'] = time.monotonic()
                return row['status'] == 'completed'
            workload_call('before_fish_generation')
            def workload():
                # At most four local calls, no retry on failure. Stop launching
                # calls when Fish ends; a current call has a 60-second deadline.
                for _ in range(4):
                    if stop.is_set(): break
                    if not workload_call('concurrent'): break
            workload_thread = threading.Thread(target=workload, daemon=True)
            workload_thread.start()
        original_build, original_frames = model.build_frames, model._frames
        native = None
        call_index = 0
        generation_started = time.perf_counter()
        receipt['generation_start_monotonic'] = time.monotonic()
        def build(references, history, target):
            nonlocal native
            native = {'index': len(receipt['native_chunks']), 'call_index': call_index,
                      'text': target, 'utf8_bytes': len(target.encode()),
                      'history_texts': [h[0] for h in history],
                      'history_frame_counts': [h[1].shape[1] for h in history],
                      'start_seconds': time.perf_counter()-generation_started, 'frames': 0,
                      'eos_status': 'not_observed', 'audio_pieces': []}
            receipt['native_chunks'].append(native)
            save()
            return original_build(references, history, target)
        def frames(*args, **kwargs):
            codes = []
            try:
                for frame in original_frames(*args, **kwargs):
                    codes.append(np.asarray(frame))
                    native['frames'] += 1
                    if unsafe.is_set(): raise RuntimeError('resource guard: memory pressure or available memory below 16 GiB')
                    if time.perf_counter()-generation_started > a.timeout:
                        raise TimeoutError('generation deadline exceeded')
                    yield frame
                if len(codes) >= a.max_frames:
                    native['eos_status'] = 'budget_exhausted_without_eos'
                    raise RuntimeError('frame budget exhausted without verified EOS')
                native['eos_status'] = 'upstream_return_before_budget'
            finally:
                native['end_seconds'] = time.perf_counter()-generation_started
                if codes:
                    file = f"codes-{native['index']:03d}.npy"
                    np.save(a.out/file, np.stack(codes))
                    native['codes_file'] = file
                save()
        model.build_frames, model._frames = build, frames
        receipt['status'] = 'generating'
        mx.reset_peak_memory()
        sample_count = 0
        receipt['raw_audio_format'] = {'file': 'stream.f32', 'dtype': '<f4', 'sample_rate': 44100, 'channels': 1}
        with sf.SoundFile(a.out/'retained.wav', mode='w', samplerate=44100, channels=1, subtype='PCM_16') as output, (a.out/'stream.f32').open('xb') as raw_output:
            for call_index, segment in enumerate(calls):
                mx.random.seed(a.seed)
                call = receipt['calls'][call_index]
                call['start_seconds'] = time.perf_counter()-generation_started
                call['start_sample'] = sample_count
                for result in model.generate(text=segment, ref_audio=str(a.out/'conditioning.wav'),
                        ref_text=profile['reference_text'], stream=True, first_chunk_frames=4,
                        max_tokens=a.max_frames, temperature=.7, top_p=.7, top_k=30):
                    audio = np.asarray(result.audio, dtype=np.float32)
                    if result.sample_rate != 44100 or audio.ndim != 1 or not np.isfinite(audio).all():
                        raise RuntimeError('invalid generated waveform')
                    if len(audio):
                        arrival = time.perf_counter()-generation_started
                        receipt.setdefault('ttfa_seconds', arrival)
                        native['audio_pieces'].append({'arrival_seconds': arrival, 'start_sample': sample_count,
                                                       'samples': len(audio), 'native_segment_idx': result.segment_idx})
                        output.write(audio)
                        output.flush()
                        raw_output.write(audio.astype('<f4').tobytes())
                        raw_output.flush()
                        sample_count += len(audio)
                        if sample_count > 44100*300: raise RuntimeError('five-minute output bound exceeded')
                call.update(end_sample=sample_count, end_seconds=time.perf_counter()-generation_started)
                save()
        receipt['status'] = 'generated_not_listening_verified' if sample_count else 'failed_empty'
    except BaseException as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    finally:
        if 'generation_started' in locals():
            receipt['generation_seconds'] = time.perf_counter()-generation_started
            receipt['generation_end_monotonic'] = time.monotonic()
        stop.set()
        monitor_thread.join(timeout=6)
        if workload_thread:
            workload_thread.join(timeout=60)
            if not workload_thread.is_alive():
                workload_call('after_fish_generation')
        receipt['system_samples'].append(system_sample())
        receipt['resources'] = resource_summary(receipt['system_samples'])
        receipt['wall_seconds'] = time.perf_counter()-started
        receipt['ended_at'] = datetime.now(timezone.utc).isoformat()
        if 'mx' in locals(): receipt['peak_metal_bytes'] = mx.get_peak_memory()
        audio_path = a.out/'retained.wav'
        if audio_path.exists():
            import soundfile as sf
            from expressive.audio_audit import waveform
            audio, rate = sf.read(audio_path, dtype='float32')
            if len(audio):
                receipt['waveform'] = waveform(audio, rate)
                receipt['audio_sha256'] = sha(audio_path.read_bytes())
                receipt['rtf'] = receipt.get('generation_seconds', 0)/(len(audio)/rate)
                if receipt['waveform']['longest_silence_seconds'] >= 10 and receipt['status'] == 'generated_not_listening_verified':
                    receipt['status'] = 'generated_rejected_silence'
        save()
        print(json.dumps({k:receipt.get(k) for k in ('status','mode','error','generation_seconds','rtf','peak_metal_bytes')}), flush=True)
    return 0 if receipt['status'] == 'generated_not_listening_verified' else 1


if __name__ == '__main__':
    sys.exit(main())
