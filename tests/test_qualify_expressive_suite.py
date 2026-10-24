"""Guard transcript and direction semantics in quantisation comparisons."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qualify_suite', ROOT/'scripts/qualify-expressive-suite.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


def test_real_long_case_keeps_all_transcript_characters():
    cases = json.loads((ROOT/'qa/expressive-voice/cases/suite.v1.json').read_text())['cases']
    case = next(c for c in cases if c['id'] == 'long-response')
    segments = suite.case_inputs(case, True)
    assert len(segments) > 1
    assert all(len(s) <= 400 for s in segments)
    assert ''.join(''.join(segments).split()) == ''.join(case['text'].split())
    assert suite.case_inputs(case, False) == [case['text']]


def test_chunked_mode_keeps_other_cases_direction_and_speaker_tags():
    emotion = {'id': 'emotion', 'text': 'Well. That worked.', 'cues': [{'offset': 6, 'cue': 'whispers'}]}
    dialogue = {'id': 'dialogue', 'turns': [{'speaker': 0, 'text': 'Hello.'}, {'speaker': 1, 'text': 'Goodbye.'}]}
    assert suite.case_inputs(emotion, True) == ['Well. [whispers] That worked.']
    assert suite.case_inputs(dialogue, True) == ['<|speaker:0|> Hello. <|speaker:1|> Goodbye.']


def test_chunked_long_rejects_unmapped_direction_offsets():
    case = {'id': 'long-response', 'text': 'Well. That worked.', 'cues': [{'offset': 6, 'cue': 'whispers'}]}
    with pytest.raises(ValueError, match='plain single-speaker'):
        suite.case_inputs(case, True)


def test_chunker_word_loss_fails_before_generation(monkeypatch):
    import chunks
    monkeypatch.setattr(chunks, 'chunk_text', lambda *a, **kw: ['The ending'])
    with pytest.raises(ValueError, match='changed non-whitespace'):
        suite.case_inputs({'id': 'long-response', 'text': 'The ending must remain.'}, True)
