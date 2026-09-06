#!/usr/bin/env python3
"""
seed_site.py — load one site's INTENDED wireless state into Infrahub.

    export INFRAHUB_ADDRESS=http://localhost:8000
    export INFRAHUB_API_TOKEN=06438eb2-8019-4776-878c-0941b1f1d1ec
    python seed_site.py fixtures/intent_nash_hq.json            # into main
    python seed_site.py fixtures/intent_nash_hq.json --branch nash-refresh

Idempotent: re-running updates existing objects (matched on site name / AP serial / SSID name) instead of duplicating.
Requires: pip install infrahub-sdk   (schema/nocternal_wireless.yml must already be loaded)
"""
import argparse
import json
import sys

from infrahub_sdk import InfrahubClientSync
from infrahub_sdk.exceptions import NodeNotFoundError


def upsert(client, kind, match, data, branch):
    """Get-or-create a node by a unique attribute, then set the rest of the fields."""
    try:
        node = client.get(kind=kind, branch=branch, **match)
        created = False
    except NodeNotFoundError:
        node = client.create(kind=kind, branch=branch, data={**match_to_data(match), **data})
        created = True
    if not created:
        for k, v in data.items():
            if v is None:
                continue
            # InfrahubNode.__setattr__ routes this to attr.value for attributes and rebuilds the
            # RelatedNode for cardinality-one relationships (RelatedNode.id is read-only, so no attr.id = v).
            setattr(node, k, v)
    node.save(allow_upsert=True)
    return node, created


def match_to_data(match):
    # {"serial__value": "Q2XX"} -> {"serial": "Q2XX"}; relationship filters (site__ids) are already in `data`
    return {k.replace("__value", ""): v for k, v in match.items() if k.endswith("__value")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("intent_file")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    intent = json.load(open(args.intent_file))
    client = InfrahubClientSync()          # reads INFRAHUB_ADDRESS / INFRAHUB_API_TOKEN

    site, new = upsert(
        client, "WirelessSite", {"name__value": intent["site"]},
        {"meraki_network_id": intent.get("meraki_network_id"), "nocternal_network": intent.get("nocternal_network"),
         "sla_tier": intent.get("sla_tier", "standard")},
        args.branch,
    )
    print(f"{'created' if new else 'updated'} site  {intent['site']}  id={site.id}")

    for a in intent["access_points"]:
        data = {k: a.get(k) for k in ("name", "model", "mac", "mgmt_ip", "floor", "lifecycle", "rf_profile")}
        data["site"] = site.id
        _, new = upsert(client, "WirelessAccessPoint", {"serial__value": a["serial"]}, data, args.branch)
        print(f"  {'created' if new else 'updated'} AP    {a['name']:<22} {a['serial']}")

    for s in intent["ssids"]:
        data = {k: s.get(k) for k in ("number", "enabled", "hidden", "auth_mode", "vlan_id", "band")}
        data["site"] = site.id
        # SSID names are unique per site, not globally: match on name + site
        _, new = upsert(client, "WirelessSSID", {"name__value": s["name"], "site__ids": [site.id]}, data, args.branch)
        print(f"  {'created' if new else 'updated'} SSID  {s['name']}")

    print(f"\nDone on branch '{args.branch}'. Open {client.config.address}/objects/WirelessSite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
