# Afterwords CLI Expansion — Design Spec
**Date:** 2026-06-04  
**Sprint:** 6 (implementation)  
**Status:** Draft — QA complete (Codex, 22 findings; 18 addressed below)

---

## Goal

Expand the `afterwords` CLI from a server-management tool into a complete voice-curation workbench. Add analysis and transcription subcommands, wire a full QA/refine pipeline into the clone workflow, expose a self-update command, and publish an `--ai` guide so agents can operate the tool without reading source.

---

## Background

Seven scripts in `scripts/` handle voice analysis, transcription comparison, and archive auditing but are only accessible by running Python directly. `clone-voice.sh` accepts only YouTube URLs. There is no update command, no structured help for agents, and the help output does not surface the analysis tools. This spec closes all four gaps.

---

## Out of Scope

- Gallery size redesign (ship fewer voices by default, rest downloadable) — deferred to Sprint 7.
- Cloud API changes.
- New voice reclones.

---

## 1. New Subcommands

All new analysis subcommands follow the existing `audit` pattern: activate the venv, validate the script exists, then `exec python3 "$script" "$@"`. All flags pass through unmodified so the underlying scripts remain usable standalone.

### 1.1 `afterwords transcribe <audio> [OPTIONS]`

Wraps `scripts/transcribe.py`. Produces word-level timestamps as JSON.

```
afterwords transcribe ref.wav
afterwords transcribe ref.wav --backend parakeet
afterwords transcribe ref.wav --out transcript.json
```

Key passthrough flags: `--backend faster-whisper|parakeet`, `--model NAME`, `--out FILE`.

### 1.2 `afterwords qa [OPTIONS]`

Wraps `scripts/qa-voices.py`. Transcribes reference WAVs, reports WER; optionally synthesises a test phrase and scores that too.

```
afterwords qa                        # all voices, ref only
afterwords qa --voice gandalf        # single voice
afterwords qa --synth                # also run synthesis tests (slow)
afterwords qa --out results.tsv
```

Key passthrough flags: `--voice NAME`, `--synth`, `--ref-only`, `--out FILE`.

### 1.3 `afterwords trim [OPTIONS]`

Wraps `scripts/trim-silence-gaps.py`. Dry-run by default; `--apply` writes changes.

```
afterwords trim                      # dry run — show what would change
afterwords trim --apply              # write trimmed WAVs + refresh transcripts
afterwords trim --voice the-doctor --apply
```

Key passthrough flags: `--apply`, `--voice NAME`.

### 1.4 `afterwords compare <audio> [OPTIONS]`

Wraps `scripts/compare-transcription.py`. Runs faster-whisper and parakeet on the same file and prints a WER comparison table.

```
afterwords compare voices/gandalf-ref.wav
afterwords compare ref.wav --skip-parakeet
afterwords compare ref.wav --skip-whisper
```

Key passthrough flags: `--skip-parakeet`, `--skip-whisper`, `--duration SECS`, `--out-dir DIR`.
Note: `compare-transcription.py` has no `--model` flag — do not document one.

### 1.5 `afterwords audit` (extended)

The existing `afterwords audit` wraps `scripts/audit-voice-transcripts.py` (voice profile drift). A new `--archive` flag switches to `scripts/audit-archive.py` (TTS archive pair auditing).

```
afterwords audit                     # voice profile drift (existing behaviour)
afterwords audit --voice picard      # single voice
afterwords audit --archive           # audit TTS archive .mp3/.txt pairs
afterwords audit --archive --json    # machine-readable archive audit
```

The `--archive` flag is detected in `cmd_audit()` before passthrough; the remaining flags are forwarded to whichever script is selected. Note: `audit-archive.py` does not support `--voice` filtering — do not document that combination.

**Rationale for extending `audit` rather than a new `audit-archive` command:** keeps the surface area flat and groups related auditing concerns under one verb.

### 1.6 `afterwords refine <voice> [--quick]`

Chains the four analysis tools in sequence for a single named voice. This is the recommended post-clone verification step and is also called automatically by `clone` (unless `--quick` is passed there).

```
afterwords refine gandalf
afterwords refine gandalf --quick    # skip compare and trim steps
```

**Step sequence:**

