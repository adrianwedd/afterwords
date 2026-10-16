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
allocation limit and 2 GiB cache limit; startup requires 64 GiB available host
memory. This is admission control, not proof that concurrent inference has no
latency impact. Measure that separately.

## Afterwords integration

`fish-drama3` is registered but is not selected or loaded by default. An opt-in
voice uses the existing `backend: "fish-drama3"` metadata plus `synthesis_extras`.
Enable it through the existing `AFTERWORDS_BACKENDS` mechanism only after local
qualification. Existing Qwen defaults and voice profiles need no change.

An independent Afterwords instance can use `--port 7862 --voices-dir PRIVATE_DIR`
with `AFTERWORDS_BACKENDS=qwen3-0.6b,fish-drama3`. That existing directory must
contain its own profile JSON and reference WAV files; reference paths stay
confined to it. Startup, reload and clone storage all use the selected directory.
Omitting the flag retains the bundled gallery. This allows experimental voices
to remain separate from the in-use server's gallery and reload operations.

Supported controls: `temperature` (0.1–1.5), `top_p` (0.1–1), `top_k` (1–100),
`max_frames` (16–4000 per text chunk), `seed`, and `cues`, e.g.
`[{"offset": 0, "cue": "whispers"}]`. Cues are separate from the authoritative
transcript and inserted at character offsets at word boundaries. Allowed names
are in `contracts.py`; acceptance of a cue is not proof of expressive effect.
Free-form `instruct`, speed changes, revision and infilling are not supported.

`context_mode` defaults to `continuous` (the upstream generation strategy).
The opt-in `paragraphs` mode makes a separate model call at each blank-line
paragraph, using the same reference and resetting the seed for each call.
It preserves every input character, attaches punctuation-only separators to
nearby prose, and inserts no artificial silence or crossfade. This prevents
cross-paragraph history from influencing generation, but may change prosody
at joins. It is a candidate strategy for literal narration, not a transcript
guarantee: qualify the resulting audio before release. An empty paragraph
generation aborts the whole buffered request instead of dropping that text.
Its first full 4bit Collection response failed the frame/EOS limit. It remains
an experimental qualification option, not an accepted remedy for missing words.

Per-request controls override voice defaults via the optional GET `performance`
JSON parameter, or POST `performance` object on the existing clone-enabled POST
route. They never mutate the prepared voice. Controls on other backends fail
explicitly. GET retains its existing 5000-character input limit.

The adapter uses a fixed loopback URL with HTTP proxies disabled. If the sidecar
is unavailable, full-text Qwen fallback is enabled by default; set per-voice or
per-request `qwen_fallback: false` to fail instead. Fallback uses the original
transcript, not delivery tags. `X-Backend` names the backend that actually
produced the WAV and `X-Requested-Backend` names the selected voice backend.
The expressive adapter resamples Qwen fallback to 44.1 kHz with a polyphase
filter, preserving duration and pitch so sentence chunks keep a consistent
format when a reply mixes Drama and fallback. Direct Qwen requests remain
24 kHz. Consumers must still read WAV metadata. Logs identify fallback.

The sidecar rejects complete outputs containing ten or more consecutive seconds
below -50 dBFS (20 ms RMS windows). Actual 4bit qualification produced 68 seconds
of silence on a laughter prompt and a 19-second gap in a long response, despite
normal model completion. Rejection discards the entire buffered output and uses
the configured fallback policy; it never trims damaged speech into a success.
This conservative guard also rejects deliberately requested pauses that long.
It does not detect every missing word or certify transcript or acting quality.
Invalid requests are not disguised as
availability failures.

When fallback is disabled, an ordinary sidecar failure reaches the main API's
existing generic synthesis-error response (HTTP 500, no audio). Queue admission
and lock deadlines use HTTP 503. Clients must check status and content type;
they must not treat every failure as a WAV or assume all unavailability is 503.

The main server admits at most four expressive requests waiting for its shared
MLX lock, with a 180s lock deadline. Qwen's existing serialization remains.
The sidecar deadline starts when its request arrives, so the two stages have
separate budgets. Expressive GET/POST requests monitor client disconnects. A per-request cancellation
event interrupts queue waits and shuts down the adapter's sidecar socket, allowing
the sidecar to kill its active worker. Explicit cancellation never starts Qwen
fallback. The main request retains its synthesis lock until adapter cleanup has
finished. Existing Qwen inference is not made interruptible by this change;
a fallback already executing in Qwen completes under its existing lock. Actual
model-loaded cancellation still needs qualification.

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
for activation, from their recorded pre-activation copies. Vixen now selects the isolated experimental route; the default profile and
7860 service remain separate.

