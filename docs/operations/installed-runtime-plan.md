# Proposed installed-runtime reconciliation

Status: prepared for review; **not installed**. Inspected and staged on
23 November 2026.

The private staging root is under
`~/.local/state/afterwords-reconciliation-20261123/`. It contains no credentials
or private voice recordings. Its handler copy remains the pre-review candidate;
the final reviewed handler must be regenerated into a fresh named staging
directory rather than silently replacing that preserved variant.

## Hermes handler

Installed before hash:

```text
cd694fdc40493a9dc29c0f75805a9a16f803041818aa7e591a7f3e036317fcbc
```

Final source-derived candidate hash, including the stamped repository hint:

```text
3a438669cabb16a9afc892a3ca1fe69f4f24ac65bdbd86d8d5503f0dd6c11469
```

The preserved pre-review staged handler is
`ee38b39e76540e0d85a12e11abd2e84c1383271a82f76e10158e1c018ab550c9`;
it is superseded evidence, not the install candidate.

The candidate differs intentionally: exact-session project routing, playback
off the gateway event loop, cancellation that terminates and waits for owned
`afplay` before releasing the lease, mute enforcement beside the side effect,
and a completion sidecar published only after every chunk is archived.
Generate and install the recorded hash with this exact ownership scope:

```bash
AFTERWORDS_PYTHON=/Users/adrian/repos/afterwords/.venv/bin/python \
  bash scripts/install-hermes-hook.sh --local-only
```

The `--local-only` flag is material: the direct CLI remains owned by the shell
hook, while the native handler owns only Hermes' `local` platform. Omitting it
produces a different hash and competing CLI ownership. Installation would replace only
`~/.hermes/hooks/afterwords-tts/{handler.py,HOOK.yaml}` using the existing
installer. The gateway must remain unchanged until an idle restart is approved.

Rollback: before installation, preserve the current handler by its exact hash in
the existing reconciliation custody root. Restore it only if the installed
candidate fails loaded-runtime acceptance, then restart the same gateway once it
is idle. Do not roll back profile configuration or unrelated Hermes files.

## Hermes native consumer bridge

Inspected Hermes source: detached `ae2a81ccc00`, with no tracked modifications
in the four consumers. The existing untracked `afterwords_native.py` is the old
helper and is preserved in place.

| Path | Installed/pristine SHA-256 | Proposed SHA-256 |
| --- | --- | --- |
| `afterwords_native.py` | `0127d4193240a831584188e6e143cbf47f027cde642f627b1f7ca85962c1497d` | `9eb1dd7df3aaeb0efdc69cfbd1c7b11d70384bce1d131fbcd0f8cedf05014f93` |
| `tools/tts_command_provider.py` | `75f9fae3a50a77e0224f4eb35c75ee24e2d40d90685ee39df401fe6bbdfa36bf` | `9c8203f7485f7242281938c2d9641f56e86e47f5c9aa75d4b9afd6d53c3738fd` |
| `tools/tts_tool_speaker.py` | `3bf6c5d7dd8b68b7e5cbaaf34a5e63a08bdb1bfaefa0a944e3c7dfad540c60e7` | `74019e1a6cb076252f5b62ec18af51313026c7496f3c0186d3a5447ff39a73e8` |
| `hermes_cli/cli_voice_mixin.py` | `d36724d6b47a1c5c2249ede8e7204493fa21ace59e5e2484e3b05463ccbb5fa9` | `e3370bfd8865cd6ac40d0826d3957e649dbc9f6f656d29fb0d8119b053e24d2d` |
| `hermes_cli/voice.py` | `54275dbdd02126407e1dec79296a831c664cb78ca17009677d871abe122f339f` | `6395756f87e1235ec6ab9a9f77f2a1b5655b7ff2fc0820853f5f3bb83f305a9c` |

The patch still applies cleanly to the inspected source. The updated helper
exports Hermes' task-local session ID and runtime cwd into the scrubbed command
child; it does not consult process-global recency. Focused staging, missing
bridge, incomplete bridge, mute, occupied-lock and playback tests pass.

Installation must be a named-file, hash-guarded copy from the staged directory.
Abort if any installed before hash, Hermes HEAD or profile-config hash has
changed. Do not reset or update the Hermes checkout as part of installation.

Rollback is the inverse named-file operation: restore the five exact inspected
files, verify their hashes, and restart only the affected idle gateway. Preserve
new unrelated Hermes changes and the candidate files in the custody root.

## Managed agent integrations

No bulk integration setup is proposed.

- Claude and AGy: legacy registrations exist and currently launch the old shared
  worker. Decide whether to migrate them to the managed durable runtime only
  after one owner and one queue are chosen. Do not install a second worker beside
  the legacy one.
- Gemini: adapter exists, registration absent. Leave absent unless Gemini is an
  actual supported surface.
- Cursor: absent. No action.
- Codex: global watcher absent and per-session watcher stopped. Choose one mode,
  never both, only if Codex speech is wanted.
- OpenCode: watcher absent. No action without a real current use case.
- Hermes: reconcile the candidate above; it is the active integration priority.

Each later installation needs its own source/registration/runtime/queue/playback
receipt. “Detected” and “speaks once” are different claims.

## Feed delivery (#143)

Before hash of `~/Library/LaunchAgents/com.afterwords.tts-feed.plist`:
`bfaf428630fa2ecdf5b23048e1012dccd688069c62913715a3b3d23fce99ffcc`.

Proposed single-field change: replace missing `/opt/homebrew/bin/python3` with
the supported repository `.venv/bin/python`. Then, under explicit live-change
approval:

1. Re-read the plist hash and the venv interpreter identity.
2. Record the current seen-state hash and enumerate unseen items without sending.
3. Under the feed lock, disposition the recorded stale set without delivery:
   `scripts/tts-feed-send.py --discard-current-backlog --receipt PRIVATE_PATH`.
   The default five-minute quiescence window excludes active responses. The
   mode-0600 receipt freezes the cutoff and records the path, size, mtime and
   SHA-256 of every original transcript/audio object before the atomic
   seen-state change. Read back the receipt and seen-state hash before
   continuing. If the disposition must be reversed while those originals still
   match, run `scripts/tts-feed-send.py --recover-backlog-disposition --receipt
   PRIVATE_PATH`; this removes only the markers introduced by that receipt.
4. Change only `ProgramArguments[0]`.
5. Boot out and bootstrap the existing label once.
6. Verify a scheduled run—not a manual invocation—has exit code zero and writes
   the configured log.
7. Reconcile every previously named backlog item as sent, deliberately excluded,
   already seen or missing; do not infer delivery from disappearance.

Each external target gets a durable, byte-bound attempt journal and in-flight
marker before `hermes send`, then a success marker immediately after confirmed
CLI acceptance. The journal freezes the exact delivery media and original
source-object hashes; later archive edits cannot rewrite the attempt record. A
timeout is indeterminate: later scheduled runs hold that target instead of
retrying it and risking a duplicate. Reconcile the remote service first; a zero
CLI exit still does not prove remote receipt. Then make one non-sending,
mode-0600 receipted transition bound to the source-media hashes:

```bash
scripts/tts-feed-send.py \
  --resolve-indeterminate 'hermes:ITEM.mp3:discord' \
  --resolution delivered \
  --receipt PRIVATE_PATH
```

Use `--resolution retry` only after confirming the remote service did not
receive it. Neither resolution sends a message.

Rollback restores the exact prior plist bytes and label. It also restores the
broken interpreter, so rollback is for unexpected side effects, not a successful
operational end state.
