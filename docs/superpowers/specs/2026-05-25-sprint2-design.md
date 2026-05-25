# afterwords (main) — Sprint 2 Design
**Date:** 2026-05-25  
**Status:** Approved — ready for implementation plan  
**Repo:** `adrianwedd/afterwords`

---

## Goal

Tag the current stable state as v1.0.1 and ship the redesigned GitHub Pages homepage.

---

## Part 1 — CHANGELOG + v1.0.1 release

### What

Close issue #73: add a v1.0.1 CHANGELOG entry covering the Opus QA-pass commits that landed after the v1.0.0 tag, then tag and publish a GitHub release.

### Commits to cover

Three commit groups landed on main after the v1.0.0 tag era:

**Security**
- `--host` default tightened to `127.0.0.1` (was `0.0.0.0`). Launchd-managed server no longer exposed on LAN by default.
- `DELETE /session/{id}` now validates `session_id` with the same regex as `POST /clone` — closes input-validation asymmetry.
- `register_all()` isolates experimental-backend imports — one broken backend can no longer crash boot.
- `setup.sh` + Codex hook worker use `awk` exact-field comparison instead of `grep` (AGENT can no longer be interpreted as regex).

**Correctness**
- `qwen3` synthesize now concatenates all output segments (was silently truncating long inputs to first segment).
- `qwen3` `load()` catches `ImportError` with the brew-upgrade hint surfaced to operators.
- `xtts_v2` + `f5_tts` buffer ref audio in `prepare_voice()` to close the TOCTOU race with `DELETE /session`.

**Tests**
- Schema validator, tiebreaker, concurrency smoke, and regression guards added (commit b2cee38). Suite: 505 passing.

**Hook / CLI fixes (PRs #74–76)**
- `afterwords-tts-command.sh`: `bash -c 'echo $PPID'` for play-lock PID (portable on bash 3.2); `mktemp` for temp WAV; 50ms recheck on empty PID file before stale-lock eviction.
- `codex-tts-worker.sh`: removed `eval` on queue content; direct field extraction via `python3`.
- `setup.sh`: `--server-only` flag now correctly gates Gemini, AGy, and shared-hook blocks.
- `afterwords.sh`: `lsof` filtered to `LISTEN` sockets only for `server_pid()`.

### CHANGELOG location

`CHANGELOG.md` at repo root. Append a `## [1.0.1]` section above `[1.0.0]`. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

### Release

- Tag: `v1.0.1`
- GitHub release title: `v1.0.1 — security, correctness, hook fixes`
- Release notes drawn from the CHANGELOG entry (awk extract)
- Close issue #73 with a reference to the tag

### Success criteria

- `CHANGELOG.md` has a `[1.0.1]` entry with all four categories above
- `git tag v1.0.1` exists and is pushed
- GitHub release page is live
- Issue #73 is closed

---

## Part 2 — GitHub Pages redesign (Surface 1)

### What

Replace the existing `docs/index.html` placeholder with the production-ready redesigned homepage. The design source is `afterwords-redesign/Surface 1 - afterwords local.html` (already in the repo as a design handoff deliverable).

### Approach

**Static HTML, no build step.** The handoff HTML is fully self-contained — no framework, no npm. The translation work is:

1. Copy `afterwords-redesign/Surface 1 - afterwords local.html` → `docs/index.html`, replacing the existing page.
2. Copy favicon assets from `afterwords-redesign/favicons/` into `docs/favicons/`.
3. Copy `afterwords-redesign/afterwords-icon.svg` into `docs/`.
4. Update any relative asset paths in the HTML to match the `docs/` layout.
5. Wire in the OG meta tags for `og-local.svg` (already in favicons/).
6. Verify `404.html` and `500.html` from the handoff are not needed for a GitHub Pages site (they are CF Pages–specific; skip them here).

**No Astro build.** The GitHub Pages site has no dynamic content, no templating, and no npm dependency. A static HTML file is the correct tool.

### Design tokens (invariants — do not change)

```css
--color-bg:          #1C1C1A;
--color-bg-elevated: #222220;
--color-bg-sunken:   #141412;
--color-fg:          #EDE8DF;
--color-fg-muted:    #A09A8F;
--color-fg-disabled: #5C5852;
--color-border:      #3A3A37;
/* No accent on afterwords local — copper is cloud/app only */
--color-success:     #6B9E6B;
--color-warning:     #C49040;
--color-error:       #C45C5C;
```

Typography: `-apple-system, BlinkMacSystemFont, "Inter", sans-serif` for prose; `ui-monospace, "SF Mono", "JetBrains Mono", monospace` for all data and code.

Max content width: 720px. Page padding: 24px desktop, 16px mobile. Base spacing unit: 4px.

### CI

Add a GitHub Actions step to the existing CI workflow that verifies `docs/index.html` exists and is non-empty. No HTML validation required — the handoff HTML is already QA'd.

### Git

- The `afterwords-redesign/` directory stays in the repo as the design source of truth. It is not deleted or gitignored.
- Commit message: `feat(docs): implement redesigned GitHub Pages homepage (Surface 1)`

### Success criteria

- `docs/index.html` renders the redesigned page on `adrianwedd.github.io/afterwords`
- All favicon assets resolve (no 404s in browser dev tools)
- OG image tag present and pointing to a valid file
- Existing `pytest` suite unaffected (no Python changes)

---

## Out of scope

- Astro migration
- `afterwords push/pull` CLI (tracked separately as issue #3 in afterwords-cloud)
- Any new backend or server features
- The `afterwords-redesign/` surfaces for cloud or app (those belong to Sprint 2 of their respective repos)
