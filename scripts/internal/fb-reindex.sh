#!/usr/bin/env bash
#
# Force Facebook to re-scrape (reindex) one or more URLs after their
# OpenGraph metadata changes. Without an explicit re-scrape, Facebook
# serves stale link previews until its cache TTL expires (often days).
#
# Usage:
#   bash scripts/internal/fb-reindex.sh                                  # default URLs
#   bash scripts/internal/fb-reindex.sh https://example.com/page1 ...    # specific URLs
#
# Auth:
#   - Set FB_APP_ID and FB_APP_SECRET in env to use the Graph API directly
#     (preferred — non-interactive, scriptable in CI).
#   - Without those, the script prints the manual Sharing Debugger URLs
#     and exits, so you can click through them.
#
# Docs: https://developers.facebook.com/docs/sharing/webmasters/scraping/
set -uo pipefail

DEFAULT_URLS=(
    "https://adrianwedd.github.io/afterwords/"
    "https://github.com/adrianwedd/afterwords"
)

if [ "$#" -gt 0 ]; then
    URLS=("$@")
else
    URLS=("${DEFAULT_URLS[@]}")
fi

# ANSI
GRN="\033[0;32m"; YLW="\033[0;33m"; RED="\033[0;31m"; DIM="\033[2m"; NC="\033[0m"

# If FB_APP_ID + FB_APP_SECRET are present, mint an app access token and call
# the Graph API. Otherwise, fall back to printing the manual Debugger URLs.
TOKEN=""
if [ -n "${FB_APP_ID:-}" ] && [ -n "${FB_APP_SECRET:-}" ]; then
    TOKEN_URL="https://graph.facebook.com/oauth/access_token?client_id=${FB_APP_ID}&client_secret=${FB_APP_SECRET}&grant_type=client_credentials"
    TOKEN=$(curl -sS "$TOKEN_URL" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("access_token",""))
except: pass' 2>/dev/null)
    if [ -z "$TOKEN" ]; then
        echo -e "${YLW}warn:${NC} could not mint FB app access token (check FB_APP_ID/FB_APP_SECRET)"
    fi
fi

if [ -z "$TOKEN" ]; then
    echo -e "${YLW}No FB credentials in env.${NC} Open these URLs in a browser to force re-scrape:"
    echo
    for u in "${URLS[@]}"; do
        # URL-encode for the debugger query
        ENC=$(python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$u")
        echo -e "  ${DIM}https://developers.facebook.com/tools/debug/?q=${ENC}${NC}"
    done
    echo
    echo -e "  Click ${DIM}\"Scrape Again\"${NC} on each. Or set FB_APP_ID + FB_APP_SECRET to do it from the CLI."
    exit 0
fi

# Have a token — call the Graph API for each URL
FAILED=0
for u in "${URLS[@]}"; do
    RESPONSE=$(curl -sS -X POST \
        -F "id=${u}" \
        -F "scrape=true" \
        -F "access_token=${TOKEN}" \
        "https://graph.facebook.com/v19.0/")
    SUCCESS=$(printf '%s' "$RESPONSE" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print("ok" if "url" in d and "error" not in d else "fail")
except: print("fail")' 2>/dev/null)
    if [ "$SUCCESS" = "ok" ]; then
        echo -e "  ${GRN}✓${NC} re-scraped: $u"
    else
        echo -e "  ${RED}✗${NC} failed:    $u"
        echo -e "    ${DIM}${RESPONSE:0:200}${NC}"
        FAILED=$((FAILED + 1))
    fi
done

exit "$FAILED"
