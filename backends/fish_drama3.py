"""Opt-in Drama 3 adapter. Experimental dependencies stay in a local sidecar."""
from __future__ import annotations
import base64
import io
import http.client
import json
import logging
import urllib.error
import urllib.request
from typing import Mapping

import numpy as np
import soundfile as sf
from .base import BackendBase, PreparedVoice, RefTextPolicy
from expressive.contracts import MODEL, REVISION, validate_options, directed_text

log = logging.getLogger(__name__)


class FishDrama3Backend(BackendBase):
    name = 'fish-drama3'
    display_name = 'Fish Audio Drama 3 (isolated MLX sidecar)'
    sample_rate = 44100
    ref_text_policy = RefTextPolicy.REQUIRED
    # Only English is admitted until other languages have been qualified here.
    supported_langs = ('en',)
    model_id = MODEL
    model_revision = REVISION
    endpoint = 'http://127.0.0.1:7861/synthesize'

    def load(self):
        # Selection is valid even while the sidecar is offline: Qwen handles
        # fallback. This flag denotes adapter readiness, not model residency.
        self._loaded = True

    def validate_extras(self, extras: Mapping[str, object]):
        options = dict(extras)
        fallback = options.pop('qwen_fallback', True)
        if type(fallback) is not bool:
            raise ValueError('qwen_fallback must be boolean')
        validate_options(options)

    def prepare_voice(self, ref_audio_path, ref_text, extras):
        self.validate_extras(extras)
        if not isinstance(ref_text, str) or not ref_text.strip():
            raise ValueError('Drama 3 requires a reference transcript')
        with open(ref_audio_path, 'rb') as stream:
            raw = stream.read(4 * 1024**2 + 1)
        from expressive.reference import normalize_reference
        normalize_reference(raw)  # validation; retain original bytes for Qwen fallback
        return PreparedVoice(ref_audio_path, ref_text, extras, data=raw)

    def synthesize(self, text, prepared, lang):
        if lang not in self.supported_langs:
            raise ValueError(f'Drama 3 does not support lang={lang!r}')
        options = dict(prepared.extras)
        fallback = options.pop('qwen_fallback', True)
        options = validate_options(options)
        directed_text(text, options)
        payload = dict(text=text, reference_text=prepared.ref_text, performance=options,
                       reference_wav=base64.b64encode(prepared.data).decode())
        try:
            if prepared.cancel_event is not None:
                from expressive.transport import request_wav
                raw = request_wav(json.dumps(payload).encode(), prepared.cancel_event)
            else:
                request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(),
                                                 headers={'Content-Type': 'application/json'})
                # Ignore proxy environment variables: reference audio never leaves loopback.
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=185) as response:
                    if response.headers.get_content_type() != 'audio/wav':
                        raise RuntimeError('sidecar returned a non-WAV response')
                    raw = response.read(44100 * 300 * 2 + 65537)
                    if len(raw) > 44100 * 300 * 2 + 65536:
                        raise RuntimeError('sidecar output exceeds duration limit')
            audio, rate = sf.read(io.BytesIO(raw), dtype='float32')
            if rate != self.sample_rate or audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
                raise RuntimeError('invalid sidecar output')
            self.last_delivery_backend = self.name
            return audio, rate
        except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 413):
                raise ValueError('sidecar rejected synthesis input') from exc
            if prepared.cancel_event is not None and prepared.cancel_event.is_set():
                from expressive.transport import SynthesisCancelled
                raise SynthesisCancelled() from None
            if not fallback:
                raise RuntimeError('expressive backend unavailable; fallback disabled') from exc
            log.warning('Drama 3 failed (%s); delivering Qwen fallback with original transcript', exc)
            from . import get
            qwen = get('qwen3-0.6b')
            qwen.load()
            reference = PreparedVoice(prepared.ref_audio_path, prepared.ref_text, {}, data=prepared.data)
            audio, rate = qwen.synthesize(text, reference, lang)
            audio = np.asarray(audio, dtype=np.float32)
            if (audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all()
                    or type(rate) is not int or rate <= 0):
                raise RuntimeError('invalid Qwen fallback output')
            if rate != self.sample_rate:
                from math import gcd
                from scipy.signal import resample_poly
                divisor = gcd(rate, self.sample_rate)
                # Keep one format across sentence chunks even if only some
                # requests fall back. Polyphase filtering preserves duration
                # and pitch; relabelling or concatenating PCM cannot do this.
                audio = resample_poly(audio, self.sample_rate // divisor,
                                      rate // divisor).astype(np.float32)
            self.last_delivery_backend = qwen.name
            return audio, self.sample_rate
