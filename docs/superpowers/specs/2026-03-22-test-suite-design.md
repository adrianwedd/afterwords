# Test Suite Design — Afterwords

**Date:** 2026-03-22
**Status:** Approved

## Overview

Add a pytest-based test suite to Afterwords covering the two testable surfaces: the FastAPI server endpoints and the strip-markdown text transform. Tests run without a GPU or model download. The test runner output is styled to match the project's polished terminal aesthetic.

## Goals

1. Catch regressions in server endpoint validation and error handling
2. Catch regressions in the markdown-stripping pipeline (the inline code content-deletion bug that prompted this work)
3. Provide a pleasant, readable test runner experience
4. Document how to run tests for humans and AI agents

## Non-Goals

- Testing actual ML model loading or audio quality (integration/manual concern)
- Testing shell scripts (setup.sh, clone-voice.sh) — system side effects make unit testing impractical
- CI/CD pipeline — no GitHub Actions; tests are run locally

## File Structure

```
afterwords/
├── strip_markdown.py          ← NEW: extracted module (single function)
├── pytest.ini                 ← NEW: minimal pytest config
├── tests/
│   ├── conftest.py            ← NEW: fixtures + custom runner UX
│   ├── test_server.py         ← NEW: FastAPI endpoint tests
│   └── test_strip_markdown.py ← NEW: text transform tests
├── server.py                  ← unchanged
├── setup.sh                   ← modified: copies strip_markdown.py instead of inlining
├── README.md                  ← modified: add Testing section
├── CLAUDE.md                  ← modified: add test commands
└── AGENTS.md                  ← modified: add test commands
```

## Component 1: strip_markdown.py extraction

### What changes

A new file `strip_markdown.py` at the repo root containing a single function:

```python
def strip_markdown(text: str) -> str:
    """Strip markdown formatting for cleaner TTS output."""

if __name__ == "__main__":
    import sys
    print(strip_markdown(sys.stdin.read()))
```

The `__main__` block is required because `tts-hook.sh` pipes text through `python3 strip-markdown.py` via stdin. Without it, the hook pipeline breaks silently.

This contains the regex pipeline currently generated inline by setup.sh. The function:

1. Removes fenced code blocks (triple backtick)
2. Strips backticks from inline code, **preserving content** (`` `claude` `` → `claude`)
3. Extracts link text, removes URLs
4. Strips heading markers (`##`)
5. Strips bullet list markers (`- `, `* `)
6. Strips numbered list markers (`1. `)
7. Removes table rows (`| col | col |`) and separator rows (`|---|---|`)
8. Strips bold/italic markers
9. Collapses double newlines to period-space
10. Collapses whitespace
11. Truncates to 1000 characters

### setup.sh change

Replace the inline `cat > strip-markdown.py <<'PYEOF'` block with:

```bash
cp "$SCRIPT_DIR/strip_markdown.py" "$HOOKS_DIR/strip-markdown.py"
```

The hook's `tts-hook.sh` continues to pipe text through `python3 ~/.claude/hooks/strip-markdown.py` — no change to the hook invocation.

## Component 2: tests/test_server.py

### Fixtures (in conftest.py)

- **`mock_model`** — Patches `server._get_model` to return a sentinel. Patches `mlx_audio.tts.generate.generate_audio` (the module-level symbol — server.py imports it at call time via deferred `from` import) with a `side_effect` that writes a tiny valid WAV file named `out_0.wav` inside the `output_path` kwarg directory (must match the glob `out_*.wav` that server.py uses at line 266). Sets `server._ready` event. Restores original state on teardown.
- **`client`** — Returns `TestClient(app)` with `mock_model` active.
- **`sample_voice`** — Creates a temporary WAV file, registers a voice named `"testvoice"` in `server.VOICES`, removes it on teardown.

### Test cases

| Function name | What it verifies |
|---|---|
| `test_health_returns_ok` | GET /health → 200, JSON has `status`, `ready`, `voices` keys |
| `test_health_lists_voices` | `voices` array contains registered voice names |
| `test_synthesize_returns_wav` | GET /synthesize?text=Hello&voice=testvoice → 200, content-type audio/wav, has X-Synthesis-Time and X-Duration headers |
| `test_synthesize_missing_text` | GET /synthesize (no text param) → 422, FastAPI validation error |
| `test_synthesize_empty_text` | GET /synthesize?text= → 400, error says "text is empty" |
| `test_synthesize_text_too_long` | GET /synthesize?text=(5001 chars) → 400, error says "text too long" |
| `test_synthesize_unknown_voice` | GET /synthesize?text=Hi&voice=nonexistent → 400, response includes available voices |
| `test_synthesize_not_ready` | _ready event cleared → GET /synthesize → 503 |
| `test_synthesize_default_voice` | GET /synthesize?text=Hello (no voice param) → 200 response (confirms DEFAULT_VOICE is valid and synthesis succeeds without explicit voice) |
| `test_resolve_voice_known` | `_resolve_voice("testvoice")` returns (path, text) tuple |
| `test_resolve_voice_unknown` | `_resolve_voice("nonexistent")` returns None |

