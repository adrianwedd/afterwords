"""Tests for the backends/ registry + protocol — no model load."""
from __future__ import annotations

import pytest

import backends
from backends.base import Backend, PreparedVoice, RefTextPolicy, _read_only, resolve_repo_dir


@pytest.fixture(autouse=True)
def _clean_registry():
    backends.reset_for_tests()
    yield
    backends.reset_for_tests()


def test_register_all_populates_shipped_backends():
    backends.register_all()
    assert set(backends.names()) == {
        "qwen3-0.6b", "qwen3-1.7b", "voxtral",
        "openvoice-v2", "f5-tts", "cosyvoice2", "gpt-sovits", "xtts-v2",
        "indextts-2", "neutts-air", "spark-tts", "dia2", "yourtts",
        "firered-tts-2", "sv2tts", "mockingbird", "soprotts",
    }


def test_register_all_isolates_experimental_failures(monkeypatch):
    """A broken experimental backend logs and skips, leaving qwen3 + others intact."""
    import importlib
    real_import = importlib.import_module

    def boom_one(name, package=None):
        if name == ".voxtral":
            raise ImportError("simulated dep missing for voxtral")
        return real_import(name, package=package)

    monkeypatch.setattr(importlib, "import_module", boom_one)
    backends.register_all()
    names = set(backends.names())
    # primary path is unaffected
    assert {"qwen3-0.6b", "qwen3-1.7b"} <= names
    # broken backend is skipped, not crashed
    assert "voxtral" not in names
    # at least some other experimental backends still register
    assert names & {"xtts-v2", "f5-tts", "dia2"}


def test_each_registered_backend_satisfies_protocol():
    backends.register_all()
    for name in backends.names():
        b = backends.get(name)
        assert isinstance(b, Backend)
        assert isinstance(b.sample_rate, int) and b.sample_rate > 0
        assert isinstance(b.ref_text_policy, RefTextPolicy)
        assert isinstance(b.name, str) and b.name == name


def test_duplicate_register_raises():
    backends.register_all()
    b = backends.get("qwen3-0.6b")
    with pytest.raises(ValueError, match="already registered"):
        backends.register(b)


def test_slug_collision_raises():
    backends.register_all()
    class _Fake:
        name = "qwen3-06b"  # slugs to "qwen3-06b", collides with qwen3-0.6b
        display_name = "fake"
        sample_rate = 16000
        ref_text_policy = RefTextPolicy.OPTIONAL
        supported_langs = ()
        def load(self): pass
        def validate_extras(self, e): pass
        def prepare_voice(self, *a, **k): raise NotImplementedError
        def synthesize(self, *a, **k): raise NotImplementedError
    with pytest.raises(ValueError, match="slug collision"):
        backends.register(_Fake())


def test_get_unknown_raises():
    backends.register_all()
    with pytest.raises(KeyError, match="unknown backend"):
        backends.get("nope")


def test_max_sample_rate_reflects_highest_backend():
    backends.register_all()
    # Highest among shipped backends: f5-tts is 24000, voxtral is 24000, etc.
    # Just assert it's a positive int >= the qwen3 sample rate.
    assert backends.max_sample_rate() >= 24000


def test_slug_strips_dots():
    assert backends.slug("qwen3-0.6b") == "qwen3-06b"
    assert backends.slug("qwen3-1.7b") == "qwen3-17b"
    assert backends.slug("voxtral") == "voxtral"


def test_prepared_voice_extras_are_readonly():
    pv = PreparedVoice(
        ref_audio_path="/tmp/x.wav",
        ref_text=None,
        extras={"a": 1},
    )
    with pytest.raises(TypeError):
        pv.extras["b"] = 2  # MappingProxyType blocks mutation


def test_prepared_voice_wraps_plain_dict():
    pv = PreparedVoice(ref_audio_path="/tmp/x.wav", ref_text=None, extras={"a": 1})
    # __post_init__ should have wrapped in MappingProxyType
    from types import MappingProxyType
    assert isinstance(pv.extras, MappingProxyType)


def test_backend_synthesize_requires_lang():
    """Backend.synthesize must take `lang` as a required parameter (no default on Protocol)."""
    import inspect
    sig = inspect.signature(Backend.synthesize)
    params = sig.parameters
    assert "lang" in params, "Backend.synthesize missing `lang` parameter"
    assert params["lang"].default is inspect.Parameter.empty, \
        "Backend.synthesize.lang must be required (no default on Protocol)"


def test_all_registered_backends_accept_lang_keyword():
    """Every registered backend's synthesize must accept `lang`.

    Distinct from `test_backend_synthesize_requires_lang` (which inspects the Protocol).
    Python's `@runtime_checkable` Protocol only checks attribute existence, not signature
    compatibility — a concrete class with `synthesize(self, text, prepared)` (no `lang`)
    would pass `isinstance(x, Backend)`. This test inspects each instance's bound method
    signature to catch that class of bug.
    """
    import inspect
    for name in backends.names():
        b = backends.get(name)
        sig = inspect.signature(b.synthesize)
        assert "lang" in sig.parameters, f"backend {name!r} missing lang kwarg"


def _write_silence_wav(tmp_path):
    """Helper: write a tiny 44.1 kHz silent WAV. Returns its path."""
    import soundfile as sf
    import numpy as np
    p = str(tmp_path / "ref.wav")
    sf.write(p, np.zeros(4410, dtype=np.float32), 44100)
    return p


