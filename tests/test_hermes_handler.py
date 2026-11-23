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
import sqlite3
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

    def slow_call(argv, **kwargs):
        """Stand-in for afplay: blocks its thread for 0.5 s, as real playback would."""
        calls.append(argv)
        import time as _time
        _time.sleep(0.5)
        return 0

    mod.subprocess.call = slow_call

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
    mod.subprocess.call = lambda *a, **kw: calls.append((a, kw))
    asyncio.run(mod._play(wav))
    assert calls == []


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
