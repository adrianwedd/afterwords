# Fish library and long-form investigation — 17–18 October 2026

This is a new private follow-up to the completed expressive integration. It does
not reopen casting acceptance, change Vixen's speech selection, or admit public
audio. Diagnostic generations never use Qwen fallback.

## Installed voice library

The isolated Studio expressive API at `127.0.0.1:7862` now lists **104** additional
Fish aliases, one per accepted Studio reference path. Their deterministic names
are `fish-` plus the original WAV stem with the final `-ref` removed, for example
`fish-galadriel`, `fish-snape`, and `fish-tilda`. The same aliases are visible
through M5's existing `127.0.0.1:17862` tunnel. `/health` lists the selectable names.

Each alias binds the exact accepted WAV SHA-256 and literal transcript SHA-256
in [aliases.json](aliases.json). The builder checks both the final acceptance
record and snapshot, then checks every associated current Qwen profile against
the verified words. Conflicting audio/transcripts are excluded, never repaired
or replaced automatically. No Qwen profile is changed. Backend-specific tuning
and family routing are not inherited into Fish aliases.

The aliases and any new recording directory entries are installed privately in
`var/expressive-voice/voices/`. New WAV entries are **hard links**, not copies or
symlinks outside the voice directory. Cross-filesystem installation fails rather
than silently copying. Original source recordings remain unchanged. Fish's
existing conditioning code downmixes 51 stereo references in memory/worker
scratch; 53 references need no conversion. That existing conditioning step is
recorded separately from original WAV custody and does not replace a recording.
No synthetic intermediary voices, retraining, new references or audition gallery
were created. Each alias sets `qwen_fallback: false` explicitly.

The existing API reloaded 131 total voices with zero errors and zero removals.
M5 tunnel health independently listed all 104 aliases. This establishes loaded
selection, not a quality verdict for every voice. Private Vixen's existing
profile and fallback policy were not rewritten.

Rebuild/inspect the library:

```bash
.venv/bin/python scripts/build-fish-library.py --out NEW_PLAN.json
.venv/bin/python scripts/build-fish-library.py --apply --out NEW_INSTALL.json
curl -fsS -X POST http://127.0.0.1:7862/reload
curl -fG http://127.0.0.1:7862/synthesize \
  --data-urlencode 'text=The library is ready.' \
  --data-urlencode 'voice=fish-galadriel' -D NEW_HEADERS.txt -o NEW_TAKE.wav
```

Use a new output filename each time. `/reload` above is additive, with pruning
disabled. The builder will not overwrite a conflicting existing profile or WAV.
For rollback, use the install receipt's exact `created` paths to remove only
newly added alias JSON files and hard-link directory entries, then reload. Never
remove the original source WAVs or pre-existing entries. Existing Vixen rollback
and historical receipts remain in their original locations.

## Additional M5 references

Fresh read-only M5 inventory: **349 profiles, 224 reference paths, 222 distinct
recording hashes**. Of these, 198 profiles match accepted Studio audio and
literal transcripts. The additional **120 paths / 119 distinct recordings**
are outside that corpus audit; metadata compatibility does not establish their
literal transcripts or speaker isolation. They are inventoried rather than
silently promoted by the bulk builder. This does not revoke separate evidence
or the existing individually reviewed Vixen route.

No missing or unsupported assets were found by the standard-library inventory.
Two additional profiles fail the current admission limits:

| Reference | Reason |
| --- | --- |
| Optimus Prime | 46.27 seconds, 4,441,964 bytes: exceeds 30 seconds and 4 MiB |
| RoboCop | 30.75 seconds: exceeds 30 seconds |

Neither recording was trimmed, rewritten or replaced. Other additional assets
need matching transcript/PCM evidence before bulk admission. Exact inventory and source
transcripts are private in
`var/expressive-voice/library-longform-20261017-1/m5-inventory.json`;
[m5-summary.json](m5-summary.json) contains the aggregate result. M5's own
profiles and recordings were not modified.

## Diagnostic design and custody

