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
