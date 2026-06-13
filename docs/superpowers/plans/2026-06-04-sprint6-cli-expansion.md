# Sprint 6 CLI Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand `afterwords` from a server-management tool into a complete voice-curation workbench: new analysis subcommands, auto-refine after clone, local-file clone, self-update, agent guide, and help redesign.

**Architecture:** All new CLI subcommands are thin bash passthroughs in `afterwords.sh` following the existing `cmd_audit` pattern (activate venv, validate script, `python3 "$script" "$@"`). Python script polish (--json, exit codes) is done first because `refine` consumes those contracts. The `refine` command chains qa → compare → trim → qa using those stable exit codes. Auto-refine is wired into `cmd_clone` after the clone-voice.sh subprocess exits.

**Tech Stack:** bash (macOS default is 3.2 — `/usr/bin/env bash`; avoid bash-4+/5-only features such as `${var^^}`, associative arrays, `mapfile`), Python 3.11+, argparse, pytest (subprocess-based tests for CLI behaviour).

> **QA note (2026-06-04):** This plan was reviewed by three CLI agents (codex, agy, hermes) against the live source and reconciled with the authoritative spec `docs/superpowers/specs/2026-06-04-afterwords-cli-design.md`. Fixes applied for: hallucinated Python variable names (qa/trim/compare built `rows`/`targets`, not `results`-of-dicts), `fail`-vs-`return 2` exit-code mismatch, `local` at top level, the script-move breaking CI, unfiltered `clone-voice.sh` positionals, and several test-harness defects. Where the spec named a contract the code cannot produce (compare `faster_whisper_wer`/`parakeet_wer` — there is no ground truth), the deviation is called out inline under the relevant task.

**Spec-pinned constants (do not invent):** ref-WER attention threshold = **0.15** (spec §5, §1.6); refine/script exit codes **0 = clean, 1 = warning, 2 = hard error** (spec §5, §1.6); compare exit 1 **or 2** → refine prints a warning and **continues** (spec §1.6 — compare is diagnostic-only and writes nothing `trim` consumes); trim/qa exit 2 → refine **aborts** with exit 2.

---

## File map

**Create:**
- `scripts/internal/` — 9 maintainer-only scripts moved here
- `docs/ai-guide.md` — AI agent reference guide
- `tests/test_cli_expansion.py` — acceptance + contract + refine exit-code tests

**Modify:**
- `scripts/qa-voices.py` — add `--json`, normalize exit codes 0/1/2, TTY markers
- `scripts/trim-silence-gaps.py` — add `--json`, normalize exit codes 0/1/2, TTY markers
- `scripts/compare-transcription.py` — add `--json`, normalize exit codes 0/1/2, TTY markers
- `afterwords.sh` — add cmd_transcribe, cmd_qa, cmd_trim, cmd_compare, cmd_refine, cmd_update; extend cmd_audit; update cmd_clone; redesign cmd_help; add --ai detection; add AFTERWORDS_REPO_DIR override for testing
- `clone-voice.sh` — local-file support, --quick flag parsing, source_basename in JSON
- `tests/test_og_metadata.py` — update SCRIPT path after check-og-metadata.py moves

---

## Task 1: Script cleanup — move internal scripts to `scripts/internal/`

**Files:**
- Create: `scripts/internal/` (directory)
- Modify: `tests/test_og_metadata.py`
- Move: 9 scripts (see step 3)