```
Step 1/4  qa --voice <name> --ref-only --json
          → parse ref_wer field; if > 0.15 print warning but continue
          → child exit 1 (WER warning) → warn and continue
          → child exit 2 (hard error) → abort refine with exit 2

Step 2/4  compare voices/<name>-ref.wav
          → print winner; if parakeet wins, note it but do not change the profile
            (backend selection is a separate decision requiring reclone)
          → child exit 1 or 2 → print warning, continue to step 3

Step 3/4  trim --voice <name> --json  (dry run; reads gap_count from JSON output)
          → if gap_count == 0: print "✓ no silence gaps", skip prompt
          → if gap_count > 0: show details, ask "Trim and rewrite reference? [Y/n]"
          → on Y: re-run trim --apply --voice <name>
          → child exit 2 → abort refine with exit 2

Step 4/4  qa --voice <name> --ref-only --json
          → re-measure WER after any trim; print final ref_wer summary line
          → this is a re-run of step 1, not audit-voice-transcripts.py
          → audit --voice is NOT used for WER (it reports drift flags, not WER)
```

`--quick` skips steps 2 and 3 (compare + trim) but still runs steps 1 and 4.

**Exit code chaining:** `refine` treats child exit 1 as "warning — print and continue". Child exit 2 in any step aborts `refine` immediately with exit 2. This means implementors must not use `set -e` around the step subprocess calls; check `$?` explicitly.

**Exit codes for `refine` itself:** 0 = all steps clean or warnings only; 1 = final WER (step 4) > 0.15; 2 = any step hard-errored.

### 1.7 `afterwords update [--check]`

Self-update: pull latest commits, reinstall packages, reload voices.

```
afterwords update           # pull + install + reload
afterwords update --check   # print available commits, exit without changing anything
```

**Sequence:**

1. Verify the repo is a git working tree (`git rev-parse --git-dir`). If not (e.g. tarball install), print a clear message and exit 1.
2. Activate `${REPO_DIR}/.venv` — same pattern as all other CLI commands. Fail clearly if venv is missing.
3. `git fetch origin`
4. Report N commits available. `--check` exits here. Note: `--check` does modify `.git/FETCH_HEAD` and remote refs — "no changes" means no working-tree, package, or server state is modified.
5. Check `git status --porcelain -- voices/` — if any tracked voice JSON or WAV is dirty, warn specifically ("your local edits to voices/ may be overwritten") and ask confirmation before proceeding.
6. Check `git status --porcelain` for any other modifications — warn and ask confirmation before pulling.
7. `git pull --ff-only` — fast-forward only; if diverged, print instructions to merge manually and exit 1.
8. `pip install --quiet -r requirements.txt && pip install --quiet -r requirements-clone.txt` (if clone file exists).
9. If the server is running, call `afterwords reload` (add-only — voices deleted from disk do NOT disappear; use `afterwords reload --prune` explicitly for that).
10. Print a summary: git refs before → after, files changed, voices added (not removed — add-only reload).
11. If `afterwords.sh` or `setup.sh` was among the changed files, print: *"Setup files changed — run `bash setup.sh` if behaviour feels wrong."* Do not attempt to re-exec the running shell process.

**User voice safety:** `git pull` only touches tracked files. Untracked user-cloned voices in `voices/` are never affected.

---

## 2. `clone` Improvements

### 2.1 Local audio file support

If the first positional argument to `afterwords clone` (or `clone-voice.sh`) is an existing file path, skip `yt-dlp` and use it as the audio source directly.

**Detection:** `[ -f "$1" ]` checked before the yt-dlp block. Accepts any format `ffprobe` can read (WAV, MP3, M4A, FLAC, etc.).

**Profile JSON:** `source_url` is set to `"local-file"` and a new `source_basename` field records only the filename (not the full path). Absolute paths are not stored — they leak filesystem layout when voices are committed or pushed to cloud.

**Interactive flow:** unchanged — user is still asked for start time and voice name unless provided as positional args.

### 2.2 Auto-refine after clone

After a successful clone, `clone` runs `afterwords refine <name>` automatically.

