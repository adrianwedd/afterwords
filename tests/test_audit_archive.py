from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit-archive.py"
SPEC = importlib.util.spec_from_file_location("audit_archive", SCRIPT)
audit_archive = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["audit_archive"] = audit_archive
SPEC.loader.exec_module(audit_archive)


def test_word_error_rate_counts_insertions_deletions_and_substitutions():
    assert audit_archive.word_error_rate(["hello", "world"], ["hello", "there"]) == 0.5
    assert audit_archive.word_error_rate(["hello"], ["hello", "there"]) == 1.0
    assert audit_archive.word_error_rate(["hello", "there"], ["hello"]) == 0.5


def test_buckets_input_lengths():
    assert audit_archive.length_bucket("one two three") == "short"
    assert audit_archive.length_bucket("word " * 40) == "medium"
    assert audit_archive.length_bucket("word " * 100) == "long"


def test_detects_risky_text_patterns():
    text = "CALL 123 now -- see https://example.com and ```python"
    assert audit_archive.pattern_names(text) == [
        "digits",
        "urls",
        "code_fences",
        "all_caps",
        "em_dash",
    ]


def test_discovers_mp3_txt_pairs(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "picard-20260428-101112.mp3").write_bytes(b"fake")
    (archive / "picard-20260428-101112.txt").write_text("Make it so.", encoding="utf-8")

    pairs = audit_archive.discover_pairs([archive])

    assert len(pairs) == 1
    assert pairs[0].voice == "picard"
    assert pairs[0].stamp == "20260428-101112"
    assert pairs[0].expected == "Make it so."
    assert pairs[0].issues == []
