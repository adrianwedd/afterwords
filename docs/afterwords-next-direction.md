# Afterwords: dependable agent speech, with expression where it earns its keep

Afterwords should be one local voice service, not a backend museum and not six
integration stacks pretending to be a product.

The useful architecture is already visible:

1. A stable local synthesis engine with explicit voices and complete-artifact
   semantics.
2. A thin identity envelope: agent, profile, conversation, project, occurrence
   and requested voice.
3. One durable delivery contract: queued, claimed, playback-may-have-started,
   terminal. Playback and external delivery remain separate consumers.
4. An optional expressive engine behind the same contract, admitted only for
   specimens where it demonstrates a useful difference.

## Retain

- **Qwen3 0.6B as the default engine.** It is the shipped, local, relatively
  memory-light cloning path with the broadest accumulated operational evidence.
- **The HTTP API and backend protocol.** They are useful boundaries. Registration
  does not need to imply endorsement or eager loading.
- **Voice profiles and exact reference custody.** Identity, transcript and
  backend selection remain data, not caller folklore.
- **Canonical strip/chunk logic and complete/partial artifact semantics.** A
  client must never describe surviving fragments as the requested speech.
- **The durable queue lifecycle and shared playback lease.** These are the right
  primitives for non-replay and non-overlap.
- **Fish Drama 3 as an isolated expressive research path.** Keep its resource
  admission, cancellation, truthful backend headers, retained failures and
  explicit fallback policy.

## Simplify

- Support integrations because they carry stable occurrence and project
  identity, not because the executable happens to be installed. Hermes first;
  then choose only the agent surfaces Adrian actually wants speaking.
- Collapse project voice selection into one identity resolver. Integrations
  should provide an identity envelope; the resolver returns an explicit voice;
  synthesis should not rediscover project state.
- Make the public status surface report source revision, loaded runtime identity,
  queue owner and selected backend. Avoid broad “integration present” claims.
- Treat the fifteen experimental backend registrations as a laboratory index.
  They should not dominate setup, health output or the product story.

## Defer or retire

- No new backend until an existing failure specimen names a capability gap and
  a candidate beats Qwen or Fish on that specimen.
- Defer general Fish long-form serving. It is promising in native-context mode
  and demonstrably unreliable in other chunking modes.
- Retire legacy hook copies after—not before—their chosen managed replacement has
  one real occurrence, queue and playback receipt. Do not run both.
- Defer public expressive character releases until rights and exact-recording
  acceptance exist. Private listening approval is not a public identity grant.

## What the existing evidence actually says

The evidence does not support a simple “Fish is better” or “Qwen is better”.

- Qwen/Seydoux gave stronger ECAPA similarity than Fish/Seydoux on the retained
  Vixen reply (`0.838/0.772` versus `0.659/0.651`), while Adrian preferred the
  Fish version in the matched listening comparison. Identity metrics and
  expressive preference are different questions.
- Fish native-context long form produced the strongest retained 302-word result:
  zero ASR deletions, four normalisation-like substitutions, one possible
  insertion and a 2.98-second longest silence. External 400-character calls
  produced 18.5 seconds of silence; paragraph isolation lost 102 words by ASR.
- A 128-frame Fish limit returned a plausible-looking but incomplete take with
  five deletions. At 512 and 1,600 frames the same short specimen completed
  identically. Budget exhaustion, EOS and silence are separate failure modes.
- Several casting failures were reference or instrumentation failures, not
  backend verdicts: the rejected synthetic Vixen voice had the wrong identity;
  a Qwen payload was initially rejected by a wrong header check; Drama/Eartha
  omitted much of the text. Retaining these failures is more useful than adding
  another model.

## Smallest useful qualification set

Use existing text and references. Do not generate a giant benchmark first.

| Specimen | Question | Required measures |
| --- | --- | --- |
| 17-word dry-humour line | Does a short turn complete quickly and cleanly? | requested/returned words, EOS/budget state, first audio, wall time, duration |
| Two concurrent project replies | Does identity survive multiplexing? | exact session→project→voice mapping, no cross-voice request |
| 400-character ordinary reply | Does the normal agent chunk remain complete? | chunk identity/order, HTTP outcome, valid audio, silence, latency |
| Retained 1,871-character response | Can long form finish without omissions or pathological gaps? | full text coverage, longest silence, chunk/call plan, wall time, memory pressure |
| Same-word Vixen Qwen/Fish pair | Does expression improve without losing the person? | identical text, negative-reference identity screen, human A/B preference |
| Retained silence/omission failures | Do gates reject seductive failures? | incomplete status, no fallback masquerade, no automatic retry or silence deletion |

For every specimen, keep four judgements distinct:

- **Quality:** human preference and intelligibility, with ASR/silence as screens.
- **Latency:** first usable audio and complete-delivery wall time.
- **Identity:** requested voice and project provenance, plus relative speaker
  evidence where useful.
- **Long-form integrity:** every requested word accounted for, ordered and
  delivered; a valid WAV is not enough.

The next experiment should be the matched Vixen pair plus the retained long-form
and failure controls on the reviewed source/runtime candidate. If Fish wins the
human comparison while passing completeness and resource gates, add an explicit
per-request expressive mode. If it does not, keep it as a research renderer.
Either result is useful. Adding another backend is not.
