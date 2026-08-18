# QA workplan — afterwords (2026-08-06)

> **For agentic workers:** Use superpowers:executing-plans (or subagent-driven-development)
> to run tasks in order. Release steps (Task 2) follow STRATEGY.md escalate-first:
> this plan being approved by the owner IS that escalation — execute as written.

**Status:** RESOLVED plan (decisions made 2026-08-06, rationale inline — veto by
editing this doc). Source: read-only QA sweep 2026-08-06.
**Baseline:** main = ee05f58 (even with origin), v1.0.6 tagged 2026-06-15,
pytest 670/670 green, OG-metadata CI guard green, live server healthy.
Tracked gallery: 198 profiles / 102 families (from `git ls-files`, per
STRATEGY.md — never count from disk; disk shows 344 with locals).

---

## Task 1 — Ship the splicing tool + docs (both files, mirrored)

**Resolved: ship.** Rationale: the scripts encode the hard-won splicing workflow
already documented in both doctrine files; the AGENTS.md diff also *amends* the
shared splicing paragraph (adds the "do NOT blindly extract / no batch
clone-voice.sh" warning + manual transcript verification), and that paragraph
exists verbatim in CLAUDE.md §8 — shipping AGENTS.md alone is exactly the
parallel-near-duplicate drift STRATEGY.md names. Discarding would throw away
working, referenced tooling for no benefit.

**Files:** Modify `CLAUDE.md` §8, keep the existing `AGENTS.md` working-tree
diff, track `scripts/splice-voice.py` + `scripts/extract-single-segment.py`,
Modify `CHANGELOG.md`.

- [x] Mirror into CLAUDE.md §8 (Voice profiles) the two AGENTS.md changes,
      verbatim: (a) the amended "Splicing references for difficult voices"
      paragraph (the version with "do NOT blindly extract the longest segment
      or use `clone-voice.sh` in non-interactive batch mode" and "manually
      verifying transcripts to exclude multiple actors"), and (b) the
      `> [!TIP]` **Agent Splicing Tool** block documenting
      `python scripts/splice-voice.py --wav <file> --voice <name> --match
      "<unique substring>" --reject-music` and the targeted-YouTube-query
      guidance.
- [x] Add CHANGELOG `[Unreleased]` line:
      `- Add voice-splicing helper scripts (scripts/splice-voice.py, scripts/extract-single-segment.py) and agent docs for the splicing workflow`
- [x] Mute-guard check: `grep -l afplay scripts/splice-voice.py scripts/extract-single-segment.py`
      → expect no output (no new afplay sites), then `pytest tests/test_mute_guard.py -q` → PASS.
- [x] `pytest -q` → 670 passed (or current green count).
- [x] `git add AGENTS.md CLAUDE.md CHANGELOG.md scripts/splice-voice.py scripts/extract-single-segment.py`
      then `git commit -m "docs+tools: ship voice-splicing helper scripts"` and push.
- [x] Done-check: `git status --short` shows no AGENTS.md/CLAUDE.md/scripts
      entries; CI green on the pushed commit.

## Task 2 — Release v1.0.7 (after Task 1)

**Resolved: release now.** Rationale: CHANGELOG `[Unreleased]` already describes
shipped work (the ee05f58 gallery bump), 15 commits sit unreleased past v1.0.6,
all gates green; project cadence (v1.0.3–v1.0.6) is release-when-green, and
letting main drift unreleased is what created the stale-count bugs STRATEGY.md
warns about. Task 1 folds in so one release covers both.

- [x] Recount before writing anything: `git ls-files 'voices/*.json' | wc -l`
      and confirm README / og:description / CHANGELOG agree (STRATEGY.md
      recheck-trigger).
- [x] `python scripts/internal/check-og-metadata.py` → PASS (docs/voices touched
      in Task 1's CHANGELOG edit; STRATEGY.md §4 says pytest alone ≠ release-done).
- [x] Roll CHANGELOG `[Unreleased]` → `[1.0.7] — 2026-08-06` (or actual date);
      commit `chore: release v1.0.7`; push.
- [x] `git tag v1.0.7 && git push origin v1.0.7`
- [x] `gh release create v1.0.7 --title "v1.0.7" --notes "<paste the [1.0.7] CHANGELOG section>"`
- [x] Done-check: `gh release view v1.0.7` returns the release; CI green on the tag.

## Task 3 — Sci-fi voice batch: standing policy + wave 1 scoping

**Resolved: publish in curated, listen-QA'd waves; everything un-QA'd stays
private — "private" is the default state, not a pending decision.** Rationale:
the repo has never bulk-shipped voices; every gallery addition (v1.0.6's 3,
ee05f58's 5) went through listen-QA and a full count sweep, and the CI OG guard
makes a 136-voice dump a high-blast-radius release. But the 2026-07-29 batch
(quark, riker, majel-computer, bender, amos, arthur, ford, zaphod, …16 total)
already passed the owner's listen-tests across 3 rounds — those are
ship-quality and shipping them is consistent with existing practice. The
remaining ~120 untracked voices have no listen-QA on record: they stay private
until some future wave QA's them. Future sweeps: do NOT re-flag untracked
voices as a finding — cite this policy instead.

- [x] Write `docs/superpowers/plans/<date>-voice-wave-1.md` scoping the wave-1
      release: the 16 listen-QA'd 2026-07-29 voices, each needing `{name}.json`
      + `{name}-ref.wav` committed, family fields set where profile variants
      exist, count sweep (README, og:description, CHANGELOG, demo clips), OG
      guard green. Execute it as its own release (v1.0.8-class), NOT folded
      into Task 2.
- [x] Done-check for the policy: this section exists; wave-1 plan file exists.

## Non-goals

- No test/CI/server fixes needed — all green at QA time.
- `scratch_v/` stays untracked (splicing dev workspace) — do not commit or clean.
- Do not tidy `.afterwords` or gitignored personal voices (muse*/vixen*) —
  deliberate local state per STRATEGY.md.
