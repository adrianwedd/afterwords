"""Summarize long agent responses before TTS.

Uses Ollama when cursor_summarize_model (or summarize_model) is set in
.afterwords; otherwise falls back to a fast extractive two-sentence clip.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MIN_CHARS = 400
DEFAULT_SENTENCES = 2
DEFAULT_MAX_CHARS = 350
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


def _trim(s: str) -> str:
    return s.strip()


def parse_afterwords_config(aw_path: str | Path | None, agent: str) -> dict:
    """Read summarize settings from .afterwords (agent-specific keys win)."""
    cfg: dict = {
        "enabled": False,
        "min_chars": DEFAULT_MIN_CHARS,
        "sentences": DEFAULT_SENTENCES,
        "max_chars": DEFAULT_MAX_CHARS,
        "model": "",
    }
    if not aw_path:
        return cfg

    path = Path(aw_path)
    if not path.is_file():
        return cfg

    agent_prefix = f"{agent}_" if agent else ""
    global_keys = {
        "summarize": "enabled",
        "summarize_min": "min_chars",
        "summarize_sentences": "sentences",
        "summarize_max_chars": "max_chars",
        "summarize_model": "model",
    }
    agent_keys = {
        f"{agent_prefix}summarize": "enabled",
        f"{agent_prefix}summarize_min": "min_chars",
        f"{agent_prefix}summarize_sentences": "sentences",
        f"{agent_prefix}summarize_max_chars": "max_chars",
        f"{agent_prefix}summarize_model": "model",
    }

    # Match longest known keys first so agent keys that contain colons
    # (e.g. feature-dev:code-architect_summarize) win over shorter prefixes,
    # and values may themselves contain colons (llama3.2:1b).
    ordered = sorted(
        list(global_keys.items()) + list(agent_keys.items()),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for key, field in ordered:
            if not line.startswith(key):
                continue
            rest = line[len(key) :].lstrip()
            if not rest.startswith(":"):
                continue
            _apply_config_key(cfg, field, _trim(rest[1:]))
            break

    return cfg


def _apply_config_key(cfg: dict, field: str, val: str) -> None:
    if field == "enabled":
        cfg["enabled"] = val.lower() in {"1", "true", "yes", "on"}
    elif field == "model":
        cfg["model"] = val
    elif field in {"min_chars", "sentences", "max_chars"}:
        try:
            cfg[field] = int(val)
        except ValueError:
            pass


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def extractive_summary(text: str, *, sentences: int = 2, max_chars: int = 350) -> str:
    """Cheap fallback: opening + closing sentence (agents often conclude at the end)."""
    sents = split_sentences(text)
    if len(sents) <= sentences:
        return text[:max_chars]

    if len(sents) >= 3:
        summary = f"{sents[0]} {sents[-1]}"
    else:
        summary = " ".join(sents[:sentences])

    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rsplit(" ", 1)[0] + "."
    return summary.strip()


def ollama_summarize(
    text: str,
    model: str,
    *,
    sentences: int = 2,
    max_chars: int = 350,
    timeout: float = 8.0,
) -> str:
    prompt = (
        f"Summarize this coding-assistant reply in exactly {sentences} short spoken "
        f"sentences (max {max_chars} characters total). Plain English only — no "
        "markdown, bullets, code, or paths. Say what was done and the outcome.\n\n"
        f"{text[:6000]}"
    )
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 160, "temperature": 0.2},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""

    out = _trim(body.get("response", ""))
    if not out:
        return ""
    out = re.sub(r"\s+", " ", out)
    return out[:max_chars]


def summarize_for_tts(
    text: str,
    *,
    agent: str = "cursor",
    afterwords_path: str | Path | None = None,
) -> str:
    """Return text unchanged, or a short spoken summary when configured."""
    clean = _trim(text)
    if not clean:
        return clean

    cfg = parse_afterwords_config(afterwords_path, agent)
    if not cfg["enabled"] or len(clean) < cfg["min_chars"]:
        return clean

    model = cfg["model"]
    if model:
        llm = ollama_summarize(
            clean,
            model,
            sentences=cfg["sentences"],
            max_chars=cfg["max_chars"],
        )
        if llm:
            return llm

    return extractive_summary(
        clean,
        sentences=cfg["sentences"],
        max_chars=cfg["max_chars"],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Summarize agent text for TTS")
    parser.add_argument("--agent", default="cursor")
    parser.add_argument("--afterwords", default="")
    args = parser.parse_args()
    src = sys.stdin.read()
    aw = args.afterwords or None
    print(summarize_for_tts(src, agent=args.agent, afterwords_path=aw))
