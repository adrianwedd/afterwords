# Casting refinement — 2026-10-17

Vixen's **Drama/Seydoux B** recording has positive operator listening feedback.
Her local speech route is now promoted to that reference and engine. The broader
LulzBench ensemble remains rejected; the two new reference candidates below are
private auditions, not an accepted public cast.

Open `var/expressive-voice/casting-refinement-1/listen/index.html` for the short
audition: Vixen's preserved comparison, then **Lisa** and **Blackadder** performing
the same 26-word Maternal Gambit excerpt. The new cast comparisons total 33.50
seconds; including both preserved Vixen recordings, approximately 66 seconds.
Each candidate includes an optional source-reference player. There are no forms,
autoplay, coverage selectors, or acceptance ceremonies.

## Vixen: installed route and rollback

Before inspection, the actual M5 command provider and legacy hook both selected
`seydoux` on port 7860 (Qwen). They now select
`vixen-seydoux-drama-reviewed` on port 17862, the existing loopback reverse
forward to Studio's isolated expressive API on port 7862. The API delegates
Fish Drama 3 to its loopback sidecar on 7861. No default-profile mapping changed.

The private voice profile uses exactly the reviewed reference SHA-256
`a8bd5856cb6dfc1bc06dd0a49d9d146503fa9e7de25d308e0cae2cdacb438d44`,
seed 20261017, temperature 0.65, top_p 0.7, and no cues. The reviewed B WAV remains
unchanged: `2648f55148db602210bfd237d128ec7fd3a397308f8d0b5b516b787f4772e516`.
The existing Qwen fallback policy is retained with the same reference; a fallback
must not be described as Drama. A new request through M5's actual port/voice
reported `X-Backend: fish-drama3` and `X-Requested-Backend: fish-drama3`.

`scripts/promote-vixen-drama.py` requires an exact before-config hash and changes
only provider voice, provider command, and the one Afterwords shell-hook command.
It uses Hermes' atomic configuration writer and native registration of that hook.
Model, tools, memory, credentials, identity and unrelated hooks remain unchanged.
Config SHA changed from `be8804ab61eaf3ce0a9b31025297f4c538dacb46de0dd7920be89a223dd901eb`
to `9c14010e526ef8f7890464c9f9854bbb7dc7037172fdcd50ebbe4f1f212b5017`.

The gateway reported zero active agents and no active work. It was gracefully
stopped with SIGTERM; launchd restarted PID 3859 as PID 30437, and the replacement
reported Telegram connected. Existing desktop session leases/processes were not
terminated. A fresh installed Hermes native sentence worker generated and decoded
an Opus artifact through the new configured provider, with zero provider playback
calls. The existing mute flag was retained. This is local route/artifact proof,
not new human listening or external-message delivery.

Private M5 rollback custody:
`~/.local/state/expressive-voice/casting-refinement-1/promote/` contains the original
0600 `config-before.yaml`, `speech-fields-before.json`, hash receipt and route
probe. To roll back, run the same script in installed Hermes with the explicit
Vixen `HERMES_HOME`, current `--expected-config-sha256`, a new `--out`, and
`--restore-fields` pointing to that saved JSON. This restores only the three
speech fields, preserving subsequent unrelated configuration changes. Register
the restored hook through the script, then refresh the idle Vixen gateway.
The rollback transformation is tested; no live rollback/re-promotion rehearsal
was performed. Qwen/Seydoux and its original reference remain available on M5.

## Reference quality comes before performance

`casting-reference-audit.v1.json` inventories every library reference and traces
all **18** current LulzBench references, including the Stage Manager. Every
registry reference and provenance receipt matches its recorded SHA-256. Six
references originated in unconditioned OmniVoice generation; twelve originated
in unconditioned Drama 3 generation. None was conditioned on an established
speaker. Seeds, generator models/revisions, original receipts and identity basis
are recorded individually. The operator's ensemble rejection is retained; zero
ASR edits never constituted artistic approval.

The canonical Studio library has **104 unique references**, and all current bytes match
the earlier accepted reference-corpus QA. That earlier evidence covers speaker
isolation, contamination, boundaries and literal transcripts. The inventory
retains its adjudications and evidence paths. This is stronger reference-quality
evidence than the original synthetic cast had, but does not prove memorable
synthesis or a publishable identity.

