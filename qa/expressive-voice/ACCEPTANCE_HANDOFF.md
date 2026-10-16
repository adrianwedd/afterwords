# Expressive voice listening handoff — 2026-10-17

Open the single local listening entry point:
`var/expressive-voice/acceptance-handoff-1/listen-2/index.html`.
This is a private generated artifact, not a public site or a browser-access workaround.
No automated browser was opened and no HTTP listening server was started.

The page packages the retained `acceptance-handoff-1/inventory.json` and
`cast-reference-inventory.json`: 12 showcase cards plus 18 original synthetic
cast references, using 29 unique, unchanged WAV files. All five unique Collection
audio/text/voice bindings are represented; eight entry mappings remain intact.
No synthesis, audio editing or replacement demonstrations were used.

The listening order is Qwen/Drama same-word A/B; three same-word emotions;
Vixen's configured reply; Aster/Gemma, Hugo/Qwen stock, Iris/OBLITERATED and
Jasper/Huihui; the complete Stage Manager/Iris request and answer (141.92s);
then the full cast reference gallery. Each card identifies the backend, duration,
transcript, hashes, permissions and specific listening questions. Hugo/Jasper
timestamp buttons expose the existing word flags within the complete recordings.

Use each card's verdict, coverage and observation fields, then Copy verdict.
Clipboard failure selects the summary for ordinary manual copy. Identical
audio/text cards share one review; unmentioned recordings remain pending.
Notes exist only for the page session. Copy before closing. This concise reply
is review input, not a generated acoustic receipt or a release-gate mutation.

## Verification completed this turn

- Packaged bytes rehashed and all 29 unique WAVs fully decoded with ffmpeg
  (`-v error -xerror ... -f null -`), without playing them or inferring quality.
- Showcase text/audio hashes, candidate manifest digest, all five Collection
  bindings and all 18 cast audio/provenance text hashes checked before packaging.
  Backend A/B and the three emotions have identical respective text hashes.
- Node syntax check passed. A non-browser event simulation passed no autoplay,
  A/B and exchange order, single-player exclusivity, pause/sequence cancellation,
  timestamp seek assignment, mute, pagehide stop, partial-coverage warning,
  clipboard fallback and playback-error cancellation. These checks do not test
  browser media, rendered layout, actual seeking or real clipboard permissions.
- Afterwords full suite: **824 passed, 2 skipped**. LulzBench non-browser suite:
  **88 passed, 44 subtests passed**. Initial system-Python unittest discovery
  lacked pytest; the complete non-browser suite then passed using Afterwords'
  existing test environment. No dependencies were installed.
- LulzBench's unchanged `scripts/run_gates.py`: **ALL GATES PASS**, including
  Astro build, secrets scan, licensing, excerpt audit, holdout membership,
  B-sides, corpus integrity, source/dist release boundaries, editorial boundary,
  Collection snapshot, claims and existing explorer-bundle assertions.
  Logs: LulzBench `build/acceptance-handoff-gates.log` and
  `build/acceptance-handoff-pytest.log`.
- Private candidate validation still exits **1**, solely for **eight missing
  acoustic acceptance receipts**. No audio/text/model/voice binding errors.
  Passing the public text-only release gates does not admit this private audio.
- Local `127.0.0.1:7860/health` reports ready, loaded Qwen 0.6B. No runtime
  restart, synthesis, profile change, M5 change, activation or deployment occurred.
  This health check does not establish installed expressive integration acceptance.

## Mobile evidence: historical tests versus remaining verification

Historical evidence was read this turn, not rerun:

| Surface | Behaviour actually tested | Scope |
| --- | --- | --- |
| Collection transport fixtures, Chrome 390×844 | No autoplay; request then answer exactly once; replay; pause cancels continuation; mute; text-only hides controls and preserves text; stale text suppresses audio; no horizontal overflow; play target at least 44px | Synthetic transport WAVs; `tests/e2e/test_collection_audio.py`, retained `build/audio-browser-final.log` (2 passed) |
| Actual Collection route, same viewport | Two paused players; controls before response; mobile screenshot | Same synthetic fixtures, not model listening |
| Older showcase-1, Chrome 390px | Real 6.16s WAV decode/play/pause/mute; no autoplay; no overflow or JS errors; mobile/desktop screenshots | Muted playback, one Qwen clip; retained `qa/expressive-voice/showcase-1/browser-check.json` and PROGRESS checkpoint 7 |

Browser access to a subsequent local showcase file URL was rejected. That
rejection was respected: no alternate browser, headless browser, HTTP serving or
other access path was attempted to get around it. Current showcase-6 and this
handoff page have **no rendered mobile/browser verification**. Current layout,
native controls, actual seeking, ordered playback, clipboard permission,
accessibility/focus/touch interaction, audible output, real phone/iOS Safari,
background and lock-screen behaviour remain unverified. Historical screenshots
and current event simulations cannot establish those behaviours.

## Remaining acceptance decisions and implementation status

Human review must decide comic timing and backend preference; believable emotion
with stable identity; recognisable Vixen signature; distinct and recognisable
model characters/full cast; pronunciation and exact-word fidelity, particularly
the flagged Hugo/Jasper words and the sad-emotion you/he disagreement; sustained
delivery, transitions and completeness of the long exchange. Full recording
coverage must be distinguished from spot checks. Reference review alone cannot
approve a response performance.

The original implementation was already pushed at Afterwords `ce79998` and
LulzBench `ef83fd0`. This handoff adds only a private packaging command, local
review UI, control-check harness and documentation. It does not reopen synthesis
development. General long-form Drama qualification still has retained omission,
silence and frame-budget failures; this selected exchange does not resolve them.
No listening approval is inferred, no acoustic receipts are written, all release
gates remain in force, and no deployment is performed. Unrelated dirty work in
both repositories is preserved.

Reproduce into a new empty output directory, preserving prior evidence:

```sh
.venv/bin/python scripts/build-acceptance-handoff.py --out /absolute/private/output
node tests/check_acceptance_controls.cjs /absolute/private/output
```

The recordings, generated page and private inventory stay local and excluded
from Git. Source/template/checker improvements are committed and pushed on the
existing Afterwords feature branch.
