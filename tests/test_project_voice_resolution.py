"""Per-project voice resolution for the Hermes command-provider path.

`text_to_speech` fills `{voice}` from `tts.providers.afterwords.voice`, which is
per-profile, so a repo's `.afterwords` never reached that surface. The wrapper
`scripts/afterwords-project-voice.sh` resolves the project file and then hands
an explicit voice to the canonical command script.

Two invariants are pinned here:

* resolution is project-file-or-configured-voice — the global `~/.afterwords`
  is never read on this path, because that file belongs to the default profile
  and reading it is what made the vixen profile speak as seven-of-nine;
* the canonical script still receives an explicit voice and still does not
  resolve `.afterwords` itself (tests/test_hermes_profile_voice.py owns that
  contract).
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts" / "afterwords-project-voice.sh"
CANONICAL = REPO / "scripts" / "afterwords-tts-command.sh"


def _print_voice(project: Path, hermes_home: Path | None = None, home: Path | None = None) -> str:
    env = {
        "PATH": os.environ["PATH"],
        "AFTERWORDS_PROJECT_DIR": str(project),
        # Isolate from the repo's own .afterwords via the $PWD branch.
        "AFTERWORDS_STATE_DB": str(project.parent / "absent.db"),
    }
    if hermes_home is not None:
        env["HERMES_HOME"] = str(hermes_home)
    if home is not None:
        env["HOME"] = str(home)
    result = subprocess.run(
        ["bash", str(WRAPPER), "--print"],
        capture_output=True, text=True, env=env, cwd=str(project), check=True,
    )
    return result.stdout.strip()


def _write_project(tmp_path: Path, content: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".afterwords").write_text(content, encoding="utf-8")
    return project


# ── resolution ────────────────────────────────────────────────────────────

def test_agent_key_wins_over_default(tmp_path):
    project = _write_project(tmp_path, "default: galadriel\nhermes: worf\n")
    assert _print_voice(project) == "worf"


def test_default_fallback_when_agent_key_absent(tmp_path):
    project = _write_project(tmp_path, "default: galadriel\n")
    assert _print_voice(project) == "galadriel"


def test_default_without_space_is_accepted(tmp_path):
    project = _write_project(tmp_path, "default:worf\n")
    assert _print_voice(project) == "worf"


def test_simple_mode_single_voice(tmp_path):
    project = _write_project(tmp_path, "# comment\nworf\n")
    assert _print_voice(project) == "worf"


def test_comments_only_yields_empty(tmp_path):
    project = _write_project(tmp_path, "# nothing configured\n")
    assert _print_voice(project) == ""


def test_missing_project_file_yields_empty(tmp_path):
    project = tmp_path / "bare"
    project.mkdir()
    assert _print_voice(project) == ""


def test_profile_home_selects_its_own_key(tmp_path):
    project = _write_project(tmp_path, "hermes: worf\nvixen: seydoux\ndefault: galadriel\n")
    hermes = tmp_path / ".hermes"
    vixen = hermes / "profiles" / "vixen"
    vixen.mkdir(parents=True)
    assert _print_voice(project, hermes_home=vixen) == "seydoux"
    assert _print_voice(project, hermes_home=hermes) == "worf"


def test_global_afterwords_is_not_consulted(tmp_path):
    """The default profile's global file must not leak onto this path."""
    project = tmp_path / "bare"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / ".afterwords").write_text("hermes: seven-of-nine\n", encoding="utf-8")
    assert _print_voice(project, home=home) == ""


# ── live-session lookup from Hermes state.db ────────────────────────────────

import sqlite3
def _state_db(tmp_path: Path) -> Path:
    """Minimal copy of the Hermes session table this path reads."""
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("create table sessions (id text primary key, cwd text, last_activity_at real)")
    con.commit()
    con.close()
    return db


def _print_with_db(project: Path, db: Path | None, cwd: Path, session_id: str = "") -> str:
    env = {"PATH": os.environ["PATH"], "HERMES_HOME": str(project.parent / ".hermes")}
    if db is not None:
        env["AFTERWORDS_STATE_DB"] = str(db)
    else:
        env["AFTERWORDS_STATE_DB"] = str(project.parent / "absent.db")
    if session_id:
        env["AFTERWORDS_SESSION_ID"] = session_id
    result = subprocess.run(
        ["bash", str(WRAPPER), "--print"],
        capture_output=True, text=True, env=env, cwd=str(cwd), check=True,
    )
    return result.stdout.strip()


def test_exact_session_id_selects_the_project_voice(tmp_path):
    project = _write_project(tmp_path, "hermes: worf\n")
    bare = tmp_path / "bare"
    bare.mkdir()
    db = _state_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("insert into sessions values ('s1', ?, 0)", (str(project),))
    con.commit()
    con.close()
    assert _print_with_db(project, db, bare, "s1") == "worf"


