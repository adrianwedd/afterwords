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
AFTERWORDS_SERVER_CONFIG="$HOME/.afterwords-server"
CODEX_WATCH_PID="/tmp/codex-tts-watch.pid"
CODEX_WATCH_LOG="/tmp/codex-tts-watch.log"
CODEX_WATCH_SCRIPT_REL=".claude/hooks/codex-tts-watch.sh"
MUTE_FILE="/tmp/afterwords-muted"

# Resolve the repo directory (where server.py lives)
# Allow test override of REPO_DIR
if [ -n "${AFTERWORDS_REPO_DIR:-}" ]; then
    REPO_DIR="$AFTERWORDS_REPO_DIR"
elif [ -L "${BASH_SOURCE[0]}" ]; then
    REAL_SCRIPT="$(readlink "${BASH_SOURCE[0]}")"
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

# True if 1.7B is enabled in the server config file
with_17b_enabled() {
    [ -f "$AFTERWORDS_SERVER_CONFIG" ] && grep -q "^WITH_17B=true" "$AFTERWORDS_SERVER_CONFIG"
}

# Write (or rewrite) the launchd plist, honouring current server config
write_plist() {
    local venv_python="${REPO_DIR}/.venv/bin/python3"
    {
        cat <<PLIST_HEAD
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${venv_python}</string>
        <string>${REPO_DIR}/server.py</string>
PLIST_HEAD
        with_17b_enabled && echo "        <string>--with-1.7b</string>"
        cat <<PLIST_TAIL
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key>
    <string>/tmp/claude-tts-server.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/claude-tts-server.log</string>
</dict>
</plist>
PLIST_TAIL
    } > "$PLIST_PATH"
}