The Hermes command provider accepts `AFTERWORDS_PORT` for a profile-local
loopback route, for example `env AFTERWORDS_PORT=7862 bash
/path/to/afterwords-tts-command.sh {input_path} {output_path} voice-name`.
It defaults to 7860 and rejects invalid ports before synthesis. A remote profile
can use an independently verified SSH loopback forward; this setting does not
permit arbitrary remote URLs or change the default Hermes profile. Actual
Vixen configuration is on M5; do not create a replacement profile on Studio.

For Hermes native `/voice` sentence playback, add
`AFTERWORDS_PLAYBACK_OWNER=hermes` to that profile's command. Hermes then owns
playback of each returned artifact, and the provider does not play it again.
These artifacts archive under `tts-archive/consumer-delivered`, outside the
feed poller's top-level scan. The default `provider` owner preserves ordinary
CLI command-tool playback. This setting does not turn full-file synthesis into
native model streaming; Hermes overlaps sentence synthesis and playback.

To capture the installed native sentence route without speaker playback, run
the following on the host owning the existing Hermes profile, using its own
Hermes environment. Use a new output directory for every attempt:

```sh
HERMES_HOME="$HOME/.hermes/profiles/vixen" \
  "$HOME/.hermes/hermes-agent/venv/bin/python" scripts/verify-hermes-sentence-route.py \
  --hermes-root "$HOME/.hermes/hermes-agent" --out var/native-sentence-smoke-1
```

The smoke test uses real configured synthesis, captures native playback calls,
detects provider playback, decodes the returned artifacts (including Hermes'
Opus conversion), and verifies the profile file remained unchanged. It sets the
playback owner only in its own process environment. It does not generate an
agent reply, exercise the independent legacy post-LLM hook, or certify audible
playback/voice quality. A configured legacy speech hook must also be reconciled
before claiming exactly-once playback of a real agent turn.

Original voice candidates can be generated without any human reference:

```sh
.venv-drama3/bin/python scripts/generate-original-references.py --name cast-aster:101 --name stage-manager:100
```

Candidates and receipts remain under QA until transcript and acoustic review.
The generator preserves every attempt, records unconditioned provenance and
pins, and never promotes a generated file directly to a public reference.

## Resource ownership and qualification

The worker, original-reference generator and benchmark tools share a kernel
process lock. Only one expressive model may be resident through these tools at
a time. `POST http://127.0.0.1:7861/release` unloads an idle worker; it returns
409 if requests are pending. The lock does not coordinate unrelated Hermes
inference, so admission still reserves 24 GiB beyond the model allocation cap.
The suite budgets 40 GiB for 4-bit, 56 GiB for 8-bit and 88 GiB for BF16; these
are limits, not measured peak usage. The pinned 8-bit candidate is recorded in
`qa/expressive-voice/pins.json` and remains unqualified.

Reference WAVs may be mono or stereo, 1–30 seconds, at most 4 MiB and 192 kHz.
Stereo conditioning uses the arithmetic channel mean and PCM16 conversion;
receipts bind both original and conditioning hashes. Qwen fallback retains the
original reference bytes. Downmixing compatibility does not establish voice
identity fidelity.

`qualify-expressive-suite.py` runs the fixed cases in
`qa/expressive-voice/cases/suite.v1.json` against a pinned model. Supply
`--references-json` containing a `references` array of objects with `path`,
`text`, and `sha256`; dialogue needs two references. Choose a new `--out`
directory per attempt. It records first model chunk, completed generation RTF,
load time, Metal peak, and host memory. First model chunk is distinct from
first playable audio through the full-file HTTP contract. Failed attempts stay
incomplete and are retained. The script's deadline is cooperative.

`audit-expressive-audio.py --audio FILE --text-file TEXT --out RECEIPT
--whisper-snapshot LOCAL_DIRECTORY` runs offline CPU Whisper and waveform
measurements. It records exact hashes, ASR words/timestamps, word-edit alignment,
silence and clipping. ASR disagreement requires listening review; zero word
error does not certify acting, identity, pronunciation or timing. No script
promotes an audio candidate to accepted merely because generation succeeded.

The Hermes command provider writes new MP3/text archives under
`${HERMES_HOME:-$HOME/.hermes}/tts-archive`. The default profile retains its
existing destination; Vixen's files stay in her active profile. Existing archive
files are never moved. Installed Hermes on M5 was verified to pass both the
active profile home and the CLI/Telegram platform into command subprocesses.
Messaging delivery therefore uses the artifact-only branch; local sentence
playback is reserved for CLI/local. Actual end-to-end playback still requires a
separate execution receipt after activation.

## Private listening showcase

Build a self-contained static page from completed audio evidence:

```sh
.venv/bin/python scripts/build-expressive-showcase.py --manifest INPUT.json --out NEW_DIRECTORY
python3 -m http.server 8769 --bind 127.0.0.1 --directory NEW_DIRECTORY
```

