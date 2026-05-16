"""Shared fixtures and custom test runner UX for Afterwords."""
from __future__ import annotations

import os
import struct
import time
from types import MappingProxyType
from typing import Mapping

import numpy as np
import pytest

import backends
from backends.base import Backend, PreparedVoice, RefTextPolicy, _read_only


# ── Colours ───────────────────────────────────────────────────────
GREEN = "\033[0;32m"
RED = "\033[0;31m"
DIM = "\033[2m"
BOLD = "\033[1m"
NC = "\033[0m"


# ── WAV helper ─────────────────────────────────────────────────────

def _make_wav(path: str) -> None:
    """Write a tiny valid 16-bit PCM WAV file (0.01s of silence) at 24 kHz."""
    sr = 24000
    n_samples = 240
    data_size = n_samples * 2
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<I", sr))
        f.write(struct.pack("<I", sr * 2))
        f.write(struct.pack("<H", 2))
        f.write(struct.pack("<H", 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)


# ── Fake backend: zero model loads, returns fake audio ─────────────

class FakeBackend:
    """Standin backend for tests. Returns 0.1s of silent float32 audio at 24 kHz."""
    name = "fake"
    display_name = "Fake Backend (tests)"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def load(self) -> None:
        pass

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        # Accept anything — tests pass varied extras.
        pass

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(dict(extras)),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if lang not in self.supported_langs:
            raise ValueError(
                f"fake does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        # Return 100ms of silence at our sample rate
        audio = np.zeros(self.sample_rate // 10, dtype=np.float32)
        return audio, self.sample_rate


# ── Autouse fixture: seed a fresh registry with FakeBackend for each test ──

@pytest.fixture(autouse=True)
def _fake_backend_registry(request):
    """Replace the real backends with FakeBackend aliases — unless the test is integration.

    Integration tests manage the registry themselves.
    """
    if request.node.get_closest_marker("integration"):
        # Integration tests manage the registry themselves.
        yield
        return

    backends.reset_for_tests()
    fake = FakeBackend()
    backends.register(fake)

    # Register aliases so VoiceProfile.backend values like "qwen3-0.6b" resolve to the FakeBackend.
    # We do this by creating lightweight delegate instances that share the FakeBackend's methods
    # but advertise different names.
    for alias in ("qwen3-0.6b", "qwen3-1.7b"):
        delegate = FakeBackend()
        delegate.name = alias
        delegate.display_name = f"{alias} (test-fake)"
        backends.register(delegate)
    yield
    backends.reset_for_tests()


# ── Voice profile fixture ──────────────────────────────────────────

@pytest.fixture
def sample_voice(tmp_path):
    """Register a temporary test voice (as a VoiceProfile) in server.VOICES."""
    import server

    wav_path = str(tmp_path / "testvoice-ref.wav")
    _make_wav(wav_path)
    backend = backends.get("fake")
    prepared = backend.prepare_voice(wav_path, "Test reference.", {})
    profile = server.VoiceProfile(
        name="testvoice",
        backend="fake",
        ref_audio=wav_path,
        ref_text="Test reference.",
        session_id=None,
        emotion="neutral",
        quality=None,
        duration_s=None,
        confidence=None,
        sequence=None,
        extras=_read_only({}),
        prepared=prepared,
    )
    server.VOICES["testvoice"] = profile
    yield "testvoice"
    server.VOICES.pop("testvoice", None)


# ── Ready + client fixtures ────────────────────────────────────────

@pytest.fixture
def ready_server():
    """Mark server as warmed up."""
    import server
    server._ready.set()
    yield
    server._ready.clear()


@pytest.fixture
def client(ready_server):
    """FastAPI TestClient — uses the FakeBackend registry from _fake_backend_registry autouse."""
    import server
    from starlette.testclient import TestClient
    return TestClient(server.app)


# ── Custom runner UX ──────────────────────────────────────────────

_current_group = None
_passed = 0
_failed = 0
_start_time = 0


def _test_display_name(nodeid: str) -> str:
    """Convert test_foo_bar_baz to 'foo bar baz'."""
    name = nodeid.split("::")[-1]
    if name.startswith("test_"):
        name = name[5:]
    return name.replace("_", " ")


def _group_name(nodeid: str) -> str:
    """Convert tests/test_server.py to 'server'."""
    path = nodeid.split("::")[0]
    fname = os.path.basename(path)
    return fname.replace("test_", "").replace(".py", "").replace("_", "-")


def pytest_collection_modifyitems(items):
    """Sort tests by file for grouped display."""
    items.sort(key=lambda item: item.fspath.strpath)


def pytest_report_teststatus(report, config):
    """Suppress default per-test output (dots/F characters)."""
    return "", "", ""


_skipped = 0


def pytest_runtest_logreport(report):
    """Print styled per-test results."""
    global _current_group, _passed, _failed, _skipped
    if report.when != "call":
        return

    group = _group_name(report.nodeid)
    if group != _current_group:
        if _current_group is not None:
            print()
        print(f"\n  {BOLD}{group}{NC}")
        _current_group = group

    name = _test_display_name(report.nodeid)
    if report.passed:
        print(f"  {GREEN}\u2713{NC} {name}")
        _passed += 1
    elif report.skipped:
        _skipped += 1
    else:
        print(f"  {RED}\u2717{NC} {name}")
        _failed += 1
        if report.longreprtext:
            for line in report.longreprtext.strip().splitlines():
                print(f"      {line}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print the styled summary banner."""
    import time as _time
    elapsed = _time.time() - _start_time
    print(f"\n  {DIM}{'─' * 41}{NC}")
    skip_note = f", {_skipped} skipped" if _skipped else ""
    if _failed:
        print(f"  {RED}\u2717 {_failed} failed, {_passed} passed{skip_note}{NC}  ({elapsed:.1f}s)")
    else:
        print(f"  {GREEN}\u2713 {_passed} passed{skip_note}{NC}  ({elapsed:.1f}s)")
    print()


def pytest_sessionstart(session):
    """Print the banner header and record start time."""
    global _start_time
    _start_time = time.time()
    print(f"\n  {BOLD}afterwords{NC}  {DIM}\u2014 test suite{NC}")
    print(f"  {DIM}{'─' * 41}{NC}")
