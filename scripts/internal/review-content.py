#!/usr/bin/env python3
"""Comprehensive content review using Gemini.

For every blog post and project page, this script:
  1. Parses frontmatter to extract repo, url, and metadata
  2. Fetches repo README via GitHub API (if repo is set)
  3. Reads the existing transcript QA output (if present)
  4. Runs Gemini (gemini-3.1-flash-lite-preview) to:
     - Review correctness, comprehensiveness, completeness
     - Propose blog post revisions
     - Propose a corrected synthesis script (text for TTS)
  5. Saves structured output to transcripts/review/<slug>.md

Usage:
    python scripts/internal/review-content.py                    # all content
    python scripts/internal/review-content.py afterwords         # one slug
    python scripts/internal/review-content.py --list             # show items and exit
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
SITE = Path("/Users/adrian/repos/adrianwedd.com/src/content")
BLOG = SITE / "blog"
PROJ = SITE / "projects"
QA_DIR = REPO / "transcripts" / "qa"
QA_MANIFEST = QA_DIR / "content-video-map.json"
OUT_DIR = REPO / "transcripts" / "review"

GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
CONTENT_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
GITHUB_NWO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")

PROMPT_TEMPLATE = """\
You are a technical editor reviewing AI-generated content for a personal website.

## Your task

Review the BLOG/PROJECT CONTENT below against:
1. The SOURCE REPO README (authoritative implementation details)
2. The EXISTING QA NOTES (known NLM hallucinations from the audio narration)

Return only a JSON object in this shape:
{
  "post_ok": false,
  "blog_post_revisions": [
    {
      "change": "what to change -- be precise, quote the existing text",
      "to": "the corrected/improved text",
      "reason": "correctness error / missing detail / outdated / incomplete"
    }
  ],
  "synthesis_script": "complete narration script"
}

If the post is accurate and complete, use "post_ok": true and an empty
"blog_post_revisions" array.

The synthesis_script must be a complete, clean narration script (2-4 minutes
when spoken, ~350-550 words) for this content -- the text that will be voiced
using TTS to replace the NLM-generated audio.

Requirements:
- Factually accurate and grounded entirely in the source material
- Written in second-person conversational style ("You're looking at...", "Here's what this means...")
- Covers: what the project/post is, the problem it solves, key technical details, real outcomes/results
- No invented details, no padding, no filler phrases like "let's dive in"
- Plain prose only — no markdown, no bullet points, no headers
- End with a single clear call to action linking to the site

---

## CONTENT SLUG
{slug}

## BLOG/PROJECT CONTENT
{content}

## SOURCE REPO README
{readme}