# Find PID listening on the TTS port (works whether launchd or manual)
server_pid() {
    lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null | head -1
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

    local pid
    pid=$(server_pid)

    local with17b_label=""
    with_17b_enabled && with17b_label="  ${DIM}1.7B: enabled${NC}"

    if [ -n "$pid" ]; then
        local mgmt="manual"
        plist_loaded && mgmt="launchd (auto-start)"
        local mute_label=""
        [ -f "$MUTE_FILE" ] && mute_label="  ${YELLOW}⏸ muted${NC}"
        echo -e "  ${GREEN}●${NC} ${BOLD}running${NC}  ${DIM}PID ${pid}  port ${PORT}  ${mgmt}${NC}${with17b_label}${mute_label}"
    else
        echo -e "  ${RED}●${NC} ${BOLD}stopped${NC}${with17b_label}"
        echo
        if plist_exists; then
            echo -e "  ${CYAN}afterwords start${NC}  to start the server"
        else
            echo -e "  ${CYAN}bash setup.sh${NC}  to install"
        fi
        echo
        return 0
    fi

    echo

    if health_check; then
        echo "$HEALTH_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ready    = data.get('ready', False)
model    = data.get('model', '?')
defvoice = data.get('default_voice', '?')
voices   = data.get('voices', [])
lb       = data.get('loaded_backends', {})

G  = '\033[0;32m'; Y = '\033[0;33m'; C = '\033[0;36m'
D  = '\033[2m';    B = '\033[1m';    R = '\033[0m'

state_mark = f'{G}✓{R}' if ready else f'{Y}⚑{R}'
state_word  = 'ready' if ready else 'warming up'
print(f'  {state_mark} {B}{state_word}{R}  {D}{model}  {len(voices)} voice(s){R}')
print()

# Backends
if lb:
    for name in sorted(lb):
        b = lb[name]
        mark = f'{G}✓{R}' if b.get('loaded') else f'{Y}⚠{R}'
        vc   = b.get('voice_count', 0)
        sr   = b.get('sample_rate', '?')
        print(f'  {mark}  {C}{name:<18}{R}  {D}{vc} voices  {sr} Hz{R}')
    print()

# Voices — compact list
if voices:
    print(f'  {B}voices{R}  {D}(default: {defvoice}){R}')
    col_w = max((len(v) for v in voices), default=20) + 2
    cols = max(1, 80 // col_w)
    padded = [f'{C}{v:<{col_w}}{R}' for v in voices]
    for i in range(0, len(padded), cols):
        print('    ' + ''.join(padded[i:i+cols]))
print()
print(f'  {D}afterwords logs  —  /tmp/claude-tts-server.log{R}')
" 2>/dev/null || warn "Server running but /health not yet responding (warming up)"
    fi
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
    local response url="http://localhost:7860/reload"
    if [ "${1:-}" = "--prune" ]; then
        url="${url}?prune=true"
    fi
    if ! response=$(curl -s -X POST "$url"); then
        fail "Server not responding on localhost:7860"
    fi
    if command -v jq >/dev/null 2>&1; then
        echo "$response" | jq .
    else
        echo "$response"
    fi
}

cmd_audit() {
    local use_archive=false
    for arg in "$@"; do
        [ "$arg" = "--archive" ] && use_archive=true
    done

    if $use_archive; then
        local script="${REPO_DIR}/scripts/audit-archive.py"
        [ -f "$script" ] || fail "audit-archive.py not found in ${REPO_DIR}/scripts/"
        [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
        # shellcheck disable=SC1091
        source "${REPO_DIR}/.venv/bin/activate"
        # Strip --archive before forwarding; remaining flags pass through to audit-archive.py
        local args=()
        for arg in "$@"; do
            [ "$arg" != "--archive" ] && args+=("$arg")
        done
        python3 "$script" ${args[@]+"${args[@]}"}
    else
        local script="${REPO_DIR}/scripts/audit-voice-transcripts.py"
        [ -f "$script" ] || fail "audit-voice-transcripts.py not found in ${REPO_DIR}/scripts/"
        [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
        # shellcheck disable=SC1091
        source "${REPO_DIR}/.venv/bin/activate"
        python3 "$script" "$@"
    fi
}

cmd_transcribe() {
    local script="${REPO_DIR}/scripts/transcribe.py"
    [ -f "$script" ] || fail "transcribe.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_qa() {
    local script="${REPO_DIR}/scripts/qa-voices.py"
    [ -f "$script" ] || fail "qa-voices.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_trim() {
    local script="${REPO_DIR}/scripts/trim-silence-gaps.py"
    [ -f "$script" ] || fail "trim-silence-gaps.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_compare() {
    local script="${REPO_DIR}/scripts/compare-transcription.py"
    [ -f "$script" ] || fail "compare-transcription.py not found in ${REPO_DIR}/scripts/"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"
    python3 "$script" "$@"
}

cmd_refine() {
    local voice="" quick=false yes=false
    for arg in "$@"; do
        case "$arg" in
            --quick) quick=true ;;
            --yes)   yes=true ;;
            --*)     ;;                       # ignore other flags
            *)       [ -z "$voice" ] && voice="$arg" ;;
        esac
    done

    [ -z "$voice" ] && fail "Usage: afterwords refine <voice> [--quick] [--yes]"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"

    local qa_script="${REPO_DIR}/scripts/qa-voices.py"
    local compare_script="${REPO_DIR}/scripts/compare-transcription.py"
    local trim_script="${REPO_DIR}/scripts/trim-silence-gaps.py"
    local ref_wav="${REPO_DIR}/voices/${voice}-ref.wav"

    [ -f "$qa_script" ]      || fail "qa-voices.py not found"
    [ -f "$compare_script" ] || fail "compare-transcription.py not found"
    [ -f "$trim_script" ]    || fail "trim-silence-gaps.py not found"
    [ -f "$ref_wav" ]        || fail "Reference WAV not found: ${ref_wav}"

    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"

    # Hard-error abort helper: prints ✗ and returns 2 (NOT fail/exit 1).
    _refine_abort() { echo -e "  ${RED}✗${NC} $*" >&2; return 2; }

    info "Refining ${voice}..."
    echo

    # Step 1/4 — QA ref WER
    info "Step 1/4  qa --voice ${voice} --ref-only"
    python3 "$qa_script" --voice "$voice" --ref-only --json
    local qa1_exit=$?
    [ $qa1_exit -eq 2 ] && { _refine_abort "qa hard-errored (exit 2) — aborting refine"; return 2; }
    [ $qa1_exit -eq 1 ] && warn "WER above threshold — continuing"

    if ! $quick; then
        # Step 2/4 — Compare transcription models (diagnostic-only; exit 1 or 2 → continue)
        info "Step 2/4  compare voices/${voice}-ref.wav"
        python3 "$compare_script" "$ref_wav" --json
        local compare_exit=$?
        [ $compare_exit -ne 0 ] && warn "compare exited ${compare_exit} — continuing to step 3"

        # Step 3/4 — Trim silence gaps (dry run, then ask)
        info "Step 3/4  trim --voice ${voice} (dry run)"
        local trim_json
        trim_json=$(python3 "$trim_script" --voice "$voice" --json 2>/dev/null)
        local trim_exit=$?
        [ $trim_exit -eq 2 ] && { _refine_abort "trim hard-errored (exit 2) — aborting refine"; return 2; }

        local gap_count=0
        gap_count=$(echo "$trim_json" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(sum(v.get('gap_count', 0) for v in d.get('voices', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

        if [ "$gap_count" -eq 0 ]; then
            ok "No silence gaps found"
        else
            warn "Found ${gap_count} silence gap(s) in '${voice}'"
            local do_trim="n"
            $yes && do_trim="y"
            if [ -t 0 ] && ! $yes; then
                echo -en "  ${BOLD}Trim and rewrite reference? [y/N]${NC} "
                read -r do_trim
            fi
            if [[ "${do_trim:-n}" =~ ^[Yy]$ ]]; then
                info "Applying trim..."
                python3 "$trim_script" --voice "$voice" --apply
            fi
        fi
    else
        info "Step 2/4  compare  (skipped — --quick)"
        info "Step 3/4  trim     (skipped — --quick)"
    fi

    # Step 4/4 — Re-measure WER
    info "Step 4/4  qa --voice ${voice} --ref-only (final)"
    python3 "$qa_script" --voice "$voice" --ref-only --json
    local qa2_exit=$?
    [ $qa2_exit -eq 2 ] && { _refine_abort "qa hard-errored on final check (exit 2)"; return 2; }

    echo
    if [ $qa2_exit -eq 1 ]; then
        warn "Final WER still above threshold"
        return 1
    fi
    ok "Refine complete"
    return 0
}

cmd_update() {
    local check_only=false yes=false
    for arg in "$@"; do
        case "$arg" in
            --check) check_only=true ;;
            --yes)   yes=true ;;
        esac
    done

    git -C "$REPO_DIR" rev-parse --git-dir &>/dev/null \
        || fail "Not a git working tree — cannot self-update (tarball installs must update manually)"
    [ -d "${REPO_DIR}/.venv" ] || fail "venv missing — run setup.sh first"
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.venv/bin/activate"

    info "Fetching latest commits..."
    git -C "$REPO_DIR" fetch origin 2>&1 \
        || warn "git fetch failed — check your network. Continuing with local state."

    # Resolve upstream robustly: prefer the tracking branch, else origin/<branch>.
    local upstream branch
    upstream=$(git -C "$REPO_DIR" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)
    if [ -z "$upstream" ]; then
        branch=$(git -C "$REPO_DIR" symbolic-ref --short HEAD 2>/dev/null)
        upstream="origin/${branch}"
    fi

    local behind
    behind=$(git -C "$REPO_DIR" rev-list "HEAD..${upstream}" --count 2>/dev/null || echo "0")
    info "${behind} commit(s) available upstream (${upstream})"

    if $check_only; then
        ok "--check complete (no working-tree, package, or server changes made)"
        return 0
    fi
    if [ "$behind" -eq 0 ]; then
        ok "Already up to date"
        return 0
    fi

    # Refuse to pull over a dirty tree unless confirmed (TTY) or --yes.
    local dirty
    dirty=$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)
    if [ -n "$dirty" ]; then
        local dirty_voices
        dirty_voices=$(git -C "$REPO_DIR" status --porcelain -- voices/ 2>/dev/null)
        if [ -n "$dirty_voices" ]; then
            warn "Local edits to voices/ may be overwritten by git pull:"
            echo "$dirty_voices" | sed 's/^/    /'
        fi
        warn "Working tree has uncommitted changes:"
        echo "$dirty" | sed 's/^/    /'
        if $yes; then
            warn "--yes given — proceeding over dirty tree"
        elif [ -t 0 ]; then
            echo -en "  ${BOLD}Continue anyway? [y/N]${NC} "
            local confirm; read -r confirm
            [[ "${confirm:-n}" =~ ^[Yy]$ ]] || { info "Cancelled"; return 1; }
        else
            fail "Dirty working tree and no TTY — re-run with --yes to override"
        fi
    fi

    local before_ref after_ref
    before_ref=$(git -C "$REPO_DIR" rev-parse --short HEAD)

    info "Pulling..."
    git -C "$REPO_DIR" pull --ff-only 2>&1 \
        || fail "git pull --ff-only failed — your branch may have diverged. Merge manually."
    after_ref=$(git -C "$REPO_DIR" rev-parse --short HEAD)

    info "Installing packages..."
    python3 -m pip install --quiet -r "${REPO_DIR}/requirements.txt" \
        || warn "pip install failed — run manually: python3 -m pip install -r requirements.txt"
    if [ -f "${REPO_DIR}/requirements-clone.txt" ]; then
        python3 -m pip install --quiet -r "${REPO_DIR}/requirements-clone.txt" \
            || warn "pip install (clone deps) failed — run manually: python3 -m pip install -r requirements-clone.txt"
    fi

    local changed_files
    changed_files=$(git -C "$REPO_DIR" diff --name-only "${before_ref}..${after_ref}" 2>/dev/null)

    # Reload voices if running (subshell so cmd_reload's `fail` can't abort update).
    if [ -n "$(server_pid)" ]; then
        info "Reloading voices (best-effort; /reload needs --allow-clone)..."
        ( cmd_reload ) || warn "reload failed — server may not be started with --allow-clone"
    fi

    # Reload is add-only and won't reimport changed code/deps — recommend a restart.
    if echo "$changed_files" | grep -qE '^(server\.py|requirements.*\.txt|backends/)'; then
        warn "Server code or dependencies changed — run ${CYAN}afterwords restart${NC} to apply."
    fi
    if echo "$changed_files" | grep -qE '^(afterwords\.sh|setup\.sh)$'; then
        warn "Setup files changed — run ${CYAN}bash setup.sh${NC} if behaviour feels wrong."
    fi

    ok "Updated ${before_ref} → ${after_ref}"
    echo "$changed_files" | sed 's/^/    /' | head -20
    return 0
}

