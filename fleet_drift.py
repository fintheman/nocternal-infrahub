#!/usr/bin/env python3
"""
fleet_drift.py — the drift engine across EVERY wireless network in a NOCternal event store, in one table.

    python3 fleet_drift.py --nocternal ../noc-platform/events.db            # all sites
    python3 fleet_drift.py --nocternal ../noc-platform/events.db --top 15   # worst 15 by critical findings
    python3 fleet_drift.py --nocternal ../noc-platform/events.db --json fleet.json --anonymize

No Infrahub needed: for each network the "intent" is bootstrapped from device_state (every known AP expected
in_service) so the interesting findings are the ones intent can't hide — degraded/offline APs, evil twins and
rogues on the wire. It's the fleet-wide sentence: "across N sites and M APs tonight, X have a rogue on the LAN."

Sites are grouped by the name stem before " - " so a site split across dashboard networks
("Site - wireless", "Site - 60037") counts once. Output is local; --anonymize replaces names with SITE-001…
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict

from drift import compare, observed_from_nocternal


def stem(name: str) -> str:
    return re.split(r"\s+-\s+", name, maxsplit=1)[0].strip().lower()


def site_groups(db_path: str) -> dict[str, dict]:
    """stem -> {"label": display name, "aliases": [network names across all three tables]}"""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    groups: dict[str, dict] = defaultdict(lambda: {"label": None, "aliases": set(), "aps": 0})
    for net, n in c.execute("SELECT network, COUNT(*) FROM device_state WHERE product_type='wireless' AND network IS NOT NULL GROUP BY network"):
        g = groups[stem(net)]
        g["aliases"].add(net)
        g["aps"] += n
        if g["label"] is None or n > g.get("_n", 0):
            g["label"], g["_n"] = net, n
    for table in ("rogue_aps", "client_info"):
        for (net,) in c.execute(f"SELECT DISTINCT network FROM {table} WHERE network IS NOT NULL"):
            if stem(net) in groups:
                groups[stem(net)]["aliases"].add(net)
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nocternal", required=True, metavar="EVENTS_DB")
    ap.add_argument("--top", type=int, default=0, help="show only the N worst sites")
    ap.add_argument("--json", help="write per-site findings here")
    ap.add_argument("--anonymize", action="store_true", help="SITE-001… instead of network names")
    args = ap.parse_args()

    groups = site_groups(args.nocternal)
    rows, allfind = [], {}
    for i, (key, g) in enumerate(sorted(groups.items(), key=lambda kv: kv[1]["label"]), 1):
        aliases = ",".join(sorted(g["aliases"]))
        label = f"SITE-{i:03d}" if args.anonymize else g["label"]
        obs = observed_from_nocternal(args.nocternal, aliases, label)
        # intent = every AP the collector knows, expected in service; SSIDs = the ones clients use (no config check)
        intent = {"site": label, "sla_tier": "standard", "nocternal_network": aliases,
                  "access_points": [{"name": a["name"], "serial": a["serial"], "model": a["model"], "mac": None,
                                     "mgmt_ip": None, "lifecycle": "in_service"} for a in obs["access_points"]],
                  "ssids": [{"name": s["name"]} for s in obs["ssids"]]}
        rep = compare(intent, obs, "fleet")
        k = defaultdict(int)
        for f in rep.findings:
            k[f.kind] += 1
        statuses = defaultdict(int)
        for a in obs["access_points"]:
            statuses[a["status"] or "unknown"] += 1
        crit = sum(1 for f in rep.findings if f.severity == "crit")
        rows.append({"site": label, "aps": len(obs["access_points"]), "online": statuses["online"],
                     "alerting": statuses["alerting"], "dormant": statuses["dormant"], "offline": statuses["offline"],
                     "evil_twin": k["EVIL_TWIN"], "rogue_wired": k["ROGUE"], "neighbors": k["NEIGHBOR"],
                     "client_ssids": len(obs["ssids"]), "crit": crit,
                     "warn": sum(1 for f in rep.findings if f.severity == "warn")})
        allfind[label] = [f.__dict__ for f in rep.findings]

    rows.sort(key=lambda r: (-r["crit"], -r["warn"], r["site"]))
    shown = rows[: args.top] if args.top else rows

    hdr = f"{'site':<34} {'APs':>5} {'online':>6} {'alert':>5} {'dorm':>5} {'off':>4} {'evil':>4} {'rogue':>5} {'nbr':>4} {'ssids':>5} {'crit':>4} {'warn':>4}"
    print(hdr)
    print("-" * len(hdr))
    for r in shown:
        print(f"{r['site'][:34]:<34} {r['aps']:>5} {r['online']:>6} {r['alerting']:>5} {r['dormant']:>5} {r['offline']:>4} "
              f"{r['evil_twin']:>4} {r['rogue_wired']:>5} {r['neighbors']:>4} {r['client_ssids']:>5} {r['crit']:>4} {r['warn']:>4}")
    print("-" * len(hdr))
    t = {key: sum(r[key] for r in rows) for key in ("aps", "online", "alerting", "dormant", "offline", "evil_twin", "rogue_wired", "crit", "warn")}
    sites_crit = sum(1 for r in rows if r["crit"])
    sites_evil = sum(1 for r in rows if r["evil_twin"])
    sites_rogue = sum(1 for r in rows if r["rogue_wired"])
    print(f"{len(rows)} sites, {t['aps']} APs: {t['online']} online, {t['alerting']} alerting, {t['dormant']} dormant, {t['offline']} offline")
    print(f"{sites_crit} sites with critical drift — {sites_evil} with an evil twin on the wire ({t['evil_twin']} BSSIDs), "
          f"{sites_rogue} with a rogue bridged to the LAN ({t['rogue_wired']} BSSIDs); {t['warn']} degraded-AP warnings fleet-wide")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"summary": rows, "findings": allfind}, fh, indent=2, default=str)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
