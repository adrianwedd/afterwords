#!/usr/bin/env python3
"""QA NLM-generated YouTube transcripts against source blog/project content.

For each video, finds the matching source markdown file(s), then runs
`gemini -p` to identify hallucinations and propose replacement text for
voice synthesis.

Usage:
    python scripts/qa-transcripts.py                    # all videos
    python scripts/qa-transcripts.py pLbwFRqgF6s        # one video by ID
    python scripts/qa-transcripts.py --list             # show mapping and exit
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
TRANSCRIPTS = REPO / "transcripts" / "youtube"
TITLES_FILE = TRANSCRIPTS / "video-titles.tsv"
QA_OUT = REPO / "transcripts" / "qa"
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

SITE = Path("/Users/adrian/repos/adrianwedd.com/src/content")
BLOG = SITE / "blog"
PROJ = SITE / "projects"

# video title → source content files (relative to SITE)
# Where a video has both a project page and a blog post, list both.
CONTENT_MAP: dict[str, list[Path]] = {
    "Wolf Clan Zen Do Kai Hub":             [PROJ / "wolf-clan-hub.md"],
    "Why Demonstrated Risk Is Ignored":     [PROJ / "why-demonstrated-risk-is-ignored.md", BLOG / "why-demonstrated-risk-is-ignored-post.md"],
    "VERITAS":                              [PROJ / "veritas.md"],
    "This Wasn't in the Brochure":          [PROJ / "this-wasnt-in-the-brochure.md", BLOG / "this-wasnt-in-the-brochure-post.md"],
    "TEL3SIS":                              [PROJ / "tel3sis.md"],
    "Strategic Acquisitions":               [PROJ / "strategic-acquisitions.md"],
    "Squishmallowdex":                      [PROJ / "squishmallowdex.md"],
    "SPARK":                                [PROJ / "spark.md"],
    "Space Weather":                        [PROJ / "space-weather.md"],
    "rlm-mcp":                              [PROJ / "rlm-mcp.md"],
    "Personal Agentic Operating System":    [PROJ / "personal-agentic-operating-system.md"],
    "ordr.fm":                              [PROJ / "ordr-fm.md"],
    "orbitr":                               [PROJ / "orbitr.md"],
    "NotebookLM Automation":               [PROJ / "notebooklm-automation.md", BLOG / "the-notebooklm-pipeline-post.md"],
    "Failure First":                        [PROJ / "failure-first.md"],
    "NeuroConnect":                         [PROJ / "neuroconnect.md"],
    "ModelAtlas":                           [PROJ / "modelatlas.md"],
    "Lunar Tools Prototypes":               [PROJ / "lunar-tools-prototypes.md"],
    "Latent Self":                          [PROJ / "latent-self.md"],
    "Home Assistant Obsidian":              [PROJ / "home-assistant-obsidian.md"],
    "Grid 2.0":                             [PROJ / "grid2.md"],
    "Freedom Engine":                       [PROJ / "freedom-engine.md"],
    "Footnotes at the Edge of Reality":     [PROJ / "footnotes-at-the-edge-of-reality.md", BLOG / "footnotes-at-the-edge-of-reality-post.md"],
    "EMDR Agent":                           [PROJ / "emdr-agent.md"],
    "Dx0":                                  [PROJ / "dx0.md"],
    "dodgylegally":                         [PROJ / "dodgylegally.md"],
    "Cygnet":                               [PROJ / "cygnet.md"],
    "Living CV":                            [PROJ / "cv.md"],
    "The Robot That Refuses to Give Orders":[BLOG / "the-robot-that-refuses-to-give-orders-post.md"],
    "Before the Words Existed":             [PROJ / "before-the-words-existed.md"],
    "Auditory Spiral":                      [PROJ / "auditory-spiral.md", BLOG / "the-resonant-fringe-post.md"],
    "Agentic Index":                        [PROJ / "agentic-index.md"],
    "Afterwords":                           [PROJ / "afterwords.md", BLOG / "afterwords-post.md"],
    "Afterglow Engine":                     [PROJ / "afterglow-engine.md"],
    "Zero-Build Web Development":           [BLOG / "zero-build-web-development-post.md", BLOG / "building-a-personal-site-in-2026-post.md"],
    "Why I Build in Public":                [BLOG / "why-i-build-in-public-post.md"],
    "When AI Systems Talk to Each Other, Safety Breaks Down": [BLOG / "when-ai-systems-talk-safety-breaks-post.md"],
    "Voice Cloning with Qwen3-TTS and MLX on Apple Silicon":  [BLOG / "voice-cloning-qwen3-tts-mlx-post.md", BLOG / "giving-a-robot-three-voices-post.md"],
    "The Resonant Fringe":                  [BLOG / "the-resonant-fringe-post.md"],
    "The Organismic Prophecy":              [BLOG / "the-organismic-prophecy-post.md"],
    "The Organismic Line: Where Predictive Processing Stops Being a Metaphor": [BLOG / "the-organismic-line-post.md"],
    "The NotebookLM Pipeline":              [BLOG / "the-notebooklm-pipeline-post.md"],
    "The Mitigation Gap":                   [BLOG / "the-mitigation-gap-post.md"],
    "The Legal AI Trust Deficit":           [BLOG / "the-legal-ai-trust-deficit-post.md"],
    "The Failure First Team":               [BLOG / "the-failure-first-team-post.md"],
    "The Cognitive Cage: Humanoid Robot Fatality Risk": [BLOG / "the-cognitive-cage-post.md"],
    "The AI Productivity J-Curve: Why Most Enterprise AI Fails": [BLOG / "the-ai-productivity-j-curve-post.md"],
    "Safety-First Therapeutic AI":          [BLOG / "safety-first-therapeutic-ai-post.md"],
    "Reconciling the Great Divergence":     [BLOG / "reconciling-the-great-divergence-post.md"],
    "The Post-Model Era":                   [BLOG / "beyond-context-windows-post.md"],
    "Connection Before Direction":          [BLOG / "non-coercive-design-post.md"],
    "Multi-Agent Safety Is the New Supply Chain Security": [BLOG / "multi-agent-supply-chain-post.md"],
    "Beyond Optimisation: The Emergence of Learning Mechanics as a Formal Science": [BLOG / "learning-mechanics-deep-learning-theory-post.md"],
    "Jailbreak Archaeology: 4 Years of Broken Promises":   [BLOG / "jailbreak-archaeology-post.md"],
    "How to Read a Safety Claim":           [BLOG / "how-to-read-a-safety-claim-post.md"],
    "Building in the Open":                 [BLOG / "why-i-build-in-public-post.md"],
    "Giving a Robot Three Voices":          [BLOG / "giving-a-robot-three-voices-post.md"],
    "Getting Google Nest Cameras Into Frigate NVR": [BLOG / "getting-google-nest-cameras-into-frigate-nvr-post.md"],
    "The Economics of Inadequate Safety":   [BLOG / "economics-of-inadequate-safety-post.md"],
    "Building a Personal Site in 2026":     [BLOG / "building-a-personal-site-in-2026-post.md"],
    "Beyond Context Windows":               [BLOG / "beyond-context-windows-post.md"],
    "Architectural Safety: The General Principle": [BLOG / "architectural-safety-post.md"],
    "AI Nationalism and the Fracturing Digital Order": [BLOG / "ai-nationalism-post.md"],
    "Afterwords: Completing the Voice Loop in Claude Code": [PROJ / "afterwords.md", BLOG / "afterwords-post.md"],
    "Adversarial Poetry: When Rhyme Bypasses Reason": [BLOG / "adversarial-poetry-as-jailbreak-post.md"],
    "120 Models, 18,176 Prompts: What We Found": [BLOG / "120-models-18k-prompts-post.md"],
}

GEMINI_PROMPT_TEMPLATE = """You are QA-ing an AI-generated audio narration (produced by NotebookLM) against its authoritative source content.

