#!/usr/bin/env bash
# Clone the main Red Dwarf characters missing from the gallery: Lister, The Cat, Kryten.
# Holly and Rimmer already exist and are skipped automatically.
#
# For each character this script:
#   1. Runs clone-voice.sh from a BBC Studios YouTube source (interactive by default
#      so you can confirm the transcript; pass --yes for fully non-interactive).
#   2. Generates both qwen3-0.6b and qwen3-1.7b per-backend JSON profiles with
#      a family field, matching the convention used for all other gallery voices.
#
# Usage:
#   bash scripts/clone-red-dwarf.sh          # interactive (recommends confirming)
#   bash scripts/clone-red-dwarf.sh --yes    # fully non-interactive (any start_s)
#   bash scripts/clone-red-dwarf.sh --voice kryten          # single character
#   bash scripts/clone-red-dwarf.sh --voice kryten --yes    # single, non-interactive
#
# Clip notes:
#   lister  — "Lister teaches Kryten how to lie" (BBC Studios) — Lister solo near start
#   the-cat — "What is it?" (BBC) — Cat's voice prominent throughout
#   kryten  — "Kryten Shares Surprising Information in the Shuttle" (BBC Studios) — Kryten monologue near start
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; DIM='\033[2m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "  ${CYAN}▸${NC} $*"; }
ok()    { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
rule()  { echo -e "${DIM}  ─────────────────────────────────────────${NC}"; }

AUTO_YES=false
ONLY_VOICE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) AUTO_YES=true; shift ;;
        --voice) ONLY_VOICE="${2:-}"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# name | youtube_url | start_s | actor | clip_title
CHARACTERS=(
    "lister|https://www.youtube.com/watch?v=8525OKIhwqk|0|Craig Charles|Lister teaches Kryten how to lie (BBC Studios)"
    "the-cat|https://www.youtube.com/watch?v=3r5Ynz-a7Io|5|Danny John-Jules|What is it? (BBC)"
    "kryten|https://www.youtube.com/watch?v=5I76_eDxWdU|0|Robert Llewellyn|Kryten Shares Surprising Information in the Shuttle (BBC Studios)"
)

add_variants() {
    local NAME="$1"
    [ -f "voices/${NAME}.json" ] || return 0

    "$REPO_DIR/.venv/bin/python3" - "$NAME" "$REPO_DIR" <<'PYEOF'
import json, sys, os
sys.path.insert(0, sys.argv[2])
import backends
backends.register_all()

name = sys.argv[1]
base_path = f"voices/{name}.json"
with open(base_path) as f:
    base = json.load(f)

ref_audio   = base.get("reference_audio", f"{name}-ref.wav")
ref_text    = base.get("reference_text", "")
source_url  = base.get("source_url", "")
seg_start   = base.get("segment_start_s", 0)

for backend in ("qwen3-0.6b", "qwen3-1.7b"):
    sl = backends.slug(backend)
    variant_name = f"{name}-{sl}"
    variant_path = f"voices/{variant_name}.json"
    if os.path.exists(variant_path):
        print(f"  [skip] {variant_name}.json already exists")
        continue
    payload = {
        "name": variant_name,
        "backend": backend,
        "reference_audio": ref_audio,
        "reference_text": ref_text,
        "family": name,
        "source_url": source_url,
        "segment_start_s": seg_start,
    }
    with open(variant_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  [write] {variant_path}")
PYEOF
}

ANY_CLONED=false

for ENTRY in "${CHARACTERS[@]}"; do
    IFS='|' read -r NAME URL START_S ACTOR CLIP_TITLE <<< "$ENTRY"

    [ -n "$ONLY_VOICE" ] && [ "$NAME" != "$ONLY_VOICE" ] && continue

    rule
    if [ -f "voices/${NAME}.json" ]; then
        warn "${NAME}: already cloned — skipping"
        add_variants "$NAME"
        continue
    fi

    echo -e "\n  ${BOLD}Cloning:${NC} ${CYAN}${NAME}${NC}  (${ACTOR})"
    info "$CLIP_TITLE"
    info "Start: ${START_S}s — adjust if the auto-transcript misses the character's solo speech"
    echo ""

    CLONE_ARGS=("$URL" "$NAME" "$START_S" "--backend" "qwen3-0.6b")
    $AUTO_YES && CLONE_ARGS+=("--yes")

    bash clone-voice.sh "${CLONE_ARGS[@]}"

    if [ -f "voices/${NAME}.json" ]; then
        add_variants "$NAME"
        ok "${NAME} cloned"
        ANY_CLONED=true
    else
        warn "${NAME}: clone-voice.sh exited without writing voices/${NAME}.json"
    fi
done

rule
echo ""
if $ANY_CLONED; then
    echo -e "  ${GREEN}✓${NC} Done. Run ${CYAN}afterwords reload${NC} to pick up the new voices."
else
    echo -e "  ${YELLOW}⚠${NC} Nothing new cloned (all characters already present or skipped)."
fi
echo ""
echo -e "  ${DIM}To use these voices in .afterwords:${NC}"
echo -e "    default: rimmer"
echo -e "    cursor: lister"
echo -e "    claude: holly"
echo ""
