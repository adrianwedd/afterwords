# Sprint 4 — Server maintenance (design)

**Date:** 2026-05-30
**Owner:** @adrianwedd
**Target release:** v1.0.3
**Status:** approved, ready for implementation plan
**QA:** code-verified against server.py / check-og-metadata.py 2026-05-30 — Part A
origin-scoping resolved (`session_id is None` ⟺ prunable gallery voice; verified
0/281 tracked JSONs set session_id and `/clone` always sets it; restart-safe, no
new registry needed), Part B count enforcement clarified (guard gates the 275
profile number only, not families).

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

**`session_id is None` is the discriminator** (verified against current code,
2026-05-30, including the two construction sites and the clone handler):

- File/gallery voices are built by `_build_voice_profile` →
  `session_id=p.get("session_id")` (server.py:168). **Every git-tracked gallery
  JSON omits `session_id` or sets it `null`** (verified: 0 of 281 tracked JSONs
  carry a non-null `session_id`), so every gallery voice has `session_id is None`.
- Session voices are built by `_register_voice` (server.py:213), whose **sole
  caller is `POST /clone`** (server.py:692), and clone **always** passes the real
  `session_id` in metadata (server.py:700). So every session voice has
  `session_id` set (non-None).

Therefore prune evicts a voice iff **`profile.session_id is None` AND its backing
`voices/{name}.json` is absent from the just-walked on-disk set.** No new
registry, no name-pattern heuristic.

This is also the resolution to the re-discovery hazard: `POST /clone` *does*
persist `{name}.json` into the voices dir (server.py:674-689), so a reload walk
re-discovers session voices. That is harmless here — a re-discovered session
voice keeps its `session_id` (loaded from the JSON it wrote), so it stays exempt.
And it is **restart-safe**: a session clone reloaded from disk after a restart
still has `session_id` set, so prune never evicts it. The conservative direction
(session voices are never auto-pruned; remove them via `DELETE /session`) is the
correct one.

**Keep-set precision.** The prune keep-set is the set of voice *names present on
disk this reload*, derived from the JSON filenames — **not** from successfully
built profiles. A JSON that fails to build (missing ref audio, bad backend) is
still on disk, so its voice must be kept, not pruned. The build walk computes
each on-disk name with the same resolution `_build_voice_profile` uses (stem of
the filename, minus a trailing `-profile`, overridden by the JSON `name` field).

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
3. `prune=true` does **not** remove a session-cloned voice (registered via
   `_register_voice` with a `session_id`) even when its JSON is deleted from disk
   — `session_id is not None` keeps it exempt.
4. `prune=true` with all JSONs still present removes nothing.
5. An aborting build (one `prepare_voice` raises) returns 500 and removes
   nothing — atomic abort still precedes any prune.
6. A pruned family member is no longer selected by lang-routing.
7. A gallery JSON that is on disk but fails to build (e.g. missing ref audio) is
   **not** pruned — keep-set is on-disk filenames, not built profiles.

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

**What the guard actually enforces (verified 2026-05-30):**
`scripts/check-og-metadata.py` `repo_voice_count()` counts `git ls-files
voices/*.json` = **281** today; removing the 6 JSONs → **275**. The guard
compares *only* this profile number against the `N voices` claim in
`docs/index.html`'s og:description — it does **not** enforce a "families" count
(the demo gallery is 21 `docs/audio/*.mp3` files, unrelated to either number).
og:description must therefore read **`275 voices`** exactly (or `275+`, which the
guard treats as "at least 275").

Update every surface that states a count: `docs/index.html` og:description
(gated by `test_og_metadata` — must be 275), plus the editorial **98 families /
275 profiles** prose in `README.md`, `AGENTS.md`, and any inline `docs/index.html`
copy (not gated, update by hand). The guard is the source of truth for the
profile number; if the mechanical `git ls-files` count differs from 275, the
guard's number wins and the prose matches it.

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
