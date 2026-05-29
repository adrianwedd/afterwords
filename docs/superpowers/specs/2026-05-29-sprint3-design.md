# afterwords (main) — Sprint 3 Design

**Date:** 2026-05-29
**Status:** Ready for implementation plan
**Repo:** `adrianwedd/afterwords`
**Theme:** Mixed maintenance — land the in-flight messaging integration, reclone the two sub-threshold voices, execute the deferred QA followup, and cut v1.0.2.

---

## Goal

Three independent maintenance threads, shipped together as **v1.0.2**:

- **Part A — Messaging integration.** Harden, de-duplicate, test, and document the uncommitted Hermes TTS → Discord/Telegram delivery path so it is correct and predictable. (Security-reviewed clean on 2026-05-29; see `docs/security/2026-05-29-hermes-messaging-review.md`.)
- **Part B — Voice recloning.** Reclone `inspector-morse` (RMS 0.0404) and `francis-urquhart` (RMS 0.0536) to meet the ≥0.07 quality bar, then assign them to currently voice-less repos.
- **Part C — QA followup.** Execute the afterwords-app Stage 2 feature-verification smoke tests deferred from the 2026-05-14 handoff, plus repo housekeeping (gitignore the new cache dirs).

Parts are independent and can be implemented/merged in any order.

---

## Part A — Messaging integration

### Current state (uncommitted working tree)

`scripts/afterwords-post-llm.sh`, `scripts/afterwords-tts-command.sh`, `scripts/strip-markdown.py` are modified; `scripts/tts-feed-send.py` is new. The feature works end-to-end but has correctness defects discovered during review.

### Problems to fix

1. **Duplicate / triple send (correctness).** Three independent code paths can deliver the *same* audio:
   - the `MSG_PLATFORM` branch (`afterwords-post-llm.sh:127`) sends to the originating platform, then `exit 0`;
   - the CLI tail (`afterwords-post-llm.sh:239`) fires whenever **any** `.afterwords` exists and unconditionally sends to **both** Telegram and Discord;
   - `tts-feed-send.py` watches `~/.hermes/tts-archive` (which the CLI tail writes to) and sends every new MP3 again.
   The CLI tail and the feed watcher overlap directly. **Decision — split ownership by direction (not a single owner):**
   - **Inbound / gateway path** (`MSG_PLATFORM`, a remote user messaged the bot): keep **one** inline `hermes send -t "<platform>:<chat_id>"` so the reply lands in the *originating* chat (only the inline path has `chat_id`; see Problem 3). Remove the watcher's involvement for these.
   - **Outbound / CLI path** (local session, no originating chat): remove the inline CLI tail (lines 239–283) entirely; the feed watcher delivers from the archive to the home channel.
   - **De-dup requirement:** the inbound path archives to `~/.hermes/tts-archive`, which the watcher also scans — the watcher must **not** re-send files already delivered inline. Achieve this by pre-seeding `tts-feed-seen.json` from the inline path (mark the archived stem seen at send time), or by having the inline path write only to a non-watched location. The implementer picks one; the invariant is **exactly one delivery per response per platform**.

2. **Egress-on-file-presence (least surprise / privacy).** The CLI tail treats the mere existence of a `.afterwords` file (a local-playback voice config most repos carry) as consent to broadcast every assistant response to external chat platforms. **Decision:** egress requires an explicit opt-in — a `send_to:` directive in `.afterwords` (e.g. `send_to: telegram, discord`) or the env var `AFTERWORDS_SEND_TO`. Absent that, no external send. This is the hardening item carried over from the security review.

3. **Wrong-recipient bug (`CHAT_ID` ignored).** `afterwords-post-llm.sh:54` extracts `chat_id` but never uses it. `hermes send -t telegram` targets the platform's *home channel*, not the originating conversation — so on the gateway (inbound message) path, replies go to the wrong chat. **Confirmed:** `hermes send -t` supports `platform:chat_id` and `platform:chat_id:thread_id` targets (verified 2026-05-29 via `hermes send --help`). **Decision:** thread `chat_id` through as `-t "<platform>:<chat_id>"` whenever it is present, falling back to bare `<platform>` (home channel) when absent. This is the inbound-reply correctness fix, not a deletion.

4. **No test coverage.** `tts-feed-send.py` (chunk merge, stem parsing, seen-state, dry-run) and the slug derivation have zero tests.

### Approach

- **Ownership split by direction.** Remove the CLI tail (lines 239–283). Keep a single guarded inline `hermes send -t "<platform>:<chat_id>"` in the `MSG_PLATFORM` branch for inbound replies. The watcher (`tts-feed-send.py`, run on a schedule/loop) owns CLI/outbound delivery from the archive, and must not re-send anything the inline path already delivered (see Problem 1 de-dup requirement).
- **Opt-in gate** lives in `tts-feed-send.py` (and/or the hook if any inline send survives): read `send_to` from the relevant `.afterwords` / env, default to no-send.
- **Tests** added under `tests/` (pure-Python, no GPU): stem parsing (`parse_claude_stem`), seen-state round-trip (`load_seen`/`save_seen`), `--dry-run` sends nothing, chunk grouping. Mock `subprocess.run` for `hermes`/`ffmpeg`.
- **Docs.** `docs/hermes-integration.md` gains a "TTS audio delivery" section documenting the `send_to:` directive, the single-owner model, and the archive/seen-state layout.

