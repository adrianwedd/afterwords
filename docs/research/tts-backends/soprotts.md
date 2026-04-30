## SoproTTS

**Repo:** https://github.com/samuel-vitorino/sopro
**License:** Apache-2.0
**Size:** 0.135B, 0.6 GB
**Sample rate:** 24000
**Languages:** en
**Apple Silicon path:** PyTorch CPU by default. Upstream reports ~20x real-time on a base M3 CPU; set `SOPROTTS_DEVICE` to opt into another torch device.

### Verification note
The original research stub pointed to `SoproTTS/sopro-tts` and claimed multilingual support. That appears stale. The real upstream is `samuel-vitorino/sopro`; its README currently describes Sopro as a lightweight English TTS model with zero-shot voice cloning, not a multilingual model.

### Install
```bash
pip install sopro torch torchaudio
```

### Model download
```bash
huggingface-cli download samuel-vitorino/sopro
```
Disk: 0.6 GB

### Python API for cloning
```python
from sopro import SoproTTS

model = SoproTTS.from_pretrained("samuel-vitorino/sopro", device="cpu")
audio = model.synthesize(
    text="This is a test sentence.",
    ref_audio_path="reference.wav"
)
```

### Backend protocol skeleton
```python
# backends/soprotts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class SoproTTSBackend(BackendBase):
    name = "soprotts"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- SoproTTS is small (135M parameters) and optimized for zero-shot cloning with a 3-12 second reference audio clip.
- The upstream package exposes `SoproTTS.from_pretrained("samuel-vitorino/sopro", device=...)`, `prepare_reference(ref_audio_path=...)`, and `synthesize(text, ref=...)` / `synthesize(text, ref_audio_path=...)`.
- `ref_text` is optional for Afterwords metadata consistency but is not used by the upstream synthesis API.
- Generation is currently English-only per upstream docs. Do not advertise multilingual routing until upstream ships and documents multilingual support.

---
