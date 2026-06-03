#!/usr/bin/env bash
# Clone (or reclone) all five main Red Dwarf characters with in-character monologue sources.
#
# For each character this script:
#   1. Runs clone-voice.sh from a BBC Studios YouTube source (interactive by
#      default so you can confirm the transcript; pass --yes for non-interactive).
#   2. Generates qwen3-0.6b and qwen3-1.7b per-backend JSON profiles with
#      a family field, matching the convention for all other gallery voices.
#
# Usage:
#   bash scripts/clone-red-dwarf.sh                    # interactive, skips existing
#   bash scripts/clone-red-dwarf.sh --force            # reclone even if voice exists
#   bash scripts/clone-red-dwarf.sh --yes              # non-interactive
#   bash scripts/clone-red-dwarf.sh --voice rimmer     # single character
#   bash scripts/clone-red-dwarf.sh --voice rimmer --force --yes
#
# Sources (all official BBC Studios YouTube, in-character monologues):
#   holly   — "April Fool" (BBC) — Holly deadpan solo about Norweb + compound interest, Series 2
#   rimmer  — "Arnold Rimmer tries to keep his Libido in check" — solo internal Rimmer monologue, S8
#   lister  — "They're Dead Dave" (BBC Comedy Greats) — Lister's extended reaction speech, S1
#   the-cat — "Cat Justifies His Existence" (The Inquisitor) — Cat's solo vanity monologue, S5
#   kryten  — "Can Kryten Swear?" — extended Kryten solo, mechanoid guilt/formality, S4
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
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes)   AUTO_YES=true; shift ;;
        --force) FORCE=true; shift ;;
        --voice) ONLY_VOICE="${2:-}"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# name | youtube_url | start_s | actor | clip_title
CHARACTERS=(
    "holly|https://www.youtube.com/watch?v=elZfflKkfxM|64|Norman Lovett|April Fool (BBC) — Holly solo deadpan monologue about Norweb and compound interest, S2"
    "rimmer|https://www.youtube.com/watch?v=W4ziDB2K46M|0|Chris Barrie|Rimmer's Eulogy (BBC Studios) — solo formal Rimmer speech"
    "lister|https://www.youtube.com/watch?v=_aPF-Rui09Y|0|Craig Charles|Mayday (Marooned) — Lister alone making a distress call, S3"
    "the-cat|https://www.youtube.com/watch?v=RfNJitORCVA|0|Danny John-Jules|Cat Justifies His Existence (The Inquisitor, BBC) — solo vanity monologue, S5"
    "kryten|https://www.youtube.com/watch?v=RXKlC8ph7mM|0|Robert Llewellyn|Can Kryten Swear? (BBC Studios) — extended Kryten solo, mechanoid guilt, S4"
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
        # Refresh in case ref WAV changed (--force reclone).
        with open(variant_path) as f:
            existing = json.load(f)
        if existing.get("reference_text") == ref_text and existing.get("source_url") == source_url:
            print(f"  [skip] {variant_name}.json unchanged")
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
    if [ -f "voices/${NAME}.json" ] && ! $FORCE; then
        warn "${NAME}: already cloned (use --force to reclone)"
        add_variants "$NAME"
        continue
    fi

    echo -e "\n  ${BOLD}Cloning:${NC} ${CYAN}${NAME}${NC}  (${ACTOR})"
    info "$CLIP_TITLE"
    info "Start offset: ${START_S}s — confirm the transcript matches ${NAME}'s solo speech"
    echo ""

    # --yes must be at $4 (clone-voice.sh checks ${4:-} == "--yes")
    CLONE_ARGS=("$URL" "$NAME" "$START_S")
    $AUTO_YES && CLONE_ARGS+=("--yes")
    CLONE_ARGS+=("--backend" "qwen3-0.6b")

    bash clone-voice.sh "${CLONE_ARGS[@]}" || true

    if [ -f "voices/${NAME}.json" ]; then
        add_variants "$NAME"
        ok "${NAME} done"
        ANY_CLONED=true
    else
        warn "${NAME}: clone-voice.sh did not write voices/${NAME}.json"
    fi
done

rule
echo ""
if $ANY_CLONED; then
    echo -e "  ${GREEN}✓${NC} Done. Run ${CYAN}afterwords reload${NC} to pick up new voices."
else
    echo -e "  ${YELLOW}⚠${NC} Nothing new cloned (all present; use --force to reclone)."
fi
echo ""
echo -e "  ${DIM}Sample .afterwords for this repo:${NC}"
echo -e "    default: rimmer"
echo -e "    cursor:  lister"
echo -e "    claude:  holly"
echo ""
