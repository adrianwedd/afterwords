# Afterwords operational entrypoint

This file is an entrypoint, not a promise that yesterday's process is still
running. Re-run the commands below before making a source, installation or
delivery claim.

## Supported baseline

The dependable product is the local Qwen3 0.6B server plus explicit voice
profiles. Agent integrations are optional clients. Fish Drama 3 is an isolated,
resource-gated expressive experiment; it is not the default engine and is not
qualified as a general long-form replacement.

```bash
git status --short --branch
git fetch origin
git rev-list --left-right --count HEAD...origin/main
.venv/bin/python -m pytest -q
curl -fsS --max-time 5 http://127.0.0.1:7860/health
bash afterwords.sh status
bash afterwords.sh integrations
```

Count the public corpus with Git, never the private on-disk directory:

```bash
git ls-files 'voices/*.json' | wc -l
```

## Reconciliation candidate

The current source candidate is the local branch
`reconcile/trustworthy-voice-20261123`. It combines the local acquisition work,
current remote `main`, nonblocking Hermes playback, deterministic project-voice
routing and a bridge manifest rebased against the inspected M5 Hermes source.
Use `git rev-parse HEAD` for its exact revision; do not substitute branch name
for commit identity in a review or deployment receipt.

The candidate deliberately does not contain private voice recordings, runtime
receipts, credentials, local preferences, the untracked October findings note
or `var/`. Those remain in their existing custody. A dirty canonical checkout
is therefore not permission to clean it.

## Current installed state (inspected 23 November 2026)

- The launchd server was ready with Qwen3 0.6B and 349 on-disk profiles. This is
  a health observation, not source identity, synthesis, playback or listening
  acceptance.
- Automatic playback was muted.
- The Hermes profile referenced `scripts/afterwords-project-voice.sh`, which was
  untracked at inspection and is tracked by the candidate.
- The installed Hermes handler was a hybrid not equal to repository source.
- The installed native bridge helper was from the preceding revision; the four
  Hermes consumers were pristine at Hermes `ae2a81ccc00`.
- Claude and AGy used legacy registered hooks and a legacy worker. Gemini had an
  unregistered adapter. Cursor was absent. Codex and OpenCode managed watchers
  were absent; the Codex per-session watcher was stopped.
- `com.afterwords.tts-feed` was spawn-failed because its plist selected the
  missing `/opt/homebrew/bin/python3`. See GitHub issue #143.

The proposed Hermes installation and rollback are in
[`docs/operations/installed-runtime-plan.md`](docs/operations/installed-runtime-plan.md).
No installation or restart is implied by source preparation.

## Acceptance layers

Keep these claims separate:

| Layer | Minimum evidence |
| --- | --- |
| Source | Exact commit, clean named diff and passing source tests |
| Installed files | Exact before/after hashes read back from the installed paths |
| Loaded runtime | Process start/reload receipt plus loaded source/config identity |
| Synthesis | Real requested text produces a complete valid audio artifact |
| Queueing | Stable event identity and terminal receipt without replay |
| Playback | The intended playback owner invokes the complete artifact once |
| Audible acceptance | A human actually hears and assesses it |
| External delivery | The intended remote service receives the actual artifact |

Captured adapters, fake players, ASR, identity embeddings and valid WAV files
are useful evidence. None of them, alone, proves audible or external delivery.

## Approval boundary

`STRATEGY.md` remains authoritative. Get Adrian's approval before pushing or
merging `main`, publishing, running setup against the live installation,
restarting services, changing hook configurations, mutating the live server or
altering tracked voice assets. Source-only work and isolated staging are not
deployment.

## Next direction

See [`docs/afterwords-next-direction.md`](docs/afterwords-next-direction.md) for
the bounded proposal: retain Qwen as the reliable engine, make identity and
delivery one thin contract, and qualify Fish only against the failure specimens
where expressive control is worth its cost.