`--quick` on the `clone` command passes `--quick` to `refine`. This runs steps 1 and 4 (qa + re-audit) but skips steps 2 and 3 (compare + trim). It is not a full skip — the basic sanity check still runs. The distinction:
- `clone URL NAME` → full refine (qa → compare → trim → re-audit)
- `clone URL NAME --quick` → fast refine (qa → re-audit only)

**Non-interactive / `--yes` mode:** auto-refine runs. The trim prompt in step 3 is suppressed (treated as "n"). Rationale: fully non-interactive callers must not block on a TTY prompt. Transcript confirmation and start-time prompts are also suppressed when all positional arguments are provided; if a required positional is missing with `--yes`, the script fails immediately rather than prompting.

**Argument parsing note:** existing `clone-voice.sh` uses raw positional args (`URL NAME [START] [--yes]`). Adding `--quick` requires care to avoid misparse when combined with `--yes` or a numeric START. Implementation must handle `--quick` as a named flag separate from the positional sequence.

---

## 3. `afterwords --ai` Flag

`afterwords --ai` prints `docs/ai-guide.md` to stdout. The guide is a standalone Markdown document maintained separately from the shell script so it can be updated without touching `afterwords.sh`, and agents can also `cat` it directly from the repo.

**Flag handling:** detected before the main `COMMAND` dispatch so it works as `afterwords --ai` (not a subcommand). Always prints raw Markdown to stdout — no pager, even on a TTY. Agents frequently pipe `afterwords --ai | head` or capture the output; a pager would block them.

**`docs/ai-guide.md` structure:**

```
# Afterwords — AI Assistant Guide
## Version
## Critical: First-Run Setup
## Command Reference
   ### Server commands
   ### Voice commands
   ### Analysis commands
   ### Clone workflow
   ### Cloud commands
   ### Update
## Workflow Sequences
   ### Clone and verify a voice
   ### QA an existing voice library
   ### Full refine cycle
   ### Update the server
## Agent Tips  (numbered rules)
## Common Failures and Fixes
```

The **Agent Tips** section mirrors `nlm --ai` in format: numbered, terse, one rule per line. Examples:
1. Always check `afterwords status` before synthesising — the server may be warming up.
2. Use `--quick` when cloning in automation; run `refine` as a separate step after review.
3. `afterwords qa --json` for machine-readable WER output; parse `ref_wer` field.
4. Do not call `trim --apply` without reviewing `trim` dry-run output first.
5. `afterwords update --check` before `update` in agent workflows — confirm no dirty state.

---

## 4. Help Redesign

The help output is reorganised into six named sections. The **Analysis** section is new; all existing commands are redistributed:

```
Server      start, stop, restart, status, logs
Voices      voices, clone, reload
Analysis    transcribe, qa, trim, compare, audit, refine
Cloud       setup-cloud, push, pull
Integrations codex-hook
Setup       configure, update, uninstall
```

Each command line shows the command, a richer description, and the most useful flag(s):

```
  Analysis
    transcribe <audio>    Word-level timestamps (--backend parakeet|faster-whisper)
    qa                    Ref WER for all voices (--voice NAME, --synth)
    trim                  Remove silence gaps from refs (--apply to write)
    compare <audio>       faster-whisper vs parakeet WER comparison
    refine <voice>        Full QA cycle: qa → compare → trim → audit (--quick to skip compare/trim)
    audit                 Voice profile drift check (--archive for TTS archive pairs)
```

Examples block at the bottom is extended with one example per new command.

---

## 5. Script Polish

All user-facing analysis scripts receive a light consistency pass:

