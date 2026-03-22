"""Shared fixtures and custom test runner UX for Afterwords."""
import os
import struct
import time
from unittest.mock import MagicMock, patch

import pytest

import server


# ── Colours ───────────────────────────────────────────────────────
GREEN = "\033[0;32m"
RED = "\033[0;31m"
DIM = "\033[2m"
BOLD = "\033[1m"
NC = "\033[0m"


# ── Fixtures ──────────────────────────────────────────────────────

def _make_wav(path: str) -> None:
    """Write a tiny valid 16-bit PCM WAV file (0.01s of silence)."""
    sr = 24000
    n_samples = 240  # 0.01s
    data_size = n_samples * 2  # 16-bit = 2 bytes per sample
    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))       # chunk size
        f.write(struct.pack("<H", 1))        # PCM
        f.write(struct.pack("<H", 1))        # mono
        f.write(struct.pack("<I", sr))       # sample rate
        f.write(struct.pack("<I", sr * 2))   # byte rate
        f.write(struct.pack("<H", 2))        # block align
        f.write(struct.pack("<H", 16))       # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)


def _fake_generate_audio(**kwargs):
    """Mock for mlx_audio generate_audio — writes out_0.wav to output_path."""
    output_path = kwargs.get("output_path", "/tmp")
    prefix = kwargs.get("file_prefix", "out")
    _make_wav(os.path.join(output_path, f"{prefix}_0.wav"))


@pytest.fixture
def sample_voice(tmp_path):
    """Register a temporary test voice in server.VOICES."""
    wav_path = str(tmp_path / "testvoice-ref.wav")
    _make_wav(wav_path)
    server.VOICES["testvoice"] = (wav_path, "This is a test voice reference.")
    yield "testvoice"
    server.VOICES.pop("testvoice", None)


@pytest.fixture
def mock_model(sample_voice):
    """Patch model loading and audio generation. Sets server to ready."""
    with patch("server._get_model", return_value=MagicMock()), \
         patch("mlx_audio.tts.generate.generate_audio", side_effect=_fake_generate_audio):
        server._ready.set()
        yield
        server._ready.clear()


@pytest.fixture
def client(mock_model):
    """FastAPI TestClient with mocked model."""
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


def pytest_runtest_logreport(report):
    """Print styled per-test results."""
    global _current_group, _passed, _failed
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
    else:
        print(f"  {RED}\u2717{NC} {name}")
        _failed += 1
        if report.longreprtext:
            for line in report.longreprtext.strip().splitlines()[:5]:
                print(f"      {line}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print the styled summary banner."""
    import time as _time
    elapsed = _time.time() - _start_time
    print(f"\n  {DIM}{'─' * 41}{NC}")
    if _failed:
        print(f"  {RED}\u2717 {_failed} failed, {_passed} passed{NC}  ({elapsed:.1f}s)")
    else:
        print(f"  {GREEN}\u2713 {_passed} passed{NC}  ({elapsed:.1f}s)")
    print()


def pytest_sessionstart(session):
    """Print the banner header and record start time."""
    global _start_time
    _start_time = time.time()
    print(f"\n  {BOLD}afterwords{NC}  {DIM}\u2014 test suite{NC}")
    print(f"  {DIM}{'─' * 41}{NC}")