cmd_clone() {
    local quick=false yes=false
    # Mirror clone-voice.sh: drop flags, take the 2nd positional as the voice name.
    local positional=() skip_next=false all=("$@") i arg
    for ((i=0; i<${#all[@]}; i++)); do
        arg="${all[i]}"
        if $skip_next; then skip_next=false; continue; fi
        case "$arg" in
            --quick)        quick=true ;;
            --yes)          yes=true ;;
            --backend)      skip_next=true ;;
            --backend=*|--all-backends|--check-source) ;;
            --*)            ;;
            *)              positional+=("$arg") ;;
        esac
    done
    local voice_name="${positional[1]:-}"
    voice_name=$(echo "${voice_name}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g')

    [ -f "$REPO_DIR/clone-voice.sh" ] || fail "clone-voice.sh not found in ${REPO_DIR}"
    bash "$REPO_DIR/clone-voice.sh" "$@"
    local clone_exit=$?
    [ $clone_exit -ne 0 ] && return $clone_exit

    if [ -n "$voice_name" ]; then
        echo
        local refine_args=("$voice_name")
        $quick && refine_args+=(--quick)
        $yes && refine_args+=(--yes)
        cmd_refine "${refine_args[@]}"
        local refine_exit=$?
        if [ $refine_exit -eq 2 ]; then
            warn "refine hard-errored (exit 2) — clone succeeded but QA could not run."
            info "Diagnose with: ${CYAN}afterwords refine ${voice_name}${NC}"
        elif [ $refine_exit -eq 1 ]; then
            warn "Refine finished with warnings — review the WER above."
        fi
    else
        echo
        info "Voice cloned. Run ${CYAN}afterwords refine <name>${NC} to verify quality."
    fi

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

cmd_configure() {
    local flag="${1:-}"
    case "$flag" in
        --with-1.7b)
            # Write config, regenerate plist, reload launchd
            if [ -f "$AFTERWORDS_SERVER_CONFIG" ] && grep -q "^WITH_17B=" "$AFTERWORDS_SERVER_CONFIG"; then
                sed -i '' "s|^WITH_17B=.*|WITH_17B=true|" "$AFTERWORDS_SERVER_CONFIG"
            else
                echo "WITH_17B=true" >> "$AFTERWORDS_SERVER_CONFIG"
            fi
            if plist_exists; then
                write_plist
                plist_loaded && { launchctl unload "$PLIST_PATH" 2>/dev/null; launchctl load "$PLIST_PATH"; }
                ok "1.7B model enabled — run ${CYAN}afterwords restart${NC} to apply"
            else
                ok "1.7B model enabled — run ${CYAN}bash setup.sh${NC} to install the service"
            fi
            ;;
        --no-1.7b)
            if [ -f "$AFTERWORDS_SERVER_CONFIG" ]; then
                sed -i '' "/^WITH_17B=/d" "$AFTERWORDS_SERVER_CONFIG"
            fi
            if plist_exists; then
                write_plist
                plist_loaded && { launchctl unload "$PLIST_PATH" 2>/dev/null; launchctl load "$PLIST_PATH"; }
                ok "1.7B model disabled — run ${CYAN}afterwords restart${NC} to apply"
            else
                ok "1.7B model disabled"
            fi
            ;;
        "")
            echo
            echo -e "  ${BOLD}afterwords configure${NC}  ${DIM}— server settings${NC}"
            rule
            echo
            if with_17b_enabled; then
                echo -e "  1.7B model  ${GREEN}enabled${NC}  ${DIM}(Qwen3-1.7B loads alongside 0.6B)${NC}"
            else
                echo -e "  1.7B model  ${DIM}disabled (default — 0.6B only)${NC}"
            fi
            echo
            echo -e "  ${DIM}afterwords configure --with-1.7b  # enable Qwen3-1.7B (higher fidelity)${NC}"
            echo -e "  ${DIM}afterwords configure --no-1.7b   # revert to 0.6B only${NC}"
            echo
            ;;
        *)
            fail "Unknown option: ${flag}. Use --with-1.7b or --no-1.7b"
            ;;
    esac
}

