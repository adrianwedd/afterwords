## CosyVoice2-0.5B

**Repo:** https://github.com/FunAudioLLM/CosyVoice
**License:** Apache-2.0
**Size:** 0.5B, 2.0 GB
**Sample rate:** 24000
**Languages:** multilingual (Chinese, English, Japanese, Korean, German, Spanish, French, Italian, Russian)
**Apple Silicon path:** PyTorch+MPS/CPU fallback — upstream disables CUDA-only acceleration flags when CUDA is unavailable; ONNX frontend/tokenizer sessions run on CPU on macOS.

### Install
```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
pip install -r requirements.txt
```

### Model download
```bash
huggingface-cli download FunAudioLLM/CosyVoice2-0.5B --local-dir backends/extras/cosyvoice2/CosyVoice2-0.5B
```
Disk: 2.0 GB

### Python API for cloning
```python
from cosyvoice.cli.cosyvoice import CosyVoice2
import torchaudio

cosyvoice = CosyVoice2('pretrained_models/CosyVoice2-0.5B')
for i, output in enumerate(cosyvoice.inference_zero_shot(
    'This is a test sentence.',
    'This is the text spoken in the reference audio.',
    'reference.wav',
    stream=False,
)):
    torchaudio.save(f'output_{i}.wav', output['tts_speech'], cosyvoice.sample_rate)
```

### Backend protocol skeleton
```python
# backends/cosyvoice2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class CosyVoice2Backend(BackendBase):
    name = "cosyvoice2"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("en", "zh", "ja", "ko", "de", "es", "fr", "it", "ru")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- CosyVoice2 strictly requires the `prompt_text` (transcript of the reference audio) to align semantic tokens during the zero-shot cloning phase. In `prepare_voice`, enforce the presence of `ref_text`.
- Current upstream `CosyVoice2.inference_zero_shot` takes `(tts_text, prompt_text, prompt_wav, zero_shot_spk_id='', stream=False, speed=1.0, text_frontend=True)`. The frontend calls `load_wav(prompt_wav, 16000)` for speech token extraction and `load_wav(prompt_wav, 24000)` for speech features internally, so Afterwords can pass the reference WAV path directly rather than preloading a `prompt_speech_16k` tensor.
- Do not auto-download weights from the backend during normal server startup. Require a local model directory (default `backends/extras/cosyvoice2/CosyVoice2-0.5B`) or `COSYVOICE2_MODEL_DIR`.

---
