## Real-Time Voice Cloning / SV2TTS

**Repo:** https://github.com/CorentinJ/Real-Time-Voice-Cloning
**License:** Open Source
**Size:** <0.5 GB
**Sample rate:** 22050
**Languages:** en-only
**Apple Silicon path:** PyTorch+MPS — Note: Very old repository (Tacotron-based); some dependencies might need tweaking for modern MPS PyTorch.

### Install
```bash
git clone https://github.com/CorentinJ/Real-Time-Voice-Cloning.git
cd Real-Time-Voice-Cloning
pip install -r requirements.txt
```

### Model download
```bash
# Uses a manual download script inside the repository
python download_models.py
```
Disk: 0.5 GB

### Python API for cloning
```python
from encoder import inference as encoder
from synthesizer.inference import Synthesizer
from vocoder import inference as vocoder

encoder.load_model("encoder/saved_models/pretrained.pt")
synthesizer = Synthesizer("synthesizer/saved_models/pretrained/pretrained.pt")
vocoder.load_model("vocoder/saved_models/pretrained/pretrained.pt")

embed = encoder.embed_utterance(encoder.preprocess_wav("reference.wav"))
specs = synthesizer.synthesize_spectrograms(["This is a test sentence."], [embed])
audio = vocoder.infer_waveform(specs)
```

### Backend protocol skeleton
```python
# backends/sv2tts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class SV2TTSBackend(BackendBase):
    name = "sv2tts"
    sample_rate = 22050
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("en",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- This is the classic 3-stage SV2TTS model. Because of its older architecture, `load()` must load three distinct models: Encoder, Synthesizer, and Vocoder. `prepare_voice` should convert the audio path to the unified speaker embedding matrix using the encoder. The crucial point to test is whether `vocoder.infer_waveform` functions correctly natively on MPS; WaveRNN operations can be notoriously slow or mathematically tricky on Apple Silicon, so falling back to CPU explicitly for the vocoder pass might be required for stability.

---