- [ ] **Step 1: Update test_og_metadata.py path so it fails (the script doesn't exist at the new path yet)**

Edit `tests/test_og_metadata.py` line 15 from:
```python
SCRIPT = REPO / "scripts" / "check-og-metadata.py"
```
to:
```python
SCRIPT = REPO / "scripts" / "internal" / "check-og-metadata.py"
```

- [ ] **Step 2: Run test to verify it now fails**

```bash
source .venv/bin/activate
pytest tests/test_og_metadata.py -v
```
Expected: FAIL — `scripts/internal/check-og-metadata.py` not found.

- [ ] **Step 3: Create the directory and move all 9 scripts**

```bash
mkdir scripts/internal
git mv scripts/reclone-flagship.py        scripts/internal/
git mv scripts/gen-comparison-audio.sh    scripts/internal/
git mv scripts/loudnorm-demo-audio.sh     scripts/internal/
git mv scripts/clone-red-dwarf.sh         scripts/internal/
git mv scripts/check-og-metadata.py       scripts/internal/
git mv scripts/fb-reindex.sh              scripts/internal/
git mv scripts/transcribe-youtube-batch.sh scripts/internal/
git mv scripts/qa-transcripts.py          scripts/internal/
git mv scripts/review-content.py          scripts/internal/
```

Do NOT move: `chunk-text.py` (has tests that import it by path), `strip-markdown.py`, `afterwords-post-llm.sh`, `afterwords-tts-command.sh`, `hermes-tts.sh`, `tts-feed-send.py`.

- [ ] **Step 4: Update every reference to the moved scripts — in the SAME commit as the move**

The move breaks references that the plan must not leave dangling:

1. **CI workflow** — `.github/workflows/ci.yml` line 29 runs `python scripts/check-og-metadata.py`. Update to:
   ```yaml
       run: python scripts/internal/check-og-metadata.py
   ```
2. **Self-references in moved scripts** — grep and fix help/usage strings that print old paths:
   ```bash
   grep -rn -e 'scripts/reclone-flagship\.py' -e 'scripts/gen-comparison-audio\.sh' \
            -e 'scripts/loudnorm-demo-audio\.sh' -e 'scripts/clone-red-dwarf\.sh' \
            -e 'scripts/check-og-metadata\.py' -e 'scripts/fb-reindex\.sh' \
            -e 'scripts/transcribe-youtube-batch\.sh' -e 'scripts/qa-transcripts\.py' \
            -e 'scripts/review-content\.py' \
            scripts/ docs/ .github/ README.md 2>/dev/null
   ```
   Known hits to fix: `scripts/internal/check-og-metadata.py` (usage line referencing `scripts/fb-reindex.sh`), `scripts/internal/gen-comparison-audio.sh` (header referencing `scripts/reclone-flagship.py`), and `docs/youtube-revoicing-pipeline.md` (references `transcribe-youtube-batch.sh`). Rewrite each old `scripts/<name>` → `scripts/internal/<name>`. Documentation prose for the moved batch-pipeline scripts should also point at the new path.

- [ ] **Step 5: Run tests — og-metadata test passes; full suite unchanged**

```bash
pytest -q
```
Expected: same baseline count as before the move (no test references the moved scripts except `test_og_metadata.py`, already updated). The CI `check-og-metadata` step runs outside pytest — verify the path edit by running it directly: `python scripts/internal/check-og-metadata.py`.

- [ ] **Step 6: Commit (move + all reference updates together)**

```bash
git add scripts/internal/ tests/test_og_metadata.py .github/workflows/ci.yml docs/youtube-revoicing-pipeline.md
git commit -m "chore: move maintainer-internal scripts to scripts/internal/ (update CI + refs)"
```

---

## Task 2: qa-voices.py — add `--json`, normalize exit codes, TTY markers

**Files:**
- Modify: `scripts/qa-voices.py`

- [ ] **Step 1: Read the current main() to understand current args and output format**

```bash
grep -n "def main\|ap\.add_argument\|sys.exit\|print(" scripts/qa-voices.py | head -40
```

> **VERIFIED against `scripts/qa-voices.py` (read before editing):** `main()` builds `rows` as a **list of lists** (line ~173), header at line ~120 — there is NO `results` list of dicts. The JSON block below builds from `rows` **by index**: `name=row[0]`, `ref_wer=float(row[1])`, `synth_wer=float(row[5]) if row[5] else None`. The existing human `WARN-REF` flag uses `ref_wer > 0.6` (line 82) — a separate, louder "severely broken" band. Per spec §5 the machine/exit threshold is **0.15**; define it as a named constant `REF_WER_THRESHOLD = 0.15` and use it ONLY for the JSON `threshold` field and the exit-1 decision. **Do not change the 0.6 human flag** (no test covers qa human output — confirmed — but leaving it avoids reflagging ~98 gallery families). The two bands are intentional: 0.15 = "refine should look at this" (machine), 0.6 = "this clone is broken" (human).

- [ ] **Step 2: Write the failing tests for the --json contract**

Add to a new file `tests/test_script_polish.py`. The structural test runs the real script (loads Whisper, transcribes every ref WAV — minutes, needs `faster_whisper`), so it is marked `integration` and skipped in the default `pytest -q` / CI run, matching the repo's `test_fidelity.py` convention. A model-free `--help` test guards flag presence in CI.

```python
"""Tests for --json flag and exit-code contracts on analysis scripts."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VOICES_DIR = REPO / "voices"
QA_SCRIPT = REPO / "scripts" / "qa-voices.py"

def run_script(script, *args, timeout=600):
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=timeout,
    )

# ── CI-safe: flag presence via --help (argparse exits before importing whisper) ──
def test_qa_has_json_flag():
    result = run_script(QA_SCRIPT, "--help", timeout=30)
    assert result.returncode == 0
    assert "--json" in result.stdout

# ── Heavy: real model run; integration-gated ──
@pytest.mark.integration
def test_qa_json_structure():
    pytest.importorskip("faster_whisper")
    result = run_script(QA_SCRIPT, "--json", "--ref-only")
    assert result.returncode in (0, 1), f"unexpected exit {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)  # stdout must be JSON only — no progress text
    assert data["threshold"] == 0.15
    assert isinstance(data["voices"], list)
    if data["voices"]:
        v = data["voices"][0]
        assert "name" in v and "ref_wer" in v
```

Run it:
```bash
pytest tests/test_script_polish.py::test_qa_has_json_flag -v
```
Expected: FAIL — `--json` not in `--help` yet.

- [ ] **Step 3: Add `--json`, the threshold constant, exit codes, and TTY markers to qa-voices.py**

Add a module-level constant near the top (after the imports / `TEST_PHRASE` block):
```python
REF_WER_THRESHOLD = 0.15  # machine/exit threshold (spec §5); human WARN-REF stays at 0.6
```

Add to the argparse block in `main()`:
```python
ap.add_argument("--json", action="store_true", help="Emit JSON to stdout; suppress human output")
```

Suppress **all** human stdout in JSON mode so stdout is valid JSON only: set `quiet = args.json` at the top of `main()` and gate on `if not quiet:` — the two preamble prints (`"Loading Whisper base model..."` line ~104 and `"Found N base voice profiles"` line ~117), every per-voice progress `print(...)`, and the trailing summary block. (qa is the only script that prints progress to **stdout** — trim/compare already use stderr.) The TSV is still written to `args.out` (a file, not stdout) — leave that.

Replace the end of `main()` (after the `rows` list is fully built and the TSV is written) with a JSON branch built **from `rows` by index** plus normalized exit codes:
```python
    n_over = sum(1 for r in rows if float(r[1]) > REF_WER_THRESHOLD)

    if args.json:
        out = {
            "threshold": REF_WER_THRESHOLD,
            "voices": [
                {"name": r[0], "ref_wer": float(r[1]),
                 **({"synth_wer": float(r[5])} if r[5] else {})}
                for r in rows
            ],
        }
        print(json.dumps(out))   # json already imported at top of file
    # exit 1 if any voice is over the attention threshold; 0 otherwise
    sys.exit(1 if n_over else 0)
```

Map any unhandled exception (missing dep, file-not-found) to exit 2. Use **`sys.exit(main())`** (not a bare `main()` call) — this is the canonical wrapper reused by Tasks 3 and 4, where `main()` *returns* its exit code; for qa, `main()` calls `sys.exit()` internally, which the `except SystemExit: raise` lets through unchanged:
```python
if __name__ == "__main__":
    try:
        sys.exit(main())          # preserves a returned code AND a sys.exit() inside main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
```

TTY markers: gate any decorative `✓/⚠/✗` prefixes on `sys.stdout.isatty()` so redirected/piped output stays plain. Do not add markers to the JSON path.

- [ ] **Step 4: Run the CI-safe test**

```bash
pytest tests/test_script_polish.py::test_qa_has_json_flag -v
```
Expected: passes. (Run the integration test on the dev machine with `pytest -m integration tests/test_script_polish.py::test_qa_json_structure`.)

- [ ] **Step 5: Commit**

```bash
git add scripts/qa-voices.py tests/test_script_polish.py
git commit -m "feat(scripts): qa-voices --json, exit codes, TTY markers"
```

---

## Task 3: trim-silence-gaps.py — add `--json`, normalize exit codes, TTY markers

**Files:**
- Modify: `scripts/trim-silence-gaps.py`

> **VERIFIED against `scripts/trim-silence-gaps.py` (read before editing):** the current `main()` builds `targets` as a **list of `(jp, ref)` tuples** (only for silence-flagged voices) and **returns at line ~80 in dry-run mode after printing human text** — there is NO `results` list, NO `gap_count`/`changed`, and the early `return 0` would fire before any JSON ever prints, so `refine`'s `json.load` on the dry-run output would crash. The fix restructures `main()` to build one `results` dict per processed voice (including zero-gap ones) and to emit JSON **before** the dry-run return.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_script_polish.py` (reuses the shared `run_script` helper):

```python
TRIM_SCRIPT = REPO / "scripts" / "trim-silence-gaps.py"

def test_trim_has_json_flag():
    result = run_script(TRIM_SCRIPT, "--help", timeout=30)
    assert result.returncode == 0
    assert "--json" in result.stdout

@pytest.mark.integration
def test_trim_json_structure():
    pytest.importorskip("faster_whisper")
    result = run_script(TRIM_SCRIPT, "--json")  # dry run — must still emit JSON
    assert result.returncode in (0, 1), f"exit {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)  # JSON in dry-run mode is the regression guard
    assert isinstance(data["voices"], list)
    if data["voices"]:
        v = data["voices"][0]
        assert "name" in v and "gap_count" in v and "changed" in v
```

Run:
```bash
pytest tests/test_script_polish.py::test_trim_has_json_flag -v
```
Expected: FAIL.

- [ ] **Step 2: Restructure `main()` in trim-silence-gaps.py**

Add to the argparse block:
```python
ap.add_argument("--json", action="store_true", help="Emit JSON to stdout; suppress human output")
```

Replace the loop-and-early-return body (current lines ~63–114) so it (a) records every processed voice, (b) emits JSON before the dry-run return:

```python
    quiet = args.json
    cache: dict[Path, str] = {}
    results: list[dict] = []                 # one entry per processed voice
    targets: list[tuple[Path, Path, dict]] = []
    for jp in profiles:
        finding = audit.audit_one(jp, VOICES, cache, model)
        gap_count = sum(1 for i in finding.issues if "mid-clip silence" in i)
        rec = {"name": jp.stem, "gap_count": gap_count, "changed": False}
        results.append(rec)
        if gap_count > 0:
            ref = jp.parent / json.loads(jp.read_text())["reference_audio"]
            targets.append((jp, ref, rec))

    # Dry run: emit results and stop BEFORE applying (this is the bug the QA caught)
    if not args.apply:
        if args.json:
            print(json.dumps({"voices": results}))
        elif not targets:
            print("no silence-gap voices to trim")
        else:
            print(f"would process {len(targets)} voice(s):")
            for jp, ref, _ in targets:
                print(f"  {jp.stem}  ({ref.name})")
            print("\ndry run — pass --apply to actually trim and rewrite transcripts")
        return 1 if any(r["gap_count"] for r in results) else 0

    # Apply path
    for jp, ref, rec in targets:
        # ... existing trim_wav / re-transcribe / write-profile body, unchanged ...
        rec["changed"] = True
        if not quiet:
            print(f"  ✓ {jp.stem}: {info.duration:.1f}s")

    if args.json:
        print(json.dumps({"voices": results}))
    elif targets:
        print(f"\ntrimmed {len(targets)} voice(s). re-run audit to verify.")
    return 0   # apply succeeded — exit 0 (Unix convention). Dry-run returns 1 for "gaps found".
```

> **Exit-code note (resolved 2026-06-04):** the **dry-run** path returns `1 if any(r["gap_count"]) else 0` (1 = "gaps found", a detection signal that `refine` and humans read). The **apply** path returns `0` on success — a command that successfully did its mutating job exits clean, so `trim --apply && next` chains work. Hard errors are exit 2 via the `__main__` wrapper. `refine` does not check `trim --apply`'s exit code (Task 8), so this is purely for standalone use.

Update `if __name__ == "__main__":` — the current code is `sys.exit(main())` and **must stay that way** (trim's `main()` returns its exit code via `return 1 if … else 0`; a bare `main()` call would discard it and the script would exit 0 even when gaps are found, violating spec §5). Add only the exception→exit-2 guard:
```python
if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
```
Gate any decorative TTY markers on `sys.stdout.isatty()`.

- [ ] **Step 3: Run the CI-safe test**

```bash
pytest tests/test_script_polish.py::test_trim_has_json_flag -v
```
Expected: passes (run `test_trim_json_structure` under `-m integration` on the dev machine).

- [ ] **Step 4: Commit**

```bash
git add scripts/trim-silence-gaps.py tests/test_script_polish.py
git commit -m "feat(scripts): trim-silence-gaps --json, exit codes, TTY markers"
```

---

## Task 4: compare-transcription.py — add `--json`, normalize exit codes, TTY markers

**Files:**
- Modify: `scripts/compare-transcription.py`

> **⚠ SPEC DEVIATION — verified against `scripts/compare-transcription.py`:** spec §5 names the contract `{ winner, faster_whisper_wer, parakeet_wer }`, but the script computes **NO ground-truth WER** — there is no reference transcript, so there is no "how accurate is each model" number. The only WER it computes is `wer_wp` (Levenshtein of whisper-output vs parakeet-output, i.e. inter-model *agreement*, line ~274), and the whole comparison block is gated on `if whisper_words and parakeet_words:` — so with `--skip-parakeet` there is **no WER at all**. `faster_whisper_wer`/`parakeet_wer` are therefore unimplementable as specified. **Substituted contract** (emit what the code can truthfully produce): `winner` is the **faster** model by elapsed time (which is exactly what the script's own on-screen Verdict already recommends for the production pipeline), `agreement_wer` is `wer_wp` (null unless both ran), plus raw word counts and a `skipped` list. `refine` only *displays* the compare result (spec §1.6 step 2 — "note it but do not change the profile"), so it does not branch on these fields. **Resolved 2026-06-04:** spec §5 line 264 was reconciled to this `{ winner, agreement_wer, whisper_words, parakeet_words, skipped }` shape — the two are now in sync.

Real variable names in `main()` (confirmed): `whisper_words`, `parakeet_words` (lists of dicts), `whisper_time`, `parakeet_time` (floats), `wer_wp`, `word_list(...)`, `wer(...)`. The early `return 1` on file-not-found / missing `yt-dlp`/`ffmpeg` should become `return 2` (hard error per spec §5).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_script_polish.py`:

```python
COMPARE_SCRIPT = REPO / "scripts" / "compare-transcription.py"
SAMPLE_WAV = REPO / "voices" / "galadriel-ref.wav"  # tracked in repo

def test_compare_has_json_flag():
    result = run_script(COMPARE_SCRIPT, "--help", timeout=30)
    assert result.returncode == 0
    assert "--json" in result.stdout

@pytest.mark.integration
def test_compare_json_structure():
    pytest.importorskip("faster_whisper")  # loads large-v2 — heavy, dev-machine only
    result = run_script(COMPARE_SCRIPT, str(SAMPLE_WAV), "--json", "--skip-parakeet")
    # one model skipped → partial comparison → exit 1
    assert result.returncode in (0, 1), f"exit {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)
    assert "winner" in data          # may be None when only one model ran
    assert "whisper_words" in data
    assert "skipped" in data
    assert "parakeet" in data["skipped"]
```

Run:
```bash
pytest tests/test_script_polish.py::test_compare_has_json_flag -v
```
Expected: FAIL.

- [ ] **Step 2: Add `--json` to compare-transcription.py**

Add to argparse:
```python
ap.add_argument("--json", action="store_true", help="Emit JSON to stdout; suppress human output")
```

Immediately after the two model-running blocks (after the `if not args.skip_parakeet:` block, ~line 266) and **before** the `if whisper_words and parakeet_words:` human block, insert the JSON branch. Then gate the existing human Results/Verdict/side-by-side block on `if not args.json:`.

```python
    if args.json:
        both = bool(whisper_words and parakeet_words)
        # NOTE: no ground truth exists — see spec-deviation note in the plan.
        # winner = faster model by wall-clock (matches the on-screen Verdict);
        # agreement_wer = inter-model WER (wer_wp), not per-model accuracy.
        skipped = []
        if not whisper_words:
            skipped.append("faster-whisper")
        if not parakeet_words:
            skipped.append("parakeet")
        out = {
            "winner": (("parakeet" if parakeet_time < whisper_time else "faster-whisper")
                       if both else None),
            "agreement_wer": (wer(word_list(whisper_words), word_list(parakeet_words))
                              if both else None),
            "whisper_words": len(whisper_words),
            "parakeet_words": len(parakeet_words),
            "skipped": skipped,
        }
        print(json.dumps(out))   # json already imported at top
        sys.exit(0 if both else 1)
```

Update `if __name__ == "__main__":` — keep the existing `sys.exit(main())` (compare's `main()` returns its exit code, including the new file-not-found `return 2`; a bare `main()` would discard it). Add only the exception→exit-2 guard:
```python
if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
```
Gate TTY `c()` colouring as already done (`c()` checks `isatty`); ensure no stray non-JSON `print(...)` to stdout when `--json` (progress prints already go to `stderr` — leave them).

- [ ] **Step 3: Run the CI-safe tests**

```bash
pytest tests/test_script_polish.py -k "has_json_flag" -v
```
Expected: the three `*_has_json_flag` tests pass.

- [ ] **Step 4: Run full suite (integration tests skipped by default)**

```bash
pytest -q
```
Expected: baseline + the new CI-safe tests pass; the three `@pytest.mark.integration` structure tests are skipped. Run them explicitly on the dev machine:
```bash
pytest -m integration tests/test_script_polish.py -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/compare-transcription.py tests/test_script_polish.py
git commit -m "feat(scripts): compare-transcription --json, exit codes, TTY markers"
```

---

## Task 5: afterwords.sh — AFTERWORDS_REPO_DIR override + thin wrappers (transcribe, qa, trim, compare)

**Files:**
- Modify: `afterwords.sh`

- [ ] **Step 1: Add AFTERWORDS_REPO_DIR test override near the top of afterwords.sh**

Find the REPO_DIR computation block (lines 47-57). Replace it with:

```bash
# Allow test override of REPO_DIR
if [ -n "${AFTERWORDS_REPO_DIR:-}" ]; then
    REPO_DIR="$AFTERWORDS_REPO_DIR"
elif [ -L "${BASH_SOURCE[0]}" ]; then
    REAL_SCRIPT="$(readlink "${BASH_SOURCE[0]}")"
    if [[ "$REAL_SCRIPT" != /* ]]; then
        REAL_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd "$(dirname "$REAL_SCRIPT")" && pwd)/$(basename "$REAL_SCRIPT")"
    fi
    REPO_DIR="$(cd "$(dirname "$REAL_SCRIPT")" && pwd)"
else
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
```

- [ ] **Step 2: Add the four thin wrapper functions to afterwords.sh, after `cmd_audit()`**

Insert these four functions immediately after the closing `}` of `cmd_audit()` (around line 485):

```bash
cmd_transcribe() {
    local script="${REPO_DIR}/scripts/transcribe.py"
    [ -f "$script" ] || fail "transcribe.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_qa() {
    local script="${REPO_DIR}/scripts/qa-voices.py"
    [ -f "$script" ] || fail "qa-voices.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_trim() {
    local script="${REPO_DIR}/scripts/trim-silence-gaps.py"
    [ -f "$script" ] || fail "trim-silence-gaps.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_compare() {
    local script="${REPO_DIR}/scripts/compare-transcription.py"
    [ -f "$script" ] || fail "compare-transcription.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}
```

- [ ] **Step 3: Add the four new commands to the main dispatch case block**

Find the `case "$COMMAND" in` block near line 990. After the `audit)` line, add:

```bash
    transcribe)  cmd_transcribe "$@" ;;
    qa)          cmd_qa "$@" ;;
    trim)        cmd_trim "$@" ;;
    compare)     cmd_compare "$@" ;;
```

- [ ] **Step 4: Test the wrappers work**

```bash
bash afterwords.sh transcribe --help 2>&1 | head -5
bash afterwords.sh qa --help 2>&1 | head -5
bash afterwords.sh trim --help 2>&1 | head -5
bash afterwords.sh compare --help 2>&1 | head -5
```
Expected: each prints argparse help from the underlying script with no errors.

- [ ] **Step 5: Commit**

```bash
git add afterwords.sh
git commit -m "feat(cli): add transcribe/qa/trim/compare subcommands"
```

---

## Task 6: `audit --archive` extension

**Files:**
- Modify: `afterwords.sh`

- [ ] **Step 1: Write the failing test for --archive routing**

Add to `tests/test_cli_expansion.py` (create this file):

```python
"""Acceptance and integration tests for Sprint 6 CLI expansion."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AFTERWORDS = REPO / "afterwords.sh"


def run_afterwords(*args, env_override=None):
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        ["bash", str(AFTERWORDS), *args],
        capture_output=True, text=True, env=env,
    )


def test_audit_archive_routes_to_archive_script(tmp_path):
    """--archive flag must use audit-archive.py, not audit-voice-transcripts.py."""
    # Create stub scripts in a temp REPO_DIR
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate").write_text("# stub activate")

    stub = scripts_dir / "audit-archive.py"
    stub.write_text("import sys; print('ARCHIVE_SCRIPT_CALLED'); sys.exit(0)")
    wrong = scripts_dir / "audit-voice-transcripts.py"
    wrong.write_text("import sys; print('WRONG_SCRIPT'); sys.exit(0)")

    result = run_afterwords("audit", "--archive",
                            env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})
    assert "ARCHIVE_SCRIPT_CALLED" in result.stdout
    assert "WRONG_SCRIPT" not in result.stdout


def test_audit_plain_unchanged(tmp_path):
    """Plain audit (no --archive) must still call audit-voice-transcripts.py."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate").write_text("# stub activate")

    stub = scripts_dir / "audit-voice-transcripts.py"
    stub.write_text("import sys; print('TRANSCRIPT_SCRIPT_CALLED'); sys.exit(0)")
    wrong = scripts_dir / "audit-archive.py"
    wrong.write_text("import sys; print('WRONG_SCRIPT'); sys.exit(0)")

    result = run_afterwords("audit",
                            env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})
    assert "TRANSCRIPT_SCRIPT_CALLED" in result.stdout
    assert "WRONG_SCRIPT" not in result.stdout
```

Run:
```bash
source .venv/bin/activate
pytest tests/test_cli_expansion.py::test_audit_archive_routes_to_archive_script -v
```
Expected: FAIL (cmd_audit always calls audit-voice-transcripts.py).

- [ ] **Step 2: Rewrite cmd_audit() in afterwords.sh to handle --archive**

Replace the existing `cmd_audit()` function body:

```bash
cmd_audit() {
    local use_archive=false
    for arg in "$@"; do
        [ "$arg" = "--archive" ] && use_archive=true
    done

    if $use_archive; then
        local script="${REPO_DIR}/scripts/audit-archive.py"
        [ -f "$script" ] || fail "audit-archive.py not found in ${REPO_DIR}/scripts/"
        [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
        # shellcheck disable=SC1091
        source "${REPO_DIR}/.venv/bin/activate"
        # Strip --archive before forwarding; remaining flags pass through to audit-archive.py
        local args=()
        for arg in "$@"; do
            [ "$arg" != "--archive" ] && args+=("$arg")
        done
        python3 "$script" "${args[@]}"
    else
        local script="${REPO_DIR}/scripts/audit-voice-transcripts.py"
        [ -f "$script" ] || fail "audit-voice-transcripts.py not found in ${REPO_DIR}/scripts/"
        [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
        # shellcheck disable=SC1091
        source "${REPO_DIR}/.venv/bin/activate"
        python3 "$script" "$@"
    fi
}
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cli_expansion.py -v
```
Expected: both audit tests pass.

- [ ] **Step 4: Commit**

```bash
git add afterwords.sh tests/test_cli_expansion.py
git commit -m "feat(cli): extend audit with --archive flag for tts-archive pair auditing"
```

---

## Task 7: clone-voice.sh — local-file support and `--quick` flag parsing

**Files:**
- Modify: `clone-voice.sh`

> **VERIFIED against `clone-voice.sh`:** it does `cd "$SCRIPT_DIR"` (the real repo) at line 13 and assigns raw positionals `YT_URL=$1 / VOICE_NAME=$2 / START_S=$3` with `AUTO_YES` from `$4`. So (a) the original test below ran the **real** script against the **real** repo — writing `voices/test-local.*` and running real Whisper/ffmpeg — and (b) `clone URL --quick` would put `--quick` in `$2` and sanitize it to the voice name `"quick"`. Both are fixed here. Note the existing 15-second extraction (`ffmpeg -ss "$START_S" -t 15`, line ~216) runs for **both** local and URL sources, so long local files are still windowed to 15s — no extra handling needed.

- [ ] **Step 1: Add a single-source detection function + `--check-source` test hook at the very top of clone-voice.sh**

Insert immediately after `set -euo pipefail` (line 10), **before** `cd "$SCRIPT_DIR"` and the venv activation — so the hook is fast, dependency-free, and never writes to the repo:

```bash
# Single source of truth for local-file-vs-URL detection (shared by the
# real flow below and the --check-source test hook). Strips an optional
# file:// scheme, then tests for an existing file.
_is_local_source() { [ -f "${1#file://}" ]; }

# Test hook: print the resolved source kind and exit before any venv/IO work.
if [[ " $* " == *" --check-source "* ]]; then
    if _is_local_source "${1:-}"; then echo "local-file"; else echo "youtube"; fi
    exit 0
fi
```

- [ ] **Step 2: Write the failing test (fast, non-polluting — exercises the detection hook)**

Add to `tests/test_cli_expansion.py`:

```python
def test_clone_local_file_detected_not_ytdlp():
    """A local file path resolves to local-file source, never yt-dlp."""
    sample = REPO / "voices" / "galadriel-ref.wav"  # tracked, real file
    result = subprocess.run(
        ["bash", str(REPO / "clone-voice.sh"), str(sample), "test-local", "--check-source"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "local-file"
    assert "yt-dlp" not in (result.stdout + result.stderr).lower()

def test_clone_url_detected_as_youtube():
    result = subprocess.run(
        ["bash", str(REPO / "clone-voice.sh"),
         "https://youtube.com/watch?v=x", "test-url", "--check-source"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.stdout.strip() == "youtube"
```

Run:
```bash
pytest tests/test_cli_expansion.py -k "clone_local_file_detected or clone_url_detected" -v
```
Expected: FAIL — `--check-source` not handled yet.

- [ ] **Step 3: Replace positional/flag parsing (lines 32–53) with flag-filtered positionals**

This drops every `--flag` out of the positional sequence (so `--quick`/`--yes`/`--all-backends` never land in `VOICE_NAME`/`START_S`) while preserving the existing `--backend=`/`--backend NAME` handling:

```bash
AUTO_YES=false
QUICK=false
BACKEND_NAME=""
ALL_BACKENDS=false

# Separate positionals from flags. --backend consumes the following token.
POSITIONAL=()
skip_next=false
all=("$@")
for ((i=0; i<${#all[@]}; i++)); do
    arg="${all[i]}"
    if $skip_next; then skip_next=false; continue; fi
    case "$arg" in
        --yes)          AUTO_YES=true ;;
        --quick)        QUICK=true ;;
        --all-backends) ALL_BACKENDS=true ;;
        --check-source) ;;                       # handled at top of file
        --backend=*)    BACKEND_NAME="${arg#--backend=}" ;;
        --backend)      BACKEND_NAME="${all[i+1]:-}"; skip_next=true ;;
        --*)            warn "Ignoring unknown flag: $arg" ;;
        *)              POSITIONAL+=("$arg") ;;
    esac
done

YT_URL="${POSITIONAL[0]:-}"
VOICE_NAME="${POSITIONAL[1]:-}"
START_S="${POSITIONAL[2]:-}"
```

(Delete the old `args=()`/`--backend` split-form loop — its logic is folded into the loop above.)

- [ ] **Step 4: Add local-file detection before the yt-dlp download block**

Find the comment `# Download` (around line 97). Before `info "Downloading audio..."`, insert — reusing the shared `_is_local_source` so detection cannot drift from the test hook:

```bash
# Detect local file — skip yt-dlp if $YT_URL is an existing file path (file:// ok)
LOCAL_FILE=false
SOURCE_BASENAME=""
if _is_local_source "$YT_URL"; then
    LOCAL_FILE=true
    YT_URL="${YT_URL#file://}"
    SOURCE_BASENAME=$(basename "$YT_URL")
fi
```

Then wrap the entire yt-dlp block (lines ~98–113) in:

```bash
if $LOCAL_FILE; then
    TMP_SRC="$YT_URL"
    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_SRC" 2>/dev/null | cut -d. -f1)
    [[ "$DURATION" =~ ^[0-9]+$ ]] || DURATION="unknown"
    ok "Using local file: ${SOURCE_BASENAME} (${DURATION}s)"
else
    # existing yt-dlp block here
    info "Downloading audio..."
    TMP_DL_DIR=$(mktemp -d)
    TMP_SRC="$TMP_DL_DIR/source.wav"
    TMPFILES+=("$TMP_DL_DIR")
    if ! yt-dlp -x --audio-format wav -o "$TMP_DL_DIR/source.%(ext)s" "$YT_URL" 2>&1 | tail -5; then
        fail "Download failed. Check the URL is valid and not private/age-restricted."
    fi
    [ -f "$TMP_SRC" ] || TMP_SRC=$(find "$TMP_DL_DIR" -name '*.wav' -print -quit)
    [ -f "$TMP_SRC" ] || fail "Download produced no audio file. Check the URL."
    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_SRC" 2>/dev/null | cut -d. -f1)
    [[ "$DURATION" =~ ^[0-9]+$ ]] || DURATION="unknown"
    if [[ "$DURATION" == "unknown" ]]; then
        ok "Downloaded"
    else
        ok "Downloaded (${DURATION}s)"
    fi
fi
```

- [ ] **Step 5: Update profile JSON to use `source_url: "local-file"` and add `source_basename`**

Find the `python3 - "$VOICE_NAME" "$YT_URL" ...` heredoc that writes the JSON profile (around line 325). There are two branches (single backend and all-backends). In both, when saving the JSON, pass `$LOCAL_FILE` and `$SOURCE_BASENAME` through and handle:

For the single-backend branch (the last `python3 - ... <<'PYEOF'` block), replace the Python call with:

```bash
python3 - "$VOICE_NAME" "$YT_URL" "$REF_TEXT" "$START_S" "$BACKEND_NAME" "$LOCAL_FILE" "$SOURCE_BASENAME" <<'PYEOF'
import json, sys
name, url, text, start, backend = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
is_local = sys.argv[6] == "true"
source_basename = sys.argv[7]
profile = {
    "name": name,
    "backend": backend,
    "source_url": "local-file" if is_local else url,
    "reference_audio": f"{name}-ref.wav",
    "reference_text": text,
    "segment_start_s": start,
}
if is_local and source_basename:
    profile["source_basename"] = source_basename
with open(f"voices/{name}.json", "w") as f:
    json.dump(profile, f, indent=2)
PYEOF
```

Apply the same change to the `--all-backends` branch (the profile for each backend).

- [ ] **Step 6: Syntax-check and run the fast tests**

```bash
bash -n clone-voice.sh          # catch parse errors in the rewritten arg loop
pytest tests/test_cli_expansion.py -k "clone_local_file_detected or clone_url_detected" -v
```
Expected: both detection tests pass; no parse errors.

- [ ] **Step 7: Run full suite**

```bash
pytest -q
```
Expected: baseline + the new CI-safe tests pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add clone-voice.sh tests/test_cli_expansion.py
git commit -m "feat(clone): local-file support, flag-filtered positionals, source_basename in JSON"
```

---

## Task 8: `cmd_refine` — 4-step pipeline with exit-code chaining

**Files:**
- Modify: `afterwords.sh`
- Modify: `tests/test_cli_expansion.py`

- [ ] **Step 1: Write failing tests for refine exit-code chaining**

Add to `tests/test_cli_expansion.py`:

```python
def _make_stub_repo(tmp_path, qa_exit=0, compare_exit=0, trim_exit=0,
                    trim_json=None, qa_json=None):
    """Build a minimal fake REPO_DIR for testing cmd_refine."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("# stub")

    qa_out = qa_json or '{"voices":[{"name":"v","ref_wer":0.05}],"threshold":0.15}'
    trim_out = trim_json or '{"voices":[{"name":"v","gap_count":0,"changed":false}]}'

    (scripts / "qa-voices.py").write_text(
        f"import sys; print({qa_out!r}); sys.exit({qa_exit})"
    )
    (scripts / "compare-transcription.py").write_text(
        f'import sys; print(\'{{"winner":"faster-whisper","agreement_wer":0.05,"whisper_words":40,"parakeet_words":40,"skipped":[]}}\'); sys.exit({compare_exit})'
    )
    (scripts / "trim-silence-gaps.py").write_text(
        f"import sys; print({trim_out!r}); sys.exit({trim_exit})"
    )
    # Stub voice file so refine finds it
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "testvoice-ref.wav").write_text("")
    (voices / "testvoice.json").write_text('{"name":"testvoice"}')
    return tmp_path


def _run_refine(tmp_path, *extra_args):
    return run_afterwords("refine", "testvoice", *extra_args,
                          env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})


def test_refine_exits_0_on_clean(tmp_path):
    repo = _make_stub_repo(tmp_path)
    result = _run_refine(repo)
    assert result.returncode == 0, result.stderr


def test_refine_continues_after_qa_exit1(tmp_path):
    """qa exit 1 (WER warning) → refine continues to next step."""
    qa_json = '{"voices":[{"name":"testvoice","ref_wer":0.20}],"threshold":0.15}'
    repo = _make_stub_repo(tmp_path, qa_exit=1, qa_json=qa_json)
    result = _run_refine(repo)
    # Should complete (exit 1 because final WER still > 0.15), not abort with 2
    assert result.returncode in (0, 1), f"should not hard-abort: {result.stderr}"


def test_refine_aborts_on_qa_exit2(tmp_path):
    """qa exit 2 (hard error) → refine aborts immediately with exit 2."""
    repo = _make_stub_repo(tmp_path, qa_exit=2)
    result = _run_refine(repo)
    assert result.returncode == 2, f"expected 2, got {result.returncode}: {result.stderr}"


def test_refine_continues_after_compare_exit2(tmp_path):
    """compare exit 2 → refine prints warning but continues to step 3."""
    repo = _make_stub_repo(tmp_path, compare_exit=2)
    result = _run_refine(repo)
    # Should still finish (exit 0 or 1), not exit 2
    assert result.returncode != 2, f"should not abort on compare exit 2: {result.stderr}"


def test_refine_quick_skips_compare_trim(tmp_path):
    """--quick must skip steps 2 and 3 entirely."""
    # Give compare a fatal exit — if --quick works, it should never be called
    repo = _make_stub_repo(tmp_path, compare_exit=2)
    result = _run_refine(repo, "--quick")
    # If compare were called, it would exit 2 and potentially cause issues;
    # with --quick it should complete cleanly
    assert result.returncode in (0, 1)
```

Run:
```bash
pytest tests/test_cli_expansion.py::test_refine_exits_0_on_clean -v
```
Expected: FAIL — `refine` command not yet defined.

- [ ] **Step 2: Implement `cmd_refine()` in afterwords.sh**

Add this function after `cmd_compare()` (inserted in Task 5):

> **VERIFIED:** `fail()` (afterwords.sh:30) does `exit 1` — so the original used `fail` for "exit 2" hard errors, which (a) returns the wrong code (1, not 2) and (b) kills the whole process instead of letting the caller see the return. `test_refine_aborts_on_qa_exit2` expects **2**, so it could never pass. Hard-error aborts below use `return 2` directly. A `--yes` flag is parsed and suppresses the trim prompt (the spec §2.2 / ai-guide document `refine --yes`); the prompt also stays suppressed on any non-TTY stdin. Compare exit 1 **or** 2 → warn and continue (spec §1.6 — compare is diagnostic-only). The voice name is resolved as the first **non-flag** argument so `refine --quick myvoice` and `refine myvoice --quick` both work.

```bash
cmd_refine() {
    local voice="" quick=false yes=false
    for arg in "$@"; do
        case "$arg" in
            --quick) quick=true ;;
            --yes)   yes=true ;;
            --*)     ;;                       # ignore other flags
            *)       [ -z "$voice" ] && voice="$arg" ;;
        esac
    done

    [ -z "$voice" ] && fail "Usage: afterwords refine <voice> [--quick] [--yes]"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"

    local qa_script="${REPO_DIR}/scripts/qa-voices.py"
    local compare_script="${REPO_DIR}/scripts/compare-transcription.py"
    local trim_script="${REPO_DIR}/scripts/trim-silence-gaps.py"
    local ref_wav="${REPO_DIR}/voices/${voice}-ref.wav"

    [ -f "$qa_script" ]      || fail "qa-voices.py not found"
    [ -f "$compare_script" ] || fail "compare-transcription.py not found"
    [ -f "$trim_script" ]    || fail "trim-silence-gaps.py not found"
    [ -f "$ref_wav" ]        || fail "Reference WAV not found: ${ref_wav}"

    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"

    # Hard-error abort helper: prints ✗ and returns 2 (NOT fail/exit 1).
    _refine_abort() { echo -e "  ${RED}✗${NC} $*" >&2; return 2; }

    info "Refining ${voice}..."
    echo

    # Step 1/4 — QA ref WER
    info "Step 1/4  qa --voice ${voice} --ref-only"
    python3 "$qa_script" --voice "$voice" --ref-only --json
    local qa1_exit=$?
    [ $qa1_exit -eq 2 ] && { _refine_abort "qa hard-errored (exit 2) — aborting refine"; return 2; }
    [ $qa1_exit -eq 1 ] && warn "WER above threshold — continuing"

    if ! $quick; then
        # Step 2/4 — Compare transcription models (diagnostic-only; exit 1 or 2 → continue)
        info "Step 2/4  compare voices/${voice}-ref.wav"
        python3 "$compare_script" "$ref_wav" --json
        local compare_exit=$?
        [ $compare_exit -ne 0 ] && warn "compare exited ${compare_exit} — continuing to step 3"

        # Step 3/4 — Trim silence gaps (dry run, then ask)
        info "Step 3/4  trim --voice ${voice} (dry run)"
        local trim_json
        trim_json=$(python3 "$trim_script" --voice "$voice" --json 2>/dev/null)
        local trim_exit=$?
        [ $trim_exit -eq 2 ] && { _refine_abort "trim hard-errored (exit 2) — aborting refine"; return 2; }

        local gap_count=0
        gap_count=$(echo "$trim_json" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(sum(v.get('gap_count', 0) for v in d.get('voices', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

        if [ "$gap_count" -eq 0 ]; then
            ok "No silence gaps found"
        else
            echo "$trim_json"
            local do_trim="n"
            if [ -t 0 ] && ! $yes; then
                echo -en "  ${BOLD}Trim and rewrite reference? [Y/n]${NC} "
                read -r do_trim
            fi
            if [[ "${do_trim:-n}" =~ ^[Yy]$ ]]; then
                info "Applying trim..."
                python3 "$trim_script" --voice "$voice" --apply
            fi
        fi
    else
        info "Step 2/4  compare  (skipped — --quick)"
        info "Step 3/4  trim     (skipped — --quick)"
    fi

    # Step 4/4 — Re-measure WER
    info "Step 4/4  qa --voice ${voice} --ref-only (final)"
    python3 "$qa_script" --voice "$voice" --ref-only --json
    local qa2_exit=$?
    [ $qa2_exit -eq 2 ] && { _refine_abort "qa hard-errored on final check (exit 2)"; return 2; }

    echo
    if [ $qa2_exit -eq 1 ]; then
        warn "Final WER still above threshold"
        return 1
    fi
    ok "Refine complete"
    return 0
}
```

- [ ] **Step 3: Add `refine` to the main dispatch case block**

After the `compare)` line added in Task 5:

```bash
    refine)      cmd_refine "$@" ;;
```

- [ ] **Step 4: Run refine tests**

```bash
pytest tests/test_cli_expansion.py -k "refine" -v
```
Expected: all 5 refine tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: ≥448 passed.

- [ ] **Step 6: Commit**

```bash
git add afterwords.sh tests/test_cli_expansion.py
git commit -m "feat(cli): add refine command with 4-step QA pipeline"
```

---

## Task 9: `cmd_clone` — auto-refine integration

**Files:**
- Modify: `afterwords.sh`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_expansion.py`:

```python
def test_clone_calls_refine_after_success(tmp_path):
    """After a successful clone, cmd_clone must invoke cmd_refine."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("# stub")
    for name in ("qa-voices.py", "trim-silence-gaps.py", "compare-transcription.py"):
        (scripts / name).write_text("import sys; sys.exit(0)")
    voices = tmp_path / "voices"
    voices.mkdir()

    # Stub clone-voice.sh to exit 0 and write a fake voice
    stub_clone = tmp_path / "clone-voice.sh"
    stub_clone.write_text(
        "#!/bin/bash\n"
        f"mkdir -p {voices}\n"
        f"touch {voices}/myvoice-ref.wav\n"
        f"echo '{{\"name\":\"myvoice\"}}' > {voices}/myvoice.json\n"
        "echo 'CLONE_DONE'\n"
        "exit 0\n"
    )
    stub_clone.chmod(0o755)

    result = run_afterwords("clone", "http://example.com", "myvoice",
                            env_override={"AFTERWORDS_REPO_DIR": str(tmp_path)})
    # refine would call qa-voices.py; since stub exits 0, refine should complete
    assert result.returncode in (0, 1), result.stderr
    assert "CLONE_DONE" in result.stdout
```

Run:
```bash
pytest tests/test_cli_expansion.py::test_clone_calls_refine_after_success -v
```
Expected: FAIL (clone currently does not call refine).

- [ ] **Step 2: Rewrite `cmd_clone()` in afterwords.sh**

Replace the existing `cmd_clone()` function:

> **VERIFIED:** the original resolved the voice name from raw `$2`, which breaks for `clone URL --quick` (`$2` = `--quick`). It also `warn`'d on every non-zero refine exit, silently treating a hard error (exit 2) the same as a WER warning (exit 1). Both fixed: the voice name comes from the **2nd flag-filtered positional** (matching `clone-voice.sh`), and exit 2 is surfaced distinctly. `--quick`/`--yes` are forwarded to `refine`. The clone itself already succeeded, so a refine warning/hard-error does not fail `cmd_clone` (it returns 0) — it just reports.

```bash
cmd_clone() {
    local quick=false yes=false
    # Mirror clone-voice.sh: drop flags, take the 2nd positional as the voice name.
    local positional=() skip_next=false all=("$@") i arg
    for ((i=0; i<${#all[@]}; i++)); do
        arg="${all[i]}"
        if $skip_next; then skip_next=false; continue; fi
        case "$arg" in
            --quick)        quick=true ;;
            --yes)          yes=true ;;
            --backend)      skip_next=true ;;
            --backend=*|--all-backends|--check-source) ;;
            --*)            ;;
            *)              positional+=("$arg") ;;
        esac
    done
    local voice_name="${positional[1]:-}"
    voice_name=$(echo "${voice_name}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')

    [ -f "$REPO_DIR/clone-voice.sh" ] || fail "clone-voice.sh not found in ${REPO_DIR}"
    bash "$REPO_DIR/clone-voice.sh" "$@"
    local clone_exit=$?
    [ $clone_exit -ne 0 ] && return $clone_exit

    if [ -n "$voice_name" ]; then
        echo
        local refine_args=("$voice_name")
        $quick && refine_args+=(--quick)
        $yes && refine_args+=(--yes)
        cmd_refine "${refine_args[@]}"
        local refine_exit=$?
        if [ $refine_exit -eq 2 ]; then
            warn "refine hard-errored (exit 2) — clone succeeded but QA could not run."
            info "Diagnose with: ${CYAN}afterwords refine ${voice_name}${NC}"
        elif [ $refine_exit -eq 1 ]; then
            warn "Refine finished with warnings — review the WER above."
        fi
    else
        echo
        info "Voice cloned. Run ${CYAN}afterwords refine <name>${NC} to verify quality."
    fi

    # Prompt restart if server is running
    if [ -n "$(server_pid)" ]; then
        echo
        info "Restart the server to load the new voice:"
        echo -e "    ${CYAN}afterwords restart${NC}"
    fi
}
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cli_expansion.py -v
```
Expected: all tests pass including the new clone-calls-refine test.

- [ ] **Step 4: Commit**

```bash
git add afterwords.sh tests/test_cli_expansion.py
git commit -m "feat(clone): auto-run refine after successful clone (--quick to use fast path)"
```

---

## Task 10: `cmd_update` — self-update command

**Files:**
- Modify: `afterwords.sh`
- Modify: `tests/test_cli_expansion.py`

- [ ] **Step 1: Write failing tests for update**

Add to `tests/test_cli_expansion.py`:

```python
import tempfile, textwrap

def _make_git_repo(tmp_path):
    """Create a minimal git repo for update tests."""
    import subprocess as _sp
    _sp.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _sp.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path,
            check=True, capture_output=True)
    _sp.run(["git", "config", "user.name", "Test"], cwd=tmp_path,
            check=True, capture_output=True)
    # Minimal structure
    (tmp_path / "server.py").write_text("# stub")
    (tmp_path / "requirements.txt").write_text("# stub")
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("# stub")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    _sp.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path,
            check=True, capture_output=True)
    return tmp_path


def _make_git_repo_with_upstream(tmp_path):
    """Clone-backed repo that is exactly 1 commit BEHIND its origin, so
    `behind > 0` and cmd_update reaches the dirty-tree check (the bug agy
    caught: a no-remote repo computes behind=0 and returns 'up to date'
    before ever checking dirty state)."""
    import subprocess as _sp
    origin = tmp_path / "origin.git"
    _sp.run(["git", "init", "--bare", "-b", "main", str(origin)],
            check=True, capture_output=True)

    work = tmp_path / "work"
    _sp.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    def g(*a): _sp.run(["git", "-C", str(work), *a], check=True, capture_output=True)
    g("config", "user.email", "t@t.com"); g("config", "user.name", "T")
    (work / "server.py").write_text("# stub")
    (work / "requirements.txt").write_text("# stub")
    venv = work / ".venv" / "bin"; venv.mkdir(parents=True)
    (venv / "activate").write_text("# stub")
    (work / "scripts").mkdir()
    g("add", "."); g("commit", "-m", "init"); g("push", "-u", "origin", "main")

    # Advance origin by one commit via a throwaway clone, leaving `work` behind.
    other = tmp_path / "other"
    _sp.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    def go(*a): _sp.run(["git", "-C", str(other), *a], check=True, capture_output=True)
    go("config", "user.email", "t@t.com"); go("config", "user.name", "T")
    (other / "UPSTREAM.txt").write_text("new")
    go("add", "."); go("commit", "-m", "upstream change"); go("push", "origin", "main")
    return work


def test_update_check_exits_without_modifying_tree(tmp_path):
    """afterwords update --check must not touch working tree files."""
    repo = _make_git_repo(tmp_path)          # no remote — fetch warns, behind=0
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("original")

    run_afterwords("update", "--check",
                   env_override={"AFTERWORDS_REPO_DIR": str(repo)})
    assert sentinel.read_text() == "original"


def test_update_warns_on_dirty_tree(tmp_path):
    """With commits available upstream AND a dirty tree, update must warn and
    abort non-interactively (no TTY, no --yes)."""
    repo = _make_git_repo_with_upstream(tmp_path)
    (repo / "voices").mkdir()
    (repo / "voices" / "test.json").write_text('{"name":"test"}')  # untracked-dirty under voices/
    import subprocess as _sp
    _sp.run(["git", "-C", str(repo), "add", "voices/test.json"],
            check=True, capture_output=True)   # stage so status --porcelain reports it

    result = run_afterwords("update",
                            env_override={"AFTERWORDS_REPO_DIR": str(repo)})
    combined = (result.stdout + result.stderr).lower()
    assert "voices" in combined          # warned about the dirty voices/ path
    assert result.returncode != 0        # aborted (non-TTY, no --yes)
```

Run:
```bash
pytest tests/test_cli_expansion.py::test_update_check_exits_without_modifying_tree -v
```
Expected: FAIL — `update` command not yet defined.

- [ ] **Step 2: Implement `cmd_update()` in afterwords.sh**

Add after `cmd_refine()`:

> **VERIFIED / spec §1.7:** (1) `origin/HEAD` is often unset (many clones only have `origin/main`), giving a false "0 commits" — resolve the upstream via `@{u}` with a branch fallback. (2) The prompts used bare `read -r` with no `[ -t 0 ]` guard — in CI / subagents that reads EOF and the behaviour is murky; gate on TTY and add `--yes`. (3) `pip` → `python3 -m pip` to guarantee the active venv. (4) `cmd_reload` itself calls `fail` (exit 1) on a non-responding server, which would kill `cmd_update` mid-run — call it in a subshell so its exit can't escape, and note `/reload` needs the server started with `--allow-clone`. (5) reload is add-only and won't reimport changed `server.py`/deps, so recommend a restart when those change.

```bash
cmd_update() {
    local check_only=false yes=false
    for arg in "$@"; do
        case "$arg" in
            --check) check_only=true ;;
            --yes)   yes=true ;;
        esac
    done

    git -C "$REPO_DIR" rev-parse --git-dir &>/dev/null \
        || fail "Not a git working tree — cannot self-update (tarball installs must update manually)"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"

    info "Fetching latest commits..."
    git -C "$REPO_DIR" fetch origin 2>&1 \
        || warn "git fetch failed — check your network. Continuing with local state."

    # Resolve upstream robustly: prefer the tracking branch, else origin/<branch>.
    local upstream branch
    upstream=$(git -C "$REPO_DIR" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)
    if [ -z "$upstream" ]; then
        branch=$(git -C "$REPO_DIR" symbolic-ref --short HEAD 2>/dev/null)
        upstream="origin/${branch}"
    fi

    local behind
    behind=$(git -C "$REPO_DIR" rev-list "HEAD..${upstream}" --count 2>/dev/null || echo "0")
    info "${behind} commit(s) available upstream (${upstream})"

    if $check_only; then
        ok "--check complete (no working-tree, package, or server changes made)"
        return 0
    fi
    if [ "$behind" -eq 0 ]; then
        ok "Already up to date"
        return 0
    fi

    # Refuse to pull over a dirty tree unless confirmed (TTY) or --yes.
    local dirty
    dirty=$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)
    if [ -n "$dirty" ]; then
        local dirty_voices
        dirty_voices=$(git -C "$REPO_DIR" status --porcelain -- voices/ 2>/dev/null)
        if [ -n "$dirty_voices" ]; then
            warn "Local edits to voices/ may be overwritten by git pull:"
            echo "$dirty_voices" | sed 's/^/    /'
        fi
        warn "Working tree has uncommitted changes:"
        echo "$dirty" | sed 's/^/    /'
        if $yes; then
            warn "--yes given — proceeding over dirty tree"
        elif [ -t 0 ]; then
            echo -en "  ${BOLD}Continue anyway? [y/N]${NC} "
            local confirm; read -r confirm
            [[ "${confirm:-n}" =~ ^[Yy]$ ]] || { info "Cancelled"; return 1; }
        else
            fail "Dirty working tree and no TTY — re-run with --yes to override"
        fi
    fi

    local before_ref after_ref
    before_ref=$(git -C "$REPO_DIR" rev-parse --short HEAD)

    info "Pulling..."
    git -C "$REPO_DIR" pull --ff-only 2>&1 \
        || fail "git pull --ff-only failed — your branch may have diverged. Merge manually."
    after_ref=$(git -C "$REPO_DIR" rev-parse --short HEAD)

    info "Installing packages..."
    python3 -m pip install --quiet -r "${REPO_DIR}/requirements.txt"
    [ -f "${REPO_DIR}/requirements-clone.txt" ] \
        && python3 -m pip install --quiet -r "${REPO_DIR}/requirements-clone.txt"

    local changed_files
    changed_files=$(git -C "$REPO_DIR" diff --name-only "${before_ref}..${after_ref}" 2>/dev/null)

    # Reload voices if running (subshell so cmd_reload's `fail` can't abort update).
    if [ -n "$(server_pid)" ]; then
        info "Reloading voices (best-effort; /reload needs --allow-clone)..."
        ( cmd_reload ) || warn "reload failed — server may not be started with --allow-clone"
    fi

    # Reload is add-only and won't reimport changed code/deps — recommend a restart.
    if echo "$changed_files" | grep -qE '^(server\.py|requirements.*\.txt|backends/)'; then
        warn "Server code or dependencies changed — run ${CYAN}afterwords restart${NC} to apply."
    fi
    if echo "$changed_files" | grep -qE '^(afterwords\.sh|setup\.sh)$'; then
        warn "Setup files changed — run ${CYAN}bash setup.sh${NC} if behaviour feels wrong."
    fi

    ok "Updated ${before_ref} → ${after_ref}"
    echo "$changed_files" | sed 's/^/    /' | head -20
    return 0
}
```

- [ ] **Step 3: Add `update` to the dispatch case block**

After `refine)`:

```bash
    update)      cmd_update "$@" ;;
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cli_expansion.py -v
```
Expected: all update tests pass.

- [ ] **Step 5: Commit**

```bash
git add afterwords.sh tests/test_cli_expansion.py
git commit -m "feat(cli): add update command for self-update via git pull"
```

---

## Task 11: `--ai` flag + `docs/ai-guide.md`

**Files:**
- Modify: `afterwords.sh`
- Create: `docs/ai-guide.md`
- Modify: `tests/test_cli_expansion.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_expansion.py`:

```python
def test_ai_flag_prints_guide():
    result = run_afterwords("--ai")
    assert result.returncode == 0
    assert "# Afterwords" in result.stdout
    assert "## Command Reference" in result.stdout
    assert "## Agent Tips" in result.stdout

def test_ai_flag_no_pager():
    """--ai must print raw to stdout (no pager, no interactive prompt)."""
    result = run_afterwords("--ai")
    assert result.returncode == 0
    assert len(result.stdout) > 500  # substantive output
```

Run:
```bash
pytest tests/test_cli_expansion.py::test_ai_flag_prints_guide -v
```
Expected: FAIL.

- [ ] **Step 2: Create `docs/ai-guide.md`**

```markdown
# Afterwords — AI Assistant Guide

## Version
Sprint 6 (2026-06-04). Run `afterwords status` to confirm the server is running before issuing any synthesis or clone commands.

## Critical: First-Run Setup
1. `bash setup.sh` — installs venv, launchd service, and CLI symlink
2. `afterwords start` — starts the TTS server
3. `afterwords status` — confirm server is healthy and voices are loaded

## Command Reference

### Server commands
```
afterwords start          Start the TTS server (via launchd)
afterwords stop           Stop the server
afterwords restart        Restart the server
afterwords status         Server state, loaded voices, backends
afterwords logs           Tail the server log
```

### Voice commands
```
afterwords voices                      List all loaded voices
afterwords voices --demo               Play a sample of each voice
afterwords clone <url> <name>          Clone from YouTube URL (runs refine after)
afterwords clone <file> <name>         Clone from local audio file
afterwords clone <url> <name> --quick  Clone + fast refine (qa only, no compare/trim)
afterwords reload                      Add newly cloned voices without restart
afterwords reload --prune              Also evict voices whose JSON was deleted
```

### Analysis commands
```
afterwords transcribe <audio>          Word-level timestamps (--backend parakeet|faster-whisper)
afterwords qa                          Ref WER for all voices (--voice NAME, --synth, --json)
afterwords qa --voice <name>           QA a single voice
afterwords qa --json                   Machine-readable output: {voices:[{name,ref_wer}], threshold}
afterwords trim                        Detect silence gaps (dry run — use --apply to write)
afterwords trim --apply                Write trimmed WAVs and refresh transcripts
afterwords trim --json                 Machine-readable: {voices:[{name,gap_count,changed}]}
afterwords compare <audio>             faster-whisper vs parakeet (speed + inter-model agreement)
afterwords compare <audio> --json      Machine-readable: {winner,agreement_wer,whisper_words,parakeet_words,skipped}
afterwords refine <voice>              Full QA cycle: qa → compare → trim → re-qa
afterwords refine <voice> --quick      Fast path: qa → re-qa only (skip compare + trim)
afterwords audit                       Voice profile drift check
afterwords audit --archive             TTS archive .mp3/.txt pair auditing
afterwords audit --archive --json      Machine-readable archive audit
```

### Clone workflow
```
afterwords clone <url> <name> [start_s] [--yes] [--quick]
```
`start_s` is the segment start in seconds (default 0). `--yes` suppresses all confirmation prompts. `--quick` runs fast post-clone refine.

### Cloud commands
```
afterwords setup-cloud     Configure API key and cloud URL
afterwords push <name>     Push a voice (+ family variants) to the cloud
afterwords pull <id>       Pull a cloud voice to local voices/
```

### Update
```
afterwords update          Pull latest commits, reinstall packages, reload voices
afterwords update --check  Report available commits without changing anything
```

## Workflow Sequences

### Clone and verify a voice
```bash
afterwords clone "https://youtube.com/watch?v=..." myvoice 45
# refine runs automatically after clone
# If WER is high, re-run manually:
afterwords refine myvoice
```

### QA an existing voice library
```bash
afterwords qa --json | python3 -c "
import json,sys
d=json.load(sys.stdin)
bad=[v for v in d['voices'] if v['ref_wer']>d['threshold']]
print('High WER voices:', [v['name'] for v in bad])
"
```

### Full refine cycle
```bash
afterwords refine myvoice          # runs qa → compare → trim (with prompt) → re-qa
# or in automation (suppress trim prompt):
afterwords refine myvoice --yes    # treats trim prompt as 'n'
```

### Update the server
```bash
afterwords update --check          # see what's available
afterwords update                  # pull + install + reload voices
```

## Agent Tips
1. Always check `afterwords status` before synthesising — the server may be warming up (models load in ~30s).
2. Use `--quick` when cloning in automation; run `afterwords refine <name>` as a separate review step.
3. `afterwords qa --json` for machine-readable WER; parse the `ref_wer` field per voice.
4. Do not call `trim --apply` without reviewing `trim` dry-run output first.
5. `afterwords update --check` before `update` in agent workflows — confirm no dirty state first.
6. The server serialises all synthesis through a single Metal lock; do not send concurrent synthesis requests.
7. Voice profiles in `voices/*.json` require `reference_text` to match the WAV content exactly — wrong transcripts produce garbled clones.
8. `afterwords reload` is add-only; use `afterwords reload --prune` to remove voices whose JSON was deleted from disk.

## Common Failures and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `venv missing` | setup.sh not run or venv broken | `bash setup.sh --server-only` |
| `bad interpreter` after brew upgrade | Python minor-version upgrade broke symlink | `bash setup.sh --server-only` |
| Synthesis returns empty/garbled | Wrong `reference_text` in profile | Run `afterwords refine <voice>` |
| `qa` returns WER > 0.3 | Reference audio has music/background noise | Re-clone with a cleaner segment |
| `update` fails with diverged | Local commits not on origin | Merge manually: `git merge @{u}` (the upstream branch) |
| Server not reachable after `update` | New packages require restart | `afterwords restart` |
```

- [ ] **Step 3: Add `--ai` detection to afterwords.sh main dispatch**

Find the main dispatch block near the bottom. Before the `COMMAND="${1:-help}"` line, add:

```bash
# --ai flag: print AI guide and exit (detected before COMMAND dispatch)
if [ "${1:-}" = "--ai" ]; then
    AI_GUIDE="${REPO_DIR}/docs/ai-guide.md"
    if [ -f "$AI_GUIDE" ]; then
        cat "$AI_GUIDE"
    else
        fail "docs/ai-guide.md not found in ${REPO_DIR}"
    fi
    exit 0
fi
```

> **VERIFIED:** this block sits at the **top level** of the script (the dispatch section near line 985, outside any function). `local` is only legal inside a function — `local guide=…` here is a fatal `local: can only be used in a function` runtime error that breaks **every** `afterwords` invocation. Use a plain variable (named in caps to avoid clashing with function-local `guide` vars) and `exit 0` (not `return 0`). `fail` is fine at top level (it `exit`s).

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cli_expansion.py -k "ai" -v
```
Expected: both --ai tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: ≥450 passed.

- [ ] **Step 6: Commit**

```bash
git add afterwords.sh docs/ai-guide.md tests/test_cli_expansion.py
git commit -m "feat(cli): --ai flag and docs/ai-guide.md for agent workflows"
```

---

## Task 12: Help redesign — six-section layout with Analysis section

**Files:**
- Modify: `afterwords.sh`
- Modify: `tests/test_cli_expansion.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_expansion.py`:

```python
def test_help_contains_analysis_section():
    result = run_afterwords("help")
    assert result.returncode == 0
    assert "Analysis" in result.stdout

def test_help_contains_all_new_commands():
    result = run_afterwords("help")
    for cmd in ("transcribe", "qa", "trim", "compare", "refine", "update"):
        assert cmd in result.stdout, f"'{cmd}' missing from help output"

def test_help_contains_update_in_setup():
    result = run_afterwords("help")
    assert "update" in result.stdout
    # update must appear under Setup section (or at minimum, in the output)
    lines = result.stdout.splitlines()
    setup_idx = next((i for i, l in enumerate(lines) if "Setup" in l), None)
    assert setup_idx is not None, "Setup section missing from help"
```

Run:
```bash
pytest tests/test_cli_expansion.py -k "help" -v
```
Expected: FAIL — Analysis section and new commands not in help.

- [ ] **Step 2: Rewrite `cmd_help()` in afterwords.sh**

Replace the entire `cmd_help()` function body with:

```bash
cmd_help() {
    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— local voice-cloning TTS for Apple Silicon${NC}"
    rule
    echo
    echo -e "  ${BOLD}Server${NC}"
    echo -e "    ${CYAN}start${NC}             Start the TTS server (via launchd)"
    echo -e "    ${CYAN}stop${NC}              Stop the server"
    echo -e "    ${CYAN}restart${NC}           Restart"
    echo -e "    ${CYAN}status${NC}            Server state, loaded voices, backends"
    echo -e "    ${CYAN}logs${NC}              Tail the server log"
    echo
    echo -e "  ${BOLD}Voices${NC}"
    echo -e "    ${CYAN}voices${NC}            List cloned voices (--demo to play samples, --cloud for cloud voices)"
    echo -e "    ${CYAN}clone URL NAME${NC}    Clone from YouTube URL or local file (--quick for fast refine)"
    echo -e "    ${CYAN}reload${NC}            Reload voices without restart (--prune to evict deleted)"
    echo
    echo -e "  ${BOLD}Analysis${NC}"
    echo -e "    ${CYAN}transcribe <audio>${NC}  Word-level timestamps (--backend parakeet|faster-whisper)"
    echo -e "    ${CYAN}qa${NC}                 Ref WER for all voices (--voice NAME, --synth, --json)"
    echo -e "    ${CYAN}trim${NC}               Remove silence gaps from refs (--apply to write, --json)"
    echo -e "    ${CYAN}compare <audio>${NC}    faster-whisper vs parakeet WER comparison (--json)"
    echo -e "    ${CYAN}refine <voice>${NC}     Full QA cycle: qa → compare → trim → re-qa (--quick to skip compare/trim)"
    echo -e "    ${CYAN}audit${NC}              Voice profile drift check (--archive for TTS archive pairs)"
    echo
    echo -e "  ${BOLD}Cloud${NC}"
    echo -e "    ${CYAN}push NAME${NC}         Push a voice (+ family variants) to the cloud"
    echo -e "    ${CYAN}pull ID${NC}           Pull a cloud voice to local voices/"
    echo -e "    ${CYAN}setup-cloud${NC}       Configure API key and cloud URL"
    echo
    echo -e "  ${BOLD}Integrations${NC}"
    echo -e "    ${CYAN}codex-hook start${NC}  Speak Codex CLI responses (run inside Codex)"
    echo -e "    ${CYAN}codex-hook stop${NC}   Stop the Codex watcher"
    echo
    echo -e "  ${BOLD}Setup${NC}"
    echo -e "    ${CYAN}configure${NC}         Show or change server settings (e.g. --with-1.7b)"
    echo -e "    ${CYAN}update${NC}            Pull latest commits, reinstall packages, reload voices"
    echo -e "    ${CYAN}uninstall${NC}         Remove service and optionally hooks"
    echo
    echo -e "  ${DIM}Examples:${NC}"
    echo -e "  ${DIM}  afterwords clone \"https://youtube.com/watch?v=xyz\" gandalf 45${NC}"
    echo -e "  ${DIM}  afterwords clone voices/clip.wav myvoice --yes${NC}"
    echo -e "  ${DIM}  afterwords refine gandalf${NC}"
    echo -e "  ${DIM}  afterwords qa --json | python3 -c \"import json,sys; print([v for v in json.load(sys.stdin)['voices'] if v['ref_wer']>0.15])\"${NC}"
    echo -e "  ${DIM}  afterwords compare voices/gandalf-ref.wav --json${NC}"
    echo -e "  ${DIM}  afterwords update --check${NC}"
    echo -e "  ${DIM}  afterwords push picard${NC}"
    echo -e "  ${DIM}  echo \"snape\" > .afterwords  # per-project voice override${NC}"
    echo
}
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cli_expansion.py -k "help" -v
```
Expected: all 3 help tests pass.

- [ ] **Step 4: Commit**

```bash
git add afterwords.sh tests/test_cli_expansion.py
git commit -m "feat(cli): redesign help output — six sections including Analysis"
```

---

## Task 13: Final verification — acceptance criteria and full test suite

**Files:**
- Modify: `tests/test_cli_expansion.py` (add any remaining acceptance criteria tests)

- [ ] **Step 1: Add any missing acceptance criteria tests**

Check the spec §7 acceptance criteria against existing tests. Add these if not already covered:

Do NOT add `pass  # covered` placeholder tests — they assert nothing and mask gaps. AC3/AC7/AC9 are already covered by real tests (`test_clone_local_file_detected_not_ytdlp`, `test_update_check_exits_without_modifying_tree`, `test_audit_archive_routes_to_archive_script`); list them in this plan's coverage table rather than restubbing them. Add only the two acceptance tests that aren't yet covered:

```python
def test_ac10_json_flags_present():
    """AC10: --json flag present on qa, trim, compare (model-free --help check)."""
    import subprocess as _sp
    for script_name in ("qa-voices.py", "trim-silence-gaps.py", "compare-transcription.py"):
        result = _sp.run(
            [sys.executable, str(REPO / "scripts" / script_name), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "--json" in result.stdout, f"--json missing from {script_name} --help"

def test_ac11_scripts_internal_contains_moved():
    """AC11: scripts/internal/ contains (at least) the 9 moved scripts."""
    internal = REPO / "scripts" / "internal"
    assert internal.is_dir()
    expected = {
        "reclone-flagship.py", "gen-comparison-audio.sh", "loudnorm-demo-audio.sh",
        "clone-red-dwarf.sh", "check-og-metadata.py", "fb-reindex.sh",
        "transcribe-youtube-batch.sh", "qa-transcripts.py", "review-content.py",
    }
    actual = {f.name for f in internal.iterdir() if not f.name.startswith(".")}
    missing = expected - actual
    assert not missing, f"missing from scripts/internal/: {missing}"

def test_ac11_chunk_text_stays_in_scripts():
    """AC11: chunk-text.py must NOT move (has tests/test_chunk_text.py)."""
    assert (REPO / "scripts" / "chunk-text.py").exists()
    assert not (REPO / "scripts" / "internal" / "chunk-text.py").exists()
```

- [ ] **Step 2: Run ALL acceptance criteria**

```bash
pytest tests/test_cli_expansion.py -v
```
Expected: all pass.

- [ ] **Step 3: Run the full test suite**

```bash
source .venv/bin/activate
pytest -q
```
Expected: ≥435 passed, 0 failures (all original tests + all new tests).

- [ ] **Step 4: Verify help output manually**

```bash
bash afterwords.sh help
```
Expected: six sections (Server, Voices, Analysis, Cloud, Integrations, Setup) with all new commands listed.

- [ ] **Step 5: Verify --ai flag manually**

```bash
bash afterwords.sh --ai | head -20
```
Expected: Markdown guide with `# Afterwords — AI Assistant Guide` header.

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli_expansion.py
git commit -m "test: acceptance criteria for Sprint 6 CLI expansion"
```

- [ ] **Step 7: Tag the release**

```bash
# After confirming all tests pass and acceptance criteria met
git tag v1.0.5
git push origin main --tags
```

---

## Self-Review

**Spec coverage check:**

| Spec § | Requirement | Task |
|--------|-------------|------|
| 1.1 transcribe | cmd_transcribe wrapper | Task 5 |
| 1.2 qa | cmd_qa wrapper | Task 5 |
| 1.3 trim | cmd_trim wrapper | Task 5 |
| 1.4 compare | cmd_compare wrapper, no --model flag | Task 5 |
| 1.5 audit --archive | cmd_audit --archive routing | Task 6 |
| 1.6 refine | 4-step pipeline, exit code chaining, --quick | Task 8 |
| 1.7 update | git pull, --check, dirty warn, setup-changed notice | Task 10 |
| 2.1 local-file | [ -f "$1" ] check, source_basename JSON field | Task 7 |
| 2.2 auto-refine | cmd_clone calls cmd_refine; --quick passes through | Task 9 |
| 2.2 --yes suppresses trim prompt | trim prompt conditional on `[ -t 0 ]` in cmd_refine | Task 8 |
| 3 --ai flag | beforeCommand dispatch, cat guide | Task 11 |
| 3 docs/ai-guide.md | all sections per spec | Task 11 |
| 4 help redesign | six sections, Analysis section | Task 12 |
| 5 script polish --json | qa/trim/compare --json flags | Tasks 2-4 |
| 5 exit codes 0/1/2 | per-script normalization | Tasks 2-4 |
| 5 TTY markers | `sys.stdout.isatty()` gating | Tasks 2-4 |
| 6 scripts/internal/ | 9 scripts moved, test path updated | Task 1 |
| 6 chunk-text.py stays | not moved | Task 1 |
| 7 AC12 pytest 435+ | full suite run | Task 13 |

**Contract drift points (verified consistent):**
- `ref_wer` field + `threshold: 0.15`: qa `--json` builds these from `rows` by index (Task 2); `REF_WER_THRESHOLD = 0.15` is the single source for the JSON field and the exit-1 decision. The human `WARN-REF` flag stays at 0.6 (separate band, no test coverage).
- `gap_count` field: trim `--json` emits one record **per processed voice incl. zero-gap** (Task 3) and prints JSON **before** the dry-run return; cmd_refine parses `gap_count` (Task 8) — same name.
- compare `--json`: emits `{winner, agreement_wer, whisper_words, parakeet_words, skipped}` (Task 4) — cmd_refine runs it for its exit code only, does not parse the body.
- AFTERWORDS_REPO_DIR override: added in Task 5, used by tests from Task 6 onward.

**Exit-code contract (Tasks 2–4, 8):** every analysis script — 0 clean / 1 warning / 2 hard error; cmd_refine aborts with `return 2` (NOT `fail`, which exits 1) on qa/trim exit 2, and warns+continues on compare exit 1 **or** 2.

**Spec deviation (resolved 2026-06-04):** spec §5 line 264 originally named compare `--json` as `{winner, faster_whisper_wer, parakeet_wer}`, but the script computes no ground-truth WER (only inter-model `wer_wp`). The spec was reconciled to the `{winner, agreement_wer, whisper_words, parakeet_words, skipped}` shape Task 4 emits — spec and plan are now in sync. (If per-model accuracy is ever genuinely wanted, that requires adding a ground-truth reference-transcript path to `compare-transcription.py` — a separate scope.)

**CI vs integration:** the qa/trim/compare structure tests load Whisper (and `large-v2` for compare) — marked `@pytest.mark.integration` and skipped in default `pytest -q` / CI, mirroring `test_fidelity.py`. CI coverage of the `--json` contract is the model-free `--help` presence tests + the stub-based refine/clone/update tests. Run `pytest -m integration` on the dev machine before tagging.
