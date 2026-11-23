"""Source acquisition uses tiny fake downloads, never network or model work."""
import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest


SPEC = importlib.util.spec_from_file_location(
    "acquire_voice_source", Path(__file__).resolve().parents[1] / "scripts/acquire_voice_source.py")
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fake(query, work, seconds):
        calls.append((query, seconds))
        path = work / "source.wav"
        path.write_bytes(b"RIFF-fake-audio-" + str(seconds).encode())
        return path, "https://example.invalid/verified-source"

    monkeypatch.setattr(SOURCE, "_download", fake)
    return calls


def test_repeated_query_verifies_source_without_another_download(tmp_path, downloads):
    first = SOURCE.acquire_wav("same query", tmp_path / "raw.wav")
    again = SOURCE.acquire_wav("same query", tmp_path / "curate.wav")
    SOURCE.acquire_wav("same query", tmp_path / "curate.wav")
    assert first == again
    assert downloads == [("same query", None)]
    assert not (tmp_path / "curate.wav").exists()
    records = list(tmp_path.glob("*.acquisition.json"))
    assert len(records) == 1
    data = json.loads(records[0].read_text())
    assert [r["requested_name"] for r in data["requests"]] == ["raw.wav", "curate.wav"]
    assert all(r["source_url"] == "https://example.invalid/verified-source" for r in data["requests"])


def test_different_queries_reuse_identical_bytes_with_both_lineages(tmp_path, downloads):
    first = SOURCE.acquire_wav("first query", tmp_path / "first.wav")
    second = SOURCE.acquire_wav("different query", tmp_path / "different.wav")
    assert second == first
    assert len(downloads) == 2
    assert len(list(tmp_path.glob("*.wav"))) == 1
    lineage = json.loads(first.with_suffix(".acquisition.json").read_text())
    assert {r["query"] for r in lineage["requests"]} == {"first query", "different query"}


def test_existing_legacy_source_needs_actual_byte_match_not_filename(tmp_path, downloads):
    existing = tmp_path / "legacy.wav"
    existing.write_bytes(b"RIFF-fake-audio-None")
    before = existing.stat()
    source = SOURCE.acquire_wav("new query", tmp_path / "new_raw.wav")
    assert source == existing
    assert existing.stat().st_ino == before.st_ino
    assert len(downloads) == 1
    assert not (tmp_path / "new_raw.wav").exists()


def test_changed_pinned_source_fails_without_reacquisition(tmp_path, downloads):
    source = SOURCE.acquire_wav("first query", tmp_path / "first.wav")
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="recorded source changed"):
        SOURCE.acquire_wav("first query", tmp_path / "alias.wav")
    assert len(downloads) == 1
    assert source.read_bytes() == b"changed"


def test_failure_releases_only_owned_download_scratch(tmp_path, monkeypatch):
    original = tmp_path / "original.wav"
    original.write_bytes(b"keep")

    def fail(query, work, seconds):
        (work / "partial.wav").write_bytes(b"partial")
        raise RuntimeError("download failed")

    monkeypatch.setattr(SOURCE, "_download", fail)
    with pytest.raises(RuntimeError, match="download failed"):
        SOURCE.acquire_wav("query", tmp_path / "new.wav")
    assert original.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".acquire-*"))
    assert not list(tmp_path.glob("*.acquisition.json"))


def test_existing_different_recording_is_never_overwritten(tmp_path, downloads):
    source = tmp_path / "first.wav"
    source.write_bytes(b"unique old recording")
    with pytest.raises(FileExistsError):
        SOURCE.acquire_wav("new query", source)
    assert source.read_bytes() == b"unique old recording"
    assert not list(tmp_path.glob(".acquire-*"))


def test_selection_is_part_of_acquisition_identity(tmp_path, downloads):
    full = SOURCE.acquire_wav("query", tmp_path / "full.wav")
    excerpt = SOURCE.acquire_wav("query", tmp_path / "excerpt.wav", seconds=120)
    assert full != excerpt
    assert downloads == [("query", None), ("query", 120)]


def test_concurrent_same_query_has_one_download(tmp_path, downloads):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda name: SOURCE.acquire_wav("query", tmp_path / name), ["one.wav", "two.wav"]))
    assert results[0] == results[1]
    assert downloads == [("query", None)]


def test_lineage_cannot_escape_acquisition_directory(tmp_path, downloads):
    (tmp_path / "bad.acquisition.json").write_text(json.dumps({
        "schema": SOURCE.SCHEMA, "file": "../outside.wav", "sha256": "0" * 64,
        "requests": [{"query": "query", "seconds": None}],
    }))
    with pytest.raises(ValueError, match="remain in its acquisition directory"):
        SOURCE.acquire_wav("query", tmp_path / "new.wav")
    assert downloads == []


def test_default_downloader_records_resolved_url_and_bounds_selection(tmp_path, monkeypatch):
    commands = []

    def command(argv, **kwargs):
        commands.append(argv)
        assert kwargs == {"check": True}
        if argv[0] == "yt-dlp":
            (tmp_path / "source.wav").write_bytes(b"full source")
            (tmp_path / "source.info.json").write_text(json.dumps({
                "webpage_url": "https://example.invalid/resolved", "id": "recording-id",
            }))
        else:
            assert argv == ["ffmpeg", "-y", "-i", str(tmp_path / "source.wav"),
                            "-t", "120", str(tmp_path / "selected.wav")]
            (tmp_path / "selected.wav").write_bytes(b"excerpt")

    monkeypatch.setattr(SOURCE.subprocess, "run", command)
    selected, url = SOURCE._download("query", tmp_path, 120)
    assert selected == tmp_path / "selected.wav"
    assert url == "https://example.invalid/resolved"
    assert commands[0][-1] == "query" and "--write-info-json" in commands[0]


def test_lineage_write_failure_leaves_unique_source_recoverable_and_scratch_clean(
    tmp_path, downloads, monkeypatch
):
    def fail(*args):
        raise OSError("metadata write failed")

    monkeypatch.setattr(SOURCE.os, "replace", fail)
    with pytest.raises(OSError, match="metadata write failed"):
        SOURCE.acquire_wav("query", tmp_path / "recording.wav")
    assert (tmp_path / "recording.wav").read_bytes() == b"RIFF-fake-audio-None"
    assert not list(tmp_path.glob(".acquire-*"))
    assert not list(tmp_path.glob(".acquisition-*"))
