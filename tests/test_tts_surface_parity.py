"""Parity between the TTS execution surfaces.

The gateway hook (`hermes/hooks/afterwords-tts/handler.py`) and the direct-CLI
shell hook (`scripts/afterwords-post-llm.sh`) must apply the SAME markdown rules
and the SAME chunking. They used to carry private copies and drifted, so these
tests fail if either surface grows its own implementation again.

`_run_shell_hook` drives the real shell hook with curl/afplay/lame/composer stubs
on PATH, so the assertions are about what the hook actually sends to the TTS
server, not about what its source text looks like.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HANDLER_PATH = REPO / "hermes/hooks/afterwords-tts/handler.py"
SHELL_HOOK = REPO / "scripts/afterwords-post-llm.sh"
STRIP_MODULE = REPO / "strip_markdown.py"
CHUNKS_MODULE = REPO / "chunks.py"

# The QA fixture: headings, bullets, numbered list, inline markup, a URL and the
# Hermes model/token footer — the shapes that used to diverge, and long enough
# (well past the old 1000-char cap) that a truncating surface is obvious.
LONG_REPLY = textwrap.dedent(
    """\
    ## Convergence Report

    Summary of the work:

    - the first bullet is deliberately long enough to matter for chunking
    - the second bullet continues the list with more spoken words
    - the third bullet closes it out

    1. numbered step one
    2. numbered step two

    Some **bold** text, some `inline code`, and a link to [the docs](https://example.com/docs).

    ### Detail section

    """
) + ("This paragraph exists purely to push the reply past the old thousand character cap so a truncating surface is caught. " * 12) + "\n\nglm-5.1 · 9% · ~\n"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_handler():
    return _load(HANDLER_PATH, "afterwords_hermes_handler_parity")


def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_shell_hook(tmp_path: Path, response: str, platform: str = "cli"):
    """Run the real shell hook with stubbed externals; return the requests it made.

    Returns (requests, result) where requests is a list of argv lists handed to
    curl. The stub logs each argument on its own line inside ARG/END record
    frames — joining argv with spaces would corrupt multi-word argument values
    like `text=...`. It synthesises a >1000-byte fake WAV for any `-o <path>` so
    the hook's size check passes.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "requests.log"

    _write_exe(
        bindir / "curl",
        "#!/usr/bin/env bash\n"
        '{\n'
        '  printf "%s\\n" "---ARG---"\n'
        '  for a in "$@"; do printf "%s\\n" "$a"; done\n'
        '  printf "%s\\n" "---END---"\n'
        f'}} >> "{log}"\n'
        'out=""; prev=""\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "-o" ]; then out="$a"; fi\n'
        '  prev="$a"\n'
        'done\n'
        'if [ -n "$out" ]; then head -c 4000 /dev/zero > "$out"; fi\n'
        "exit 0\n",
    )
    for tool in ("afplay", "lame", "ffmpeg"):
        _write_exe(bindir / tool, "#!/usr/bin/env bash\nexit 0\n")
    _write_exe(bindir / "hermes", "#!/usr/bin/env bash\nexit 0\n")

    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True, exist_ok=True)

    payload = json.dumps(
        {"hook_event_name": "post_llm_call", "session_id": "parity",
         "cwd": str(tmp_path), "extra": {"assistant_response": response, "platform": platform}}
    )
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HOME"] = str(home)
    env.pop("AFTERWORDS_REPO", None)
    env["HERMES_SESSION_PLATFORM"] = platform

    result = subprocess.run(
        ["bash", str(SHELL_HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=180,
    )
    return _parse_records(log), result


def _parse_records(log: Path) -> list[list[str]]:
    """Parse the ARG/END framed curl log into a list of argv lists."""
    if not log.exists():
        return []
    records: list[list[str]] = []
    current: list[str] | None = None
    for line in log.read_text().splitlines():
        if line == "---ARG---":
            current = []
        elif line == "---END---":
            if current is not None:
                records.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return records


def _chunk_texts(requests, endpoint: str = "/synthesize") -> list[str]:
    """Pull `--data-urlencode text=...` values out of recorded curl argv lists."""
    import urllib.parse

    texts = []
    for argv in requests:
        if not any(endpoint in arg for arg in argv):
            continue
        for i, token in enumerate(argv):
            if token == "--data-urlencode" and i + 1 < len(argv):
                key, _, value = argv[i + 1].partition("=")
                if key == "text":
                    texts.append(urllib.parse.unquote(value))
    return texts


# --------------------------------------------------------------------------
# Canonical modules agree with each other
# --------------------------------------------------------------------------

def test_scripts_strip_shim_resolves_the_repo_module():
    shim = _load(REPO / "scripts/strip-markdown.py", "aw_strip_shim")
    assert shim.canonical_source() == str(STRIP_MODULE)


def test_scripts_chunk_shim_matches_canonical_chunker():
    canonical = _load(CHUNKS_MODULE, "aw_chunks_a").chunk_text(LONG_REPLY)
    shim = _load(REPO / "scripts/chunk-text.py", "aw_chunk_shim")
    assert shim._load().chunk_text(LONG_REPLY) == canonical


def test_footer_is_stripped_by_the_canonical_module():
    cleaned = _load(STRIP_MODULE, "aw_strip_a").strip_markdown(LONG_REPLY, max_chars=None)
    assert "·" not in cleaned, f"footer survived: {cleaned[-80:]!r}"


def test_long_reply_is_not_truncated_by_the_canonical_module():
    cleaned = _load(STRIP_MODULE, "aw_strip_b").strip_markdown(LONG_REPLY, max_chars=None)
    assert len(cleaned) > 1000, "canonical stripper truncated a long reply"


# --------------------------------------------------------------------------
# Gateway hook == canonical modules
# --------------------------------------------------------------------------

def test_handler_strip_matches_canonical_module():
    handler = _load_handler()
    canonical = _load(STRIP_MODULE, "aw_strip_c")
    assert handler.strip_markdown(LONG_REPLY) == canonical.strip_markdown(LONG_REPLY, max_chars=None).strip()


def test_handler_chunking_matches_canonical_module():
    handler = _load_handler()
    canonical = _load(CHUNKS_MODULE, "aw_chunks_b")
    text = _load(STRIP_MODULE, "aw_strip_d").strip_markdown(LONG_REPLY, max_chars=None)
    assert handler.chunk_text(text) == canonical.chunk_text(text)


def test_handler_resolves_canonical_helpers_not_fallbacks(caplog):
    import logging

    handler = _load_handler()
    with caplog.at_level(logging.WARNING, logger="afterwords-tts"):
        handler.strip_markdown(LONG_REPLY)
        handler.chunk_text("Hello there. A second sentence.")
    warnings = [r.getMessage() for r in caplog.records if "fallback" in r.getMessage().lower()]
    assert not warnings, f"canonical helpers did not resolve: {warnings}"


def test_handler_preserves_pause_cues_for_headings_and_bullets():
    handler = _load_handler()
    cleaned = handler.strip_markdown(LONG_REPLY)
    assert "Convergence Report." in cleaned, "heading lost its pause cue"
    assert "first bullet is deliberately long enough" in cleaned
    assert "numbered step two." in cleaned


# --------------------------------------------------------------------------
# CLI shell hook == canonical modules (drives the real hook)
# --------------------------------------------------------------------------

def test_cli_shell_hook_uses_canonical_strip_and_chunking(tmp_path):
    requests, result = _run_shell_hook(tmp_path, LONG_REPLY)
    assert result.returncode == 0, result.stderr

    handler = _load_handler()
    expected_clean = handler.strip_markdown(LONG_REPLY)
    expected_chunks = handler.chunk_text(expected_clean)

    sent = _chunk_texts(requests)
    assert sent, f"shell hook made no synth requests; stderr={result.stderr!r}"
    assert sent == expected_chunks, (
        "CLI surface chunked differently from the gateway surface:\n"
        f"  cli={sent}\n  gateway={expected_chunks}"
    )


def test_cli_shell_hook_does_not_truncate_a_long_reply(tmp_path):
    requests, result = _run_shell_hook(tmp_path, LONG_REPLY)
    assert result.returncode == 0, result.stderr
    sent = _chunk_texts(requests)
    spoken = " ".join(sent)
    assert len(spoken) > 1000, f"CLI surface truncated the reply to {len(spoken)} chars"
    tail = "push the reply past the old thousand character cap"
    assert tail in spoken, "content past the old 1000-char cap was dropped"
    assert "·" not in spoken, "footer was spoken by the CLI surface"


def test_cli_shell_hook_ignores_a_legacy_strip_copy(tmp_path):
    """A stale ~/.claude/hooks/strip-markdown.py must not change what is spoken."""
    legacy_home = tmp_path / "home"
    hooks = legacy_home / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    # Legacy copy: no max_chars kwarg, no pause cues, 1000-char truncation.
    (hooks / "strip-markdown.py").write_text(
        "import re\n"
        "def strip_markdown(text):\n"
        "    return re.sub(r'\\s+', ' ', text)[:1000]\n"
    )
    requests, result = _run_shell_hook(tmp_path, LONG_REPLY)
    assert result.returncode == 0, result.stderr
    sent = _chunk_texts(requests)
    handler = _load_handler()
    expected = handler.chunk_text(handler.strip_markdown(LONG_REPLY))
    assert sent == expected, "legacy ~/.claude/hooks copy leaked into the CLI surface"


# --------------------------------------------------------------------------
# Drift guard: no surface carries a private rule set
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["scripts/strip-markdown.py", "scripts/chunk-text.py", "chunk_text.py"],
)
def test_entrypoints_are_thin_no_private_rules(path):
    """Entrypoints delegate; they must not define the rules themselves."""
    source = (REPO / path).read_text()
    for marker in ("re.split", "re.sub(r'`", "_word_split"):
        assert marker not in source, (
            f"{path} re-implements TTS rules ({marker!r}); it should delegate to "
            f"the canonical module instead"
        )


def test_shell_hook_has_no_second_stripper():
    source = SHELL_HOOK.read_text()
    assert "sed 's/`//g" not in source
    # It must call the canonical stripper, not a scripts/-local copy.
    assert "$SCRIPT_DIR/strip-markdown.py" not in source


def test_setup_stamps_repo_hint_into_installed_shims():
    source = (REPO / "setup.sh").read_text()
    assert "scripts/strip-markdown.py" in source
    assert "scripts/chunk-text.py" in source
    assert "_REPO_HINT" in source


# --------------------------------------------------------------------------
# Portability: the hook runs on Linux CI as well as macOS
# --------------------------------------------------------------------------

def test_shell_hook_has_no_bsd_only_stat_size_reads():
    """`stat -f%z` is BSD-only; on Linux it fails and the size check reads 0.

    That made every chunk look unsynthesized and get synthesized a second time
    (CI runs on ubuntu-latest). Size must go through the portable helper.
    """
    source = SHELL_HOOK.read_text()
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "stat -f%z" not in body, "BSD-only stat size read in the hook body"
    assert "file_size()" in source, "portable file_size helper missing"


def test_both_surfaces_allow_time_for_queued_synthesis():
    """Per-chunk timeout must accommodate a chunk queued behind another synthesis.

    Synthesis is serialised server-side and the pipelined loop keeps a second
    request in flight, so a request can wait for a full synthesis of the chunk
    ahead of it. A timeout that only covers network transfer expires and the
    chunk is silently dropped — 30s dropped every chunk after the first.
    """
    import re

    handler = (REPO / "hermes/hooks/afterwords-tts/handler.py").read_text()
    match = re.search(r"^TTS_REQUEST_TIMEOUT = .*$", handler, re.M)
    assert match, "handler has no TTS_REQUEST_TIMEOUT"
    assert "ClientTimeout(total=TTS_REQUEST_TIMEOUT" in handler, (
        "handler fetch does not use TTS_REQUEST_TIMEOUT"
    )

    shell = SHELL_HOOK.read_text()
    assert 'local t="${AFTERWORDS_TTS_TIMEOUT:-180}"' in shell, (
        "shell hook synth timeout is not configurable/bounded correctly"
    )
    assert "--max-time 60 -G" not in shell, (
        "shell hook still uses the marginal 60s per-chunk synth timeout"
    )


def test_file_size_helper_is_portable(tmp_path):
    """Extract the helper and prove it works with BSD stat unavailable."""
    import re

    source = SHELL_HOOK.read_text()
    match = re.search(r"^file_size\(\) \{.*?^\}", source, re.M | re.S)
    assert match, "file_size() not found in the hook"
    helper = tmp_path / "helper.sh"
    helper.write_text(match.group(0))

    probe = tmp_path / "probe.wav"
    probe.write_bytes(b"\0" * 4000)

    # A stat shim that rejects the BSD form, exactly like GNU coreutils.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_stat = bindir / "stat"
    fake_stat.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"-f%z\" ]; then\n"
        "  echo \"stat: cannot read file system information\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "exec /usr/bin/stat \"$@\"\n"
    )
    fake_stat.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    result = subprocess.run(
        ["bash", "-c", f"source {helper!s}; file_size {probe!s}"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "4000", (
        f"file_size returned {result.stdout.strip()!r} with BSD stat unavailable"
    )
