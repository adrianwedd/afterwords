## NeuTTS Air

**Repo:** Proprietary (Neuphonic SDK/CLI)
**License:** Proprietary
**Size:** 0.748B, 1.5 GB
**Sample rate:** 24000
**Languages:** en-only
**Apple Silicon path:** CPU-only — Note: This is an on-device embedded engine packaged with compiled libraries specifically optimized to run without cloud reliance or heavy GPU scaffolding.

### Install
```bash
# Requires an SDK license and proprietary wheel file from Neuphonic
pip install neuphonic-air-sdk
```

### Model download
```bash
# Provided securely via SDK initialization or authenticated endpoint
neuphonic download --model air-0.7b
```
Disk: 1.5 GB

### Python API for cloning
```python
from neuphonic import NeuTTS

model = NeuTTS(model_name="air-0.7b")
audio = model.synthesize(
    text="This is a test sentence.",
    ref_audio="reference.wav"
)
```

### Backend protocol skeleton
```python
# backends/neutts_air.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class NeuTTSAirBackend(BackendBase):
    name = "neutts_air"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.IGNORED
    supported_langs = ("en",)

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- As a proprietary model running highly compressed CoreML or specialized CPU operations, NeuTTS Air sidesteps standard PyTorch/MPS bottlenecks completely. Its integration will likely be the most stable of the bunch for the M5 due to its specialized environment. The main quirk here is managing the SDK authentication logic (if required) within the `load` function, and verifying that threading models inside afterwords don't conflict with Neuphonic's compiled C++ bindings execution lock.