The input is an object with a `clips` array. Each clip has unique `id`, `part`
(1–5 for backend comparison, emotions, Vixen, cast, exchange), `label`, `backend`,
`audio` and `text` file paths relative to the input JSON, and exact `audio_sha256`
and `text_sha256`. Optional `acoustic_acceptance` and `permission` record the
actual review state. Exchange clips play in input order. The builder validates
all hashes and PCM16 mono WAVs before creating the page, copies only those WAVs,
and refuses to overwrite prior builds. Serve only this output directory on
loopback; do not serve the broader QA directory or publish private comparisons.

Playback is explicit, one clip at a time, with pause, mute, replay and exact
transcripts. The five required demonstrations remain visible when recordings
are missing. Availability counts never certify identity, emotion, end-to-end
Vixen delivery, distinct casting or acoustic acceptance.

A baseline against the existing running service is reproducible with:

```sh
.venv/bin/python scripts/benchmark-afterwords-http.py --voice galadriel --case interruption --case pronunciation --case long-response --out NEW_PRIVATE_DIRECTORY
```

This sends one request at a time to loopback, preserves every attempted case,
checks complete PCM16 mono WAV payloads, and records response headers, exact
hashes, full-file latency and end-to-end RTF. It does not restart the service,
apply experimental controls, retry failed cases, or measure native model TTFA.
Use original/consented voices for public assets; existing identifiable voices
are private comparison material unless separately cleared.

## Local acoustic measurements

The CPU speaker-embedding audit has its own pinned environment:

```sh
uv venv --python 3.12 .venv-audio-audit
uv pip install --python .venv-audio-audit/bin/python -r requirements-audio-audit.txt
hf download speechbrain/spkrec-ecapa-voxceleb --revision 0f99f2d0ebe89ac095bcc5903c4dd8f72b367286
.venv-audio-audit/bin/python scripts/audit-voice-identity.py --snapshot PINNED_SNAPSHOT --reference REFERENCE.wav --reference NEGATIVE_CONTROL.wav --audio SAMPLE.wav --out NEW_RECEIPT.json
```

This runs ECAPA-TDNN on four CPU threads, downmixes/resamples explicitly to16kHz,
compares every10-second output window against each supplied reference, and records
hashes and package/model pins. Sub-second tails are explicitly unmeasured. A
cosine score is comparative evidence, not a calibrated identity-quality grade.
The initial Qwen baseline was actually measured with this tool; no subjective
listening acceptance is inferred.

`assess-expressive-delivery.py --audio SAMPLE.wav --out NEW_RECEIPT.json` uses
the existing Drama environment with a separately pinned Qwen2-Audio model to
record automated delivery observations. The pinned environment includes Jinja2
for the model's chat template. Actual short and 92.56-second Qwen inputs have
run successfully; this establishes execution and full-input coverage, not the
accuracy of subjective judgments. **This model/prompt failed an all-zero-silence
control**, describing speech, sighs/gasps and clicks in silent PCM. Its delivery
judgments are unsuitable for acceptance and must not serve as listening evidence.
The script retains exploratory outputs with this qualification recorded. It takes the
shared model lease, requires40GiB host headroom, caps MLX allocations at16GiB,
and processes the entire input in20-second segments because the upstream
implementation truncates individual inputs at30seconds. It never supplies the
intended emotion to the observer. Its observations may still be wrong or depend
on lexical content; they remain separate from human listening acceptance.
Evaluation model revisions are in `qa/expressive-voice/pins.json`.

### Real Vixen reply probe

`verify-hermes-sentence-route.py --agent-prompt 'Your prompt' --deadline 360`
adds a real `HermesCLI.chat` turn to the same native sentence capture. It keeps
the configured model/tools/personality, applies a $0.50 run budget, enables
native TTS for that probe, observes the actual post-LLM ownership field, and
checks one returned artifact per spoken sentence. The configured command must
already contain `AFTERWORDS_PLAYBACK_OWNER=hermes`; this mode does not inject
that provider override. The probe captures local playback; it does not invoke a
messaging send or establish physical audibility.
Each attempt needs a new output directory, including failed attempts. The
parent enforces a process-group deadline and retains an incomplete receipt on
timeout. An existing automatic mute flag is preserved.

On M5, the existing `local-studio` Keychain credential command returned exit 36
under SSH but succeeded in a fresh GUI launchd worker without credential
changes. Run the probe in that working user context. Do not replace the model,
print credentials, or treat an authentication error message as a generated
Vixen reply. The one-shot GUI worker must be unloaded after its bounded run.

