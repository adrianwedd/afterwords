# Afterwords Menu-Bar App — Design Spec

**Date:** 2026-05-14 (revised)
**Scope:** Phase 1 — Server lifecycle menu-bar app
**Repo:** Separate repo (`afterwords-app`), depends on `afterwords` being installed

## Architecture

A Swift/SwiftUI menu-bar app that communicates with the existing `afterwords` TTS server exclusively through its HTTP API (`localhost:7860`) and CLI (`afterwords` binary on PATH).

```
Afterwords.app (Swift/SwiftUI, ~2-5 MB)
  ├── Menu-bar icon (SF Symbols: waveform.circle / waveform.circle.fill)
  ├── Popover UI
  │     ├── Status (running/starting/stopped/error)
  │     ├── Start/Stop/Restart controls
  │     ├── Open Logs button
  │     ├── Open API button (localhost:7860)
  │     └── Settings link
  ├── ServerManager (owns lifecycle: CLI calls + health polling)
  │     ├── CLIExecutor (Foundation.Process with explicit PATH injection)
  │     └── HealthMonitor (GET /health every 5s)
  └── AppDelegate (SMAppService for launch-at-login)
```

## Key Design Decisions

1. **CLI for actions, HTTP for state.** Server start/stop/restart via `afterwords` CLI. Health and backend status via `GET /health`. The app never imports Python or touches the venv.

2. **No Python bundling.** The app is a thin native shell. Requires `afterwords` installed and on PATH (setup.sh already symlinks to `/usr/local/bin/afterwords`). This keeps the binary at 2-5 MB instead of 500+ MB.

3. **No App Sandbox.** Sandbox blocks subprocess spawning, which is core to the app. FlashMLX and macMLX both disable sandbox for the same reason.

4. **Auto-start via SMAppService.** macOS 13+ API for launch-at-login of the *app itself*. This is separate from the server's launchd plist — SMAppService manages "open Afterwords.app at login", while launchd manages "keep the server process alive".

5. **Separate repo.** `afterwords-app` alongside `afterwords`. The app wraps the CLI, it doesn't share Python code with the server.

6. **launchd owns server lifecycle.** The existing `afterwords` CLI uses `launchctl load/enable` to manage a LaunchAgent plist with `KeepAlive: true`. The app delegates to `afterwords start/stop/restart` and treats the CLI as the authority. It does NOT call `launchctl` directly or try to track the server PID. HealthMonitor polling `GET /health` is the single source of truth for server state.

7. **HealthMonitor is the single source of truth.** No ProcessManager tracking PIDs. The app calls `afterwords start` (fire-and-forget), then HealthMonitor detects the transition from `.stopped` → `.starting` → `.running`. This avoids race conditions between CLI exit and server readiness.

8. **Explicit PATH injection.** macOS GUI apps don't inherit shell PATH. The app builds a PATH at startup from known locations: `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` plus any user-configured path. This PATH is injected into every `Foundation.Process` environment before execution.

## Phase 1: Server Lifecycle

### Features

- **Status icon** in menu bar with dynamic appearance:
  - `waveform.circle.fill` (green) when server is running
  - `waveform.circle` (gray) when stopped
  - `waveform.circle.badge.xmark` (red) on error
  - Spinning/pulsing animation while `.starting`

- **Start/Stop/Restart** buttons that call `afterwords start`, `afterwords stop`, `afterwords restart`
- **Health display** showing loaded backends and voice count from `GET /health`
- **Open Logs** button that runs `afterwords logs` (opens Console.app or tails the log)
- **Open API** button that opens `http://localhost:7860` in default browser
- **Settings** with:
  - Launch at Login toggle (SMAppService — controls the *app*, not the server)
  - CLI path override (default: auto-detect from `/usr/local/bin/afterwords` or `which afterwords`)
  - Server auto-start toggle (whether to start the server when the app launches)

### Server State Machine

The app tracks server state through HealthMonitor polling, not through ProcessManager PID tracking:

```
         afterwords start
.stopped ──────────────────→ .starting
   ↑                            │
   │                            │ GET /health returns 200
   │                            ↓
   │                       .running
   │                            │
   │  afterwords stop           │ health poll fails 3×
   │  (or server crash)         │ (crash recovery)
   │                            ↓
   └─────────────────────── .error(message)
                                │
                                │ afterwords start
                                └──→ .starting
```

**`.starting` state:** Server takes 15-45s to load models *once weights are cached locally*. HealthMonitor polls every 2s during `.starting` (faster than the normal 5s) to detect the transition to `.running`. If health hasn't responded within 90s, transition to `.error("Server did not become healthy within 90s")`.

**Cold-cache first-run caveat:** The four backends preload ~10 GB of weights at boot. On a fresh install where weights are not yet cached, the Hugging Face download can take several minutes on typical residential bandwidth — well beyond the 90s timeout. Phase 1 mitigation: when the timeout fires, do NOT transition to `.error` outright if `/health` is still reachable and reports `loaded_backends == []`; instead surface a "Downloading models (first run)…" sub-state and extend the timeout. A cleaner long-term fix is to extend `/health` to report per-backend load progress so the app can distinguish `loading-weights-from-disk` (fast) from `downloading-weights` (slow).

**Crash recovery:** If HealthMonitor detects `.running` → connection refused (3 consecutive failures), the app transitions to `.error` and shows a "Server crashed — Restart?" prompt. The user can click Restart to try again. The app does NOT auto-restart, because launchd's `KeepAlive: true` should handle that — if the server is down despite `KeepAlive`, something deeper is wrong.

