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
import json
import os
import subprocess
import sys
import re
from pathlib import Path

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


def save_seen(seen: set) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Read-merge-write: union with whatever is on disk right now so a marker
    # the hook pre-seeded during this pass survives our write (no clobber).
    merged = set(seen) | load_seen()
    # Atomic swap: write to a temp file in the SAME dir, then os.replace() so a
    # crash mid-write can never truncate the live tts-feed-seen.json.
    tmp = SEEN_FILE.with_suffix(SEEN_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(merged), indent=2))
    os.replace(tmp, SEEN_FILE)


def to_ogg(mp3_path: Path) -> Path | None:
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


def send_media(target: str, file_path: Path) -> bool:
    cmd = ["hermes", "send", "-t", target, f"MEDIA:{file_path}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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


def _deliver(merged: Path, send_to: set) -> None:
    """Send a prepared MP3 to each enabled platform (discord MP3, telegram OGG)."""
    if "discord" in send_to:
        send_media("discord", merged)
    if "telegram" in send_to:
        ogg = to_ogg(merged)
        send_media("telegram", ogg if ogg else merged)


def process_new_files(seen: set, dry_run: bool = False) -> set:
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

                # Merge chunks into single MP3
                merged = merge_chunks(base_stem, archive_dir)
                if merged is None:
                    # No chunks — check for single MP3 with this stem
                    single_mp3 = archive_dir / f"{base_stem}.mp3"
                    if single_mp3.exists():
                        if dry_run:
                            print(f"  [dry-run] Would send {base_stem} to {preview}")
                            new_seen.add(marker)
                            continue
                        merged = copy_to_cache(single_mp3)
                    else:
                        new_seen.add(marker)
                        continue

                if dry_run:
                    print(f"  [dry-run] Would send {base_stem} to {preview}")
                    new_seen.add(marker)
                    continue

                print(f"  [{source}] {base_stem} -> {preview}")
                _deliver(merged, send_to)

                new_seen.add(marker)
                sent_any = True

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

                if dry_run:
                    print(f"  [dry-run] Would send {name} to {preview}")
                    new_seen.add(name)
                    continue

                print(f"  [{source}] {name} -> {preview}")
                cached = copy_to_cache(mp3_file)
                _deliver(cached, send_to)

                new_seen.add(name)
                sent_any = True

    if not sent_any and not dry_run:
        print("  No new files")

    return new_seen


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Send new TTS audio to Discord/Telegram")
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    print(f"Loaded {len(seen)} previously sent items")
    
    seen = process_new_files(seen, args.dry_run)
    if not args.dry_run:
        save_seen(seen)

    if args.once:
        return
    
    print("Done")


if __name__ == "__main__":
    main()