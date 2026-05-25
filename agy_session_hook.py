"""Helper for extracting final answer from Antigravity (agy) session transcript."""

from __future__ import annotations

import argparse
import json
import sys


def extract_final_text(transcript_path: str) -> str | None:
    """Read transcript JSONL backwards and return the final model response content."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None

    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("source") != "MODEL":
            continue
        if event.get("type") != "PLANNER_RESPONSE":
            continue
        if event.get("tool_calls"):
            continue

        content = event.get("content")
        if content:
            return content.strip()

    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract final model text from agy transcript."
    )
    parser.add_argument(
        "transcript_path",
        help="Path to the transcript.jsonl file",
    )
    args = parser.parse_args(argv)

    text = extract_final_text(args.transcript_path)
    if not text:
        return 0

    sys.stdout.write(text)
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