**Pre-existing server:** On app launch, HealthMonitor immediately polls `GET /health`. If the server is already running, the app shows `.running` without any CLI call. This handles the common case where the server was started before the app.

### Process Management

`CLIExecutor` uses `Foundation.Process` to run `afterwords` CLI commands with explicit PATH injection:

```swift
func execute(_ arguments: [String]) async throws -> String {
    let process = Process()
    process.executableURL = resolvedCLIURL  // /usr/local/bin/afterwords or user override
    process.arguments = arguments
    // Explicit PATH injection — macOS GUI apps don't inherit shell PATH
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = Self.resolvedPATH  // /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin + user override
    process.environment = env
    // ... capture stdout/stderr, handle exit codes
}
```

`resolvedPATH` is built at startup from known macOS Homebrew locations:
```swift
static let resolvedPATH: String = {
    let defaultPaths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    if let userPath = UserDefaults.standard.string(forKey: "additionalPath") {
        return userPath + ":" + defaultPaths.joined(separator: ":")
    }
    return defaultPaths.joined(separator: ":")
}()
```

`resolvedCLIURL` tries these locations in order:
1. User-configured path (Settings)
2. `/usr/local/bin/afterwords` (where setup.sh symlinks it)
3. Result of `which afterwords` (run at startup via a shell process that inherits PATH)

If not found, show a setup prompt with instructions to run `bash setup.sh`.

Key behaviors:
- Start: `afterwords start` — fire and forget. HealthMonitor detects transition.
- Stop: `afterwords stop`
- Restart: `afterwords restart`
- Logs: `afterwords logs`
- Status: `afterwords status` for CLI-based status confirmation, but HealthMonitor polling is the primary state source.

### Health Monitoring

`HealthMonitor` polls `GET /health` on a timer:

```swift
class HealthMonitor: ObservableObject {
    @Published var state: ServerState = .stopped

    // Polling intervals
    private let normalInterval: TimeInterval = 5.0
    private let startingInterval: TimeInterval = 2.0
    private let startupTimeout: TimeInterval = 90.0

    // Consecutive failure threshold before declaring server down
    private let crashConfirmCount = 3
}
```

Parses `/health` response into `ServerState` enum:
```swift
enum ServerState {
    case stopped
    case starting(since: Date)   // CLI called, waiting for /health
    case running(HealthInfo)      // /health returning 200
    case error(message: String)   // crash confirmed or startup timeout
}

struct HealthInfo {
    let backends: [BackendInfo]
    let voices: [String]

    struct BackendInfo {
        let name: String
        let supportedLangs: [String]
    }
}
```

### Quit Behavior

When the app quits:
- The server **continues running** — it's managed by launchd, not the app.
- This matches user expectations: the server should stay available for Claude Code hooks even if the app isn't open.
- The app's "Start at Login" toggle controls whether the *app* opens at login (SMAppService). The server's auto-start is controlled by the existing launchd plist's `RunAtLoad` key.

### Minimum macOS Version

macOS 13.0 (Ventura) — required for `SMAppService` and modern SwiftUI APIs.

### Phase 1 ↔ Signing dependency

`SMAppService.mainApp.register()` works for unsigned development builds, but the system Login Items database persists the bundle identity. If a user installs an unsigned Phase 1 build and later replaces it with a Developer-ID-signed Phase 3 build at the same bundle ID, macOS may flag the registration as tampered and silently disable the launch-at-login item until the user toggles it again in System Settings → General → Login Items. Two mitigations to consider:

1. Ship Phase 1 with at least an ad-hoc signature (`codesign --sign -`) so the bundle identity is stable.
2. Document in the Phase 1 README that launch-at-login on unsigned dev builds is best-effort and may need a manual re-enable after upgrades. Real reliability arrives in Phase 3 with Developer ID + notarization.

### File Structure

```
afterwords-app/
├── Afterwords.xcodeproj
├── Afterwords/
│   ├── AfterwordsApp.swift        # App entry + @MainActor
│   ├── AppDelegate.swift          # SMAppService registration
│   ├── Models/
│   │   ├── ServerState.swift      # State machine enum
│   │   └── HealthInfo.swift        # /health response model
│   ├── Services/
│   │   ├── CLIExecutor.swift      # Foundation.Process + PATH injection
│   │   └── HealthMonitor.swift    # /health polling + state transitions
│   ├── Views/
│   │   ├── PopoverView.swift      # Main popover
│   │   ├── StatusView.swift       # Status icon + state display
│   │   └── SettingsView.swift     # Launch at login, CLI path, auto-start
│   ├── Assets.xcassets/
│   └── Info.plist
├── AfterwordsTests/
│   ├── CLIExecutorTests.swift
│   ├── HealthMonitorTests.swift
│   └── ServerStateTests.swift
└── README.md
```

## What Phase 1 Does NOT Include

- No Python bundling or first-run setup
- No model downloading
- No voice cloning UI (Phase 2)
- No voice list in popover (too dense; deferred to Phase 2 detail window)
- No port override in Settings (hardcoded 7860; deferred to Phase 2)
- No auto-update via Sparkle (Phase 3)
- No DMG distribution or notarization (Phase 3)
- No direct launchctl calls (app delegates entirely to `afterwords` CLI)

## Future Phases

### Phase 2: Voice Management & Detail Window
- Separate detail window (not popover) for voice list, backend info
- Voice cloning from URL (wraps `afterwords clone`)
- Voice preview (plays sample WAV via `afplay`)
- Default voice selector per project (reads `.afterwords` files)
- Port override in Settings
- Server auto-start toggle (whether to call `afterwords start` on app launch)

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