"""Acceptance and integration tests for Sprint 6 CLI expansion."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AFTERWORDS = REPO / "afterwords.sh"


def run_afterwords(*args, env_override=None):
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        ["bash", str(AFTERWORDS), *args],
        capture_output=True, text=True, env=env,
    )


def test_audit_archive_routes_to_archive_script(tmp_path):
    """--archive flag must use audit-archive.py, not audit-voice-transcripts.py."""
    # Create stub scripts in a temp REPO_DIR
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate").write_text("# stub activate")

    stub = scripts_dir / "audit-archive.py"
    stub.write_text("import sys; print('ARCHIVE_SCRIPT_CALLED'); sys.exit(0)")
    wrong = scripts_dir / "audit-voice-transcripts.py"
    wrong.write_text("import sys; print('WRONG_SCRIPT'); sys.exit(0)")

    result = run_afterwords("audit", "--archive",
                            env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})
    assert "ARCHIVE_SCRIPT_CALLED" in result.stdout
    assert "WRONG_SCRIPT" not in result.stdout


def test_audit_plain_unchanged(tmp_path):
    """Plain audit (no --archive) must still call audit-voice-transcripts.py."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate").write_text("# stub activate")

    stub = scripts_dir / "audit-voice-transcripts.py"
    stub.write_text("import sys; print('TRANSCRIPT_SCRIPT_CALLED'); sys.exit(0)")
    wrong = scripts_dir / "audit-archive.py"
    wrong.write_text("import sys; print('WRONG_SCRIPT'); sys.exit(0)")

    result = run_afterwords("audit",
                            env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})
    assert "TRANSCRIPT_SCRIPT_CALLED" in result.stdout
    assert "WRONG_SCRIPT" not in result.stdout
