## Real-Time Voice Cloning / SV2TTS

**Repo:** https://github.com/CorentinJ/Real-Time-Voice-Cloning
**License:** Open Source
**Size:** <0.5 GB
**Sample rate:** 22050
**Languages:** en-only
**Apple Silicon path:** PyTorch CPU/MPS hybrid — Note: Very old repository (Tacotron-based). The encoder can be directed to MPS, but the upstream synthesizer and WaveRNN vocoder still choose CUDA-or-CPU internally, so CPU fallback is the reliable default on Apple Silicon.

### Install
```bash
git clone https://github.com/CorentinJ/Real-Time-Voice-Cloning.git
cd Real-Time-Voice-Cloning
uv sync --extra cpu
```

### Model download
```bash
# Upstream demo code can ensure/download defaults, but the Afterwords backend
# intentionally does not download. Put local files here or set env overrides:
mkdir -p backends/extras/sv2tts/saved_models/default
# encoder.pt, synthesizer.pt, vocoder.pt
```
Disk: 0.5 GB

### Python API for cloning
```python
from pathlib import Path
from encoder import inference as encoder
from synthesizer.inference import Synthesizer
from vocoder import inference as vocoder

encoder.load_model(Path("saved_models/default/encoder.pt"))
synthesizer = Synthesizer(Path("saved_models/default/synthesizer.pt"))
vocoder.load_model(Path("saved_models/default/vocoder.pt"))

embed = encoder.embed_utterance(encoder.preprocess_wav("reference.wav"))
specs = synthesizer.synthesize_spectrograms(["This is a test sentence."], [embed])
audio = vocoder.infer_waveform(specs[0])
```

### Backend protocol skeleton
```python
# backends/sv2tts.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class SV2TTSBackend(BackendBase):
    name = "sv2tts"
    sample_rate = 22050
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def load(self): ...
    def validate_extras(self, extras): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- This is the classic 3-stage SV2TTS model. Because of its older architecture, `load()` must load three distinct models: Encoder, Synthesizer, and Vocoder. `prepare_voice` should convert the audio path to a speaker embedding using the encoder. The backend must keep upstream imports lazy and must not call upstream model-download helpers. The crucial runtime risk is WaveRNN speed/stability on Apple Silicon; CPU fallback is expected unless upstream grows a first-class MPS path.

---
