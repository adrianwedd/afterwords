"""A Codex event must not replay after audio may have started."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from watcher.queue import enqueue


REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / ".claude/hooks/codex-tts-worker.sh"


def _executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _wait_for(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(f"drainer exited before {path.name} appeared: {process.returncode}")
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def test_codex_event_is_terminal_after_playback_failure_or_worker_crash(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    archive = tmp_path / "archive"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".afterwords").write_text("codex: seven-of-nine\n")

    calls = tmp_path / "afplay-calls"
    started = tmp_path / "afplay-started"
    release = tmp_path / "afplay-release"
    _executable(
        fakebin / "curl",
        "#!/bin/bash\n"
        "out=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = '-o' ]; then shift; out=$1; fi\n"
        "  shift\n"
        "done\n"
        "dd if=/dev/zero of=\"$out\" bs=2048 count=1 2>/dev/null\n",
    )
    _executable(
        fakebin / "afplay",
        "#!/bin/bash\n"
        "echo play >> \"$AFPLAY_CALLS\"\n"
        "touch \"$AFPLAY_STARTED\"\n"
        "if [ \"${FAKE_AFPLAY_BLOCK:-0}\" = '1' ]; then\n"
        "  while [ ! -f \"$AFPLAY_RELEASE\" ]; do sleep 0.01; done\n"
        "fi\n"
        "exit 1\n",
    )
    _executable(
        fakebin / "lame",
        "#!/bin/bash\n"
        "for output do :; done\n"
        "printf mp3 > \"$output\"\n",
    )

    # Exercise the macOS worker on Linux CI with real filesystem metadata,
    # rather than relying on GNU stat to accept BSD -f%u/-f%z flags.
    _executable(
        fakebin / "stat",
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "info = os.stat(sys.argv[-1])\n"
        "if sys.argv[1] == '-f%u': print(info.st_uid)\n"
        "elif sys.argv[1] == '-f%z': print(info.st_size)\n"
        "else: raise SystemExit(2)\n",
    )

    env = dict(os.environ)
    env.update(
        PATH=f"{fakebin}:{env['PATH']}",
        HOME=str(home),
        PYTHONPATH=str(REPO),
        AFTERWORDS_RELIABLE_QUEUE="1",
        AFTERWORDS_QUEUE_DIR=str(queue),
        AFTERWORDS_ARCHIVE_DIR=str(archive),
        AFTERWORDS_PLAY_LOCK=str(tmp_path / "play.lock"),
        AFTERWORDS_PLAY_PID=str(tmp_path / "play.pid"),
        AFTERWORDS_MUTE_FILE=str(tmp_path / "muted"),
        AFTERWORDS_PYTHON=sys.executable,
        AFPLAY_CALLS=str(calls),
        AFPLAY_STARTED=str(started),
        AFPLAY_RELEASE=str(release),
        FAKE_AFPLAY_BLOCK="1",
    )
    event = queue / "event-test.json"
    event.write_text(json.dumps({
        "project_dir": str(project),
        "agent": "codex",
        "text": "This Codex response must only be played once.",
    }))

    process = subprocess.Popen(
        [sys.executable, "-m", "watcher.drain", str(WORKER), str(queue)],
        cwd=REPO,
        env=env,
        start_new_session=True,
    )
    _wait_for(started, process)
    playing_receipt = queue / "event-test.playing"
    assert playing_receipt.exists(), "durable receipt must precede afplay"

    # Simulate a worker/process crash while afplay is in progress.
    os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)

    # A subsequent drain must treat .playing as terminal and never call afplay again.
    subprocess.run(
        [sys.executable, "-m", "watcher.drain", str(WORKER), str(queue)],
        cwd=REPO,
        env=env,
        check=True,
        timeout=10,
    )
    assert calls.read_text().splitlines() == ["play"]
    assert playing_receipt.exists()
    assert not list(queue.glob("*.json"))
    assert not list(queue.glob("*.claimed"))

    # A nonzero afplay exit can happen after sound was emitted. It is also a
    # terminal partial delivery, not a reason to synthesize and play again.
    started.unlink()
    env["FAKE_AFPLAY_BLOCK"] = "0"
    (queue / "event-nonzero.json").write_text(json.dumps({
        "project_dir": str(project),
        "agent": "codex",
        "text": "This response exercises the nonzero afplay exit.",
    }))
    subprocess.run(
        [sys.executable, "-m", "watcher.drain", str(WORKER), str(queue)],
        cwd=REPO,
        env=env,
        check=True,
        timeout=10,
    )
    assert (queue / "event-nonzero.failed").exists()
    assert calls.read_text().splitlines() == ["play", "play"]
    subprocess.run(
        [sys.executable, "-m", "watcher.drain", str(WORKER), str(queue)],
        cwd=REPO,
        env=env,
        check=True,
        timeout=10,
    )
    assert calls.read_text().splitlines() == ["play", "play"]


def test_enqueue_treats_playing_receipt_as_terminal(tmp_path):
    session = "codex-session"
    event_id = "assistant-final-record-17"
    queue = tmp_path / "queues" / "codex" / hashlib.sha256(session.encode()).hexdigest()
    queue.mkdir(parents=True)
    name = "event-" + hashlib.sha256(event_id.encode()).hexdigest()
    (queue / f"{name}.playing").write_text("playback may have started\n")

    target = enqueue(tmp_path, "codex", session, event_id, "/project", "response")

    assert target == queue / f"{name}.json"
    assert not target.exists()


def test_legacy_session_queue_still_plays(tmp_path):
    """The per-session watcher runs the worker without a reliable queue; its
    item is removed after parsing, so playback must not wait on a receipt."""
    queue = tmp_path / "queue"
    queue.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".afterwords").write_text("codex: seven-of-nine\n")
    calls = tmp_path / "afplay-calls"
    _executable(fakebin / "curl",
                "#!/bin/bash\nout=''\nwhile [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = '-o' ]; then shift; out=$1; fi\n  shift\ndone\n"
                "[ -n \"$out\" ] && dd if=/dev/zero of=\"$out\" bs=2048 count=1 2>/dev/null\nexit 0\n")
    _executable(fakebin / "afplay", "#!/bin/bash\necho play >> \"$AFPLAY_CALLS\"\n")
    _executable(fakebin / "lame", "#!/bin/bash\nfor output do :; done\nprintf mp3 > \"$output\"\n")
    _executable(fakebin / "stat",
                f"#!{sys.executable}\nimport os, sys\ninfo = os.stat(sys.argv[-1])\n"
                "if sys.argv[1] == '-f%u': print(info.st_uid)\n"
                "elif sys.argv[1] == '-f%z': print(info.st_size)\nelse: raise SystemExit(2)\n")
    env = dict(os.environ)
    env.pop("AFTERWORDS_RELIABLE_QUEUE", None)
    env.update(
        PATH=f"{fakebin}:{env['PATH']}", HOME=str(tmp_path / "home"), PYTHONPATH=str(REPO),
        CODEX_THREAD_ID=f"pytest-{os.getpid()}-{time.monotonic_ns()}",
        AFTERWORDS_QUEUE_DIR=str(queue), AFTERWORDS_ARCHIVE_DIR=str(tmp_path / "archive"),
        AFTERWORDS_PLAY_LOCK=str(tmp_path / "play.lock"), AFTERWORDS_PLAY_PID=str(tmp_path / "play.pid"),
        AFTERWORDS_MUTE_FILE=str(tmp_path / "muted"), AFTERWORDS_PYTHON=sys.executable,
        AFPLAY_CALLS=str(calls),
    )
    (queue / "legacy.json").write_text(json.dumps({
        "project_dir": str(project), "agent": "codex", "text": "A per-session Codex reply.",
    }))
    subprocess.run(["bash", str(WORKER)], cwd=REPO, env=env, check=True, timeout=30)
    assert calls.read_text().splitlines() == ["play"]
    assert not list(queue.glob("*.playing"))
    assert not list(queue.glob("legacy.*"))