`scripts/compare-fish-longform.py` directly calls the pinned MLX Fish model.
It cannot dispatch to Qwen. Every attempt records actual backend, quantisation,
model revision, implementation/chunker hashes, original and conditioning hashes,
reference transcript, seed and sampling controls. Native frame generation and
prompt construction are observed without changing sampling or history.

The fixed 1,871-character canonical response produces these call plans:

| Condition | External calls | Planned native chunks |
| --- | ---: | ---: |
| `external400` | 6 | 10 |
| `native300` | 1 | 7 |
| `paragraphs` | 6 | 10 |

Each external/paragraph call resets seed and codec/history as the existing
independent-call paths do. Within a native call, MLX keeps its first generated
chunk pinned and its latest chunk as context. Receipts retain exact planned and
observed chunk text, actual history text/frame counts, streamed audio boundaries
and arrival times. Paragraph isolation is a distinct condition: its boundaries
differ from the 400-character plan despite having the same number of calls.

The short dry-humour script separately tests 128, 512 and 1,600 frames per native
chunk, using the same seed/reference/text. A low-limit failure is retained as an
incomplete take, not released as truncated speech. Silence is measured separately
from frame exhaustion and ASR fidelity; silence is never cut out to create a
successful take. No failed take is automatically retried or repaired.

Every attempt gets a new directory, including refusals. `retained.wav` contains
all returned audio, complete or partial; `stream.f32` is flushed little-endian
float32 mono/44.1 kHz so a hard supervisor termination cannot hide returned
audio behind an unfinished WAV header. Native code arrays are also retained.
`upstream_return_before_budget` means the pinned generator returned before its
limit; it is distinct from `budget_exhausted_without_eos`. It does not establish
that the script was fully spoken. `run.json` never labels an incomplete result
as complete acoustic acceptance.

## Resource admission and controlled concurrency

Admission retains the existing conservative limits: 4-bit requires 64 GiB
available (40 GiB Metal cap plus 24 GiB reserve); 8-bit requires 80 GiB
(56 plus 24). Normal macOS memory pressure must also be confirmed. A single
expressive-model kernel lease prevents overlapping workers. No Hermes model is
unloaded and no active render is stopped to create headroom.

During generation, samples every two seconds retain memory availability, wired
memory, swap usage, cumulative VM swap-in/out counters and pressure. The runner
stops at a frame boundary if pressure becomes abnormal, availability drops below
16 GiB, or new swap-outs exceed 256 MiB. Historical swap use is reported as a
baseline, not attributed to this attempt. A 360-second generation deadline and
480-second outer process-group deadline bound each matrix attempt. A stalled
Metal call may only respond to the outer deadline.

Optional controlled concurrency uses the already resident local llama server,
not a provider or a new model load. It requires an idle slots readback, uses
explicit slot 0, one fixed prompt, temperature zero, seed 20261017 and at most
128 predicted tokens per call. One call before Fish, up to four concurrent
calls, and one call after Fish retain timings and actual model/quantisation
identity. This is a bounded overlap experiment, not proof of continuous load
throughout an entire long response. Read-only slots telemetry also records
ambient inference during Fish-only conditions. No global inference route is
changed.

The matrix supervisor can wait for an identified pre-existing render process
to exit. Its explicit `--release-idle-sidecar` option uses the existing guarded
`/release` endpoint only when no requests are pending. It never restarts the API
or changes Vixen's configuration. While diagnostics hold the exclusive model
lease, new live Fish requests can encounter the existing unavailable/fallback
behavior; that interval must not be described as uninterrupted Fish serving.

Reproduce the canonical input files from the retained suite (choose a fresh
private directory), then run a new matrix:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
out = Path('var/expressive-voice/NEW_INPUTS')
out.mkdir(parents=True, exist_ok=False)
cases = json.loads(Path('qa/expressive-voice/cases/suite.v1.json').read_text())['cases']
for name in ('long-response', 'dry-humour'):
    (out/(name+'.txt')).write_text(next(c['text'] for c in cases if c['id'] == name))
PY
.venv-drama3/bin/python -u scripts/run-fish-comparison.py \
  --reference-profile var/expressive-voice/voices/fish-galadriel.json \
  --long-text var/expressive-voice/NEW_INPUTS/long-response.txt \
  --short-text var/expressive-voice/NEW_INPUTS/dry-humour.txt \
  --out var/expressive-voice/NEW_MATRIX --release-idle-sidecar