def test_qwen3_prepare_voice_buffers_ref_audio_for_toctou(tmp_path):
    """Regression: qwen3 must pre-load ref audio bytes in prepare_voice() so
    a DELETE /session that removes the source file does NOT break an
    in-flight synthesize() call (C3 TOCTOU fix from commit 5289576)."""
    import os
    import numpy as np
    from backends.qwen3 import Qwen3Backend
    from backends.base import PreparedVoice

    backend = Qwen3Backend("0.6B")
    ref_path = _write_silence_wav(tmp_path)
    prepared = backend.prepare_voice(ref_path, "reference text", {})

    # prepare_voice must capture bytes — synthesize() must never re-open the file.
    assert isinstance(prepared, PreparedVoice)
    assert prepared.data is not None, "qwen3 prepare_voice must buffer ref audio bytes"
    assert isinstance(prepared.data, (bytes, bytearray))
    assert len(prepared.data) > 0
    # Verify bytes match disk content at prepare time.
    with open(ref_path, "rb") as fh:
        assert prepared.data == fh.read()

    # Simulate DELETE /session removing the underlying ref file mid-run.
    os.remove(ref_path)
    assert not os.path.exists(ref_path)

    # Stub the model and generate_audio to assert the path passed in is the
    # buffered tempfile, not the now-deleted prepared.ref_audio_path.
    captured = {}

    def fake_generate_audio(**kwargs):
        captured.update(kwargs)
        # Write a tiny output WAV so synthesize's sf.read path succeeds.
        import soundfile as sf
        out = os.path.join(kwargs["output_path"], "out_000.wav")
        sf.write(out, np.zeros(10, dtype=np.float32), 24000)

    import sys
    import types as _types

    # Snapshot any existing real entries so we can restore them — avoids cross-test
    # pollution of sys.modules for tests that monkeypatch mlx_audio.tts.generate later.
    _saved = {k: sys.modules.get(k) for k in ("mlx_audio", "mlx_audio.tts", "mlx_audio.tts.generate")}
    pkg = _types.ModuleType("mlx_audio")
    tts_pkg = _types.ModuleType("mlx_audio.tts")
    gen_mod = _types.ModuleType("mlx_audio.tts.generate")
    gen_mod.generate_audio = fake_generate_audio
    # Wire submodules as attributes so pytest's monkeypatch.setattr can walk the tree.
    pkg.tts = tts_pkg
    tts_pkg.generate = gen_mod
    sys.modules["mlx_audio"] = pkg
    sys.modules["mlx_audio.tts"] = tts_pkg
    sys.modules["mlx_audio.tts.generate"] = gen_mod
    backend._model = object()  # synthesize() guards against None; any value is fine

    try:
        audio, sr = backend.synthesize("hello", prepared, lang="en")
    finally:
        for k, v in _saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    assert sr == 24000
    # The ref_audio passed to generate_audio must point at a file that exists
    # (the freshly written tempfile), proving TOCTOU is closed.
    assert os.path.basename(captured["ref_audio"]) == "ref.wav"
    assert captured["ref_text"] == "reference text"
    assert captured["lang_code"] == "en"


def test_voxtral_prepare_ignores_ref_text_and_preserves_extras():
    from backends.voxtral import VoxtralBackend
    from backends.base import RefTextPolicy

    backend = VoxtralBackend()
    assert backend.ref_text_policy is RefTextPolicy.IGNORED

    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "not used by voxtral",
        {"voice": "fr_female", "temperature": 0.7},
    )

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text is None
    assert prepared.extras["voice"] == "fr_female"
    assert prepared.extras["temperature"] == 0.7


def test_voxtral_validate_extras_rejects_unknown_and_invalid_voice():
    from backends.voxtral import VoxtralBackend

    backend = VoxtralBackend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"cfg_value": 2.0})
    with pytest.raises(ValueError, match="voice must be one of"):
        backend.validate_extras({"voice": "picard"})


def test_voxtral_synthesize_uses_language_default_voice():
    from types import SimpleNamespace
    import numpy as np
    from backends.voxtral import VoxtralBackend
    from backends.base import PreparedVoice, _read_only

    backend = VoxtralBackend()
    captured_kwargs = {}

    class _CapturingModel:
        def generate(self, **kwargs):
            captured_kwargs.update(kwargs)
            yield SimpleNamespace(
                audio=np.full(10, 0.25, dtype=np.float32),
                sample_rate=24000,
            )

    backend._model = _CapturingModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    audio, sr = backend.synthesize("bonjour", prepared, lang="fr")

    assert sr == 24000
    assert captured_kwargs["voice"] == "fr_male"
    assert captured_kwargs["text"] == "bonjour"
    assert captured_kwargs["verbose"] is False
    assert audio.shape == (10,)
    assert np.allclose(audio, 0.25)


def test_voxtral_synthesize_uses_voice_extra_and_concatenates_chunks():
    from types import SimpleNamespace
    import numpy as np
    from backends.voxtral import VoxtralBackend
    from backends.base import PreparedVoice, _read_only

    backend = VoxtralBackend()
    captured_kwargs = {}

    class _CapturingModel:
        def generate(self, **kwargs):
            captured_kwargs.update(kwargs)
            yield SimpleNamespace(audio=np.full(4, 0.1, dtype=np.float32))
            yield SimpleNamespace(audio=np.full(6, 0.2, dtype=np.float32))

    backend._model = _CapturingModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({"voice": "hi_female", "max_tokens": 32}),
    )

    audio, sr = backend.synthesize("namaste", prepared, lang="hi")

    assert sr == 24000
    assert captured_kwargs["voice"] == "hi_female"
    assert captured_kwargs["max_tokens"] == 32
    assert audio.shape == (10,)
    assert np.allclose(audio[:4], 0.1)
    assert np.allclose(audio[4:], 0.2)


def test_indextts2_prepare_voice_allows_optional_ref_text():
    from backends.indextts_2 import IndexTTS2Backend
    from backends.base import RefTextPolicy

    backend = IndexTTS2Backend()
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL

    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  ",
        {"emo_alpha": 0.4, "use_emo_text": True, "emo_text": "calm"},
    )

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text is None
    assert prepared.extras["emo_alpha"] == 0.4
    assert prepared.extras["use_emo_text"] is True


def test_indextts2_validate_extras_rejects_unknown_and_invalid_emotion_vector():
    from backends.indextts_2 import IndexTTS2Backend

    backend = IndexTTS2Backend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="emo_vector must be a sequence of 8"):
        backend.validate_extras({"emo_vector": [0.1, 0.2]})
    with pytest.raises(ValueError, match="emo_alpha must be between 0 and 1"):
        backend.validate_extras({"emo_alpha": 1.5})


def test_indextts2_synthesize_passes_emotion_and_duration_controls():
    import numpy as np
    from backends.indextts_2 import IndexTTS2Backend
    from backends.base import PreparedVoice, _read_only

    backend = IndexTTS2Backend()
    captured_kwargs = {}

    class _CapturingModel:
        def infer(self, **kwargs):
            captured_kwargs.update(kwargs)
            return 22050, np.full(12, 1000, dtype=np.int16)

    backend._model = _CapturingModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({
            "emo_audio_prompt": "/tmp/emo.wav",
            "emo_alpha": 0.7,
            "max_mel_tokens": 600,
            "max_text_tokens_per_segment": 80,
            "top_p": 0.75,
        }),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 22050
    assert audio.dtype == np.float32
    assert audio.shape == (12,)
    assert np.allclose(audio, np.full(12, 1000 / 32767, dtype=np.float32))
    assert captured_kwargs["spk_audio_prompt"] == "/tmp/ref.wav"
    assert captured_kwargs["text"] == "hello"
    assert captured_kwargs["output_path"] is None
    assert captured_kwargs["emo_audio_prompt"] == "/tmp/emo.wav"
    assert captured_kwargs["emo_alpha"] == 0.7
    assert captured_kwargs["max_mel_tokens"] == 600
    assert captured_kwargs["max_text_tokens_per_segment"] == 80
    assert captured_kwargs["top_p"] == 0.75


def test_indextts2_synthesize_rejects_unsupported_lang():
    from backends.indextts_2 import IndexTTS2Backend
    from backends.base import PreparedVoice, _read_only

    backend = IndexTTS2Backend()
    backend._model = object()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='ja'"):
        backend.synthesize("hello", prepared, lang="ja")