Private acceptance evidence now includes one real configured Vixen reply:
two native sentence artifacts, no provider playback, 30.95 seconds from probe
start through delivery, 18.30 seconds of audio, and zero CPU Whisper word errors.
That establishes generated audio and captured playback calls, not acting or
physical audibility. The live profile uses an original synthetic reference and
Qwen fallback on the separate experimental server. The experimental API, sidecar and SSH tunnel now run as separate user launchd
jobs. Fresh-process synthesis and supervised tunnel reconnection are verified;
reboot/cable-disconnect behavior and live gateway receipt remain unverified.

### Persistent experimental services

Prepare launchd definitions without loading them:

```sh
.venv/bin/python scripts/prepare-expressive-services.py \
  --out var/expressive-voice/service-plists-1 \
  --peer m5-tb --tailscale-ip CURRENT_M5_TAILSCALE_IPV4
plutil -lint var/expressive-voice/service-plists-1/*.plist
```

Read the current infrastructure runbook before selecting peer addresses. The
three `net.afterwords.expressive.{sidecar,api,m5}` user jobs run the isolated
7861 sidecar, the private 7862 API/gallery, and the reverse SSH forward to M5
loopback 17862. They do not manage the default 7860 service. Logs go under
`var/expressive-voice/services/`. Create that log directory, copy the plists to
`~/Library/LaunchAgents/`, and bootstrap them in the user's GUI domain after
gracefully retiring any task-owned foreground instances on these ports.

The SSH alias must have a pinned `HostKeyAlias`. The tunnel first probes the
direct alias and falls back to the supplied Tailscale address while preserving
the same identity/key pin. All forwards bind explicitly to loopback. launchd
restarts a disconnected tunnel, selecting the available route anew; this is
reconnection, not seamless migration of an in-flight HTTP request. A diagnostic
`--route tailscale --remote-port 17863` tests the alternate path separately.

Rollback these three jobs with `launchctl bootout gui/$(id -u)/LABEL`, then
remove only their three launchd plists. Restore only Vixen's speech fields from
the recorded pre-activation config if retiring its experimental route; preserve
subsequent unrelated config changes. No `setup.sh`, global routing edit, or
restart of the default Afterwords service is needed.

### Gateway artifact handoff

Run `scripts/verify-hermes-gateway-voice.py` in the installed Hermes environment
with the intended `HERMES_HOME`, `--hermes-root` and a fresh `--out` directory.
It invokes the installed gateway voice and profile-routing methods with the
real configured command provider. A local capture adapter receives the output;
no bot starts and no network message is sent. The probe requires one valid
Opus handoff, verifies the native-tool dedup rule, and checks that an absent
Vixen adapter cannot fall back to the default bot. This proves the bounded
adapter handoff, not live Telegram receipt. Existing gateway health is a
separate check; it is not audio delivery evidence.

### Pinned OmniVoice comparison

The alternative probe is `scripts/benchmark-omnivoice.py`, using the existing
isolated `.venv-drama3` environment and the same reference normalization and
exclusive model lease. It loads only the cached
`mlx-community/OmniVoice@defe4bdce0decb321d17e96a4774417be08022ea` snapshot,
requires 48 GiB of available memory, caps Metal allocations at 24 GiB, and
reaps a timed-out worker. It does not change serving routes. Example:

```sh
.venv-drama3/bin/python scripts/benchmark-omnivoice.py \
  --text-file TEXT.txt --reference REFERENCE.wav \
  --reference-text-file REFERENCE.txt --output NEW_ATTEMPT.wav \
  --steps 64 --timeout 300
```

The observed parameters are float32. The first dry-humour sample took 1.45 s
to load and 3.41 s to generate 7.88 s of audio (RTF 0.432), with a measured
generation Metal peak of 4.35 GB. CPU transcription found zero word errors.
The API produces a complete waveform, not native streaming audio. Reference
conditioning uses the full normalized clip (up to 30 s), rather than silently
clipping its audio while retaining a longer transcript.

The fixed short-case cohort had zero transcript errors except `touch` versus
`touched` in the excitement case. That disagreement still needs listening.
The 302-word single-call long response failed: 126 ASR edits (41.72%), including
omitted passages and a garbled ending. It is rejected. Instructions such as
`excited`, `sad`, `angry`, `whispering` and `laughing` were passed separately
from the exact target text; their acoustic effectiveness remains unverified.
Native multi-speaker generation was not tested by this single-reference probe.

A controlled six-paragraph version of that same 302-word long response retained
all prose in the CPU transcript audit: its three raw edits were only number
formatting (`seventeen`/`17`, `eleven fifteen`/`1115`). The complete artifact is
130.68 s; six separate model processes took 32.01 s including their loads.
Every paragraph used the same original reference and seed. No silence was
trimmed or inserted and no crossfade was applied. This is application-level
segmentation, not native model streaming or a general long-text qualification;
boundary timing and acoustic quality still require review.
