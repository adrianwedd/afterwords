"""Shared wire contract. No MLX or web dependencies in the main server."""
import math

MODEL = 'mlx-community/fish-audio-drama-3-4bit'
REVISION = 'cc639e27aba7edb73429d3e3806f471dcd79d316'
SOURCE_REVISION = 'dad2087f790dfe96b07d5aac1405db4b578b411f'
CUES = frozenset({'whispers', 'laughs', 'sighs', 'chuckles', 'gasps', 'excited', 'sad', 'angry', 'calm'})
DEFAULTS = dict(temperature=0.7, top_p=0.7, top_k=30, max_frames=1600, seed=20261016,
                context_mode='continuous')


def validate_options(options):
    if not isinstance(options, dict):
        raise ValueError('performance must be an object')
    unknown = set(options) - set(DEFAULTS) - {'cues'}
    if unknown:
        raise ValueError(f'unsupported performance controls: {sorted(unknown)}')
    out = {**DEFAULTS, **options}
    if out['context_mode'] not in ('continuous', 'paragraphs'):
        raise ValueError('context_mode must be continuous or paragraphs')
    for key, low, high, integer in [('temperature', 0.1, 1.5, False), ('top_p', 0.1, 1, False),
                                    ('top_k', 1, 100, True), ('max_frames', 16, 4000, True),
                                    ('seed', 0, 2**32-1, True)]:
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        if integer and not isinstance(value, int):
            raise ValueError(f'{key} must be an integer')
        if not low <= value <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
    cues = out.setdefault('cues', [])
    if not isinstance(cues, list) or len(cues) > 64:
        raise ValueError('cues must contain at most 64 events')
    previous = -1
    for cue in cues:
        if not isinstance(cue, dict) or set(cue) != {'offset', 'cue'}:
            raise ValueError('each cue needs offset and cue')
        pos = cue['offset']
        if type(pos) is not int or pos < 0 or pos < previous or not isinstance(cue['cue'], str) or cue['cue'] not in CUES:
            raise ValueError('cues must use known names and ordered nonnegative offsets')
        previous = pos
    return out


def directed_text(text, options):
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        raise ValueError('text must contain 1–16000 characters')
    # Model control tokens in captured prose must not become speaker instructions.
    if '<|' in text or '|>' in text:
        raise ValueError('literal model control tokens are not supported')
    result = text
    for cue in reversed(options['cues']):
        offset = cue['offset']
        if offset > len(text) or (0 < offset < len(text) and not (text[offset-1].isspace() or text[offset].isspace())):
            raise ValueError('cue offset must be a word boundary within text')
        result = result[:offset] + '[' + cue['cue'] + '] ' + result[offset:]
    return result
