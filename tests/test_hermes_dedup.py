"""Behavioral tests for native speech ownership in afterwords-post-llm.sh.

Runs the real hook script via subprocess with stubbed external binaries
(curl, lame, hermes, afplay, ffmpeg) on a prepended PATH. python3 stays real —
the script shells out to it for JSON parsing, hashing, and markdown stripping.
Each test uses uuid4 response text so the hardcoded /tmp/afterwords-dedup dir
never collides across runs. CI-safe: no BSD-only tools in the tests themselves.
"""
from __future__ import annotations

import json
import os
import shlex
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

    # Private play lock: the real /tmp lock is held by live speech on dev
    # machines, and a CLI turn waits up to ~60s for it.
    hook = tmp_path / "afterwords-post-llm.sh"
    source = SCRIPT.read_text()
    for filename in ("afterwords-play.lock", "afterwords-play.pid"):
        source = source.replace(f'"/tmp/{filename}"', shlex.quote(str(tmp_path / filename)))
    hook.write_text(source)

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["STUB_LOG"] = str(log)
    env["AFTERWORDS_REPO"] = str(REPO)
    env["_TEST_HOOK"] = str(hook)

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
        ["bash", env["_TEST_HOOK"]],
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














def test_cli_scope_skips_gateway_and_external_delivery(hook_env):
    env, log, workdir = hook_env
    env["AFTERWORDS_SHELL_SCOPE"] = "cli"
    for platform in ("local", "discord", "telegram", ""):
        result = run_hook(env, workdir, unique_text(), platform=platform)
        assert result.returncode == 0
    assert not log.exists(), "out-of-scope hooks must not synthesize, play, or send"


def test_cli_scope_skips_gateway_local_mapped_to_cli(hook_env):
    env, log, workdir = hook_env
    env["AFTERWORDS_SHELL_SCOPE"] = "cli"
    env["_HERMES_GATEWAY"] = "1"
    result = run_hook(env, workdir, unique_text(), platform="cli")
    assert result.returncode == 0
    assert not log.exists(), "gateway local turns are owned by the native hook"


@pytest.mark.parametrize("nested", [False, True])
def test_native_playback_owner_skips_all_shell_speech(hook_env, nested):
    env, log, workdir = hook_env
    payload = {"platform": "cli", "response": unique_text()}
    owner = {"tts_playback_owner": "native"}
    payload.update({"extra": owner} if nested else owner)
    result = subprocess.run(
        ["bash", env["_TEST_HOOK"]], input=json.dumps(payload), capture_output=True,
        text=True, env=env, cwd=workdir, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not log.exists(), "native-owned turns must not synthesize, archive or play twice"


def test_ordinary_cli_without_native_owner_still_synthesizes(hook_env):
    env, log, workdir = hook_env
    # CLI rejects implausibly tiny artifacts; use a sufficiently large stub.
    curl = Path(env["PATH"].split(os.pathsep)[0]) / "curl"
    curl.write_text(curl.read_text().replace("RIFF-fake-wav-payload", "RIFF" + "x" * 4096))
    result = run_hook(env, workdir, unique_text(), platform="cli")
    assert result.returncode == 0, result.stderr
    assert len(synth_calls(log)) == 1


@pytest.mark.parametrize("port", ["0", "65536", "localhost:123", "-1"])
def test_shell_profile_port_rejects_invalid_target(hook_env, port):
    env, log, workdir = hook_env
    result = run_hook(dict(env, AFTERWORDS_PORT=port), workdir, unique_text(), platform="cli")
    assert result.returncode == 2
    assert not log.exists()


def test_shell_profile_route_uses_explicit_loopback_port_and_voice(hook_env):
    env, log, workdir = hook_env
    curl = Path(env["PATH"].split(os.pathsep)[0]) / "curl"
    curl.write_text(curl.read_text().replace("RIFF-fake-wav-payload", "RIFF" + "x" * 4096))
    result = run_hook(dict(env, AFTERWORDS_PORT="17862", AFTERWORDS_VOICE="vixen-original-r1"),
                      workdir, unique_text(), platform="cli")
    assert result.returncode == 0, result.stderr
    calls = synth_calls(log)
    assert len(calls) == 1
    assert "http://127.0.0.1:17862/synthesize" in calls[0]
    assert "voice=vixen-original-r1" in calls[0]


@pytest.mark.parametrize("platform", ["discord", "telegram"])
def test_gateway_delivery_is_owned_by_native_voice_mode(hook_env, platform):
    env, log, workdir = hook_env
    result = run_hook(env, workdir, unique_text(), platform=platform)
    assert result.returncode == 0, result.stderr
    assert not log.exists(), "shell hooks must not duplicate gateway delivery"
