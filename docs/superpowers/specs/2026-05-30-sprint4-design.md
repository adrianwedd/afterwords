# Sprint 4 — Server maintenance (design)

**Date:** 2026-05-30
**Owner:** @adrianwedd
**Target release:** v1.0.3
**Status:** approved, ready for implementation plan

## Goal

Drain the server-side maintenance backlog carried out of Sprint 3, plus add
the one piece of real engineering that was deferred since the v1 roadmap:
opt-in removal semantics for hot-reload. Three independent parts in the
`afterwords` repo, then a v1.0.3 release. No external blockers.

## Scope at a glance

| Part | Item | Size | Blocker |
|------|------|------|---------|
| A | Hot-reload removal semantics (opt-in `prune`) | Medium (engineering) | none |
| B | Remove `inspector-morse` + `francis-urquhart` voices | Small | none |
| C | Voice-assignment dedup fix (`ronan` collision) | Small | none |

**Explicitly out of scope:** recloning `inspector-morse` / `francis-urquhart`
(the user decided against keeping these voices — Part B removes them instead);
afterwords-app work; afterwords-cloud work; any new backend, language, or
performance work.

## Sequencing

A (feature + tests) → B (dogfoods A's prune at runtime) → C (config-only) →
release. Each part commits independently so a stall in one doesn't block the
others.

---

## Part A — Hot-reload removal semantics (opt-in prune)

### Problem

`POST /reload` is add-only. It re-walks `voices/*.json` and adds/updates
profiles, but a voice whose JSON has been deleted from disk stays resident in
`VOICES` until `DELETE /session/{id}` (session voices only) or a full server
restart. There is no runtime way to evict a file-originated voice. As the
gallery churns — and as the cloud layer grows toward runtime voice eviction —
this gap matters.

### Design

Add a `prune: bool = False` query parameter to `POST /reload`.

The existing three-phase reload is preserved:

1. **Build** — construct a new `VoiceProfile` per JSON on the dedicated MLX
   thread (`_run_in_ml_thread`), tracking `cleanup_paths` + `owns_temp_audio`
   for rollback. Unchanged.
2. **Atomic abort** — if any `prepare_voice` raises, delete every tracked temp
   file and return 500 with `errors[]`. `VOICES` unchanged. Removal does **not**
   happen on an aborted reload — prune runs only after a clean build. Unchanged.
3. **Commit** under `_model_lock`:
   - existing add-only behavior: `VOICES[name] = profile` for each built profile;
   - **new, only when `prune=true`:** evict every *file-originated* `VOICES`
     entry whose JSON no longer exists on disk, freeing each evicted profile's
     `cleanup_paths` / `owns_temp_audio`.

### Correctness crux — file-origin scoping

Prune must touch **only** voices that came from `voices/*.json`. Session-cloned
voices (added via `POST /clone`, with no backing JSON on disk) must never be
evicted by a prune — a naive "remove any voice whose JSON is gone" would wrongly
nuke every session voice.

Implementation approach (verify exact mechanism against current `VoiceProfile`
during the plan; pick whichever the code already supports):

- **Preferred:** if `VoiceProfile` already records its origin (e.g. a source
  JSON path, or session voices carry a `session_id`), prune iterates only
  file-originated entries and removes those whose recorded JSON path no longer
  resolves on disk.
- **Fallback:** maintain a module-level set of file-built voice names, populated
  at startup discovery and refreshed on every reload's build phase. Prune
  removes names in that set that are absent from the just-walked on-disk set.
  Session voices never enter the set, so they are structurally exempt.

The build phase already walks the current on-disk JSON set, so "names present on
disk this reload" is available for free as the prune keep-set.

### Family-routing interaction

Voice-family lang-routing iterates `VOICES` live under `_model_lock` (no
separate index to maintain). Because prune runs inside the same `_model_lock`
commit, a pruned voice simply stops being a routing candidate on the next
lookup. No extra invalidation needed. A test asserts a pruned family member is
no longer returned by routing.

### Response shape

`POST /reload` response gains a `removed` array (names evicted this call),
reported alongside the existing `added` and `errors`. With `prune=false`,
`removed` is always empty.

### CLI

`afterwords reload --prune` appends `?prune=true` to the curl and pretty-prints
the `removed[]` list in addition to `added`/`errors`. Bare `afterwords reload`
is unchanged (add-only).

### Tests (FakeBackend, no GPU)

1. `prune=false` (default) leaves a voice whose JSON was deleted resident in
   `VOICES` — current add-only contract preserved.
2. `prune=true` removes a voice whose JSON was deleted, and frees its tracked
   temp resources.
3. `prune=true` does **not** remove a session-cloned voice (no backing JSON).
4. `prune=true` with all JSONs still present removes nothing.
5. An aborting build (one `prepare_voice` raises) returns 500 and removes
   nothing — atomic abort still precedes any prune.
6. A pruned family member is no longer selected by lang-routing.

### Docs

- CLAUDE.md "Hot-reload" section: document the `prune` flag and the
  file-origin scoping (session voices exempt; restart or `DELETE /session/{id}`
  still the path for those).
- Reload CLI help / any reload doc: note `--prune`.

---

## Part B — Remove inspector-morse + francis-urquhart

### Rationale

These two voices were the deferred Sprint-3 reclone targets (RMS 0.0404 /
0.0536, below the ≥0.07 bar). The user has decided not to keep them. Remove
rather than reclone.

### Files removed (8)

```
voices/inspector-morse-ref.wav
voices/inspector-morse.json
voices/inspector-morse-qwen3-06b.json
voices/inspector-morse-qwen3-17b.json
voices/francis-urquhart-ref.wav
voices/francis-urquhart.json
voices/francis-urquhart-qwen3-06b.json
voices/francis-urquhart-qwen3-17b.json
```

6 profiles (3 per family) + 2 reference WAVs. Neither voice has a demo
`docs/audio/*.mp3`, neither is assigned to any repo's `.afterwords`, and the
only doc references are the historical sprint-3 plan/spec (left untouched as
historical record).

### Count updates

Advertised counts drop **281 → 275 profiles** and **100 → 98 families**.
Update every surface that states a count: `README.md`, `docs/index.html`
(og:description and any inline count), `AGENTS.md`, demo-site copy. The exact
post-removal numbers are verified against `scripts/check-og-metadata.py` so
`test_og_metadata` stays green — that guard is the source of truth; if the
mechanical count differs from 275/98, the guard's number wins and the prose
matches it.

### Live dogfood of Part A

After the JSONs are deleted on disk, `afterwords reload --prune` against a
running server should evict both families at runtime. This is a manual
verification step, recorded in the sprint notes — it exercises Part A end to
end on real files.

### Memory

Update `project_voice_assignments` memory: drop the two "needs reclone" notes
for inspector-morse / francis-urquhart.

---

## Part C — Voice-assignment dedup fix

### Problem

A live scan of 90 repos with `.afterwords` finds 4 primary-voice collisions; 3
are the known same-remote / fork allowances (malcolm-tucker, spock, data). One
is a genuine new collision: **`ronan` is the default voice on both
`evolve-evolution` and `adrianwedd-ops`**, which do not share a remote.

### Fix

Reassign one of the two to an unused gallery voice. **Default:** `adrianwedd-ops`
gets a distinct unused voice (pick from the gallery, cross-checked against the
live usage scan for no collision); `evolve-evolution` keeps `ronan`. Confirm the
direction at spec review — if `ronan` "belongs" to `adrianwedd-ops`, swap which
side changes.

Apply the constraints from `project_voice_assignments`: single-speaker reference,
RMS ≥0.07 (0.06x clean exception allowed), no chatterbox/voxcpm variants, Doctor
Who companion voices reserved for failure-first repos.

### Memory refresh

Rewrite `project_voice_assignments` to reflect the live state: ~90 repos, the
current 4 collisions (3 allowed + the `ronan` fix), and the date. The 2026-05-04
"all duplicates resolved" snapshot is stale.

---

## Release — v1.0.3

### CHANGELOG `[1.0.3]`

- **Added** — opt-in `prune` for `POST /reload` (`afterwords reload --prune`):
  evicts file-originated voices whose JSON was deleted, scoped to never touch
  session-cloned voices. Reports `removed[]`.
- **Removed** — `inspector-morse` and `francis-urquhart` voices (sub-threshold
  references the project chose not to reclone). Gallery now 98 families / 275
  profiles.
- **Fixed** — `ronan` voice assigned to two unrelated repos; `adrianwedd-ops`
  reassigned to a unique voice.

### Pre-tag gate

```bash
git status                            # clean
.venv/bin/pytest --tb=short -q        # green (suite up by the new prune tests)
git log --oneline v1.0.2..HEAD        # review against CHANGELOG [1.0.3]
```

### Tag + release

```bash
git push origin main
git tag v1.0.3 && git push origin v1.0.3
gh release create v1.0.3 \
  --title "v1.0.3 — hot-reload prune, voice removal, dedup" \
  --notes "$(awk '/^## \[1\.0\.3\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md)" \
  --latest
```

## Testing strategy

All new tests are unit/contract (no GPU): Part A's prune tests run against
`FakeBackend` through the existing reload test harness; Part B is covered by the
existing `test_og_metadata` count guard; Part C is config-only (no code).
`pytest` must run inside `.venv` (`source .venv/bin/activate`) — bare `pytest`
hits system Python 3.14.4 which lacks `soundfile` and errors at collection.

## Success criteria

- `POST /reload?prune=true` evicts file-originated voices whose JSON vanished,
  never evicts session-cloned voices, and reports `removed[]`; `prune=false`
  default behavior is byte-for-byte the old add-only contract.
- `inspector-morse` + `francis-urquhart` gone from the gallery; all advertised
  counts updated; `test_og_metadata` green; `afterwords reload --prune` evicted
  them at runtime once (recorded).
- No primary-voice collision across `~/repos/*/.afterwords` except the documented
  same-remote/fork allowances; assignments memory refreshed.
- `pytest` green inside `.venv`; `v1.0.3` tagged, GitHub release live, CHANGELOG
  complete.
