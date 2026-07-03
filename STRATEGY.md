# STRATEGY.md — Afterwords

This file overrides executor judgment. Conflict between this file, code, docs, git history, live state, or other agent guidance is DRIFT: report it and stop before relying on the disputed claim. It is never permission to guess. Known conflicts recorded below as documented-stale are exceptions: do not stop on those; any new, broader, or unexplained conflict is drift. Every substantive claim is labeled OBSERVED (explicit in code/docs/history/live state) or INFERRED (probable, evidence stated). UNKNOWN items do not appear here.

## 1. INTENT

Afterwords is a local voice-cloning TTS server for Apple Silicon Macs whose agent integrations (Claude Code, Codex, AGy, Gemini CLI, Cursor, Hermes) speak assistant responses aloud. "Done" for most work = `pytest` green, CI green (tests + OG-metadata guard + Pages asset check), CHANGELOG entry, PR merged to main. It is deliberately NOT a cloud service (that is the separate `~/repos/afterwords-cloud` repo — never edit it from a task scoped here), not cross-platform, and not a general TTS library: macOS-only tools (afplay, launchd, mkdir-locks) are intentional (OBSERVED, CLAUDE.md).

Source-of-truth precedence: code + tests > CLAUDE.md/AGENTS.md > README/docs site > memory/session notes. `docs/` is the **published GitHub Pages site** — committed source-of-truth AND externally visible on every push to main (OBSERVED: CI verifies Pages assets; commit 9832d8e fixed its og:description under a CI guard).

