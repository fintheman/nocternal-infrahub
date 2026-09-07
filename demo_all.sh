#!/usr/bin/env bash
# demo_all.sh — the whole story, in order, with a pause between beats. Rehearse it, record it, screen-share it.
#   ./demo_all.sh            pauses between steps (press Enter)
#   ./demo_all.sh --fast     no pauses
#   NOCTERNAL_DB=../noc-platform/events.db SITE=SITE-A ./demo_all.sh     adds the real-site beat at the end
# Assumes demo.sh, demo_branch.sh and demo_generator.sh have run once (Infrahub up, NASH-HQ on main,
# nash-6ghz-refresh and nash-clinic branches exist). Everything here is read-only against Infrahub.
set -uo pipefail
export INFRAHUB_ADDRESS="${INFRAHUB_ADDRESS:-http://localhost:8000}"
export INFRAHUB_API_TOKEN="${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}"
[ -d .venv ] && source .venv/bin/activate
FAST=0; [ "${1:-}" = "--fast" ] && FAST=1

beat()  { printf '\n\n\033[1;36m━━ %s\033[0m\n\033[2m%s\033[0m\n\n' "$1" "$2"; }
pause() { [ "$FAST" = 1 ] || read -r -p $'\n\033[2m[enter]\033[0m ' _; }
say()   { printf '\033[2m$ %s\033[0m\n' "$*"; "$@"; }

clear
beat "1 · Intent vs observed, no server needed" \
     "A 7-AP site as it should be, the same site as the dashboard reports it. Nine planted faults. Every line is a real 2 a.m."
say python3 drift.py --site NASH-HQ --intent fixtures/intent_nash_hq.json --observed fixtures/observed_nash_hq.json
pause

beat "2 · The same diff, intent read live from Infrahub" \
     "Now the left side is GraphQL: the site, its APs (with RF profiles applied), its SSIDs."
say python3 drift.py --site NASH-HQ --observed fixtures/observed_nash_hq.json
pause

beat "3 · Drift against the FUTURE: a 6 GHz refresh branch" \
     "Reality diffed against a branch that hasn't merged. The CW9166 goes MISSING; the Corp band mismatches. Readiness check."
say python3 drift.py --site NASH-HQ --branch nash-6ghz-refresh --observed fixtures/observed_nash_hq.json
pause

beat "4 · The same thing as an Infrahub Check — what a Proposed Change runs" \
     "Critical findings are errors; the PC goes red. Same compare(), same fixtures, Infrahub's own runner."
say infrahubctl check wireless_drift site=NASH-HQ --branch nash-6ghz-refresh
pause

beat "5 · A Generator: vertical → standard SSIDs" \
     "NASH-CLINIC was created with vertical=healthcare and no SSIDs. The generator produced Clinical / Guest / Biomed on the branch."
say infrahubctl generator site_wireless_standard site=NASH-CLINIC --branch nash-clinic
echo; echo "  → ${INFRAHUB_ADDRESS}/objects/WirelessSSID?branch=nash-clinic"
pause

beat "6 · The artifact for cloud-managed wireless is the API payload" \
     "No config file to render — so render the Meraki PUT bodies per SSID, secrets as placeholders, diffable per branch."
say infrahubctl render meraki_ssids site=NASH-HQ --branch nash-6ghz-refresh
pause

if [ -n "${NOCTERNAL_DB:-}" ] && [ -n "${SITE:-}" ]; then
  beat "7 · A real site: intent in Infrahub, observed from the NOC's own event store" \
       "No Meraki call. device_state, rogue_aps, client_info. Whatever it prints is true right now."
  say python3 drift.py --site "$SITE" --nocternal "$NOCTERNAL_DB"
  pause
  beat "8 · The whole fleet, one table" \
       "Every wireless network the collectors know, graded the same way."
  say python3 fleet_drift.py --nocternal "$NOCTERNAL_DB" --top 12 --anonymize
fi

printf '\n\033[1;32mdone.\033[0m  UI: %s   repo: https://github.com/fintheman/nocternal-infrahub\n' "$INFRAHUB_ADDRESS"
