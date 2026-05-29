# Voice Cloning TTS Landscape — 2026 Research

NotebookLM deep research over 60 sources from arXiv, HuggingFace, project repos, and review articles. Captured 2026-04-30. Source notebook: `tts-research` alias in NLM (notebook id `0ef2077d-15dc-4f17-a68a-b583bfe2ee00`).

## Already shipping in afterwords

- **Qwen3-TTS** (0.6B + 1.7B) — Apache-2.0, native MLX, 24 kHz, multilingual
- **Voxtral 4B** — CC-BY-NC, MLX, preset-only (cloning blocked upstream — see issue #45 / Blaizzy/mlx-audio#694)

> Note (updated 2026-05-29): Chatterbox and VoxCPM were removed in commit f03e826 — they failed the listen-test and VoxCPM additionally returned HTTP 500 on the launchd-managed server. They no longer ship.

## Tier A — local M5 (32 GB unified memory)

14 models that accept reference WAV input AND have an Apple Silicon path (native MLX or PyTorch+MPS). Per-model implementation plans in this directory.

| Model | License | Size | SR | Langs | Notes |
|---|---|---|---|---|---|
| [XTTS v2](xtts-v2.md) | CPML (non-commercial) | 0.47B / 1.8 GB | 24k | 17 langs | Coqui's flagship |
| [CosyVoice2-0.5B](cosyvoice2.md) | Apache-2.0 | 0.5B | — | multi | Streaming, ~150ms latency |
| [F5-TTS](f5-tts.md) | CC-BY-NC | 0.34B | 24k | multi | Flow-matching DiT |
| [IndexTTS-2](indextts-2.md) | Open Source | — | — | multi | Duration control + emotion |
| [Spark-TTS](spark-tts.md) | Open Source | 0.5B | — | multi | LLM + BiCodec |
| [Dia2](dia2.md) | Apache-2.0 | 1.6B | 44k | en | Multi-speaker dialogue focus |
| [YourTTS](yourtts.md) | Open Source | — / 1.0 GB | 16k | en/fr/pt | VITS-based, lightweight |
| [OpenVoice v2](openvoice-v2.md) | MIT | — | — | multi | Tone-color + style decoupled |
| [FireRedTTS-2](firered-tts-2.md) | Open Source | 1.5B | — | multi | Long conversational |
| [SV2TTS](sv2tts.md) | Open Source | — | — | en | Classic 5-second cloning |
| [MockingBird](mockingbird.md) | Open Source | <0.5 GB | 22k | zh/en | Chinese-focused SV2TTS extension |
| [GPT-SoVITS](gpt-sovits.md) | Open Source | — | — | multi | High community traction |
| [SoproTTS](soprotts.md) | Open Source | 0.135B | 24k | en | Lightweight zero-shot cloning |
| [NeuTTS Air](neutts-air.md) | Apache-2.0 | 0.75B | 24k | en | On-device GGUF (llama.cpp) |

## Tier B — Google Colab (GPU, too large for M5)

2 models that need a real GPU (CUDA/A100) — see Colab notebooks under `colab/`:

| Model | License | Size | Runtime | Notebook |
|---|---|---|---|---|
| Fish Speech S2 Pro | Proprietary | 4.4B | A100 ~15 min | [colab/fish-speech-s2-pro.ipynb](../../../colab/fish-speech-s2-pro.ipynb) |
| Llasa-8B | Apache-2.0 | 8B | A100 ~20 min | [colab/llasa-8b.ipynb](../../../colab/llasa-8b.ipynb) |

## Tier C — skip

Closed/cloud-only (ElevenLabs, PlayHT, Murf, Cartesia Sonic 3, Azure CNV, Google Cloud TTS, Inworld, Hume Octave 2, MiniMax, Speechify, WellSaid, Lovo, DupDub, Descript Overdub) — no path to integrate as a self-hosted backend. Useful as quality benchmarks, not as candidates.

Preset-only open models (Bark, Parler-TTS, Piper, Kokoro, StyleTTS 2, MeloTTS, ChatTTS, VibeVoice, OpenAI TTS) — synthesize from text + speaker ID, but don't accept a reference WAV at inference. Could be added as preset backends but don't extend cloning capability.

## How these plans were generated

1. `nlm research start --mode deep` over the topic prompt → 60 imported sources
2. `nlm query notebook tts-research <prompt>` to extract the structured model list
3. Re-query with sharper criteria (the first pass conflated "REST API exists" with "Python API accepts reference WAV")
4. Filter against the 5 backends afterwords already ships
5. Batch-query NLM for all 14 local plans + 2 Colab plans

Reproducible — full prompts archived at `/tmp/local-plans-prompt.md`, `/tmp/colab-prompt.md`, raw NLM responses at `/tmp/local-plans.json`, `/tmp/colab-plans.json`.

## Recommended ship order

If we wire all 14 in, do them in this order based on community traction × license × likelihood-of-quality:

1. **OpenVoice v2** — MIT, 2024 still SOTA for tone-color transfer
2. **F5-TTS** — flow-matching DiT, very natural results (license blocks commercial use though)
3. **CosyVoice2-0.5B** — Apache-2.0, streaming latency story
4. **GPT-SoVITS** — huge community, well-documented
5. **XTTS v2** — battle-tested, multilingual; CPML restricts commercial deployment
6. **IndexTTS-2** — emotion control is a differentiator
7. **NeuTTS Air** — on-device specialized; smallest VRAM footprint
8. Rest as time/interest allows.

Each integration: ~1-2 hours codex-driven if the upstream Python API is clean (it's clean for #1-#5).
