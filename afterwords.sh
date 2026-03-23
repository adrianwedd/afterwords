#!/usr/bin/env bash
#
# afterwords — CLI for the local voice-cloning TTS server
#
# Usage: afterwords <command> [options]
#
# Commands:
#   start      Start the TTS server (via launchd)
#   stop       Stop the TTS server
#   restart    Restart the TTS server
#   status     Show server status, loaded voices, and health
#   logs       Tail the server log
#   voices     List available voices
#   clone      Clone a new voice from YouTube
#   uninstall  Remove the launchd service and optionally Claude Code hooks
#
set -uo pipefail

# ── Colours & output helpers (matches setup.sh) ──────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; DIM='\033[2m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "  ${CYAN}▸${NC} $*"; }
ok()    { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "  ${RED}✗${NC} $*"; exit 1; }
rule()  { echo -e "${DIM}  ─────────────────────────────────────────${NC}"; }

# ── Constants ────────────────────────────────────────────────────
PLIST_NAME="com.afterwords.tts-server"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_FILE="/tmp/claude-tts-server.log"
PORT=7860
HEALTH_URL="http://localhost:${PORT}/health"

# Resolve the repo directory (where server.py lives)
if [ -L "${BASH_SOURCE[0]}" ]; then
    # Followed a symlink — resolve to the real script location
    REAL_SCRIPT="$(readlink "${BASH_SOURCE[0]}")"
    # Handle relative symlinks
    if [[ "$REAL_SCRIPT" != /* ]]; then
        REAL_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd "$(dirname "$REAL_SCRIPT")" && pwd)/$(basename "$REAL_SCRIPT")"
    fi
    REPO_DIR="$(cd "$(dirname "$REAL_SCRIPT")" && pwd)"
else
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# ── Helpers ──────────────────────────────────────────────────────

# Check if plist is loaded in launchd
plist_loaded() {
    launchctl list "$PLIST_NAME" &>/dev/null
}

# Check if plist file exists on disk
plist_exists() {
    [ -f "$PLIST_PATH" ]
}

# Find PID listening on the TTS port (works whether launchd or manual)
server_pid() {
    lsof -ti :"$PORT" 2>/dev/null | head -1
}

# Get PID from launchd (available before port binding)
launchd_pid() {
    launchctl list "$PLIST_NAME" 2>/dev/null | awk '/PID/{gsub(/[^0-9]/,"",$3); if($3+0>0) print $3}'
}

# Query the /health endpoint; sets HEALTH_JSON on success
health_check() {
    HEALTH_JSON=$(curl -s --max-time 3 "$HEALTH_URL" 2>/dev/null) || return 1
    echo "$HEALTH_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" &>/dev/null || return 1
}

# ── Commands ─────────────────────────────────────────────────────

cmd_start() {
    local pid
    pid=$(server_pid)
    if [ -n "$pid" ]; then
        ok "Server already running (PID ${pid})"
        return 0
    fi

    if ! plist_exists; then
        fail "No launchd plist found. Run ${CYAN}bash setup.sh${NC} first."
    fi

    info "Starting afterwords..."
    launchctl load "$PLIST_PATH" 2>/dev/null

    # Check launchd PID first (available immediately, before port binding)
    local i
    for i in $(seq 1 5); do
        pid=$(launchd_pid)
        [ -n "$pid" ] && break
        sleep 1
    done

    # Fall back to port-based check for non-launchd starts
    if [ -z "$pid" ]; then
        pid=$(server_pid)
    fi

    if [ -n "$pid" ]; then
        ok "Server started (PID ${pid})"
        info "Model warmup takes ~15–30s. Run ${CYAN}afterwords status${NC} to check readiness."
    else
        fail "Server failed to start. Check: ${CYAN}afterwords logs${NC}"
    fi
}

cmd_stop() {
    local pid
    pid=$(server_pid)

    if [ -z "$pid" ]; then
        ok "Server is not running"
        # Unload plist anyway in case it's loaded but crashed
        plist_loaded && launchctl unload "$PLIST_PATH" 2>/dev/null
        return 0
    fi

    if plist_loaded; then
        info "Stopping afterwords (launchd)..."
        launchctl unload "$PLIST_PATH" 2>/dev/null
    else
        info "Stopping afterwords (PID ${pid})..."
        kill "$pid" 2>/dev/null
    fi

    # Wait for process to exit
    local i
    for i in $(seq 1 5); do
        [ -z "$(server_pid)" ] && break
        sleep 1
    done

    if [ -z "$(server_pid)" ]; then
        ok "Server stopped"
    else
        warn "Server still running — sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null
        sleep 1
        if [ -z "$(server_pid)" ]; then
            ok "Server killed"
        else
            fail "Could not stop server (PID ${pid})"
        fi
    fi
}

cmd_restart() {
    cmd_stop
    echo
    cmd_start
}

cmd_status() {
    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— status${NC}"
    rule
    echo

    # Process info
    local pid
    pid=$(server_pid)
    if [ -n "$pid" ]; then
        ok "Server running (PID ${pid})"

        if plist_loaded; then
            info "Managed by launchd (auto-starts on login)"
        else
            info "Running manually (no launchd)"
        fi
    else
        warn "Server is not running"
        if plist_exists; then
            info "Plist exists — start with: ${CYAN}afterwords start${NC}"
        else
            info "No plist — run: ${CYAN}bash setup.sh${NC}"
        fi
        echo
        return 0
    fi

    echo

    # Health check
    if health_check; then
        local ready model voices default_voice
        ready=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready', False))")
        model=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('model', '?'))")
        default_voice=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_voice', '?'))")
        voices=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('voices', [])))")

        if [ "$ready" = "True" ]; then
            ok "Model loaded and ready"
        else
            warn "Model loading (warmup in progress)"
        fi
        info "Model: ${DIM}${model}${NC}"
        info "Default voice: ${CYAN}${default_voice}${NC}"
        echo
        info "Available voices:"
        echo "$HEALTH_JSON" | python3 -c "
import sys, json
for v in json.load(sys.stdin).get('voices', []):
    print(f'    \033[0;36m{v}\033[0m')
"
    else
        warn "Server running but /health not responding (still warming up?)"
    fi

    echo
    info "Logs: ${DIM}${LOG_FILE}${NC}"
    info "Port: ${DIM}${PORT}${NC}"
    echo
}

cmd_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        fail "No log file at ${LOG_FILE}"
    fi
    # Pass through any extra flags (e.g., -n 50)
    tail -f "$@" "$LOG_FILE"
}

cmd_voices() {
    local demo=false
    for arg in "$@"; do
        case "$arg" in
            --demo) demo=true ;;
        esac
    done

    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— voices${NC}"
    rule
    echo

    # Try live server first
    if health_check; then
        local default_voice
        default_voice=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_voice', ''))")

        echo "$HEALTH_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
default = data.get('default_voice', '')
for v in data.get('voices', []):
    marker = ' (default)' if v == default else ''
    print(f'    \033[0;36m{v}\033[0m\033[2m{marker}\033[0m')
"
    else
        # Fallback: read voice profiles from disk
        info "Server not running — reading from disk"
        echo
        local count=0
        for f in "$REPO_DIR"/voices/*.json; do
            [ -f "$f" ] || continue
            local name
            name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$f" 2>/dev/null || basename "$f" .json)
            echo -e "    ${CYAN}${name}${NC}"
            count=$((count + 1))
        done
        if [ "$count" -eq 0 ]; then
            warn "No voice profiles found in voices/"
        fi
    fi

    echo

    if $demo; then
        if ! health_check; then
            fail "Server not running — cannot play demos. Start with: ${CYAN}afterwords start${NC}"
        fi

        local ready
        ready=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready', False))")
        if [ "$ready" != "True" ]; then
            fail "Model still warming up — try again in a moment"
        fi

        info "Playing voice demos (this takes ~20s per voice)..."
        echo
        local demo_text="The quick brown fox jumps over the lazy dog."
        local voices_list
        voices_list=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(' '.join(json.load(sys.stdin).get('voices', [])))")

        for v in $voices_list; do
            local encoded
            encoded=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$demo_text")
            info "Playing ${BOLD}${v}${NC}..."
            local wavfile="/tmp/afterwords-demo-$$.wav"
            if curl -s --max-time 90 "http://localhost:${PORT}/synthesize?text=${encoded}&voice=${v}" -o "$wavfile" 2>/dev/null; then
                local filesize
                filesize=$(stat -f%z "$wavfile" 2>/dev/null || echo 0)
                if [ "$filesize" -gt 1000 ]; then
                    afplay "$wavfile" 2>/dev/null
                else
                    warn "Synthesis returned empty audio for ${v}"
                fi
            else
                warn "Synthesis failed for ${v}"
            fi
            rm -f "$wavfile"
        done
        echo
        ok "Demo complete"
    fi
}

cmd_clone() {
    if [ ! -f "$REPO_DIR/clone-voice.sh" ]; then
        fail "clone-voice.sh not found in ${REPO_DIR}"
    fi
    # Pass all arguments through to clone-voice.sh
    bash "$REPO_DIR/clone-voice.sh" "$@"

    # Prompt restart if server is running
    if [ -n "$(server_pid)" ]; then
        echo
        info "Restart the server to load the new voice:"
        echo -e "    ${CYAN}afterwords restart${NC}"
    fi
}

cmd_uninstall() {
    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— uninstall${NC}"
    rule
    echo

    # Stop server if running
    local pid
    pid=$(server_pid)
    if [ -n "$pid" ]; then
        info "Stopping server..."
        cmd_stop
        echo
    fi

    # Remove plist
    if plist_exists; then
        rm -f "$PLIST_PATH"
        ok "Removed launchd plist"
    else
        info "No launchd plist to remove"
    fi

    # Remove symlink
    if [ -L /usr/local/bin/afterwords ]; then
        info "Removing /usr/local/bin/afterwords symlink..."
        rm -f /usr/local/bin/afterwords 2>/dev/null || sudo rm -f /usr/local/bin/afterwords
        ok "Removed CLI symlink"
    fi

    # Offer to remove Claude Code hooks
    echo
    local hooks_dir="$HOME/.claude/hooks"
    if [ -f "$hooks_dir/tts-hook.sh" ] || [ -f "$hooks_dir/tts-worker.sh" ]; then
        echo -en "  ${BOLD}Remove Claude Code TTS hooks? [y/N]:${NC} "
        read -r remove_hooks
        if [[ "$remove_hooks" =~ ^[Yy] ]]; then
            rm -f "$hooks_dir/tts-hook.sh" "$hooks_dir/tts-worker.sh" "$hooks_dir/strip-markdown.py"
            rm -f "$hooks_dir/tts-hook.sh.bak" "$hooks_dir/tts-worker.sh.bak"
            ok "Removed hook scripts"

            # Remove Stop hook from settings.json
            local settings="$HOME/.claude/settings.json"
            if [ -f "$settings" ] && command -v jq &>/dev/null; then
                local hook_cmd="bash ~/.claude/hooks/tts-hook.sh"
                if jq -e ".hooks.Stop[]?.hooks[]? | select(.command == \"$hook_cmd\")" "$settings" &>/dev/null; then
                    local tmpf
                    tmpf=$(mktemp)
                    jq "(.hooks.Stop[]?.hooks) |= [.[]? | select(.command != \"$hook_cmd\")]" "$settings" > "$tmpf" \
                        && mv "$tmpf" "$settings"
                    ok "Removed TTS hook from settings.json"
                fi
            fi
        else
            info "Keeping Claude Code hooks"
        fi
    fi

    echo
    ok "Afterwords uninstalled"
    info "Voice profiles and server code remain in ${DIM}${REPO_DIR}${NC}"
    info "To reinstall: ${CYAN}bash setup.sh${NC}"
    echo
}

cmd_help() {
    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— local voice-cloning TTS server${NC}"
    rule
    echo
    echo -e "  ${BOLD}Usage:${NC} afterwords <command> [options]"
    echo
    echo -e "  ${BOLD}Commands:${NC}"
    echo -e "    ${CYAN}start${NC}       Start the TTS server"
    echo -e "    ${CYAN}stop${NC}        Stop the TTS server"
    echo -e "    ${CYAN}restart${NC}     Restart the TTS server"
    echo -e "    ${CYAN}status${NC}      Show server status and loaded voices"
    echo -e "    ${CYAN}logs${NC}        Tail the server log"
    echo -e "    ${CYAN}voices${NC}      List available voices"
    echo -e "    ${CYAN}clone${NC}       Clone a new voice from YouTube"
    echo -e "    ${CYAN}uninstall${NC}   Remove the service and optionally hooks"
    echo
    echo -e "  ${BOLD}Options:${NC}"
    echo -e "    ${DIM}voices --demo${NC}    Play a sample of each voice"
    echo -e "    ${DIM}clone URL NAME [START] [--yes]${NC}"
    echo
    echo -e "  ${BOLD}Examples:${NC}"
    echo -e "    ${DIM}afterwords start${NC}"
    echo -e "    ${DIM}afterwords voices --demo${NC}"
    echo -e "    ${DIM}afterwords clone \"https://youtube.com/watch?v=...\" gandalf 45${NC}"
    echo
}

# ── Main dispatch ────────────────────────────────────────────────

COMMAND="${1:-help}"
shift 2>/dev/null || true

case "$COMMAND" in
    start)     cmd_start "$@" ;;
    stop)      cmd_stop "$@" ;;
    restart)   cmd_restart "$@" ;;
    status)    cmd_status "$@" ;;
    logs)      cmd_logs "$@" ;;
    voices)    cmd_voices "$@" ;;
    clone)     cmd_clone "$@" ;;
    uninstall) cmd_uninstall "$@" ;;
    help|--help|-h)  cmd_help ;;
    *)
        fail "Unknown command: ${COMMAND}. Run ${CYAN}afterwords help${NC} for usage."
        ;;
esac
