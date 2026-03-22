# Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pytest test suite with polished terminal UX covering the server API and strip-markdown transform.

**Architecture:** Extract strip-markdown into an importable module, test it as a pure function. Test server endpoints via FastAPI TestClient with mocked ML model. Custom pytest hooks for styled output matching the project's terminal aesthetic.

**Tech Stack:** pytest, FastAPI TestClient, unittest.mock, soundfile (for generating test WAVs)

**Spec:** `docs/superpowers/specs/2026-03-22-test-suite-design.md`

---

### Task 1: Extract strip_markdown.py module

**Files:**
- Create: `strip_markdown.py`
- Modify: `setup.sh:327-344`

- [ ] **Step 1: Create `strip_markdown.py`**

```python
"""Strip markdown formatting for cleaner TTS output.

Usable as an importable module or as a stdin-to-stdout script.
The regex pipeline preserves inline code content (strips only backticks),
removes fenced code blocks, tables, and markdown formatting, then
truncates to 1000 characters.
"""
import re


def strip_markdown(text: str) -> str:
    """Strip markdown formatting from text for TTS."""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)
    text = re.sub(r'^\|.*\|$', '', text, flags=re.M)
    text = re.sub(r'^[-|:\s]+$', '', text, flags=re.M)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:1000]


if __name__ == "__main__":
    import sys
    print(strip_markdown(sys.stdin.read()))
```

- [ ] **Step 2: Verify it works as a stdin script**

Run: `echo "Use \`claude\` for **everything**" | python3 strip_markdown.py`
Expected: `Use claude for everything`

- [ ] **Step 3: Update setup.sh to copy instead of inline**

In `setup.sh`, replace lines 327-344 (the `cat > "$HOOKS_DIR/strip-markdown.py" <<'PYEOF'` heredoc block) with:

```bash
# Strip-markdown helper
cp "$SCRIPT_DIR/strip_markdown.py" "$HOOKS_DIR/strip-markdown.py"
```

- [ ] **Step 4: Verify setup.sh syntax**

Run: `bash -n setup.sh`
Expected: no output (clean)

- [ ] **Step 5: Commit**

```bash
git add strip_markdown.py setup.sh
git commit -m "refactor: extract strip_markdown into importable module"
```

---

### Task 2: Create pytest infrastructure

**Files:**
- Create: `pytest.ini`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
addopts = -q --tb=short --no-header
```

- [ ] **Step 2: Create `tests/conftest.py` with fixtures**

```python
"""Shared fixtures and custom test runner UX for Afterwords."""
import os
import struct
import tempfile
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
_failures = []
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
    import time
    elapsed = time.time() - _start_time
    print(f"\n  {DIM}{'─' * 41}{NC}")
    if _failed:
        print(f"  {RED}\u2717 {_failed} failed, {_passed} passed{NC}  ({elapsed:.1f}s)")
    else:
        print(f"  {GREEN}\u2713 {_passed} passed{NC}  ({elapsed:.1f}s)")
    print()


def pytest_sessionstart(session):
    """Print the banner header and record start time."""
    global _start_time
    import time
    _start_time = time.time()
    print(f"\n  {BOLD}afterwords{NC}  {DIM}\u2014 test suite{NC}")
    print(f"  {DIM}{'─' * 41}{NC}")
```

- [ ] **Step 3: Verify pytest discovers infrastructure**

Run: `source .venv/bin/activate && pip install -q pytest httpx && pytest --collect-only 2>&1 | head -5`
Expected: `no tests ran` or empty collection (no errors)

- [ ] **Step 4: Commit**

```bash
git add pytest.ini tests/conftest.py
git commit -m "test: add pytest infrastructure with custom runner UX"
```

---

### Task 3: Write strip-markdown tests

**Files:**
- Create: `tests/test_strip_markdown.py`

- [ ] **Step 1: Write all strip-markdown tests**

```python
"""Tests for the strip-markdown text transform.

Every regex pattern in the pipeline has a dedicated test.
The golden test (test_real_claude_response) exercises all
patterns together on a realistic Claude response.
"""
from strip_markdown import strip_markdown


