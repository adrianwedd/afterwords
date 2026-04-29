#!/usr/bin/env python3
"""Audit voice profiles for transcript-vs-audio drift.

For each voices/*.json:
  - Re-transcribe the referenced WAV with faster-whisper
  - Compare against the JSON's reference_text
  - Flag drift: phantom text, truncation, silence gaps, impossible cps

Usage:
    python scripts/audit-voice-transcripts.py [--fix] [--voice NAME] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_VOICES = REPO / "voices"

# Heuristic thresholds
CPS_MAX = 22.0          # chars/sec; English natural speech ~14-17
SIM_MIN = 0.55          # SequenceMatcher ratio on normalized word lists
LEN_RATIO_MAX = 1.6     # ref_text words / whisper words; >1.6 = phantom canonical text
SILENCE_GAP_S = 1.5     # mid-clip gap that hurts conditioning
SILENCE_RMS = 0.005     # RMS threshold for silence (assumes ref WAVs are normalized to ±1.0)

# Issue codes that indicate a *text* problem (so --fix should rewrite reference_text).
# Audio-only issues (silence, missing-wav) are not fixable by editing text.
TEXT_ISSUE_PREFIXES = ("phantom", "low similarity", "impossibly fast", "empty whisper", "likely truncated")

# ANSI
RED = "\033[0;31m"; GRN = "\033[0;32m"; YLW = "\033[0;33m"
DIM = "\033[2m"; BLD = "\033[1m"; NC = "\033[0m"


@dataclass
class Finding:
    voice: str
    json_path: Path
    wav: str
    duration_s: float
    ref_text: str
    whisper_text: str
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def has_text_issue(self) -> bool:
        return any(any(i.startswith(p) for p in TEXT_ISSUE_PREFIXES) for i in self.issues)


def normalize(s: str) -> list[str]:
    out = []
    for tok in s.lower().split():
        tok = "".join(c for c in tok if c.isalnum() or c == "'")
        if tok:
            out.append(tok)
    return out


def safe_resolve(base: Path, ref: str) -> Path | None:
    """Resolve `ref` against `base`; reject anything that escapes `base`."""
    if not ref:
        return None
    candidate = (base / ref).resolve()
    base_resolved = base.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return None
    return candidate


def load_audio(path: Path):
    import soundfile as sf
    audio, sr = sf.read(str(path))
    if hasattr(audio, "ndim") and audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, sr


def detect_silence_gaps(audio, sr: int, win_s: float = 0.1) -> list[tuple[float, float]]:
    """Return mid-clip silence regions >= SILENCE_GAP_S as (start_s, end_s)."""
    import numpy as np
    win = max(1, int(sr * win_s))
    n = len(audio)
    gaps: list[tuple[float, float]] = []
    in_gap = False
    gap_start_w = 0
    for w in range(0, n, win):
        chunk = audio[w:w + win]
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        silent = rms < SILENCE_RMS
        if silent and not in_gap:
            in_gap = True
            gap_start_w = w
        elif not silent and in_gap:
            in_gap = False
            dur = (w - gap_start_w) / sr
            if dur >= SILENCE_GAP_S:
                gaps.append((gap_start_w / sr, w / sr))
    # Trailing gap that runs to end of file is treated as natural silence, not flagged.
    # Leading silence (start < 0.3s) is also natural; skip.
    return [(a, b) for (a, b) in gaps if a > 0.3]


def transcribe(wav_path: Path, model, lang: str | None) -> str:
    kwargs = {"language": lang} if lang else {}
    segments, _ = model.transcribe(str(wav_path), **kwargs)
    return " ".join(seg.text.strip() for seg in segments).strip()


def evaluate(profile: dict, ref_text: str, whisper_text: str, duration: float, audio_gaps: list[tuple[float, float]]) -> list[str]:
    issues: list[str] = []

    if not ref_text.strip():
        issues.append("empty reference_text")
        return issues

    if not whisper_text.strip():
        issues.append("empty whisper output (audio may be silent or unrecognized speech)")
        # Still run cps + silence checks; skip text comparisons
    else:
        ref_words = normalize(ref_text)
        wh_words = normalize(whisper_text)
        if wh_words:
            ratio = len(ref_words) / max(1, len(wh_words))
            if ratio > LEN_RATIO_MAX:
                issues.append(
                    f"phantom text suspected: transcript {len(ref_words)}w vs whisper {len(wh_words)}w "
                    f"(ratio {ratio:.2f})"
                )
        if ref_words and wh_words:
            sim = SequenceMatcher(None, ref_words, wh_words).ratio()
            if sim < SIM_MIN:
                issues.append(f"low similarity to whisper: {sim:.2f} (<{SIM_MIN})")

        # Truncation: ref_text's last word doesn't appear at the tail of whisper output.
        # Avoids the false-positive "ends mid-word" check that tripped on every
        # transcript without terminal punctuation.
        ref_words = normalize(ref_text)
        wh_words_full = normalize(whisper_text)
        if ref_words and wh_words_full:
            last_ref = ref_words[-1]
            last_three_wh = wh_words_full[-3:]
            ref_ends_with_letter = ref_text.rstrip()[-1:].isalpha()
            if ref_ends_with_letter and last_ref not in last_three_wh:
                # Whisper kept going past where ref_text stops, AND ref_text has no terminal
                # punctuation — strong signal of mid-word truncation.
                issues.append(f"likely truncated: last word '{last_ref}' not in whisper tail {last_three_wh}")

    # Char/sec
    if duration > 0:
        cps = len(ref_text) / duration
        if cps > CPS_MAX:
            issues.append(f"impossibly fast: {cps:.1f} cps (>{CPS_MAX})")

    for a, b in audio_gaps:
        issues.append(f"mid-clip silence: {a:.1f}-{b:.1f}s ({b-a:.1f}s)")

    return issues


def audit_one(json_path: Path, voices_dir: Path, whisper_cache: dict[Path, str], model) -> Finding:
    profile = json.loads(json_path.read_text())
    name = profile.get("name", json_path.stem)
    ref_audio = profile.get("reference_audio") or ""
    ref_text = profile.get("reference_text", "") or ""
    lang = profile.get("language", "en")  # default English; profile may override

    wav_path = safe_resolve(voices_dir, ref_audio)
    if wav_path is None or not wav_path.exists():
        f = Finding(name, json_path, ref_audio, 0.0, ref_text, "")
        if not ref_audio:
            f.issues.append("missing reference_audio field")
        elif wav_path is None:
            f.issues.append(f"reference_audio escapes voices/ or is invalid: {ref_audio}")
        else:
            f.issues.append(f"reference_audio file not found: {ref_audio}")
        return f

    audio, sr = load_audio(wav_path)
    duration = len(audio) / sr

    if wav_path not in whisper_cache:
        whisper_cache[wav_path] = transcribe(wav_path, model, lang)
    whisper_text = whisper_cache[wav_path]

    gaps = detect_silence_gaps(audio, sr)
    finding = Finding(name, json_path, wav_path.name, duration, ref_text, whisper_text)
    finding.issues = evaluate(profile, ref_text, whisper_text, duration, gaps)
    return finding


def fix_finding(finding: Finding) -> bool:
    """Replace reference_text with whisper output, but only for text-type issues."""
    if not finding.has_text_issue or not finding.whisper_text.strip():
        return False
    profile = json.loads(finding.json_path.read_text())
    if profile.get("reference_text") == finding.whisper_text:
        return False
    profile["reference_text"] = finding.whisper_text
    finding.json_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    return True


def safe_relative(p: Path) -> str:
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def render_report(findings: list[Finding], use_color: bool = True) -> str:
    def c(code: str, s: str) -> str:
        return f"{code}{s}{NC}" if use_color else s

    lines = []
    bad = [f for f in findings if not f.ok]
    good = [f for f in findings if f.ok]

    for f in findings:
        if f.ok:
            lines.append(f"  {c(GRN, '✓')} {f.voice} {c(DIM, f'({f.duration_s:.1f}s)')}")
        else:
            lines.append(f"  {c(RED, '✗')} {c(BLD, f.voice)} {c(DIM, f'({f.duration_s:.1f}s, {f.wav})')}")
            for issue in f.issues:
                lines.append(f"      {c(YLW, '•')} {issue}")
            if f.whisper_text and f.ref_text != f.whisper_text:
                lines.append(f"      {c(DIM, 'ref:')}     {f.ref_text[:120]}")
                lines.append(f"      {c(DIM, 'whisper:')} {f.whisper_text[:120]}")

    lines.append("")
    lines.append(f"  {len(good)} ok, {c(RED, str(len(bad)))} flagged out of {len(findings)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true",
                    help="Overwrite reference_text with Whisper output for voices flagged with text issues")
    ap.add_argument("--voice", help="Audit a single voice by name (json stem)")
    ap.add_argument("--json", action="store_true", help="Emit JSON report instead of text")
    ap.add_argument("--voices-dir", default=str(DEFAULT_VOICES), help="Path to voices/")
    ap.add_argument("--model", default="base.en", help="Whisper model (default: base.en)")
    args = ap.parse_args()

    voices_dir = Path(args.voices_dir).resolve()
    profiles = sorted(voices_dir.glob("*.json"))
    if args.voice:
        profiles = [p for p in profiles if p.stem == args.voice]
        if not profiles:
            print(f"no profile matching name={args.voice}", file=sys.stderr)
            return 2

    if not profiles:
        print("no voice profiles found", file=sys.stderr)
        return 2

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed. pip install faster-whisper", file=sys.stderr)
        return 2

    print(f"  loading whisper {args.model}...", file=sys.stderr)
    model = WhisperModel(args.model, compute_type="int8")

    cache: dict[Path, str] = {}
    findings: list[Finding] = []
    for jp in profiles:
        try:
            findings.append(audit_one(jp, voices_dir, cache, model))
        except Exception as e:
            f = Finding(jp.stem, jp, "", 0.0, "", "")
            f.issues.append(f"audit error: {e}")
            findings.append(f)

    if args.fix:
        fixed = 0
        for i, f in enumerate(findings):
            if f.has_text_issue and fix_finding(f):
                fixed += 1
                # Re-audit so the report and exit code reflect post-fix state.
                findings[i] = audit_one(f.json_path, voices_dir, cache, model)
        print(f"  fixed reference_text in {fixed} profile(s)", file=sys.stderr)

    if args.json:
        out = [
            {
                "voice": f.voice,
                "json": safe_relative(f.json_path),
                "wav": f.wav,
                "duration_s": round(f.duration_s, 2),
                "issues": f.issues,
                "reference_text": f.ref_text,
                "whisper_text": f.whisper_text,
            }
            for f in findings
        ]
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(render_report(findings, use_color=sys.stdout.isatty()))

    return 1 if any(not f.ok for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