```

Add `--wait-for-pid PID` to wait for a known existing render job. To include
controlled local inference, first identify the actual resident loopback port,
then add `--workload-url http://127.0.0.1:PORT/completion` and
`--observe-slots-url http://127.0.0.1:PORT/slots`. These are explicit inputs,
not a permanent service address. `--case NAME` selects an individual matrix
condition; use it to run previously unadmitted conditions without repeating
completed or failed generations. Generation failures are retained, not retried.

Audit each complete or partial retained WAV with the existing CPU tools:

```bash
.venv/bin/python scripts/audit-expressive-audio.py \
  --audio ATTEMPT/retained.wav --text-file CANONICAL_INPUT.txt \
  --whisper-snapshot LOCAL_PINNED_WHISPER_DIRECTORY --out NEW_WORD_AUDIT.json
.venv-audio-audit/bin/python scripts/audit-voice-identity.py \
  --snapshot LOCAL_PINNED_ECAPA_DIRECTORY \
  --reference voices/galadriel-ref.wav --reference voices/tilda-ref.wav \
  --audio ATTEMPT/retained.wav --out NEW_IDENTITY_AUDIT.json
```

The intended reference is first, with Tilda as a negative comparison. ECAPA
scores support reference conditioning but are not calibrated identity or
listening acceptance. ASR disagreement is measured word fidelity, not a proven
auditory error; partial takes are compared against the full requested script and
must remain labelled incomplete.

Private matrix, commands, logs and refusal receipts are retained under
`var/expressive-voice/library-longform-20261017-1/`. Source tests pass:
843 passed, 2 skipped. No human listening, public deployment or universal
long-form reliability is claimed.

## Measured results

[results.json](results.json) retains exact call/native boundaries, observed
first/latest history, audio boundaries/arrivals, hashes, frame/EOS observations,
latency, resource summaries, full word-edit lists and identity windows. Raw WAVs,
float streams, code arrays, full telemetry and audit logs remain in the private
evidence directory. Regenerate the summary with
`scripts/summarize-fish-comparison.py --root PRIVATE_ROOT --out NEW_SUMMARY.json`.

All admitted generations used the pinned `mlx-community/fish-audio-drama-3-4bit`
checkpoint `cc639e27aba7edb73429d3e3806f471dcd79d316`, the unchanged Galadriel
reference and seed **20261017**. The checkpoint label is shorthand: its config
defaults to 8-bit with 4-bit expert overrides. Instantiated-module inspection in
the controlled experiment counted **120 quantised modules at 4 bits and 338 at
8 bits**, including 8-bit codebook heads. These are module counts, not parameter
percentages; unquantised layers are not counted. Configuration hash and actual
module examples are retained. No 8-bit checkpoint was loaded or promoted.

### Canonical long response: 302 words

| Condition | Calls / native chunks | Generation wall s | Audio s | Longest silence s | ASR deletions / substitutions / insertions |
| --- | ---: | ---: | ---: | ---: | ---: |
| External 400 characters | 6 / 10 | 61.24 | 181.25 | 18.50 | 7 / 5 / 0 |
| Native first/latest context | 1 / 7 | 54.98 | 154.64 | 2.98 | 0 / 4 / 1 |
| Paragraph isolation | 6 / 10 | 55.19 | 164.82 | 18.30 | 102 / 4 / 0 |

All three generators returned before their per-native-chunk 1,600-frame limits.
External and paragraph outputs were retained and rejected for sustained silence.
Native context passed the existing ten-second silence screen and had no ASR
deletions. Its substitutions were `ten/10`, `eleven/11`, `fifteen/15`, and
`cancelled/canceled`; ASR also reported one possible extra `using`. These are
measurements, not claims that a listener heard a mistake. This is the strongest
standalone long-form result in this follow-up, not universal qualification.

