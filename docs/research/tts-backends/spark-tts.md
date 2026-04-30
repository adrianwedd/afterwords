## Spark-TTS

**Repo:** https://github.com/SparkAudio/Spark-TTS
**License:** Code is Apache-2.0; `SparkAudio/Spark-TTS-0.5B` weights are CC-BY-NC-SA 4.0, non-commercial
**Size:** 0.5B, 2.0 GB
**Sample rate:** 24000
**Languages:** en/zh, with cross-lingual and code-switching cloning examples upstream
**Apple Silicon path:** PyTorch+MPS via `SPARK_TTS_DEVICE=mps`; upstream primarily documents Linux/CUDA, so expect occasional `PYTORCH_ENABLE_MPS_FALLBACK=1` use on Apple Silicon.

### Install
```bash
git clone https://github.com/SparkAudio/Spark-TTS.git
cd Spark-TTS
pip install -r requirements.txt
```

### Model download
```bash
huggingface-cli download SparkAudio/Spark-TTS-0.5B
```
Disk: 2.0 GB

### Python API for cloning
```python
from pathlib import Path
import torch
from cli.SparkTTS import SparkTTS

model = SparkTTS(Path("pretrained_models/Spark-TTS-0.5B"), device=torch.device("mps"))
wav_out = model.inference(
    text="This is a test sentence.",
    prompt_speech_path=Path("reference.wav"),
    prompt_text=None,
)
```

### Backend protocol skeleton
```python
# backends/spark_tts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class SparkTTSBackend(BackendBase):
    name = "spark-tts"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "zh")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- Spark-TTS introduces BiCodec, treating semantic and acoustic global speaker tokens distinctly. For cloning, providing reference audio handles the acoustic speaker token matching implicitly, bypassing the strict necessity for transcripts, although some community scripts allow transcript hints. The biggest implementation quirk will be making sure the BiCodec extracts the correct fixed-length global tokens during `prepare_voice` so that `synthesize` doesn't have to re-evaluate the reference audio on every single text chunk.

---
