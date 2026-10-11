#!/usr/bin/env python3
"""Report whether detected Afterwords agent integrations are installed."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


HOME = Path.home()
RUNTIME = HOME / "Library/Application Support/Afterwords/watchers/runtime"
DOMAIN = f"gui/{os.getuid()}"
failed = False


def report(name: str, state: str, detail: str = "") -> None:
    global failed
    print(f"{state:7} {name}" + (f" — {detail}" if detail else ""))
    failed |= state in ("MISSING", "MANUAL")


def json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def commands(node) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        command = node.get("command")
        if isinstance(command, str):
            found.append(command)
        for value in node.values():
            found.extend(commands(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(commands(value))
    return found


def matches_source(relative: str) -> bool:
    source = Path(__file__).resolve().parents[1] / relative
    installed = RUNTIME / relative
    try:
        return hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(installed.read_bytes()).digest()
    except OSError:
        return False


def watcher(agent: str) -> None:
    plist = HOME / "Library/LaunchAgents" / f"au.wedd.afterwords-{agent}-watch.plist"
    if not plist.exists():
        report(agent, "MISSING", "run `afterwords watchers install " + agent + "`")
        return
    result = subprocess.run(["launchctl", "print", f"{DOMAIN}/au.wedd.afterwords-{agent}-watch"],
                            capture_output=True, text=True)
    running = result.returncode == 0 and "state = running" in result.stdout
    script = RUNTIME / agent / f"afterwords-{agent}-watch.py"
    if not script.is_file() or not matches_source(f"{agent}/afterwords-{agent}-watch.py") \
            or not matches_source("watcher/queue.py") \
            or not matches_source(".claude/hooks/codex-tts-worker.sh"):
        report(agent, "MISSING", "LaunchAgent points at an incomplete runtime")
    elif running:
        try:
            values = plistlib.loads(plist.read_bytes()).get("EnvironmentVariables", {})
        except (OSError, plistlib.InvalidFileException):
            values = {}
        if "/opt/homebrew/bin" not in values.get("PATH", "").split(":"):
            report(agent, "MISSING", "watcher PATH omits Homebrew tools such as lame")
        else:
            report(agent, "OK", "source matches installed runtime; watcher is running")
    else:
        report(agent, "MISSING", "LaunchAgent is installed but not running")


def main() -> int:
    claude_settings = HOME / ".claude/settings.json"
    claude_hook = RUNTIME / ".claude/hooks/claude-tts-hook.sh"
    claude_events = json_file(claude_settings).get("hooks", {})
    if shutil.which("claude") or claude_settings.exists():
        registered = all(any("claude-tts-hook.sh" in command
                             for command in commands(claude_events.get(event, [])))
                         for event in ("Stop", "SubagentStop"))
        if registered and claude_hook.is_file() \
                and matches_source(".claude/hooks/claude-tts-hook.sh") \
                and matches_source("claude_session_hook.py"):
            report("Claude Code", "OK", "Stop and SubagentStop hook target exists")
        else:
            report("Claude Code", "MISSING", "rerun `bash setup.sh --integrations`")

    agy_hooks = HOME / ".gemini/config/hooks.json"
    agy_hook = RUNTIME / ".claude/hooks/agy-tts-hook.sh"
    if shutil.which("agy") or agy_hooks.exists():
        registered = any("agy-tts-hook.sh" in command for command in commands(json_file(agy_hooks)))
        if registered and agy_hook.is_file() \
                and matches_source(".claude/hooks/agy-tts-hook.sh") \
                and matches_source("agy_session_hook.py"):
            report("Antigravity", "OK", "Stop hook target exists")
        else:
            report("Antigravity", "MISSING", "rerun `bash setup.sh --integrations`")

    gemini_settings = HOME / ".gemini/settings.json"
    if shutil.which("gemini") or gemini_settings.exists():
        registered = any("gemini-tts-hook.sh" in command
                         for command in commands(json_file(gemini_settings)))
        adapter = HOME / ".claude/hooks/gemini-tts-hook.sh"
        if registered and adapter.is_file():
            report("Gemini CLI", "OK", "AfterAgent hook and adapter are present")
        elif adapter.is_file():
            report("Gemini CLI", "MANUAL", "adapter installed; merge the AfterAgent snippet printed by setup")
        else:
            report("Gemini CLI", "MISSING", "rerun `bash setup.sh --integrations`")

    cursor_settings = HOME / ".cursor/hooks.json"
    if shutil.which("cursor") or cursor_settings.exists() or (Path("/Applications/Cursor.app").exists()):
        registered = any("cursor-tts-hook.sh" in command
                         for command in commands(json_file(cursor_settings)))
        adapter = HOME / ".claude/hooks/cursor-tts-hook.sh"
        if registered and adapter.is_file():
            report("Cursor", "OK", "afterAgentResponse hook and adapter are present")
        else:
            report("Cursor", "MISSING", "rerun `bash setup.sh --integrations`")

    if shutil.which("codex") or (HOME / ".codex/sessions").exists():
        watcher("codex")
    if shutil.which("opencode") or (HOME / ".local/share/opencode/opencode.db").exists():
        watcher("opencode")

    hermes_hook = HOME / ".hermes/hooks/afterwords-tts/handler.py"
    if hermes_hook.exists():
        report("Hermes", "SEPARATE", "managed by docs/hermes-integration.md")

    if not any((shutil.which(name) for name in ("claude", "agy", "gemini", "cursor",
                                                 "codex", "opencode"))):
        print("No supported coding-agent CLI detected.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
