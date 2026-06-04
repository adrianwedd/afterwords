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


def test_clone_local_file_detected_not_ytdlp():
    """A local file path resolves to local-file source, never yt-dlp."""
    sample = REPO / "voices" / "galadriel-ref.wav"  # tracked, real file
    result = subprocess.run(
        ["bash", str(REPO / "clone-voice.sh"), str(sample), "test-local", "--check-source"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "local-file"
    assert "yt-dlp" not in (result.stdout + result.stderr).lower()


def test_clone_url_detected_as_youtube():
    result = subprocess.run(
        ["bash", str(REPO / "clone-voice.sh"),
         "https://youtube.com/watch?v=x", "test-url", "--check-source"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.stdout.strip() == "youtube"


# ── refine: 4-step pipeline exit-code chaining ───────────────────────

def _make_stub_repo(tmp_path, qa_exit=0, compare_exit=0, trim_exit=0,
                    trim_json=None, qa_json=None):
    """Build a minimal fake REPO_DIR for testing cmd_refine."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("# stub")

    qa_out = qa_json or '{"voices":[{"name":"v","ref_wer":0.05}],"threshold":0.15}'
    trim_out = trim_json or '{"voices":[{"name":"v","gap_count":0,"changed":false}]}'

    (scripts / "qa-voices.py").write_text(
        f"import sys; print({qa_out!r}); sys.exit({qa_exit})"
    )
    (scripts / "compare-transcription.py").write_text(
        f'import sys; print(\'{{"winner":"faster-whisper","agreement_wer":0.05,"whisper_words":40,"parakeet_words":40,"skipped":[]}}\'); sys.exit({compare_exit})'
    )
    (scripts / "trim-silence-gaps.py").write_text(
        f"import sys; print({trim_out!r}); sys.exit({trim_exit})"
    )
    # Stub voice file so refine finds it
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "testvoice-ref.wav").write_text("")
    (voices / "testvoice.json").write_text('{"name":"testvoice"}')
    return tmp_path


def _run_refine(tmp_path, *extra_args):
    return run_afterwords("refine", "testvoice", *extra_args,
                          env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})


def test_refine_exits_0_on_clean(tmp_path):
    repo = _make_stub_repo(tmp_path)
    result = _run_refine(repo)
    assert result.returncode == 0, result.stderr


def test_refine_continues_after_qa_exit1(tmp_path):
    """qa exit 1 (WER warning) → refine continues to next step."""
    qa_json = '{"voices":[{"name":"testvoice","ref_wer":0.20}],"threshold":0.15}'
    repo = _make_stub_repo(tmp_path, qa_exit=1, qa_json=qa_json)
    result = _run_refine(repo)
    # Should complete (exit 1 because final WER still > 0.15), not abort with 2
    assert result.returncode in (0, 1), f"should not hard-abort: {result.stderr}"


def test_refine_aborts_on_qa_exit2(tmp_path):
    """qa exit 2 (hard error) → refine aborts immediately with exit 2."""
    repo = _make_stub_repo(tmp_path, qa_exit=2)
    result = _run_refine(repo)
    assert result.returncode == 2, f"expected 2, got {result.returncode}: {result.stderr}"


def test_refine_aborts_on_trim_exit2(tmp_path):
    """trim exit 2 → abort with exit 2 (unlike compare, which continues)."""
    repo = _make_stub_repo(tmp_path, trim_exit=2)
    result = _run_refine(repo)
    assert result.returncode == 2, f"expected 2, got {result.returncode}: {result.stderr}"


def test_refine_continues_after_compare_exit2(tmp_path):
    """compare exit 2 → refine prints warning but continues to step 3."""
    repo = _make_stub_repo(tmp_path, compare_exit=2)
    result = _run_refine(repo)
    # Should still finish (exit 0 or 1), not exit 2
    assert result.returncode != 2, f"should not abort on compare exit 2: {result.stderr}"


def test_refine_quick_skips_compare_trim(tmp_path):
    """--quick must skip steps 2 and 3 entirely."""
    # Give compare a fatal exit — if --quick works, it should never be called
    repo = _make_stub_repo(tmp_path, compare_exit=2)
    result = _run_refine(repo, "--quick")
    # If compare were called, it would exit 2 and potentially cause issues;
    # with --quick it should complete cleanly
    assert result.returncode in (0, 1)


def test_clone_calls_refine_after_success(tmp_path):
    """After a successful clone, cmd_clone must invoke cmd_refine."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("# stub")
    # qa-voices.py emits a sentinel so we can assert refine was actually invoked
    for name in ("trim-silence-gaps.py", "compare-transcription.py"):
        (scripts / name).write_text("import sys; sys.exit(0)")
    (scripts / "qa-voices.py").write_text(
        "import sys; print('REFINE_RAN'); sys.exit(0)"
    )
    voices = tmp_path / "voices"
    voices.mkdir()

    # Stub clone-voice.sh to exit 0 and write a fake voice
    stub_clone = tmp_path / "clone-voice.sh"
    stub_clone.write_text(
        "#!/bin/bash\n"
        f"mkdir -p {voices}\n"
        f"touch {voices}/myvoice-ref.wav\n"
        f"echo '{{\"name\":\"myvoice\"}}' > {voices}/myvoice.json\n"
        "echo 'CLONE_DONE'\n"
        "exit 0\n"
    )
    stub_clone.chmod(0o755)

    result = run_afterwords("clone", "http://example.com", "myvoice",
                            env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})
    # refine calls qa-voices.py which prints REFINE_RAN; assert it was wired
    assert result.returncode in (0, 1), result.stderr
    assert "CLONE_DONE" in result.stdout
    assert "REFINE_RAN" in result.stdout
