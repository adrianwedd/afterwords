## IndexTTS-2

**Repo:** https://github.com/index-tts/index-tts
**Weights:** https://huggingface.co/IndexTeam/IndexTTS-2
**License:** `LicenseRef-Bilibili-IndexTTS` (bilibili Model Use License; usage restrictions)
**Size:** 1.5B, ~3.0 GB
**Sample rate:** 22050
**Languages:** en/zh in the current upstream package
**Apple Silicon path:** PyTorch+MPS — upstream supports MPS device selection, but disables fp16 on MPS.

### Install
```bash
git clone https://github.com/index-tts/index-tts.git
cd index-tts
uv sync --all-extras
```

### Model download
```bash
huggingface-cli download IndexTeam/IndexTTS-2 --local-dir checkpoints
```
Disk: 3.0 GB

### Python API for cloning
```python
from indextts.infer_v2 import IndexTTS2

tts = IndexTTS2(
    cfg_path="checkpoints/config.yaml",
    model_dir="checkpoints",
    use_fp16=False,
    use_cuda_kernel=False,
    use_deepspeed=False,
)
audio = tts.infer(
    spk_audio_prompt="reference.wav",
    text="This is a test sentence.",
    output_path=None,
)
```

### Backend protocol skeleton
```python
# backends/indextts_2.py
from backends.base import BackendBase, PreparedVoice, RefTextPolicy, _read_only

class IndexTTS2Backend(BackendBase):
    name = "indextts-2"
    sample_rate = 22050
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en", "zh")

    def load(self): ...
    def prepare_voice(self, ref_audio_path, ref_text, extras): ...
    def synthesize(self, text, prepared, lang): ...
```

### Notes for afterwords integration
- IndexTTS-2 specializes in auto-regressive zero-shot cloning with emotional control. Upstream describes precise duration control, but the 2025/09/08 README notes that duration control was "not yet enabled in this release"; expose currently available generation controls such as `max_mel_tokens`, `max_text_tokens_per_segment`, and sampling parameters rather than inventing a hard duration API.
- Emotion controls are exposed by upstream as `emo_audio_prompt`, `emo_alpha`, `emo_vector`, `use_emo_text`, `emo_text`, and `use_random`.
- The package may download auxiliary upstream dependencies such as semantic codec assets on first model construction. Afterwords should not download the IndexTTS-2 checkpoints itself; require a local `INDEXTTS2_MODEL_DIR` or the default `backends/extras/indextts-2/checkpoints`.

---