def test_indextts2_synthesize_raises_on_empty_output():
    import numpy as np
    from backends.indextts_2 import IndexTTS2Backend
    from backends.base import PreparedVoice, _read_only

    backend = IndexTTS2Backend()

    class _EmptyModel:
        def infer(self, **kwargs):
            return 22050, np.array([], dtype=np.float32)

    backend._model = _EmptyModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_neutts_air_metadata():
    from backends.neutts_air import NeuTTSAirBackend

    backend = NeuTTSAirBackend()

    assert backend.name == "neutts-air"
    assert backend.display_name == "NeuTTS Air (Apache-2.0)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en",)


def test_neutts_air_prepare_voice_preencodes_reference_when_loaded():
    import numpy as np
    from backends.neutts_air import NeuTTSAirBackend

    backend = NeuTTSAirBackend()

    class _NeuTTS:
        def encode_reference(self, ref_audio_path):
            assert ref_audio_path == "/tmp/ref.wav"
            return np.array([1, 2, 3], dtype=np.int64)

    backend._model = _NeuTTS()

    prepared = backend.prepare_voice("/tmp/ref.wav", " reference text ", {})

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference text"
    assert np.array_equal(prepared.extras["ref_codes"], np.array([1, 2, 3]))


def test_neutts_air_rejects_unknown_extras():
    from backends.neutts_air import NeuTTSAirBackend

    backend = NeuTTSAirBackend()

    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"temperature": 0.8})


def test_neutts_air_synthesize_uses_preencoded_reference():
    import numpy as np
    from backends.neutts_air import NeuTTSAirBackend

    backend = NeuTTSAirBackend()
    captured = {}

    class _NeuTTS:
        def encode_reference(self, ref_audio_path):
            raise AssertionError("preencoded ref_codes should be reused")

        def infer(self, text, ref_codes, ref_text):
            captured["text"] = text
            captured["ref_codes"] = ref_codes
            captured["ref_text"] = ref_text
            return np.array([[0.1, -0.2]], dtype=np.float64)

    ref_codes = np.array([4, 5, 6], dtype=np.int64)
    backend._model = _NeuTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference text",
        extras=_read_only({"ref_codes": ref_codes}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured == {
        "text": "hello",
        "ref_codes": ref_codes,
        "ref_text": "reference text",
    }


def test_neutts_air_synthesize_rejects_unsupported_lang_and_empty_output():
    import numpy as np
    from backends.neutts_air import NeuTTSAirBackend

    backend = NeuTTSAirBackend()

    class _NeuTTS:
        def encode_reference(self, ref_audio_path):
            return [1]

        def infer(self, text, ref_codes, ref_text):
            return np.array([], dtype=np.float32)

    backend._model = _NeuTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='fr'"):
        backend.synthesize("bonjour", prepared, lang="fr")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_spark_tts_metadata():
    from backends.spark_tts import SparkTTSBackend

    backend = SparkTTSBackend()

    assert backend.name == "spark-tts"
    assert backend.display_name == "Spark-TTS-0.5B (CC-BY-NC-SA 4.0 weights)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en", "zh")


def test_spark_tts_prepare_voice_allows_optional_ref_text():
    from backends.spark_tts import SparkTTSBackend

    backend = SparkTTSBackend()
    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  ",
        {"temperature": 0.7, "top_k": 40, "top_p": 0.9},
    )

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text is None
    assert prepared.extras["temperature"] == 0.7
    assert prepared.extras["top_k"] == 40
    assert prepared.extras["top_p"] == 0.9


def test_spark_tts_validate_extras_rejects_unknown_and_invalid_values():
    from backends.spark_tts import SparkTTSBackend

    backend = SparkTTSBackend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="top_k must be an integer"):
        backend.validate_extras({"top_k": 12.5})
    with pytest.raises(ValueError, match="temperature must be > 0"):
        backend.validate_extras({"temperature": 0})


def test_spark_tts_synthesize_calls_inference_with_prompt_and_sampling_extras():
    import numpy as np
    from pathlib import Path
    from backends.spark_tts import SparkTTSBackend

    backend = SparkTTSBackend()
    captured_kwargs = {}

    class _SparkTTS:
        sample_rate = 24000

        def inference(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([[0.1, -0.2]], dtype=np.float64)

    backend._model = _SparkTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference transcript",
        extras=_read_only({"temperature": 0.65, "top_k": 25, "top_p": 0.85}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured_kwargs == {
        "text": "hello",
        "prompt_speech_path": Path("/tmp/ref.wav"),
        "prompt_text": "reference transcript",
        "temperature": 0.65,
        "top_k": 25,
        "top_p": 0.85,
    }


def test_spark_tts_synthesize_rejects_unsupported_lang_and_empty_output():
    import numpy as np
    from backends.spark_tts import SparkTTSBackend

    backend = SparkTTSBackend()

    class _SparkTTS:
        sample_rate = 24000

        def inference(self, **kwargs):
            return np.array([], dtype=np.float32)

    backend._model = _SparkTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='ja'"):
        backend.synthesize("konnichiwa", prepared, lang="ja")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_dia2_metadata():
    from backends.dia2 import Dia2Backend

    backend = Dia2Backend()

    assert backend.name == "dia2"
    assert backend.display_name == "Dia2 (Nari Labs Apache-2.0)"
    assert backend.sample_rate == 44100
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en",)


def test_dia2_prepare_voice_allows_optional_ref_text():
    from backends.dia2 import Dia2Backend

    backend = Dia2Backend()
    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  reference transcript  ",
        {"temperature": 0.7, "top_k": 40, "cfg_scale": 3.0},
    )

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference transcript"
    assert prepared.extras["temperature"] == 0.7
    assert prepared.extras["top_k"] == 40
    assert prepared.extras["cfg_scale"] == 3.0


def test_dia2_validate_extras_rejects_unknown_and_invalid_values():
    from backends.dia2 import Dia2Backend

    backend = Dia2Backend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="top_k must be an integer"):
        backend.validate_extras({"top_k": 12.5})
    with pytest.raises(ValueError, match="temperature must be > 0"):
        backend.validate_extras({"temperature": 0})
    with pytest.raises(ValueError, match="use_cuda_graph must be boolean"):
        backend.validate_extras({"use_cuda_graph": "yes"})


