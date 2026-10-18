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

Prepare a reviewable installation without touching the running checkout:

```sh
python scripts/prepare-hermes-native.py \
  --hermes-root "$HOME/.hermes/hermes-agent" --out NEW_PRIVATE_DIRECTORY
```

Preparation fails if any target file differs from its recorded base. Install
only during the approved runtime transition: retain the original four files,
copy the staged replacements and `afterwords_native.py` into Hermes, and start
new consumers from the new source. Existing processes retain imported modules.
Do not claim this bridge is active merely because preparation or tests pass.
Rollback restores the four original files and removes only the installed helper.

Tests exercise the staged **actual installed consumer code**, with artifact
creation and speaker output captured locally. They cover mute, a live shared
lease, release on failure, per-call ownership and ordinary tool calls. They do
not send messages or establish acoustic acceptance. The patch is maintained
here as an explicit local compatibility dependency, not an upstream Hermes
release claim. Applying it is part of the final runtime approval, not preparation.
