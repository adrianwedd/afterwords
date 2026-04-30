## MockingBird

**Repo:** https://github.com/babysor/MockingBird
**License:** Open Source
**Size:** <0.5 GB
**Sample rate:** 22050
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: Same architectural constraints as SV2TTS; focus on Mandarin compatibility.

### Install
```bash
git clone https://github.com/babysor/MockingBird.git
cd MockingBird
pip install -r requirements.txt
```

### Model download
```bash
# Requires downloading checkpoint via Google Drive/Baidu links provided in the repo
```
Disk: 0.5 GB

### Python API for cloning
```python
from encoder import inference as encoder
from synthesizer.inference import Synthesizer
from vocoder import inference as vocoder

encoder.load_model("models/encoder.pt")
synthesizer = Synthesizer("models/synthesizer.pt")
vocoder.load_model("models/vocoder.pt")

embed = encoder.embed_utterance(encoder.preprocess_wav("reference.wav"))
specs = synthesizer.synthesize_spectrograms(["This is a test sentence."], [embed])
audio = vocoder.infer_waveform(specs)
```

### Backend protocol skeleton
```python
# backends/mockingbird.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class MockingBirdBackend(BackendBase):
    name = "mockingbird"
    sample_rate = 22050
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- MockingBird operates on identical logic to SV2TTS but integrates language-specific grapheme-to-phoneme parsing specifically suited to Chinese datasets. The main implementation difference from SV2TTS for your `afterwords` backend is the front-end text normalization. Ensure your text handling in `synthesize` successfully supports the localized tokenizer required by the MockingBird synthesizer, and similarly watch out for WaveRNN generation speeds on MPS.

---
