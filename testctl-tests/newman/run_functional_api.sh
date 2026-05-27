#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Run StaffPlus Functional API Tests via Newman
#
# Usage:
#   ./run_functional_api.sh                  # auto-reads cookie from session.json
#   ./run_functional_api.sh <session_cookie> # pass cookie manually
#
# Output: reports/newman_functional_<timestamp>.html
# ─────────────────────────────────────────────────────────────────────────────

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTION="$DIR/staffplus_functional_api.json"
SESSION_FILE="$DIR/../playwright/.auth/session.json"
REPORTS_DIR="$DIR/../playwright/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT="$REPORTS_DIR/newman_functional_${TIMESTAMP}.html"

mkdir -p "$REPORTS_DIR"

# ── Resolve session cookie ────────────────────────────────────────────────────
if [ -n "$1" ]; then
    COOKIE="$1"
    echo "Using provided session cookie."
elif [ -f "$SESSION_FILE" ]; then
    # Extract bmgmt_sess cookie value from Playwright storage_state JSON
    COOKIE_VALUE=$(python3 -c "
import json, sys
data = json.load(open('$SESSION_FILE'))
cookies = data.get('cookies', [])
for c in cookies:
    if c.get('name') == 'bmgmt_sess':
        print('bmgmt_sess=' + c['value'])
        sys.exit(0)
print('')
" 2>/dev/null)
    if [ -z "$COOKIE_VALUE" ]; then
        echo "❌  No bmgmt_sess cookie found in $SESSION_FILE"
        echo "    Run: python ../playwright/save_session.py"
        exit 1
    fi
    COOKIE="$COOKIE_VALUE"
    echo "✓  Session cookie loaded from session.json"
else
    echo "❌  No session file at $SESSION_FILE and no cookie passed as argument."
    echo "    Run: python ../playwright/save_session.py"
    exit 1
fi

# ── Check Newman is installed ─────────────────────────────────────────────────
if ! command -v newman &>/dev/null; then
    echo "❌  Newman not found. Install with: npm install -g newman newman-reporter-htmlextra"
    exit 1
fi

# ── Run collection ────────────────────────────────────────────────────────────
echo ""
echo "Running StaffPlus Functional API Tests..."
echo "Collection: $COLLECTION"
echo "Report:     $REPORT"
echo ""

newman run "$COLLECTION" \
    --env-var "cookie=$COOKIE" \
    --reporters cli,htmlextra \
    --reporter-htmlextra-export "$REPORT" \
    --reporter-htmlextra-title "StaffPlus Functional API — $(date '+%Y-%m-%d %H:%M')" \
    --reporter-htmlextra-browserTitle "Functional API Results" \
    --bail \
    || true   # don't exit on test failures — let newman print the summary

echo ""
echo "Report saved to: $REPORT"