def test_dia2_synthesize_builds_dialogue_script_and_config():
    import numpy as np
    from backends.dia2 import Dia2Backend

    backend = Dia2Backend()
    captured = {}

    class _SamplingConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _PrefixConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _GenerationConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Dia2:
        def generate(self, script, **kwargs):
            captured["script"] = script
            captured.update(kwargs)
            return type(
                "Result",
                (),
                {"waveform": np.array([[0.1, -0.2]], dtype=np.float64), "sample_rate": 44000},
            )()

    backend._model = _Dia2()
    backend._SamplingConfig = _SamplingConfig
    backend._PrefixConfig = _PrefixConfig
    backend._GenerationConfig = _GenerationConfig
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({
            "text_temperature": 0.55,
            "text_top_k": 35,
            "audio_temperature": 0.75,
            "audio_top_k": 45,
            "cfg_scale": 4.0,
            "cfg_filter_k": 60,
            "initial_padding": 3,
            "use_cuda_graph": True,
            "include_prefix": False,
        }),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 44000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured["script"] == "[S1] hello"
    assert captured["prefix_speaker_1"] == "/tmp/ref.wav"
    assert captured["include_prefix"] is False
    config = captured["config"]
    assert config.kwargs["text"].kwargs == {"temperature": 0.55, "top_k": 35}
    assert config.kwargs["audio"].kwargs == {"temperature": 0.75, "top_k": 45}
    assert config.kwargs["cfg_scale"] == 4.0
    assert config.kwargs["cfg_filter_k"] == 60
    assert config.kwargs["initial_padding"] == 3
    assert config.kwargs["use_cuda_graph"] is True


def test_dia2_synthesize_rejects_unsupported_lang_and_empty_output():
    import numpy as np
    from backends.dia2 import Dia2Backend

    backend = Dia2Backend()

    class _SamplingConfig:
        def __init__(self, **kwargs):
            pass

    class _PrefixConfig:
        def __init__(self, **kwargs):
            pass

    class _GenerationConfig:
        def __init__(self, **kwargs):
            pass

    class _Dia2:
        def generate(self, script, **kwargs):
            return type("Result", (), {"waveform": np.array([], dtype=np.float32)})()

    backend._model = _Dia2()
    backend._SamplingConfig = _SamplingConfig
    backend._PrefixConfig = _PrefixConfig
    backend._GenerationConfig = _GenerationConfig
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='fr'"):
        backend.synthesize("bonjour", prepared, lang="fr")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_yourtts_metadata():
    from backends.yourtts import YourTTSBackend

    backend = YourTTSBackend()

    assert backend.name == "yourtts"
    assert backend.display_name == "YourTTS (Coqui VITS, open source)"
    assert backend.sample_rate == 16000
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en", "fr", "pt-BR")


def test_yourtts_prepare_voice_allows_optional_ref_text():
    from backends.yourtts import YourTTSBackend

    backend = YourTTSBackend()
    prepared = backend.prepare_voice("/tmp/ref.wav", "  reference transcript  ", {})

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference transcript"
    assert prepared.extras == {}


def test_yourtts_rejects_unknown_extras():
    from backends.yourtts import YourTTSBackend

    backend = YourTTSBackend()

    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"temperature": 0.8})


def test_yourtts_synthesize_calls_coqui_tts_with_language_mapping():
    import numpy as np
    from backends.yourtts import YourTTSBackend

    backend = YourTTSBackend()
    captured_kwargs = {}

    class _YourTTS:
        def tts(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([[0.1, -0.2]], dtype=np.float64)

    backend._model = _YourTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    audio, sr = backend.synthesize("bonjour", prepared, lang="fr")

    assert sr == 16000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured_kwargs == {
        "text": "bonjour",
        "speaker_wav": "/tmp/ref.wav",
        "language": "fr-fr",
    }


def test_yourtts_synthesize_rejects_unsupported_lang_and_empty_output():
    import numpy as np
    from backends.yourtts import YourTTSBackend

    backend = YourTTSBackend()

    class _YourTTS:
        def tts(self, **kwargs):
            return np.array([], dtype=np.float32)

    backend._model = _YourTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='pt'"):
        backend.synthesize("ola", prepared, lang="pt")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_firered_tts_2_metadata():
    from backends.firered_tts_2 import FireRedTTS2Backend

    backend = FireRedTTS2Backend()

    assert backend.name == "firered-tts-2"
    assert backend.display_name == "FireRedTTS-2 (Apache-2.0)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en", "zh", "ja", "ko", "fr", "de", "ru")


def test_firered_tts_2_prepare_voice_allows_optional_ref_text():
    from backends.firered_tts_2 import FireRedTTS2Backend

    backend = FireRedTTS2Backend()
    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  reference transcript  ",
        {"temperature": 0.8, "top_k": 30},
    )

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference transcript"
    assert prepared.extras["temperature"] == 0.8
    assert prepared.extras["top_k"] == 30


def test_firered_tts_2_validate_extras_rejects_unknown_and_invalid_values():
    from backends.firered_tts_2 import FireRedTTS2Backend

    backend = FireRedTTS2Backend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="top_k must be an integer"):
        backend.validate_extras({"top_k": 12.5})
    with pytest.raises(ValueError, match="temperature must be > 0"):
        backend.validate_extras({"temperature": 0})
    with pytest.raises(ValueError, match="either topk or top_k"):
        backend.validate_extras({"topk": 30, "top_k": 30})


def test_firered_tts_2_synthesize_calls_monologue_with_prompt_and_sampling():
    import numpy as np
    from backends.firered_tts_2 import FireRedTTS2Backend

    backend = FireRedTTS2Backend()
    captured_kwargs = {}

    class _FireRedTTS2:
        def generate_monologue(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([[0.1, -0.2]], dtype=np.float64)

    backend._model = _FireRedTTS2()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference transcript",
        extras=_read_only({"temperature": 0.75, "top_k": 25}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured_kwargs == {
        "text": "hello",
        "prompt_wav": "/tmp/ref.wav",
        "prompt_text": "reference transcript",
        "temperature": 0.75,
        "topk": 25,
    }


def test_firered_tts_2_synthesize_rejects_unsupported_lang_and_empty_output():
    import numpy as np
    from backends.firered_tts_2 import FireRedTTS2Backend

    backend = FireRedTTS2Backend()

    class _FireRedTTS2:
        def generate_monologue(self, **kwargs):
            return np.array([], dtype=np.float32)

    backend._model = _FireRedTTS2()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='es'"):
        backend.synthesize("hola", prepared, lang="es")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_sv2tts_metadata():
    from backends.sv2tts import SV2TTSBackend

    backend = SV2TTSBackend()

    assert backend.name == "sv2tts"
    assert backend.display_name == "SV2TTS (Real-Time Voice Cloning, open source)"
    assert backend.sample_rate == 22050
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en",)


def test_sv2tts_validate_extras_rejects_unknown_and_invalid_values():
    from backends.sv2tts import SV2TTSBackend

    backend = SV2TTSBackend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="vocoder_target must be an integer"):
        backend.validate_extras({"vocoder_target": 1200.5})
    with pytest.raises(ValueError, match="vocoder_overlap must be > 0"):
        backend.validate_extras({"vocoder_overlap": 0})
    with pytest.raises(ValueError, match="vocoder_batched must be boolean"):
        backend.validate_extras({"vocoder_batched": "yes"})


def test_sv2tts_prepare_voice_embeds_reference_and_preserves_optional_text():
    import numpy as np
    from backends.sv2tts import SV2TTSBackend

    backend = SV2TTSBackend()
    captured = {}

    class _Encoder:
        def preprocess_wav(self, path):
            captured["path"] = path
            return np.array([0.1, 0.2], dtype=np.float32)

        def embed_utterance(self, wav):
            captured["wav"] = wav
            return np.array([0.3, 0.4], dtype=np.float64)

    backend._encoder = _Encoder()
    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  reference transcript  ",
        {"vocoder_target": 4000},
    )

    assert captured["path"] == "/tmp/ref.wav"
    assert np.allclose(captured["wav"], [0.1, 0.2])
    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference transcript"
    assert prepared.extras["vocoder_target"] == 4000
    assert prepared.extras["speaker_embedding"].dtype == np.float32
    assert np.allclose(prepared.extras["speaker_embedding"], [0.3, 0.4])


