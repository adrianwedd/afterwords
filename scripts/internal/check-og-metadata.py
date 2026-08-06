#!/usr/bin/env python3
"""Verify docs/index.html OpenGraph metadata stays in sync with reality.

Catches the failure mode where the demo site grows or shrinks but og:description
isn't updated, leading to stale Facebook/Twitter/LinkedIn link previews that
are technically wrong AND get cached for days. Exits non-zero if a mismatch
is found, so it's safe to wire into CI.

Checks performed:
  - og:description claims a voice count that matches the actual gallery size
  - og:url is canonical (matches the deployed Pages URL)
  - og:image exists at the claimed path
  - twitter:card and twitter:image are present
  - All four <meta property="og:*"> required fields are present
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
INDEX = REPO / "docs" / "index.html"
GALLERY = REPO / "docs" / "audio"
EXPECTED_OG_URL = "https://adrianwedd.github.io/afterwords/"

# Required OG/Twitter tags. Title and description are checked separately.
REQUIRED_OG = ("og:title", "og:description", "og:type", "og:url", "og:image")
REQUIRED_TW = ("twitter:card", "twitter:image")


def parse_meta(html: str) -> dict[str, str]:
    """Extract <meta property|name=...> content into a flat dict."""
    pattern = re.compile(
        r'<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)"', re.IGNORECASE
    )
    return {m.group(1): m.group(2) for m in pattern.finditer(html)}


def gallery_voice_count() -> int:
    return len(list(GALLERY.glob("*.mp3")))


def repo_voice_count() -> int:
    """Count git-tracked voice profiles so CI and local agree (ignores gitignored files)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "voices/*.json"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if lines:
            return len(lines)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # Fallback for non-git environments (downloaded tarballs).
    return len(list((REPO / "voices").glob("*.json")))


def main() -> int:
    if not INDEX.exists():
        print(f"error: {INDEX} not found", file=sys.stderr)
        return 2

    html = INDEX.read_text()
    meta = parse_meta(html)
    issues: list[str] = []

    # 1. Required tags present
    for tag in (*REQUIRED_OG, *REQUIRED_TW):
        if tag not in meta or not meta[tag].strip():
            issues.append(f"missing or empty meta: {tag}")

    # 2. Voice count claim in og:description is consistent with voices/*.json.
    # og:description may use an approximate "N+" form (e.g. "110+ voices") meaning
    # "at least N". An exact "N voices" means exactly N. We always compare against
    # the voice profile count (voices/*.json), not the demo gallery (docs/audio/*.mp3),
    # since the OG headline advertises the full library, not just the curated demos.
    desc = meta.get("og:description", "")
    actual_count = repo_voice_count()
    claim_match = re.search(r"(\d+)(\+)?\s+voices?", desc, re.IGNORECASE)
    if claim_match:
        claimed = int(claim_match.group(1))
        is_approx = claim_match.group(2) == "+"
        if is_approx:
            if actual_count < claimed:
                issues.append(
                    f"og:description claims {claimed}+ voices but voices/ only has {actual_count}"
                )
        else:
            if claimed != actual_count:
                issues.append(
                    f"og:description claims {claimed} voices but voices/ has {actual_count}"
                )
    else:
        issues.append(
            "og:description doesn't mention a voice count — "
            "add 'N voices' or 'N+ voices' so this drift check stays meaningful"
        )

    # 3. Canonical URL
    if meta.get("og:url") not in (EXPECTED_OG_URL, EXPECTED_OG_URL.rstrip("/")):
        issues.append(
            f"og:url is {meta.get('og:url')!r}, expected {EXPECTED_OG_URL!r}"
        )

    # 4. og:image points at a file that exists in docs/
    img_url = meta.get("og:image", "")
    if img_url:
        # Strip the deployed prefix to get a repo-relative path
        relative = img_url.replace(EXPECTED_OG_URL, "")
        img_path = REPO / "docs" / relative
        if not img_path.exists():
            issues.append(
                f"og:image points to {img_url} but {img_path} not found in repo"
            )

    # 5. Visible on-page counts must agree with the tracked gallery too — the
    # 2026-08-06 QA round found the hero ("98 voices included") and backends
    # section title ("281 voice profiles") had drifted for months because only
    # og:description was checked. Same "N+" approx semantics as check 2.
    for label, pattern in (
        ("hero subtitle", r'class="hero-sub">[^<]*?(\d+)(\+)?\s+voices'),
        ("backends section title", r'class="section-title">[^<]*?(\d+)(\+)?\s+voice profiles'),
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if not m:
            continue  # section reworded to drop the count — nothing to drift
        claimed = int(m.group(1))
        if m.group(2) == "+":
            if actual_count < claimed:
                issues.append(
                    f"{label} claims {claimed}+ voices but voices/ only has {actual_count}"
                )
        elif claimed != actual_count:
            issues.append(
                f"{label} claims {claimed} voices but voices/ has {actual_count}"
            )

    # 6. Same-as title — a Twitter card without title is fine if og:title exists,
    # but flag if og:title and twitter:title both exist and differ.
    if "twitter:title" in meta and meta["twitter:title"] != meta.get("og:title"):
        issues.append(
            f"twitter:title {meta['twitter:title']!r} differs from "
            f"og:title {meta.get('og:title')!r}"
        )

    # Output
    if issues:
        print(f"OG metadata drift detected ({len(issues)} issue(s)):", file=sys.stderr)
        for i in issues:
            print(f"  ✗ {i}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "After fixing, force a Facebook re-scrape so the cached preview updates:",
            file=sys.stderr,
        )
        print("    bash scripts/internal/fb-reindex.sh", file=sys.stderr)
        return 1

    demo_count = gallery_voice_count()
    print(f"✓ OG metadata clean — {actual_count} voice profiles, {demo_count} demo clips, all required tags present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
