from types import SimpleNamespace

import pytest

from expressive.contracts import validate_options
from expressive.generation import generate_with_context, paragraph_segments


def test_paragraphs_keep_exact_text_and_do_not_synthesize_markdown_separators_alone():
    text = 'Here is a draft:\n\n***\n\n**Subject: Evidence**\n\nThe answer.\n\n***'
    parts = paragraph_segments(text)
    assert ''.join(parts) == text
    assert parts == ['Here is a draft:\n\n', '***\n\n**Subject: Evidence**\n\n', 'The answer.\n\n***']


@pytest.mark.parametrize('mode,count', [('continuous', 1), ('paragraphs', 2)])
def test_context_mode_reuses_reference_and_never_drops_or_reorders_words(mode, count):
    calls, seeds = [], []
    class Model:
        def generate(self, **kwargs):
            calls.append(kwargs)
            yield SimpleNamespace(audio=[.1])
    text = 'First statement.\n\nSecond statement.'
    options = validate_options({'context_mode': mode, 'seed': 8})
    assert len(list(generate_with_context(Model(), text, 'ref.wav', 'Reference.', options, seeds.append))) == count
    assert ''.join(call['text'] for call in calls) == text
    assert all(call['ref_audio'] == 'ref.wav' and call['ref_text'] == 'Reference.' for call in calls)
    assert seeds == [8] * count


def test_empty_middle_paragraph_aborts_instead_of_delivering_partial_narration():
    calls = []
    class Model:
        def generate(self, **kwargs):
            calls.append(kwargs['text'])
            yield SimpleNamespace(audio=[] if len(calls) == 2 else [.1])
    with pytest.raises(RuntimeError, match='segment 1 generated no audio'):
        list(generate_with_context(Model(), 'One.\n\nTwo.\n\nThree.', 'ref', 'Ref',
                                   validate_options({'context_mode': 'paragraphs'}), lambda seed: None))
    assert len(calls) == 2


@pytest.mark.parametrize('mode', ['sentences', None, [], 1])
def test_unsupported_context_policy_rejected(mode):
    with pytest.raises(ValueError, match='context_mode'):
        validate_options({'context_mode': mode})
