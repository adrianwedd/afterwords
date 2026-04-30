## F5-TTS

**Repo:** https://github.com/SWivid/F5-TTS
**License:** Code is MIT; the default pretrained SWivid/F5-TTS model weights are CC-BY-NC 4.0 and block commercial use.
**Size:** 0.336B, 1.2 GB
**Sample rate:** 24000
**Languages:** `F5TTS_v1_Base` is zh/en. Upstream `SHARED.md` lists community checkpoints for additional languages with their own licenses.
**Apple Silicon path:** PyTorch+MPS — upstream enables `PYTORCH_ENABLE_MPS_FALLBACK=1`; some ops may fall back from MPS.

### Install
```bash
pip install f5-tts torch torchaudio
```

### Model download
Pip installs can auto-fetch from Hugging Face on first load. To prefetch manually:

```bash
huggingface-cli download SWivid/F5-TTS --include 'F5TTS_v1_Base/*'
```
Disk: 1.2 GB

### Python API for cloning
```python
from f5_tts.api import F5TTS

# Auto-downloads the default F5TTS_v1_Base checkpoint if absent.
f5tts = F5TTS(model="F5TTS_v1_Base", device="mps")
audio_out, sample_rate, spect = f5tts.infer(
    ref_file="reference.wav",
    ref_text="Transcript of reference.",
    gen_text="This is a test sentence.",
)
```

### Backend protocol skeleton
```python
# backends/f5_tts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class F5TTSBackend(BackendBase):
    name = "f5-tts"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("en", "zh")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- F5-TTS utilizes a flow-matching and Diffusion Transformer (DiT) backbone, heavily relying on the alignment between `ref_text` and `ref_audio`. Upstream can transcribe when `ref_text` is empty, but that costs extra memory and makes voice profiles less deterministic. For Afterwords, require `reference_text` and store both the reference WAV and its transcription.
- Useful inference extras to expose: `nfe_step`, `cfg_strength`, `sway_sampling_coef`, `speed`, `target_rms`, `cross_fade_duration`, `fix_duration`, and `seed`. Lowering `nfe_step` can speed up MPS generation, with an audio-quality tradeoff.
- Keep F5-TTS optional. It is a PyTorch dependency stack, not part of the default MLX-only install, and the default pretrained weights are CC-BY-NC 4.0.

---
