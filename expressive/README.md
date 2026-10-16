# Expressive sidecar (experimental)

Built with Fish Audio. This implementation uses the Fish Audio Community License
v1.0 model and an unofficial MLX conversion. Model code and weight pins are in
`contracts.py`. No experimental packages are installed in Afterwords' main venv.

Current status: source failure-path tests pass; real synthesis and listening
qualification are pending. Do not interpret adapter registration/readiness as
model residency or acoustic acceptance.

## Run locally

From the Afterwords repository, install the pinned MLX Audio source in
`.venv-drama3`, download the pinned model, then run:

```sh
uv venv --python 3.12 .venv-drama3
uv pip install --python .venv-drama3/bin/python -r requirements-drama3.txt
hf download mlx-community/fish-audio-drama-3-4bit --revision cc639e27aba7edb73429d3e3806f471dcd79d316
.venv-drama3/bin/python -m expressive.sidecar
```

This binds only `127.0.0.1:7861`. `/health` reports the worker process and queue;
`POST /synthesize` accepts `text`, base64 `reference_wav`, `reference_text`, and
optional `performance`. It returns complete PCM16 mono 44.1 kHz WAV. The worker
uses actual native generation chunks internally, but this HTTP endpoint returns
only the finished file. It does not claim live playback or public streaming.

The persistent child process loads weights only on first use and runs offline.
It caches up to four reference files/conditioning contexts. Admission is bounded
to four requests including active work; queue plus generation deadline is 180s.
A timeout or disconnected client kills the worker before admitting the next
request. Failed requests return no partial audio. The child has a 40 GiB MLX
allocation limit and 2 GiB cache limit; startup requires 32 GiB available host
memory. This is admission control, not proof that concurrent inference has no
latency impact. Measure that separately.

## Afterwords integration

`fish-drama3` is registered but is not selected or loaded by default. An opt-in
voice uses the existing `backend: "fish-drama3"` metadata plus `synthesis_extras`.
Enable it through the existing `AFTERWORDS_BACKENDS` mechanism only after local
qualification. Existing Qwen defaults and voice profiles need no change.

Supported controls: `temperature` (0.1–1.5), `top_p` (0.1–1), `top_k` (1–100),
`max_frames` (16–4000 per text chunk), `seed`, and `cues`, e.g.
`[{"offset": 0, "cue": "whispers"}]`. Cues are separate from the authoritative
transcript and inserted at character offsets at word boundaries. Allowed names
are in `contracts.py`; acceptance of a cue is not proof of expressive effect.
Free-form `instruct`, speed changes, revision and infilling are not supported.

Per-request controls override voice defaults via the optional GET `performance`
JSON parameter, or POST `performance` object on the existing clone-enabled POST
route. They never mutate the prepared voice. Controls on other backends fail
explicitly. GET retains its existing 5000-character input limit.

The adapter uses a fixed loopback URL with HTTP proxies disabled. If the sidecar
is unavailable, full-text Qwen fallback is enabled by default; set per-voice or
per-request `qwen_fallback: false` to fail instead. Fallback uses the original
transcript, not delivery tags. `X-Backend` names the backend that actually
produced the WAV and `X-Requested-Backend` names the selected voice backend.
A fallback may therefore return Qwen's 24 kHz audio; consumers must read WAV
metadata. Logs also identify fallback. Invalid requests are not disguised as
availability failures.

The main server admits at most four expressive requests waiting for its shared
MLX lock, with a 180s lock deadline. Qwen's existing serialization remains.
The sidecar deadline starts when its request arrives, so the two stages have
separate budgets. Cancelling the sidecar request cancels synthesis; cancellation
of an existing synchronous Afterwords consumer still needs integration testing.

## References and release

Use original synthetic or explicitly consented reference voices. The existing
identifiable-person voice library is not a public-use permission registry.
Model-use permission, ownership of generated output and reference-voice rights
are separate. Keep this service local; public sites receive reviewed static
assets only. The model's license/attribution does not grant reference rights.
See `qa/expressive-voice/FISH_AUDIO_LICENSE.txt` for the inspected license.

## Verification and rollback

```sh
.venv/bin/python -m pytest tests/test_expressive.py tests/test_backends.py tests/test_server.py
.venv-drama3/bin/python scripts/benchmark-drama3.py --text 'Well. That worked.' --output qa/expressive-voice/sample.wav
```

The probe refuses to overwrite attempts, records model/text/reference/audio
hashes and TTFA/RTF/memory, and treats upstream frame exhaustion as failure.
Its timeout is cooperative; production hard cancellation belongs to the
sidecar. A successful WAV remains `generated_not_listening_verified`.

Rollback: stop the separately launched sidecar and remove its opt-in routing.
Existing Qwen service remains usable. Restore only configuration files changed
for activation, from their recorded pre-activation copies. No live routing or
activation has been performed at this checkpoint.

The Hermes command provider accepts `AFTERWORDS_PORT` for a profile-local
loopback route, for example `env AFTERWORDS_PORT=7862 bash
/path/to/afterwords-tts-command.sh {input_path} {output_path} voice-name`.
It defaults to 7860 and rejects invalid ports before synthesis. A remote profile
can use an independently verified SSH loopback forward; this setting does not
permit arbitrary remote URLs or change the default Hermes profile. Actual
Vixen configuration is on M5; do not create a replacement profile on Studio.

Original voice candidates can be generated without any human reference:

```sh
.venv-drama3/bin/python scripts/generate-original-references.py --name cast-aster:101 --name stage-manager:100
```

Candidates and receipts remain under QA until transcript and acoustic review.
The generator preserves every attempt, records unconditioned provenance and
pins, and never promotes a generated file directly to a public reference.
