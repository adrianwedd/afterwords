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


def test_register_all_populates_four_backends():
    backends.register_all()
    assert set(backends.names()) == {
        "qwen3-0.6b", "qwen3-1.7b", "chatterbox", "voxcpm-1.5",
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
