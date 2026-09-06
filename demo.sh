#!/usr/bin/env bash
# One-shot: bring up Infrahub, load the wireless schema, seed NASH-HQ, run drift.
# Run from the nocternal-infrahub folder. Needs Docker Desktop (or Docker Engine) running and python3.
set -euo pipefail

export INFRAHUB_ADDRESS="${INFRAHUB_ADDRESS:-http://localhost:8000}"
export INFRAHUB_API_TOKEN="${INFRAHUB_API_TOKEN:-06438eb2-8019-4776-878c-0941b1f1d1ec}"   # default token baked into the demo compose file

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

step "0/5  preflight"
command -v docker >/dev/null || die "docker not found — install Docker Desktop and give it ≥4 CPU / 8 GB (Settings → Resources)"
docker info >/dev/null 2>&1   || die "docker daemon not running — start Docker Desktop and re-run"
command -v python3 >/dev/null || die "python3 not found"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python3 -m pip install -q --upgrade pip
python3 -m pip install -q -r requirements.txt
echo "python: $(python3 --version)   infrahub-sdk: $(python3 -m pip show infrahub-sdk | awk '/^Version/{print $2}')"

step "1/5  Infrahub via Docker Compose (first pull is ~3 GB, be patient)"
[ -f docker-compose.yml ] || curl -fsSL https://infrahub.opsmill.io > docker-compose.yml
docker compose -p infrahub up -d

step "2/5  waiting for the API (Neo4j + task worker take a minute or two on first boot)"
for i in $(seq 1 90); do
  curl -fs "$INFRAHUB_ADDRESS/api/info" >/dev/null 2>&1 && break
  sleep 5; printf '.'
done; echo
curl -fs "$INFRAHUB_ADDRESS/api/info" >/dev/null 2>&1 || die "Infrahub never answered at $INFRAHUB_ADDRESS — try: docker compose -p infrahub logs infrahub-server"

step "3/5  load the wireless schema"
infrahubctl schema load --wait 60 schema/nocternal_wireless.yml

step "4/5  seed intended state for NASH-HQ"
python3 seed_site.py fixtures/intent_nash_hq.json

step "5/5  drift: Infrahub intent vs observed fixture"
python3 drift.py --site NASH-HQ --observed fixtures/observed_nash_hq.json --json drift_nash_hq.json || true

cat <<EOF

UI:      $INFRAHUB_ADDRESS   (admin / infrahub)  -> left menu "Wireless" -> Sites -> NASH-HQ
GraphQL: $INFRAHUB_ADDRESS/graphql   -> paste queries/site_intent.gql, variables {"site":"NASH-HQ"}
Branch demo (Day 2):                 ./demo_branch.sh
Live Meraki instead of the fixture:  MERAKI_API_KEY=... python3 drift.py --site NASH-HQ
Stop everything:                     docker compose -p infrahub down        (add -v to wipe the data)
EOF
