"""Behavioral tests for the messaging-path dedup block in afterwords-post-llm.sh.

Runs the real hook script via subprocess with stubbed external binaries
(curl, lame, hermes, afplay, ffmpeg) on a prepended PATH. python3 stays real —
the script shells out to it for JSON parsing, hashing, and markdown stripping.
Each test uses uuid4 response text so the hardcoded /tmp/afterwords-dedup dir
never collides across runs. CI-safe: no BSD-only tools in the tests themselves.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "afterwords-post-llm.sh"
DEDUP_DIR = Path("/tmp/afterwords-dedup")  # hardcoded in the script

# Stubs log every invocation as "<name> <argv>" to $STUB_LOG so tests can
# assert which external calls actually happened.
CURL_STUB = """#!/usr/bin/env bash
printf 'curl %s\\n' "$*" >> "$STUB_LOG"
# Two call shapes in the script:
#   health: curl -s --max-time 2 URL            -> just exit 0
#   synth:  curl -s -w %{http_code} -o FILE URL -> write FILE, print code
# CURL_SYNTH_CODE (default 200) simulates synthesis failures.
out=""
prev=""
for a in "$@"; do
  [ "$prev" = "-o" ] && out="$a"
  prev="$a"
done
if [ -n "$out" ]; then
  code="${CURL_SYNTH_CODE:-200}"
  [ "$code" = "200" ] && printf 'RIFF-fake-wav-payload' > "$out"
  printf '%s' "$code"
fi
exit 0
"""

NOOP_STUB = """#!/usr/bin/env bash
printf '{name} %s\\n' "$*" >> "$STUB_LOG"
exit 0
"""

# hermes stub can simulate a failed send via HERMES_EXIT
HERMES_STUB = """#!/usr/bin/env bash
printf 'hermes %s\\n' "$*" >> "$STUB_LOG"
exit "${HERMES_EXIT:-0}"
"""


@pytest.fixture
def hook_env(tmp_path):
    """Stub PATH + isolated HOME + empty cwd (no .afterwords lookups hit the repo)."""
    # The script disables dedup when the shared dir is symlinked or foreign-
    # owned; on such a machine these tests would fail confusingly — skip loud.
    if DEDUP_DIR.is_symlink() or (
        DEDUP_DIR.exists() and DEDUP_DIR.stat().st_uid != os.getuid()
    ):
        pytest.skip("/tmp/afterwords-dedup is symlinked or foreign-owned; script disables dedup")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "curl").write_text(CURL_STUB)
    (bindir / "hermes").write_text(HERMES_STUB)
    for name in ("lame", "afplay", "ffmpeg"):
        (bindir / name).write_text(NOOP_STUB.format(name=name))
    for stub in bindir.iterdir():
        stub.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    log = tmp_path / "stub.log"

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["STUB_LOG"] = str(log)

    # Teardown: remove only the markers this test created — the dedup dir is
    # real shared state also used by the live Hermes hook on dev machines.
    before = set(DEDUP_DIR.iterdir()) if DEDUP_DIR.is_dir() else set()
    yield env, log, workdir
    if DEDUP_DIR.is_dir():
        for leftover in set(DEDUP_DIR.iterdir()) - before:
            try:
                leftover.unlink()
            except OSError:
                pass


def run_hook(env, workdir, text, platform="discord"):
    payload = json.dumps({"platform": platform, "response": text, "chat_id": "42"})
    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=workdir,
        timeout=30,
    )


def synth_calls(log):
    """curl invocations that wrote a synth output file (-o); excludes the health check."""
    if not log.exists():
        return []
    return [
        line
        for line in log.read_text().splitlines()
        if line.startswith("curl") and " -o " in line
    ]


def unique_text():
    return f"dedup regression check {uuid.uuid4().hex}"


def test_first_run_synthesizes(hook_env):
    env, log, workdir = hook_env
    result = run_hook(env, workdir, unique_text())
    assert result.returncode == 0, result.stderr
    assert len(synth_calls(log)) == 1
    # Delivery went out through the stub too
    assert any(line.startswith("hermes send") for line in log.read_text().splitlines())


def test_identical_text_is_deduped(hook_env):
    env, log, workdir = hook_env
    text = unique_text()
    first = run_hook(env, workdir, text)
    assert first.returncode == 0, first.stderr
    assert len(synth_calls(log)) == 1
    second = run_hook(env, workdir, text)
    assert second.returncode == 0, second.stderr
    # Marker is fresh (< 60s) -> second run exits before synthesizing
    assert len(synth_calls(log)) == 1


def test_different_text_still_synthesizes(hook_env):
    env, log, workdir = hook_env
    run_hook(env, workdir, unique_text())
    run_hook(env, workdir, unique_text())
    assert len(synth_calls(log)) == 2


def test_failed_synthesis_releases_marker(hook_env):
    env, log, workdir = hook_env
    text = unique_text()
    first = run_hook(dict(env, CURL_SYNTH_CODE="503"), workdir, text)
    assert first.returncode == 0, first.stderr
    assert len(synth_calls(log)) == 1
    # Non-200 released the marker, so a retry of the SAME text is not swallowed
    second = run_hook(env, workdir, text)
    assert second.returncode == 0, second.stderr
    assert len(synth_calls(log)) == 2


def test_failed_send_releases_marker(hook_env):
    env, log, workdir = hook_env
    text = unique_text()
    first = run_hook(dict(env, HERMES_EXIT="1"), workdir, text)
    assert first.returncode == 0, first.stderr
    assert len(synth_calls(log)) == 1
    # hermes send failed -> marker released -> same-text retry synthesizes
    second = run_hook(env, workdir, text)
    assert second.returncode == 0, second.stderr
    assert len(synth_calls(log)) == 2


def test_stale_markers_are_expired(hook_env):
    env, log, workdir = hook_env
    DEDUP_DIR.mkdir(mode=0o700, exist_ok=True)
    stale = DEDUP_DIR / f"discord-{uuid.uuid4().hex[:16]}"
    stale.write_text("0")
    old = time.time() - 4000  # > 60 minutes ago
    os.utime(stale, (old, old))

    result = run_hook(env, workdir, unique_text())
    assert result.returncode == 0, result.stderr
    # The expiry sweep (find -mmin +60 -delete) removed the stale marker
    assert not stale.exists()
    # ...and the run itself still synthesized normally
    assert len(synth_calls(log)) == 1
