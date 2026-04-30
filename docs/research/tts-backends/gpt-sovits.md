## GPT-SoVITS

**Repo:** https://github.com/RVC-Boss/GPT-SoVITS
**License:** MIT
**Size:** 2.0 GB
**Sample rate:** 32000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: Native support via macOS environments; the community has created specialized single-click installers, but the programmatic API runs cleanly on M5.

### Install
```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS
pip install -r requirements.txt
```

### Model download
```bash
huggingface-cli download lj1995/GPT-SoVITS
```
Disk: 2.0 GB

### Python API for cloning
```python
from GPT_SoVITS.inference import get_tts_wav

# API wrapper assumes configurations are pointed to weights correctly
audio_generator = get_tts_wav(
    ref_wav_path="reference.wav",
    prompt_text="Reference transcript.",
    prompt_language="en",
    text="This is a test sentence.",
    text_language="en"
)
audio_data = next(audio_generator)
```

### Backend protocol skeleton
```python
# backends/gpt_sovits.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class GPTSoVITSBackend(BackendBase):
    name = "gpt_sovits"
    sample_rate = 32000
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- GPT-SoVITS relies heavily on an exact match transcript of the reference audio for the GPT alignment phase, so `ref_text_policy` must be `REQUIRED`. Its Python API natively returns a generator yielding audio chunks sequentially (perfect for streaming backends). In `synthesize`, you can capture these chunks and either yield them directly if the afterwords pipeline supports streaming buffers, or concatenate them into a full array before returning.

---
