# Afterwords — AI Assistant Guide

## Version
v1.0.6 (2026-06-15). Run `afterwords status` to confirm the server is running before issuing any synthesis or clone commands.

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
afterwords mute           Toggle TTS playback on/off (mute the Mac; synthesis continues)
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
