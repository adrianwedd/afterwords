## CosyVoice2-0.5B

**Repo:** https://github.com/FunAudioLLM/CosyVoice
**License:** Apache-2.0
**Size:** 0.5B, 2.0 GB
**Sample rate:** 22050
**Languages:** multilingual
**Apple Silicon path:** PyTorch+MPS — Note: Fully supports MPS, but may require specific ONNX runtime configurations for frontend grapheme-to-phoneme conversion.

### Install
```bash
git clone https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
pip install -r requirements.txt
pip install torch torchaudio
```

### Model download
```bash
huggingface-cli download FunAudioLLM/CosyVoice2-0.5B
```
Disk: 2.0 GB

### Python API for cloning
```python
from cosyvoice.cli.cosyvoice import CosyVoice
from cosyvoice.utils.file_utils import load_wav
import torchaudio

cosyvoice = CosyVoice('pretrained_models/CosyVoice2-0.5B')
prompt_speech_16k = load_wav('reference.wav', 16000)
output = cosyvoice.inference_zero_shot(
    'This is a test sentence.', 
    prompt_text='This is the text spoken in the reference audio.', 
    prompt_speech_16k=prompt_speech_16k
)
torchaudio.save('output.wav', output['tts_speech'], 22050)
```

### Backend protocol skeleton
```python
# backends/cosyvoice2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class CosyVoice2Backend(BackendBase):
    name = "cosyvoice2"
    sample_rate = 22050
    ref_text_policy = RefTextPolicy.REQUIRED
    supported_langs = ("multilingual",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- CosyVoice2 strictly requires the `prompt_text` (transcript of the reference audio) to align semantic tokens perfectly during the zero-shot cloning phase. In `prepare_voice`, you will need to enforce the presence of `ref_text`. A known quirk on Macs is managing the 16kHz resampling for the prompt audio vs the 22.05kHz generated output—make sure your backend seamlessly resamples user-provided `ref_audio_path` using `torchaudio.transforms.Resample` before sending it into the model.

---
