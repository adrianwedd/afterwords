"""Every *automatic* local-playback path must honor the `afterwords mute` flag.

`afterwords mute` toggles /tmp/afterwords-muted. Each worker that plays an agent
response locally via afplay must skip that playback — while still synthesizing +
archiving, so archive-driven Discord/Telegram delivery keeps firing — when the
flag exists. The proven shell pattern, from the Claude worker, is:

    [ -f "$MUTE_FILE" ] || afplay "$WAV" 2>/dev/null

and the Python equivalent in the Hermes native hook is:

    if not Path("/tmp/afterwords-muted").exists():
        subprocess.call(["afplay", ...])

This test discovers afplay sites itself (it does not trust a hand-maintained
allowlist) so a *new* unguarded playback site fails CI rather than slipping
through. Foreground, user-initiated playback is exempt — see EXEMPT.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

MUTE_FILE_PATH = "/tmp/afterwords-muted"

# Foreground, user-initiated playback is NOT automatic agent-response TTS, so it
# is intentionally exempt from `afterwords mute`. When a user runs
# `afterwords voices --demo`, previews a freshly cloned voice, or invokes the
# "say this in X's voice" skill, they have explicitly asked to hear audio — mute
# (which silences the per-turn agent voice) should not swallow it. This is the
# documented scope of mute (CLAUDE.md → "Play lock convention / mute"). A *new*
# worker file is never silently exempt: it must guard its afplay or be added
# here with a rationale, or the test below fails.
EXEMPT = {
    "afterwords.sh",           # `afterwords voices --demo`
    "clone-voice.sh",          # post-clone synthesis preview
    "skill/scripts/speak.sh",  # "say X in Y's voice" skill — explicit request
}

# A real afplay *command* invocation: afplay in command position — at the start
# of a line (possibly indented), after a shell separator (`;` `&` `|` `(`), or
# after `||`/`&&` — optionally path-qualified (/usr/bin/afplay), followed by an
# argument or end of line. This matches afplay "$WAV", afplay $WAV, afplay /x.wav
# and `... || afplay ...`, but NOT afplay sitting inside echo/help/comment text.
INVOCATION_RE = re.compile(r'(?:^\s*|[;&|(]\s*)(?:[^\s;&|()]*/)?afplay(?=\s|$)')
GUARD = '[ -f "$MUTE_FILE" ]'

_SKIP_DIR_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}


def _shell_scripts() -> list[Path]:
    return [
        p for p in sorted(REPO.rglob("*.sh"))
        if not _SKIP_DIR_PARTS & set(p.parts)
    ]


def _afplay_lines(text: str) -> list[str]:
    return [
        ln for ln in text.splitlines()
        if INVOCATION_RE.search(ln) and not ln.lstrip().startswith("#")
    ]


# Discover, at collection time, every shell script that actually plays audio.
_AFPLAY_SCRIPTS = [(str(p.relative_to(REPO)), p) for p in _shell_scripts() if _afplay_lines(p.read_text())]
_GUARDED_SCRIPTS = [(rel, p) for rel, p in _AFPLAY_SCRIPTS if rel not in EXEMPT]


def test_discovery_found_the_known_playback_scripts():
    """Sanity: the globber actually finds the automatic workers we expect.

    Guards against the discovery silently matching nothing (e.g. a regex typo),
    which would make every guard assertion below vacuously pass.
    """
    found = {rel for rel, _ in _AFPLAY_SCRIPTS}
    for expected in (
        "setup.sh",  # carries the Claude worker heredoc (the reference guard)
        ".claude/hooks/codex-tts-worker.sh",
        "scripts/afterwords-post-llm.sh",
        "scripts/afterwords-tts-command.sh",
        "scripts/hermes-tts.sh",
    ):
        assert expected in found, f"discovery missed {expected}; found {sorted(found)}"


@pytest.mark.parametrize("rel,path", _GUARDED_SCRIPTS, ids=[rel for rel, _ in _GUARDED_SCRIPTS])
def test_afplay_invocations_are_mute_guarded(rel, path):
    text = path.read_text()

    assert MUTE_FILE_PATH in text, (
        f"{rel}: must wire the mute flag (MUTE_FILE=\"{MUTE_FILE_PATH}\")"
    )

    for ln in _afplay_lines(text):
        assert GUARD in ln, (
            f"{rel}: unguarded afplay — wrap as `{GUARD} || afplay ...`, "
            f"or add {rel!r} to EXEMPT with a rationale:\n    {ln.strip()}"
        )


@pytest.mark.parametrize("rel", sorted(EXEMPT))
def test_exempt_entries_are_real(rel):
    """Keep EXEMPT honest: every entry must exist and actually play audio, so
    stale exemptions can't quietly hide a future regression."""
    path = REPO / rel
    assert path.exists(), f"EXEMPT lists {rel!r} but it does not exist"
    assert _afplay_lines(path.read_text()), (
        f"EXEMPT lists {rel!r} but it has no afplay invocation — drop it"
    )


def test_hermes_handler_afplay_is_mute_guarded():
    """The Hermes native hook plays via subprocess.call(["afplay", ...]); each
    such call must sit under an `afterwords-muted` existence check."""
    path = REPO / "hermes/hooks/afterwords-tts/handler.py"
    lines = path.read_text().splitlines()
    afplay_idxs = [
        i for i, ln in enumerate(lines)
        if '"afplay"' in ln and not ln.lstrip().startswith("#")
    ]
    assert afplay_idxs, "expected afplay subprocess call(s) in handler.py"

    for i in afplay_idxs:
        window = "\n".join(lines[max(0, i - 6):i])
        assert "afterwords-muted" in window, (
            f"handler.py:{i + 1}: afplay not preceded by a mute guard "
            f'(`if not Path("{MUTE_FILE_PATH}").exists():`)'
        )
