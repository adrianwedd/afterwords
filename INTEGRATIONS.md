# Agent integration matrix

Use ONBOARDING.md to accept bundled-voice foreground speech first. Integrations are optional; the baseline installer configures none. `bash setup.sh --integrations` is interactive discovery of installed agents and can offer Claude installation. It is not an unattended single-agent installer. Changing installed hook configuration or restarting the in-use service requires owner approval under STRATEGY.md.

| Integration | Prerequisites | Config destination and installation | Helpers | Live acceptance |
|---|---|---|---|---|
| Claude Code | Installed `claude`; setup-managed Python runtime; curl, jq; Homebrew `lame` for archives | `bash setup.sh --integrations` merges Stop and SubagentStop into `~/.claude/settings.json`, pointing both at the private managed runtime | Stable transcript-event adapter and durable queue under `~/Library/Application Support/Afterwords/watchers/` | `afterwords integrations` confirms config/runtime; one real final response speaks once and archives under `~/.claude/tts-archive/` |
| Gemini CLI | Installed `gemini`, same queue-worker prerequisites | Setup installs adapter and prints a snippet to manually merge into `~/.gemini/settings.json`; it does not edit those settings | `gemini-tts-hook.sh` plus shared worker/helpers | `gemini -p "say hi"` speaks once; Claude archive receives audio |
| Antigravity (AGy) | Installed `agy`; setup-managed Python runtime; curl and Homebrew `lame` for archives | `bash setup.sh --integrations` merges `afterwords-tts` Stop registration into `~/.gemini/config/hooks.json`, preserving unrelated hooks | Stable transcript-event adapter and durable queue under `~/Library/Application Support/Afterwords/watchers/` | `afterwords integrations` confirms config/runtime; one real final response speaks once and archives under `~/.claude/tts-archive/` |
| Cursor | Cursor application, command, or `~/.cursor`; same queue-worker prerequisites | Integration setup merges `afterAgentResponse` into `~/.cursor/hooks.json` | `cursor-tts-hook.sh`, shared worker/helpers | One Cursor agent final reply speaks once; Claude archive receives audio |
| Codex CLI | Installed `codex`; Python, ripgrep, curl, audio/archive tools | `bash setup.sh --integrations` installs a login LaunchAgent that follows Codex sessions globally; no Stop hook | Private managed runtime under `~/Library/Application Support/Afterwords/watchers/` | `afterwords watchers status codex`; one real final answer speaks once and archives under `~/.codex/tts-archive/` |
| OpenCode v2 desktop/CLI | Installed `opencode` using the v2 SQLite `session_v2`/`session_message` schema; Python, curl, `afplay`, Homebrew `lame` | `bash setup.sh --integrations` detects it and installs a private runtime and login LaunchAgent; no OpenCode plugin or Claude settings changes | Private managed runtime under `~/Library/Application Support/Afterwords/watchers/` | `afterwords watchers status opencode`; one real final answer queues once, speaks once, and archives under `~/.opencode/tts-archive/` |
| Hermes | Installed Hermes; Python/aiohttp for native hook; curl and audio/archive tools for shell paths | Separate explicit setup in `docs/hermes-integration.md`; baseline/integration setup does not configure Hermes | Native `handler.py`, shell post-LLM hook, or command provider; choose the intended path | One local final response speaks once; expected archive under `~/.hermes/tts-archive/`; command provider returns complete real audio |

`bash setup.sh --integrations` stages the managed runtime before writing Claude or AGy hook settings, then installs login watchers for detected Codex and OpenCode CLIs. It merges only Afterwords-owned hook entries and preserves unrelated hook owners. `afterwords integrations` checks hook registration, source/runtime agreement, watcher state and Homebrew `PATH`. Gemini CLI and Hermes retain their separate setup paths described above.

Every automatic playback path honors `/tmp/afterwords-muted`; synthesis and archives continue. All integrations share `/tmp/afterwords-play.lock` and `/tmp/afterwords-play.pid`. Foreground user-requested playback remains audible when automatic speech is muted. Project `.afterwords` mappings use `claude` subagent types or `codex`, `gemini`, `agy`, `cursor`, and `hermes`, with `default` fallback.

Repository tests exercise each queue-based shared-helper install in a disposable HOME, verify no Claude settings are written for other agents, and cover Hermes delivery failure contracts. These checks do not prove live third-party hook execution, audible speech, or exactly-once archives. Complete the per-integration live acceptance above before claiming that integration works on a fresh Mac.

## Desktop login watchers

`afterwords watchers install codex|opencode|all` installs the candidate watchers
without touching the TTS server or another tool's hook configuration. Python and
curl must be available; afplay and lame are required for playback and archives.
The installer copies only an explicit list of source helpers into a private
runtime under `~/Library/Application Support/Afterwords/watchers/`. It does not
copy voices, project preferences, credentials, transcripts or scratch files.

