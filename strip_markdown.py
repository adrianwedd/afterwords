"""Strip markdown formatting for cleaner TTS output.

Usable as an importable module or as a stdin-to-stdout script.
The regex pipeline preserves inline code content (strips only backticks),
removes fenced code blocks, tables, and markdown formatting.

Structural cues (bullets, numbered lists, headings, blank lines) become
sentence boundaries so the TTS model pauses between points instead of
running them together.

CLI default is no truncation (hooks speak the full reply). Pass
STRIP_MARKDOWN_MAX_CHARS=N to cap length; the library default remains
1000 for callers that omit max_chars.
"""
from __future__ import annotations

import re

_SENTENCE_END = re.compile(r'[.!?…:;]$')
_BULLET = re.compile(r'^(\s*)([-*•]|\d+[.)])\s+(.*)$')
_HEADING = re.compile(r'^#{1,6}\s+(.*)$')
_BLOCKQUOTE = re.compile(r'^\s*>\s?(.*)$')
_TABLE_ROW = re.compile(r'^\|.*\|$')
_TABLE_SEP = re.compile(r'^[-|:\s]+$')


def _ensure_sentence(text: str) -> str:
    """Make a fragment end in sentence punctuation so TTS inserts a pause."""
    text = text.strip()
    if not text:
        return ""
    if _SENTENCE_END.search(text):
        return text
    return text + "."


def _inline_markdown(text: str) -> str:
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # Drop raw URLs — speaking them aloud is noise.
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\bwww\.\S+', '', text)
    # Prefer the file basename over a long path (/a/b/foo.py → foo.py).
    text = re.sub(r'(?:[A-Za-z]:)?(?:/[\w.-]+)+/([\w.-]+\.\w+)\b', r'\1', text)
    # Em/en dashes and arrows → short comma pauses.
    text = re.sub(r'\s*[—–]\s*', ', ', text)
    text = re.sub(r'\s*→\s*', ', ', text)
    text = re.sub(r'\s*<->\s*', ', ', text)
    text = re.sub(r'\s*->\s*', ', ', text)
    # snake_case identifiers read better as words.
    text = re.sub(
        r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b',
        lambda m: m.group(1).replace('_', ' '),
        text,
    )
    # Normalize ellipses to a single pause character.
    text = re.sub(r'\.{3,}', '…', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    text = re.sub(r'(,\s*){2,}', ', ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _structural_lines(text: str) -> list[str]:
    """Turn markdown structure into spoken sentence fragments."""
    # Drop fenced code entirely (not speakable).
    text = re.sub(r'```[\s\S]*?```', '\n\n', text)

    spoken: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            # Paragraph break → explicit pause boundary.
            if spoken and spoken[-1] != '':
                spoken.append('')
            continue

        if _TABLE_ROW.match(line.strip()) or _TABLE_SEP.match(line.strip()):
            continue

        m = _HEADING.match(line)
        if m:
            spoken.append(_ensure_sentence(_inline_markdown(m.group(1))))
            spoken.append('')  # pause after a heading
            continue

        m = _BLOCKQUOTE.match(line)
        if m:
            spoken.append(_ensure_sentence(_inline_markdown(m.group(1))))
            continue

        m = _BULLET.match(line)
        if m:
            # Each bullet/number is its own spoken beat.
            spoken.append(_ensure_sentence(_inline_markdown(m.group(3))))
            continue

        spoken.append(_inline_markdown(line))

    return spoken


def _join_spoken(parts: list[str]) -> str:
    """Join fragments with sentence-aware spacing."""
    out: list[str] = []
    for part in parts:
        if part == '':
            if out and not out[-1].endswith(('.', '!', '?', '…', ':')):
                out[-1] = out[-1] + '.'
            continue
        if not out:
            out.append(part)
            continue
        prev = out[-1]
        # Soft-wrap continuation (no blank line): keep a space unless we
        # already ended a sentence / list item.
        if _SENTENCE_END.search(prev):
            out.append(part)
        else:
            out[-1] = prev + ' ' + part
    text = ' '.join(out)
    text = re.sub(r'\s+', ' ', text).strip()
    # Collapse accidental double punctuation from ensure_sentence + original.
    text = re.sub(r'([.!?…])\1+', r'\1', text)
    text = re.sub(r'\.\s*\.', '. ', text)
    return text.strip()


def strip_markdown(text: str, max_chars: int | None = 1000) -> str:
    """Strip markdown formatting from text for TTS."""
    text = _join_spoken(_structural_lines(text))
    if max_chars is not None:
        text = text[:max_chars]
    return text


if __name__ == "__main__":
    import os
    import sys

    # Default 0 = no cap. A hard 1000-char cut made long agent replies
    # stop mid-sentence during TTS.
    raw_limit = os.environ.get("STRIP_MARKDOWN_MAX_CHARS", "0")
    limit: int | None
    if raw_limit in {"", "0", "none", "None"}:
        limit = None
    else:
        limit = int(raw_limit)
    print(strip_markdown(sys.stdin.read(), max_chars=limit))
