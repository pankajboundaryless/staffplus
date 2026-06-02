#!/usr/bin/env bash
# Run Newman Mutation API v2 — POST/UPDATE write-path tests
# Usage: bash run_mutation_api.sh [--report-only]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTION="$SCRIPT_DIR/staffplus_mutation_api.json"
REPORTS_DIR="$SCRIPT_DIR/../reports"
TS=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="$REPORTS_DIR/newman_mutation_${TS}.html"

mkdir -p "$REPORTS_DIR"

# Inject live session cookie from .auth/session.json
SESSION_FILE="$SCRIPT_DIR/../playwright/.auth/session.json"
if [ ! -f "$SESSION_FILE" ]; then
  echo "ERROR: Session file not found: $SESSION_FILE"
  echo "       Run: python save_session.py  (from repo root)"
  exit 1
fi

COOKIE=$(python3 -c "
import json, sys
with open('$SESSION_FILE') as f:
    d = json.load(f)
val = next((c['value'] for c in d.get('cookies',[]) if c.get('name')=='bmgmt_sess'), None)
if not val:
    print('ERROR: bmgmt_sess cookie not found', file=sys.stderr)
    sys.exit(1)
print(val)
")

echo "Session cookie: ${COOKIE:0:10}... (len=${#COOKIE})"

# Patch session cookie into a temp copy of the collection
TMP_COL="/tmp/staffplus_mutation_api_run_${TS}.json"
python3 -c "
import json
with open('$COLLECTION') as f:
    col = json.load(f)
for v in col['variable']:
    if v['key'] == 'session_cookie':
        v['value'] = '$COOKIE'
        break
with open('$TMP_COL', 'w') as f:
    json.dump(col, f, indent=2)
"

echo ""
echo "Running Newman Mutation API v2..."
echo "Collection: $COLLECTION"
echo "Report:     $REPORT_FILE"
echo ""

newman run "$TMP_COL" \
  --reporters cli,htmlextra \
  --reporter-htmlextra-export "$REPORT_FILE" \
  --reporter-htmlextra-title "StaffPlus Mutation API v2 — $(date '+%Y-%m-%d %H:%M')" \
  --timeout-request 10000 \
  --delay-request 200

rm -f "$TMP_COL"

echo ""
echo "Done. HTML report: $REPORT_FILE"
