#!/usr/bin/env python3
"""
bootstrap_from_ekahau.py — the design tool feeds intent.

An Ekahau project (.esx) is a zip of JSON. Every AP that has a *simulated* radio is a design decision:
someone placed it on a floor plan on purpose. This turns those into WirelessAccessPoint intent with
lifecycle=planned, so the drift engine reports them as PLANNED (info) until they are claimed, and as
MISSING (crit) the moment someone flips them to in_service without the hardware showing up.

    python3 bootstrap_from_ekahau.py --esx "Nashville HQ.esx" --site NASH-HQ                # new intent file
    python3 bootstrap_from_ekahau.py --esx "Nashville HQ.esx" --site NASH-HQ --merge fixtures/intent_nash_hq.json

--merge adds planned APs to an existing intent (matched on name; existing APs are left alone), which is the
real workflow: the live estate came from bootstrap_intent.py, the expansion came from the survey.

Simulated APs have no serial yet. They get `PLANNED-<SITE>-<name>` as a placeholder; replace it with the real
serial when the box is claimed (that edit is what moves the AP from planned to staged in a Proposed Change).
"""
import argparse
import json
import re
import sys
import zipfile

VENDOR_PREFIXES = ("cisco meraki", "meraki", "cisco", "aruba", "hpe aruba networking", "hpe", "juniper mist", "mist", "juniper")


def clean_model(vendor: str | None, model: str | None) -> str | None:
    m = (model or "").strip()
    if not m:
        return None
    low = m.lower()
    for p in VENDOR_PREFIXES:
        if low.startswith(p + " "):
            m = m[len(p) + 1:]
            break
    return m.split(" (")[0].strip() or None          # "MR57 (external antenna)" -> "MR57"


def read_esx(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        def load(name, key):
            return json.loads(z.read(name))[key] if name in names else []

        return {
            "floors": {f["id"]: f.get("name") for f in load("floorPlans.json", "floorPlans")},
            "aps": load("accessPoints.json", "accessPoints"),
            "simulated": {r["accessPointId"] for r in load("simulatedRadios.json", "simulatedRadios")},
            "measured": {r["accessPointId"] for r in load("measuredRadios.json", "measuredRadios")},
        }


def planned_aps(esx: dict, site: str) -> list[dict]:
    out = []
    for ap in esx["aps"]:
        if ap["id"] not in esx["simulated"] or ap["id"] in esx["measured"]:
            continue                                   # measured = already on the air; not a plan
        if ap.get("mine") is False:
            continue                                   # a neighbour's AP that was surveyed
        loc = ap.get("location") or {}
        floor = esx["floors"].get(loc.get("floorPlanId"))
        name = ap.get("name") or f"AP-{len(out) + 1:02d}"
        slug = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")
        out.append({
            "name": name, "serial": f"PLANNED-{site}-{slug}", "model": clean_model(ap.get("vendor"), ap.get("model")),
            "mac": None, "mgmt_ip": None, "floor": floor, "lifecycle": "planned", "rf_profile": None,
            "ekahau": {"id": ap["id"], "x": round((loc.get("coord") or {}).get("x", 0), 1),
                       "y": round((loc.get("coord") or {}).get("y", 0), 1)},
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--esx", required=True)
    p.add_argument("--site", required=True, help="WirelessSite.name, e.g. NASH-HQ")
    p.add_argument("--merge", metavar="INTENT_JSON", help="add planned APs into this existing intent file")
    p.add_argument("--out", help="default fixtures/intent_<site>.json (or the --merge file)")
    args = p.parse_args()

    esx = read_esx(args.esx)
    planned = planned_aps(esx, args.site)
    if not planned:
        sys.exit("no simulated APs found in that .esx (nothing to plan)")

    if args.merge:
        intent = json.load(open(args.merge))
        have = {a["name"] for a in intent["access_points"]}
        added = [a for a in planned if a["name"] not in have]
        intent["access_points"].extend(added)
        out = args.out or args.merge
    else:
        intent = {"_comment": f"planned APs from Ekahau project {args.esx!r}", "site": args.site, "meraki_network_id": None,
                  "sla_tier": "standard", "access_points": planned, "ssids": []}
        added = planned
        out = args.out or f"fixtures/intent_{args.site.lower().replace('-', '_')}.json"

    json.dump(intent, open(out, "w"), indent=2)
    floors = sorted({a["floor"] for a in added if a["floor"]})
    print(f"wrote {out}: {len(added)} planned APs from {len(esx['aps'])} in the project"
          + (f" across floors {', '.join(floors)}" if floors else ""))
    for a in added:
        print(f"  planned  {a['name']:<20} {a['model'] or '?':<10} floor={a['floor']}  ({a['ekahau']['x']}, {a['ekahau']['y']})")
    print(f"next: python3 seed_site.py {out} --branch <survey-branch>   then   python3 drift.py --site {args.site} --branch <survey-branch>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
