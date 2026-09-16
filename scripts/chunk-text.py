"""Split text into sentence-boundary chunks for TTS synthesis.

Thin shim, NOT a second implementation. The splitting logic lives in the
repo-root `chunks.py`; every surface loads that file.

Kept at scripts/chunk-text.py for backwards compatibility: setup.sh copies it to
~/.claude/hooks/chunk-text.py, where the Claude/Codex workers invoke it, and
tests/test_cli_expansion.py pins its location.

Repo root resolution: the `_REPO_HINT` stamp (setup.sh rewrites it when
installing into ~/.claude/hooks/), then $AFTERWORDS_REPO, then the parent of
this file, then a walk up for a directory holding chunks.py.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_REPO_HINT = ""
_CANONICAL_NAME = "chunks.py"


def _repo_root() -> Path | None:
    for candidate in (
        Path(_REPO_HINT).expanduser() if _REPO_HINT else None,
        Path(os.environ["AFTERWORDS_REPO"]).expanduser() if os.environ.get("AFTERWORDS_REPO") else None,
        Path(__file__).resolve().parent.parent,
    ):
        if candidate and (candidate / _CANONICAL_NAME).is_file():
            return candidate
    for directory in Path(__file__).resolve().parents:
        if (directory / _CANONICAL_NAME).is_file():
            return directory
    return None


def _load():
    root = _repo_root()
    if root is None:
        raise RuntimeError(
            "chunk-text.py: canonical chunks.py not found; refusing to fall back "
            "to a different splitter (that is how the surfaces drifted before)"
        )
    canonical = root / _CANONICAL_NAME
    spec = importlib.util.spec_from_file_location("afterwords_chunks", canonical)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"chunk-text.py: cannot load {canonical}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    for chunk in _load().chunk_text(sys.stdin.read().strip()):
        print(chunk)
