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

GROUP = "wireless_sites"


def upsert(client, kind, match, data, branch):
    """Get-or-create a node by a unique attribute, then set the rest of the fields."""
    try:
        node = client.get(kind=kind, branch=branch, **match)
        created = False
    except NodeNotFoundError:
        node = client.create(kind=kind, branch=branch, data={**match_to_data(match), **{k: v for k, v in data.items() if v is not None}})
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

    # Every site goes in the `wireless_sites` group: that is what .infrahub.yml targets for the drift check and the artifact.
    # The group lives on main (membership is plumbing, not intent) so a branch created earlier never collides with it;
    # branches inherit it. A site created on a branch is added to the group once that branch is merged.
    if args.branch == "main":
        group, new = upsert(client, "CoreStandardGroup", {"name__value": GROUP}, {"description": "Sites the wireless_drift check and meraki-ssids artifact run against"}, "main")
        group.members.fetch()
        if site.id not in group.members.peer_ids:
            group.members.add(site.id)
            group.save()
        print(f"  {'created' if new else 'in'} group {GROUP}")

    # Profiles: an RF standard applied to many APs instead of typed into each one (Infrahub generates ProfileWirelessAccessPoint from the schema).
    profile_ids = {}
    for p in intent.get("profiles", []):
        data = {k: p.get(k) for k in ("rf_profile", "tags", "floor")}
        data["profile_priority"] = p.get("priority", 1000)
        prof, new = upsert(client, "ProfileWirelessAccessPoint", {"profile_name__value": p["name"]}, data, args.branch)
        profile_ids[p["name"]] = prof.id
        print(f"  {'created' if new else 'updated'} profile {p['name']}  (rf_profile={p.get('rf_profile')})")

    for a in intent["access_points"]:
        data = {k: a.get(k) for k in ("name", "model", "mac", "mgmt_ip", "floor", "lifecycle", "rf_profile")}
        data["site"] = site.id
        node, new = upsert(client, "WirelessAccessPoint", {"serial__value": a["serial"]}, data, args.branch)
        if a.get("profile"):
            node.profiles.fetch()
            if profile_ids[a["profile"]] not in node.profiles.peer_ids:
                node.profiles.add(profile_ids[a["profile"]])
                node.save()
        print(f"  {'created' if new else 'updated'} AP    {a['name']:<22} {a['serial']}" + (f"  profile={a['profile']}" if a.get("profile") else ""))

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
