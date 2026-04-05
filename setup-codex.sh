#!/usr/bin/env bash
#
# Install Afterwords playback for the current Codex CLI session.
#
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; DIM='\033[2m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "  ${CYAN}▸${NC} $*"; }
ok()    { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "  ${RED}✗${NC} $*"; exit 1; }
rule()  { echo -e "${DIM}  ─────────────────────────────────────────${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo
echo -e "  ${BOLD}afterwords${NC}  ${DIM}— Codex CLI session setup${NC}"
rule
echo

[ -n "${CODEX_THREAD_ID:-}" ] || fail "CODEX_THREAD_ID is not set. Run this from inside the Codex CLI session you want to speak."
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v rg >/dev/null 2>&1 || fail "rg is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

chmod +x "${SCRIPT_DIR}/.claude/hooks/codex-tts-hook.sh"
chmod +x "${SCRIPT_DIR}/.claude/hooks/codex-tts-worker.sh"
chmod +x "${SCRIPT_DIR}/.claude/hooks/codex-tts-watch.sh"
chmod +x "${SCRIPT_DIR}/afterwords.sh"
ok "Codex hook scripts are ready"

if ! curl -s --max-time 2 "http://127.0.0.1:7860/health" >/dev/null 2>&1; then
    info "Starting Afterwords server..."
    bash "${SCRIPT_DIR}/afterwords.sh" start || fail "Server failed to start"
else
    ok "Afterwords server is reachable"
fi

info "Starting Codex watcher for thread ${CODEX_THREAD_ID}..."
bash "${SCRIPT_DIR}/afterwords.sh" codex-hook start

echo
ok "Codex CLI speech is installed for this session"
info "Check watcher status with: ${CYAN}bash afterwords.sh codex-hook status${NC}"
info "Stop it with: ${CYAN}bash afterwords.sh codex-hook stop${NC}"
echo
