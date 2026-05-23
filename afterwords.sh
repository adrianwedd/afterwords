#!/usr/bin/env bash
#
# afterwords — CLI for the local voice-cloning TTS server
#
# Usage: afterwords <command> [options]
#
# Commands:
#   start        Start the TTS server (via launchd)
#   stop         Stop the TTS server
#   restart      Restart the TTS server
#   status       Show server status, loaded voices, and health
#   logs         Tail the server log
#   voices       List available voices (--demo, --cloud)
#   clone        Clone a new voice from YouTube
#   push         Push a voice (and family variants) to the cloud
#   pull         Pull a cloud voice to local voices/
#   setup-cloud  Configure cloud API key and URL
#   codex-hook   Manage the repo-local Codex CLI watcher
#   uninstall    Remove the launchd service and optionally Claude Code hooks
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
CLOUD_CONFIG_FILE="$HOME/.afterwords-cloud"
CLOUD_DEFAULT_URL="https://afterwords-api.adrianwedd.workers.dev"
CODEX_WATCH_PID="/tmp/codex-tts-watch.pid"
CODEX_WATCH_LOG="/tmp/codex-tts-watch.log"
CODEX_WATCH_SCRIPT_REL=".claude/hooks/codex-tts-watch.sh"

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
        echo
        info "Backends:"
        echo "$HEALTH_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
lb = data.get('loaded_backends', {})
if not lb:
    print('    \033[2m(loaded_backends not reported)\033[0m')
else:
    for name in sorted(lb.keys()):
        b = lb[name]
        loaded = b.get('loaded', False)
        vc = b.get('voice_count', 0)
        sr = b.get('sample_rate', '?')
        mark = '\033[0;32m✓\033[0m' if loaded else '\033[0;33m⚠\033[0m'
        print(f'    {mark} \033[0;36m{name:<15}\033[0m \033[2m{vc} voices, {sr} Hz\033[0m')
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

# ── Cloud config helpers ──────────────────────────────────────────

load_cloud_config() {
    CLOUD_API_KEY=""
    CLOUD_URL="$CLOUD_DEFAULT_URL"
    if [ -f "$CLOUD_CONFIG_FILE" ]; then
        local parsed
        parsed=$(python3 -c "
import sys
data = {}
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        data[k.strip()] = v.strip()
print(data.get('api_key', ''))
print(data.get('cloud_url', ''))
" "$CLOUD_CONFIG_FILE" 2>/dev/null)
        CLOUD_API_KEY="$(echo "$parsed" | sed -n '1p')"
        local file_url
        file_url="$(echo "$parsed" | sed -n '2p')"
        [ -n "$file_url" ] && CLOUD_URL="$file_url"
    fi
    CLOUD_API_KEY="${AFTERWORDS_API_KEY:-$CLOUD_API_KEY}"
    CLOUD_URL="${AFTERWORDS_CLOUD_URL:-$CLOUD_URL}"
}

require_cloud_config() {
    load_cloud_config
    if [ -z "$CLOUD_API_KEY" ]; then
        fail "No API key configured. Run: ${CYAN}afterwords setup-cloud${NC}"
    fi
}

cmd_voices() {
    local demo=false cloud=false
    for arg in "$@"; do
        case "$arg" in
            --demo)  demo=true ;;
            --cloud) cloud=true ;;
        esac
    done

    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— voices${NC}"
    rule
    echo

    export REPO_DIR

    # Try live server first
    if health_check; then
        local default_voice
        default_voice=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_voice', ''))")

        echo "$HEALTH_JSON" | python3 -c "
import sys, json, os, glob
data = json.load(sys.stdin)
default = data.get('default_voice', '')
voices_dir = os.path.join(os.environ.get('REPO_DIR', '.'), 'voices')
# Map each voice name → backend by reading voices/*.json (fall back to qwen3-0.6b default)
backends_by_voice = {}
for jf in glob.glob(os.path.join(voices_dir, '*.json')):
    try:
        with open(jf) as f:
            p = json.load(f)
        backends_by_voice[p.get('name') or os.path.basename(jf)[:-5]] = p.get('backend', 'qwen3-0.6b')
    except Exception:
        pass
for v in data.get('voices', []):
    b = backends_by_voice.get(v, 'qwen3-0.6b')
    marker = ' (default)' if v == default else ''
    print(f'    \033[0;36m{v:<30}\033[0m \033[2m{b}{marker}\033[0m')
