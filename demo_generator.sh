#!/usr/bin/env bash
# Generator demo: a new healthcare site gets its standard SSIDs from a template, in a branch, reviewable as a diff.
# Requires demo.sh to have run (Infrahub up, schema loaded) and the repo's .infrahub.yml (generators are discovered from it).
set -euo pipefail
export INFRAHUB_ADDRESS="${INFRAHUB_ADDRESS:-http://localhost:8000}"
export INFRAHUB_API_TOKEN="${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}"
BRANCH="${1:-nash-clinic}"
[ -d .venv ] && source .venv/bin/activate

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

step "1/3  branch $BRANCH"
infrahubctl branch create "$BRANCH" 2>/dev/null || infrahubctl branch rebase "$BRANCH"

step "2/3  a new site, vertical=healthcare, two staged APs, NO ssids"
python3 seed_site.py fixtures/intent_nash_clinic.json --branch "$BRANCH"

step "3/3  generator: the healthcare SSID standard, applied"
infrahubctl generator site_wireless_standard site=NASH-CLINIC --branch "$BRANCH"

cat <<EOF

Open $INFRAHUB_ADDRESS/objects/WirelessSSID?branch=$BRANCH  -> Clinical (dot1x/110), Guest (open/120), Biomed (ipsk/130, hidden)
Then: Branches -> $BRANCH -> Data -> the diff is the whole site, SSIDs included, before anything touched a dashboard.
Change the site's vertical to 'office' and re-run: the generator's tracking retires Clinical/Biomed and produces Corp/IoT.
EOF
