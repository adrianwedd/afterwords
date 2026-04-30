## F5-TTS

**Repo:** https://github.com/SWivid/F5-TTS
**License:** CC-BY-NC 4.0
**Size:** 0.336B, 1.2 GB
**Sample rate:** 24000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: MPS is fully supported, and the flow-matching DiT architecture runs very fast on M-series chips.

### Install
```bash
pip install f5-tts torch torchaudio
```

### Model download
```bash
huggingface-cli download SWivid/F5-TTS
```
Disk: 1.2 GB

### Python API for cloning
```python
from f5_tts.infer.utils_infer import infer_process
from f5_tts.model import DiT

# Assuming models are downloaded to default cache paths
audio_out, sample_rate, spect = infer_process(
    ref_audio="reference.wav",
    ref_text="Transcript of reference.",
    gen_text="This is a test sentence.",
    model_obj=DiT(),
    vocoder=None
)
```

### Backend protocol skeleton
```python
# backends/f5tts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class F5TTSBackend(BackendBase):
    name = "f5_tts"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- F5-TTS utilizes a flow-matching and Diffusion Transformer (DiT) backbone, heavily relying on the cross-attention between `ref_text` and `ref_audio`. For the afterwords backend, the `prepare_voice` method must store both the reference WAV and its transcription. One quirk to test first is adjusting the ODE solver's `nfe_step` parameter (number of function evaluations); lowering it speeds up MPS generation drastically, but you'll need to strike the right balance between inference speed and output audio clarity.

---
