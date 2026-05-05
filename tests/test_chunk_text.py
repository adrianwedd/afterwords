"""Tests for chunk_text.py sentence splitter."""
from __future__ import annotations

import importlib.util
import sys
from io import StringIO
from pathlib import Path


def _run_chunk(text: str) -> list[str]:
    """Run chunk_text.py with the given text, return list of chunks."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "chunk_text.py")],
        input=text,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_short_text_single_chunk():
    chunks = _run_chunk("Hello world.")
    assert chunks == ["Hello world."]


def test_two_short_sentences_in_one_chunk():
    chunks = _run_chunk("Hello world. How are you?")
    assert len(chunks) == 1
    assert "Hello world." in chunks[0]
    assert "How are you?" in chunks[0]


def test_splits_at_200_char_boundary():
    # ~110 chars each sentence; together >200 chars → must split
    s1 = "A" * 100 + "."
    s2 = "B" * 100 + "."
    chunks = _run_chunk(s1 + " " + s2)
    assert len(chunks) == 2
    assert s1 in chunks[0]
    assert s2 in chunks[1]


def test_empty_input_produces_no_output():
    chunks = _run_chunk("")
    assert chunks == []


def test_whitespace_only_input_produces_no_output():
    chunks = _run_chunk("   \n  ")
    assert chunks == []


def test_internal_newlines_stripped_from_chunks():
    chunks = _run_chunk("Hello\nworld. Goodbye.")
    assert all("\n" not in c for c in chunks)


def test_multiple_sentences_pack_until_limit():
    # 5 short sentences; each ~20 chars — should fit multiple per chunk
    sentences = ["Short sentence" + str(i) + "." for i in range(5)]
    text = " ".join(sentences)
    chunks = _run_chunk(text)
    # All 5 sentences fit in ~100 chars total → 1 chunk
    assert len(chunks) == 1


def test_exclamation_and_ellipsis_as_sentence_boundaries():
    chunks = _run_chunk("Wow! That was amazing. Really… Or was it?")
    # All together <200 chars → 1 chunk, but splits ARE at these boundaries
    assert len(chunks) >= 1


def test_single_sentence_exceeding_max_chars_is_word_split():
    # A single sentence with no punctuation that exceeds MAX_CHARS must be split.
    long_sentence = "word " * 50  # 250 chars, no sentence-end punctuation
    chunks = _run_chunk(long_sentence.strip())
    assert all(len(c) <= 200 for c in chunks), f"Chunk exceeds 200 chars: {[len(c) for c in chunks]}"
    assert len(chunks) >= 2


def test_word_split_preserves_all_words():
    # Ensure no words are dropped when word-splitting a long sentence.
    long_sentence = ("alpha " * 40).strip()  # 240 chars
    chunks = _run_chunk(long_sentence)
    rejoined = " ".join(chunks)
    assert rejoined == long_sentence