def test_sv2tts_synthesize_calls_synthesizer_and_vocoder_with_embedding_and_extras():
    import numpy as np
    from backends.sv2tts import SV2TTSBackend

    backend = SV2TTSBackend()
    captured = {}

    class _Synthesizer:
        def synthesize_spectrograms(self, texts, embeds):
            captured["texts"] = texts
            captured["embeds"] = embeds
            return [np.ones((80, 4), dtype=np.float32)]

    class _Vocoder:
        def infer_waveform(self, mel, **kwargs):
            captured["mel"] = mel
            captured["vocoder_kwargs"] = kwargs
            return np.array([[0.1, -0.2]], dtype=np.float64)

    backend._synthesizer = _Synthesizer()
    backend._vocoder = _Vocoder()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({
            "speaker_embedding": np.array([0.3, 0.4], dtype=np.float64),
            "vocoder_target": 4000,
            "vocoder_overlap": 400,
            "vocoder_batched": False,
        }),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 22050
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured["texts"] == ["hello"]
    assert captured["embeds"][0].dtype == np.float32
    assert np.allclose(captured["embeds"][0], [0.3, 0.4])
    assert captured["mel"].shape == (80, 4)
    assert captured["vocoder_kwargs"]["batched"] is False
    assert captured["vocoder_kwargs"]["target"] == 4000
    assert captured["vocoder_kwargs"]["overlap"] == 400
    assert callable(captured["vocoder_kwargs"]["progress_callback"])


def test_sv2tts_synthesize_rejects_unsupported_lang_missing_embedding_and_empty_output():
    import numpy as np
    from backends.sv2tts import SV2TTSBackend

    backend = SV2TTSBackend()

    class _Synthesizer:
        def synthesize_spectrograms(self, texts, embeds):
            return [np.ones((80, 4), dtype=np.float32)]

    class _Vocoder:
        def infer_waveform(self, mel, **kwargs):
            return np.array([], dtype=np.float32)

    backend._synthesizer = _Synthesizer()
    backend._vocoder = _Vocoder()
    prepared_without_embedding = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({"speaker_embedding": np.array([0.3, 0.4], dtype=np.float32)}),
    )

    with pytest.raises(ValueError, match="does not support lang='fr'"):
        backend.synthesize("bonjour", prepared, lang="fr")
    with pytest.raises(RuntimeError, match="missing speaker_embedding"):
        backend.synthesize("hello", prepared_without_embedding, lang="en")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_mockingbird_metadata():
    from backends.mockingbird import MockingBirdBackend

    backend = MockingBirdBackend()

    assert backend.name == "mockingbird"
    assert backend.display_name == "MockingBird (Chinese-focused SV2TTS, open source)"
    assert backend.sample_rate == 22050
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("zh", "en")


def test_mockingbird_validate_extras_rejects_unknown_and_invalid_values():
    from backends.mockingbird import MockingBirdBackend

    backend = MockingBirdBackend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="vocoder_target must be an integer"):
        backend.validate_extras({"vocoder_target": 1200.5})
    with pytest.raises(ValueError, match="vocoder_overlap must be > 0"):
        backend.validate_extras({"vocoder_overlap": 0})
    with pytest.raises(ValueError, match="vocoder_batched must be boolean"):
        backend.validate_extras({"vocoder_batched": "yes"})


def test_mockingbird_prepare_voice_embeds_reference_and_preserves_optional_text():
    import numpy as np
    from backends.mockingbird import MockingBirdBackend

    backend = MockingBirdBackend()
    captured = {}

    class _Encoder:
        def preprocess_wav(self, path):
            captured["path"] = path
            return np.array([0.1, 0.2], dtype=np.float32)

        def embed_utterance(self, wav):
            captured["wav"] = wav
            return np.array([0.3, 0.4], dtype=np.float64)

    backend._encoder = _Encoder()
    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  reference transcript  ",
        {"vocoder_target": 4000},
    )

    assert captured["path"] == "/tmp/ref.wav"
    assert np.allclose(captured["wav"], [0.1, 0.2])
    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference transcript"
    assert prepared.extras["vocoder_target"] == 4000
    assert prepared.extras["speaker_embedding"].dtype == np.float32
    assert np.allclose(prepared.extras["speaker_embedding"], [0.3, 0.4])


def test_mockingbird_synthesize_calls_synthesizer_and_vocoder_with_embedding_and_extras():
    import numpy as np
    from backends.mockingbird import MockingBirdBackend

    backend = MockingBirdBackend()
    captured = {}

    class _Synthesizer:
        def synthesize_spectrograms(self, texts, embeds):
            captured["texts"] = texts
            captured["embeds"] = embeds
            return [np.ones((80, 4), dtype=np.float32)]

    class _Vocoder:
        def infer_waveform(self, mel, **kwargs):
            captured["mel"] = mel
            captured["vocoder_kwargs"] = kwargs
            return np.array([[0.1, -0.2]], dtype=np.float64)

    backend._synthesizer = _Synthesizer()
    backend._vocoder = _Vocoder()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({
            "speaker_embedding": np.array([0.3, 0.4], dtype=np.float64),
            "vocoder_target": 4000,
            "vocoder_overlap": 400,
            "vocoder_batched": False,
        }),
    )

    audio, sr = backend.synthesize("ni hao", prepared, lang="zh")

    assert sr == 22050
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured["texts"] == ["ni hao"]
    assert captured["embeds"][0].dtype == np.float32
    assert np.allclose(captured["embeds"][0], [0.3, 0.4])
    assert captured["mel"].shape == (80, 4)
    assert captured["vocoder_kwargs"]["batched"] is False
    assert captured["vocoder_kwargs"]["target"] == 4000
    assert captured["vocoder_kwargs"]["overlap"] == 400
    assert callable(captured["vocoder_kwargs"]["progress_callback"])


