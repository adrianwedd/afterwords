# First successful speech on Studio

Afterwords serves local voice-cloning TTS over HTTP on Apple Silicon. The supported baseline is ARM-native Python 3.11+, at least 16 GiB RAM (32 recommended), Qwen3 0.6B, bundled voices, and loopback port 7860. Python dependency resolution on newer versions is not proof of MLX compatibility; Python 3.11 is the CI reference. No tested macOS minimum or upper Python runtime bound is established yet.

Run `bash setup.sh --preflight` first. It reads architecture, Python architecture/version, RAM, available disk, destination permissions, macOS version, bundled voice presence, and port ownership. It neither installs packages nor writes configuration. A busy port with no Afterwords identity fails closed; an older server without the identity field needs operator investigation before setup.

Reserve at least 6 GiB of free disk for the baseline environment and model cache; this is a conservative planning allowance, not a measured download size. The baseline model is `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit`, approximately 1.5 GiB resident memory. Optional `--with-1.7b` adds `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`, approximately 3.5 GiB total resident memory. Exact download sizes/revisions are not locked. The default Hugging Face cache is `~/.cache/huggingface/hub` (environment overrides can relocate it). Local inference needs no cloud API key; initial package/model downloads use the network.

Run `bash setup.sh --server-only`. Setup installs baseline Python dependencies into `.venv`, creates `~/Library/LaunchAgents/com.afterwords.tts-server.plist`, installs `/usr/local/bin/afterwords`, and loads the login service. It replaces the existing service configuration and restarts it. It does not install cloning tools or hooks. Ensure `/usr/local/bin` is on PATH and its permissions permit creating the symlink; otherwise setup may need sudo. Missing bundled voices fail rather than prompting for a YouTube URL.

The plist preserves backend selection across service startup and regeneration. Only Qwen 0.6B loads by default; `--with-1.7b` additionally selects 1.7B. For experimental backends set `BACKENDS=qwen3-0.6b,<backend-name>` in `~/.afterwords-server` before setup/configure. An explicit `AFTERWORDS_BACKENDS` environment variable can select backends during initial setup. Unknown names fail at server startup. Registration in `/health` does not imply availability or successful loading: an unselected backend has `state=registered`, `available=null`, and `loaded=false`. Selected failures abort startup. Warmup synthesis must succeed before normal startup declares readiness; `--no-warmup` is a diagnostic bypass, not installation acceptance.

Setup waits up to 60 seconds for the service and then requires HTTP-success synthesis plus valid, non-silent audio. A cold download may exceed that wait; setup exits unsuccessfully and leaves the service downloading. Inspect `afterwords logs` and `afterwords status` before rerunning. Do not start a second model-loading process merely because the wait expired.

Listen to a separate foreground sample:

```bash
curl --fail --get --data-urlencode 'text=Afterwords is ready to speak.' \
  http://127.0.0.1:7860/synthesize -o /tmp/afterwords-first-speech.wav
.venv/bin/python3 scripts/validate-wav.py /tmp/afterwords-first-speech.wav
afplay /tmp/afterwords-first-speech.wav
```

Confirm the opening words, complete phrase, and absence of long internal silence. WAV validity does not prove fidelity. The leading-word/internal-silence defects reported in issue #122 remain unresolved by this onboarding work.

Only after foreground speech passes, enable one integration. `bash setup.sh --integrations` performs interactive discovery; Codex uses `bash setup-codex.sh` inside an interactive session, while Hermes has separate instructions in `docs/hermes-integration.md`. Confirm one final response speaks once and produces its expected local archive. Integration acceptance has not been established by server unit tests.

Exercise `afterwords mute` twice (mute/unmute), then operator-authorized stop/start and repeat synthesis. Mute suppresses automatic playback while synthesis and archives continue; foreground samples still play. Archives persist spoken text/audio under each agent's home directory. Optional cloud commands can upload voice data and use `~/.afterwords-cloud`; their privacy boundary differs from local inference.

Remaining audit work includes separating gallery reload permissions from upload cloning, reconciling the full integration matrix and Hermes guidance, dependency/model reproducibility, and live macOS/launchd/audio/integration acceptance. `afterwords reload` still requires a server launched with `--allow-clone`; HTTP failures now return nonzero.
