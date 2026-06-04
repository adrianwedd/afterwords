# Afterwords CLI Expansion — Design Spec
**Date:** 2026-06-04  
**Sprint:** 6 (implementation)  
**Status:** Draft — pending CLI agent QA

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
```

Key passthrough flags: `--skip-parakeet`, `--model NAME`.

### 1.5 `afterwords audit` (extended)

The existing `afterwords audit` wraps `scripts/audit-voice-transcripts.py` (voice profile drift). A new `--archive` flag switches to `scripts/audit-archive.py` (TTS archive pair auditing).

```
afterwords audit                     # voice profile drift (existing behaviour)
afterwords audit --voice picard      # single voice
afterwords audit --archive           # audit TTS archive .mp3/.txt pairs
afterwords audit --archive --voice picard
```

The `--archive` flag is detected in `cmd_audit()` before passthrough; the remaining flags are forwarded to whichever script is selected.

**Rationale for extending `audit` rather than a new `audit-archive` command:** keeps the surface area flat and groups related auditing concerns under one verb.

### 1.6 `afterwords refine <voice> [--quick]`

Chains the four analysis tools in sequence for a single named voice. This is the recommended post-clone verification step and is also called automatically by `clone` (unless `--quick` is passed there).

```
afterwords refine gandalf
afterwords refine gandalf --quick    # skip compare and trim steps
```

**Step sequence:**

```
Step 1/4  qa --voice <name> --ref-only
          → if WER > 15% warn but continue (user may want to see full picture)

Step 2/4  compare voices/<name>-ref.wav
          → print winner; if parakeet wins, note it but do not change the profile
            (backend selection is a separate decision requiring reclone)

Step 3/4  trim --voice <name>  (dry run first, then prompt)
          → if no silence gap detected: skip prompt, print "✓ no silence gaps"
          → if gap detected: show details, ask "Trim and rewrite reference? [Y/n]"
          → on Y: re-run trim --apply --voice <name>

Step 4/4  audit --voice <name>
          → final WER after any trim; print summary line
```

`--quick` skips steps 2 and 3 entirely (compare + trim). Useful when the reference is already known-good.

**Exit codes:** 0 = all steps clean or warnings only; 1 = WER > 15% after step 4; 2 = script error in any step.

### 1.7 `afterwords update [--check]`

Self-update: pull latest commits, reinstall packages, reload voices.

```
afterwords update           # pull + install + reload
afterwords update --check   # print available commits, exit without changing anything
```

**Sequence:**

1. Verify the repo is a git working tree (`git rev-parse --git-dir`). If not (e.g. tarball install), print a clear message and exit 1.
2. `git fetch origin`
3. Report N commits available (`--check` exits here).
4. `git pull --ff-only` — fast-forward only; if diverged, print instructions to merge manually and exit 1.
5. `pip install --quiet -r requirements.txt`
6. If `requirements-clone.txt` exists in the repo, `pip install --quiet -r requirements-clone.txt`.
7. If the server is running, `afterwords reload` and report voices added/removed.
8. Print a summary: version before → after, files changed, voices delta.

**User voice safety:** `git pull` only touches tracked files. Untracked user-cloned voices in `voices/` are never affected.

**Dirty working tree:** if `git status --porcelain` shows modifications, warn and ask confirmation before pulling. Do not pull silently over local changes.

---

## 2. `clone` Improvements

### 2.1 Local audio file support

If the first positional argument to `afterwords clone` (or `clone-voice.sh`) is an existing file path, skip `yt-dlp` and use it as the audio source directly.

**Detection:** `[ -f "$1" ]` checked before the yt-dlp block. Accepts any format `ffprobe` can read (WAV, MP3, M4A, FLAC, etc.).

**Profile JSON:** `source_url` is set to `"file://$(realpath "$1")"` so the provenance is recorded even though the file may not be portable.

**Interactive flow:** unchanged — user is still asked for start time and voice name unless provided as positional args.

### 2.2 Auto-refine after clone

After a successful clone, `clone` runs `afterwords refine <name>` automatically.

`--quick` on the `clone` command passes `--quick` to `refine` (skips compare + trim). When `--quick` is used, the completion message reads:

> *"Run `afterwords refine <name>` to verify reference quality when you're ready."*

This makes `--quick` meaningful: it's not "skip QA forever", it's "I'll do QA separately".

**Non-interactive / `--yes` mode:** auto-refine runs but skips the trim prompt (treats it as "n"). Rationale: fully non-interactive callers (scripts, agents) should not block on a TTY prompt; trim must be an explicit follow-up.

---

## 3. `afterwords --ai` Flag

`afterwords --ai` prints `docs/ai-guide.md` to stdout. The guide is a standalone Markdown document maintained separately from the shell script so it can be updated without touching `afterwords.sh`, and agents can also `cat` it directly from the repo.

**Flag handling:** detected before the main `COMMAND` dispatch so it works as `afterwords --ai` (not a subcommand). If a pager (`less`, `bat`) is available and stdout is a TTY, pipe through it; otherwise raw stdout.

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
- **`--json` flag:** all scripts that don't already have it get a `--json` flag that suppresses human output and prints a single JSON object to stdout. Enables agent parsing without screen-scraping.
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
| `fb-reindex.sh` | Unknown/internal indexing tool |
| `transcribe-youtube-batch.sh` | Bulk transcription — maintainer workflow |
| `chunk-text.py` | Internal text-chunking utility |
| `qa-transcripts.py` | NotebookLM transcript QA against source content — unrelated to voice cloning |

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
| 5 | `afterwords clone <url> myvoice --quick` skips refine and prints the follow-up hint |
| 6 | `afterwords refine <voice>` runs all 4 steps, skips trim prompt when no gap found |
| 7 | `afterwords update --check` reports commits without modifying anything |
| 8 | `afterwords update` on a dirty working tree warns before pulling |
| 9 | `afterwords audit --archive` uses `scripts/audit-archive.py`; plain `audit` unchanged |
| 10 | All analysis scripts exit 0/1/2 per spec; `--json` flag present on qa, trim, compare |
| 11 | `scripts/internal/` exists and contains the 8 moved scripts |
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
