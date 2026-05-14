# Afterwords Menu-Bar App — Design Spec

**Date:** 2026-05-14
**Scope:** Phase 1 — Server lifecycle menu-bar app
**Repo:** Separate repo (`afterwords-app`), depends on `afterwords` being installed

## Architecture

A Swift/SwiftUI menu-bar app that communicates with the existing `afterwords` TTS server exclusively through its HTTP API (`localhost:7860`) and CLI (`afterwords` binary on PATH).

```
Afterwords.app (Swift/SwiftUI, ~2-5 MB)
  ├── Menu-bar icon (SF Symbols: waveform.circle / waveform.circle.fill)
  ├── Popover UI
  │     ├── Status (running/stopped/starting/error)
  │     ├── Start/Stop/Restart controls
  │     ├── Voice list (from GET /health)
  │     ├── Open Logs button
  │     ├── Open API button (localhost:7860)
  │     └── Settings link
  ├── ProcessManager (Foundation.Process → afterwords CLI)
  └── HealthMonitor (GET /health every 5s)
```

## Key Design Decisions

1. **CLI for actions, HTTP for state.** Server start/stop/restart via `afterwords` CLI. Health, voice list, backend status via `GET /health`. The app never imports Python or touches the venv.

2. **No Python bundling.** The app is a thin native shell. Requires `afterwords` installed and on PATH (setup.sh already symlinks to `/usr/local/bin/afterwords`). This keeps the binary at 2-5 MB instead of 500+ MB.

3. **No App Sandbox.** Sandbox blocks subprocess spawning, which is core to the app. FlashMLX and macMLX both disable sandbox for the same reason.

4. **Auto-start via SMAppService.** macOS 13+ API for launch-at-login, replacing the current launchd plist approach. One-line toggle in Settings.

5. **Separate repo.** `afterwords-app` alongside `afterwords`. The app wraps the CLI, it doesn't share Python code with the server.

## Phase 1: Server Lifecycle

### Features

- **Status icon** in menu bar with dynamic appearance:
  - `waveform.circle.fill` (green) when server is running
  - `waveform.circle` (gray) when stopped
  - `waveform.circle.badge.xmark` (red) on error
- **Start/Stop/Restart** buttons that call `afterwords start`, `afterwords stop`, `afterwords restart`
- **Health display** showing loaded backends and voice count from `GET /health`
- **Voice list** showing all loaded voices with name and backend
- **Open Logs** button that runs `afterwords logs` (opens Console.app or tails the log)
- **Open API** button that opens `http://localhost:7860` in default browser
- **Settings** with:
  - Launch at Login toggle (SMAppService)
  - Port override (default 7860)
  - Default voice selection

### Process Management

`ProcessManager` uses `Foundation.Process` to spawn `afterwords` CLI commands:

```swift
func execute(_ arguments: [String]) async throws -> String {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/local/bin/afterwords")
    process.arguments = arguments
    // ... capture stdout/stderr, handle exit codes
}
```

Key behaviors:
- Start: `afterwords start` (launchd manages the actual server process)
- Stop: `afterwords stop`
- Restart: `afterwords restart`
- Status: `afterwords status` for CLI-based status, `GET /health` for runtime state
- Crash recovery: HealthMonitor detects server-down transitions, offers restart

### Health Monitoring

`HealthMonitor` polls `GET /health` every 5 seconds when the server is running:

```json
{
  "status": "ok",
  "loaded_backends": [
    {"name": "chatterbox", "supported_langs": ["en", "es", ...]}
  ],
  "voices": ["galadriel", "picard", ...]
}
```

Parses into `ServerState` enum: `.running(health)`, `.stopped`, `.starting`, `.error(message)`.

### File Structure

```
afterwords-app/
├── Afterwords.xcodeproj
├── Afterwords/
│   ├── AfterwordsApp.swift
│   ├── AppDelegate.swift
│   ├── Models/
│   │   ├── ServerState.swift
│   │   └── VoiceInfo.swift
│   ├── Services/
│   │   ├── ProcessManager.swift
│   │   └── HealthMonitor.swift
│   ├── Views/
│   │   ├── PopoverView.swift
│   │   ├── StatusView.swift
│   │   ├── VoiceListView.swift
│   │   └── SettingsView.swift
│   ├── Assets.xcassets/
│   └── Info.plist
├── AfterwordsTests/
└── README.md
```

### CLI Discovery

The app needs to find the `afterwords` binary. Priority order:
1. `/usr/local/bin/afterwords` (where setup.sh symlinks it)
2. `which afterwords` output
3. User-configurable path in Settings

If not found, show a setup prompt with instructions to run `bash setup.sh`.

### Minimum macOS Version

macOS 13.0 (Ventura) — required for `SMAppService` and modern SwiftUI APIs.

## Future Phases

### Phase 2: Voice Management
- Voice cloning from URL (wraps `afterwords clone`)
- Voice preview (plays sample WAV via `afplay`)
- Default voice selector per project (reads `.afterwords` files)

### Phase 3: Distribution
- Code signing with Developer ID
- Notarization via `notarytool`
- DMG creation via `create-dmg`
- Sparkle 2.x for auto-updates
- GitHub Releases as appcast host

### Phase 4: First-Run Setup (optional)
- Detect Python 3.11+ installation
- Offer to install via `uv` or Homebrew
- Download model weights with progress UI
- Configure Claude Code hooks

## What Phase 1 Does NOT Include

- No Python bundling or first-run setup
- No model downloading
- No voice cloning UI
- No auto-update via Sparkle
- No DMG distribution or notarization