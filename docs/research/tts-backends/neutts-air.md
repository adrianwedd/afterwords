## NeuTTS Air

**Repo:** https://github.com/neuphonic/neutts
**Model:** https://huggingface.co/neuphonic/neutts-air
**License:** Apache-2.0 for NeuTTS Air model weights; the `neutts` package also
ships NeuTTS Nano models under the NeuTTS Open License 1.0.
**Size:** ~0.7B params / 1.5 GB BF16; Q4/Q8 GGUF quantizations are available.
**Sample rate:** 24000
**Languages:** en-only
**Apple Silicon path:** CPU-first GGUF via `llama-cpp-python` + NeuCodec. This is
not CoreML; upstream recommends Apple Accelerate builds for `llama-cpp-python`.

### Install
```bash
# Requires espeak-ng as a system dependency.
brew install espeak-ng

pip install "neutts[llama,onnx]"
```

### Model download
```bash
# No separate SDK-authenticated download step. The neutts package downloads from
# Hugging Face on first load unless model files are already cached.
```
Disk: 1.5 GB

### Python API for cloning
```python
from neutts import NeuTTS

tts = NeuTTS(
    backbone_repo="neuphonic/neutts-air-q4-gguf",
    backbone_device="cpu",
    codec_repo="neuphonic/neucodec-onnx-decoder",
    codec_device="cpu",
)
ref_codes = tts.encode_reference("reference.wav")
audio = tts.infer("This is a test sentence.", ref_codes, "reference transcript")
```

### Backend protocol skeleton
```python
# backends/neutts_air.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class NeuTTSAirBackend(BackendBase):
    name = "neutts-air"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- NeuTTS Air is open-weight and local; no Neuphonic SDK authentication is
  required.
- Upstream expects reference audio plus reference text. Afterwords can treat the
  transcript as optional for profile compatibility, but quality is best when it
  is present.
- Pre-encode references in `prepare_voice()` with `encode_reference()` so normal
  synthesis only calls `infer(text, ref_codes, ref_text)`.
- Keep imports lazy in `load()` because `neutts` pulls in Torch, Transformers,
  llama-cpp-python, phonemizer, and codec dependencies.

---
