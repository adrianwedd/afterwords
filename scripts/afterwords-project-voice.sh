#!/usr/bin/env bash
# afterwords-project-voice.sh — resolve a PER-PROJECT voice for the Hermes
# command-provider path, then hand off to the canonical command script.
#
# Why this exists: `text_to_speech` fills {voice} from
# tts.providers.afterwords.voice, which is per-PROFILE (global), and the
# canonical provider deliberately refuses to re-resolve .afterwords itself
# (tests/test_hermes_profile_voice.py pins that: re-resolution under a
# hardcoded `hermes` key made the vixen profile speak as seven-of-nine).
# So project scope is resolved HERE, once, and an explicit voice is always
# passed on — the canonical contract ("the serving profile's explicit voice
# or fail visibly") is unchanged.
#
# Resolution: <project>/.afterwords (agent key -> default: -> simple name)
#             -> the caller's configured voice.
# The global ~/.afterwords is deliberately NOT consulted here: it belongs to
# the default profile, and reading it would re-introduce the cross-profile
# bleed the canonical script was fixed to eliminate. The configured {voice}
# already carries the serving profile's global choice.
#
# Project dir: $AFTERWORDS_PROJECT_DIR, else the cwd of the session holding the
# live turn lease (read-only from ~/.hermes/state.db, $AFTERWORDS_STATE_DB to
# override), else $PWD. The DB step exists because Hermes runs this command
# from the profile dir with a scrubbed environment — $PWD is ~/.hermes and no
# session identity is passed — so the harness's own record is the only
# trustworthy "which project is this" signal on this surface.
#
# Usage:  afterwords-project-voice.sh <config_voice> <input_path> <output_path>
#         afterwords-project-voice.sh --print      # resolved voice, no synthesis
#
# Agent key:   $AFTERWORDS_AGENT, else the HERMES_HOME profile name
#              ("hermes" for the default profile).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANONICAL="${AFTERWORDS_COMMAND_SCRIPT:-$SCRIPT_DIR/afterwords-tts-command.sh}"
# bash 3.2 + `set -u`: never write "${VAR}/path" — it trips "unbound variable"
# even when VAR is set. Build the default with a $name form instead.
HOME_DIR="${HOME:-}"
STATE_DB="${AFTERWORDS_STATE_DB:-}"
# Recency window (seconds) for the "no live lease" fallback.
SESSION_CWD_WINDOW="${AFTERWORDS_SESSION_WINDOW:-3600}"
[ -n "$STATE_DB" ] || STATE_DB="$HOME_DIR/.hermes/state.db"

resolve_agent() {
    local agent="${AFTERWORDS_AGENT:-}"
    if [ -n "$agent" ]; then
        printf '%s' "$agent"
        return 0
    fi
    local home="${HERMES_HOME:-}"
    case "$home" in
        */profiles/*) printf '%s' "${home##*/}" ;;
        *) printf 'hermes' ;;
    esac
}

# cwd of the session that holds the live turn lease — the closest thing this
# surface has to "the project the operator is working in". Read-only; any
# failure (no sqlite3, no DB, changed schema) just yields an empty string.
live_session_cwd() {
    [ -f "$STATE_DB" ] || return 0
    command -v sqlite3 >/dev/null 2>&1 || return 0
    local cwd
    # 1. the live turn lease (exact while a turn is running)
    cwd=$(sqlite3 -readonly "$STATE_DB" "
        select s.cwd
          from session_turn_leases l
          join sessions s on s.id = l.conversation_id
         where l.expires_at > strftime('%s','now')
           and s.cwd is not null and s.cwd <> ''
         order by l.acquired_at desc
         limit 1
    " 2>/dev/null || true)
    if [ -n "$cwd" ]; then
        printf '%s' "$cwd"
        return 0
    fi
    # 2. the most recently active session, if recent (covers agent:end timing)
    sqlite3 -readonly "$STATE_DB" "
        select cwd from sessions
         where cwd is not null and cwd <> ''
           and last_activity_at > strftime('%s','now') - $SESSION_CWD_WINDOW
         order by last_activity_at desc
         limit 1
    " 2>/dev/null || true
}

# First project directory that actually carries a .afterwords file.
project_dir() {
    local candidate="${AFTERWORDS_PROJECT_DIR:-}"
    if [ -n "$candidate" ] && [ -f "$candidate/.afterwords" ]; then
        printf '%s' "$candidate"
        return 0
    fi
    candidate="$(live_session_cwd)"
    if [ -n "$candidate" ] && [ -f "$candidate/.afterwords" ]; then
        printf '%s' "$candidate"
        return 0
    fi
    if [ -f "$PWD/.afterwords" ]; then
        printf '%s' "$PWD"
        return 0
    fi
    return 0
}


# Same mapping semantics as the tested resolver in
# tests/test_afterwords_voice_mapping.py: last ':' on the line splits key/value,
# so both "default:data" and "default: data" work, and compound keys such as
# "feature-dev:code-reviewer" stay intact.
resolve_voice() {
    local file="$1"
    local agent="$2"
    local voice=""
    [ -f "$file" ] || return 0
    if grep -q ':' "$file" 2>/dev/null; then
        voice=$(awk -v agent="$agent" '
            function trim(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
            /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
            {
                pos = 0
                for (i = 1; i <= length($0); i++) {
                    if (substr($0, i, 1) == ":") pos = i
                }
                if (!pos) next
                key = trim(substr($0, 1, pos - 1))
                val = trim(substr($0, pos + 1))
                if (agent != "" && key == agent) { print val; found = 1; exit }
                if (key == "default" && fallback == "") fallback = val
            }
            END { if (!found && fallback != "") print fallback }
        ' "$file" 2>/dev/null)
    else
        voice=$(grep -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' "$file" 2>/dev/null | head -1 | tr -d '[:space:]' || true)
    fi
    printf '%s' "$voice"
}

if [ "${1:-}" = "--print" ]; then
    project="$(project_dir)"
    if [ -z "$project" ]; then
        printf '\n'
        exit 0
    fi
    resolve_voice "$project/.afterwords" "$(resolve_agent)"
    printf '\n'
    exit 0
fi

CONFIG_VOICE="${1:?Usage: afterwords-project-voice.sh <config_voice> <input_path> <output_path>}"
INPUT_PATH="${2:?Usage: afterwords-project-voice.sh <config_voice> <input_path> <output_path>}"
OUTPUT_PATH="${3:?Usage: afterwords-project-voice.sh <config_voice> <input_path> <output_path>}"

voice=""
project="$(project_dir)"
if [ -n "$project" ]; then
    voice="$(resolve_voice "$project/.afterwords" "$(resolve_agent)")"
fi
if [ -z "$voice" ]; then
    voice="$CONFIG_VOICE"
fi

if [ ! -f "$CANONICAL" ]; then
    printf 'afterwords-project-voice: canonical command script not found: %s\n' "$CANONICAL" >&2
    exit 1
fi

exec bash "$CANONICAL" "$INPUT_PATH" "$OUTPUT_PATH" "$voice"