cmd_mute() {
    if [ -f "$MUTE_FILE" ]; then
        rm -f "$MUTE_FILE"
        ok "Unmuted — playback resumed"
    else
        touch "$MUTE_FILE"
        pkill -x afplay 2>/dev/null || true
        ok "Muted — synthesis continues, playback paused"
        info "Run ${CYAN}afterwords mute${NC} again to unmute"
    fi
}

cmd_help() {
    echo
    echo -e "  ${BOLD}afterwords${NC}  ${DIM}— local voice-cloning TTS for Apple Silicon${NC}"
    rule
    echo
    echo -e "  ${BOLD}Server${NC}"
    echo -e "    ${CYAN}start${NC}             Start the TTS server (via launchd)"
    echo -e "    ${CYAN}stop${NC}              Stop the server"
    echo -e "    ${CYAN}restart${NC}           Restart"
    echo -e "    ${CYAN}status${NC}            Server state, loaded voices, backends"
    echo -e "    ${CYAN}logs${NC}              Tail the server log"
    echo
    echo -e "  ${BOLD}Voices${NC}"
    echo -e "    ${CYAN}voices${NC}            List cloned voices (--demo to play samples, --cloud for cloud voices)"
    echo -e "    ${CYAN}clone URL NAME${NC}    Clone from YouTube URL or local file (--quick for fast refine)"
    echo -e "    ${CYAN}reload${NC}            Reload voices without restart (--prune to evict deleted)"
    echo
    echo -e "  ${BOLD}Analysis${NC}"
    echo -e "    ${CYAN}transcribe <audio>${NC}  Word-level timestamps (--backend parakeet|faster-whisper)"
    echo -e "    ${CYAN}qa${NC}                 Ref WER for all voices (--voice NAME, --synth, --json)"
    echo -e "    ${CYAN}trim${NC}               Remove silence gaps from refs (--apply to write, --json)"
    echo -e "    ${CYAN}compare <audio>${NC}    faster-whisper vs parakeet WER comparison (--json)"
    echo -e "    ${CYAN}refine <voice>${NC}     Full QA cycle: qa → compare → trim → re-qa (--quick to skip compare/trim)"
    echo -e "    ${CYAN}audit${NC}              Voice profile drift check (--archive for TTS archive pairs)"
    echo
    echo -e "  ${BOLD}Cloud${NC}"
    echo -e "    ${CYAN}push NAME${NC}         Push a voice (+ family variants) to the cloud"
    echo -e "    ${CYAN}pull ID${NC}           Pull a cloud voice to local voices/"
    echo -e "    ${CYAN}setup-cloud${NC}       Configure API key and cloud URL"
    echo
    echo -e "  ${BOLD}Integrations${NC}"
    echo -e "    ${CYAN}mute${NC}              Toggle playback on/off (synthesis and archiving continue)"
    echo -e "    ${CYAN}codex-hook start${NC}  Speak Codex CLI responses (run inside Codex)"
    echo -e "    ${CYAN}codex-hook stop${NC}   Stop the Codex watcher"
    echo
    echo -e "  ${BOLD}Setup${NC}"
    echo -e "    ${CYAN}configure${NC}         Show or change server settings (e.g. --with-1.7b)"
    echo -e "    ${CYAN}update${NC}            Pull latest commits, reinstall packages, reload voices"
    echo -e "    ${CYAN}uninstall${NC}         Remove service and optionally hooks"
    echo
    echo -e "  ${DIM}Examples:${NC}"
    echo -e "  ${DIM}  afterwords clone \"https://youtube.com/watch?v=xyz\" gandalf 45${NC}"
    echo -e "  ${DIM}  afterwords clone voices/clip.wav myvoice --yes${NC}"
    echo -e "  ${DIM}  afterwords refine gandalf${NC}"
    echo -e "  ${DIM}  afterwords qa --json | python3 -c \"import json,sys; print([v for v in json.load(sys.stdin)['voices'] if v['ref_wer']>0.15])\"${NC}"
    echo -e "  ${DIM}  afterwords compare voices/gandalf-ref.wav --json${NC}"
    echo -e "  ${DIM}  afterwords update --check${NC}"
    echo -e "  ${DIM}  afterwords push picard${NC}"
    echo -e "  ${DIM}  echo \"snape\" > .afterwords  # per-project voice override${NC}"
    echo
}

# ── Main dispatch ────────────────────────────────────────────────

# --ai flag: print AI guide and exit (detected before COMMAND dispatch)
if [ "${1:-}" = "--ai" ]; then
    AI_GUIDE="${REPO_DIR}/docs/ai-guide.md"
    if [ -f "$AI_GUIDE" ]; then
        cat "$AI_GUIDE"
    else
        fail "docs/ai-guide.md not found in ${REPO_DIR}"
    fi
    exit 0
fi

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
    transcribe)  cmd_transcribe "$@" ;;
    qa)          cmd_qa "$@" ;;
    trim)        cmd_trim "$@" ;;
    compare)     cmd_compare "$@" ;;
    refine)      cmd_refine "$@" ;;
    update)      cmd_update "$@" ;;
    mute)        cmd_mute "$@" ;;
    codex-hook)  cmd_codex_hook "$@" ;;
    configure)   cmd_configure "$@" ;;
    uninstall)   cmd_uninstall "$@" ;;
    help|--help|-h)  cmd_help ;;
    *)
        fail "Unknown command: ${COMMAND}. Run ${CYAN}afterwords help${NC} for usage."
        ;;
esac
