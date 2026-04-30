## FireRedTTS-2

**Repo:** https://github.com/FireRedTeam/FireRedTTS
**License:** Open Source
**Size:** 1.5B, 3.0 GB
**Sample rate:** 24000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: Handles long conversational generation well; entirely viable on M5 given enough context buffer.

### Install
```bash
git clone https://github.com/FireRedTeam/FireRedTTS.git
cd FireRedTTS
pip install -r requirements.txt torch torchaudio
```

### Model download
```bash
huggingface-cli download FireRedTeam/FireRedTTS-2
```
Disk: 3.0 GB

### Python API for cloning
```python
from fireredtts import FireRedTTS

model = FireRedTTS.from_pretrained("FireRedTeam/FireRedTTS-2").to("mps")
audio = model.synthesize(
    text="This is a test sentence.",
    ref_audio="reference.wav"
)
```

### Backend protocol skeleton
```python
# backends/fireredtts_2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class FireRedTTS2Backend(BackendBase):
    name = "fireredtts_2"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- Designed heavily for podcast and conversational chatbot style output, FireRedTTS-2 often anticipates long inputs. When adapting it for afterwords, its default context window handles large semantic chunks automatically, but you should still implement chunking to avoid OOM memory peaks on MPS if input texts exceed typical sentence structures. Providing a `ref_text` is optional but has been shown to improve the speaker timbre consistency during zero-shot cloning.

---
