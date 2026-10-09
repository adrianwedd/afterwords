"""afterwords-codex-watch.py — speak new Codex final answers via Afterwords.

Watches ~/.codex/sessions for rollout JSONL files and speaks assistant
final_answer lines through the existing per-thread codex hook
(.claude/hooks/codex-tts-hook.sh's queue/worker pipeline), giving every new
Codex session coverage without arming it manually from inside the session.

Line-offset watermarks per file make restarts resumable and exactly-once; a
file that shrinks (rewrite/reopen) resets its watermark. A project directory
for each rollout is resolved from its first line's cwd field when present.

Fails silent on every error: TTS must never break codex.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
WATCH_SCRIPT = Path.home() / "repos/afterwords/.claude/hooks/codex-tts-hook.sh"
POLL_S = 2.0

# launchd PATH lacks Homebrew tools the worker needs (lame lives in
# /opt/homebrew/bin); enqueue's bash must inherit a real PATH or the worker
# silently loses its mp3 archive step.
os.environ["PATH"] = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:" + os.environ.get("PATH", "")


STATE_FILE = Path("/tmp/afterwords-codex-watch-state.json")


def _load_state() -> dict[str, int]:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict[str, int]) -> None:
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def log(msg: str) -> None:
    try:
        with open("/tmp/afterwords-codex-watch.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def rollout_files() -> list[Path]:
    out: list[Path] = []
    try:
        for day_dir in sorted(SESSIONS_ROOT.glob("*/*/*")):
            for f in day_dir.glob("rollout-*.jsonl"):
                try:
                    # Rollouts older than 1h are dead sessions; skip cheaply.
                    if time.time() - f.stat().st_mtime > 3600:
                        continue
                    out.append(f)
                except OSError:
                    continue
    except OSError:
        pass
    return out


def file_cwd(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = d.get("payload") or d
                cwd = payload.get("cwd") or d.get("cwd")
                if cwd:
                    return str(cwd)
    except OSError:
        pass
    return ""


def final_answer_lines(path: Path, start_line: int) -> list[str]:
    """Final-answer lines from `start_line` (1-indexed) onward; '' payload text skipped."""
    lines: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i < start_line:
                    continue
                if '"final_answer"' not in line or '"assistant"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") or {}
                if (
                    event.get("type") == "response_item"
                    and payload.get("type") == "message"
                    and payload.get("role") == "assistant"
                    and payload.get("phase") == "final_answer"
                    and any(
                        item.get("text", "").strip()
                        for item in payload.get("content") or []
                        if item.get("type") == "output_text"
                    )
                ):
                    lines.append(line)
    except OSError:
        pass
    return lines


def main() -> int:
    log(f"watcher starting, root={SESSIONS_ROOT}")
    watermarks: dict[str, int] = _load_state()

    while True:
        time.sleep(POLL_S)
        changed = False
        for path in rollout_files():
            try:
                n_lines = sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
            except OSError:
                continue
            key = str(path)
            prev = watermarks.get(key)
            if prev is None:
                # First sighting: watermark past everything already written —
                # only NEW lines this session produce get spoken. But on this
                # fresh watcher start, live sessions may still be running and
                # lines already on disk but spoken by nobody must be caught:
                # if the file was modified within the last 60s, speak from the
                # last final_answer written to disk, else skip old content.
                # Persistent watermarks make a restart deterministic: lines
                # already seen by ANY prior watcher instance are skipped, so
                # exactly-once holds across restarts. A genuinely brand-new
                # file gets one catch-up of its current final answers only if
                # it went live while we were down (mtime <= 60s old) — then it
                # is marked at its full length immediately after.
                if time.time() - path.stat().st_mtime <= 60:
                    prev = 0  # speak pending content of an active session
                else:
                    watermarks[key] = n_lines
                    changed = True
                    continue
            if n_lines < prev:  # rewritten/rotated: reset
                prev = 0
            watermarks[key] = max(watermarks.get(key, 0), n_lines)
            changed = True
            pend_start = prev + 1
            lines = final_answer_lines(path, pend_start)
            if not lines:
                continue
            thread_id = path.stem.replace("rollout-", "")
            thread_id = thread_id[20:] if len(thread_id) > 40 and thread_id[19] == "T" else thread_id.split("-2")[0]
            cwd = file_cwd(path)
            for line in lines:
                env = dict(os.environ)
                env["CODEX_THREAD_ID"] = thread_id
                env["PROJECT_DIR"] = cwd
                try:
                    subprocess.run(
                        ["bash", str(WATCH_SCRIPT), thread_id],
                        input=line,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        env=env,
                    )
                    log(f"enqueued final answer thread={thread_id} project={cwd}")
                except Exception as e:
                    log(f"enqueue error thread={thread_id}: {e}")
        if changed:
            _save_state(watermarks)
            changed = False


if __name__ == "__main__":
    sys.exit(main())