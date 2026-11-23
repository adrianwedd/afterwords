# Native Hermes consumer bridge

The Afterwords command returns an artifact to several different callers. A
profile-wide `AFTERWORDS_PLAYBACK_OWNER=hermes` cannot distinguish an ordinary
CLI tool from the native sentence speaker. The bridge scopes ownership to each
native synthesis invocation using a ContextVar, then exports that identity only
to its command subprocess. Gateway attachment delivery remains separate.

The retained patch targets the exact installed Hermes files recorded in
`native-command-playback.json`. It covers the native synchronous sentence
pipeline and both fallback CLI speech consumers. The actual consumer invokes
`native_playback`, which checks the automatic mute flag and acquires the same
mkdir/PID lease used by the shell workers. A native provider does not acquire
that lease while synthesising. This avoids synthesis waiting on its own consumer.
Ordinary CLI tools retain provider playback and profile-local archives; native
speaker artifacts go to `consumer-delivered`, outside the feed poller's scope.

## Revision 2: a missing bridge fails before audio, it does not degrade

Every patched call site reaches the bridge through one guard,
`_afterwords_bridge()`. A missing `afterwords_native`, or one that has lost
`native_synthesis`/`native_playback`/`command_environment`, raises `RuntimeError`
naming the reinstall command **before** any synthesis or playback. There is
deliberately no fallback to stock playback: stock playback bypasses the mute
flag and the shared lease, so degrading would trade a loud failure for silent,
unguarded audio. The tests assert the strong property — with the bridge absent,
zero synthesis calls, zero playback calls, and no lease is created.

Known limitation, deliberately not papered over: Hermes' per-sentence pipeline
catches exceptions from its synthesis step and logs them. A missing bridge
therefore surfaces there as a log line rather than an exception in the UI. The
audio invariant still holds (nothing plays); `--check` exists so the condition is
caught before it becomes that log line.

## Preparation works over any recognised installed state

```sh
python scripts/prepare-hermes-native.py \
  --hermes-root "$HOME/.hermes/hermes-agent" --out NEW_PRIVATE_DIRECTORY
```

Staging starts from the recorded pristine base, so it no longer requires a
pristine checkout: the base is taken from the upstream blob (`git show HEAD:`),
from an installed copy that still hashes to `before_sha256`, or — for a host
already carrying this patch — by reverse-applying the patch and checking the
recovered base against `before_sha256`. Anything the manifest does not recognise
is refused with `installed source changed`, exactly as before. The staged output
is then hash-checked against `after_sha256`.

Install only during the approved runtime transition: retain the original four
files, copy the staged replacements and `afterwords_native.py` into Hermes, and
start new consumers from the new source. Existing processes retain imported
modules. Do not claim this bridge is active merely because preparation or tests
pass. Rollback restores the four original files and removes only the installed
helper.

## Post-update verification (two commands, no new framework)

```sh
python scripts/prepare-hermes-native.py --hermes-root "$HOME/.hermes/hermes-agent" --check
```

`--check` prints a JSON receipt naming each file's state — `current`,
`superseded` (an older revision is installed), `pristine`, `missing`, `changed`
— plus the helper's state, and exits non-zero unless everything is current. It
never writes. Run it after `hermes update`: the update restores the patched
files, so `current` is the expected result and anything else names the exact
file to look at.

For behavioural evidence rather than hashes, use the existing sentence-route
capture (`scripts/verify-hermes-sentence-route.py`) and, when audible output is
acceptable, `scripts/verify-hermes-playback-invariants.py`. The latter records
synthesis, playback invocation and player success separately for the audible,
muted and stale-lease paths, and states plainly that it is not acoustic
acceptance.

Tests exercise the staged **actual installed consumer code**, with artifact
creation and speaker output captured locally. They cover mute, a live shared
lease, release on failure, per-call ownership, ordinary tool calls, absent and
incomplete bridges, and preparation over a superseded installation. They stage
from the recorded base, so `tests/test_native_consumer_bridge.py` is usable as a
regression gate on a host that is already running the patch. They do not send
messages or establish acoustic acceptance. The patch is maintained here as an
explicit local compatibility dependency, not an upstream Hermes release claim.
Applying it is part of the final runtime approval, not preparation.

The `--variant studio` patch/manifest targets Studio's earlier Hermes base
(`b53c2f6`). The default variant targets the four files as they stand from
Hermes `08a79ff`; when a host's files match its before-hashes, use the default
variant there. Preparation refuses a mismatch either way. Neither variant updates the Hermes
repository, discards its dirty changes or changes profile configuration. Stage
against the exact target host and recheck all hashes at application. Studio's
legacy command also needs `{voice}` plus an explicit provider voice before the
Afterwords source transition; its currently effective global selection is
`seven-of-nine`. Keep the standard 7860 route.

The studio variant remains at revision 1 (no guard): its base files are not on
this host, so it cannot be regenerated or hash-checked here. Do not treat the two
variants as interchangeable.
