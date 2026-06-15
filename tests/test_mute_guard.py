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
# of a line (possibly indented), after a shell separator (`;` `&` `|` `(` `{`) or
# `||`/`&&`, optionally behind a command wrapper/keyword (`exec`, `command`,
# `env`, `time`, `nohup`, `caffeinate`, `then`, `do`, `else`, ...) and optionally
# path-qualified (/usr/bin/afplay), followed by an argument or end of line.
# Quoted-string content is stripped before matching (see `_strip_quotes`), so
# afplay inside echo/help text — e.g. `echo "... && afplay test.wav"` — is NOT
# counted. This matches `afplay "$WAV"`, `afplay $WAV`, `afplay /x.wav`,
# `... || afplay ...`, and `exec afplay ...`.
_CMD_PREFIX = (
    r'(?:exec|command|builtin|env|time|nice|nohup|caffeinate|stdbuf'
    r'|then|do|else)\s+'
)
INVOCATION_RE = re.compile(
    r'(?:^\s*|[;&|({]\s*)'        # command position: line start or a separator
    r'(?:' + _CMD_PREFIX + r')*'  # optional wrapper/keyword prefixes (exec, ...)
    r'(?:[^\s;&|(){}]*/)?'        # optional path qualifier (/usr/bin/)
    r'afplay(?=\s|$|;)'           # afplay as its own word
)

# Shell string literals ('...' and "..."). Stripped before invocation matching so
# afplay mentioned inside help text / echo output is not mistaken for a command;
# real invocations (afplay "$WAV") keep the bare `afplay` token after stripping.
_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')


def _strip_quotes(line: str) -> str:
    return _QUOTED_RE.sub("", line)


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
        if not ln.lstrip().startswith("#") and INVOCATION_RE.search(_strip_quotes(ln))
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


# --- Regression: command-position detection (PR #92 QA hardening) -------------
# QA (codex/agy/hermes) found INVOCATION_RE both *missed* real invocations behind
# a wrapper/keyword prefix (`exec afplay`) and *false-positived* on afplay inside
# quoted help text (clone-voice.sh's `echo "... && afplay test.wav"`), which also
# let the EXEMPT integrity check pass off help text. These pin both directions.

# Real command invocations that MUST be detected as afplay sites.
_REAL_INVOCATIONS = [
    'afplay "$WAV"',
    '    afplay "$WAV"',                        # indented
    'afplay $WAV',                              # unquoted var
    'afplay /tmp/x.wav',                        # literal path arg
    '/usr/bin/afplay "$WAV"',                   # path-qualified
    '[ -f "$MUTE_FILE" ] || afplay "$WAV"',     # the canonical guarded form
    'foo && afplay "$WAV"',                     # &&-chained
    'foo; afplay "$WAV"',                       # ;-chained
    'cat x | afplay -',                         # pipe
    'exec afplay "$WAV"',                       # exec wrapper — was MISSED
    'exec /usr/bin/afplay "$WAV"',              # exec + path qualifier
    'time afplay "$WAV"',                       # time wrapper
    'command afplay "$WAV"',                    # command wrapper
    'env afplay "$WAV"',                        # env wrapper
    'nohup afplay "$WAV"',                      # nohup wrapper
    'if cond; then afplay "$WAV"; fi',          # then keyword
    '{ afplay "$WAV"; }',                       # brace group
]

# Mentions of afplay that are NOT command invocations and MUST NOT be counted:
# afplay appears as string/help/echo *data*, not as a command.
_NON_INVOCATIONS = [
    'echo "run: afplay out.wav"',
    "echo 'afplay out.wav'",
    'echo afplay',                              # prints the literal word
    '    echo -e "    ${DIM}afplay out.wav${NC}"',
    # The exact clone-voice.sh:432 help line (escaped inner quotes and all).
    r'echo -e "  curl \"localhost:7860/synthesize?voice=x\" -o test.wav && afplay test.wav"',
]


@pytest.mark.parametrize("line", _REAL_INVOCATIONS)
def test_regex_detects_real_afplay_invocations(line):
    assert _afplay_lines(line), f"regex failed to detect a real invocation: {line!r}"


@pytest.mark.parametrize("line", _NON_INVOCATIONS)
def test_regex_ignores_afplay_in_strings_and_help_text(line):
    assert not _afplay_lines(line), f"regex false-positived on a non-invocation: {line!r}"


def test_clone_voice_help_text_not_counted_keeps_exempt_check_honest():
    """clone-voice.sh has a real foreground preview afplay AND a help line that
    only prints an afplay example. Only the real invocation may count — otherwise
    the EXEMPT integrity check could be satisfied by help text alone."""
    detected = _afplay_lines((REPO / "clone-voice.sh").read_text())
    assert any('afplay "$TEST_WAV"' in ln for ln in detected), (
        "real post-clone preview afplay must still be detected"
    )
    assert not any("curl" in ln and "afplay test.wav" in ln for ln in detected), (
        "help-text afplay example must NOT be counted as a playback site"
    )
