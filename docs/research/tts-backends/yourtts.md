## YourTTS

**Repo:** https://github.com/coqui-ai/TTS
**License:** Open Source
**Size:** 0.15B, 1.0 GB
**Sample rate:** 16000
**Languages:** English, French, Portuguese
**Apple Silicon path:** PyTorch+MPS — Note: A very lightweight VITS-based model; will fly on an M5 with practically zero latency.

### Install
```bash
pip install TTS torch torchaudio
```

### Model download
```bash
huggingface-cli download coqui/YourTTS
```
Disk: 1.0 GB

### Python API for cloning
```python
from TTS.api import TTS
tts = TTS("tts_models/multilingual/multi-dataset/your_tts").to("mps")
tts.tts_to_file("This is a test sentence.", speaker_wav="reference.wav", language="en", file_path="output.wav")
```

### Backend protocol skeleton
```python
# backends/yourtts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class YourTTSBackend(BackendBase):
    name = "yourtts"
    sample_rate = 16000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "fr", "pt-BR")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- YourTTS is the predecessor to XTTS. It relies strictly on extracting a d-vector speaker embedding via an encoder. For the most efficient implementation in afterwords, use `prepare_voice` to invoke the `SpeakerEncoder` directly on the reference WAV, storing the tensor in the `PreparedVoice` object. During `synthesize`, pass this pre-computed tensor instead of the audio file path to save significant processing overhead on rapid consecutive generations.

---
