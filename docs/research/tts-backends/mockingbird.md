## MockingBird

**Repo:** https://github.com/babysor/MockingBird
**License:** Open Source
**Size:** <0.5 GB
**Sample rate:** 22050
**Languages:** zh/en (multilingual toolkit; Chinese strongest)
**Apple Silicon path:** PyTorch+MPS fallback — same architectural constraints as SV2TTS; focus on Mandarin compatibility.
**Reference text policy:** OPTIONAL

### Install
```bash
git clone https://github.com/babysor/MockingBird.git
cd MockingBird
pip install -r requirements.txt
pip install cn2an
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
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("zh", "en")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- MockingBird operates on the same encoder + Tacotron synthesizer + WaveRNN vocoder shape as SV2TTS, but its tooling and pretrained ecosystem are Chinese-focused.
- Keep source and checkpoint paths separate from SV2TTS because both projects expose top-level `encoder`, `synthesizer`, and `vocoder` modules.
- Do not trigger upstream demo downloads from the backend. Require local source under `backends/extras/mockingbird/MockingBird` and local checkpoint files under `backends/extras/mockingbird/saved_models/default`.
- `cn2an` is useful for Chinese number normalization, but the backend should still delegate text handling to the upstream synthesizer rather than doing ad hoc normalization in Afterwords.

---
