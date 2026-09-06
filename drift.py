#!/usr/bin/env python3
"""
drift.py — NOCternal x Infrahub: intended state vs observed state for one wireless site.

  Infrahub answers "what SHOULD be true"   (WirelessSite / WirelessAccessPoint / WirelessSSID)
  NOCternal answers "what IS true"         (Meraki Dashboard API: devices, statuses, SSIDs, Air Marshal)
  drift.py prints the difference.          Exit code 1 if any drift, so it can gate a CI job or a Proposed Change.

Offline (no Infrahub, no Meraki — uses fixtures):
    python drift.py --site NASH-HQ --intent fixtures/intent_nash_hq.json --observed fixtures/observed_nash_hq.json

Live intent from Infrahub, observed from fixture:
    export INFRAHUB_ADDRESS=http://localhost:8000 INFRAHUB_API_TOKEN=06438eb2-8019-4776-878c-0941b1f1d1ec
    python drift.py --site NASH-HQ --observed fixtures/observed_nash_hq.json

Fully live (Infrahub + Meraki):
    export MERAKI_API_KEY=...
    python drift.py --site NASH-HQ

Infrahub intent vs NOCternal's own event store (no Meraki call — this is the integration):
    python drift.py --site SITE --nocternal ../noc-platform/events.db --network "Site - wireless,Site - 60019"

Intent from a branch (the git-style trick: "what would drift look like if we merged this?"):
    python drift.py --site NASH-HQ --branch nash-refresh --observed fixtures/observed_nash_hq.json

Output: a human table on stdout, and --json <file> for the machine-readable version NOCternal ingests.
"""
import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------- normalisation tables
MERAKI_AUTH = {          # Meraki authMode -> schema auth_mode
    "open": "open", "psk": "psk", "ipsk-with-radius": "ipsk", "ipsk-without-radius": "ipsk",
    "8021x-radius": "dot1x", "8021x-meraki": "dot1x", "8021x-google": "dot1x", "8021x-entra": "dot1x",
}
MERAKI_BAND = {          # Meraki bandSelection -> schema band
    "Dual band operation": "dual", "5 GHz band only": "five_only",
    "Dual band operation with Band Steering": "dual", "6 GHz band only": "six_capable",
}
AP_FIELDS = ("name", "model", "mac", "mgmt_ip")           # attributes compared per AP
SSID_FIELDS = ("enabled", "hidden", "auth_mode", "vlan_id", "band")


@dataclass
class Finding:
    kind: str         # MISSING | UNEXPECTED | MISMATCH | DOWN | DEGRADED | SSID_MISSING | SSID_QUIET | SSID_UNEXPECTED | SSID_MISMATCH | ROGUE | EVIL_TWIN | STAGED_LIVE
    severity: str     # crit | warn | info
    object: str
    detail: str
    intent: object = None
    observed: object = None


@dataclass
class Report:
    site: str
    branch: str
    findings: list = field(default_factory=list)

    def add(self, *a, **k):
        self.findings.append(Finding(*a, **k))

    @property
    def drift(self):
        return any(f.severity != "info" for f in self.findings)


# ---------------------------------------------------------------- INTENT (Infrahub)
def intent_from_infrahub(site: str, branch: str) -> dict:
    """Pull the site subtree from Infrahub with the SDK. Same shape as fixtures/intent_*.json."""
    from infrahub_sdk import InfrahubClientSync
    client = InfrahubClientSync()
    s = client.get(kind="WirelessSite", name__value=site, branch=branch,
                   include=["access_points", "ssids"], prefetch_relationships=True, populate_store=True)
    s.access_points.fetch()
    s.ssids.fetch()
    out = {"site": s.name.value, "meraki_network_id": s.meraki_network_id.value,
           "nocternal_network": s.nocternal_network.value,
           "sla_tier": s.sla_tier.value, "access_points": [], "ssids": []}
    for rel in s.access_points.peers:
        a = rel.peer
        out["access_points"].append({
            "name": a.name.value, "serial": a.serial.value, "model": a.model.value, "mac": a.mac.value,
            "mgmt_ip": a.mgmt_ip.value, "floor": a.floor.value, "lifecycle": a.lifecycle.value,
            "rf_profile": a.rf_profile.value})
    for rel in s.ssids.peers:
        x = rel.peer
        out["ssids"].append({
            "name": x.name.value, "number": x.number.value, "enabled": x.enabled.value, "hidden": x.hidden.value,
            "auth_mode": x.auth_mode.value, "vlan_id": x.vlan_id.value, "band": x.band.value})
    return out


