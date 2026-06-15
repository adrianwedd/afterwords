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
# `... || afplay ...`, `exec afplay ...`, and wrappers that carry their own
# options/assignments (`env FOO=1 afplay`, `time -p afplay`, `nice -n 10 afplay`).
#
# Wrappers may take their own flags / VAR=val assignments / numeric flag-values
# before the target command; control keywords (`then`/`do`/`else`) take none. A
# wrapper arg is deliberately NOT a bare word, so `env mycmd afplay` (where afplay
# is mycmd's argument, not a command) is not mistaken for an afplay invocation.
_WRAPPER = r'(?:exec|command|builtin|env|time|nice|nohup|caffeinate|stdbuf)'
_WRAPPER_ARG = r'(?:-{1,2}[\w-]+|[A-Za-z_]\w*=[^\s;&|(){}]*|\d[\w.]*)\s+'
_KEYWORD = r'(?:then|do|else)'
_CMD_PREFIX = (
    r'(?:' + _WRAPPER + r'\s+(?:' + _WRAPPER_ARG + r')*'  # wrapper + its flags/assignments
    r'|' + _KEYWORD + r'\s+)'                             # or a bare control keyword
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


# The guard must DIRECTLY protect the afplay: `[ -f "$MUTE_FILE" ] || afplay ...`,
# the `||` connecting straight to the (optionally wrapper/path-qualified) afplay.
# A line that merely *contains* the guard substring but runs afplay through a
# separate, unconditional command (`... || true; afplay`) is fail-open and must
# NOT count as guarded. Quotes are NOT stripped here — the guard literally
# contains "$MUTE_FILE".
_GUARD_RE = re.compile(
    re.escape(GUARD) +              # [ -f "$MUTE_FILE" ]
    r'\s*\|\|\s*'                   # directly OR-guarded
    r'(?:' + _CMD_PREFIX + r')*'    # optional wrapper/keyword prefixes (exec, ...)
    r'(?:[^\s;&|(){}]*/)?'          # optional path qualifier (/usr/bin/)
    r'afplay(?=\s|$|;)'
)


def _afplay_line_is_guarded(line: str) -> bool:
    """True iff this line's afplay is actually protected by the mute guard — the
    guard must be `||`-connected straight to the afplay command, not merely
    present somewhere on the line."""
    return bool(_GUARD_RE.search(line))


# Python guard (Hermes native hook): `if not Path("/tmp/afterwords-muted").exists():`
_PY_GUARD_RE = re.compile(
    r'if\s+not\s+Path\(\s*["\']' + re.escape(MUTE_FILE_PATH) + r'["\']\s*\)\.exists\(\)\s*:'
)


def _py_afplay_is_guarded(lines: list[str], idx: int) -> bool:
    """True iff the afplay subprocess call at line `idx` is genuinely enclosed by
    a real mute guard — a non-commented `if not Path("/tmp/afterwords-muted")
    .exists():` whose block actually contains the call.

    Walking upward through the few lines above the call, we track the smallest
    indent of the intervening code lines. A candidate guard encloses the call
    only if it is less-indented than every one of those body lines: a dedent back
    to (or below) the guard's own indent means the call is a sibling statement,
    not inside the block, so it does NOT count. A commented-out guard never
    counts."""
    body_min = len(lines[idx]) - len(lines[idx].lstrip())
    for j in range(idx - 1, max(-1, idx - 8), -1):
        ln = lines[j]
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip())
        if _PY_GUARD_RE.search(ln):
            return indent < body_min
        body_min = min(body_min, indent)
    return False


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
        assert _afplay_line_is_guarded(ln), (
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
        assert _py_afplay_is_guarded(lines, i), (
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
    'env FOO=1 afplay "$WAV"',                  # env + assignment — was MISSED
    'time -p afplay "$WAV"',                    # time + flag — was MISSED
    'nice -n 10 afplay "$WAV"',                 # nice + flag + value — was MISSED
    'nohup nice -5 afplay "$WAV"',             # chained wrappers w/ flag
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
    # A wrapper whose *command* is something else, with afplay only an argument —
    # the wrapper-flag loosening below must not let this slip through.
    'env mycmd afplay out.wav',
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


# --- Regression: shell guard must DIRECTLY protect afplay ---------------------
# QA found the guard check was line-substring based (`GUARD in ln`): it only asked
# whether `[ -f "$MUTE_FILE" ]` appeared *anywhere* on the afplay line. That is
# fail-open — `[ -f "$MUTE_FILE" ] || true; afplay x` carries the guard substring
# yet runs afplay unconditionally (the guard short-circuits into `true`, then `;`
# starts a fresh, unguarded command). The guard must be `||`-connected straight to
# the afplay, the proven form `[ -f "$MUTE_FILE" ] || afplay ...`.

_GUARDED_LINES = [
    '[ -f "$MUTE_FILE" ] || afplay "$WAV" 2>/dev/null',          # canonical
    '[ -f "$MUTE_FILE" ] || afplay "$TMP_WAV" 2>/dev/null || true',  # trailing || true
    '            [ -f "$MUTE_FILE" ] || afplay "$PREV_WAV" 2>/dev/null',  # indented
    '[ -f "$MUTE_FILE" ] || /usr/bin/afplay "$WAV"',            # path-qualified
    '[ -f "$MUTE_FILE" ] || exec afplay "$WAV"',                # wrapper after guard
]

_FAIL_OPEN_LINES = [
    '[ -f "$MUTE_FILE" ] || true; afplay "$WAV"',         # guard short-circuits, afplay after ;
    '[ -f "$MUTE_FILE" ] && echo muted; afplay "$WAV"',   # guard present, afplay still unconditional
    'echo "$MUTE_FILE"; afplay "$WAV"',                   # MUTE_FILE mentioned, no real guard
    'afplay "$WAV"',                                      # no guard at all
]


@pytest.mark.parametrize("line", _GUARDED_LINES)
def test_guard_detects_directly_protected_afplay(line):
    assert _afplay_line_is_guarded(line), (
        f"a directly-guarded afplay must be recognized as guarded: {line!r}"
    )


@pytest.mark.parametrize("line", _FAIL_OPEN_LINES)
def test_guard_rejects_afplay_not_directly_protected(line):
    assert not _afplay_line_is_guarded(line), (
        f"afplay not `||`-connected to the guard must read as UNGUARDED: {line!r}"
    )


# --- Regression: handler.py guard must be a REAL (uncommented) if-block --------
# QA found the Python check was a 6-line substring window for "afterwords-muted":
# a *commented-out* guard above the call would still satisfy it (fail-open). The
# guard must be a real `if not Path(...).exists():` (not a comment) at a lower
# indent than the afplay call — i.e. the call genuinely sits inside the block.

_PY_GUARDED_BLOCK = [
    '            if not Path("/tmp/afterwords-muted").exists():',
    '                subprocess.call(',
    '                    ["afplay", str(play_path)],',
    '                )',
]
_PY_COMMENTED_GUARD = [
    '            # if not Path("/tmp/afterwords-muted").exists():',
    '            subprocess.call(',
    '                ["afplay", str(play_path)],',
    '            )',
]
_PY_NO_GUARD = [
    '            subprocess.call(',
    '                ["afplay", str(play_path)],',
    '            )',
]
# A guard block whose body ends BEFORE the afplay: the call dedents back to the
# guard's own indent (a sibling statement), so afplay runs unconditionally. The
# guard exists nearby but does not enclose the call — must read as UNGUARDED.
_PY_SIBLING_GUARD = [
    '            if not Path("/tmp/afterwords-muted").exists():',  # idx 0, indent 12
    '                do_other()',                                  # idx 1, indent 16 (in block)
    '            subprocess.call(',                                # idx 2, indent 12 (dedent → sibling)
    '                ["afplay", str(play_path)],',                 # idx 3, indent 16
    '            )',                                               # idx 4, indent 12
]


def test_py_guard_detects_real_if_block():
    assert _py_afplay_is_guarded(_PY_GUARDED_BLOCK, 2)


def test_py_guard_rejects_commented_out_guard():
    assert not _py_afplay_is_guarded(_PY_COMMENTED_GUARD, 2), (
        "a commented-out guard above the call must read as UNGUARDED"
    )


def test_py_guard_rejects_missing_guard():
    assert not _py_afplay_is_guarded(_PY_NO_GUARD, 1)


def test_py_guard_rejects_sibling_block_not_enclosing_afplay():
    assert not _py_afplay_is_guarded(_PY_SIBLING_GUARD, 3), (
        "a guard whose block ends before the call (afplay dedented to a sibling) "
        "must read as UNGUARDED"
    )
