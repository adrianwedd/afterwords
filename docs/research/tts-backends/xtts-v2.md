## XTTS v2

**Repo:** https://github.com/coqui-ai/TTS
**License:** CPML (Non-commercial)
**Size:** 0.467B, 1.8 GB
**Sample rate:** 24000
**Languages:** English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Hungarian, Korean, Japanese, Hindi
**Apple Silicon path:** PyTorch+MPS — Note: Works well on MPS, though some minor ops may fall back to CPU. Performance is strong for 32GB M5.

### Install
```bash
pip install TTS torch torchaudio --index-url https://download.pytorch.org/whl/cpu
# MPS is built into standard macOS PyTorch wheels, no special index needed for Mac, use standard pip install:
pip install TTS torch torchaudio
```

### Model download
```bash
huggingface-cli download coqui/XTTS-v2
```
Disk: 1.8 GB

### Python API for cloning
```python
from TTS.api import TTS
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("mps")
tts.tts_to_file(text="This is a test sentence.", speaker_wav="reference.wav", language="en", file_path="output.wav")
```

### Backend protocol skeleton
```python
# backends/xtts_v2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class XTTSv2Backend(BackendBase):
    name = "xtts_v2"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh", "hu", "ko", "ja", "hi")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- XTTS v2 is a robust starting point with out-of-the-box MPS support via Coqui. Because it requires no transcript for the reference audio, `prepare_voice` only needs to cache the path to the speaker WAV or pre-compute the latent embeddings. One quirk to watch out for is that XTTS can be prone to "hallucinating" background noise or extended trailing silences on Apple Silicon if the reference audio is noisy; ensure you test with a highly clean, 6-second target clip.

---
