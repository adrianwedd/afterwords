"""Split text into sentence-boundary chunks for TTS synthesis.

Each chunk is capped at MAX_CHARS characters. Chunks are printed one per line
with internal newlines stripped — safe to pass directly to /synthesize.
"""
import re
import sys

MAX_CHARS = 200

text = sys.stdin.read().strip()
if not text:
    sys.exit(0)

sentences = re.split(r'(?<=[.!?…])\s+', text)
sentences = [s.strip().replace('\n', ' ') for s in sentences if s.strip()]

def _word_split(sentence: str) -> list[str]:
    """Split a sentence longer than MAX_CHARS on word boundaries."""
    parts: list[str] = []
    while len(sentence) > MAX_CHARS:
        split_at = sentence.rfind(' ', 0, MAX_CHARS)
        if split_at == -1:
            split_at = MAX_CHARS
        parts.append(sentence[:split_at].strip())
        sentence = sentence[split_at:].strip()
    if sentence:
        parts.append(sentence)
    return parts


# Normalize: sentences longer than MAX_CHARS become multiple word-split parts.
parts: list[str] = []
for s in sentences:
    parts.extend(_word_split(s) if len(s) > MAX_CHARS else [s])

chunk = ''
for part in parts:
    if chunk and len(chunk) + 1 + len(part) > MAX_CHARS:
        print(chunk)
        chunk = part
    elif chunk:
        chunk = chunk + ' ' + part
    else:
        chunk = part

if chunk:
    print(chunk)
