#!/usr/bin/env bash
# install-hermes-hook.sh — propagate the Hermes TTS hook from the repo to the
# locations Hermes actually loads, stamping the repo path so the installed copy
# resolves the CANONICAL strip_markdown.py / chunks.py instead of guessing.
#
# Two execution surfaces, both stamped here:
#   gateway  agent:end      → ~/.hermes/hooks/afterwords-tts/handler.py
#   direct CLI post_llm_call → ~/.hermes/config.yaml (shell hook path, in repo)
#
# Idempotent. Backs up the previous handler. Does NOT restart the gateway
# (that is the owner's call) — it prints the command to run next.
#
# Usage: bash scripts/install-hermes-hook.sh [--dry-run]
set -uo pipefail

DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/hermes/hooks/afterwords-tts/handler.py"
HOOK_DIR="${HERMES_HOME:-$HOME/.hermes}/hooks/afterwords-tts"
DST="$HOOK_DIR/handler.py"

for required in "$SRC" "$REPO_ROOT/strip_markdown.py" "$REPO_ROOT/chunks.py"; do
    if [ ! -f "$required" ]; then
        echo "ERROR: missing $required — is REPO_ROOT right? ($REPO_ROOT)" >&2
        exit 1
    fi
done

if $DRY_RUN; then
    echo "would install: $SRC"
    echo "           → $DST"
    echo "would stamp: _REPO_HINT = '$REPO_ROOT'"
    exit 0
fi

mkdir -p "$HOOK_DIR"
[ -f "$DST" ] && cp -p "$DST" "$DST.bak-$(date +%Y%m%d-%H%M%S)"

# Stamp the repo path into the installed copy so resolution never falls back to
# a stale ~/.claude/hooks helper.
python3 - "$SRC" "$DST" "$REPO_ROOT" <<'PYEOF'
import re, sys
src_path, dst_path, repo = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(src_path).read()
stamped, count = re.subn(r'^_REPO_HINT = .*$', f'_REPO_HINT = {repo!r}', src, count=1, flags=re.M)
if count != 1:
    sys.exit(f"ERROR: could not stamp _REPO_HINT in {src_path}")
if f"_REPO_HINT = {repo!r}" not in stamped:
    sys.exit("ERROR: stamp verification failed")
open(dst_path, 'w').write(stamped)
PYEOF
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "ERROR: stamping failed (rc=$rc); installed copy NOT replaced" >&2
    exit "$rc"
fi

rm -rf "$HOOK_DIR/__pycache__"
echo "installed: $DST"
echo "stamped:   _REPO_HINT = $REPO_ROOT"

# Prove the installed copy resolves the canonical modules from its real location.
python3 - "$DST" <<'PYEOF'
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("aw_installed_check", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
report = mod._resolution_report()
print("resolved:  " + report)
if "MISSING" in report:
    sys.exit(f"ERROR: installed handler cannot resolve canonical helpers: {report}")
PYEOF
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "ERROR: post-install resolution check failed" >&2
    exit "$rc"
fi

echo
echo "Gateway loads this file at startup — restart to pick it up:"
echo "  hermes gateway restart"
echo
echo "Direct CLI uses the shell hook by path, so it needs no restart:"
echo "  $REPO_ROOT/scripts/afterwords-post-llm.sh"
