"""Guard rail: OpenGraph metadata on docs/index.html stays in sync with reality.

If og:description claims "20 voices" but docs/audio/ has 25, Facebook caches
the wrong preview for days. This test fails fast so the operator catches drift
before pushing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check-og-metadata.py"


def test_og_metadata_in_sync_with_demo_gallery():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"OG metadata drift detected — fix docs/index.html:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