The LaunchAgents `au.wedd.afterwords-codex-watch` and
`au.wedd.afterwords-opencode-watch` use RunAtLoad and KeepAlive. Manage only
these services with `afterwords watchers status|restart|uninstall <agent>`.
`afterwords watchers stage all` refreshes the shared private runtime without
installing a new LaunchAgent.
Reinstall updates the runtime and reloads installed sibling watchers safely.
Uninstall stops the selected watcher and removes its plist. The shared source
runtime and private progress/queue receipts are retained because Claude or AGY
hooks may still use them and so reinstall does not replay old answers; archives
remain.

Global Codex coverage and `codex-hook start` have mutually exclusive ownership:
stop the per-session watcher before installing global coverage, and uninstall
global coverage before arming a per-session watcher. Diagnostics remain usable.
Codex identity comes from `session_meta.payload.id`; project selection comes
from its cwd, and `codex:` mappings are used. Only newline-terminated records
advance persistent byte offsets. Partial JSON/UTF-8 bytes remain in the source
file across process termination. First installation baselines historical complete
records; subsequent downtime is caught up without a one-hour expiry.

OpenCode waits for `data.time.completed` on each identified assistant row. It
reads that row's content and session directory, retains unfinished messages, and
persists accepted message IDs. This is specifically the inspected v2 schema;
other database schemas are not silently treated as supported integrations.

Stable event names preserve one queue publication across watcher retries and
restarts. Pre-playback failures retain a bounded retry path. Before playback may start,
the event moves to `.playing`. Complete playback commits `.done`; partial or
uncertain playback parks `.failed` without replay. Archive failure is diagnostic
and cannot replay audio that may already have been heard. Reliable
watcher queues do not coalesce pending answers. Receipts and private state live
outside the repository with restricted permissions. Process-group supervision
lets launchd stop drain workers during restart, upgrade and uninstall.

This guarantees deduplicated queue acceptance, not mathematically exactly-once
audible playback across a process kill: playback is an external side effect. The `.playing` receipt
prevents replay after a kill once playback may have started; interrupted speech
can therefore remain incomplete and must not be described as full delivery.

Fresh-install acceptance must use disposable HOME, sessions/database and unique
LaunchAgent labels, then exercise install, reinstall/upgrade, restart, cold
bootstrap and uninstall. Use `watcher/manage.py --home ... --label-prefix ...`
with `--sessions` / `--db` for that isolation. Run a real OpenCode turn through
that installed runtime before claiming end-to-end delivery. A cold bootstrap
checks login launch semantics but does not itself prove a physical reboot.

Native automatic speech requires the caller-scoped consumer bridge described in `hermes/patches/README.md`. A profile-wide playback-owner setting cannot identify which caller will play the returned artifact.

### Profile-specific native speech ownership

The shell hook defers before synthesis, archiving and playback when Hermes
supplies `tts_playback_owner: "native"` (flat or under `extra`). A compatible
Hermes producer is required. The native consumer bridge supplies caller-scoped
`AFTERWORDS_TTS_CALLER=native`, then guards actual playback with mute and the shared lock.
Ordinary CLI hooks without an owner continue to speak. Gateway delivery stays
owned by native voice mode; the shell hook must not send another message.

A profile hook may set `AFTERWORDS_PORT` (loopback only, 1–65535, default 7860)
and `AFTERWORDS_VOICE` (overrides project/global mappings). Use the same route
and voice in that profile's command provider; no global routing change is needed.

The native route probe supports `--agent-prompt 'Your prompt' --deadline 360`
for a real Hermes CLI reply with captured sentence playback. It preserves the
configured model/tools/personality and automatic mute flag, requires the installed caller-scoped
native consumer bridge, and records incomplete attempts on a hard
process deadline. Use a fresh output directory. Keychain-backed model access on
this M5 succeeds in a fresh GUI launchd worker but returns exit 36 under SSH;
use the working context without changing credentials. Capture is not physical
playback or acoustic acceptance. The current expressive transport is temporary.

## Removing setup-managed integrations

`afterwords uninstall` removes the standard server/CLI, then offers the existing
opt-in removal choice for setup-managed hook registrations and Codex/OpenCode
login watchers. Accepting removes only Afterwords registrations and those two
watcher units, retaining unrelated hooks/settings. Declining leaves integrations
in place and reports that choice explicitly. Runtime/helper code, offsets, queue
receipts and archives remain for safe reinstall. Per-session Codex and manually
configured Hermes/expressive services have separate lifecycle controls.
