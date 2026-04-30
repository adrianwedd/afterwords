## OpenVoice v2

**Repo:** https://github.com/myshell-ai/OpenVoice
**License:** MIT
**Size:** 0.5B, 2.0 GB
**Sample rate:** 22050 (converter `checkpoints_v2/converter/config.json`)
**Languages:** English, Spanish, French, Chinese, Japanese, Korean (native v2 support)
**Apple Silicon path:** PyTorch+MPS/CPU — OpenVoice v2 acts as a tone-color converter applied over a base MeloTTS utterance.

### Install
```bash
git clone https://github.com/myshell-ai/OpenVoice.git
cd OpenVoice
pip install -r requirements.txt
pip install git+https://github.com/myshell-ai/MeloTTS.git
python -m unidic download
```

### Model download
```bash
huggingface-cli download myshell-ai/OpenVoiceV2 --local-dir checkpoints_v2
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
    name = "openvoice-v2"
    sample_rate = 22050
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "es", "fr", "zh", "ja", "ko")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- OpenVoice's architecture separates text/prosody (MeloTTS) from tone color (OpenVoice converter). `load` should instantiate the converter from `checkpoints_v2/converter`, while MeloTTS language models can be cached lazily per language to avoid loading every language at server startup. `prepare_voice` should execute `se_extractor.get_se` to pull the reference audio's tone color embedding. In `synthesize`, generate a temporary base utterance with MeloTTS, load the matching `checkpoints_v2/base_speakers/ses/{speaker}.pth` source embedding, then pass the base WAV through `ToneColorConverter.convert(...)` with the cached target embedding.
- Upstream v2 demo language codes are `EN_NEWEST`, `EN`, `ES`, `FR`, `ZH`, `JP`, and `KR`; Afterwords should expose normal request language tags: `en`, `es`, `fr`, `zh`, `ja`, `ko`.
- The reference transcript is not required by upstream OpenVoice v2 extraction, so Afterwords should advertise `RefTextPolicy.OPTIONAL`.

---