def test_mockingbird_synthesize_rejects_unsupported_lang_missing_embedding_and_empty_output():
    import numpy as np
    from backends.mockingbird import MockingBirdBackend

    backend = MockingBirdBackend()

    class _Synthesizer:
        def synthesize_spectrograms(self, texts, embeds):
            return [np.ones((80, 4), dtype=np.float32)]

    class _Vocoder:
        def infer_waveform(self, mel, **kwargs):
            return np.array([], dtype=np.float32)

    backend._synthesizer = _Synthesizer()
    backend._vocoder = _Vocoder()
    prepared_without_embedding = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({"speaker_embedding": np.array([0.3, 0.4], dtype=np.float32)}),
    )

    with pytest.raises(ValueError, match="does not support lang='ja'"):
        backend.synthesize("konnichiwa", prepared, lang="ja")
    with pytest.raises(RuntimeError, match="missing speaker_embedding"):
        backend.synthesize("hello", prepared_without_embedding, lang="en")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_soprotts_metadata():
    from backends.soprotts import SoproTTSBackend

    backend = SoproTTSBackend()

    assert backend.name == "soprotts"
    assert backend.display_name == "SoproTTS v1.5 (Apache-2.0)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en",)


def test_soprotts_validate_extras_rejects_unknown_and_invalid_values():
    from backends.soprotts import SoproTTSBackend

    backend = SoproTTSBackend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"speed": 1.1})
    with pytest.raises(ValueError, match="max_frames must be an integer"):
        backend.validate_extras({"max_frames": 12.5})
    with pytest.raises(ValueError, match="temperature must be > 0"):
        backend.validate_extras({"temperature": 0})
    with pytest.raises(ValueError, match="top_p must be <= 1"):
        backend.validate_extras({"top_p": 1.5})
    with pytest.raises(ValueError, match="anti_loop must be boolean"):
        backend.validate_extras({"anti_loop": "yes"})


def test_soprotts_prepare_voice_prepares_reference_when_loaded():
    from backends.soprotts import SoproTTSBackend

    backend = SoproTTSBackend()
    captured = {}

    class _SoproTTS:
        def prepare_reference(self, **kwargs):
            captured.update(kwargs)
            return "prepared-ref"

    backend._model = _SoproTTS()
    prepared = backend.prepare_voice(
        "/tmp/ref.wav",
        "  reference transcript  ",
        {"ref_seconds": 6.0, "temperature": 0.8},
    )

    assert captured == {"ref_audio_path": "/tmp/ref.wav", "ref_seconds": 6.0}
    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference transcript"
    assert prepared.extras["ref"] == "prepared-ref"
    assert prepared.extras["temperature"] == 0.8


def test_soprotts_synthesize_calls_upstream_with_prepared_reference_and_sampling():
    import numpy as np
    from backends.soprotts import SoproTTSBackend

    backend = SoproTTSBackend()
    captured = {}

    class _SoproTTS:
        def synthesize(self, text, **kwargs):
            captured["text"] = text
            captured.update(kwargs)
            return np.array([[0.1, -0.2]], dtype=np.float64)

    backend._model = _SoproTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({
            "ref": "prepared-ref",
            "temperature": 0.75,
            "top_p": 0.85,
            "style_strength": 1.1,
            "max_frames": 300,
            "anti_loop": False,
        }),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.1, -0.2])
    assert captured == {
        "text": "hello",
        "ref": "prepared-ref",
        "temperature": 0.75,
        "top_p": 0.85,
        "style_strength": 1.1,
        "max_frames": 300,
        "anti_loop": False,
    }


def test_soprotts_synthesize_rejects_unsupported_lang_and_empty_output():
    import numpy as np
    from backends.soprotts import SoproTTSBackend

    backend = SoproTTSBackend()

    class _SoproTTS:
        def synthesize(self, text, **kwargs):
            return np.array([], dtype=np.float32)

    backend._model = _SoproTTS()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='fr'"):
        backend.synthesize("bonjour", prepared, lang="fr")
    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_gpt_sovits_requires_reference_text():
    from backends.gpt_sovits import GPTSoVITSBackend

    backend = GPTSoVITSBackend()
    with pytest.raises(ValueError, match="requires reference_text"):
        backend.prepare_voice("/tmp/ref.wav", "  ", {})


def test_gpt_sovits_validate_extras_rejects_unknown_and_invalid_lang():
    from backends.gpt_sovits import GPTSoVITSBackend

    backend = GPTSoVITSBackend()
    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"cfg_value": 2.0})
    with pytest.raises(ValueError, match="prompt_language must be one of"):
        backend.validate_extras({"prompt_language": "de"})


def test_gpt_sovits_synthesize_calls_upstream_api_and_concatenates_chunks():
    import numpy as np
    from backends.gpt_sovits import GPTSoVITSBackend
    from backends.base import PreparedVoice, _read_only

    backend = GPTSoVITSBackend()
    captured_kwargs = {}

    def _fake_get_tts_wav(**kwargs):
        captured_kwargs.update(kwargs)
        yield 32000, np.full(4, 0.1, dtype=np.float32)
        yield 32000, np.full(6, 0.2, dtype=np.float32)

    backend._get_tts_wav = _fake_get_tts_wav
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference transcript",
        extras=_read_only({"prompt_language": "en", "top_k": 15, "speed": 1.1}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="zh")

    assert sr == 32000
    assert captured_kwargs == {
        "ref_wav_path": "/tmp/ref.wav",
        "prompt_text": "reference transcript",
        "prompt_language": "en",
        "text": "hello",
        "text_language": "zh",
        "top_k": 15,
        "speed": 1.1,
    }
    assert audio.shape == (10,)
    assert np.allclose(audio[:4], 0.1)
    assert np.allclose(audio[4:], 0.2)


def test_gpt_sovits_synthesize_accepts_mapping_chunks():
    import numpy as np
    from backends.gpt_sovits import GPTSoVITSBackend
    from backends.base import PreparedVoice, _read_only

    backend = GPTSoVITSBackend()

    def _fake_get_tts_wav(**kwargs):
        yield {"audio": np.full(3, 0.25, dtype=np.float32), "sample_rate": 48000}

    backend._get_tts_wav = _fake_get_tts_wav
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference transcript",
        extras=_read_only({}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 48000
    assert audio.dtype == np.float32
    assert audio.shape == (3,)
    assert np.allclose(audio, 0.25)


def test_gpt_sovits_synthesize_raises_on_empty_generator():
    from backends.gpt_sovits import GPTSoVITSBackend
    from backends.base import PreparedVoice, _read_only

    backend = GPTSoVITSBackend()
    backend._get_tts_wav = lambda **kwargs: (x for x in ())
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference transcript",
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="produced no output"):
        backend.synthesize("hello", prepared, lang="en")


def test_voxtral_synthesize_raises_on_empty_generator():
    from backends.voxtral import VoxtralBackend
    from backends.base import PreparedVoice, _read_only

    backend = VoxtralBackend()

    class _EmptyModel:
        def generate(self, **kwargs):
            return (x for x in ())

    backend._model = _EmptyModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="no audio chunks"):
        backend.synthesize("hello", prepared, lang="en")