The live M5 library is larger: **349 profiles, 224 unique references**. All 104
canonical accepted hashes are present there; the other 120 references are outside
that corpus-QA record and are not automatically admitted. The complete host
inventory, including private profiles, is retained privately as `m5-library.json`;
the committed audit contains aggregate counts only. Seydoux's source is recorded
on M5 as YouTube `gP0TI4i84Hg`, with the reviewed reference hash above. Her positive
human feedback is specific evidence beyond the historical 104-reference corpus.

The preceding private replacements are traced too: Aster → Lisa (YouTube
`Z66IHEEiCAw`), Hugo → Snape (original acquisition URL absent), Iris → Eartha
(`TEoAypCUdRI`), Jasper → Cat (`RfNJitORCVA`). Snape existed in the initial shipped
profiles at commit `c9162b2`; neither that profile nor the remediation record
supplies an acquisition URL. This provenance gap is not filled by guessing a
film clip. Hugo remains unsatisfactory; passing source QA did not rescue the cast.

## Small matched audition

| Reference | Source | Why this candidate | Current evidence |
| --- | --- | --- | --- |
| Lisa | YouTube `Z66IHEEiCAw` | Bright, emphatic prodigy against solemn academic absurdity | Source bytes match prior isolated-speaker QA; both engine takes pass word screening |
| Blackadder | YouTube `n-Zm8H6G108` | Dry, deliberate contempt, contrasting with Lisa's register | Source bytes match prior isolated-speaker QA; both engine takes pass word screening |
| Eartha | YouTube `TEoAypCUdRI` | Smoky, low reference; considered as an alternative texture | Qwen passes word screening; Drama take excluded for severe transcript disagreement |

All three engine comparisons used the identical source audio bytes, literal
reference transcript and performed text within each pair. The Qwen service uses
the existing library profiles; Drama receives those exact WAV bytes directly.
No engine-specific cues or free-form instructions were added. Both use existing
pinned 0.6B Qwen/4-bit Drama models. This isolates engine behaviour more closely
than the earlier comparisons, which also changed references and direction.

The excerpt is bound to the complete captured Huihui response, LULZ-0199. Only
Markdown emphasis is removed. “Qwen/Huihui” identifies the **text model**; it says
nothing about the **speech engine**. Every listening card now names the reference
and speech engine explicitly, and the complete original prompt/reply remains
expandable. The earlier four-pair page has corrected labels too; its original
files are preserved under `listen-before-refinement-labels/`.

Six takes were generated once; no retries or lucky-take search. Eartha/Drama was
25.50 seconds, but CPU Whisper recovered only “I must confess” (23/26 word edits).
That disagreement is sufficient to withhold the take, not a claim that every
missing word was independently heard to be absent. The take, plan and measurements
are retained. Qwen/Eartha remains a private reserve, not silently substituted
into a Drama comparison. The four shortlisted new takes have zero word edits
except ASR's orthographic four/4 differences. They have no clipped samples and
measured longest near-silences of 0.26–0.62 seconds. These are screens, not timing
or recognisability verdicts. Bland or unconvincing performances remain rejectable
by listening; no independent artistic listening is claimed here.

## Permission and release boundary

**No identity publication grant has been established for Seydoux, Lisa, Snape,
Eartha, Cat or Blackadder.** Library possession, source URLs and model licenses
are not recorded as permission. These clips remain local private research;
no reference clone or audition is added to the public LulzBench audio registry.
Public casting requires an actual grant covering the selected speaker identity,
cloning and intended publication, or a replacement reference with such evidence.
No rights-holder contact or external message was sent in this task.

All raw attempts, rejected takes, previous research and existing release gates
are retained. LulzBench's unchanged release runner reports **ALL GATES PASS**;
that does not admit this private cast. No acceptance receipt was fabricated and
no public deployment was performed.

All eight player WAVs (six performances plus two optional references) fully
decode and match their filenames' SHA-256. Node control simulation passes for
both the short page and corrected historical page: no forms/autoplay, ordered
A/B, exclusive source/performance playback, pause cancellation, mute, pagehide
and error handling. The full suite passed **834 tests, 2 skipped**; after the
final reference-match guard, all **11 focused casting tests** passed. Browser review
was rejected by the URL policy for `file:`; no alternate serving or browser
workaround was attempted, so rendered/mobile behaviour remains unverified.

Private working evidence lives under
`var/expressive-voice/casting-refinement-1/`; only source, reference hashes,
provenance/QA metadata and these notes are committed. Listening preference and
public identity permission remain separate from the completed local promotion.
