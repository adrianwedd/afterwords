#!/usr/bin/env python3
"""
Watch TTS archives and send new audio to Discord/Telegram.

Monitors ~/.hermes/tts-archive/ and ~/.claude/tts-archive/ for new MP3
files. For Claude archives, merges chunked files (c1.mp3, c2.mp3...) into
a single audio file before sending.

Keeps state in ~/.hermes/tts-feed-seen.json to avoid re-sending.

Usage:
    python3 scripts/tts-feed-send.py [--once] [--dry-run]
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import re
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

HERMES_ARCHIVE = Path.home() / ".hermes" / "tts-archive"
CLAUDE_ARCHIVE = Path.home() / ".claude" / "tts-archive"
AUDIO_CACHE = Path.home() / ".hermes" / "audio_cache"
SEEN_FILE = Path.home() / ".hermes" / "tts-feed-seen.json"
HOME_AFTERWORDS = Path.home() / ".afterwords"

WATCH_DIRS = [
    (HERMES_ARCHIVE, "hermes"),
    (CLAUDE_ARCHIVE, "claude"),
]

# Only these platforms may ever be targeted by the watcher.
KNOWN_PLATFORMS = ("telegram", "discord")
BACKLOG_QUIESCENCE_SECONDS = 300


def _parse_send_to_tokens(raw: str) -> set:
    """Parse a comma-separated platform list, keeping only known platforms."""
    return {
        tok.strip().lower()
        for tok in raw.split(",")
        if tok.strip().lower() in KNOWN_PLATFORMS
    }


def _send_to_from_file(path: Path) -> set | None:
    """Return the platform set from a `send_to:` line in an .afterwords file.

    Returns None if the file is absent or has no send_to: directive (so the
    caller can fall back to the next source). Returns a (possibly empty) set
    if a send_to: line is present.
    """
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        if key.strip().lower() == "send_to":
            return _parse_send_to_tokens(val)
    return None


def resolve_send_to() -> set:
    """Resolve the set of platforms allowed to receive external sends.

    Priority (first match wins):
      1. env AFTERWORDS_SEND_TO (comma-separated)
      2. send_to: line in $PWD/.afterwords
      3. send_to: line in $HOME/.afterwords
    Default: empty set (no external send). Only telegram/discord accepted;
    unknown tokens are ignored.
    """
    env = os.environ.get("AFTERWORDS_SEND_TO")
    if env is not None:
        return _parse_send_to_tokens(env)

    pwd_result = _send_to_from_file(Path.cwd() / ".afterwords")
    if pwd_result is not None:
        return pwd_result

    home_result = _send_to_from_file(HOME_AFTERWORDS)
    if home_result is not None:
        return home_result

    return set()


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


LOCK_FILE = Path.home() / ".hermes" / "tts-feed-send.lock"


def acquire_lock() -> int:
    """Exclusive flock on a lock file. Returns the fd (caller must KEEP it open
    for the life of the run — closing releases the lock). Raises BlockingIOError
    if another instance holds it. Without this, a hung instance + a periodic
    relauncher (launchd StartInterval) spawns overlapping senders that each see
    the same 'unseen' archive files and re-deliver them — the 2026-10-10 flood."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.truncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def _fsync_directory(path: Path) -> None:
    """Make a completed create/replace durable across a host crash."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_seen(seen: set, *, remove: set | None = None) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Read-merge-write: union with whatever is on disk right now so a marker
    # the hook pre-seeded during this pass survives our write (no clobber).
    merged = (set(seen) | load_seen()) - set(remove or ())
    # Atomic swap: write to a temp file in the SAME dir, then os.replace() so a
    # crash mid-write can never truncate the live tts-feed-seen.json.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{SEEN_FILE.name}.", suffix=".tmp", dir=SEEN_FILE.parent,
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(sorted(merged), handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, SEEN_FILE)
        _fsync_directory(SEEN_FILE.parent)
    finally:
        tmp.unlink(missing_ok=True)


def to_ogg(mp3_path: Path) -> Path | None:
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    ogg_path = AUDIO_CACHE / f"{mp3_path.stem}.ogg"
    if ogg_path.exists():
        return ogg_path
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-c:a", "libopus", "-b:a", "64k", str(ogg_path)],
        capture_output=True, timeout=30,
    )
    return ogg_path if result.returncode == 0 else None


def copy_to_cache(mp3_path: Path) -> Path:
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    dest = AUDIO_CACHE / mp3_path.name
    if not dest.exists() or dest.stat().st_size != mp3_path.stat().st_size:
        import shutil
        shutil.copy2(str(mp3_path), str(dest))
    return dest


def merge_chunks(base_stem: str, archive_dir: Path) -> Path | None:
    """Merge chunked MP3 files (base-c1.mp3, base-c2.mp3, ...) into one file."""
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    chunks = sorted(archive_dir.glob(f"{base_stem}-c[0-9]*.mp3"))
    if not chunks:
        return None
    
    # Use ffmpeg concat demuxer to merge
    merged = AUDIO_CACHE / f"{base_stem}-merged.mp3"
    concat_file = AUDIO_CACHE / f"{base_stem}.concat"
    
    # Find the .txt sidecar for text content
    txt_file = archive_dir / f"{base_stem}.txt"
    
    try:
        concat_content = "\n".join(f"file '{c.absolute()}'" for c in chunks)
        concat_file.write_text(concat_content)
        
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(merged)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and merged.exists() and merged.stat().st_size > 100:
            # Copy text sidecar if it exists
            if txt_file.exists():
                import shutil
                txt_dest = AUDIO_CACHE / f"{base_stem}.txt"
                shutil.copy2(str(txt_file), str(txt_dest))
            return merged
    except Exception:
        pass
    finally:
        concat_file.unlink(missing_ok=True)
    
    return None


def send_media(target: str, file_path: Path) -> bool | None:
    """Return True/False for confirmed outcomes, None when outcome is unknown."""
    cmd = ["hermes", "send", "-t", target, f"MEDIA:{file_path}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        # The remote service may have accepted the message before the local CLI
        # timed out. Never turn that ambiguity into an automatic duplicate.
        print(
            f"  [UNKNOWN] hermes send {target} timed out; holding for reconciliation",
            file=sys.stderr,
        )
        return None
    if result.returncode != 0:
        print(f"  [ERROR] hermes send {target}: {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  [sent] {target}: {file_path.name}")
    return True


def parse_claude_stem(name: str) -> str | None:
    """Extract base stem from Claude chunk filenames.
    
    the-doctor-20260527-175322-12999-26349-c5.mp3 -> the-doctor-20260527-175322-12999-26349
    ace-20260504-232124-70606-15100.mp3 -> ace-20260504-232124-70606-15100
    """
    # Remove extension
    stem = name.rsplit(".", 1)[0] if "." in name else name
    # Remove chunk suffix like -c5
    stem = re.sub(r"-c\d+$", "", stem)
    return stem


def _deliver(
    merged: Path,
    send_to: set,
    marker: str,
    seen: set,
    *,
    persist: bool,
) -> set:
    """Deliver targets with a durable per-target crash boundary.

    Persist an in-flight marker before egress and a success marker immediately
    after confirmation. Recovered in-flight attempts are ambiguous and held for
    reconciliation rather than blindly retried without a remote idempotency key.
    """
    delivered = set()
    for target in ("discord", "telegram"):
        if target not in send_to:
            continue
        success_marker = f"{marker}:{target}"
        inflight_marker = f"{success_marker}:inflight"
        if success_marker in seen:
            continue
        if inflight_marker in seen:
            print(
                f"  [hold] {marker} -> {target} has an indeterminate prior attempt; "
                "reconcile before retrying",
                file=sys.stderr,
            )
            continue

        seen.add(inflight_marker)
        if persist:
            save_seen(seen)

        media = merged
        if target == "telegram":
            ogg = to_ogg(merged)
            media = ogg if ogg else merged
        outcome = send_media(target, media)
        if outcome is True:
            delivered.add(target)
            seen.add(success_marker)
            if persist:
                save_seen(seen)
        elif outcome is False:
            seen.discard(inflight_marker)
            if persist:
                save_seen(seen, remove={inflight_marker})
        # None deliberately retains the durable in-flight marker.
    return delivered


def process_new_files(seen: set, dry_run: bool = False, *, persist: bool = False) -> set:
    new_seen = set(seen)
    sent_any = False
    send_to = resolve_send_to()
    preview = "+".join(sorted(send_to)) if send_to else "(none)"

    for archive_dir, source in WATCH_DIRS:
        if not archive_dir.exists():
            continue

        # For Claude: group by base stem and only send complete (non-chunk) files
        if source == "claude":
            # Find all .txt sidecar files — these mark complete responses
            for txt_file in sorted(archive_dir.glob("*.txt")):
                base_stem = txt_file.stem
                # Check if we've seen this base stem
                marker = f"claude:{base_stem}"
                if marker in new_seen:
                    continue

                # Empty send_to: still mark seen so files don't accumulate.
                if not send_to:
                    print(f"  [skip] {base_stem} (no send_to configured)")
                    new_seen.add(marker)
                    continue

                pending = {
                    target for target in send_to
                    if f"{marker}:{target}" not in new_seen
                }
                if not pending:
                    new_seen.add(marker)
                    continue

                # A preview must not run ffmpeg or populate the delivery cache.
                # Check source presence only; actual assembly belongs to the
                # authorised delivery path.
                if dry_run:
                    has_audio = (
                        any(archive_dir.glob(f"{base_stem}-c[0-9]*.mp3"))
                        or (archive_dir / f"{base_stem}.mp3").is_file()
                    )
                    if has_audio:
                        print(f"  [dry-run] Would send {base_stem} to {'+'.join(sorted(pending))}")
                    continue

                # Merge chunks into single MP3
                merged = merge_chunks(base_stem, archive_dir)
                if merged is None:
                    # No chunks — check for single MP3 with this stem
                    single_mp3 = archive_dir / f"{base_stem}.mp3"
                    if single_mp3.exists():
                        merged = copy_to_cache(single_mp3)
                    else:
                        new_seen.add(marker)
                        continue

                print(f"  [{source}] {base_stem} -> {'+'.join(sorted(pending))}")
                delivered = _deliver(
                    merged, pending, marker, new_seen, persist=persist,
                )
                if all(f"{marker}:{target}" in new_seen for target in send_to):
                    new_seen.add(marker)
                sent_any = sent_any or bool(delivered)

        else:
            # Hermes archive — send standalone MP3s (skip chunks)
            for mp3_file in sorted(archive_dir.glob("*.mp3")):
                name = mp3_file.name
                if name in new_seen:
                    continue

                # Skip chunked files
                if re.search(r"-c\d+\.", name):
                    new_seen.add(name)
                    continue

                # Empty send_to: still mark seen so files don't accumulate.
                if not send_to:
                    print(f"  [skip] {name} (no send_to configured)")
                    new_seen.add(name)
                    continue

                marker = f"hermes:{name}"
                pending = {
                    target for target in send_to
                    if f"{marker}:{target}" not in new_seen
                }
                if not pending:
                    new_seen.add(name)
                    continue

                if dry_run:
                    print(f"  [dry-run] Would send {name} to {'+'.join(sorted(pending))}")
                    continue

                print(f"  [{source}] {name} -> {'+'.join(sorted(pending))}")
                cached = copy_to_cache(mp3_file)
                delivered = _deliver(
                    cached, pending, marker, new_seen, persist=persist,
                )
                if all(f"{marker}:{target}" in new_seen for target in send_to):
                    new_seen.add(name)
                sent_any = sent_any or bool(delivered)

    if not sent_any and not dry_run:
        print("  No new files")

    return new_seen


def _asset_record(path: Path) -> dict:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def _asset_content_matches(record: dict) -> bool:
    path = Path(record["path"])
    try:
        current = _asset_record(path)
    except OSError:
        return False
    return current["size"] == record["size"] and current["sha256"] == record["sha256"]


def _item_assets_unchanged(item: dict) -> bool:
    """Re-enumerate as well as re-hash: added/removed chunks invalidate a snapshot."""
    records = item.get("assets", [])
    if not records:
        return False
    expected = {Path(record["path"]) for record in records}
    if item.get("source") == "claude":
        archive_dir = next(iter(expected)).parent
        stem = item["item"]
        actual = {archive_dir / f"{stem}.txt"}
        actual.update(archive_dir.glob(f"{stem}-c[0-9]*.mp3"))
        single = archive_dir / f"{stem}.mp3"
        if single.is_file():
            actual.add(single)
    else:
        actual = expected
    return actual == expected and all(
        _asset_record(Path(record["path"])) == record for record in records
    )


def _replace_receipt(receipt_path: Path, receipt: dict) -> None:
    fd, complete_name = tempfile.mkstemp(
        prefix=f".{receipt_path.name}.", suffix=".complete", dir=receipt_path.parent,
    )
    complete_path = Path(complete_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(receipt, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(complete_path, receipt_path)
        _fsync_directory(receipt_path.parent)
    finally:
        complete_path.unlink(missing_ok=True)


def discard_current_backlog(
    seen: set,
    receipt_path: Path,
    *,
    quiescence_seconds: int = BACKLOG_QUIESCENCE_SECONDS,
) -> dict:
    """Mark the complete backlog seen without sending or assembling audio.

    This is an explicit recovery operation for a long-disabled scheduler, not a
    startup default. The caller already holds the feed lock. A receipt is
    mandatory and exclusive so the disposition cannot be repeated or confused
    with successful external delivery.
    """
    if receipt_path.exists():
        raise FileExistsError(f"receipt already exists: {receipt_path}")
    if quiescence_seconds < 0:
        raise ValueError("quiescence_seconds must be non-negative")
    before_bytes = SEEN_FILE.read_bytes() if SEEN_FILE.exists() else b""
    cutoff_ns = time.time_ns()
    settled_before_ns = cutoff_ns - quiescence_seconds * 1_000_000_000
    discarded = []
    deferred = []
    updated = set(seen)
    for archive_dir, source in WATCH_DIRS:
        if not archive_dir.exists():
            continue
        if source == "claude":
            for txt_file in sorted(archive_dir.glob("*.txt")):
                stem = txt_file.stem
                marker = f"claude:{stem}"
                if marker in updated:
                    continue
                has_audio = (
                    any(archive_dir.glob(f"{stem}-c[0-9]*.mp3"))
                    or (archive_dir / f"{stem}.mp3").is_file()
                )
                if has_audio:
                    assets = [txt_file]
                    assets.extend(sorted(archive_dir.glob(f"{stem}-c[0-9]*.mp3")))
                    single = archive_dir / f"{stem}.mp3"
                    if single.is_file():
                        assets.append(single)
                    records = [_asset_record(path) for path in assets]
                    if any(row["mtime_ns"] > settled_before_ns for row in records):
                        deferred.append({"source": source, "item": stem, "reason": "not_quiescent"})
                        continue
                    updated.add(marker)
                    discarded.append({
                        "source": source, "item": stem, "marker": marker,
                        "assets": records,
                    })
        else:
            for mp3_file in sorted(archive_dir.glob("*.mp3")):
                if re.search(r"-c\d+\.", mp3_file.name) or mp3_file.name in updated:
                    continue
                record = _asset_record(mp3_file)
                if record["mtime_ns"] > settled_before_ns:
                    deferred.append({
                        "source": source, "item": mp3_file.name, "reason": "not_quiescent",
                    })
                    continue
                updated.add(mp3_file.name)
                discarded.append({
                    "source": source, "item": mp3_file.name, "marker": mp3_file.name,
                    "assets": [record],
                })

    receipt = {
        "schema_version": 1,
        "status": "prepared",
        "action": "discard_current_backlog_as_stale_without_delivery",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_cutoff_ns": cutoff_ns,
        "quiescence_seconds": quiescence_seconds,
        "external_messages_sent": 0,
        "before_seen_sha256": hashlib.sha256(before_bytes).hexdigest(),
        "discarded_count": len(discarded),
        "discarded": discarded,
        "deferred": deferred,
        "recovery": "Use --recover-backlog-disposition with this receipt; original assets must still match their recorded SHA-256 values.",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        # Persist intent before the atomic seen-state swap. If the process dies,
        # a `prepared` receipt exposes the incomplete disposition instead of
        # leaving an unexplained state change.
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(receipt_path.parent)

    # Freeze the snapshot before changing delivery state. A producer that
    # modifies any selected transcript/audio object causes an explicit abort.
    if not all(_item_assets_unchanged(item) for item in discarded):
        raise RuntimeError("backlog asset changed after snapshot; seen state not modified")

    save_seen(updated)
    after_bytes = SEEN_FILE.read_bytes()
    receipt["status"] = "complete"
    receipt["after_seen_sha256"] = hashlib.sha256(after_bytes).hexdigest()

    # Never truncate the only prepared receipt after mutating seen-state.
    # Failure while writing this separately-fsynced completion leaves the
    # durable `prepared` receipt and exact marker inventory intact.
    _replace_receipt(receipt_path, receipt)
    return receipt


def recover_backlog_disposition(receipt_path: Path) -> dict:
    """Mechanically reverse only the markers added by a complete disposition."""
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("action") != "discard_current_backlog_as_stale_without_delivery":
        raise ValueError("receipt is not a backlog-disposition receipt")
    if receipt.get("status") not in {"prepared", "complete", "recovered"}:
        raise ValueError("unsupported backlog-disposition receipt status")
    if receipt.get("status") == "recovered":
        return receipt
    mismatched = [
        asset["path"]
        for item in receipt.get("discarded", [])
        for asset in item.get("assets", [])
        if not _asset_content_matches(asset)
    ]
    if mismatched:
        raise RuntimeError(f"original backlog assets changed or are missing: {mismatched}")
    markers = {item["marker"] for item in receipt.get("discarded", [])}
    before_bytes = SEEN_FILE.read_bytes() if SEEN_FILE.exists() else b""
    current = load_seen()
    if receipt.get("status") == "prepared":
        current_hash = hashlib.sha256(before_bytes).hexdigest()
        if current_hash == receipt.get("before_seen_sha256"):
            receipt["status"] = "aborted_before_seen_mutation"
            receipt["recovered_at"] = datetime.now(timezone.utc).isoformat()
            receipt["recovered_markers"] = []
            _replace_receipt(receipt_path, receipt)
            return receipt
        if not markers.issubset(current):
            raise RuntimeError(
                "prepared receipt does not match either before-state or applied markers; "
                "manual reconciliation required"
            )
    save_seen(current - markers, remove=markers)
    after_bytes = SEEN_FILE.read_bytes()
    receipt["status"] = "recovered"
    receipt["recovered_at"] = datetime.now(timezone.utc).isoformat()
    receipt["recovery_before_seen_sha256"] = hashlib.sha256(before_bytes).hexdigest()
    receipt["recovery_after_seen_sha256"] = hashlib.sha256(after_bytes).hexdigest()
    receipt["recovered_markers"] = sorted(markers)
    _replace_receipt(receipt_path, receipt)
    return receipt


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Send new TTS audio to Discord/Telegram")
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument(
        "--discard-current-backlog", action="store_true",
        help="mark the complete current backlog stale without sending (requires --receipt)",
    )
    parser.add_argument(
        "--recover-backlog-disposition", action="store_true",
        help="remove only markers added by a complete disposition receipt",
    )
    parser.add_argument(
        "--quiescence-seconds", type=int, default=BACKLOG_QUIESCENCE_SECONDS,
        help="exclude backlog assets modified within this many seconds",
    )
    parser.add_argument("--receipt", type=Path, help="exclusive receipt for backlog discard")
    args = parser.parse_args()
    operation_count = int(args.discard_current_backlog) + int(args.recover_backlog_disposition)
    if operation_count > 1:
        parser.error("backlog discard and recovery are mutually exclusive")
    if bool(operation_count) != bool(args.receipt):
        parser.error("a backlog discard or recovery operation and --receipt are required together")
    if operation_count and args.dry_run:
        parser.error("backlog operations and --dry-run are mutually exclusive")

    try:
        _lock_fd = acquire_lock()
    except BlockingIOError:
        holder = ""
        try:
            holder = LOCK_FILE.read_text().strip()
        except OSError:
            pass
        print(f"Another tts-feed-send instance holds the lock ({holder or 'pid unknown'}) — exiting without sending.")
        return
    seen = load_seen()
    print(f"Loaded {len(seen)} previously sent items")

    if args.discard_current_backlog:
        receipt = discard_current_backlog(
            seen, args.receipt, quiescence_seconds=args.quiescence_seconds,
        )
        print(
            f"Discarded {receipt['discarded_count']} stale backlog items without delivery; "
            f"receipt: {args.receipt}"
        )
        return
    if args.recover_backlog_disposition:
        receipt = recover_backlog_disposition(args.receipt)
        print(
            f"Recovered {len(receipt.get('recovered_markers', []))} backlog markers; "
            f"receipt: {args.receipt}"
        )
        return
    
    seen = process_new_files(seen, args.dry_run, persist=not args.dry_run)
    if not args.dry_run:
        save_seen(seen)

    if args.once:
        return
    
    print("Done")


if __name__ == "__main__":
    main()
