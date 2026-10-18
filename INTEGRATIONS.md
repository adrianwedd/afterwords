# Agent integration matrix

Use ONBOARDING.md to accept bundled-voice foreground speech first. Integrations are optional; the baseline installer configures none. `bash setup.sh --integrations` is interactive discovery of installed agents and can offer Claude installation. It is not an unattended single-agent installer. Changing installed hook configuration or restarting the in-use service requires owner approval under STRATEGY.md.

| Integration | Prerequisites | Config destination and installation | Helpers | Live acceptance |
|---|---|---|---|---|
| Claude Code | Installed `claude`, Python, curl, jq; ffmpeg/lame for archives | Integration setup merges Stop and SubagentStop into `~/.claude/settings.json` | Shared `~/.claude/hooks/tts-hook.sh`, `tts-worker.sh`, strip/chunk/summarization helpers | One final response speaks once; MP3 appears in `~/.claude/tts-archive/` |
| Gemini CLI | Installed `gemini`, same queue-worker prerequisites | Setup installs adapter and prints a snippet to manually merge into `~/.gemini/settings.json`; it does not edit those settings | `gemini-tts-hook.sh` plus shared worker/helpers | `gemini -p "say hi"` speaks once; Claude archive receives audio |
| Antigravity (AGy) | Installed `agy`, same queue-worker prerequisites | Integration setup merges `afterwords-tts` Stop registration into `~/.gemini/config/hooks.json` | `agy-tts-hook.sh`, `agy-session-hook.py`, shared worker/helpers | `agy --print "say hi"` speaks once; Claude archive receives audio |
| Cursor | Cursor application, command, or `~/.cursor`; same queue-worker prerequisites | Integration setup merges `afterAgentResponse` into `~/.cursor/hooks.json` | `cursor-tts-hook.sh`, shared worker/helpers | One Cursor agent final reply speaks once; Claude archive receives audio |
| Codex CLI | Interactive CLI session with `CODEX_THREAD_ID`, Python, curl, ripgrep; audio/archive tools | Run `bash setup-codex.sh` in that session; watcher follows the matching rollout. No global Stop config | Repo `.claude/hooks/codex-tts-watch.sh`, `codex-tts-worker.sh`, session parser and repository helpers | Watcher status is healthy; one final answer speaks once and archives under `~/.codex/tts-archive/` |
| Hermes | Installed Hermes; Python/aiohttp for native hook; curl and audio/archive tools for shell paths | Separate explicit setup in `docs/hermes-integration.md`; baseline/integration setup does not configure Hermes | Native `handler.py`, shell post-LLM hook, or command provider; choose the intended path | One local final response speaks once; expected archive under `~/.hermes/tts-archive/`; command provider returns complete real audio |

The four queue-based agents install shared helpers even when detected alone. Installing those helpers under `~/.claude/hooks` does not imply Claude hook registration: Claude settings are changed only when Claude is selected. Gemini and AGy deliberately have different config destinations and event payloads.

Every automatic playback path honors `/tmp/afterwords-muted`; synthesis and archives continue. All integrations share `/tmp/afterwords-play.lock` and `/tmp/afterwords-play.pid`. Foreground user-requested playback remains audible when automatic speech is muted. Project `.afterwords` mappings use `claude` subagent types or `codex`, `gemini`, `agy`, `cursor`, and `hermes`, with `default` fallback.

Repository tests exercise each queue-based shared-helper install in a disposable HOME, verify no Claude settings are written for other agents, and cover Hermes delivery failure contracts. These checks do not prove live third-party hook execution, audible speech, or exactly-once archives. Complete the per-integration live acceptance above before claiming that integration works on a fresh Mac.

### Profile-specific native speech ownership

The shell hook defers before synthesis, archiving and playback when Hermes
supplies `tts_playback_owner: "native"` (flat or under `extra`). A compatible
Hermes producer is required. Native command providers also use
`AFTERWORDS_PLAYBACK_OWNER=hermes` so the artifact is played only by Hermes.
Ordinary CLI hooks without an owner continue to speak. Gateway delivery stays
owned by native voice mode; the shell hook must not send another message.

A profile hook may set `AFTERWORDS_PORT` (loopback only, 1–65535, default 7860)
and `AFTERWORDS_VOICE` (overrides project/global mappings). Use the same route
and voice in that profile's command provider; no global routing change is needed.

The native route probe supports `--agent-prompt 'Your prompt' --deadline 360`
for a real Hermes CLI reply with captured sentence playback. It preserves the
configured model/tools/personality and automatic mute flag, requires native
ownership in the configured command, and records incomplete attempts on a hard
process deadline. Use a fresh output directory. Keychain-backed model access on
this M5 succeeds in a fresh GUI launchd worker but returns exit 36 under SSH;
use the working context without changing credentials. Capture is not physical
playback or acoustic acceptance. The current expressive transport is temporary.
