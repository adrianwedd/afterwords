## IndexTTS-2

**Repo:** https://huggingface.co/IndexTeam/IndexTTS-2
**License:** Open Source
**Size:** 1.5B, 3.0 GB
**Sample rate:** 24000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: High RAM footprint, but comfortably fits inside the 32GB unified memory of the M5.

### Install
```bash
git clone https://github.com/IndexTeam/IndexTTS.git
cd IndexTTS
pip install -r requirements.txt torch torchaudio
```

### Model download
```bash
huggingface-cli download IndexTeam/IndexTTS-2
```
Disk: 3.0 GB

### Python API for cloning
```python
from indextts import IndexTTS

model = IndexTTS.from_pretrained("IndexTeam/IndexTTS-2").to("mps")
audio = model.synthesize(
    text="This is a test sentence.",
    ref_audio="reference.wav",
    ref_text="Reference transcript."
)
```

### Backend protocol skeleton
```python
# backends/indextts2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class IndexTTS2Backend(BackendBase):
    name = "indextts_2"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- IndexTTS-2 specializes in explicit token specification for precise duration and emotional control. Because it is highly capable of separating emotional expression from speaker identity, you might want to expose optional parameters via `extras` in the backend so users can pass emotion tags. Its auto-regressive decoding can cause repetition loops on long inputs, so testing text-chunking logic inside the `synthesize` method before hitting the model will be essential for stable integration.

---
