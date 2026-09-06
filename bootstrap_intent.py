#!/usr/bin/env python3
"""
bootstrap_intent.py — write a fixtures/intent_<site>.json from a REAL Meraki network.

    export MERAKI_API_KEY=...
    python bootstrap_intent.py --network N_123456789 --site CLIENT-HQ [--sla critical] [--out fixtures/intent_client_hq.json]

Yes, bootstrapping intent from observed is cheating — it is also exactly what every customer does on day one
(infrahub-sync does the same from NetBox). Load the result with seed_site.py, then EDIT it so drift has something
to catch: rename an AP, set an SSID to dot1x that is really psk, mark a spare AP decommissioned.
Nothing here is written back to Meraki; it is a single read.
"""
import argparse
import json
import os
import sys

import requests

from drift import MERAKI_AUTH, MERAKI_BAND

BASE = "https://api.meraki.com/api/v1"


def from_nocternal(db_path: str, network: str, site: str, sla: str) -> dict:
    """Intent bootstrapped from NOCternal's device_state — every AP the collector knows becomes in_service intent."""
    import sqlite3
    names = [n.strip() for n in network.split(",") if n.strip()]      # "Site - wireless,Site - 60019" (see drift.py)
    ph = ",".join("?" * len(names))
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = c.execute(f"SELECT serial, name, model FROM device_state WHERE product_type='wireless' AND network IN ({ph}) "
                     "ORDER BY name", names).fetchall()
    if not rows:
        sys.exit(f"no wireless devices for network {network!r} in {db_path} — check the exact name in device_state")
    ssids = [r[0] for r in c.execute(f"SELECT DISTINCT ssid FROM client_info WHERE network IN ({ph}) AND connection='Wireless' "
                                     "AND ssid IS NOT NULL AND ssid != '' ORDER BY ssid", names)]
    return {
        "_comment": f"bootstrapped from NOCternal device_state for {network!r} — edit before treating as intent",
        "site": site, "meraki_network_id": None, "nocternal_network": network, "sla_tier": sla,
        "access_points": [{"name": n or s, "serial": s, "model": m, "mac": None, "mgmt_ip": None,
                           "floor": None, "lifecycle": "in_service", "rf_profile": None} for s, n, m in rows],
        "ssids": [{"name": x, "number": None, "enabled": True, "hidden": False, "auth_mode": "psk",
                   "vlan_id": None, "band": "dual"} for x in ssids],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", required=True, help="Meraki network ID (N_... / L_...), or the NOCternal network name with --from-nocternal")
    ap.add_argument("--site", required=True, help="WirelessSite.name to use, e.g. CLIENT-HQ")
    ap.add_argument("--sla", default="standard", choices=["critical", "standard", "best_effort"])
    ap.add_argument("--out", help="default fixtures/intent_<site>.json")
    ap.add_argument("--from-nocternal", metavar="EVENTS_DB", help="build intent from NOCternal's SQLite store instead of the Meraki API")
    args = ap.parse_args()

    if args.from_nocternal:
        intent = from_nocternal(args.from_nocternal, args.network, args.site, args.sla)
        out = args.out or f"fixtures/intent_{args.site.lower().replace('-', '_')}.json"
        json.dump(intent, open(out, "w"), indent=2)
        print(f"wrote {out}: {len(intent['access_points'])} APs, {len(intent['ssids'])} SSIDs from NOCternal network {args.network!r}")
        return 0

    key = os.environ.get("MERAKI_API_KEY") or sys.exit("MERAKI_API_KEY not set")
    h = {"X-Cisco-Meraki-API-Key": key, "Accept": "application/json"}

    def get(path, **params):
        r = requests.get(BASE + path, headers=h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    net = get(f"/networks/{args.network}")
    devices = [d for d in get(f"/networks/{args.network}/devices") if (d.get("model") or "").startswith(("MR", "CW"))]
    ssids = [s for s in get(f"/networks/{args.network}/wireless/ssids")
             if s.get("enabled") and s.get("name") and not s["name"].startswith("Unconfigured SSID")]
    try:
        profiles = {p["id"]: p["name"] for p in get(f"/networks/{args.network}/wireless/rfProfiles")}
    except Exception:
        profiles = {}

    intent = {
        "_comment": f"bootstrapped from Meraki network {args.network} ({net.get('name')}) — edit before treating as intent",
        "site": args.site,
        "meraki_network_id": args.network,
        "sla_tier": args.sla,
        "access_points": [],
        "ssids": [],
    }
    for d in devices:
        rf = None
        try:
            rf = profiles.get(get(f"/devices/{d['serial']}/wireless/radio/settings").get("rfProfileId"))
        except Exception:
            pass
        intent["access_points"].append({
            "name": d.get("name") or d["serial"], "serial": d["serial"], "model": d.get("model"),
            "mac": (d.get("mac") or "").lower() or None, "mgmt_ip": d.get("lanIp"),
            "floor": None, "lifecycle": "in_service", "rf_profile": rf,
        })
    for s in ssids:
        intent["ssids"].append({
            "name": s["name"], "number": s["number"], "enabled": True, "hidden": s.get("visible") is False,
            "auth_mode": MERAKI_AUTH.get(s.get("authMode"), "psk"), "vlan_id": s.get("defaultVlanId"),
            "band": MERAKI_BAND.get(s.get("bandSelection"), "dual"),
        })

    out = args.out or f"fixtures/intent_{args.site.lower().replace('-', '_')}.json"
    json.dump(intent, open(out, "w"), indent=2)
    print(f"wrote {out}: {len(intent['access_points'])} APs, {len(intent['ssids'])} SSIDs from '{net.get('name')}'")
    print("next: edit it to lie about two things, then  python3 seed_site.py", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