## Source content (ground truth)

{source}

## Transcript of NLM-generated narration (word-level JSON converted to text with timestamps)

{transcript_text}

## Your task

1. Identify every factual claim in the transcript that contradicts or is unsupported by the source: wrong stats, wrong dates, wrong names, invented details, misattributed quotes, inflated or deflated numbers, confabulated context, or anything the source simply doesn't say.

2. Return only a JSON object in this shape:
   {{"status":"clean","issues":[]}}
   or:
   {{"status":"issues","issues":[{{"timestamp_seconds":12.3,"transcript":"exact words from transcript","source_says":"what the source actually says, or not mentioned","replacement":"corrected sentence or phrase in the same narrative style"}}]}}

3. If the transcript is factually clean relative to the source, use status "clean" and an empty issues array.

Be strict. NLM often invents plausible-sounding details. Flag anything that can't be verified in the source.
"""


def validate_video_id(video_id: str) -> str:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError(f"invalid YouTube video ID: {video_id!r}")
    return video_id


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
    """Encode untrusted prompt data as inert JSON string content."""
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
def validate_gemini_response(output: str) -> str:
    model_text = extract_gemini_text(output)
    try:
        payload = parse_model_json(model_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini response was not valid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError("Gemini response JSON must be an object")
    status = payload.get("status")
    issues = payload.get("issues")
    if status == "clean" and issues == []:
        return "CLEAN"
    if status != "issues" or not isinstance(issues, list) or not issues:
        raise ValueError("Gemini response failed QA JSON validation")

    lines: list[str] = []
    for i, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ValueError(f"Gemini issue {i} must be an object")
        timestamp = issue.get("timestamp_seconds")
        transcript = issue.get("transcript")
        source_says = issue.get("source_says")
        replacement = issue.get("replacement")
        if not isinstance(timestamp, (int, float)) or timestamp < 0:
            raise ValueError(f"Gemini issue {i} has invalid timestamp_seconds")
        if not all(isinstance(v, str) and v.strip() for v in (transcript, source_says, replacement)):
            raise ValueError(f"Gemini issue {i} is missing required text fields")
        for field_name, value in (
            ("transcript", transcript),
            ("source_says", source_says),
            ("replacement", replacement),
        ):
            if re.search(r"[\n\r\f\v\x85  ]", value):
                raise ValueError(f"Gemini issue {i} field {field_name} must be single-line")
        lines.extend(
            [
                f"ISSUE at ~{timestamp:g}s: \"{transcript.strip()}\"",
                f"SOURCE SAYS: {source_says.strip()}",
                f"REPLACEMENT: \"{replacement.strip()}\"",
                "",
            ]
        )
    body = "\n".join(lines).strip()
    return body


def load_titles() -> dict[str, str]:
    """Returns {video_id: title}."""
    result = {}
    for line in TITLES_FILE.read_text().strip().splitlines():
        if "\t" in line:
            vid, title = line.split("\t", 1)
            vid = vid.strip()
            validate_video_id(vid)
            result[vid] = title.strip()
    return result


def transcript_to_text(path: Path) -> str:
    """Convert word-level JSON to readable text with periodic timestamps."""
    try:
        words = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid transcript JSON in {path.name}: {e}") from e
    if not isinstance(words, list):
        raise ValueError(f"invalid transcript JSON in {path.name}: expected list")
    parts = []
    for i, w in enumerate(words):
        if not isinstance(w, dict) or "start" not in w or "word" not in w:
            raise ValueError(f"invalid transcript word entry in {path.name} at index {i}")
        try:
            start = float(w["start"])
        except (TypeError, ValueError) as e:
            raise ValueError(f"invalid transcript start in {path.name} at index {i}") from e
        if i % 50 == 0:
            mins = int(start // 60)
            secs = int(start % 60)
            parts.append(f"[{mins}:{secs:02d}]")
        parts.append(str(w["word"]))
    return " ".join(parts)


def source_content(title: str) -> str:
    paths = CONTENT_MAP.get(title, [])
    if not paths:
        return "(no source content mapped)"
    chunks = []
    for p in paths:
        if p.exists():
            chunks.append(f"### {p.name}\n\n{p.read_text()}")
        else:
            chunks.append(f"### {p.name}\n\n(file not found)")
    return "\n\n---\n\n".join(chunks)


def run_qa(video_id: str, title: str) -> str:
    validate_video_id(video_id)
    transcript_path = TRANSCRIPTS / f"{video_id}.json"
    if not transcript_path.exists():
        return f"SKIP: no transcript for {video_id}"

    transcript_text = transcript_to_text(transcript_path)
    src = source_content(title)

    prompt = GEMINI_PROMPT_TEMPLATE.format(
        source=sanitize_prompt_content(src),
        transcript_text=sanitize_prompt_content(transcript_text),
    )

    result = run_with_timeout(
        ["gemini", "--model", GEMINI_MODEL, "--output-format", "json", "-p", prompt],
        env=minimal_env(("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    )
    output = result.stdout.strip()
    if result.returncode != 0:
        raise RuntimeError(f"gemini failed: {result.stderr.strip()[:500] or result.returncode}")
    if not output:
        raise RuntimeError("gemini returned no output")
    return validate_gemini_response(output)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_ids", nargs="*", help="Specific video ID(s) to QA (default: all)")
    ap.add_argument("--list", action="store_true", help="Show ID→title→source mapping and exit")
    args = ap.parse_args()

    titles = load_titles()

    if args.list:
        for vid, title in titles.items():
            sources = [p.name for p in CONTENT_MAP.get(title, [])]
            mapped = ", ".join(sources) if sources else "(UNMAPPED)"
            print(f"{vid}  {title!r:60s}  {mapped}")
        return 0

    QA_OUT.mkdir(parents=True, exist_ok=True)

    try:
        target_ids = [validate_video_id(vid) for vid in (args.video_ids if args.video_ids else list(titles.keys()))]
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    total = len(target_ids)
    failed = 0

    for i, vid in enumerate(target_ids, 1):
        title = titles.get(vid, "(unknown)")
        out_path = QA_OUT / f"{vid}.txt"

        if out_path.exists():
            print(f"[{i}/{total}] {vid}  {title!r}  — already QA'd, skipping")
            continue

        print(f"[{i}/{total}] {vid}  {title!r} ...", flush=True)
        try:
            result = run_qa(vid, title)
        except subprocess.TimeoutExpired:
            result = "TIMEOUT"
            failed += 1
        except Exception as e:
            result = f"ERROR: {e}"
            failed += 1

        atomic_write_text(out_path, f"VIDEO: {vid}\nTITLE: {title}\n\n{result}\n")
        # Print a preview
        preview = result[:300].replace("\n", " ")
        print(f"  → {preview}{'...' if len(result) > 300 else ''}")
        print()

    print(f"QA outputs in: {QA_OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
