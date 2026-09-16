"""Split text into sentence-boundary chunks for TTS synthesis.

Importable module form of the canonical chunker: the splitting logic lives in
the repo-root `chunks.py` and this file only exposes it under the historical
module name, so `from chunk_text import chunk_text` keeps working.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CANONICAL = Path(__file__).resolve().parent / "chunks.py"

if not _CANONICAL.is_file():
    raise RuntimeError(f"chunk_text.py: canonical chunker missing at {_CANONICAL}")

_spec = importlib.util.spec_from_file_location("afterwords_chunks", _CANONICAL)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"chunk_text.py: cannot load {_CANONICAL}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export the canonical surface.
CHUNK_CHARS = _mod.CHUNK_CHARS
chunk_text = _mod.chunk_text


if __name__ == "__main__":
    for chunk in chunk_text(sys.stdin.read().strip()):
        print(chunk)
