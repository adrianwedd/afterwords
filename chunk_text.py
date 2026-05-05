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

chunk = ''
for sentence in sentences:
    if chunk and len(chunk) + 1 + len(sentence) > MAX_CHARS:
        print(chunk)
        chunk = sentence
    elif chunk:
        chunk = chunk + ' ' + sentence
    else:
        chunk = sentence

if chunk:
    print(chunk)
