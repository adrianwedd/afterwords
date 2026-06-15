"""Every local-playback path must honor the `afterwords mute` flag.

`afterwords mute` toggles /tmp/afterwords-muted. Each worker that plays audio
locally via afplay must skip that playback (but keep synthesizing + archiving,
so archive-driven Discord/Telegram delivery still fires) when the flag exists.
The proven pattern, from the Claude worker, is:

    [ -f "$MUTE_FILE" ] || afplay "$WAV" 2>/dev/null

This test guards against a new afplay site being added without the mute check.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

MUTE_FILE_PATH = "/tmp/afterwords-muted"

# Scripts containing a local afplay invocation that must respect the mute flag.
# setup.sh carries the Claude worker heredoc (already guarded — the reference).
PLAYBACK_SCRIPTS = [
    "setup.sh",
    ".claude/hooks/codex-tts-worker.sh",
    "scripts/afterwords-post-llm.sh",
    "scripts/afterwords-tts-command.sh",
    "scripts/hermes-tts.sh",
]

# A real afplay invocation in these scripts always passes a quoted shell var
# (afplay "$WAV"); this avoids matching help text like `echo "... afplay out.wav"`.
INVOCATION_RE = re.compile(r'afplay\s+"\$')
GUARD = '[ -f "$MUTE_FILE" ]'


@pytest.mark.parametrize("rel", PLAYBACK_SCRIPTS)
def test_afplay_invocations_are_mute_guarded(rel):
    path = REPO / rel
    text = path.read_text()

    invocations = [
        ln for ln in text.splitlines()
        if INVOCATION_RE.search(ln) and not ln.lstrip().startswith("#")
    ]
    assert invocations, f"{rel}: expected at least one afplay invocation to check"

    assert MUTE_FILE_PATH in text, (
        f"{rel}: must define the mute flag path (MUTE_FILE=\"{MUTE_FILE_PATH}\")"
    )

    for ln in invocations:
        assert GUARD in ln, (
            f"{rel}: unguarded afplay — wrap it as `{GUARD} || afplay ...`:\n    {ln.strip()}"
        )
