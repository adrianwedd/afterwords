"""Private JSON-lines worker. Run only with the isolated Drama 3 environment."""
import base64
import hashlib
import io
import json
import sys
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from expressive.contracts import MODEL, REVISION, validate_options, directed_text
from expressive.generation import generate_with_context


def emit(value):
    # Libraries may print diagnostics; the protocol has its own saved stdout.
    PROTOCOL.write(json.dumps(value, separators=(',', ':')) + '\n')
    PROTOCOL.flush()


PROTOCOL = sys.stdout
sys.stdout = sys.stderr


def main():
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from huggingface_hub import snapshot_download
    from mlx_audio.tts.utils import load_model
    mx.set_memory_limit(40 * 1024**3)
    mx.set_cache_limit(2 * 1024**3)
    model = None
    with tempfile.TemporaryDirectory(prefix='afterwords-drama3-') as folder:
        references = OrderedDict()
        for line in sys.stdin:
            started = time.perf_counter()
            try:
                request = json.loads(line)
                options = validate_options(request.get('performance', {}))
                text = directed_text(request['text'], options)
                raw = base64.b64decode(request['reference_wav'], validate=True)
                from expressive.reference import normalize_reference
                conditioning, conversion = normalize_reference(raw)
                if not request.get('reference_text', '').strip():
                    raise ValueError('reference transcript required')
                digest = hashlib.sha256(raw).hexdigest()
                if digest not in references:
                    path = Path(folder) / (digest + '.wav')
                    path.write_bytes(conditioning)
                    references[digest] = path
                    if len(references) > 4:
                        _, old = references.popitem(last=False)
                        old.unlink()
                references.move_to_end(digest)
                load_started = time.perf_counter()
                if model is None:
                    from expressive.resources import acquire_model_lease
                    acquire_model_lease()
                    model = load_model(snapshot_download(MODEL, revision=REVISION, local_files_only=True))
                load_seconds = time.perf_counter() - load_started
                original_frames = model._frames
                def checked_frames(*args, **kwargs):
                    count = 0
                    for frame in original_frames(*args, **kwargs):
                        count += 1
                        yield frame
                    if count >= options['max_frames']:
                        raise RuntimeError('frame limit reached without verified EOS')
                model._frames = checked_frames
                mx.reset_peak_memory()
                generation_started = time.perf_counter()
                count = 0
                ttfa = None
                try:
                    for result in generate_with_context(model, text, str(references[digest]),
                            request['reference_text'], options, mx.random.seed):
                        audio = np.asarray(result.audio, dtype='<f4')
                        if audio.ndim != 1 or not np.isfinite(audio).all():
                            raise RuntimeError('invalid generated audio')
                        if not len(audio):
                            continue
                        if ttfa is None:
                            ttfa = time.perf_counter() - generation_started
                        count += len(audio)
                        if count > 44100 * 300:
                            raise RuntimeError('audio duration exceeds five minutes')
                        emit(dict(kind='chunk', audio=base64.b64encode(audio.tobytes()).decode(), sample_rate=result.sample_rate))
                finally:
                    model._frames = original_frames
                if not count:
                    raise RuntimeError('model generated no audio')
                elapsed = time.perf_counter() - generation_started
                emit(dict(kind='done', samples=count, sample_rate=model.sample_rate, model=MODEL,
                          context_mode=options['context_mode'],
                          revision=REVISION, reference_sha256=digest,
                          reference_conversion=conversion,
                          conditioning_sha256=hashlib.sha256(references[digest].read_bytes()).hexdigest(),
                          ttfa_seconds=ttfa, generation_seconds=elapsed,
                          load_seconds=load_seconds, wall_seconds=time.perf_counter()-started,
                          rtf=elapsed/(count/model.sample_rate), peak_metal_bytes=mx.get_peak_memory()))
            except Exception as exc:
                emit(dict(kind='error', error=f'{type(exc).__name__}: {exc}'))


if __name__ == '__main__':
    main()
