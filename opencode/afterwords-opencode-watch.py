#!/usr/bin/env python3
"""afterwords-opencode-watch.py — speak new OpenCode assistant responses via Afterwords.

Polls opencode's sqlite store for new assistant messages (rowid watermark) and
enqueues them into /tmp/claude-tts-queue for the shared tts-worker.sh pipeline
(same as claude/agy). Voice resolves from the session directory's .afterwords
(agent key `opencode:` -> `default:`). Runs until TERM'd; started at login via
launchd (au.wedd.afterwords-opencode-watch).

Fails silent on every error: TTS must never break opencode.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DB = Path.home() / ".local/share/opencode/opencode.db"
# launchd PATH lacks Homebrew tools the shared worker needs (lame lives in
# /opt/homebrew/bin); the enqueue bash must inherit a real PATH or the worker
# silently loses its mp3 archive step.
os.environ["PATH"] = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:" + os.environ.get("PATH", "")
QUEUE_DIR = Path("/tmp/claude-tts-queue")
ENQUEUE_HOOK = Path.home() / ".claude/hooks/tts-hook-opencode.sh"
POLL_S = 2.0
HEALTH_URL = "http://127.0.0.1:7860/health"


def log(msg: str) -> None:
    try:
        with open("/tmp/afterwords-opencode-watch.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def server_up() -> bool:
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "2", HEALTH_URL], capture_output=True, timeout=4
        )
        return b'"ok"' in out.stdout or b"ok" == out.stdout.strip()
    except Exception:
        return False


def session_dir(session_id: str) -> str:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT directory FROM session_v2 WHERE id=?", (session_id,)
            ).fetchone()
        finally:
            con.close()
        return row[0] if row else ""
    except Exception:
        return ""


def latest_assistant_text(session_id: str) -> str:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT data FROM session_message WHERE session_id=? AND type='assistant' ORDER BY seq",
                (session_id,),
            ).fetchall()
        finally:
            con.close()
        for (data,) in reversed(rows):
            try:
                d = json.loads(data)
            except Exception:
                continue
            text = " ".join(
                p.get("text", "") for p in d.get("content", []) if p.get("type") == "text"
            )
            if text.strip():
                return text.strip()
    except Exception:
        pass
    return ""


def enqueue(project_dir: str, text: str) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", prefix="afterwords-oc-", dir="/tmp", delete=False
    ) as f:
        f.write(text)
        tmp = f.name
    try:
        subprocess.run(
            ["bash", str(ENQUEUE_HOOK), project_dir or os.path.expanduser("~"), tmp],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def main() -> int:
    log(f"watcher starting, db={DB}")
    max_rowid = 0
    spoken: dict[str, str] = {}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM session_message WHERE type='assistant'"
            ).fetchone()
            max_rowid = row[0] if row else 0
        finally:
            con.close()
    except Exception:
        pass
    log(f"watermark rowid={max_rowid}")
    while True:
        time.sleep(POLL_S)
        try:
            if not server_up():
                continue
            con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT rowid, id, session_id FROM session_message "
                    "WHERE type='assistant' AND rowid > ? ORDER BY rowid",
                    (max_rowid,),
                ).fetchall()
            finally:
                con.close()
        except Exception as e:
            log(f"poll error: {e}")
            continue
        for rowid, msg_id, session_id in rows:
            max_rowid = max(max_rowid, rowid)
            text = latest_assistant_text(session_id)
            if not text:
                continue
            if spoken.get(session_id) == text:
                continue
            spoken[session_id] = text
            proj = session_dir(session_id)
            log(f"speaking {session_id} ({len(text)} chars) dir={proj}")
            enqueue(proj, text)


if __name__ == "__main__":
    sys.exit(main())