def test_preserves_plain_text():
    assert strip_markdown("Hello world") == "Hello world"


def test_inline_code_keeps_content():
    assert strip_markdown("`--server-only` flag") == "--server-only flag"


def test_multiple_inline_code_spans():
    assert strip_markdown("Use `foo` and `bar`") == "Use foo and bar"


def test_inline_code_special_chars():
    assert strip_markdown("`--flag=value` option") == "--flag=value option"


def test_fenced_code_block_removed():
    text = "before\n```bash\ncurl localhost:7860/health\n```\nafter"
    result = strip_markdown(text)
    assert "curl" not in result
    assert "before" in result
    assert "after" in result


def test_bold_stripped():
    assert strip_markdown("**important** thing") == "important thing"


def test_italic_stripped():
    assert strip_markdown("*emphasis* here") == "emphasis here"


def test_heading_stripped():
    assert strip_markdown("## Section Title") == "Section Title"


def test_bullet_list_stripped():
    result = strip_markdown("- item one\n- item two")
    assert "item one" in result
    assert "item two" in result
    assert result.startswith("-") is False


def test_numbered_list_stripped():
    result = strip_markdown("1. first\n2. second")
    assert "first" in result
    assert "second" in result
    assert "1." not in result


def test_link_keeps_text():
    assert strip_markdown("[click here](http://example.com)") == "click here"


def test_table_removed():
    text = "before\n| Name | Value |\n|---|---|\n| a | b |\nafter"
    result = strip_markdown(text)
    assert "before" in result
    assert "after" in result
    assert "|" not in result


def test_truncates_at_1000_chars():
    text = "word " * 400  # 2000 chars
    result = strip_markdown(text)
    assert len(result) <= 1000


def test_collapses_whitespace():
    assert strip_markdown("too   many    spaces") == "too many spaces"


def test_real_claude_response():
    """Golden test — a realistic Claude response with every markdown feature."""
    text = """## Voice Configuration

You can set a **per-project voice** using the `.afterwords` file:

```bash
echo "snape" > .afterwords
```

The `--server-only` flag skips Claude Code integration. Available voices:

1. `galadriel` — ethereal, ancient
2. `snape` — velvet menace

| Voice | Source |
|---|---|
| galadriel | Cate Blanchett |
| snape | Alan Rickman |

Features:

- Zero-shot cloning
- Real-time synthesis

For more details, see the [README](https://github.com/adrianwedd/afterwords)."""

    result = strip_markdown(text)
    # Headings stripped
    assert "##" not in result
    # Fenced code block removed
    assert "echo" not in result
    # Bullet list markers stripped, content preserved
    assert "Zero-shot cloning" in result
    assert result.count("- ") == 0  # no bullet markers remain
    # Inline code content preserved
    assert "--server-only" in result
    assert "galadriel" in result
    assert "snape" in result
    # Bold stripped
    assert "**" not in result
    # Table removed
    assert "|" not in result
    # Link text preserved, URL removed
    assert "README" in result
    assert "github.com" not in result
    # No backticks remain
    assert "`" not in result
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_strip_markdown.py -v`
Expected: all 16 tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_strip_markdown.py
git commit -m "test: add strip-markdown tests (16 cases including golden test)"
```

---

### Task 4: Write server tests

**Files:**
- Create: `tests/test_server.py`

- [ ] **Step 1: Write all server tests**