def test_concurrent_sessions_never_borrow_the_newest_project(tmp_path):
    project = _write_project(tmp_path, "hermes: worf\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".afterwords").write_text("hermes: galadriel\n", encoding="utf-8")
    bare = tmp_path / "bare"
    bare.mkdir()
    db = _state_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("insert into sessions values ('s1', ?, 1)", (str(project),))
    con.execute("insert into sessions values ('s2', ?, 9999999999)", (str(other),))
    con.commit()
    con.close()
    assert _print_with_db(project, db, bare, "s1") == "worf"
    assert _print_with_db(project, db, bare, "s2") == "galadriel"


def test_missing_identity_does_not_borrow_a_recent_session(tmp_path):
    project = _write_project(tmp_path, "hermes: worf\n")
    bare = tmp_path / "bare"
    bare.mkdir()
    db = _state_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("insert into sessions values ('s1', ?, 9999999999)", (str(project),))
    con.commit()
    con.close()
    assert _print_with_db(project, db, bare) == ""


def test_missing_state_db_falls_through_to_pwd(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert _print_with_db(bare, None, bare) == ""


def test_native_unknown_session_never_falls_through_to_gateway_pwd(tmp_path):
    wrong = _write_project(tmp_path, "hermes: wrong-conversation\n")
    db = _state_db(tmp_path)
    env = {
        "PATH": os.environ["PATH"],
        "HERMES_HOME": str(tmp_path / ".hermes"),
        "AFTERWORDS_STATE_DB": str(db),
        "AFTERWORDS_SESSION_ID": "expired-or-unknown",
        "AFTERWORDS_TTS_CALLER": "native",
    }
    result = subprocess.run(
        ["bash", str(WRAPPER), "--print"],
        capture_output=True, text=True, env=env, cwd=str(wrong), check=True,
    )
    assert result.stdout.strip() == ""


def test_native_explicit_bare_project_never_falls_through_to_gateway_pwd(tmp_path):
    wrong = _write_project(tmp_path, "hermes: wrong-conversation\n")
    bare = tmp_path / "bare"
    bare.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HERMES_HOME": str(tmp_path / ".hermes"),
        "AFTERWORDS_PROJECT_DIR": str(bare),
        "AFTERWORDS_TTS_CALLER": "native",
    }
    result = subprocess.run(
        ["bash", str(WRAPPER), "--print"],
        capture_output=True, text=True, env=env, cwd=str(wrong), check=True,
    )
    assert result.stdout.strip() == ""


def test_home_afterwords_is_never_treated_as_a_project(tmp_path):
    """~/.afterwords is the global fallback; it must not shadow the session."""
    bare = tmp_path / "bare"
    bare.mkdir()
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    (home / ".afterwords").write_text("hermes: galadriel\n", encoding="utf-8")
    project = _write_project(tmp_path, "hermes: worf\n")
    db = _state_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("insert into sessions values ('s1', ?, 0)", (str(project),))
    con.commit()
    con.close()
    env = {"PATH": os.environ["PATH"], "HOME": str(home),
           "AFTERWORDS_STATE_DB": str(db), "AFTERWORDS_SESSION_ID": "s1"}
    result = subprocess.run(["bash", str(WRAPPER), "--print"], capture_output=True,
                            text=True, env=env, cwd=str(home), check=True)
    assert result.stdout.strip() == "worf"


def test_project_without_afterwords_file_is_not_selected(tmp_path):
    """A wrong guess must be harmless: no file, no voice, caller's config wins."""
    empty_project = tmp_path / "empty"
    empty_project.mkdir()
    bare = tmp_path / "bare"
    bare.mkdir()
    db = _state_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("insert into sessions values ('s1', ?, 0)", (str(empty_project),))
    con.commit()
    con.close()
    assert _print_with_db(empty_project, db, bare, "s1") == ""


# ── hand-off to the canonical command script ───────────────────────────────

def _stub_canonical(tmp_path: Path) -> Path:
    stub = tmp_path / "stub-command.sh"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$3" > "$(dirname "$0")/voice-arg.txt"\n',
                    encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def test_resolved_voice_is_passed_to_canonical(tmp_path):
    project = _write_project(tmp_path, "hermes: worf\n")
    stub = _stub_canonical(tmp_path)
    env = {
        "PATH": os.environ["PATH"],
        "AFTERWORDS_PROJECT_DIR": str(project),
        "AFTERWORDS_COMMAND_SCRIPT": str(stub),
    }
    subprocess.run(
        ["bash", str(WRAPPER), "seven-of-nine", str(tmp_path / "in.txt"), str(tmp_path / "out.wav")],
        capture_output=True, text=True, env=env, check=True,
    )
    assert (tmp_path / "voice-arg.txt").read_text().strip() == "worf"


def test_configured_voice_is_the_fallback(tmp_path):
    project = tmp_path / "bare"
    project.mkdir()
    stub = _stub_canonical(tmp_path)
    env = {
        "PATH": os.environ["PATH"],
        "AFTERWORDS_PROJECT_DIR": str(project),
        "AFTERWORDS_COMMAND_SCRIPT": str(stub),
    }
    subprocess.run(
        ["bash", str(WRAPPER), "seven-of-nine", str(tmp_path / "in.txt"), str(tmp_path / "out.wav")],
        capture_output=True, text=True, env=env, check=True,
    )
    assert (tmp_path / "voice-arg.txt").read_text().strip() == "seven-of-nine"


def test_missing_canonical_script_fails_loudly(tmp_path):
    project = tmp_path / "bare"
    project.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "AFTERWORDS_PROJECT_DIR": str(project),
        "AFTERWORDS_COMMAND_SCRIPT": str(tmp_path / "absent.sh"),
    }
    result = subprocess.run(
        ["bash", str(WRAPPER), "seven-of-nine", "in", "out"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    assert "canonical command script not found" in result.stderr


# ── the canonical script keeps its own contract ────────────────────────────

def test_canonical_script_does_not_resolve_afterwords():
    """Project scope lives in the wrapper; the canonical script must stay inert.

    If this fails, the per-profile voice contract in
    tests/test_hermes_profile_voice.py is at risk again.
    """
    text = CANONICAL.read_text(encoding="utf-8")
    # Guard on a file-path reference ("…/.afterwords"), not the word itself:
    # the script legitimately names `tts.providers.afterwords.voice` in comments.
    assert "/.afterwords" not in text