- **Progress markers:** when stdout is a TTY (`sys.stdout.isatty()`), print `✓`, `⚠`, `✗` prefix lines matching the shell helper style. When stdout is redirected (pipe, file), print plain text only — no ANSI.
- **`--json` flag:** all scripts that don't already have it get a `--json` flag that suppresses human output and prints a single JSON object to stdout. Required fields per script:
  - `qa --json` → `{ voices: [{name, ref_wer, synth_wer?}], threshold: 0.15 }`
  - `trim --json` → `{ voices: [{name, gap_count, changed}] }` — `gap_count` is required; `refine` branches on it without screen-scraping
  - `compare --json` → `{ winner: "faster-whisper"|"parakeet"|null, agreement_wer, whisper_words, parakeet_words, skipped: [] }` — `winner` is the **faster** model by elapsed wall-clock (matching the script's on-screen Verdict), or `null` when only one model ran. The script has **no ground-truth reference transcript**, so it cannot produce per-model accuracy (`faster_whisper_wer`/`parakeet_wer`); `agreement_wer` is the inter-model WER (whisper-output vs parakeet-output, `null` unless both ran). `whisper_words`/`parakeet_words` are raw word counts; `skipped` lists models that did not run (e.g. `--skip-parakeet`). `refine` runs this only for its exit code and does not parse the body.
  - `audit-archive.py` already has `--json` — no change
  - `transcribe.py` already outputs JSON by default — no `--json` flag needed
- **Exit codes:** 0 = success/clean; 1 = warnings (WER above threshold, gaps found); 2 = hard error (missing dep, file not found).
- **Argparse help strings:** updated to match the CLI-style descriptions above.

Scripts are not restructured — only surface-level output and argument changes.

---

## 6. Internal Script Cleanup

The following are moved to `scripts/internal/` (not exposed via CLI, no user-facing value):

| Script | Reason |
|--------|--------|
| `reclone-flagship.py` | Maintainer-specific voice curation |
| `gen-comparison-audio.sh` | Website demo audio generation |
| `loudnorm-demo-audio.sh` | Website demo audio normalisation |
| `clone-red-dwarf.sh` | One-off batch clone for the Red Dwarf gallery |
| `check-og-metadata.py` | CI guard for og:description voice count |
| `fb-reindex.sh` | Internal indexing tool |
| `transcribe-youtube-batch.sh` | Bulk transcription — maintainer workflow |
| `qa-transcripts.py` | NotebookLM transcript QA against source content — unrelated to voice cloning |
| `review-content.py` | Gemini-powered blog post reviewer — unrelated to voice cloning |

**Not moved — `chunk-text.py`:** has an existing test (`tests/test_chunk_text.py`). Moving it without updating the test import path would break CI. Leave it in `scripts/` and do not expose it via CLI.

These remain in place (hook dependencies or user utilities):

| Script | Reason |
|--------|--------|
| `strip-markdown.py` | Required by `tts-hook.sh` at runtime |
| `afterwords-post-llm.sh` | Hermes integration hook |
| `afterwords-tts-command.sh` | Hermes command provider |
| `hermes-tts.sh` | Hermes shell hook |
| `tts-feed-send.py` | Messaging delivery (opt-in egress) |

---

## 7. Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `afterwords transcribe`, `qa`, `trim`, `compare`, `refine`, `update` all present in `afterwords help` under the Analysis / Setup sections |
| 2 | `afterwords --ai` prints the full ai-guide.md without error |
| 3 | `afterwords clone /path/to/local.wav myvoice` completes without calling yt-dlp |
| 4 | `afterwords clone <url> myvoice` runs `refine` at the end by default |
| 5 | `afterwords clone <url> myvoice --quick` runs `refine --quick` (qa + re-audit, no compare/trim) |
| 6 | `afterwords refine <voice>` runs all 4 steps, skips trim prompt when no gap found |
| 7 | `afterwords update --check` reports commits without modifying anything |
| 8 | `afterwords update` on a dirty working tree warns before pulling |
| 9 | `afterwords audit --archive` uses `scripts/audit-archive.py`; plain `audit` unchanged |
| 10 | All analysis scripts exit 0/1/2 per spec; `--json` flag present on qa, trim, compare |
| 11 | `scripts/internal/` exists and contains the 9 moved scripts (chunk-text.py stays in place) |
| 12 | `pytest` passes (435+ tests) with no regressions |

---

## 8. Implementation Order

Suggested sequence (each step independently testable):

1. Script cleanup (`scripts/internal/`)
2. Thin wrappers: `transcribe`, `qa`, `trim`, `compare`
3. `audit --archive` extension
4. `clone` local-file support
5. `refine` command
6. `clone` auto-refine integration
7. `update` command
8. `--ai` flag + `docs/ai-guide.md`
9. Help redesign
10. Script polish (`--json`, exit codes, TTY markers)
11. `pytest` + acceptance criteria check