def test_openvoice_v2_metadata():
    from backends.openvoice_v2 import OpenVoiceV2Backend

    backend = OpenVoiceV2Backend()

    assert backend.name == "openvoice-v2"
    assert backend.display_name == "OpenVoice v2"
    assert backend.sample_rate == 22050
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == ("en", "es", "fr", "zh", "ja", "ko")


def test_openvoice_v2_prepare_voice_extracts_target_se(tmp_path):
    from backends.openvoice_v2 import OpenVoiceV2Backend

    backend = OpenVoiceV2Backend()
    backend._tone_color_converter = object()

    class _Extractor:
        def get_se(self, ref_audio_path, converter, target_dir, vad):
            assert ref_audio_path == "/tmp/ref.wav"
            assert converter is backend._tone_color_converter
            assert vad is True
            assert tmp_path.exists()
            return "target-se", "ref"

    backend._se_extractor = _Extractor()

    prepared = backend.prepare_voice("/tmp/ref.wav", "reference text", {})

    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text == "reference text"
    assert prepared.extras["target_se"] == "target-se"


def test_openvoice_v2_synthesize_raises_before_load():
    from backends.openvoice_v2 import OpenVoiceV2Backend

    backend = OpenVoiceV2Backend()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="called before load"):
        backend.synthesize("hello", prepared, lang="en")


def test_openvoice_v2_synthesize_rejects_unsupported_language():
    from backends.openvoice_v2 import OpenVoiceV2Backend

    backend = OpenVoiceV2Backend()
    backend._tone_color_converter = object()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({"target_se": "target-se"}),
    )

    with pytest.raises(ValueError, match="does not support lang='de'"):
        backend.synthesize("hallo", prepared, lang="de")


def test_openvoice_v2_synthesize_uses_melo_and_converter(tmp_path):
    import numpy as np
    from types import SimpleNamespace
    from backends.openvoice_v2 import OpenVoiceV2Backend

    backend = OpenVoiceV2Backend()
    checkpoint_dir = tmp_path / "checkpoints_v2"
    se_dir = checkpoint_dir / "base_speakers" / "ses"
    se_dir.mkdir(parents=True)
    (se_dir / "en-newest.pth").write_bytes(b"stub")
    backend._checkpoint_dir = str(checkpoint_dir)
    backend._device = "cpu"

    captured_tts = {}
    captured_convert = {}

    class _Torch:
        def load(self, path, map_location):
            assert path == str(se_dir / "en-newest.pth")
            assert map_location == "cpu"
            return "source-se"

    class _TTSModel:
        hps = SimpleNamespace(data=SimpleNamespace(spk2id={"EN-Newest": 7}))

        def tts_to_file(self, text, speaker_id, output_path, speed):
            captured_tts.update(
                text=text,
                speaker_id=speaker_id,
                output_path=output_path,
                speed=speed,
            )
            with open(output_path, "wb") as f:
                f.write(b"RIFF")

    class _Converter:
        def convert(self, **kwargs):
            captured_convert.update(kwargs)
            return np.array([0.1, -0.2], dtype=np.float32)

    backend._torch = _Torch()
    backend._tone_color_converter = _Converter()
    backend._tts_models["EN_NEWEST"] = _TTSModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({"target_se": "target-se", "speed": 1.2, "tau": 0.4}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 22050
    assert np.allclose(audio, [0.1, -0.2])
    assert captured_tts["text"] == "hello"
    assert captured_tts["speaker_id"] == 7
    assert captured_tts["speed"] == 1.2
    assert captured_convert["src_se"] == "source-se"
    assert captured_convert["tgt_se"] == "target-se"
    assert captured_convert["tau"] == 0.4


def test_f5_tts_metadata():
    from backends.f5_tts import F5TTSBackend

    backend = F5TTSBackend()

    assert backend.name == "f5-tts"
    assert backend.display_name == "F5-TTS v1 Base (DiT, CC-BY-NC)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.REQUIRED
    assert backend.supported_langs == ("en", "zh")


def test_f5_tts_prepare_voice_requires_ref_text():
    from backends.f5_tts import F5TTSBackend

    backend = F5TTSBackend()

    with pytest.raises(ValueError, match="requires reference_text"):
        backend.prepare_voice("/tmp/ref.wav", "", {})


def test_f5_tts_validate_extras_rejects_unknown_and_invalid_values():
    from backends.f5_tts import F5TTSBackend

    backend = F5TTSBackend()

    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"emotion": "happy"})
    with pytest.raises(ValueError, match="nfe_step must be > 0"):
        backend.validate_extras({"nfe_step": 0})
    with pytest.raises(ValueError, match="speed must be > 0"):
        backend.validate_extras({"speed": -1})
    with pytest.raises(ValueError, match="seed must be an integer"):
        backend.validate_extras({"seed": 1.5})


def test_f5_tts_synthesize_raises_before_load():
    from backends.f5_tts import F5TTSBackend

    backend = F5TTSBackend()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference text",
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="called before load"):
        backend.synthesize("hello", prepared, lang="en")


def test_f5_tts_synthesize_rejects_unsupported_language():
    from backends.f5_tts import F5TTSBackend

    backend = F5TTSBackend()
    backend._model = object()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference text",
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='fr'"):
        backend.synthesize("bonjour", prepared, lang="fr")


