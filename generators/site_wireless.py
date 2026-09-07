"""
site_wireless — an Infrahub Generator: the standard SSID set for a site's vertical, created from a template.

Every enterprise wireless team keeps this in a spreadsheet: "a hospital gets clinical/guest/biomed, a venue gets
ops/POS/fan, an office gets corp/guest/IoT". Here it is a Generator. Set `vertical` on a WirelessSite and the
SSIDs appear — in the branch, in the Proposed Change diff, re-run on merge, and removed by Infrahub's tracking
if the vertical changes and they are no longer produced.

    infrahubctl generator site_wireless_standard site=NASH-CLINIC --branch nash-clinic

Hand-made SSIDs on the same site are left alone: the generator only owns what it creates. If a generated name
already exists (someone made "Guest" by hand), it is adopted and brought in line with the standard.
"""
from __future__ import annotations

from infrahub_sdk.generator import InfrahubGenerator

# name, slot, auth, vlan, band, hidden  —  vlan/band are the corporate default; a site can override after generation
STANDARDS: dict[str, list[dict]] = {
    "healthcare": [
        {"name": "Clinical",  "number": 0, "auth_mode": "dot1x", "vlan_id": 110, "band": "five_only",   "hidden": False},
        {"name": "Guest",     "number": 1, "auth_mode": "open",  "vlan_id": 120, "band": "dual",        "hidden": False},
        {"name": "Biomed",    "number": 2, "auth_mode": "ipsk",  "vlan_id": 130, "band": "five_only",   "hidden": True},
    ],
    "venue": [
        {"name": "Ops",       "number": 0, "auth_mode": "dot1x", "vlan_id": 110, "band": "five_only",   "hidden": True},
        {"name": "POS",       "number": 1, "auth_mode": "ipsk",  "vlan_id": 140, "band": "five_only",   "hidden": True},
        {"name": "Fan-WiFi",  "number": 2, "auth_mode": "open",  "vlan_id": 120, "band": "six_capable", "hidden": False},
    ],
    "office": [
        {"name": "Corp",      "number": 0, "auth_mode": "dot1x", "vlan_id": 110, "band": "six_capable", "hidden": False},
        {"name": "Guest",     "number": 1, "auth_mode": "open",  "vlan_id": 120, "band": "dual",        "hidden": False},
        {"name": "IoT",       "number": 2, "auth_mode": "psk",   "vlan_id": 130, "band": "dual",        "hidden": True},
    ],
    "retail": [
        {"name": "Store",     "number": 0, "auth_mode": "dot1x", "vlan_id": 110, "band": "five_only",   "hidden": True},
        {"name": "POS",       "number": 1, "auth_mode": "ipsk",  "vlan_id": 140, "band": "five_only",   "hidden": True},
        {"name": "Guest",     "number": 2, "auth_mode": "open",  "vlan_id": 120, "band": "dual",        "hidden": False},
    ],
}


def plan(vertical: str | None, existing: dict[str, dict]) -> list[dict]:
    """Pure decision: which SSIDs this site should have from its vertical, and whether each is new or adopted.
    `existing` maps SSID name -> {"id": ...} for SSIDs already on the site. Unknown/empty vertical -> nothing."""
    out = []
    for std in STANDARDS.get(vertical or "", []):
        row = {**std, "enabled": True}
        row["action"] = "adopt" if std["name"] in existing else "create"
        row["id"] = existing.get(std["name"], {}).get("id")
        out.append(row)
    return out


class SiteWirelessGenerator(InfrahubGenerator):
    async def generate(self, data: dict) -> None:
        edges = data.get("WirelessSite", {}).get("edges", [])
        if not edges:
            self.logger.warning("generator: site %s not found on this branch", self.params.get("site"))
            return
        site = edges[0]["node"]
        vertical = (site.get("vertical") or {}).get("value")
        existing = {e["node"]["name"]["value"]: {"id": e["node"].get("id")} for e in site.get("ssids", {}).get("edges", [])}

        todo = plan(vertical, existing)
        if not todo:
            self.logger.info("generator: %s has no vertical (or an unknown one: %r) — nothing to generate", site["name"]["value"], vertical)
            return

        for row in todo:
            payload = {"name": row["name"], "number": row["number"], "enabled": True, "hidden": row["hidden"],
                       "auth_mode": row["auth_mode"], "vlan_id": row["vlan_id"], "band": row["band"], "site": site["id"]}
            if row["action"] == "adopt" and row["id"]:
                obj = await self.client.get(kind="WirelessSSID", id=row["id"])
                for k, v in payload.items():
                    if k != "site":
                        setattr(obj, k, v)
            else:
                obj = await self.client.create(kind="WirelessSSID", data=payload)
            await obj.save(allow_upsert=True)
            self.logger.info("generator: %s SSID %s (%s, vlan %s) on %s", row["action"], row["name"], row["auth_mode"], row["vlan_id"], site["name"]["value"])
