# Desktop watcher corrective acceptance — 9 October 2026

Candidate source is on `fix/desktop-tts-watchers`, retaining the two omitted
commits `e97536a` and `81e75d8`. Main is `ed60536`. This work does not resolve
issue #122, accept PR #123, refresh dependency PRs, or remove the inherited
private original voice reference from main.

## Regressions and review

Before repair, the standard timestamped Codex rollout filename produced the
entire timestamp-prefixed stem instead of its session UUID. A split JSON record
advanced the line watermark to 1, then emitted zero answers when completed;
parsing the completed first line directly returned one. The source candidate
had no watcher installer or repository OpenCode adapter.

The repair uses session metadata identity, persistent byte offsets that stop
before unterminated records, stable queue event names and durable completion
receipts. OpenCode follows each identified completed message. Failed synthesis,
encoding or playback retains the claimed event for retry. Queue children stay
in the launchd process group and use a process lock during recovery. Global
and per-session Codex speech have mutually exclusive ownership.

Seventeen desktop regression cases cover metadata/session isolation, split
UTF-8 and newline writes, actual process termination between writer chunks,
termination after worker claim, synthesis/encoder failure, restart deduplication,
truncation, initial-baseline termination, OpenCode completion, fresh copied
runtime and lifecycle registration. Before-fix failures were reproduced against
the original watcher logic; installation and adapter were absent from that tree.

Final full suite: **754 passed, 2 skipped**. The existing Starlette/httpx
TestClient deprecation warning remains. The independent read-only reviewer
ran **26 focused tests** (desktop and Hermes), passed diff checks, inspected
sanitized fixtures and approved the final source diff with no concrete remaining
code defect. An earlier full run timed out because a Hermes stub test used the
live play lock; tests now isolate their lock paths while production defaults
retain the shared play-lock convention.

## Isolated live lifecycle and speech

A fresh disposable HOME, separate session files, separate OpenCode database and
unique LaunchAgent labels were used. The installer copied only its explicit
source-helper list; no source checkout or existing Studio hook installation was
used by the installed runtime.

Verified with real launchctl: initial install, repeated install/upgrade, restart,
bootout followed by cold bootstrap, uninstall, and repeated uninstall. Both
services were running after cold bootstrap. Restart produced zero duplicate
archives. Uninstall during an isolated sleeping worker terminated that worker
and removed source runtime, while preserving private progress/receipts.

A real `opencode run --standalone` turn ran in an empty disposable project with
an isolated data/state/cache directory. Existing provider configuration was
read without alteration. Its completed database row passed through the installed
watcher and included OpenCode adapter into the shared speech worker. Both
Codex and OpenCode created an MP3 plus text archive through the existing TTS
server. The ordinary-word post-bootstrap input was:

> The river flows beside the quiet garden.

Cached local faster-whisper base.en recovered that sentence from both decoded
MP3s (OpenCode transcription differed only in initial capitalization). Codex:
2.88 seconds, 26,928 bytes. OpenCode: 1.92 seconds, 17,112 bytes. This is ASR and
artifact evidence, not a native listening judgment or a resolution of #122.
An earlier app-name phrase produced phonetic ASR substitutions, which were not
claimed as an exact-word pass.

The real TTS process remained PID 13632, started 5 October; no server restart,
setup, reload, clone or server-configuration mutation was performed. Isolated
acceptance watcher services were uninstalled after testing. Existing Studio
watcher services were not restarted or reconfigured.

## Privacy and remaining release gate

The two branch-only commits introduce only four intended source/test paths.
Their patches and the named final source/test/fixture paths were inspected;
credential-shaped literal scanning found no keys or tokens. Nested metadata
identities were replaced with synthetic UUIDs and test paths before staging.
No private configuration, user transcript, credential, audio, generated runtime,
audit scratch or personal `.afterwords` file is included in this candidate.
This check is scoped to material introduced by the PR; the private original WAV
already inherited from main remains a separate cleanup item and is not erased
from repository history by this repair.

Physical reboot acceptance has **not** been performed. RunAtLoad/KeepAlive
registration and isolated cold bootstrap are verified. The user has been asked
whether that fulfills the reboot gate under the instruction to keep the live
server untouched; publishing awaits that answer.

Stable queue identities provide deduplicated acceptance across watcher retries.
Exactly-once audible playback across termination is not promised: killing a
process after audio plays but before acknowledgement can replay unfinished work.