## EXISTING QA NOTES (NLM hallucinations already identified)
{qa_notes}
"""


def validate_slug(slug: str) -> str:
    if not CONTENT_SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid content slug: {slug!r}")
    return slug


def validate_video_id(video_id: str) -> str:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError(f"invalid YouTube video ID: {video_id!r}")
    return video_id


def scalar_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def minimal_env(extra: tuple[str, ...] = ()) -> dict[str, str]:
    # PATH is hardcoded to prevent caller-controlled PATH from shadowing tools.
    # /opt/homebrew first since this repo is Apple Silicon-only (per CLAUDE.md).
    # HOME is inherited because `gh` and `gemini` look up auth/config under it
    # (~/.config/gh, ~/.gemini). Threat model: same-user local dev shell. Do
    # NOT run this script in untrusted CI without overriding HOME to a sandbox.
    env = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", "C"),
    }
    for key in extra:
        val = os.environ.get(key)
        if val:
            env[key] = val
    return {k: v for k, v in env.items() if v}


def sanitize_prompt_content(value: str, limit: int | None = None) -> str:
    """Encode untrusted markdown/README/QA content as inert JSON string data."""
    if limit is not None:
        value = value[:limit]
    value = value.replace("\x00", "")
    return json.dumps(value, ensure_ascii=False)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as e:
        print(f"WARNING: could not fsync directory {path.parent}: {e}", file=sys.stderr)


def run_with_timeout(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    p = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = p.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait()
        raise
    return subprocess.CompletedProcess(args, p.returncode, stdout, stderr)


def extract_gemini_text(output: str) -> str:
    """Extract model text from Gemini CLI JSON output."""
    text = output.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        raise ValueError("Gemini JSON output had unexpected top-level type")
    for key in ("response", "text", "output", "content", "result"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(parts, list):
            joined = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            if joined.strip():
                return joined.strip()
    raise ValueError("Gemini JSON output did not contain model text")


def parse_model_json(text: str) -> object:
    """Parse a JSON-only model response, allowing fenced JSON as a fallback."""
    stripped = text.strip()
    match = re.match(r"\A```(?:json)?\s*(.*?)\s*```\s*\Z", stripped, re.DOTALL)
    if match:
        stripped = match.group(1).strip()
    return json.loads(stripped)


# LLM output is treated as untrusted. We validate structure but cannot prevent
# semantic prompt injection -- downstream consumers must treat the output as
# content from an untrusted source.
def validate_review_response(output: str) -> str:
    text = extract_gemini_text(output)
    if not text:
        raise ValueError("Gemini returned no output")
    try:
        payload = parse_model_json(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini response was not valid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError("Gemini response JSON must be an object")
    post_ok = payload.get("post_ok")
    revisions = payload.get("blog_post_revisions")
    script = payload.get("synthesis_script")
    if not isinstance(post_ok, bool) or not isinstance(revisions, list):
        raise ValueError("Gemini response failed review JSON validation")
    if not isinstance(script, str) or not script.strip():
        raise ValueError("Gemini response missing synthesis_script")
    if post_ok and revisions:
        raise ValueError("Gemini response cannot set post_ok with revisions")
    if not post_ok and not revisions:
        raise ValueError("Gemini response must include revisions or set post_ok")

    lines = ["### A) BLOG POST REVISIONS"]
    if post_ok:
        lines.append("POST OK")
    else:
        for i, revision in enumerate(revisions):
            if not isinstance(revision, dict):
                raise ValueError(f"Gemini revision {i} must be an object")
            change = revision.get("change")
            to = revision.get("to")
            reason = revision.get("reason")
            if not all(isinstance(v, str) and v.strip() for v in (change, to, reason)):
                raise ValueError(f"Gemini revision {i} is missing required text fields")
            for field_name, value in (
                ("change", change),
                ("to", to),
                ("reason", reason),
            ):
                if re.search(r"[\n\r\f\v\x85  ]", value):
                    raise ValueError(f"Gemini revision {i} field {field_name} must be single-line")
            lines.extend(
                [
                    f"CHANGE: {change.strip()}",
                    f"TO: {to.strip()}",
                    f"REASON: {reason.strip()}",
                    "",
                ]
            )
    lines.extend(["", "### B) SYNTHESIS SCRIPT", script.strip()])
    body = "\n".join(lines).strip()
    return body


def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter as a dict."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = text[3:end]

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(fm)
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        pass
    except Exception:
        return {}

    result: dict = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    for line in fm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_key and current_list is not None and stripped.startswith("- "):
            current_list.append(stripped[2:].strip().strip('"').strip("'"))
            continue
        current_key = None
        current_list = None
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if val == "":
            result[key] = ""
            current_key = key
            current_list = []
            result[key] = current_list
        elif val.startswith("[") and val.endswith("]"):
            try:
                result[key] = json.loads(val.replace("'", '"'))
            except json.JSONDecodeError:
                result[key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
        else:
            result[key] = val.strip('"').strip("'")
    return result


def fetch_readme(repo_url: str) -> str:
    """Fetch README from a GitHub repo via gh API."""
    if not repo_url:
        return "(no repo)"
    # Normalise: https://github.com/org/repo → org/repo
    match = re.search(r"github\.com/([^/]+/[^/\s#?]+)", repo_url)
    if not match:
        return f"(unrecognised repo URL: {repo_url})"
    nwo = match.group(1).rstrip("/")
    if ".." in nwo:
        raise ValueError(f"invalid repo path: {nwo}")
    if not GITHUB_NWO_RE.fullmatch(nwo):
        raise ValueError(f"invalid repo path: {nwo}")
    result = run_with_timeout(
        ["gh", "api", f"repos/{nwo}/readme"],
        env=minimal_env(("GH_TOKEN", "GITHUB_TOKEN")),
    )
    if result.returncode != 0:
        return f"(could not fetch README: {result.stderr.strip()[:200]})"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return f"(invalid GitHub API JSON: {e})"
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
        return "(GitHub API response missing README content)"
    try:
        return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"(README decode error: {e})"


def load_qa_notes(slug: str, frontmatter: dict) -> str:
    """Load QA notes only from an explicit video_id mapping."""
    # Do not infer video mappings from titles or slug words: near-match guesses can
    # attach hallucination notes to the wrong content item. Content frontmatter is
    # preferred; the sidecar manifest is only an explicit fallback for files that
    # cannot carry a video_id field yet.
    video_id = scalar_text(frontmatter.get("video_id", "")).strip()
    if not video_id and QA_MANIFEST.exists():
        try:
            manifest = json.loads(QA_MANIFEST.read_text())
        except json.JSONDecodeError:
            manifest = {}
        if isinstance(manifest, dict):
            video_id = scalar_text(manifest.get(slug, "")).strip()
    if not video_id:
        print(f"WARNING: no video_id mapping for slug={slug!r}; skipping QA notes", file=sys.stderr)
        return "(no QA notes)"
    vid = validate_video_id(video_id)
    qa_path = QA_DIR / f"{vid}.txt"
    if not qa_path.exists():
        return "(no QA notes)"
    return qa_path.read_text()


def collect_items() -> list[dict]:
    """Return list of {slug, path, kind, frontmatter, content}."""
    items = []
    for path in sorted(BLOG.glob("*.md")) + sorted(PROJ.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        kind = "blog" if path.parent == BLOG else "project"
        slug = validate_slug(path.stem.removesuffix("-post"))
        items.append({"slug": slug, "path": path, "kind": kind, "fm": fm, "content": text})
    return items


def run_gemini_review(slug: str, content: str, readme: str, qa_notes: str) -> str:
    validate_slug(slug)
    prompt = PROMPT_TEMPLATE.format(
        slug=slug,
        content=sanitize_prompt_content(content, 6000),  # cap to avoid token limits
        readme=sanitize_prompt_content(readme, 4000),
        qa_notes=sanitize_prompt_content(qa_notes, 2000),
    )
    result = run_with_timeout(
        ["gemini", "--model", GEMINI_MODEL, "--output-format", "json", "-p", prompt],
        env=minimal_env(("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    )
    if result.returncode != 0:
        raise RuntimeError(f"gemini failed: {result.stderr.strip()[:500] or result.returncode}")
    return validate_review_response(result.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="Specific slug(s) to review")
    ap.add_argument("--list", action="store_true", help="List all items and exit")
    args = ap.parse_args()

    items = collect_items()

    if args.list:
        for it in items:
            repo = scalar_text(it["fm"].get("repo", ""))
            print(f"  {it['kind']:7s}  {it['slug']:50s}  {repo}")
        print(f"\n{len(items)} items total")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        requested_slugs = [validate_slug(slug) for slug in args.slugs]
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if requested_slugs:
        items = [it for it in items if it["slug"] in requested_slugs or it["path"].stem in requested_slugs]

    total = len(items)
    print(f"Reviewing {total} items with {GEMINI_MODEL}...\n")
    failed = 0

    for i, it in enumerate(items, 1):
        slug = it["slug"]
        out_path = OUT_DIR / f"{slug}.md"

        if out_path.exists():
            print(f"[{i}/{total}] {slug}  — already reviewed, skipping")
            continue

        repo_url = scalar_text(it["fm"].get("repo", ""))
        live_url = scalar_text(it["fm"].get("url", ""))

        print(f"[{i}/{total}] {it['kind']:7s}  {slug}", flush=True)

        try:
            readme = fetch_readme(repo_url) if repo_url else "(no repo)"
            qa_notes = load_qa_notes(slug, it["fm"])
            review = run_gemini_review(slug, it["content"], readme, qa_notes)
        except subprocess.TimeoutExpired:
            review = "TIMEOUT — re-run to retry"
            failed += 1
        except Exception as e:
            review = f"ERROR: {e}"
            failed += 1

        header = (
            f"# Review: {slug}\n\n"
            f"**Kind:** {it['kind']}  \n"
            f"**Repo:** {repo_url or '(none)'}  \n"
            f"**URL:** {live_url or '(none)'}  \n\n"
            f"---\n\n"
        )
        atomic_write_text(out_path, header + review + "\n")

        # One-line preview
        first = next((ln for ln in review.splitlines() if ln.strip()), "")
        print(f"  → {first[:120]}")
        print()

    print(f"Reviews saved to: {OUT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
