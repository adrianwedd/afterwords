# Casting correction — 2026-10-17

Historical correction record; see [CLOSEOUT.md](CLOSEOUT.md) for final engineering
status. For the subsequent human feedback, Vixen's
Drama/Seydoux promotion and the shorter matched audition, see
[CASTING_REFINEMENT.md](CASTING_REFINEMENT.md). Statements below about the live
Qwen route or missing feedback describe the earlier checkpoint.

The operator rejected the synthetic Vixen candidate as a random male voice and
did not accept the LulzBench cast. That conversational feedback is the current
verdict; the previous handoff is superseded.

Open the new private listening room at
`var/expressive-voice/casting-correction-1/listen/index.html`.
It contains Vixen's two recordings and exactly four recast/baseline pairs.
There are no forms, coverage selectors or acceptance ceremonies. Reply normally.

## Vixen: actual cause and correction

M5's established `.afterwords` mapping selects `seydoux`. However, her active
Hermes provider and legacy hook overrode it with `vixen-original-r1-live` on
port 17862. Afterwords resolved that name to an **unconditioned synthetic**
reference (seed 9502; SHA `61a98494…`). It was not Seydoux. The rejected rendered
reply is `16dd4fe3…wav`. The earlier activation replaced her voice identity
before listening acceptance; preserving the rest of the config did not make
that speaker replacement correct.

Both Vixen speech paths now explicitly select **Qwen/Seydoux on M5 port 7860**.
The existing 25-second Seydoux reference is SHA
`a8bd5856cb6dfc1bc06dd0a49d9d146503fa9e7de25d308e0cae2cdacb438d44`.
Only provider voice/command and the legacy speech-hook command changed; all
other config fields, including model/persona/tool/memory settings, were retained.
The correction used Hermes' atomic config API, an exact before-hash guard and
native approval of only the changed speech hook. No credentials were changed.
`scripts/restore-vixen-seydoux.py` preserves the private before-config on M5.

Vixen's idle gateway was refreshed to drop its cached old hook; no active turn
lease existed. `launchctl kickstart -k` produced an unclean predecessor exit
(SIGKILL), retained in `vixen-gateway-refresh.json`; the new gateway reconnected
to Telegram. No other gateway or Afterwords service was restarted.

Real Hermes session **20261017_111422_ea4790** generated a new two-sentence reply
through the configured Qwen/Seydoux provider: two native artifacts, one native
post-LLM owner, zero provider playback calls. The model remained
`Qwen3.8-Flash-Next-UD-Q4_K_XL`. Physical playback was captured, not heard, and no
external message was sent. The one-shot GUI probe job was unloaded.
The installed gateway handoff also passed, including native-tool deduplication
and refusal to substitute the default bot for a disconnected Vixen adapter.
Its first capture failed because SSH PATH omitted ffprobe; the retained second
capture used the normal tool PATH and passed.

Drama rendered the **same real reply using the same Seydoux reference**.
Both versions had zero CPU Whisper word edits. ECAPA windows scored Qwen
0.838/0.772 against Seydoux, Drama 0.659/0.651. The rejected old reply scored
-0.027/-0.038 against Seydoux and 0.899/0.872 against the synthetic reference.
These are supporting identity measurements, not listening approval. Qwen
remains live; no Drama identity acceptance is inferred.

## Four preliminary casting choices

All excerpts come from complete public LulzBench captures. Aster uses the Roast
Club minutes (Gemma, LULZ-0331); Hugo, Iris and Jasper use the Pasta Wars exchange
(Qwen stock, OBLITERATED and Huihui respectively, LULZ-0199). Complete prompts
and model replies are expandable in the player. Original excerpt words remain
unchanged; Markdown formatting is removed with strict lexical equality checks.
Each baseline regenerates that same excerpt with its previous cast reference
and neutral Drama delivery. These are matched baselines, not old full-response WAVs.

- **Aster:** bright, emphatic prodigy; calm-to-indignant delivery against beige
  committee procedure. Lisa reference, Drama; 17.09 seconds.
- **Hugo:** low, restrained disdain; a sigh before the scientist's wounded
  “To suggest”. Snape reference, Drama; 28.42 seconds.
