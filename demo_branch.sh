#!/usr/bin/env bash
# Day 2 demo: "what will drift look like AFTER the 6 GHz refresh?"  — diff reality against a FUTURE intent on a branch.
# Requires demo.sh to have run (Infrahub up, schema loaded, NASH-HQ seeded on main).
set -euo pipefail
export INFRAHUB_ADDRESS="${INFRAHUB_ADDRESS:-http://localhost:8000}"
export INFRAHUB_API_TOKEN="${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}"
BRANCH="${1:-nash-6ghz-refresh}"
[ -d .venv ] && source .venv/bin/activate

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

step "1/3  create branch $BRANCH (no-op if it exists)"
infrahubctl branch create "$BRANCH" 2>/dev/null || echo "branch $BRANCH already exists"

step "2/3  seed the FUTURE intent on the branch (NOCternal-Corp -> six_capable, CW9166 on 3F -> in_service)"
python3 seed_site.py fixtures/intent_nash_hq_refresh.json --branch "$BRANCH"

step "3/3  drift of today's reality vs the branch"
python3 drift.py --site NASH-HQ --branch "$BRANCH" --observed fixtures/observed_nash_hq.json --json "drift_nash_hq_$BRANCH.json" || true

cat <<EOF

Now open $INFRAHUB_ADDRESS/branches/$BRANCH  -> "Proposed change" -> the diff shows exactly the objects you touched.
Merge it and re-run:  python3 drift.py --site NASH-HQ --observed fixtures/observed_nash_hq.json
The CW9166 moves from PLANNED (info) to MISSING (crit) — the readiness check became an outstanding-work item.
EOF
