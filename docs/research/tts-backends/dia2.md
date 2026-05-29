## Dia2

**Repo:** https://github.com/nari-labs/dia2
**License:** Apache-2.0
**Size:** 1B / 2B variants
**Sample rate:** 44100
**Languages:** en-only
**Apple Silicon path:** PyTorch runtime; upstream is CUDA-first and documents CUDA 12.8+ for best support. Try `DIA2_DEVICE=mps` or `DIA2_DEVICE=cpu` locally, but expect upstream compatibility to lag CUDA. Handles dialogue formatting natively and supports realtime/streaming-oriented generation.

### Install
```bash
pip install -r requirements-dia2.txt
```

### Model download
```bash
huggingface-cli download nari-labs/Dia2-2B
```
Variants: `nari-labs/Dia2-1B`, `nari-labs/Dia2-2B`

### Python API for cloning
```python
from dia2 import Dia2, GenerationConfig, PrefixConfig, SamplingConfig

dia = Dia2.from_repo("nari-labs/Dia2-2B", device="cuda", dtype="bfloat16")
config = GenerationConfig(
    audio=SamplingConfig(temperature=0.8, top_k=50),
    prefix=PrefixConfig(include_audio=False),
)
result = dia.generate("[S1] This is a test sentence.", config=config, prefix_speaker_1="reference.wav")
audio_data = result.waveform
```

### Backend protocol skeleton
```python
# backends/dia2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class Dia2Backend(BackendBase):
    name = "dia2"
    sample_rate = 44100
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- Dia2 is optimized for multi-speaker dialogues and supports embedded nonverbal tags like `(laughs)`.
- Dia2 expects `[S1]` / `[S2]` speaker tag formatting. The backend should prepend `[S1]` when callers provide plain text.
- Voice conditioning is passed as `prefix_speaker_1`; upstream transcribes prefix audio internally.
- The implementation should keep Dia2 imports lazy in `load()` and must not download weights during unit tests.

---