Native identity windows ranked the intended reference over the Tilda comparison
in **16/16** windows, with target cosines **0.650–0.798**. External ranked it
first in 19/19, and paragraphs in 17/17, but their silence-heavy windows had
very low absolute similarity. Relative rank alone must not admit a defective
take or establish human recognisability. First internal audio arrived in roughly
0.48 seconds; this was not a playback measurement. Defective silence-filled
audio is not useful throughput, despite its apparent low RTF.

Ambient llama inference was not successfully observed during these long-form
conditions: the earlier engine endpoint disappeared, and the subsequent
long-form run had no slots observer configured. They establish a chunking
comparison under retained machine telemetry, not strict compute isolation.
All recorded pressure levels were normal and new swap-outs were zero.

### Generation limits, separately from silence

The 17-word short script exhausted **128** frames without verified EOS. Its
5.712-second returned waveform, all 128 sampled code frames and five ASR
deletions remain retained as an incomplete failure. Pending SDK decode frames
are represented by the retained codes, not fabricated as returned audio.

At both **512** and **1,600**, the generator stopped at **171** frames and
produced the same 7.941-second WAV SHA-256, with zero ASR word edits. The live
`fish-galadriel` alias returned HTTP 200, actual/requested backend `fish-drama3`,
and this exact same WAV hash when given the same text/seed. Alias fallback was
disabled. No playback or listening acceptance is inferred.

The long-form silence failures occurred despite EOS before the cap, so raising
the frame ceiling does not address those failures. Conversely, a global
512-frame ceiling would truncate legitimate observed native chunks: this long
script needed as many as 571 frames in a single native chunk. Keep caps as
explicit bounds and fail incomplete, rather than dropping audio or pretending
that a budget-exhausted take ended normally.

### Bounded resident-inference contention

The first concurrency setup failed before Fish generation because its resident
endpoint had gone away. That failure and all admission refusals remain retained.
No failed audio was rerun to seek a favourable outcome. A new controlled
before/during/after experiment used the currently resident
`Qwen3.8-Flash-Next-UD-Q4_K_XL` model, reported as `Q4_K - Medium`, without
changing its route, unloading it or starting another reasoning model.

| Fish condition | Generation s | Audio s | New swap-outs | Sampled llama state |
| --- | ---: | ---: | ---: | --- |
| Before, Fish only | 2.929 | 7.941 | 0 | Idle |
| Controlled inference overlap | 3.459 | 7.941 | 0 | Busy |
| After, Fish only | 2.945 | 7.941 | 0 | Idle |

All three WAVs were byte-identical and had zero ASR word edits. Fish generation
took **17.8%** longer during overlap than the mean of its surrounding baselines.
The first concurrent reasoning call overlapped Fish for 2.999 seconds; the
second overlapped for only 0.461 seconds. Reasoning throughput was 43.59 tok/s
before, 44.39 and 46.22 during those calls, and 46.51 after. Variable baselines
and partial overlap do not establish a general reasoning-model slowdown.
This is one bounded pilot, not a confidence interval or sustained-load test.

### Practical admission and next-use recommendations

- Prefer **one native-context call** for private long-form experiments using
  this model. Keep external and paragraph modes as reproducible diagnostic
  controls. Do not silently change Vixen's existing sentence pipeline on the
  basis of one script/reference/seed.
- Keep the **64 GiB available / normal pressure / exclusive lease** gate for
  4-bit. The existing 8-bit budget remains 80 GiB; it was not newly qualified.
  Do not lower admission just to fit beside an active render, unload a Hermes
  model, clear swap or change global inference routing.
- Separate historical swap use from new activity. These admitted runs retained
  about 14 GiB of pre-existing swap use with no new swap-outs and normal
  pressure. File-backed model page-ins are not proof of swapping.
- Wait for existing renders to exit and live requests to finish. Release only
  an idle Fish worker through its guarded endpoint, then acquire the exclusive
  diagnostic lease. Record that new live requests during a diagnostic lease can
  encounter the existing fallback/unavailable policy; configuration preservation
  is not a claim of uninterrupted Fish serving.
- Preserve every take, enforce per-chunk frame and outer time bounds, measure
  silence and word fidelity independently, and never increase limits or retry
  silently to turn a failed cohort into a success. No production frame limit,
  Vixen voice selection, speech route or release gate was changed here.
