#!/usr/bin/env python3
"""Audit archived TTS responses against their requested text.

The Claude/Codex workers archive paired files:
  - {voice}-{stamp}.mp3: synthesized audio
  - {voice}-{stamp}.txt: exact text sent to /synthesize

This script transcribes the audio with faster-whisper, compares it to the
sidecar text, and buckets results by input length and risky text patterns.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


DEFAULT_ARCHIVES = (
    Path.home() / ".claude" / "tts-archive",
    Path.home() / ".codex" / "tts-archive",
)

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("digits", re.compile(r"\d")),
    ("urls", re.compile(r"https?://|www\.", re.IGNORECASE)),
    ("code_fences", re.compile(r"```")),
    ("all_caps", re.compile(r"\b[A-Z]{3,}\b")),
    ("em_dash", re.compile(r"\u2014|--")),
)


@dataclass
class Pair:
    audio: Path
    text_path: Path | None
    voice: str
    stamp: str
    expected: str = ""
    transcript: str = ""
    similarity: float | None = None
    word_error_rate: float | None = None
    length_bucket: str = ""
    patterns: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.issues:
            return False
        if self.similarity is None or self.word_error_rate is None:
            return True
        return self.similarity >= 0.78 and self.word_error_rate <= 0.35


def normalize_words(text: str) -> list[str]:
    words = []
    for token in text.lower().split():
        token = "".join(ch for ch in token if ch.isalnum() or ch == "'")
        if token:
            words.append(token)
    return words


def word_error_rate(expected: list[str], actual: list[str]) -> float:
    if not expected:
        return 0.0 if not actual else 1.0

    prev = list(range(len(actual) + 1))
    for i, expected_word in enumerate(expected, 1):
        cur = [i]
        for j, actual_word in enumerate(actual, 1):
            cost = 0 if expected_word == actual_word else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / len(expected)


def length_bucket(text: str) -> str:
    n = len(normalize_words(text))
    if n <= 20:
        return "short"
    if n <= 80:
        return "medium"
    return "long"


def pattern_names(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS if pattern.search(text)]


def split_voice_stamp(stem: str) -> tuple[str, str]:
    match = re.match(r"^(.+)-(\d{8}-\d{6})$", stem)
    if not match:
        return stem, ""
    return match.group(1), match.group(2)


def discover_pairs(archive_dirs: list[Path]) -> list[Pair]:
    pairs: list[Pair] = []
    seen: set[Path] = set()
    for archive_dir in archive_dirs:
        if not archive_dir.exists():
            continue
        for audio in sorted(archive_dir.glob("*.mp3")):
            audio = audio.resolve()
            if audio in seen:
                continue
            seen.add(audio)

            text_path = audio.with_suffix(".txt")
            voice, stamp = split_voice_stamp(audio.stem)
            pair = Pair(
                audio=audio,
                text_path=text_path if text_path.exists() else None,
                voice=voice,
                stamp=stamp,
            )
            if pair.text_path is None:
                pair.issues.append("missing sidecar text")
            else:
                pair.expected = pair.text_path.read_text(encoding="utf-8").strip()
                if not pair.expected:
                    pair.issues.append("empty sidecar text")
            pair.length_bucket = length_bucket(pair.expected)
            pair.patterns = pattern_names(pair.expected)
            pairs.append(pair)
    return pairs


def transcribe(audio: Path, model, lang: str | None) -> str:
    kwargs = {"language": lang} if lang else {}
    segments, _ = model.transcribe(str(audio), **kwargs)
    return " ".join(segment.text.strip() for segment in segments).strip()


def score_pair(pair: Pair, model, lang: str | None) -> None:
    if not pair.expected:
        return
    pair.transcript = transcribe(pair.audio, model, lang)
    if not pair.transcript:
        pair.issues.append("empty whisper output")
        return

    expected_words = normalize_words(pair.expected)
    actual_words = normalize_words(pair.transcript)
    pair.similarity = SequenceMatcher(None, expected_words, actual_words).ratio()
    pair.word_error_rate = word_error_rate(expected_words, actual_words)

    if pair.similarity < 0.78:
        pair.issues.append(f"low similarity: {pair.similarity:.2f}")
    if pair.word_error_rate > 0.35:
        pair.issues.append(f"high WER: {pair.word_error_rate:.2f}")


def summarize(pairs: list[Pair]) -> dict[str, object]:
    buckets: dict[str, dict[str, int]] = {}
    patterns: dict[str, dict[str, int]] = {}

    def add(target: dict[str, dict[str, int]], key: str, pair: Pair) -> None:
        row = target.setdefault(key, {"total": 0, "ok": 0, "flagged": 0})
        row["total"] += 1
        if pair.ok:
            row["ok"] += 1
        else:
            row["flagged"] += 1

    for pair in pairs:
        add(buckets, pair.length_bucket or "unknown", pair)
        if pair.patterns:
            for pattern in pair.patterns:
                add(patterns, pattern, pair)
        else:
            add(patterns, "plain", pair)

    return {
        "total": len(pairs),
        "ok": sum(1 for pair in pairs if pair.ok),
        "flagged": sum(1 for pair in pairs if not pair.ok),
        "by_length": buckets,
        "by_pattern": patterns,
    }


def safe_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def pair_to_json(pair: Pair) -> dict[str, object]:
    return {
        "audio": safe_path(pair.audio),
        "text": safe_path(pair.text_path) if pair.text_path else None,
        "voice": pair.voice,
        "stamp": pair.stamp,
        "length_bucket": pair.length_bucket,
        "patterns": pair.patterns,
        "similarity": round(pair.similarity, 3) if pair.similarity is not None else None,
        "word_error_rate": round(pair.word_error_rate, 3) if pair.word_error_rate is not None else None,
        "issues": pair.issues,
        "expected": pair.expected,
        "transcript": pair.transcript,
    }


def render_text(pairs: list[Pair]) -> str:
    summary = summarize(pairs)
    lines = [
        f"archive pairs: {summary['total']} total, {summary['ok']} ok, {summary['flagged']} flagged",
        "",
        "by length:",
    ]
    for name, row in sorted(summary["by_length"].items()):
        lines.append(f"  {name}: {row['ok']} ok, {row['flagged']} flagged ({row['total']} total)")
    lines.append("")
    lines.append("by pattern:")
    for name, row in sorted(summary["by_pattern"].items()):
        lines.append(f"  {name}: {row['ok']} ok, {row['flagged']} flagged ({row['total']} total)")

    flagged = [pair for pair in pairs if not pair.ok]
    if flagged:
        lines.append("")
        lines.append("flagged:")
        for pair in flagged:
            score = "not scored"
            if pair.similarity is not None and pair.word_error_rate is not None:
                score = f"sim={pair.similarity:.2f}, wer={pair.word_error_rate:.2f}"
            lines.append(f"  {safe_path(pair.audio)} ({score})")
            for issue in pair.issues:
                lines.append(f"    - {issue}")
            if pair.expected and pair.transcript:
                lines.append(f"    expected:   {pair.expected[:120]}")
                lines.append(f"    transcript: {pair.transcript[:120]}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-dir",
        action="append",
        type=Path,
        help="Archive directory to scan. Repeatable. Defaults to Claude and Codex archives.",
    )
    parser.add_argument("--model", default="base.en", help="Whisper model name (default: base.en)")
    parser.add_argument("--lang", default="en", help="Whisper language hint; empty disables hint")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Only check MP3/TXT pairing and buckets; do not run Whisper.",
    )
    args = parser.parse_args(argv)

    archive_dirs = args.archive_dir or list(DEFAULT_ARCHIVES)
    pairs = discover_pairs([path.expanduser().resolve() for path in archive_dirs])
    if not pairs:
        print("no archived MP3 files found", file=sys.stderr)
        return 2

    if not args.no_transcribe:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            print("faster-whisper not installed. pip install faster-whisper", file=sys.stderr)
            return 2

        print(f"loading whisper {args.model}...", file=sys.stderr)
        model = WhisperModel(args.model, compute_type="int8")
        lang = args.lang or None
        for pair in pairs:
            try:
                score_pair(pair, model, lang)
            except Exception as exc:
                pair.issues.append(f"transcription error: {exc}")

    if args.json:
        print(json.dumps({"summary": summarize(pairs), "pairs": [pair_to_json(p) for p in pairs]}, indent=2))
    else:
        print(render_text(pairs))

    return 1 if any(not pair.ok for pair in pairs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
