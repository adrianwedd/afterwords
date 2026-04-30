## FireRedTTS-2

**Repo:** https://github.com/FireRedTeam/FireRedTTS2
**License:** Apache-2.0
**Size:** 1.5B, ~3.0 GB
**Sample rate:** 24000
**Languages:** en, zh, ja, ko, fr, de, ru
**Apple Silicon path:** PyTorch+MPS — upstream is CUDA-first, but the backend enables MPS fallback and allows `FIRERED_TTS_2_DEVICE=mps/cpu/cuda`.

### Install
```bash
git clone https://github.com/FireRedTeam/FireRedTTS2.git
cd FireRedTTS2
pip install -e .
pip install -r requirements.txt torch torchaudio torchvision
```

### Model download
```bash
git lfs install
git clone https://huggingface.co/FireRedTeam/FireRedTTS2 pretrained_models/FireRedTTS2
```
Disk: 3.0 GB

### Python API for cloning
```python
from fireredtts2.fireredtts2 import FireRedTTS2

model = FireRedTTS2(
    pretrained_dir="./pretrained_models/FireRedTTS2",
    gen_type="monologue",
    device="mps",
)
audio = model.generate_monologue(
    text="This is a test sentence.",
    prompt_wav="reference.wav",
    prompt_text=None,
)
```

### Backend protocol skeleton
```python
# backends/firered_tts_2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class FireRedTTS2Backend(BackendBase):
    name = "firered-tts-2"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "zh", "ja", "ko", "fr", "de", "ru")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- Designed heavily for podcast and conversational chatbot style output, FireRedTTS-2 often anticipates long inputs. When adapting it for afterwords, its default context window handles large semantic chunks automatically, but you should still implement chunking to avoid OOM memory peaks on MPS if input texts exceed typical sentence structures. Providing a `ref_text` is optional but has been shown to improve the speaker timbre consistency during zero-shot cloning.

---
