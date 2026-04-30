## Dia2

**Repo:** https://github.com/NariLabs/Dia2
**License:** Apache-2.0
**Size:** 1.6B, 5.0 GB
**Sample rate:** 44000
**Languages:** en-only
**Apple Silicon path:** PyTorch+MPS — Note: Handles dialogue formatting natively; larger parameter count but highly optimized for single-stream text.

### Install
```bash
pip install dia-tts torch torchaudio
```

### Model download
```bash
huggingface-cli download NariLabs/Dia2
```
Disk: 5.0 GB

### Python API for cloning
```python
from dia import DiaModel

dia = DiaModel.from_pretrained("NariLabs/Dia2").to("mps")
audio_data = dia.generate(
    "This is a test sentence.", 
    audio_prompt="reference.wav"
)
```

### Backend protocol skeleton
```python
# backends/dia2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class Dia2Backend(BackendBase):
    name = "dia_2"
    sample_rate = 44000
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("en",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- Dia2 is optimized for multi-speaker dialogues and supports embedded nonverbal tags like `(laughs)`. In your afterwords pipeline, you can largely ignore `ref_text` and just pass `audio_prompt`. However, when sending the `text` string to `synthesize`, you should be aware of the `[S1]` / `[S2]` speaker tag formatting that Dia2 expects. You may need to prepend your input string with `[S1]` implicitly within the backend to ensure it treats the cloned reference as the primary active speaker.

---
