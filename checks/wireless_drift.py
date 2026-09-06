"""
wireless_drift — an Infrahub Check: does live wireless reality agree with the intent on this branch?

Runs once per WirelessSite in the `wireless_sites` group whenever a Proposed Change is validated
(see .infrahub.yml). Intent comes from the site_intent GraphQL query on the proposed branch; observed
state comes from, in order of preference:

  NOCTERNAL_DB=/path/events.db   -> NOCternal's event store (device_state / rogue_aps / client_info)
  MERAKI_API_KEY=...             -> Meraki Dashboard API, if the site has a meraki_network_id
  fixtures/observed_<site>.json  -> committed fixture (the demo path; NASH-HQ ships with one)

Critical findings fail the check (red X on the Proposed Change). Warnings and info are logged.
Run locally against a live Infrahub:   infrahubctl check wireless_drift site=NASH-HQ --branch nash-6ghz-refresh
"""
import os
import pathlib
import sys

from infrahub_sdk.checks import InfrahubCheck

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from drift import compare, intent_from_gql, observed_from_meraki, observed_from_nocternal, load_json  # noqa: E402


class WirelessDriftCheck(InfrahubCheck):
    query = "site_intent"

    def _observed(self, intent: dict):
        site = intent["site"]
        if os.environ.get("NOCTERNAL_DB"):
            return observed_from_nocternal(os.environ["NOCTERNAL_DB"], intent.get("nocternal_network") or site, site)
        if os.environ.get("MERAKI_API_KEY") and intent.get("meraki_network_id"):
            return observed_from_meraki(intent["meraki_network_id"], site)
        fixture = ROOT / "fixtures" / f"observed_{site.lower().replace('-', '_')}.json"
        if fixture.exists():
            return load_json(fixture)
        return None

    def validate(self, data: dict) -> None:
        edges = data.get("WirelessSite", {}).get("edges", [])
        if not edges:
            self.log_error(f"WirelessSite {self.params.get('site')!r} not found on branch {self.branch_name}")
            return
        node = edges[0]["node"]
        intent = intent_from_gql(node)
        observed = self._observed(intent)
        if observed is None:
            self.log_info(f"{intent['site']}: no observed-state source (NOCTERNAL_DB / MERAKI_API_KEY / fixture) — nothing to compare")
            return

        rep = compare(intent, observed, self.branch_name)
        for f in sorted(rep.findings, key=lambda f: {"crit": 0, "warn": 1, "info": 2}[f.severity]):
            msg = f"[{f.severity}] {f.kind} {f.object}: {f.detail}"
            if f.severity == "crit":
                self.log_error(msg, object_id=node["id"], object_type="WirelessSite")
            else:
                self.log_info(msg, object_id=node["id"], object_type="WirelessSite")
        n = {s: sum(1 for f in rep.findings if f.severity == s) for s in ("crit", "warn", "info")}
        self.log_info(f"{intent['site']} on {self.branch_name}: {n['crit']} critical, {n['warn']} warning, {n['info']} info")
