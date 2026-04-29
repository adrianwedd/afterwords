"""Tests for the backends/ registry + protocol — no model load."""
from __future__ import annotations

import pytest

import backends
from backends.base import Backend, PreparedVoice, RefTextPolicy, _read_only


@pytest.fixture(autouse=True)
def _clean_registry():
    backends.reset_for_tests()
    yield
    backends.reset_for_tests()


def test_register_all_populates_shipped_backends():
    backends.register_all()
    assert set(backends.names()) == {
        "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5", "voxtral",
    }


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
    b = backends.get("chatterbox")
    with pytest.raises(ValueError, match="already registered"):
        backends.register(b)


def test_slug_collision_raises():
    backends.register_all()
    class _Fake:
        name = "voxcpm-15"  # slugs to "voxcpm-15", collides with voxcpm-1.5
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


def test_max_sample_rate_reflects_voxcpm():
    backends.register_all()
    assert backends.max_sample_rate() == 44100


def test_slug_strips_dots():
    assert backends.slug("voxcpm-1.5") == "voxcpm-15"
    assert backends.slug("qwen3-0.6b") == "qwen3-06b"
    assert backends.slug("chatterbox") == "chatterbox"
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


def test_voxcpm_synthesize_handles_generator_output(tmp_path):
    """Regression: mlx-audio's VoxCPM.generate() yields GenerationResult objects
    (dataclass with .audio = mx.array). Earlier code passed the generator directly
    to np.asarray which raised TypeError. Mock the model to verify the generator
    branch concatenates chunk audio correctly without loading mlx-audio."""
    from types import SimpleNamespace
    import numpy as np
    from backends.voxcpm import VoxCPMBackend
    from backends.base import PreparedVoice, _read_only

    backend = VoxCPMBackend()
    # Stub the model — yields two GenerationResult-shaped objects.
    chunk_a = SimpleNamespace(audio=np.full(100, 0.1, dtype=np.float32))
    chunk_b = SimpleNamespace(audio=np.full(150, 0.2, dtype=np.float32))

    class _StubModel:
        def generate(self, **kwargs):
            yield chunk_a
            yield chunk_b

    backend._model = _StubModel()
    prepared = PreparedVoice(
        ref_audio_path=_write_silence_wav(tmp_path),
        ref_text="ref",
        extras=_read_only({}),
    )

    audio, sr = backend.synthesize("hello", prepared, lang="en")
    assert sr == 44100  # NATIVE_SR
    assert audio.shape == (250,)
    assert audio.dtype == np.float32
    # First 100 samples from chunk_a, next 150 from chunk_b
    assert np.allclose(audio[:100], 0.1)
    assert np.allclose(audio[100:], 0.2)


def test_voxcpm_synthesize_raises_on_empty_generator(tmp_path):
    """If generate() yields nothing, surface a clear error rather than
    returning an empty array silently."""
    import pytest as _pytest
    from backends.voxcpm import VoxCPMBackend
    from backends.base import PreparedVoice, _read_only

    backend = VoxCPMBackend()

    class _EmptyModel:
        def generate(self, **kwargs):
            return (x for x in ())  # empty generator (real GeneratorType)

    backend._model = _EmptyModel()
    prepared = PreparedVoice(
        ref_audio_path=_write_silence_wav(tmp_path),
        ref_text="ref",
        extras=_read_only({}),
    )
    with _pytest.raises(RuntimeError, match="no audio chunks"):
        backend.synthesize("hello", prepared, lang="en")


def test_voxcpm_synthesize_passes_mxarray_ref_audio_to_model(tmp_path):
    """Regression for the kwarg-rename + mx.array conversion bug.

    When BOTH ref_audio and ref_text are provided, voxcpm.py must:
    - call generate() with kwarg names ref_audio (not reference_wav_path)
      and ref_text (not prompt_text)
    - pass ref_audio as an mx.array (the model's _encode_prompt_audio
      expects a tensor, not a string path)
    """
    from types import SimpleNamespace
    import numpy as np
    import mlx.core as mx
    from backends.voxcpm import VoxCPMBackend
    from backends.base import PreparedVoice, _read_only

    backend = VoxCPMBackend()
    captured_kwargs = {}

    class _CapturingModel:
        def generate(self, **kwargs):
            captured_kwargs.update(kwargs)
            yield SimpleNamespace(audio=np.zeros(10, dtype=np.float32))

    backend._model = _CapturingModel()
    prepared = PreparedVoice(
        ref_audio_path=_write_silence_wav(tmp_path),
        ref_text="reference text",
        extras=_read_only({}),
    )
    backend.synthesize("hello", prepared, lang="en")

    assert "ref_audio" in captured_kwargs, "must pass ref_audio (not reference_wav_path)"
    assert "ref_text" in captured_kwargs, "must pass ref_text (not prompt_text)"
    assert captured_kwargs["ref_text"] == "reference text"
    # ref_audio must be an mx.array of shape (T,), not a path string.
    ref = captured_kwargs["ref_audio"]
    assert isinstance(ref, mx.array), f"ref_audio must be mx.array, got {type(ref).__name__}"
    assert ref.ndim == 1, f"ref_audio must be 1-D, got shape {ref.shape}"
    assert ref.shape[0] > 0


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