# ---------------------------------------------------------------- OBSERVED (Meraki / NOCternal collector)
def observed_from_meraki(network_id: str, site: str) -> dict:
    """
    Live pull straight from the Meraki Dashboard API.
    In NOCternal proper this is replaced by a read from the collector's reconciled history table —
    the shape is deliberately identical to what the collector already stores.
    """
    import requests
    key = os.environ["MERAKI_API_KEY"]
    base = "https://api.meraki.com/api/v1"
    h = {"X-Cisco-Meraki-API-Key": key, "Accept": "application/json"}

    def get(path, **params):
        r = requests.get(base + path, headers=h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    devices = [d for d in get(f"/networks/{network_id}/devices") if d.get("model", "").startswith(("MR", "CW"))]
    org_id = get(f"/networks/{network_id}")["organizationId"]
    status = {d["serial"]: d.get("status") for d in get(f"/organizations/{org_id}/devices/statuses", networkIds=[network_id])}
    ssids = [s for s in get(f"/networks/{network_id}/wireless/ssids") if s.get("enabled") or s.get("name", "").strip()]
    try:
        air = get(f"/networks/{network_id}/wireless/airMarshal", timespan=3600)
    except Exception:
        air = []
    return {
        "site": site,
        "access_points": [{"name": d.get("name"), "serial": d["serial"], "model": d.get("model"), "mac": d.get("mac"),
                           "lanIp": d.get("lanIp"), "status": status.get(d["serial"], "unknown")} for d in devices],
        "ssids": [{"number": s["number"], "name": s["name"], "enabled": s["enabled"], "hidden": s.get("visible") is False,
                   "authMode": s.get("authMode"), "defaultVlanId": s.get("defaultVlanId"),
                   "bandSelection": s.get("bandSelection")} for s in ssids],
        "air_marshal": air,
    }


def observed_from_nocternal(db_path: str, network: str, site: str) -> dict:
    """
    Observed state straight from NOCternal's event store (SQLite) — no Meraki call at all.
      device_state  -> access points (serial, name, model, status)        [meraki_devices.py keeps this current]
      rogue_aps     -> air marshal (ssid, bssid, on_wire, is_spoof)       [meraki_rogue.py, already triaged]
      client_info   -> SSIDs with clients on them = evidence of what is really broadcasting
    NOCternal does not store SSID config or AP MAC/LAN IP, so those come back None and compare() skips them.
    `network` may be a comma-separated list: Meraki sites are often split into several dashboard networks
    ("Site - wireless", "Site - 60019") and NOCternal's tables are keyed on whichever one each collector polls.
    """
    import sqlite3
    names = [n.strip() for n in network.split(",") if n.strip()]
    ph = ",".join("?" * len(names))
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    aps = [{"name": r["name"], "serial": r["serial"], "model": r["model"], "mac": None, "lanIp": None,
            "status": r["status"], "updated_at": r["updated_at"]}
           for r in c.execute("SELECT serial, name, model, status, updated_at FROM device_state "
                              f"WHERE product_type='wireless' AND network IN ({ph})", names)]
    ssids = [{"number": None, "name": r["ssid"], "enabled": True, "hidden": None, "authMode": None,
              "defaultVlanId": None, "bandSelection": None, "clients": r["n"]}
             for r in c.execute(f"SELECT ssid, COUNT(*) AS n FROM client_info WHERE network IN ({ph}) AND ssid IS NOT NULL "
                                "AND ssid != '' AND connection='Wireless' GROUP BY ssid", names)]
    air = []
    for r in c.execute("SELECT ssid, bssid, on_wire, is_spoof, last_seen, COALESCE(triage,'') AS triage "
                       f"FROM rogue_aps WHERE network IN ({ph})", names):
        if r["triage"] in ("known-innocent", "ignored"):
            continue
        air.append({"ssid": r["ssid"], "bssids": [{"bssid": r["bssid"]}],
                    "wiredMacs": [r["bssid"]] if r["on_wire"] else [], "lastSeen": r["last_seen"]})
    return {"site": site, "source": f"nocternal:{network}", "ssid_evidence": "clients",
            "access_points": aps, "ssids": ssids, "air_marshal": air}


def normalise_observed(obs: dict) -> dict:
    """Map Meraki field names/values onto the schema vocabulary so the comparison is apples to apples."""
    aps = {}
    for a in obs["access_points"]:
        aps[a["serial"]] = {"name": a.get("name"), "model": a.get("model"), "mac": (a.get("mac") or "").lower() or None,
                            "mgmt_ip": a.get("lanIp"), "status": a.get("status")}
    ssids = {}
    for s in obs["ssids"]:
        if not s.get("name") or s["name"].startswith("Unconfigured SSID"):
            continue
        ssids[s["name"]] = {"number": s.get("number"), "enabled": bool(s.get("enabled")), "hidden": bool(s.get("hidden")),
                            "auth_mode": MERAKI_AUTH.get(s.get("authMode"), s.get("authMode")),
                            "vlan_id": s.get("defaultVlanId"), "band": MERAKI_BAND.get(s.get("bandSelection"), s.get("bandSelection"))}
    return {"access_points": aps, "ssids": ssids, "air_marshal": obs.get("air_marshal", []),
            "ssid_evidence": obs.get("ssid_evidence", "config")}


# ---------------------------------------------------------------- COMPARE
def _host(ip):
    """'10.20.1.11/32' -> '10.20.1.11'; None stays None."""
    if not ip:
        return ip
    ip = str(ip)
    return ip.split("/", 1)[0] if ip.endswith(("/32", "/128")) else ip


def compare(intent: dict, observed: dict, branch: str) -> Report:
    rep = Report(site=intent["site"], branch=branch)
    obs = normalise_observed(observed)
    crit_site = intent.get("sla_tier") == "critical"

    # ---- access points: join on serial
    intent_aps = {a["serial"]: a for a in intent["access_points"]}
    for serial, want in intent_aps.items():
        have = obs["access_points"].get(serial)
        lc = want.get("lifecycle", "in_service")
        if have is None:
            if lc == "in_service":
                rep.add("MISSING", "crit", want["name"], "in intent as in_service but NOT in the dashboard", want, None)
            elif lc == "planned":
                rep.add("PLANNED", "info", want["name"], "planned in intent, not claimed yet (expected)", want, None)
            continue
        if lc == "decommissioned":
            rep.add("DECOM_LIVE", "warn", want["name"], "decommissioned in intent but still present in dashboard", want, have)
            continue
        if lc in ("planned", "staged"):
            rep.add("STAGED_LIVE", "warn", want["name"], f"lifecycle={lc} in intent but device is already in the network", want, have)
        st = have["status"]
        if st == "offline":
            rep.add("DOWN", "crit" if crit_site else "warn", want["name"], "intent in_service, dashboard says offline", "online", st)
        elif st not in ("online", None):        # alerting / dormant: reachable, but not healthy
            rep.add("DEGRADED", "warn", want["name"], f"intent in_service, dashboard says {st}", "online", st)
        for f in AP_FIELDS:
            w, h = want.get(f), have.get(f)
            if f == "mac" and w:
                w = w.lower()
            if f == "mgmt_ip":      # Infrahub IPHost carries a prefix length (10.20.1.11/32); Meraki lanIp does not
                w = _host(w)
                h = _host(h)
            if w is None or h is None:
                continue
            if str(w) != str(h):
                rep.add("MISMATCH", "warn", f"{want['name']}.{f}", f"intent={w!r} observed={h!r}", w, h)
    for serial, have in obs["access_points"].items():
        if serial not in intent_aps:
            rep.add("UNEXPECTED", "warn", have.get("name") or serial,
                    f"{have.get('model')} {serial} is in the dashboard but not in the source of truth", None, have)

    # ---- SSIDs: join on name
    intent_ssids = {s["name"]: s for s in intent["ssids"]}
    for name, want in intent_ssids.items():
        have = obs["ssids"].get(name)
        if have is None:
            if obs["ssid_evidence"] == "clients":
                rep.add("SSID_QUIET", "info", name, "in intent; no clients seen on it in NOCternal's window (config not checked)", want, None)
            else:
                rep.add("SSID_MISSING", "crit", name, "SSID in intent but not configured/enabled", want, None)
            continue
        for f in SSID_FIELDS:
            w, h = want.get(f), have.get(f)
            if w is None or h is None:
                continue
            if w != h:
                sev = "crit" if f == "auth_mode" else "warn"
                rep.add("SSID_MISMATCH", sev, f"{name}.{f}", f"intent={w!r} observed={h!r}", w, h)
    for name, have in obs["ssids"].items():
        if name not in intent_ssids:
            if obs["ssid_evidence"] == "clients":
                rep.add("SSID_UNEXPECTED", "warn", name, "clients are associating to an SSID that is not in intent", None, have)
            else:
                sev = "crit" if have.get("auth_mode") in ("open", "psk") else "warn"
                rep.add("SSID_UNEXPECTED", sev, name, f"broadcasting ({have.get('auth_mode')}, vlan {have.get('vlan_id')}) with no entry in intent", None, have)

    # ---- over the air: anything Air Marshal saw
    our_bssid_prefixes = {(a.get("mac") or "")[:8].lower() for a in intent["access_points"] if a.get("mac")}
    for entry in obs["air_marshal"]:
        ssid = entry.get("ssid")
        for b in entry.get("bssids", []):
            bssid = (b.get("bssid") or "").lower()
            ours = bssid[:8] in our_bssid_prefixes
            if ssid in intent_ssids and not ours:
                rep.add("EVIL_TWIN", "crit", ssid, f"our SSID name broadcast from a BSSID we don't own: {bssid}"
                        + (" (seen on the WIRE)" if bssid in [m.lower() for m in entry.get("wiredMacs", [])] else ""), None, bssid)
            elif ssid not in intent_ssids and entry.get("wiredMacs"):
                rep.add("ROGUE", "crit", ssid, f"unknown SSID from {bssid}, bridged to our LAN", None, bssid)
            elif ssid not in intent_ssids:
                rep.add("NEIGHBOR", "info", ssid, f"foreign SSID from {bssid}, not on our wire", None, bssid)
    return rep


# ---------------------------------------------------------------- OUTPUT
SEV_ORDER = {"crit": 0, "warn": 1, "info": 2}


def print_report(rep: Report, intent_src: str = "Infrahub", observed_src: str = "Meraki"):
    print(f"\nNOCternal drift report — site {rep.site}   intent: {intent_src}@{rep.branch}   observed: {observed_src}")
    print("=" * 96)
    if not rep.findings:
        print("no findings — reality matches intent")
    for f in sorted(rep.findings, key=lambda f: (SEV_ORDER[f.severity], f.kind, f.object)):
        flag = {"crit": "!!", "warn": " !", "info": "  "}[f.severity]
        print(f"{flag} {f.severity:<4} {f.kind:<15} {f.object:<28} {f.detail}")
    n = {s: sum(1 for f in rep.findings if f.severity == s) for s in SEV_ORDER}
    print("-" * 96)
    print(f"{n['crit']} critical, {n['warn']} warning, {n['info']} info   ->   {'DRIFT' if rep.drift else 'CLEAN'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, help="WirelessSite.name in Infrahub, e.g. NASH-HQ")
    ap.add_argument("--branch", default="main", help="Infrahub branch to read intent from")
    ap.add_argument("--intent", help="JSON file instead of Infrahub (offline/demo)")
    ap.add_argument("--observed", help="JSON file instead of Meraki (offline/demo)")
    ap.add_argument("--nocternal", metavar="EVENTS_DB", help="read observed state from NOCternal's SQLite store instead of Meraki")
    ap.add_argument("--network", help="NOCternal network name for --nocternal (default: intent's nocternal_network, else --site)")
    ap.add_argument("--json", help="write findings to this file")
    args = ap.parse_args()

    intent = json.load(open(args.intent)) if args.intent else intent_from_infrahub(args.site, args.branch)
    if args.observed:
        observed = json.load(open(args.observed))
    elif args.nocternal:
        observed = observed_from_nocternal(args.nocternal, args.network or intent.get("nocternal_network") or args.site, args.site)
    else:
        nid = intent.get("meraki_network_id")
        if not nid:
            sys.exit("site has no meraki_network_id in Infrahub and no --observed file given")
        observed = observed_from_meraki(nid, args.site)

    rep = compare(intent, observed, args.branch)
    print_report(rep,
                 intent_src=f"file:{os.path.basename(args.intent)}" if args.intent else "Infrahub",
                 observed_src=f"file:{os.path.basename(args.observed)}" if args.observed
                 else observed.get("source", "Meraki"))
    if args.json:
        json.dump({"site": rep.site, "branch": rep.branch, "drift": rep.drift,
                   "findings": [asdict(f) for f in rep.findings]}, open(args.json, "w"), indent=2, default=str)
        print(f"wrote {args.json}")
    return 1 if rep.drift else 0


if __name__ == "__main__":
    sys.exit(main())
