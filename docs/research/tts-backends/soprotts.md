## SoproTTS

**Repo:** https://github.com/SoproTTS/sopro-tts
**License:** Open Source
**Size:** 0.135B, 0.6 GB
**Sample rate:** 24000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: Highly optimized for minimal hardware; runs ~20x real-time on M-series chips.

### Install
```bash
pip install soprotts torch torchaudio
```

### Model download
```bash
huggingface-cli download SoproTTS/sopro-tts-1.5
```
Disk: 0.6 GB

### Python API for cloning
```python
from soprotts import SoproTTS

model = SoproTTS.from_pretrained("SoproTTS/sopro-tts-1.5").to("mps")
audio = model.synthesize(
    text="This is a test sentence.",
    ref_audio="reference.wav"
)
```

### Backend protocol skeleton
```python
# backends/soprotts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class SoproTTSBackend(BackendBase):
    name = "sopro_tts"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- SoproTTS is uniquely small (only 135M parameters) and heavily optimized for zero-shot tasks without taking up massive GPU bandwidth. It operates flawlessly out-of-the-box on MPS, and `ref_text` is generally ignored. Its behavior is exceptionally stable, but because it relies strictly on acoustic prompt extraction, make sure the sample provided in `prepare_voice` is tightly cropped around active speech, as its lighter attention span might become confused by excessive dead air.

---
