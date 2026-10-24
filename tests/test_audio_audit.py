import numpy as np
import pytest
from expressive.audio_audit import waveform,word_errors,validate_delivery


def test_dramatic_pauses_are_preserved_without_claiming_word_integrity():
    audio=np.concatenate([np.full(1000,.1),np.zeros(5000),np.full(1000,.1)])
    measured=validate_delivery(audio,1000)
    assert measured['longest_silence_seconds']==5
    assert measured['samples']==7000


@pytest.mark.parametrize('expected,heard,operation',[
    ('Well this is fine','this is fine','deletion'),
    ('this is fine','this is is fine','insertion'),
    ('this is fine','this is bad','substitution'),
])
def test_word_errors_are_distinguished(expected,heard,operation):
    result=word_errors(expected,heard)
    assert result['edit_distance']==1
    assert result['edits'][0]['operation']==operation


def test_punctuation_not_misreported_as_missing_words():
    assert word_errors('Well—this, indeed, is fine!','well this indeed is fine')['wer']==0


def test_silence_and_clipping_are_measured_without_quality_verdict():
    audio=np.concatenate([np.zeros(1000),np.ones(1000),np.zeros(500)])
    result=waveform(audio,1000)
    assert result['leading_silence_seconds']==1
    assert result['trailing_silence_seconds']==.5
    assert result['clipped_sample_fraction']==.4
    assert 'acoustic_acceptance' not in result


@pytest.mark.parametrize('a',[np.array([]),np.array([np.nan]),np.zeros((10,2))])
def test_invalid_waveforms_fail(a):
    with pytest.raises(ValueError):waveform(a,24000)