```python
"""Tests for the Afterwords FastAPI server.

All tests use a mocked ML model — no GPU, no model download,
no network access. The mock generates a tiny valid WAV file
to exercise the full synthesis response path.
"""
import server


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "ready" in data
    assert "voices" in data


def test_health_lists_voices(client, sample_voice):
    r = client.get("/health")
    assert sample_voice in r.json()["voices"]


def test_synthesize_returns_wav(client, sample_voice):
    r = client.get("/synthesize", params={"text": "Hello", "voice": sample_voice})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert "x-synthesis-time" in r.headers
    assert "x-duration" in r.headers


def test_synthesize_missing_text(client):
    r = client.get("/synthesize")
    assert r.status_code == 422


def test_synthesize_empty_text(client):
    r = client.get("/synthesize", params={"text": " "})
    assert r.status_code == 400
    assert "empty" in r.json()["error"]


def test_synthesize_text_too_long(client):
    r = client.get("/synthesize", params={"text": "x" * 5001})
    assert r.status_code == 400
    assert "too long" in r.json()["error"]


def test_synthesize_unknown_voice(client):
    r = client.get("/synthesize", params={"text": "Hi", "voice": "nonexistent"})
    assert r.status_code == 400
    data = r.json()
    assert "unknown voice" in data["error"]
    assert "available" in data


def test_synthesize_not_ready(client):
    server._ready.clear()
    r = client.get("/synthesize", params={"text": "Hi", "voice": "testvoice"})
    assert r.status_code == 503
    server._ready.set()


def test_synthesize_default_voice(client, sample_voice):
    # Temporarily set testvoice as default so the test has a valid default
    original = server.DEFAULT_VOICE
    server.DEFAULT_VOICE = sample_voice
    r = client.get("/synthesize", params={"text": "Hello"})
    server.DEFAULT_VOICE = original
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_resolve_voice_known(sample_voice):
    result = server._resolve_voice(sample_voice)
    assert result is not None
    path, text = result
    assert isinstance(path, str)
    assert isinstance(text, str)


def test_resolve_voice_unknown():
    result = server._resolve_voice("definitely_not_a_voice")
    assert result is None
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_server.py -v`
Expected: all 11 tests pass

- [ ] **Step 3: Run full suite to see styled output**

Run: `pytest`
Expected: styled output with checkmarks, group headers, 26 passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add server endpoint tests (11 cases)"
```

---

### Task 5: Update documentation

**Files:**
- Modify: `README.md` (add Testing section after Troubleshooting)
- Modify: `CLAUDE.md` (replace no-tests line, add test commands)
- Modify: `AGENTS.md` (replace no-tests line, add test commands)

- [ ] **Step 1: Add Testing section to README.md**

After the "Troubleshooting" section (around line 186), add:

```markdown
## Testing

```bash
pip install pytest httpx
pytest
```

Tests cover the server API (endpoint validation, error handling, voice resolution) and the strip-markdown text transform (every regex pattern, plus a golden test with a realistic Claude response). The server tests mock the ML model — no GPU or model download needed.

Run a single test:

```bash
pytest tests/test_strip_markdown.py::test_inline_code_keeps_content
```
```

- [ ] **Step 2: Update CLAUDE.md**

Replace "No test suite exists. Verify changes manually with the health and synthesize endpoints." with "Verify changes with `pytest` (no GPU required). Run a single test with `pytest tests/test_server.py::test_health_returns_ok`."

Add to the Commands section:

```bash
# Run tests (no GPU required)
pip install pytest httpx
pytest

# Run a single test
pytest tests/test_server.py::test_health_returns_ok
```

- [ ] **Step 3: Update AGENTS.md**

Same changes as CLAUDE.md.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md AGENTS.md
git commit -m "docs: add testing documentation"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite from clean state**

Run: `pytest`
Expected: 26 passed, styled output with banner, group headers, and checkmarks

- [ ] **Step 2: Verify strip_markdown.py works as stdin script**

Run: `echo "## Hello **world** with \`code\`" | python3 strip_markdown.py`
Expected: `Hello world with code`

- [ ] **Step 3: Verify setup.sh syntax**

Run: `bash -n setup.sh`
Expected: no output (clean)

- [ ] **Step 4: Verify server.py syntax**

Run: `python3 -c "import ast; ast.parse(open('server.py').read()); print('OK')"`
Expected: `OK`