"
    else
        # Fallback: read voice profiles from disk
        info "Server not running — reading from disk"
        echo
        local count=0
        for f in "$REPO_DIR"/voices/*.json; do
            [ -f "$f" ] || continue
            local info_line
            info_line=$(python3 -c "import json,sys; p=json.load(open(sys.argv[1])); print(f\"{p.get('name', '?')}|{p.get('backend', 'qwen3-0.6b')}\")" "$f" 2>/dev/null || echo "$(basename "$f" .json)|?")
            local name="${info_line%|*}"
            local backend="${info_line##*|}"
            printf "    \033[0;36m%-30s\033[0m \033[2m%s\033[0m\n" "$name" "$backend"
            count=$((count + 1))
        done
        if [ "$count" -eq 0 ]; then
            warn "No voice profiles found in voices/"
        fi
    fi

    echo

    if $cloud; then
        load_cloud_config
        if [ -z "$CLOUD_API_KEY" ]; then
            warn "No API key configured — run: ${CYAN}afterwords setup-cloud${NC}"
        else
            echo -e "  ${DIM}── cloud ─────────────────────────────────${NC}"
            echo
            local full_response http_code cloud_body
            full_response=$(curl -s -w "\n%{http_code}" --max-time 15 \
                -H "Authorization: Bearer $CLOUD_API_KEY" \
                "$CLOUD_URL/v1/voices" 2>/dev/null)
            http_code=$(printf '%s' "$full_response" | tail -1)
            cloud_body=$(printf '%s' "$full_response" | head -n -1)
            if [ "$http_code" = "200" ]; then
                printf '%s' "$cloud_body" | python3 -c "
import sys, json
voices = json.load(sys.stdin)
if not voices:
    print('    \033[2mNo cloud voices — push one with: afterwords push <name>\033[0m')
else:
    for v in voices:
        name = v.get('name', '?')
        backend = v.get('backend', '?')
        vid = v.get('voice_id', '')[:8]
        print(f'    \033[0;36m{name:<30}\033[0m \033[2m{backend}  {vid}...\033[0m')
"
            else
                warn "Could not fetch cloud voices (HTTP ${http_code})"
            fi
            echo
        fi
    fi

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

cmd_reload() {
    local response
    if ! response=$(curl -s -X POST http://localhost:7860/reload); then
        fail "Server not responding on localhost:7860"
    fi
    if command -v jq >/dev/null 2>&1; then
        echo "$response" | jq .
    else
        echo "$response"
    fi
}

cmd_audit() {
    local script="${REPO_DIR}/scripts/audit-voice-transcripts.py"
    if [ ! -f "$script" ]; then
        fail "audit-voice-transcripts.py not found"
    fi
    if [ ! -d "${REPO_DIR}/.venv" ]; then
        fail "venv missing — run setup.sh first"
    fi
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
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

cmd_codex_hook() {
    local subcommand="${1:-status}"
    local watcher="${REPO_DIR}/${CODEX_WATCH_SCRIPT_REL}"
    local pid=""
    local diagnose=""

    codex_watch_log_tail() {
        if [ -s "$CODEX_WATCH_LOG" ]; then
            info "Recent watcher log:"
            tail -20 "$CODEX_WATCH_LOG" | sed 's/^/    /'
        else
            warn "Watcher log is empty: ${CODEX_WATCH_LOG}"
        fi
    }

    case "$subcommand" in
        start)
            diagnose="${2:-}"
            [ -f "$watcher" ] || fail "Watcher script not found at ${watcher}"
            if [ "$diagnose" = "--diagnose" ]; then
                CODEX_THREAD_ID="${CODEX_THREAD_ID:-}" PROJECT_DIR="$REPO_DIR" CODEX_WATCH_LOG="$CODEX_WATCH_LOG" \
                    bash "$watcher" --diagnose
                return $?
            fi
            [ -z "$diagnose" ] || fail "Unknown codex-hook start option: ${diagnose}. Use --diagnose."
            [ -n "${CODEX_THREAD_ID:-}" ] || fail "CODEX_THREAD_ID is not set. Run inside Codex CLI or export it first."

            if [ -f "$CODEX_WATCH_PID" ]; then
                pid=$(cat "$CODEX_WATCH_PID" 2>/dev/null)
                if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                    ok "Codex watcher already running (PID ${pid})"
                    info "Thread: ${DIM}${CODEX_THREAD_ID}${NC}"
                    info "Log: ${DIM}${CODEX_WATCH_LOG}${NC}"
                    return 0
                fi
                rm -f "$CODEX_WATCH_PID"
            fi

            : > "$CODEX_WATCH_LOG"
            nohup env CODEX_THREAD_ID="$CODEX_THREAD_ID" PROJECT_DIR="$REPO_DIR" CODEX_WATCH_LOG="$CODEX_WATCH_LOG" \
                bash "$watcher" >>"$CODEX_WATCH_LOG" 2>&1 &
            pid=$!
            sleep 0.5
            if ! kill -0 "$pid" 2>/dev/null; then
                wait "$pid" 2>/dev/null
                rm -f "$CODEX_WATCH_PID"
                codex_watch_log_tail
                fail "Codex watcher failed to start"
            fi
            echo "$pid" > "$CODEX_WATCH_PID"
            ok "Codex watcher started (PID ${pid})"
            info "Thread: ${DIM}${CODEX_THREAD_ID}${NC}"
            info "Log: ${DIM}${CODEX_WATCH_LOG}${NC}"
            ;;
        stop)
            if [ ! -f "$CODEX_WATCH_PID" ]; then
                ok "Codex watcher is not running"
                return 0
            fi

            pid=$(cat "$CODEX_WATCH_PID" 2>/dev/null)
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                sleep 1
                if kill -0 "$pid" 2>/dev/null; then
                    kill -9 "$pid" 2>/dev/null || true
                fi
                ok "Codex watcher stopped"
            else
                ok "Codex watcher was not running"
            fi
            rm -f "$CODEX_WATCH_PID"
            ;;
        status)
            if [ -f "$CODEX_WATCH_PID" ]; then
                pid=$(cat "$CODEX_WATCH_PID" 2>/dev/null)
                if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                    ok "Codex watcher running (PID ${pid})"
                else
                    warn "Codex watcher pid file exists but process is not running"
                    codex_watch_log_tail
                fi
            else
                warn "Codex watcher is not running"
                codex_watch_log_tail
            fi
            info "Log: ${DIM}${CODEX_WATCH_LOG}${NC}"
            ;;
        *)
            fail "Unknown codex-hook subcommand: ${subcommand}. Use start, stop, or status."
            ;;
    esac
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

cmd_setup_cloud() {
    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— setup cloud${NC}"
    rule
    echo

    load_cloud_config
    local current_key_display="(not set)"
    [ -n "$CLOUD_API_KEY" ] && current_key_display="${CLOUD_API_KEY:0:8}..."

    info "Current URL:     ${DIM}${CLOUD_URL}${NC}"
    info "Current API key: ${DIM}${current_key_display}${NC}"
    echo

    local new_key
    printf "  Enter API key (aw_...): "
    read -r new_key
    new_key="${new_key#"${new_key%%[! ]*}"}"  # ltrim
    new_key="${new_key%"${new_key##*[! ]}"}"  # rtrim
    [ -z "$new_key" ] && fail "API key cannot be empty"
    [[ "$new_key" == aw_* ]] || warn "Key doesn't start with 'aw_' — proceeding anyway"

    local new_url
    printf "  Cloud URL [%s]: " "$CLOUD_URL"
    read -r new_url
    new_url="${new_url#"${new_url%%[! ]*}"}"; new_url="${new_url%"${new_url##*[! ]}"}"
    [ -z "$new_url" ] && new_url="$CLOUD_URL"

    info "Testing connection..."
    local status_code
    status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -H "Authorization: Bearer $new_key" \
        "${new_url}/v1/voices" 2>/dev/null)
    case "$status_code" in
        200) ok "Connection successful" ;;
        401) fail "Invalid API key (HTTP 401)" ;;
        000) fail "Could not reach ${new_url} — check URL and network" ;;
        *)   warn "Unexpected status ${status_code} — saving config anyway" ;;
    esac

    printf 'api_key=%s\ncloud_url=%s\n' "$new_key" "$new_url" > "$CLOUD_CONFIG_FILE"
    chmod 600 "$CLOUD_CONFIG_FILE"
    ok "Config saved to ${DIM}${CLOUD_CONFIG_FILE}${NC}"
    echo
}

cmd_push() {
    local name="${1:-}"
    [ -z "$name" ] && fail "Usage: afterwords push <voice-name>"

    require_cloud_config

    local profile="$REPO_DIR/voices/${name}.json"
    [ -f "$profile" ] || fail "Voice profile not found: voices/${name}.json"

    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— push${NC}"
    rule
    echo

    # Collect all profiles to push (by family, or just this one if no family)
    local profiles_list
    profiles_list=$(VOICES_DIR="$REPO_DIR/voices" VOICE_NAME="$name" python3 -c "
import json, glob, os
name = os.environ['VOICE_NAME']
voices_dir = os.environ['VOICES_DIR']
base_file = os.path.join(voices_dir, name + '.json')
try:
    base = json.load(open(base_file))
except Exception as e:
    print(f'ERROR: {e}', flush=True)
    raise SystemExit(1)
family = base.get('family', '')
results = []
for f in sorted(glob.glob(os.path.join(voices_dir, '*.json'))):
    try:
        p = json.load(open(f))
        if family and p.get('family') == family:
            results.append(f)
        elif not family and p.get('name') == name:
            results.append(f)
    except Exception:
        pass
print('\n'.join(results))
" 2>/dev/null)
    [ -z "$profiles_list" ] && fail "No profiles found for voice: ${name}"

    local pushed=0 failed=0

    while IFS= read -r pfile; do
        [ -f "$pfile" ] || continue

        local pname pbackend pref_text pfamily pwav
        pname=$(    python3 -c "import json; p=json.load(open('$pfile')); print(p.get('name',''))" 2>/dev/null)
        pbackend=$( python3 -c "import json; p=json.load(open('$pfile')); print(p.get('backend','qwen3-0.6b'))" 2>/dev/null)
        pref_text=$(python3 -c "import json; p=json.load(open('$pfile')); print(p.get('reference_text') or '')" 2>/dev/null)
        pfamily=$(  python3 -c "import json; p=json.load(open('$pfile')); print(p.get('family') or '')" 2>/dev/null)
        pwav=$(     python3 -c "import json; p=json.load(open('$pfile')); print(p.get('reference_audio',''))" 2>/dev/null)

        local wav_path="$REPO_DIR/voices/$pwav"
        if [ ! -f "$wav_path" ]; then
            warn "Skipping ${pname}: reference audio not found (${pwav})"
            failed=$((failed + 1)); continue
        fi

        local form_args=(-F "name=$pname" -F "ref_audio=@${wav_path};type=audio/wav" -F "backend=$pbackend")
        [ -n "$pref_text" ] && form_args+=(-F "ref_text=$pref_text")
        [ -n "$pfamily"   ] && form_args+=(-F "family=$pfamily")

        local full_response http_code http_body
        full_response=$(curl -s -w "\n%{http_code}" --max-time 60 \
            -X POST "${CLOUD_URL}/v1/voices" \
            -H "Authorization: Bearer $CLOUD_API_KEY" \
            "${form_args[@]}" 2>/dev/null)
        http_code=$(printf '%s' "$full_response" | tail -1)
        http_body=$(printf '%s' "$full_response" | head -n -1)

        if [ "$http_code" = "201" ]; then
            local voice_id
            voice_id=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('voice_id',''))" "$http_body" 2>/dev/null)
            PFILE="$pfile" VOICE_ID="$voice_id" python3 -c "
import json, os
p = json.load(open(os.environ['PFILE']))
p['cloud_voice_id'] = os.environ['VOICE_ID']
with open(os.environ['PFILE'], 'w') as f:
    json.dump(p, f, indent=2)
    f.write('\n')
"
            ok "${CYAN}${pname}${NC}  ${DIM}${pbackend}${NC}  →  ${voice_id}"
            pushed=$((pushed + 1))
        else
            local err_msg
            err_msg=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('error','unknown'))" "$http_body" 2>/dev/null || echo "$http_body")
            warn "Failed to push ${pname}: ${err_msg} (HTTP ${http_code})"
            failed=$((failed + 1))
        fi
    done <<< "$profiles_list"

    echo
    if [ "$failed" -eq 0 ]; then
        ok "Pushed ${pushed} profile(s) to ${DIM}${CLOUD_URL}${NC}"
    else
        warn "Pushed ${pushed}, failed ${failed}"
        [ "$pushed" -eq 0 ] && exit 1
    fi
    echo
}

cmd_pull() {
    local voice_id="${1:-}"
    [ -z "$voice_id" ] && fail "Usage: afterwords pull <voice-id>"

    require_cloud_config

    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— pull${NC}"
    rule
    echo

    # Fetch voice metadata
    local full_response http_code meta_body
    full_response=$(curl -s -w "\n%{http_code}" --max-time 15 \
        -H "Authorization: Bearer $CLOUD_API_KEY" \
        "${CLOUD_URL}/v1/voices/${voice_id}" 2>/dev/null)
    http_code=$(printf '%s' "$full_response" | tail -1)
    meta_body=$(printf '%s' "$full_response" | head -n -1)

    if [ "$http_code" != "200" ]; then
        local err
        err=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('error','unknown'))" "$meta_body" 2>/dev/null || echo "$meta_body")
        fail "Could not fetch voice ${voice_id}: ${err} (HTTP ${http_code})"
    fi

    local vname
    vname=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('name',''))" "$meta_body" 2>/dev/null)
    [ -z "$vname" ] && fail "Voice metadata is missing 'name' field"

    local target_json="$REPO_DIR/voices/${vname}.json"
    local target_wav="$REPO_DIR/voices/${vname}-ref.wav"

    [ -f "$target_json" ] && warn "Overwriting existing profile: voices/${vname}.json"
    [ -f "$target_wav"  ] && warn "Overwriting existing audio:   voices/${vname}-ref.wav"

    # Download reference WAV
    local wav_status
    wav_status=$(curl -s -w "%{http_code}" --max-time 60 \
        -H "Authorization: Bearer $CLOUD_API_KEY" \
        "${CLOUD_URL}/v1/voices/${voice_id}/audio" \
        -o "$target_wav" 2>/dev/null)
    if [ "$wav_status" != "200" ]; then
        rm -f "$target_wav"
        fail "Could not download audio for ${voice_id} (HTTP ${wav_status})"
    fi

    # Write local JSON profile (pass data via env to avoid quoting issues)
    META_BODY="$meta_body" VOICE_ID="$voice_id" TARGET="$target_json" VNAME="$vname" python3 -c "
import json, os
meta = json.loads(os.environ['META_BODY'])
vname = os.environ['VNAME']
profile = {
    'name': vname,
    'reference_audio': f'{vname}-ref.wav',
    'reference_text': meta.get('ref_text') or '',
    'backend': meta.get('backend', 'qwen3-0.6b'),
    'cloud_voice_id': os.environ['VOICE_ID'],
}
if meta.get('lang') and meta['lang'] != 'en':
    profile['lang'] = meta['lang']
if meta.get('family'):
    profile['family'] = meta['family']
with open(os.environ['TARGET'], 'w') as f:
    json.dump(profile, f, indent=2)
    f.write('\n')
"

    local vbackend
    vbackend=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('backend','?'))" "$meta_body" 2>/dev/null)
    ok "Pulled ${CYAN}${vname}${NC}  ${DIM}${vbackend}${NC}"

    # Reload server if it's running
    if health_check 2>/dev/null; then
        info "Reloading server..."
        curl -s -X POST "http://localhost:${PORT}/reload" >/dev/null 2>&1 \
            && ok "Server reloaded — ${vname} is ready"
    else
        info "Server not running — voice available after next start"
    fi

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
    echo -e "    ${CYAN}reload${NC}      Reload voices from disk without restarting"
    echo -e "    ${CYAN}clone${NC}       Clone a new voice from YouTube"
    echo -e "    ${CYAN}push${NC}        Push a voice (and its family variants) to the cloud"
    echo -e "    ${CYAN}pull${NC}        Pull a cloud voice to local voices/"
    echo -e "    ${CYAN}setup-cloud${NC} Configure cloud API key and URL"
    echo -e "    ${CYAN}audit${NC}       Audit voice profiles for transcript-vs-audio drift"
    echo -e "    ${CYAN}codex-hook${NC}  Start or stop the Codex CLI watcher"
    echo -e "    ${CYAN}uninstall${NC}   Remove the service and optionally hooks"
    echo
    echo -e "  ${BOLD}Options:${NC}"
    echo -e "    ${DIM}voices --demo${NC}          Play a sample of each voice"
    echo -e "    ${DIM}voices --cloud${NC}         Show cloud voices after local list"
    echo -e "    ${DIM}clone URL NAME [START] [--yes]${NC}"
    echo -e "    ${DIM}codex-hook start [--diagnose]${NC}"
    echo
    echo -e "  ${BOLD}Examples:${NC}"
    echo -e "    ${DIM}afterwords start${NC}"
    echo -e "    ${DIM}afterwords voices --demo${NC}"
    echo -e "    ${DIM}afterwords voices --cloud${NC}"
    echo -e "    ${DIM}afterwords push picard${NC}"
    echo -e "    ${DIM}afterwords pull <voice-id>${NC}"
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
    reload)      cmd_reload "$@" ;;
    clone)       cmd_clone "$@" ;;
    push)        cmd_push "$@" ;;
    pull)        cmd_pull "$@" ;;
    setup-cloud) cmd_setup_cloud "$@" ;;
    audit)       cmd_audit "$@" ;;
    codex-hook)  cmd_codex_hook "$@" ;;
    uninstall)   cmd_uninstall "$@" ;;
    help|--help|-h)  cmd_help ;;
    *)
        fail "Unknown command: ${COMMAND}. Run ${CYAN}afterwords help${NC} for usage."
        ;;
esac