Time-sensitive baselines (re-measure, don't quote): latest release v1.0.6, tagged 2026-06-15; shipped voice gallery 97 families / 193 profiles as of 2026-06-15, derived from `git ls-files voices/*.json` — NOT from on-disk counts (OBSERVED: 308 files on disk vs 294 tracked; untracked + gitignored private voices inflate disk counts, and a prior session shipped a wrong count from `ls`). Recheck trigger: any task touching voice counts, README stats, or `docs/` metadata must recount from `git ls-files` first.

## 2. INVARIANTS

- **Never `git add -A` / `git add .`** Stage named paths only. The working tree deliberately carries untracked scratch, and `.gitignore` itself warns "untracked but unignored = git add -A risk" (OBSERVED).
- **Never commit, revert, stash, or "clean up" pre-existing dirty files.** As of 2026-07-03 the tree deliberately carries a modified `.afterwords` (local voice preferences — never commit) and local QA artifacts (e.g. `hermes_qa_*.md`, gitignored). The "helpful" pre-commit tidy-up destroys in-progress work. Leave dirty files alone unless the task names them.
- **Never commit `voices/muse*` or `voices/vixen*`.** Gitignored personal voices that live only on this machine (OBSERVED, .gitignore). `.afterwords` references `vixen` — that file is tracked-despite-gitignore-entry; do not commit local voice-assignment edits to it unless the task says so.
- **Never delete or rewrite tracked `voices/*.json` / `voices/*-ref.wav`** outside an explicit voice-removal task: they ship with releases and back the public demo site (OBSERVED, CLAUDE.md Key Constraints). Voice removals historically go through a release + count-sync sweep (v1.0.3 pattern).
- **Any new `afplay` call site must guard the mute flag** (`[ -f /tmp/afterwords-muted ] || afplay …`) or be added to `tests/test_mute_guard.py` EXEMPT with a written rationale. The test auto-discovers all afplay sites; the tempting shortcut is adding playback "just for this script" — CI fails on it (OBSERVED, commit cc16e25 closed fail-open gaps).
- **Play-lock convention:** PID file at `/tmp/afterwords-play.pid`, NOT inside the lock dir; empty-PID stale detection needs the 50ms recheck (OBSERVED, CLAUDE.md). Don't "simplify" by moving the PID file.
- **All MLX/Metal ops run on the dedicated ML executor thread**; synthesis serialized via `_synth_lock`. Do not add threading, and do not unpin `mlx-audio` (<0.4.1) to "update deps" — a threading incident forced the executor design (OBSERVED design in server.py/CLAUDE.md; pin rationale INFERRED from session memory).
- **Do not loosen server security gates:** `--allow-clone` gating on POST endpoints, Host-header allowlist, `--bind-public` gate, 25MB `/clone` cap, queue-dir chmod-700/ownership checks (OBSERVED, commits 981c1fd/108bd37/f1548ef/e625062, audit-driven). The tempting shortcut is relaxing a gate to make a test or demo pass.
- **Editing any voice-count-bearing text** (README, `docs/index.html`, og:description, CHANGELOG) requires the counts to agree; CI runs `scripts/internal/check-og-metadata.py` and fails on drift (OBSERVED).
- **Do not modify doctrine** (this file, CLAUDE.md, AGENTS.md, skill/SKILL.md) unless the current task names the file. CLAUDE.md and AGENTS.md are parallel near-duplicates (Claude Code vs Codex audiences); an authorized edit to one usually needs the same edit in the other or they drift (OBSERVED duplication).
- **Do not act on the hermes 2026-06-21 audit's hygiene claims without re-verifying.** It claimed `.DS_Store` and `.claude/scheduled_tasks.lock` were git-tracked; `git ls-files` disproved both on 2026-07-03 (documented-stale evidence — issue #106 closed as invalid). Untracked lint on disk (`.DS_Store`, `default.profraw`, `__pycache__`) is already gitignored; cleaning it mid-task is scope creep.

## 3. DECISIONS & GRAVEYARD

- **Qwen3-TTS (0.6B default, 1.7B opt-in) is the only endorsed cloning path.** 15 other registered backends are experimental. Decided by listen-tests 2026-05-16 (OBSERVED, CLAUDE.md). Revisit trigger: a new listen-test round, not a benchmark or hunch.
- **Chatterbox and VoxCPM backends removed entirely** (commit f03e826): failed listen-test; VoxCPM 500'd under launchd (OBSERVED). Do not re-add.
- **inspector-morse and francis-urquhart voices removed in v1.0.3; ronan deduplicated to mckenna** (OBSERVED, memory + CHANGELOG). Do not resurrect from git history.
- **`/reload` is add-only by default; pruning is opt-in (`?prune=true`) and scoped to file-originated gallery voices** (OBSERVED, CLAUDE.md). Do not "improve" reload to auto-remove missing voices.
- **Reference-clip splicing procedure for contaminated sources** is codified in CLAUDE.md (spectral mid/high heuristic, per-chunk denoise, fades, gaps). Follow it; don't invent an alternative pipeline.
- **A prior Stripe/CF-token-in-.env security finding was explicitly DISMISSED by the owner 2026-06-15** (local-only, never committed). Do not re-flag it (OBSERVED, session memory — documented-stale-adjacent: this is a standing owner decision, not drift).
- **QA convention:** high-blast-radius changes get review-only peer-agent QA rounds via `codex exec -s read-only`, `hermes -z`, `agy -p` (OBSERVED pattern across sprints 3–6). GitHub issues are the parking lot for deferred findings (OBSERVED, issues #79–#94 workflow).

## 4. FAILURE MODES

- **Shortcut:** count voices with `ls voices/`. **Tell:** number ≠ og:description/README, or CI OG guard fails. **Correction:** count `git ls-files 'voices/*.json'`; families vs profiles are different numbers.
- **Shortcut:** run the full backend/fidelity test "for completeness." **Tell:** `pytest -m integration tests/test_fidelity.py` loads ~10 GB Metal models and requires the live server stopped. **Correction:** default `pytest` only (no GPU, server may stay up); the fidelity test self-skips when the server is running — that skip is a feature, not a failure.
- **Shortcut:** restart/stop the launchd server to "get a clean state." **Tell:** `afterwords status` showed it healthy before you touched it. **Correction:** the server is the owner's live, in-use TTS; don't stop/restart it unless the task requires it, and restart it after if you did.
- **Shortcut:** `rm -rf /tmp/afterwords-play.lock` whenever a lock exists. **Tell:** audio is currently playing. **Correction:** only clear locks that are actually stale (PID dead), per CLAUDE.md.
- **Shortcut:** treat `pytest` pass as release-done. **Tell:** CI also runs the OG-metadata guard and Pages asset checks that local pytest habits skip. **Correction:** run `python scripts/internal/check-og-metadata.py` too when docs/voices changed.
- **Shortcut:** summarize or tidy `docs/superpowers/*`, `transcripts/`, or QA reports. **Tell:** file is dated/handover/QA-named. **Correction:** evidence — append-only history; never rewrite.
- **False-success trap:** older session notes claiming "Sprint 6 CLI unstarted" were WRONG (it shipped in v1.0.5). Trust code + git over narrative notes; verify claims from history before acting on them (OBSERVED, memory corrected 2026-06-15).

## 5. ESCALATION TRIGGERS

Stop before the gated action; continue safe preparatory work (diagnosis, draft patches, branch-ready diffs, dry-runs) and deliver it. Always escalate: drift between sources of truth; destructive/irreversible ops (deleting voices, force-push, history rewrite, `rm` outside scratch/tmp); scope creep beyond the named task; stale time-sensitive facts (voice counts, version numbers, deployment state).

Side-effect classification for this repo:
- **Allowed without asking:** reading anything; `pytest` (default suite); static checks; local `curl localhost:7860/health` and GET `/synthesize` reads; building patches on a branch; `git log/diff/status`.
- **Escalate first:** push/merge to main (publishes `docs/` to GitHub Pages — externally visible); tagging/releasing; `afterwords stop/restart` or killing the launchd service; running `setup.sh` (writes `~/.claude/`, `/usr/local/bin` symlink, launchd plist — system mutation); `clone-voice.sh` (external YouTube fetch + big downloads); POST `/clone`, `/reload?prune=true`, `DELETE /session/*` against the live server; editing `~/.claude/hooks/*`, `~/.gemini/*`, `~/.cursor/*` (live hook config of other tools); modifying doctrine or evidence files; anything touching `afterwords-cloud` or Cloudflare/Stripe tooling.
- **Forbidden:** committing gitignored private voices; deleting evidence files; publishing or exfiltrating voice reference audio outside the repo's existing channels; clearing an active (non-stale) play lock.

GitHub issue filing is conventional here for non-sensitive deferred findings; search for duplicates first. A task is human-blocked only when no safe preparatory work remains — a blocked push/release/deploy alone is not "blocked."

## 6. VERIFICATION

Run in order; report actual output:
1. `pytest --tb=short -q` — expect all pass/skip, 0 failures (suite ~520 tests as of 2026-06-15; re-measure).
2. `python scripts/internal/check-og-metadata.py` — expect exit 0 (only needed when docs/voices/counts changed).
3. Pages asset check (when `docs/` changed): `test -s docs/index.html && test -s docs/404.html && test -s docs/favicons/og-local.png` — expect success.
4. Live-server checks (read-only): `afterwords status`; `curl localhost:7860/health` — expect HTTP 200 JSON with `loaded_backends`. Only if the server was already running; do not start it to verify.
5. Fidelity (only when a task explicitly targets cloning quality, and with owner-approved server stop): the CLAUDE.md `pytest -m integration tests/test_fidelity.py` sequence.

Verification never grants permission: if a check needs a push, release, deploy, server restart, or live mutation, report the blocked step instead. Read before write; after any authorized live write (e.g. `/reload`), read back (`/health`, voice list) and report.

If `pytest` dies with `bad interpreter`, the venv broke via a Homebrew Python bump; the fix is `bash setup.sh --server-only` — but that is a system-mutating command: escalate unless the task authorizes it.
