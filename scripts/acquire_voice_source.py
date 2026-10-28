#!/usr/bin/env python3
"""Acquire one WAV, reusing verified source bytes and recording requested names.

Callers must consume the returned path: a requested name is provenance, not an
instruction to create another full WAV. Existing recordings are never replaced
or removed. This helper does not run transcription, cloning or synthesis.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


SCHEMA = "afterwords-source-acquisition/1"


def _sha256(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise ValueError(f"source changed during verification: {path}")
    return digest.hexdigest()


@contextmanager
def _lock(directory: Path):
    with (directory / ".source-acquisition.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _download(query: str, work: Path, seconds: int | None):
    subprocess.run([
        "yt-dlp", "--no-playlist", "-x", "--audio-format", "wav",
        "--write-info-json", "-o", str(work / "source.%(ext)s"), query,
    ], check=True)
    source = work / "source.wav"
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("download produced no non-empty WAV")
    info_path = work / "source.info.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    if seconds is not None:
        selected = work / "selected.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(source), "-t", str(seconds), str(selected),
        ], check=True)
        source = selected
    return source, info.get("webpage_url")


def _lineage(path: Path):
    data = json.loads(path.read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unrecognised acquisition lineage: {path}")
    name = data["file"]
    if Path(name).name != name:
        raise ValueError(f"source path must remain in its acquisition directory: {path}")
    source = path.parent / name
    if source.with_suffix(".acquisition.json") != path:
        raise ValueError(f"lineage filename does not match its source: {path}")
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"recorded source is missing or not a regular file: {source}")
    if _sha256(source) != data["sha256"]:
        raise ValueError(f"recorded source changed: {source}")
    return source, data


def _record(source: Path, digest: str, request: dict):
    path = source.with_suffix(".acquisition.json")
    if path.exists():
        _, data = _lineage(path)
    else:
        data = {"schema": SCHEMA, "file": source.name,
                "sha256": digest, "requests": []}
    if request in data["requests"]:
        return
    data["requests"].append(request)
    fd, name = tempfile.mkstemp(prefix=".acquisition-", suffix=".json", dir=source.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def acquire_wav(query: str, requested: Path, *, seconds: int | None = None) -> Path:
    """Return one retained WAV for a query/selection, without renamed copies.

    An unchanged recorded query/selection is a verified no-download hit. A new
    query is downloaded in owned scratch; only same-size neighbouring WAVs are
    hashed to find an existing identical source. Requests/aliases accumulate in
    one small lineage file per retained WAV, not in per-run receipts.
    """
    requested = Path(requested).absolute()
    if requested.suffix.lower() != ".wav" or not query.strip():
        raise ValueError("a non-empty source query and .wav requested name are required")
    if seconds is not None and (not isinstance(seconds, int) or seconds <= 0):
        raise ValueError("selection seconds must be a positive integer")
    directory = requested.parent
    directory.mkdir(parents=True, exist_ok=True)
    request = {"query": query, "seconds": seconds, "requested_name": requested.name}
    with _lock(directory):
        for path in sorted(directory.glob("*.acquisition.json")):
            data = json.loads(path.read_text())
            if any(r["query"] == query and r["seconds"] == seconds
                   for r in data.get("requests", [])):
                source, data = _lineage(path)
                prior = next(r for r in data["requests"]
                             if r["query"] == query and r["seconds"] == seconds)
                _record(source, data["sha256"], {**request, "source_url": prior.get("source_url")})
                return source

        with tempfile.TemporaryDirectory(prefix=".acquire-", dir=directory) as temporary:
            candidate, source_url = _download(query, Path(temporary), seconds)
            if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size == 0:
                raise ValueError("acquisition produced no non-empty regular WAV")
            digest = _sha256(candidate)
            size = candidate.stat().st_size
            source = None
            for path in sorted(directory.glob("*.wav")):
                if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
                    continue
                if _sha256(path) == digest:
                    source = path
                    break
            if source is None:
                # Exclusive publication: never overwrite an earlier recording.
                os.link(candidate, requested)
                source = requested
            _record(source, digest, {**request, "source_url": source_url})
            return source