### Dependencies

- `pytest` (dev dependency, not in requirements.txt)
- `httpx` (installed by FastAPI's TestClient)
- No ML libraries loaded — all mocked

## Component 3: tests/test_strip_markdown.py

### Test cases

| Function name | Input | Expected output |
|---|---|---|
| `test_preserves_plain_text` | `"Hello world"` | `"Hello world"` |
| `test_inline_code_keeps_content` | `` "`--server-only` flag"`` | `"--server-only flag"` |
| `test_multiple_inline_code_spans` | `` "Use `foo` and `bar`" `` | `"Use foo and bar"` |
| `test_inline_code_special_chars` | `` "`--flag=value` option" `` | `"--flag=value option"` |
| `test_fenced_code_block_removed` | ` ```bash\ncurl localhost\n``` ` | whitespace/empty |
| `test_bold_stripped` | `"**important** thing"` | `"important thing"` |
| `test_italic_stripped` | `"*emphasis* here"` | `"emphasis here"` |
| `test_heading_stripped` | `"## Section Title"` | `"Section Title"` |
| `test_bullet_list_stripped` | `"- item one\n- item two"` | contains `"item one"` and `"item two"` |
| `test_numbered_list_stripped` | `"1. first\n2. second"` | contains `"first"` and `"second"` |
| `test_link_keeps_text` | `"[click here](http://x.com)"` | `"click here"` |
| `test_table_removed` | `"before\n\| a \| b \|\n\|---\|---\|\n\| c \| d \|\nafter"` | contains `"before"` and `"after"`, no pipes |
| `test_truncates_at_1000_chars` | 2000 chars of `"word "` | len(output) ≤ 1000 |
| `test_collapses_whitespace` | `"too   many    spaces"` | `"too many spaces"` |
| `test_real_claude_response` | Multi-paragraph markdown with headings, code blocks, inline code, bold, links, a table, and a numbered list | Readable prose. No backticks, no pipes, no `##`. Inline code content preserved. |

### No fixtures needed

Pure function — import and call directly.

## Component 4: Runner UX (conftest.py)

### Pytest hooks used

- **`pytest_collection_modifyitems`** — Sorts tests by file for grouped display.
- **`pytest_report_teststatus`** — Returns `("", "", "")` to suppress pytest's default per-test dot/F characters. Without this, `-q` mode prints dots alongside the custom checkmark output.
- **`pytest_runtest_logreport`** — On `call` phase: prints group headers (derived from filename: `test_server.py` → `server`, `test_strip_markdown.py` → `strip-markdown`). Prints `✓` (green) or `✗` (red) per test. Test names derived from function name: `test_inline_code_keeps_content` → `inline code keeps content`.
- **`pytest_terminal_summary`** — Prints the banner and final summary line.
- **`pytest_configure`** — Registers the plugin informally (no entry point).

### pytest.ini

```ini
[pytest]
testpaths = tests
addopts = -q --tb=short --no-header
```

The `-q --no-header` suppresses pytest's default output so our custom hooks control the display. `--tb=short` keeps failure tracebacks concise.

### Terminal output (passing)

```
  afterwords  — test suite
  ─────────────────────────────────────────

  server
  ✓ health returns ok
  ✓ health lists voices
  ✓ synthesize returns wav
  ✓ synthesize empty text rejected
  ✓ synthesize text too long rejected
  ✓ synthesize unknown voice rejected
  ✓ synthesize not ready returns 503
  ✓ synthesize uses default voice
  ✓ resolve voice known
  ✓ resolve voice unknown

  strip-markdown
  ✓ preserves plain text
  ✓ inline code keeps content
  ✓ fenced code block removed
  ...

  ─────────────────────────────────────────
  ✓ 27 passed  (0.4s)
```

### Terminal output (failure)

```
  strip-markdown
  ✓ preserves plain text
  ✗ inline code keeps content
      AssertionError: assert '' == 'claude'
  ✓ fenced code block removed
  ...

  ─────────────────────────────────────────
  ✗ 1 failed, 26 passed  (0.3s)
```

## Component 5: Documentation

### README.md

Add a "Testing" section after "Troubleshooting":

```markdown
## Testing

\```bash
pip install pytest
pytest
\```

Tests cover the server API and the strip-markdown text transform.
The server tests mock the ML model — no GPU or model download needed.

Run a single test:

\```bash
pytest tests/test_strip_markdown.py::test_inline_code_keeps_content
\```
```

### CLAUDE.md / AGENTS.md

Replace the line "No test suite exists. Verify changes manually with the health and synthesize endpoints." and add to the Commands section:

```bash
# Run tests (no GPU required)
pip install pytest
pytest

# Run a single test
pytest tests/test_server.py::test_health_returns_ok
```

## Run command

```bash
pip install pytest
pytest
```

No other setup required. Tests do not touch the network, GPU, or filesystem outside of temp directories.
