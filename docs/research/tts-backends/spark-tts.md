## Spark-TTS

**Repo:** https://github.com/Spark-TTS/Spark-TTS
**License:** Open Source
**Size:** 0.5B, 2.0 GB
**Sample rate:** 24000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: Model architecture leverages a decoupled token approach which translates nicely to standard PyTorch MPS ops.

### Install
```bash
git clone https://github.com/Spark-TTS/Spark-TTS.git
cd Spark-TTS
pip install -r requirements.txt
```

### Model download
```bash
huggingface-cli download Spark-TTS/Spark-TTS-0.5B
```
Disk: 2.0 GB

### Python API for cloning
```python
from sparktts import SparkTTS

model = SparkTTS.from_pretrained("Spark-TTS/Spark-TTS-0.5B").to("mps")
wav_out = model.generate(
    text="This is a test sentence.",
    prompt_audio="reference.wav"
)
```

### Backend protocol skeleton
```python
# backends/spark_tts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class SparkTTSBackend(BackendBase):
    name = "spark_tts"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- Spark-TTS introduces BiCodec, treating semantic and acoustic global speaker tokens distinctly. For cloning, providing reference audio handles the acoustic speaker token matching implicitly, bypassing the strict necessity for transcripts, although some community scripts allow transcript hints. The biggest implementation quirk will be making sure the BiCodec extracts the correct fixed-length global tokens during `prepare_voice` so that `synthesize` doesn't have to re-evaluate the reference audio on every single text chunk.

---
