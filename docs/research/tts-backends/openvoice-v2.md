## OpenVoice v2

**Repo:** https://github.com/myshell-ai/OpenVoice
**License:** MIT
**Size:** 0.5B, 2.0 GB
**Sample rate:** 24000
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: OpenVoice essentially acts as a timbre filter applied over a base TTS model (like MeloTTS).

### Install
```bash
git clone https://github.com/myshell-ai/OpenVoice.git
cd OpenVoice
pip install -r requirements.txt
pip install melo-tts
```

### Model download
```bash
huggingface-cli download myshell-ai/OpenVoiceV2
```
Disk: 2.0 GB

### Python API for cloning
```python
import torch
from openvoice import se_extractor
from openvoice.api import ToneColorConverter
from melo.api import TTS

# 1. Base TTS generation
model = TTS(language='EN', device='mps')
speaker_ids = model.hps.data.spk2id
model.tts_to_file("This is a test sentence.", speaker_ids['EN-Default'], 'base.wav')

# 2. Tone color conversion (Cloning)
tone_color_converter = ToneColorConverter('checkpoints_v2/converter', device='mps')
target_se, audio_name = se_extractor.get_se('reference.wav', tone_color_converter, target_dir='processed', vad=True)
base_se, _ = se_extractor.get_se('base.wav', tone_color_converter, target_dir='processed', vad=True)

tone_color_converter.convert('base.wav', base_se, target_se, 'output.wav')
```

### Backend protocol skeleton
```python
# backends/openvoice_v2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class OpenVoiceV2Backend(BackendBase):
    name = "openvoice_v2"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- OpenVoice's architecture separates style/prosody (handled by a base TTS engine like MeloTTS) from tone color (handled by the converter). Thus, `load` must instantiate *two* models. `prepare_voice` should execute `se_extractor.get_se` to pull the reference audio's tone color embedding. In `synthesize`, you will first generate the raw audio using the base TTS and its default speaker embedding, then pass that output through the converter applying the cached target tone color. Ensure intermediate `base.wav` files are either written to memory buffers (like `io.BytesIO`) or temporary files to avoid disk IO bottlenecks.

---
