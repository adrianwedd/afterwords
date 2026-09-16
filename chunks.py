"""Canonical sentence-boundary chunker for TTS synthesis.

ONE implementation. Every Hermes surface loads this module — the native gateway
hook (`hermes/hooks/afterwords-tts/handler.py`), the direct-CLI shell hook
(`scripts/afterwords-post-llm.sh`) and the Claude/Codex workers — instead of
carrying its own copy of the splitter. Before this module existed the gateway
hook and the shell hook had drifted into two subtly different splitters, so the
same reply could be chunked differently depending on which surface spoke it.

CLI contract (`python3 chunks.py`): read text on stdin, print one chunk per
line with internal newlines stripped, safe to pass straight to /synthesize.
Library contract: `chunk_text(text, max_chars=CHUNK_CHARS) -> list[str]`.

Override the cap with the CHUNK_CHARS env var (parsed leniently: a bad value
logs a warning and falls back to the default rather than dying mid-reply).
"""
from __future__ import annotations

import os
import re
import sys
import warnings

CHUNK_CHARS = 400
_ENV_VAR = "CHUNK_CHARS"


def _resolve_default() -> int:
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        return CHUNK_CHARS
    try:
        value = int(raw)
    except ValueError:
        warnings.warn(f"chunks.py: ignoring non-integer {_ENV_VAR}={raw!r}", stacklevel=2)
        return CHUNK_CHARS
    if value <= 0:
        warnings.warn(f"chunks.py: ignoring non-positive {_ENV_VAR}={raw!r}", stacklevel=2)
        return CHUNK_CHARS
    return value


def chunk_text(text: str, max_chars: int | None = None) -> list[str]:
    """Split text into sentence-boundary chunks, each capped at max_chars.

    Splits on sentence boundaries (.!?…) first, then word boundaries for any
    single sentence longer than the cap, then packs consecutive parts together
    up to the cap so short sentences do not each become their own request.
    """
    if max_chars is None:
        max_chars = _resolve_default()
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?…])\s+', text)
    sentences = [s.strip().replace('\n', ' ') for s in sentences if s.strip()]

    # Word-split overlong sentences.
    parts: list[str] = []
    for sentence in sentences:
        if len(sentence) > max_chars:
            while len(sentence) > max_chars:
                split_at = sentence.rfind(' ', 0, max_chars)
                if split_at == -1:
                    split_at = max_chars
                piece = sentence[:split_at].strip()
                if piece:
                    parts.append(piece)
                sentence = sentence[split_at:].strip()
            if sentence:
                parts.append(sentence)
        else:
            parts.append(sentence)

    # Pack consecutive parts up to the cap.
    chunks: list[str] = []
    current = ''
    for part in parts:
        if current and len(current) + 1 + len(part) > max_chars:
            chunks.append(current)
            current = part
        elif current:
            current = current + ' ' + part
        else:
            current = part
    if current:
        chunks.append(current)

    return chunks


if __name__ == "__main__":
    for chunk in chunk_text(sys.stdin.read().strip()):
        print(chunk)
