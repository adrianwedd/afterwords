"""Strip markdown formatting for cleaner TTS output.

Thin shim, NOT a second implementation. The canonical rules live in the
repo-root `strip_markdown.py`; every surface loads that file. This shim exists
because setup.sh copies it to ~/.claude/hooks/strip-markdown.py, where the
Claude/Codex/Gemini/AGy/Cursor hooks invoke it by that historical path.

Resolution order for the canonical module:
  1. `$AFTERWORDS_REPO/strip_markdown.py` — explicit override.
  2. Walk up from this file for a directory holding `strip_markdown.py`
     (works from a repo checkout at any depth; no hardcoded parent index).
  3. `~/.claude/hooks/strip-markdown.py` — a *shim* installed there by
     setup.sh, which resolves back here. Only used if it accepts max_chars,
     so an older pre-shim copy cannot silently swap in different TTS rules.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import warnings
from pathlib import Path

_SIBLING = "strip_markdown.py"

# Repo root for this deployment. This file is a shim, so the walk-up below only
# finds the repo when the shim lives inside a checkout; setup.sh rewrites this
# line with the real repo path when it installs the copy into ~/.claude/hooks/,
# which is how the Claude/Codex/Gemini/AGy/Cursor hooks stay canonical.
_REPO_HINT = ""


def _walk_up(start: Path) -> Path | None:
    """Find a directory at or above `start` containing the canonical module."""
    for directory in [start, *start.parents]:
        candidate = directory / _SIBLING
        if candidate.is_file():
            return candidate
    return None


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("afterwords_strip_markdown", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    if _REPO_HINT:
        paths.append(Path(_REPO_HINT).expanduser() / _SIBLING)
    repo = os.environ.get("AFTERWORDS_REPO", "").strip()
    if repo:
        paths.append(Path(repo).expanduser() / _SIBLING)
    discovered = _walk_up(Path(__file__).resolve().parent)
    if discovered:
        paths.append(discovered)
    paths.append(Path.home() / ".claude" / "hooks" / "strip-markdown.py")
    # De-dupe, keep order.
    seen: set[Path] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def _resolve():
    """Return (callable, description) for the canonical strip_markdown."""
    for path in _candidate_paths():
        if not path.is_file():
            continue
        try:
            mod = _load_module(path)
        except Exception as exc:
            # Surface the degradation: silently reverting to a different rule
            # set is exactly how the two copies drifted apart before.
            warnings.warn(f"strip-markdown: cannot load {path}: {exc!r}", stacklevel=3)
            continue
        if mod is None:
            continue
        fn = getattr(mod, "strip_markdown", None)
        if not callable(fn):
            warnings.warn(f"strip-markdown: {path} has no callable strip_markdown", stacklevel=3)
            continue
        # Guard against an older copy whose signature would raise TypeError on
        # max_chars and thereby demote every caller to the fallback path.
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        accepts_max = "max_chars" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if not accepts_max and path.name == "strip-markdown.py":
            warnings.warn(
                f"strip-markdown: {path} is a legacy copy without max_chars; "
                f"run setup.sh to install the shim",
                stacklevel=3,
            )
            continue
        return fn, str(path)
    return None, ""


def strip_markdown(text: str, max_chars: int | None = None) -> str:
    """Strip markdown for TTS via the canonical repo implementation."""
    fn, source = _resolve()
    if fn is None:
        looked = "\n  ".join(str(p) for p in _candidate_paths())
        raise RuntimeError(
            "strip-markdown: no canonical strip_markdown.py found; refusing to "
            f"silently degrade to a different implementation. Looked in:\n  {looked}"
        )
    return fn(text, max_chars=max_chars)


def canonical_source() -> str:
    """Path the canonical implementation was loaded from ('' if unresolvable)."""
    _, source = _resolve()
    return source


if __name__ == "__main__":
    print(strip_markdown(sys.stdin.read()))
