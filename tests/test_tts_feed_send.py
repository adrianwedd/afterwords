"""Tests for tts-feed-send.py — the TTS archive watcher / sender.

Pure-Python, no GPU. All hermes/ffmpeg subprocess calls are mocked so the
tests never shell out. Covers stem parsing, seen-state round-trip, the
send_to opt-in resolver, and the dry-run no-send guarantee.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


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

    # A preview neither sends nor persists/assembles delivery state.
    with mock.patch.object(tfs.subprocess, "run") as run_mock:
        tfs.process_new_files(set(), dry_run=True)

    run_mock.assert_not_called()


def test_chunked_dry_run_does_not_merge_or_write_cache(tmp_path, monkeypatch, capsys):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    stem = "worf-20261111-135822-65368-27244"
    (claude_dir / f"{stem}.txt").write_text("complete response")
    (claude_dir / f"{stem}-c1.mp3").write_bytes(b"a" * 256)
    (claude_dir / f"{stem}-c2.mp3").write_bytes(b"b" * 256)
    cache = tmp_path / "cache"

    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", cache)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram,discord")

    with mock.patch.object(tfs.subprocess, "run") as run_mock:
        tfs.process_new_files(set(), dry_run=True)

    run_mock.assert_not_called()
    assert not cache.exists()
    assert f"Would send {stem}" in capsys.readouterr().out


def test_transcript_without_audio_is_deferred_not_marked_seen(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    stem = "still-missing-audio"
    (claude_dir / f"{stem}.txt").write_text("reply")
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude")])
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    new_seen = tfs.process_new_files(set())
    assert f"claude:{stem}" not in new_seen


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


def test_partial_delivery_retries_only_failed_target(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-20260504-000000.mp3"
    (hermes_dir / name).write_bytes(b"\x00" * 256)

    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram,discord")
    attempts = []
    telegram_ok = False

    def fake_send(target, _path):
        attempts.append(target)
        return target == "discord" or telegram_ok

    monkeypatch.setattr(tfs, "send_media", fake_send)
    monkeypatch.setattr(tfs, "to_ogg", lambda path: path)

    first = tfs.process_new_files(set(), dry_run=False)
    marker = f"hermes:{name}"
    assert f"{marker}:discord" in first
    assert f"{marker}:telegram" not in first
    assert name not in first
    assert attempts == ["discord", "telegram"]

    attempts.clear()
    telegram_ok = True
    second = tfs.process_new_files(first, dry_run=False)
    assert attempts == ["telegram"]
    assert f"{marker}:telegram" in second
    assert name in second


def test_confirmed_target_is_durable_before_later_target_crashes(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-20260504-000000.mp3"
    (hermes_dir / name).write_bytes(b"\x00" * 256)
    seen_file = tmp_path / "seen.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "telegram,discord")
    monkeypatch.setattr(tfs, "to_ogg", lambda path: path)

    calls = []
    def crash_after_discord(target, _path):
        calls.append(target)
        if target == "discord":
            return True
        raise RuntimeError("simulated process failure before Telegram result")

    monkeypatch.setattr(tfs, "send_media", crash_after_discord)
    with pytest.raises(RuntimeError, match="simulated"):
        tfs.process_new_files(set(), persist=True)

    durable = tfs.load_seen()
    marker = f"hermes:{name}"
    assert f"{marker}:discord" in durable
    assert f"{marker}:telegram:inflight" in durable

    calls.clear()
    monkeypatch.setattr(tfs, "send_media", lambda target, _path: calls.append(target) or True)
    tfs.process_new_files(durable, persist=True)
    assert calls == []  # confirmed Discord and indeterminate Telegram are held


def test_confirmed_failure_clears_inflight_and_remains_retryable(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-20260504-000000.mp3"
    (hermes_dir / name).write_bytes(b"\x00" * 256)
    seen_file = tmp_path / "seen.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    monkeypatch.setattr(tfs, "send_media", lambda *_a: False)

    tfs.process_new_files(set(), persist=True)
    marker = f"hermes:{name}:discord"
    assert marker not in tfs.load_seen()
    assert f"{marker}:inflight" not in tfs.load_seen()

    calls = []
    monkeypatch.setattr(tfs, "send_media", lambda target, _path: calls.append(target) or True)
    tfs.process_new_files(tfs.load_seen(), persist=True)
    assert calls == ["discord"]
    assert marker in tfs.load_seen()
    assert f"{marker}:inflight" not in tfs.load_seen()


def test_timeout_is_held_as_indeterminate_instead_of_retried(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-timeout.mp3"
    (hermes_dir / name).write_bytes(b"\x00" * 256)
    seen_file = tmp_path / "seen.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    monkeypatch.setattr(
        tfs.subprocess, "run",
        mock.Mock(side_effect=subprocess.TimeoutExpired(["hermes", "send"], 30)),
    )

    tfs.process_new_files(set(), persist=True)
    marker = f"hermes:{name}:discord:inflight"
    assert marker in tfs.load_seen()
    tfs.process_new_files(tfs.load_seen(), persist=True)
    assert tfs.subprocess.run.call_count == 1


@pytest.mark.parametrize("resolution,delivered", [("delivered", True), ("retry", False)])
def test_indeterminate_resolution_is_receipted_hash_bound_and_non_sending(
    tmp_path, monkeypatch, resolution, delivered,
):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-ambiguous.mp3"
    media = hermes_dir / name
    media.write_bytes(b"original audio")
    seen_file = tmp_path / "seen.json"
    success = f"hermes:{name}:discord"
    inflight = f"{success}:inflight"
    receipt = tmp_path / f"{resolution}.json"
    monkeypatch.setattr(tfs, "HERMES_ARCHIVE", hermes_dir)
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    monkeypatch.setattr(tfs, "send_media", lambda *_a: None)
    tfs.process_new_files(set(), persist=True)
    assert inflight in tfs.load_seen()

    with mock.patch.object(tfs.subprocess, "run") as run_mock:
        row = tfs.resolve_indeterminate_delivery(success, resolution, receipt)

    run_mock.assert_not_called()
    durable = tfs.load_seen()
    assert (success in durable) is delivered
    assert inflight not in durable
    assert row["status"] == "complete"
    assert row["external_messages_sent"] == 0
    assert row["attempt"]["source_assets"][0]["path"] == str(media)
    assert row["attempt"]["source_assets"][0]["sha256"] == __import__("hashlib").sha256(
        media.read_bytes()
    ).hexdigest()
    assert receipt.stat().st_mode & 0o777 == 0o600


def test_indeterminate_resolution_resumes_after_completion_receipt_failure(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-resume.mp3"
    (hermes_dir / name).write_bytes(b"audio")
    seen_file = tmp_path / "seen.json"
    success = f"hermes:{name}:discord"
    inflight = f"{success}:inflight"
    receipt = tmp_path / "resolution.json"
    monkeypatch.setattr(tfs, "HERMES_ARCHIVE", hermes_dir)
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    monkeypatch.setattr(tfs, "send_media", lambda *_a: None)
    tfs.process_new_files(set(), persist=True)
    real_replace = tfs._replace_receipt
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated completion receipt failure")
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(tfs, "_replace_receipt", fail_once)
    with pytest.raises(OSError, match="simulated"):
        tfs.resolve_indeterminate_delivery(success, "delivered", receipt)
    assert success in tfs.load_seen() and inflight not in tfs.load_seen()
    assert json.loads(receipt.read_text())["status"] == "prepared"

    row = tfs.resolve_indeterminate_delivery(success, "delivered", receipt)
    assert row["status"] == "complete"
    assert json.loads(receipt.read_text())["status"] == "complete"


def test_indeterminate_receipt_uses_attempt_time_bytes_after_source_changes(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-mutated.mp3"
    source = hermes_dir / name
    source.write_bytes(b"OLD-AUDIO")
    seen_file = tmp_path / "seen.json"
    success = f"hermes:{name}:discord"
    receipt = tmp_path / "resolution.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    attempted = []
    monkeypatch.setattr(
        tfs, "send_media", lambda _target, path: attempted.append(path.read_bytes()) or None,
    )

    tfs.process_new_files(set(), persist=True)
    source.write_bytes(b"NEW-AUDIO")  # same length; archive no longer matches attempt
    row = tfs.resolve_indeterminate_delivery(success, "delivered", receipt)

    old_hash = __import__("hashlib").sha256(b"OLD-AUDIO").hexdigest()
    new_hash = __import__("hashlib").sha256(b"NEW-AUDIO").hexdigest()
    assert attempted == [b"OLD-AUDIO"]
    assert row["attempt"]["delivery_media"]["sha256"] == old_hash
    assert row["attempt"]["source_assets"][0]["sha256"] == old_hash
    assert row["attempt"]["source_assets"][0]["sha256"] != new_hash


def test_deliberate_retry_creates_a_new_attempt_bound_to_current_bytes(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    name = "picard-retry.mp3"
    source = hermes_dir / name
    source.write_bytes(b"OLD-AUDIO")
    seen_file = tmp_path / "seen.json"
    success = f"hermes:{name}:discord"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    monkeypatch.setattr(tfs, "send_media", lambda *_a: None)

    tfs.process_new_files(set(), persist=True)
    source.write_bytes(b"NEW-AUDIO")
    tfs.resolve_indeterminate_delivery(success, "retry", tmp_path / "retry.json")

    attempted = []
    monkeypatch.setattr(
        tfs, "send_media", lambda _target, path: attempted.append(path.read_bytes()) or None,
    )
    tfs.process_new_files(tfs.load_seen(), persist=True)
    new_hash = __import__("hashlib").sha256(b"NEW-AUDIO").hexdigest()
    assert attempted == [b"NEW-AUDIO"]
    assert tfs.load_attempts()[success]["source_assets"][0]["sha256"] == new_hash
    assert tfs.load_attempts()[success]["delivery_media"]["sha256"] == new_hash


def test_indeterminate_resolution_refuses_unjournalled_claude_transcript_only(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    (claude_dir / "empty.txt").write_text("no audio")
    seen_file = tmp_path / "seen.json"
    success = "claude:empty:discord"
    seen_file.write_text(json.dumps([f"{success}:inflight"]))
    monkeypatch.setattr(tfs, "CLAUDE_ARCHIVE", claude_dir)
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    with pytest.raises(ValueError, match="frozen attempt journal"):
        tfs.resolve_indeterminate_delivery(success, "delivered", tmp_path / "receipt.json")


def test_indeterminate_resolution_refuses_journalled_claude_transcript_only(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    transcript = claude_dir / "empty.txt"
    transcript.write_text("no audio")
    delivery = tmp_path / "cache" / "empty.mp3"
    delivery.parent.mkdir()
    delivery.write_bytes(b"claimed delivery")
    seen_file = tmp_path / "seen.json"
    success = "claude:empty:discord"
    inflight = f"{success}:inflight"
    seen_file.write_text(json.dumps([inflight]))
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "created_at": "2026-11-23T00:00:00+00:00",
        "success_marker": success,
        "inflight_marker": inflight,
        "target": "discord",
        "delivery_media": tfs._asset_record(delivery),
        "source_assets": [tfs._asset_record(transcript)],
    }
    tfs._attempts_file().write_text(json.dumps({success: attempt}))
    with pytest.raises(RuntimeError, match="inconsistent frozen attempt journal"):
        tfs.resolve_indeterminate_delivery(success, "delivered", tmp_path / "receipt.json")


def test_indeterminate_resolution_refuses_invalid_asset_hash_schema(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    media = hermes_dir / "bad.mp3"
    media.write_bytes(b"audio")
    seen_file = tmp_path / "seen.json"
    success = "hermes:bad.mp3:discord"
    inflight = f"{success}:inflight"
    seen_file.write_text(json.dumps([inflight]))
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    asset = tfs._asset_record(media)
    asset["sha256"] = "not-a-sha256"
    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "created_at": "2026-11-23T00:00:00+00:00",
        "success_marker": success,
        "inflight_marker": inflight,
        "target": "discord",
        "delivery_media": asset,
        "source_assets": [asset],
    }
    tfs._attempts_file().write_text(json.dumps({success: attempt}))
    with pytest.raises(RuntimeError, match="malformed frozen attempt journal"):
        tfs.resolve_indeterminate_delivery(success, "delivered", tmp_path / "receipt.json")


@pytest.mark.parametrize("source", ["hermes", "claude"])
def test_indeterminate_resolution_refuses_sources_outside_authoritative_archive(
    tmp_path, monkeypatch, source,
):
    authoritative = tmp_path / f"authoritative-{source}"
    wrong = tmp_path / "wrong"
    cache = tmp_path / "cache"
    authoritative.mkdir()
    wrong.mkdir()
    cache.mkdir()
    if source == "hermes":
        success = "hermes:item.mp3:discord"
        source_paths = [wrong / "item.mp3"]
        delivery = cache / "item.mp3"
    else:
        success = "claude:stem:discord"
        source_paths = [wrong / "stem.txt", wrong / "stem-c1.mp3"]
        delivery = cache / "stem-merged.mp3"
    for path in source_paths:
        path.write_bytes(b"source")
    delivery.write_bytes(b"delivery")
    inflight = f"{success}:inflight"
    seen_file = tmp_path / "seen.json"
    seen_file.write_text(json.dumps([inflight]))
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setattr(tfs, "AUDIO_CACHE", cache)
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(authoritative, source)])
    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "created_at": "2026-11-23T00:00:00+00:00",
        "success_marker": success,
        "inflight_marker": inflight,
        "target": "discord",
        "delivery_media": tfs._asset_record(delivery),
        "source_assets": [tfs._asset_record(path) for path in source_paths],
    }
    tfs._attempts_file().write_text(json.dumps({success: attempt}))
    receipt = tmp_path / "receipt.json"
    before = tfs.load_seen()
    with pytest.raises(RuntimeError, match="inconsistent frozen attempt journal"):
        tfs.resolve_indeterminate_delivery(success, "delivered", receipt)
    assert not receipt.exists()
    assert tfs.load_seen() == before


def test_indeterminate_resolution_refuses_archive_symlink_escape(tmp_path, monkeypatch):
    archive = tmp_path / "hermes"
    wrong = tmp_path / "wrong"
    cache = tmp_path / "cache"
    archive.mkdir()
    wrong.mkdir()
    cache.mkdir()
    outside = wrong / "item.mp3"
    outside.write_bytes(b"outside")
    linked = archive / "linked.mp3"
    linked.symlink_to(outside)
    delivery = cache / "linked.mp3"
    delivery.write_bytes(b"delivery")
    success = "hermes:linked.mp3:discord"
    inflight = f"{success}:inflight"
    seen_file = tmp_path / "seen.json"
    seen_file.write_text(json.dumps([inflight]))
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setattr(tfs, "AUDIO_CACHE", cache)
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(archive, "hermes")])
    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "created_at": "2026-11-23T00:00:00+00:00",
        "success_marker": success,
        "inflight_marker": inflight,
        "target": "discord",
        "delivery_media": tfs._asset_record(delivery),
        "source_assets": [tfs._asset_record(linked)],
    }
    tfs._attempts_file().write_text(json.dumps({success: attempt}))
    receipt = tmp_path / "receipt.json"
    before = tfs.load_seen()
    with pytest.raises(RuntimeError, match="inconsistent frozen attempt journal"):
        tfs.resolve_indeterminate_delivery(success, "delivered", receipt)
    assert not receipt.exists()
    assert tfs.load_seen() == before


def test_malformed_attempt_journal_blocks_delivery_instead_of_resending(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir()
    (hermes_dir / "picard.mp3").write_bytes(b"audio")
    seen_file = tmp_path / "seen.json"
    seen_file.write_text("[]")
    seen_file.with_name("tts-feed-attempts.json").write_text("{not-json")
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "AUDIO_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    monkeypatch.setenv("AFTERWORDS_SEND_TO", "discord")
    with mock.patch.object(tfs, "send_media") as send_mock:
        with pytest.raises(RuntimeError, match="attempt journal"):
            tfs.process_new_files(set(), persist=True)
    send_mock.assert_not_called()


def test_discard_backlog_is_auditable_and_never_sends(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    hermes_dir = tmp_path / "hermes"
    claude_dir.mkdir()
    hermes_dir.mkdir()
    stem = "worf-20261111-135822-65368-27244"
    (claude_dir / f"{stem}.txt").write_text("old response")
    (claude_dir / f"{stem}-c1.mp3").write_bytes(b"a" * 256)
    hermes_name = "picard-old.mp3"
    (hermes_dir / hermes_name).write_bytes(b"b" * 256)
    seen_file = tmp_path / "seen.json"
    seen_file.write_text("[]")
    receipt = tmp_path / "state" / "discard.json"

    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude"), (hermes_dir, "hermes")])
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    with mock.patch.object(tfs.subprocess, "run") as run_mock:
        row = tfs.discard_current_backlog(set(), receipt, quiescence_seconds=0)

    run_mock.assert_not_called()
    assert row["action"] == "discard_current_backlog_as_stale_without_delivery"
    assert row["status"] == "complete"
    assert row["external_messages_sent"] == 0
    assert row["discarded_count"] == 2
    assert all(item["assets"] for item in row["discarded"])
    assert all(
        len(asset["sha256"]) == 64
        for item in row["discarded"] for asset in item["assets"]
    )
    assert receipt.stat().st_mode & 0o777 == 0o600
    saved = tfs.load_seen()
    assert f"claude:{stem}" in saved
    assert hermes_name in saved
    assert receipt.read_text().endswith("\n")
    with pytest.raises(FileExistsError):
        tfs.discard_current_backlog(saved, receipt, quiescence_seconds=0)


def test_discard_finalization_failure_preserves_prepared_receipt(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    stem = "worf-old"
    (claude_dir / f"{stem}.txt").write_text("old response")
    (claude_dir / f"{stem}-c1.mp3").write_bytes(b"a" * 256)
    seen_file = tmp_path / "seen.json"
    seen_file.write_text("[]")
    receipt = tmp_path / "state" / "discard.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude")])
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    real_dump = tfs.json.dump
    calls = 0

    def fail_complete_dump(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:  # prepared receipt, seen-state, complete receipt
            raise OSError("simulated completion write failure")
        return real_dump(*args, **kwargs)

    monkeypatch.setattr(tfs.json, "dump", fail_complete_dump)
    with pytest.raises(OSError, match="simulated"):
        tfs.discard_current_backlog(set(), receipt, quiescence_seconds=0)

    prepared = json.loads(receipt.read_text())
    assert prepared["status"] == "prepared"
    assert len(prepared["discarded"]) == 1
    assert prepared["discarded"][0]["marker"] == f"claude:{stem}"
    assert {Path(asset["path"]).name for asset in prepared["discarded"][0]["assets"]} == {
        f"{stem}.txt", f"{stem}-c1.mp3",
    }
    assert f"claude:{stem}" in tfs.load_seen()
    recovered = tfs.recover_backlog_disposition(receipt)
    assert recovered["status"] == "recovered"
    assert f"claude:{stem}" not in tfs.load_seen()


def test_discard_backlog_cli_writes_complete_receipt(tmp_path):
    home = tmp_path / "home"
    archive = home / ".claude" / "tts-archive"
    archive.mkdir(parents=True)
    stem = "samantha-old"
    (archive / f"{stem}.txt").write_text("old response")
    (archive / f"{stem}-c1.mp3").write_bytes(b"a" * 256)
    receipt = home / ".local" / "state" / "afterwords" / "discard.json"
    env = {**os.environ, "HOME": str(home), "AFTERWORDS_SEND_TO": "discord,telegram"}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--discard-current-backlog", "--receipt", str(receipt),
         "--quiescence-seconds", "0"],
        env=env, capture_output=True, text=True, check=True,
    )

    row = json.loads(receipt.read_text())
    assert row["status"] == "complete"
    assert row["discarded_count"] == 1
    assert row["external_messages_sent"] == 0
    assert "Discarded 1 stale backlog items without delivery" in result.stdout
    seen = set(json.loads((home / ".hermes" / "tts-feed-seen.json").read_text()))
    assert f"claude:{stem}" in seen

    recovery = subprocess.run(
        [sys.executable, str(SCRIPT), "--recover-backlog-disposition", "--receipt", str(receipt)],
        env=env, capture_output=True, text=True, check=True,
    )
    assert "Recovered 1 backlog markers" in recovery.stdout
    assert f"claude:{stem}" not in set(json.loads(
        (home / ".hermes" / "tts-feed-seen.json").read_text()
    ))
    recovered = json.loads(receipt.read_text())
    assert recovered["status"] == "recovered"
    assert recovered["recovered_markers"] == [f"claude:{stem}"]


def test_discard_defers_nonquiescent_in_progress_response(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    stem = "still-producing"
    (claude_dir / f"{stem}.txt").write_text("full intended reply")
    (claude_dir / f"{stem}-c1.mp3").write_bytes(b"partial")
    seen_file = tmp_path / "seen.json"
    seen_file.write_text("[]")
    receipt = tmp_path / "discard.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude")])
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)

    row = tfs.discard_current_backlog(set(), receipt, quiescence_seconds=300)
    assert row["discarded_count"] == 0
    assert row["deferred"] == [
        {"source": "claude", "item": stem, "reason": "not_quiescent"}
    ]
    assert f"claude:{stem}" not in tfs.load_seen()


def test_discard_aborts_if_snapshot_gains_a_chunk_before_seen_mutation(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    stem = "changes-during-snapshot"
    (claude_dir / f"{stem}.txt").write_text("reply")
    (claude_dir / f"{stem}-c1.mp3").write_bytes(b"one")
    seen_file = tmp_path / "seen.json"
    seen_file.write_text("[]")
    receipt = tmp_path / "discard.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude")])
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    real_fsync_dir = tfs._fsync_directory
    calls = 0

    def inject_new_chunk(path):
        nonlocal calls
        calls += 1
        real_fsync_dir(path)
        if calls == 1:  # prepared receipt is durable; producer advances
            (claude_dir / f"{stem}-c2.mp3").write_bytes(b"two")

    monkeypatch.setattr(tfs, "_fsync_directory", inject_new_chunk)
    with pytest.raises(RuntimeError, match="changed after snapshot"):
        tfs.discard_current_backlog(set(), receipt, quiescence_seconds=0)
    assert f"claude:{stem}" not in tfs.load_seen()
    assert json.loads(receipt.read_text())["status"] == "prepared"


def test_discard_reverses_if_snapshot_gains_a_chunk_during_seen_swap(tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    stem = "racy"
    (claude_dir / f"{stem}.txt").write_text("reply")
    (claude_dir / f"{stem}-c1.mp3").write_bytes(b"one")
    seen_file = tmp_path / "seen.json"
    seen_file.write_text("[]")
    receipt = tmp_path / "discard.json"
    monkeypatch.setattr(tfs, "WATCH_DIRS", [(claude_dir, "claude")])
    monkeypatch.setattr(tfs, "SEEN_FILE", seen_file)
    real_save_seen = tfs.save_seen
    calls = 0

    def inject_during_swap(seen, **kwargs):
        nonlocal calls
        calls += 1
        result = real_save_seen(seen, **kwargs)
        if calls == 1:
            (claude_dir / f"{stem}-c2.mp3").write_bytes(b"two")
        return result

    monkeypatch.setattr(tfs, "save_seen", inject_during_swap)
    with pytest.raises(RuntimeError, match="markers reversed"):
        tfs.discard_current_backlog(set(), receipt, quiescence_seconds=0)
    assert f"claude:{stem}" not in tfs.load_seen()
    row = json.loads(receipt.read_text())
    assert row["status"] == "aborted_asset_race"
    assert row["recovered_markers"] == [f"claude:{stem}"]
