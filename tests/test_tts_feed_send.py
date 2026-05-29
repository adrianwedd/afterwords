"""Tests for tts-feed-send.py — the TTS archive watcher / sender.

Pure-Python, no GPU. All hermes/ffmpeg subprocess calls are mocked so the
tests never shell out. Covers stem parsing, seen-state round-trip, the
send_to opt-in resolver, and the dry-run no-send guarantee.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tts-feed-send.py"
SPEC = importlib.util.spec_from_file_location("tts_feed_send", SCRIPT)
assert SPEC is not None
tfs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["tts_feed_send"] = tfs
SPEC.loader.exec_module(tfs)


# ── parse_claude_stem ──────────────────────────────────────────────

def test_parse_claude_stem_strips_chunk_suffix():
    assert (
        tfs.parse_claude_stem("the-doctor-20260527-175322-12999-26349-c5.mp3")
        == "the-doctor-20260527-175322-12999-26349"
    )


def test_parse_claude_stem_no_chunk_suffix():
    assert (
        tfs.parse_claude_stem("ace-20260504-232124-70606-15100.mp3")
        == "ace-20260504-232124-70606-15100"
    )


# ── load_seen / save_seen round-trip ───────────────────────────────

def test_seen_roundtrips_through_json(tmp_path, monkeypatch):
    monkeypatch.setattr(tfs, "SEEN_FILE", tmp_path / "seen.json")
    original = {"alpha.mp3", "claude:beta-123", "gamma.mp3"}
    tfs.save_seen(original)
    assert tfs.load_seen() == original


def test_load_seen_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(tfs, "SEEN_FILE", tmp_path / "absent.json")
    assert tfs.load_seen() == set()


# ── send_to resolver ───────────────────────────────────────────────

def test_send_to_default_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("AFTERWORDS_SEND_TO", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tfs, "HOME_AFTERWORDS", tmp_path / "nonexistent" / ".afterwords")
    assert tfs.resolve_send_to() == set()


def test_send_to_from_env(monkeypatch):
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram,discord")
    assert tfs.resolve_send_to() == {"telegram", "discord"}


def test_send_to_env_single(monkeypatch):
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram")
    assert tfs.resolve_send_to() == {"telegram"}


def test_send_to_rejects_unknown_platforms(monkeypatch):
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram,sms,carrier-pigeon")
    assert tfs.resolve_send_to() == {"telegram"}


def test_send_to_from_pwd_afterwords(tmp_path, monkeypatch):
    monkeypatch.delenv("AFTERWORDS_SEND_TO", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".afterwords").write_text("default: picard\nsend_to: discord\n")
    monkeypatch.setattr(tfs, "HOME_AFTERWORDS", tmp_path / "home" / ".afterwords")
    assert tfs.resolve_send_to() == {"discord"}


def test_send_to_from_home_afterwords(tmp_path, monkeypatch):
    monkeypatch.delenv("AFTERWORDS_SEND_TO", raising=False)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    home_aw = tmp_path / "home" / ".afterwords"
    home_aw.parent.mkdir()
    home_aw.write_text("send_to: telegram\n")
    monkeypatch.setattr(tfs, "HOME_AFTERWORDS", home_aw)
    assert tfs.resolve_send_to() == {"telegram"}


def test_send_to_env_takes_priority_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".afterwords").write_text("send_to: discord\n")
    monkeypatch.setattr(tfs, "HOME_AFTERWORDS", tmp_path / "home" / ".afterwords")
    assert tfs.resolve_send_to() == {"telegram"}


def test_send_to_pwd_takes_priority_over_home(tmp_path, monkeypatch):
    monkeypatch.delenv("AFTERWORDS_SEND_TO", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".afterwords").write_text("send_to: discord\n")
    home_aw = tmp_path / "home" / ".afterwords"
    home_aw.parent.mkdir()
    home_aw.write_text("send_to: telegram\n")
    monkeypatch.setattr(tfs, "HOME_AFTERWORDS", home_aw)
    assert tfs.resolve_send_to() == {"discord"}


# ── dry-run performs no sends ──────────────────────────────────────

def test_dry_run_makes_no_subprocess_calls(tmp_path, monkeypatch):
    # Build a claude archive with a complete (single, non-chunk) response.
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    (claude_dir / "ace-20260504-232124-70606-15100.txt").write_text("hello")
    (claude_dir / "ace-20260504-232124-70606-15100.mp3").write_bytes(b"\x00" * 256)

    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    (hermes_dir / "picard-20260504-000000.mp3").write_bytes(b"\x00" * 256)

    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes"), (claude_dir, "claude")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram,discord")

    # dry-run intentionally mutates the in-memory seen set (markers added) but
    # never persists it — save_seen() is skipped by main() when --dry-run.
    with mock.patch.object(tfs.subprocess, "run") as run_mock:
        tfs.process_new_files(set(), dry_run=True)

    run_mock.assert_not_called()


# ── empty send_to: marks seen, sends nothing ───────────────────────

def test_empty_send_to_marks_seen_but_sends_nothing(tmp_path, monkeypatch, capsys):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    (hermes_dir / "picard-20260504-000000.mp3").write_bytes(b"\x00" * 256)

    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.delenv("AFTERWORDS_SEND_TO", raising=False)
    monkeypatch.setattr(tfs, "HOME_AFTERWORDS", tmp_path / "nope" / ".afterwords")
    monkeypatch.chdir(tmp_path / "hermes")  # no .afterwords here

    with mock.patch.object(tfs.subprocess, "run") as run_mock:
        new_seen = tfs.process_new_files(set(), dry_run=False)

    run_mock.assert_not_called()
    assert "picard-20260504-000000.mp3" in new_seen
    out = capsys.readouterr().out
    assert "no send_to configured" in out


# ── single-platform send_to: only that platform sends ──────────────

def test_telegram_only_send_to_skips_discord(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    (hermes_dir / "picard-20260504-000000.mp3").write_bytes(b"\x00" * 256)

    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram")

    targets = []

    def fake_run(cmd, *_a, **_k):
        # hermes send -t <target> MEDIA:<file>
        if cmd[:3] == ["hermes", "send", "-t"]:
            targets.append(cmd[3])
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch.object(tfs.subprocess, "run", side_effect=fake_run):
        tfs.process_new_files(set(), dry_run=False)

    assert "telegram" in targets
    assert "discord" not in targets