### Invariants (do not change)

- Untrusted text stays URL-encoded before HTTP and slug-whitelisted before filesystem use (preserves the clean security posture).
- All `subprocess.run` calls remain list-form (never `shell=True`).
- Loopback-only synthesis target (`127.0.0.1:7860`).

### Success criteria

- A single assistant response produces **exactly one** delivery per configured platform — verified by sending a known phrase and counting messages.
- With no `send_to` directive, **zero** external sends occur (local playback still works).
- `pytest` green including new `tts-feed-send` tests; suite count rises from 505.
- `docs/hermes-integration.md` documents the opt-in and the single-owner model.

---

## Part B — Voice recloning

### What

Reclone two voices currently below the RMS ≥0.07 quality bar (per `project_voice_assignments` memory) and never assigned to a repo:

- `inspector-morse` — current RMS 0.0404
- `francis-urquhart` — current RMS 0.0536

### Approach

Use the existing `clone-voice.sh` pipeline. Apply the **splicing-for-difficult-voices** procedure from `CLAUDE.md` if no single clean 15s solo-vocal window exists (timestamped whisper pass → spectral mid/high-ratio music heuristic → extract clean windows → per-chunk noisereduce → 30ms fades → 150ms gaps). Re-measure RMS after cloning.

### QA constraints (STRICT — user mandate, from memory)

- One speaker only in the reference WAV.
- No half-words at start/end (verify via `word_timestamps`).
- RMS ≥ 0.07 preferred; 0.06x accepted only if content is demonstrably clean.
- No chatterbox / voxcpm variants.
- Cross-check `project_voice_assignments` before assigning to any repo (every repo must have a unique voice).

### Success criteria

- Both voices reclone to RMS ≥ 0.07 (or a justified 0.06x clean-content exception, documented in the JSON notes).
- Both produce a recognizable clone on listen-test via Qwen3.
- Each is assigned to a distinct currently-voice-less repo (candidates from the memory's "Repos With No .afterwords" list) with no duplicate-voice collision.
- `voices/{name}-ref.wav` + `voices/{name}.json` committed with accurate `reference_text` and `segment_start_s`.

---

## Part C — QA followup + housekeeping

### afterwords-app Stage 2 (deferred from 2026-05-14)

Smoke-test against a **live** server (these were deferred because Stage 1 covered lifecycle only):

- Voice-list window content renders correctly (294 voices).
- Port-override field (Advanced tab) actually changes the probed port.
- Server auto-start toggle behaves on next launch.

Record results in the afterwords-app repo's QA notes; fix any defect found or file it. This part lives in `/Users/adrian/repos/afterwords-app` — out of the main repo tree but in scope for the sprint.

### Repo housekeeping (main repo)

- Add `.wrangler/` and `.playwright-mcp/` to `.gitignore` — both are tool caches that appeared untracked and should never be committed (`.wrangler/cache/wrangler-account.json` contains a Cloudflare account ID).
- Decide the fate of `afterwords-redesign/` cloud/app surfaces (2a/2b/2c/3): they are design sources for *other* repos (afterwords-cloud, afterwords-app). Keep as design source of truth (consistent with Sprint 2's treatment of Surface 1), or move them to their owning repos. Default: keep, and remove the stray `.DS_Store` / `.thumbnail`.

### Success criteria

- afterwords-app Stage 2 items all pass (or defects filed).
- `.gitignore` covers `.wrangler/` and `.playwright-mcp/`; `git status` is clean of cache noise.
- No `.DS_Store`/`.thumbnail` tracked.

---

## Release

- Tag `v1.0.2` after all three parts merge and the pre-tag gate passes (clean tree, `pytest` green, `git log v1.0.1..HEAD` reviewed against the CHANGELOG).
- CHANGELOG `## [1.0.2]` using Keep a Changelog headings: `Added` (tts-feed-send + tests, two voices), `Changed` (single delivery owner, `send_to` opt-in), `Fixed` (duplicate-send), `Security` (reference the 2026-05-29 review — clean).
- GitHub release title: `v1.0.2 — messaging delivery, voice recloning, QA`.

---

## Out of scope

- afterwords-cloud SaaS build (no code yet; separate repo, separate sprint).
- Astro migration; any new backend or server feature.
- Code signing / notarization of afterwords-app (blocked on Apple Developer account).
- (Resolved during planning: hermes *does* support per-chat targeting via `-t platform:chat_id`, so `chat_id` is threaded through in Part A rather than documented as a limitation.)
