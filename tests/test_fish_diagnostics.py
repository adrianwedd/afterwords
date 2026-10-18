import pytest

from expressive.diagnostics import admission, call_plan, resource_summary


def test_conditions_preserve_words_and_paragraph_resets():
    text = ('One complete sentence. '*28)+'\n\n'+('Another sentence. '*22)
    assert len(call_plan(text, 'native300')) == 1
    assert len(call_plan(text, 'external400')) > 2
    assert len(call_plan(text, 'paragraphs')) == 2
    for mode in ('native300', 'external400', 'paragraphs'):
        assert ''.join(''.join(call_plan(text, mode)).split()) == ''.join(text.split())
    with pytest.raises(ValueError): call_plan(text, 'unknown')


def test_admission_requires_headroom_and_known_normal_pressure():
    normal = {'available_bytes': 64*1024**3, 'pressure': '1'}
    assert not admission(normal, 40)
    assert admission({**normal, 'available_bytes': 63*1024**3}, 40)
    assert admission({**normal, 'pressure': '2'}, 40)
    assert admission({**normal, 'pressure': None}, 40)
    assert admission(normal, 56)


def test_swap_summary_reports_new_activity_separately_from_historical_use():
    start = {'available_bytes': 100, 'swap_used_bytes': 9999, 'pressure': '1',
             'page_size': 16384, 'vm_counters': {'Swapins': 1000, 'Swapouts': 2000}}
    end = {**start, 'available_bytes': 80, 'vm_counters': {'Swapins': 1003, 'Swapouts': 2001},
           'llama_slots': [{'is_processing': True}]}
    summary = resource_summary([start, end])
    assert summary['swapins_delta_bytes'] == 3*16384
    assert summary['swapouts_delta_bytes'] == 16384
    assert summary['swap_used_start_bytes'] == 9999
    assert summary['available_min_bytes'] == 80
    assert summary['llama_busy_samples'] == 1


@pytest.mark.parametrize('frame_count,expected_status', [(2, 'generated_not_listening_verified'), (16, 'failed')])
def test_real_runner_retains_stream_on_budget_failure(tmp_path, monkeypatch, frame_count, expected_status):
    """Exercise receipt/audio custody through the actual CLI without GPU/models."""
    import importlib.util
    import json
    from pathlib import Path
    import sys
    from types import ModuleType, SimpleNamespace
    import wave
    import numpy as np
    import expressive.resources

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('fish_comparison_test', root/'scripts/compare-fish-longform.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sample = {'available_bytes': 128*1024**3, 'pressure': '1', 'monotonic': 1}
    monkeypatch.setattr(runner, 'system_sample', lambda: dict(sample))
    monkeypatch.setattr(expressive.resources, 'acquire_model_lease', lambda: None)
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    ref = tmp_path/'reference.wav'
    with wave.open(str(ref), 'wb') as f:
        f.setparams((1, 2, 24000, 24000, 'NONE', 'not compressed'))
        f.writeframes(b'\0\0'*24000)
    profile = tmp_path/'voice.json'
    profile.write_text(json.dumps({'reference_audio': ref.name, 'reference_text': 'Reference words.'}))
    text = tmp_path/'text.txt'
    text.write_text('A complete sentence.')
    out = tmp_path/'attempt'
    impl_file = tmp_path/'drama3.py'
    impl_file.write_text('fake implementation for runner custody test')
    impl_file.with_name('chunking.py').write_text('fake chunker')

    class Model:
        sample_rate = 44100

        def build_frames(self, *args):
            return None

        def _frames(self, *args, **kwargs):
            for _ in range(frame_count):
                yield np.zeros(10, dtype=np.int32)

        def generate(self, text, **kwargs):
            self.build_frames([], [], text)
            for _ in self._frames():
                yield SimpleNamespace(audio=np.full(64, .1, dtype=np.float32), sample_rate=44100, segment_idx=0)

    names = ['mlx', 'mlx.core', 'huggingface_hub', 'mlx_audio', 'mlx_audio.tts',
             'mlx_audio.tts.utils', 'mlx_audio.tts.models', 'mlx_audio.tts.models.fish_drama3',
             'mlx_audio.tts.models.fish_drama3.drama3']
    modules = {name: ModuleType(name) for name in names}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(modules[parent], child, module)
    core = modules['mlx.core']
    for name in ('set_memory_limit', 'set_cache_limit', 'reset_peak_memory'):
        setattr(core, name, lambda *a: None)
    core.random = SimpleNamespace(seed=lambda *a: None)
    core.get_peak_memory = lambda: 123
    modules['huggingface_hub'].snapshot_download = lambda *a, **kw: 'offline-test-model'
    modules['mlx_audio.tts.utils'].load_model = lambda *a: Model()
    implementation = modules['mlx_audio.tts.models.fish_drama3.drama3']
    implementation.__file__ = str(impl_file)
    implementation.split_text = lambda text: [text]
    monkeypatch.setattr(sys, 'argv', ['compare-fish-longform', '--text-file', str(text),
                        '--reference-profile', str(profile), '--out', str(out),
                        '--mode', 'native300', '--max-frames', '16'])
    runner.main()
    receipt = json.loads((out/'run.json').read_text())
    assert receipt['status'] == expected_status
    assert receipt['actual_backend'] == 'fish-drama3'
    assert receipt['qwen_fallback'] is False
    assert receipt['waveform']['samples'] == frame_count*64
    assert (out/'stream.f32').stat().st_size == frame_count*64*4
    assert np.load(out/'codes-000.npy').shape[0] == frame_count
    if frame_count == 16:
        assert receipt['native_chunks'][0]['eos_status'] == 'budget_exhausted_without_eos'
