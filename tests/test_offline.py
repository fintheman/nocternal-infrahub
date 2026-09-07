"""
Offline tests — no Infrahub, no Meraki. Run:  python3 -m pytest -q tests/   (or just: python3 tests/test_offline.py)

Builds the exact GraphQL result shape Infrahub returns for queries/site_intent.gql from the fixture,
then exercises the drift Check and the Jinja2 artifact template against it.
"""
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from drift import compare, intent_from_gql, load_json  # noqa: E402


def gql_result_from_intent(intent: dict) -> dict:
    """What Infrahub answers for site_intent($site) — every attribute wrapped as {value: ...}."""
    w = lambda d, keys: {k: {"value": d.get(k)} for k in keys}  # noqa: E731
    node = {"id": "00000000-0000-0000-0000-000000000001",
            **w(intent, ("name", "meraki_network_id", "nocternal_network", "sla_tier"))}
    node["name"] = {"value": intent["site"]}
    node["access_points"] = {"edges": [{"node": w(a, ("name", "serial", "model", "mac", "mgmt_ip", "floor", "lifecycle", "rf_profile"))}
                                       for a in intent["access_points"]]}
    node["ssids"] = {"edges": [{"node": w(s, ("name", "number", "enabled", "hidden", "auth_mode", "vlan_id", "band"))}
                               for s in intent["ssids"]]}
    return {"WirelessSite": {"edges": [{"node": node}]}}


def test_intent_roundtrip():
    intent = load_json(ROOT / "fixtures/intent_nash_hq.json")
    back = intent_from_gql(gql_result_from_intent(intent)["WirelessSite"]["edges"][0]["node"])
    assert back["site"] == "NASH-HQ" and len(back["access_points"]) == 7 and len(back["ssids"]) == 3
    rep = compare(back, load_json(ROOT / "fixtures/observed_nash_hq.json"), "main")
    assert sum(f.severity == "crit" for f in rep.findings) == 4


def test_check_fails_on_drift():
    from checks.wireless_drift import WirelessDriftCheck
    intent = load_json(ROOT / "fixtures/intent_nash_hq.json")
    chk = WirelessDriftCheck(branch="main", root_directory=str(ROOT), params={"site": "NASH-HQ"})
    passed = asyncio.run(chk.run(data=gql_result_from_intent(intent)))
    errors = [l for l in chk.logs if l["level"] == "ERROR"]
    assert passed is False and len(errors) == 4, chk.logs
    assert any("EVIL_TWIN" in e["message"] for e in errors)


def test_check_passes_when_clean():
    from checks.wireless_drift import WirelessDriftCheck
    intent = load_json(ROOT / "fixtures/intent_nash_hq.json")
    chk = WirelessDriftCheck(branch="main", root_directory=str(ROOT), params={"site": "NASH-HQ"})
    # observed == intent, minus the planned AP, with everything online and no rogues
    observed = {"site": "NASH-HQ",
                "access_points": [{"name": a["name"], "serial": a["serial"], "model": a["model"], "mac": a["mac"],
                                   "lanIp": a["mgmt_ip"], "status": "online"} for a in intent["access_points"] if a["lifecycle"] == "in_service"],
                "ssids": [{"number": s["number"], "name": s["name"], "enabled": s["enabled"], "hidden": s["hidden"],
                           "authMode": {"open": "open", "psk": "psk", "ipsk": "ipsk-with-radius", "dot1x": "8021x-radius"}[s["auth_mode"]],
                           "defaultVlanId": s["vlan_id"],
                           "bandSelection": {"dual": "Dual band operation", "five_only": "5 GHz band only", "six_capable": "6 GHz band only"}[s["band"]]}
                          for s in intent["ssids"]],
                "air_marshal": []}
    chk._observed = lambda intent: observed
    assert asyncio.run(chk.run(data=gql_result_from_intent(intent))) is True, chk.logs


def test_meraki_artifact_template():
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT / "templates")), trim_blocks=False)
    intent = load_json(ROOT / "fixtures/intent_nash_hq_refresh.json")
    out = env.get_template("meraki_ssids.json.j2").render(data=gql_result_from_intent(intent))
    doc = json.loads(out)                      # must be valid JSON
    assert doc["site"] == "NASH-HQ" and len(doc["requests"]) == 3
    corp = next(r for r in doc["requests"] if r["body"]["name"] == "NOCternal-Corp")
    assert corp["path"].endswith("/wireless/ssids/0") and corp["body"]["authMode"] == "8021x-radius"
    assert corp["body"]["defaultVlanId"] == 110 and "_note" in corp["body"]
    assert "${PSK_" in json.dumps(doc)         # secrets never rendered
    globals()["_last_render"] = out


if __name__ == "__main__":
    test_intent_roundtrip(); print("intent roundtrip      ok")
    test_check_fails_on_drift(); print("check fails on drift  ok")
    test_check_passes_when_clean(); print("check passes clean    ok")
    test_meraki_artifact_template(); print("artifact template     ok\n"); print(_last_render)  # noqa: F821
