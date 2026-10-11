"""Helper for extracting final answer from Antigravity (agy) session transcript."""

from __future__ import annotations

import argparse
import hashlib
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


def extract_final_event(transcript_path: str) -> dict | None:
    """Return the final response and an identity stable across repeated Stop hooks."""
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
        if event.get("source") != "MODEL" or event.get("type") != "PLANNER_RESPONSE":
            continue
        if event.get("tool_calls"):
            continue
        content = event.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        step = str(event.get("step_index", ""))
        created = str(event.get("created_at", ""))
        digest = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
        return {"text": content.strip(), "event_id": f"{step}:{created}:{digest}"}
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract final model text from agy transcript."
    )
    parser.add_argument(
        "transcript_path",
        help="Path to the transcript.jsonl file",
    )
    parser.add_argument("--json", action="store_true", help="Emit text and stable event identity")
    args = parser.parse_args(argv)

    if args.json:
        result = extract_final_event(args.transcript_path)
        if result:
            sys.stdout.write(json.dumps(result, ensure_ascii=False))
        return 0

    text = extract_final_text(args.transcript_path)
    if not text:
        return 0

    sys.stdout.write(text)
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
