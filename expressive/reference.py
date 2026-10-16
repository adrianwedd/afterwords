"""Bounded reference validation and explicit stereo-to-mono conditioning."""
import io
import numpy as np
import soundfile as sf


def normalize_reference(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4*1024**2:
        raise ValueError('reference must contain at most 4 MiB')
    info=sf.info(io.BytesIO(raw))
    if info.format!='WAV' or info.channels not in (1,2) or not 1<=info.duration<=30 or info.samplerate>192000:
        raise ValueError('reference must be a mono/stereo WAV, 1–30 seconds, at most 192 kHz')
    audio,rate=sf.read(io.BytesIO(raw),dtype='float32')
    if not np.isfinite(audio).all():
        raise ValueError('reference contains nonfinite samples')
    if info.channels==1:return raw,'none'
    output=io.BytesIO()
    sf.write(output,audio.mean(axis=1),rate,format='WAV',subtype='PCM_16')
    return output.getvalue(),'stereo-mean-to-mono'
