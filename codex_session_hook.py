"""Helpers for extracting speakable final answers from Codex session JSONL."""

from __future__ import annotations

import argparse
import json
import sys

from strip_markdown import strip_markdown


def extract_final_text(line: str) -> str | None:
    """Return final assistant output text from a Codex session JSONL line."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    if event.get("type") != "response_item":
        return None

    payload = event.get("payload") or {}
    if payload.get("type") != "message":
        return None
    if payload.get("role") != "assistant":
        return None
    if payload.get("phase") != "final_answer":
        return None

    parts = []
    for item in payload.get("content") or []:
        if item.get("type") == "output_text":
            text = item.get("text", "").strip()
            if text:
                parts.append(text)

    if not parts:
        return None
    return "\n".join(parts).strip()


def extract_agent_type(line: str) -> str | None:
    """Return agent_type from a Codex session JSONL line, if present."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    payload = event.get("payload") or {}
    return payload.get("agent_type") or event.get("agent_type") or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract final assistant text from Codex session JSONL."
    )
    parser.add_argument(
        "--strip-markdown",
        action="store_true",
        help="Convert markdown output into plainer speakable text.",
    )
    parser.add_argument(
        "--agent-type",
        action="store_true",
        help="Print agent_type from event instead of the response text.",
    )
    args = parser.parse_args(argv)

    line = sys.stdin.read()

    if args.agent_type:
        agent = extract_agent_type(line)
        if agent:
            sys.stdout.write(agent)
        return 0

    text = extract_final_text(line)
    if not text:
        return 0

    if args.strip_markdown:
        text = strip_markdown(text)
        if not text:
            return 0

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