- **Iris:** smoky low alto; retain the reference's texture without forcing
  dramatic control tokens. Eartha reference, **Qwen**; 17.84 seconds.
- **Jasper:** conversational showman, turning amused at the Maternal Gambit;
  longer comic holds instead of the original brisk recital. Cat reference,
  Drama; 39.06 seconds, longest measured near-silence 2.78 seconds.

The old cast remains not accepted. I discarded the Rimmer/Jasper take after a
503 delivery failure; Avasarala/Iris after a possible added “logical”; and
Drama/Eartha after severe omissions (47/59 ASR edits, 52.15 seconds). No failed
take was repaired by deleting generated words or hiding it behind fallback.
A Qwen probe initially failed the harness's incorrect backend-header check
(`X-Afterwords-Backend` instead of the actual `X-Backend`); this was an
instrumentation error. The corrected harness checks the actual backend header
and now persists every returned payload before validating it. That failed
attempt's receipt is retained; its response bytes were not saved.

The four selected performances have zero CPU Whisper edits. Baseline differences
are only organization/organisation and four/4. These checks screen omissions,
not artistic quality. The casting choices follow contrasting register, texture,
role and comic direction; **no independent human listening or artistic acceptance
is claimed**. The available audio observer previously failed a silence control
and was deliberately not used as an artistic judge. Natural feedback on these
four performances is still needed before claiming the artistic goal achieved.

A subsequent CPU reference screen compared every selected recording against all
four chosen references. Its intended reference ranked first in all 11 measured
windows (`cast-reference-screen-1.json`), supporting distinct speaker conditioning
without establishing artistic quality. Jasper's match was weaker than the other
three. A single same-reference Qwen alternative improved that match but introduced
an unresolved ASR disagreement on “pasta”/“aposto”; it was not promoted. The original
four-pair page stays unchanged and that alternative remains private evidence.

Directions and source/reference digests are retained in
`casting-directions.v2.json`. All attempts, reference copies, raw chunks and
audits are private under `var/expressive-voice/casting-correction-1/`.
The established character references are private audition material, not cleared
public cast assets. No public registry or release manifest was replaced.

## Operator listening feedback — 2026-10-17

The operator subsequently reported: “B is better almost always. vixen is good,
Hugo/defaults sound a bit more shit than the qwen cloned voices?” This supersedes
the earlier statement that no listening feedback had arrived. It is a general
preference for B, positive feedback on Vixen, and a remaining quality concern
about Hugo/default voices; it does not identify every exception or approve every
recording, pronunciation, or public release. The artistic outcome now has human
listening evidence but remains only partially resolved.

The page's backend mapping matters: Vixen A is Qwen/Seydoux and B is
Drama/Seydoux; Aster B is Drama/Lisa; Hugo B is Drama/Snape; Iris B is
Qwen/Eartha; Jasper B is Drama/Cat. All four cast A recordings use neutral Drama
with the previous cast references. “Qwen stock” in Hugo's title identifies the
text-generating model, not the speech backend. These pairs therefore do not
establish a general Qwen-versus-Drama quality verdict: the cast comparisons also
change reference and direction. Vixen's pair holds reference and reply constant.

No new sample generation, live routing change, acoustic gate completion, or
deployment is implied by this feedback. Vixen's documented live choice remains
Qwen/Seydoux pending a specific decision to change it. Hugo remains an unresolved
casting-quality concern.

## Verification and release boundary

All ten player WAVs were fully decoded with ffmpeg and rehashed. A/B text hashes
match within every pair. Non-browser control simulation verifies five pairs,
no forms/autoplay, ordered playback, one player, pause cancellation, mute,
pagehide stop and media-error cancellation. Node syntax check passes.
Current rendered/browser/mobile behaviour remains unverified after the earlier
access rejection; no alternate browser or serving workaround was attempted.

LulzBench's unchanged full release-gate runner passes, as do its 88 non-browser
tests plus 44 subtests. Its old private candidate still fails closed with eight
missing acoustic receipts. No new acceptance receipt is created and no public
deployment is performed. Afterwords: **832 passed, 2 skipped**; the preceding
focused correction/showcase run passed 11 tests. Logs are retained in
`final-full-tests.log` and `final-focused-tests.log` beside the audio.
Unrelated dirty work in both repositories remains untouched.
