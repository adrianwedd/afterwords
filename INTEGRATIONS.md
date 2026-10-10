# Agent integration matrix

Use ONBOARDING.md to accept bundled-voice foreground speech first. Integrations are optional; the baseline installer configures none. `bash setup.sh --integrations` is interactive discovery of installed agents and can offer Claude installation. It is not an unattended single-agent installer. Changing installed hook configuration or restarting the in-use service requires owner approval under STRATEGY.md.

| Integration | Prerequisites | Config destination and installation | Helpers | Live acceptance |
|---|---|---|---|---|
| Claude Code | Installed `claude`, Python, curl, jq; ffmpeg/lame for archives | Integration setup merges Stop and SubagentStop into `~/.claude/settings.json` | Shared `~/.claude/hooks/tts-hook.sh`, `tts-worker.sh`, strip/chunk/summarization helpers | One final response speaks once; MP3 appears in `~/.claude/tts-archive/` |
| Gemini CLI | Installed `gemini`, same queue-worker prerequisites | Setup installs adapter and prints a snippet to manually merge into `~/.gemini/settings.json`; it does not edit those settings | `gemini-tts-hook.sh` plus shared worker/helpers | `gemini -p "say hi"` speaks once; Claude archive receives audio |
| Antigravity (AGy) | Installed `agy`, same queue-worker prerequisites | Integration setup merges `afterwords-tts` Stop registration into `~/.gemini/config/hooks.json` | `agy-tts-hook.sh`, `agy-session-hook.py`, shared worker/helpers | `agy --print "say hi"` speaks once; Claude archive receives audio |
| Cursor | Cursor application, command, or `~/.cursor`; same queue-worker prerequisites | Integration setup merges `afterAgentResponse` into `~/.cursor/hooks.json` | `cursor-tts-hook.sh`, shared worker/helpers | One Cursor agent final reply speaks once; Claude archive receives audio |
| Codex CLI | Interactive CLI session with `CODEX_THREAD_ID`, Python, curl, ripgrep; audio/archive tools | Run `bash setup-codex.sh` in that session; watcher follows the matching rollout. No global Stop config | Repo `.claude/hooks/codex-tts-watch.sh`, `codex-tts-worker.sh`, session parser and repository helpers | Watcher status is healthy; one final answer speaks once and archives under `~/.codex/tts-archive/` |
| OpenCode v2 desktop/CLI | OpenCode v2 SQLite `session_v2`/`session_message` schema; Python, curl, afplay/lame | `afterwords watchers install opencode` installs a private runtime and a login LaunchAgent; no OpenCode plugin or Claude settings changes | Included `opencode/tts-hook-opencode.sh`, durable message ledger, shared speech worker | New completed real turn queues once, produces an MP3+txt under `~/.opencode/tts-archive/`, and restart does not replay it |
| Hermes | Installed Hermes; Python/aiohttp for native hook; curl and audio/archive tools for shell paths | Separate explicit setup in `docs/hermes-integration.md`; baseline/integration setup does not configure Hermes | Native `handler.py`, shell post-LLM hook, or command provider; choose the intended path | One local final response speaks once; expected archive under `~/.hermes/tts-archive/`; command provider returns complete real audio |

The four queue-based agents install shared helpers even when detected alone. Installing those helpers under `~/.claude/hooks` does not imply Claude hook registration: Claude settings are changed only when Claude is selected. Gemini and AGy deliberately have different config destinations and event payloads.

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
Reinstall updates the runtime and reloads installed sibling watchers safely.
Uninstall stops the selected watcher, removes its plist, and removes source
runtime after the last watcher is removed. Private progress and queue receipts
are retained to prevent old answers replaying on reinstall; archives remain.

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
restarts. A failed worker keeps the claimed event for retry; a done receipt is
committed after all chunks synthesize, play (unless muted), and archive. Reliable
watcher queues do not coalesce pending answers. Receipts and private state live
outside the repository with restricted permissions. Process-group supervision
lets launchd stop drain workers during restart, upgrade and uninstall.

This guarantees deduplicated queue acceptance, not mathematically exactly-once
audible playback across a process kill: playback is an external side effect. A
kill after playback but before acknowledgement can replay unfinished work.

Fresh-install acceptance must use disposable HOME, sessions/database and unique
LaunchAgent labels, then exercise install, reinstall/upgrade, restart, cold
bootstrap and uninstall. Use `watcher/manage.py --home ... --label-prefix ...`
with `--sessions` / `--db` for that isolation. Run a real OpenCode turn through
that installed runtime before claiming end-to-end delivery. A cold bootstrap
checks login launch semantics but does not itself prove a physical reboot.