def test_f5_tts_synthesize_uses_f5_api_and_generation_extras():
    import numpy as np
    from backends.f5_tts import F5TTSBackend

    backend = F5TTSBackend()
    captured_kwargs = {}

    class _F5Model:
        def infer(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([0.3, -0.1], dtype=np.float32), 24000, "spectrogram"

    backend._model = _F5Model()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference text",
        extras=_read_only({"nfe_step": 16, "speed": 1.1, "seed": 123}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert np.allclose(audio, [0.3, -0.1])
    assert captured_kwargs["ref_file"] == "/tmp/ref.wav"
    assert captured_kwargs["ref_text"] == "reference text"
    assert captured_kwargs["gen_text"] == "hello"
    assert captured_kwargs["nfe_step"] == 16
    assert captured_kwargs["speed"] == 1.1
    assert captured_kwargs["seed"] == 123
    assert captured_kwargs["progress"] is None


def test_cosyvoice2_metadata():
    from backends.cosyvoice2 import CosyVoice2Backend

    backend = CosyVoice2Backend()

    assert backend.name == "cosyvoice2"
    assert backend.display_name == "CosyVoice2-0.5B (Apache-2.0)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.REQUIRED
    assert backend.supported_langs == ("en", "zh", "ja", "ko", "de", "es", "fr", "it", "ru")


def test_cosyvoice2_prepare_voice_requires_ref_text():
    from backends.cosyvoice2 import CosyVoice2Backend

    backend = CosyVoice2Backend()

    with pytest.raises(ValueError, match="requires reference_text"):
        backend.prepare_voice("/tmp/ref.wav", "  ", {})


def test_cosyvoice2_validate_extras_rejects_unknown_and_invalid_values():
    from backends.cosyvoice2 import CosyVoice2Backend

    backend = CosyVoice2Backend()

    with pytest.raises(ValueError, match="does not accept extras"):
        backend.validate_extras({"emotion": "happy"})
    with pytest.raises(ValueError, match="speed must be > 0"):
        backend.validate_extras({"speed": 0})
    with pytest.raises(ValueError, match="text_frontend must be boolean"):
        backend.validate_extras({"text_frontend": "yes"})


def test_cosyvoice2_synthesize_raises_before_load():
    from backends.cosyvoice2 import CosyVoice2Backend

    backend = CosyVoice2Backend()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference text",
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="called before load"):
        backend.synthesize("hello", prepared, lang="en")


def test_cosyvoice2_synthesize_uses_zero_shot_api_and_concatenates_chunks():
    import numpy as np
    from backends.cosyvoice2 import CosyVoice2Backend

    backend = CosyVoice2Backend()
    captured = {}

    class _Tensorish:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=np.float32)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    class _CosyModel:
        sample_rate = 24000

        def inference_zero_shot(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            yield {"tts_speech": _Tensorish([[0.1, 0.2]])}
            yield {"tts_speech": _Tensorish([[-0.1]])}

    backend._model = _CosyModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text="reference text",
        extras=_read_only({"speed": 1.2, "text_frontend": False}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert np.allclose(audio, [0.1, 0.2, -0.1])
    assert captured["args"] == ("hello", "reference text", "/tmp/ref.wav")
    assert captured["kwargs"] == {"stream": False, "speed": 1.2, "text_frontend": False}


def test_xtts_v2_metadata():
    from backends.xtts_v2 import XTTSv2Backend

    backend = XTTSv2Backend()

    assert backend.name == "xtts-v2"
    assert backend.display_name == "XTTS v2 (CPML, non-commercial)"
    assert backend.sample_rate == 24000
    assert backend.ref_text_policy is RefTextPolicy.OPTIONAL
    assert backend.supported_langs == (
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
        "nl", "cs", "ar", "zh", "hu", "ko", "ja", "hi",
    )


def test_xtts_v2_prepare_voice_allows_missing_ref_text_and_rejects_extras():
    from backends.xtts_v2 import XTTSv2Backend

    backend = XTTSv2Backend()

    prepared = backend.prepare_voice("/tmp/ref.wav", "  ", {})
    assert prepared.ref_audio_path == "/tmp/ref.wav"
    assert prepared.ref_text is None

    with pytest.raises(ValueError, match="does not accept extras"):
        backend.prepare_voice("/tmp/ref.wav", None, {"speed": 1.1})


def test_xtts_v2_synthesize_raises_before_load():
    from backends.xtts_v2 import XTTSv2Backend

    backend = XTTSv2Backend()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(RuntimeError, match="called before load"):
        backend.synthesize("hello", prepared, lang="en")


def test_xtts_v2_synthesize_rejects_unsupported_language():
    from backends.xtts_v2 import XTTSv2Backend

    backend = XTTSv2Backend()
    backend._model = object()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    with pytest.raises(ValueError, match="does not support lang='yue'"):
        backend.synthesize("nei hou", prepared, lang="yue")


def test_xtts_v2_synthesize_uses_coqui_api_and_returns_float32_audio():
    import numpy as np
    from backends.xtts_v2 import XTTSv2Backend

    backend = XTTSv2Backend()
    captured_kwargs = {}

    class _Tensorish:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.array([[0.2, -0.4]], dtype=np.float64)

    class _XTTSModel:
        def tts(self, **kwargs):
            captured_kwargs.update(kwargs)
            return _Tensorish()

    backend._model = _XTTSModel()
    prepared = PreparedVoice(
        ref_audio_path="/tmp/ref.wav",
        ref_text=None,
        extras=_read_only({}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")

    assert sr == 24000
    assert audio.dtype == np.float32
    assert np.allclose(audio, [0.2, -0.4])
    assert captured_kwargs == {
        "text": "hello",
        "speaker_wav": "/tmp/ref.wav",
        "language": "en",
    }


# --- resolve_repo_dir security tests ---


class TestResolveRepoDir:
    """Tests for backends.base.resolve_repo_dir — symlink + world-writable rejection."""

    def test_normal_path_passes(self):
        from backends.base import resolve_repo_dir
        import pathlib

        d = str(pathlib.Path(__file__).parent.resolve())
        assert resolve_repo_dir(d) == d

    def test_rejects_tmp(self):
        from backends.base import resolve_repo_dir

        with pytest.raises(ValueError, match="world-writable"):
            resolve_repo_dir("/tmp")

    def test_rejects_tmp_subdir(self):
        from backends.base import resolve_repo_dir

        with pytest.raises(ValueError, match="world-writable"):
            resolve_repo_dir("/tmp/evil_repo")

    def test_rejects_var_tmp(self):
        from backends.base import resolve_repo_dir

        with pytest.raises(ValueError, match="world-writable"):
            resolve_repo_dir("/var/tmp/evil")

    def test_rejects_dev_shm(self):
        from backends.base import resolve_repo_dir

        with pytest.raises(ValueError, match="world-writable"):
            resolve_repo_dir("/dev/shm/payload")

    def test_rejects_symlink_to_tmp(self, tmp_path):
        """A symlink pointing into /tmp must be caught after realpath resolution.

        On macOS /tmp is a symlink to /private/tmp, so realpath resolves
        through it. The _DANGEROUS_PATH_PREFIXES are themselves resolved at
        module load, meaning /private/tmp is in the list on macOS.
        """
        import os

        from backends.base import resolve_repo_dir

        # Create a symlink from a safe location pointing into /tmp.
        # After realpath, it resolves under /private/tmp (macOS) or /tmp (Linux).
        target = os.path.realpath("/tmp")  # /private/tmp on macOS
        link = str(tmp_path / "link_to_tmp")
        os.symlink(target, link)
        with pytest.raises(ValueError, match="world-writable"):
            resolve_repo_dir(link)

    def test_default_repo_dir_passes(self):
        import os

        from backends.base import resolve_repo_dir
        import backends.gpt_sovits as gs

        result = resolve_repo_dir(gs.DEFAULT_REPO_DIR)
        assert os.path.isabs(result)
        assert not result.startswith(os.path.realpath("/tmp"))

    def test_expanduser_before_resolve(self):
        """Tilde in env vars must expand before realpath resolution."""
        import os

        from backends.base import resolve_repo_dir

        home = os.path.expanduser("~")
        # ~/some_dir should resolve to the real home, not a literal ~
        result = resolve_repo_dir(os.path.expanduser("~/some_dir"))
        assert result.startswith(os.path.realpath(home))
        assert "~" not in result

