"""Behavioral checks for the Hermes native hook (handler.py).

The handler's synth+playback path needs aiohttp; messaging-only installs omit it
(the module-level import is guarded to `aiohttp = None`). A non-messaging (CLI)
`agent:end` arriving on such an install must skip *explicitly* — not dereference
`None.ClientSession`, get rescued by the broad health-check `except`, and log the
misleading "server not reachable".
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sqlite3
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HANDLER_PATH = REPO / "hermes/hooks/afterwords-tts/handler.py"


def _load_handler():
    spec = importlib.util.spec_from_file_location("afterwords_hermes_handler", HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_handle_skips_explicitly_when_aiohttp_missing(caplog):
    mod = _load_handler()
    mod.aiohttp = None  # simulate a messaging-only install (no aiohttp)

    with caplog.at_level(logging.INFO, logger="afterwords-tts"):
        # platform "cli" is NOT telegram/discord, so it does not short-circuit on
        # the messaging-platform check — it reaches the aiohttp guard.
        asyncio.run(mod.handle("agent:end", {"response": "hello world", "platform": "cli"}))

    msgs = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "aiohttp" in msgs, f"expected an explicit aiohttp-missing skip; got: {msgs!r}"
    assert "not reachable" not in msgs, (
        f"must not fall through to the health-check except; got: {msgs!r}"
    )


def test_native_local_only_skips_direct_cli_before_network():
    mod = _load_handler()
    mod.LOCAL_PLATFORMS = ("local",)
    class UnexpectedNetwork:
        def ClientSession(self, *args, **kwargs):
            raise AssertionError("direct CLI must be owned by the shell hook")
    mod.aiohttp = UnexpectedNetwork()
    asyncio.run(mod.handle("agent:end", {"response": "distinct turn", "platform": "cli"}))


def test_installer_local_only_installs_manifest_and_scope(tmp_path):
    import os, subprocess
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)
    env["AFTERWORDS_PYTHON"] = __import__("sys").executable
    result = subprocess.run(["bash", str(REPO / "scripts/install-hermes-hook.sh"), "--local-only"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    hook = tmp_path / "hooks/afterwords-tts"
    assert (hook / "HOOK.yaml").read_text() == (REPO / "hermes/hooks/afterwords-tts/HOOK.yaml").read_text()
    assert 'LOCAL_PLATFORMS = ("local",)' in (hook / "handler.py").read_text()


def test_play_does_not_block_the_calling_event_loop(tmp_path):
    """afplay must run off the loop: an inline call freezes the host gateway for the clip.

    The gateway awaits hook handlers on its event loop, so an inline ``afplay`` (which blocks
    for the whole audio) stalls keepalive pongs and every RPC for that duration -- the client
    then drops a healthy socket with "1011 keepalive ping timeout". Measure loop schedulability
    while a deliberately slow play "runs": the ticker must keep firing.
    """
    mod = _load_handler()
    mod.MUTE_FILE = tmp_path / "not-muted"
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 64)

    calls = []

    class SlowProcess:
        returncode = None
        async def wait(self):
            await asyncio.sleep(0.5)
            self.returncode = 0
            return 0
        def terminate(self):
            self.returncode = -15
        def kill(self):
            self.returncode = -9

    async def slow_exec(*argv, **kwargs):
        calls.append(argv)
        return SlowProcess()

    mod.asyncio.create_subprocess_exec = slow_exec

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(ticker())
        await mod._play(wav)
        ticks_during = ticks
        task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await task
        return ticks_during

    ticks = asyncio.run(scenario())
    assert calls and calls[0][0] == "afplay", calls
    # 0.5 s of playback on a 0.02 s ticker is ~25 ticks; inline it would be 0 (or 1).
    assert ticks >= 10, f"event loop was starved for the whole clip (only {ticks} ticks in 0.5s)"


def test_play_checks_mute_at_the_side_effect(tmp_path, monkeypatch):
    mod = _load_handler()
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 64)
    muted = tmp_path / "afterwords-muted"
    muted.write_text("")
    monkeypatch.setattr(mod, "MUTE_FILE", muted)
    calls = []
    async def unexpected(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("muted playback must not spawn")
    mod.asyncio.create_subprocess_exec = unexpected
    asyncio.run(mod._play(wav))
    assert calls == []


def test_handler_default_mute_path_is_pinned(monkeypatch):
    monkeypatch.delenv("AFTERWORDS_MUTE_FILE", raising=False)
    mod = _load_handler()
    assert mod.MUTE_FILE == Path("/tmp/afterwords-muted")


def test_cancellation_stops_playback_before_releasing_lock(tmp_path, monkeypatch):
    mod = _load_handler()
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 64)
    monkeypatch.setattr(mod, "MUTE_FILE", tmp_path / "not-muted")
    monkeypatch.setattr(mod, "PLAY_LOCK", tmp_path / "play.lock")
    monkeypatch.setattr(mod, "PLAY_PID", tmp_path / "play.pid")
    started = asyncio.Event()
    termination_started = asyncio.Event()
    allow_termination = asyncio.Event()

    class OwnedProcess:
        returncode = None
        async def wait(self):
            started.set()
            if self.returncode is None:
                await allow_termination.wait()
                self.returncode = -15
            return self.returncode
        def terminate(self):
            termination_started.set()
        def kill(self):
            self.returncode = -9
            allow_termination.set()

    process = OwnedProcess()
    async def fake_exec(*_args, **_kwargs):
        return process
    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)

    async def inner(_chunks, _voice, session_pool=None):
        try:
            await mod._play(wav)
        finally:
            wav.unlink(missing_ok=True)

    monkeypatch.setattr(mod, "_speak_chunked_inner", inner)

    async def scenario():
        task = asyncio.create_task(mod._speak_chunked(["hello"], "worf"))
        await started.wait()
        assert mod.PLAY_LOCK.is_dir()
        task.cancel()
        await termination_started.wait()
        assert mod.PLAY_LOCK.is_dir(), "lease released before afplay termination completed"
        allow_termination.set()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not mod.PLAY_LOCK.exists()
    assert not mod.PLAY_PID.exists()
    assert not wav.exists()


def test_partial_handler_output_never_publishes_completion_sidecar(tmp_path, monkeypatch):
    mod = _load_handler()
    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: tmp_path))
    responses = iter([b"R" * 1500, None])

    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False

    mod.aiohttp = types.SimpleNamespace(ClientSession=lambda: Session())
    async def fake_fetch(_session, _url):
        return next(responses)
    async def fake_play(_path):
        return None
    def fake_archive(wav_path, mp3_name, archive_dir):
        (archive_dir / mp3_name).write_bytes(b"partial")
        wav_path.unlink(missing_ok=True)
        return True
    monkeypatch.setattr(mod, "_fetch_audio", fake_fetch)
    monkeypatch.setattr(mod, "_play", fake_play)
    monkeypatch.setattr(mod, "_archive_wav_and_cleanup", fake_archive)

    asyncio.run(mod._speak_chunked_inner(["first", "second"], "worf"))
    archive = tmp_path / ".hermes" / "tts-archive"
    assert list(archive.glob("*.mp3")), "the surviving partial artifact should remain evidence"
    assert not list(archive.glob("*.txt")), "partial output must not masquerade as complete"


def test_hook_session_identity_routes_concurrent_projects(tmp_path, monkeypatch):
    mod = _load_handler()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / ".afterwords").write_text("hermes: worf\n")
    (second / ".afterwords").write_text("hermes: galadriel\n")
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as con:
        con.execute("create table sessions (id text primary key, cwd text, last_activity_at real)")
        con.execute("insert into sessions values ('first-id', ?, 1)", (str(first),))
        con.execute("insert into sessions values ('second-id', ?, 9999999999)", (str(second),))
    monkeypatch.setattr(mod, "STATE_DB", db)
    assert mod.resolve_voice({"session_id": "first-id"}) == "worf"
    assert mod.resolve_voice({"session_id": "second-id"}) == "galadriel"
    # No identity means no project guess, even though one session is newest.
    monkeypatch.setattr(mod, "GLOBAL_AFTERWORDS", tmp_path / "absent")
    assert mod.resolve_voice({}) is None
