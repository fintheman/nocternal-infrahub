"""Builds a minimal synthetic .esx (the real thing is a zip of these same JSON files) and runs the importer on it."""
import json
import pathlib
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bootstrap_from_ekahau import planned_aps, read_esx  # noqa: E402


def make_esx(path):
    floors = [{"id": "f1", "name": "3"}, {"id": "f2", "name": "4"}]
    aps = [
        {"id": "a1", "name": "NASH-HQ-AP-3F-08", "vendor": "Cisco Meraki", "model": "CW9166I", "mine": True,
         "location": {"floorPlanId": "f1", "coord": {"x": 12.3, "y": 45.6}}},
        {"id": "a2", "name": "NASH-HQ-AP-4F-09", "vendor": "Cisco", "model": "Meraki MR57 (external antenna)", "mine": True,
         "location": {"floorPlanId": "f2", "coord": {"x": 70.0, "y": 8.25}}},
        {"id": "a3", "name": "NASH-HQ-AP-1F-01", "vendor": "Cisco Meraki", "model": "MR57", "mine": True,
         "location": {"floorPlanId": "f1", "coord": {"x": 1, "y": 1}}},          # measured: already installed
        {"id": "a4", "name": "xfinitywifi-neighbour", "vendor": "Comcast", "model": "?", "mine": False,
         "location": {"floorPlanId": "f1", "coord": {"x": 0, "y": 0}}},          # not ours
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"name": "NASH-HQ expansion"}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": floors}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": aps}))
        z.writestr("simulatedRadios.json", json.dumps({"simulatedRadios": [
            {"id": "r1", "accessPointId": "a1", "radioTechnology": "802.11ax"},
            {"id": "r2", "accessPointId": "a2", "radioTechnology": "802.11ax"}]}))
        z.writestr("measuredRadios.json", json.dumps({"measuredRadios": [
            {"id": "m1", "accessPointId": "a3"}, {"id": "m2", "accessPointId": "a4"}]}))


def test_planned_from_esx():
    with tempfile.TemporaryDirectory() as d:
        esx = pathlib.Path(d) / "nash.esx"
        make_esx(esx)
        aps = planned_aps(read_esx(str(esx)), "NASH-HQ")
        assert [a["name"] for a in aps] == ["NASH-HQ-AP-3F-08", "NASH-HQ-AP-4F-09"]
        assert aps[0]["model"] == "CW9166I" and aps[1]["model"] == "MR57"
        assert aps[0]["floor"] == "3" and aps[0]["lifecycle"] == "planned"
        assert aps[0]["serial"] == "PLANNED-NASH-HQ-NASH-HQ-AP-3F-08"


def test_merge_cli_then_drift():
    with tempfile.TemporaryDirectory() as d:
        esx = pathlib.Path(d) / "nash.esx"
        make_esx(esx)
        merged = pathlib.Path(d) / "intent.json"
        merged.write_text((ROOT / "fixtures/intent_nash_hq.json").read_text())
        r = subprocess.run([sys.executable, str(ROOT / "bootstrap_from_ekahau.py"), "--esx", str(esx), "--site", "NASH-HQ",
                            "--merge", str(merged)], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, r.stderr
        assert len(json.loads(merged.read_text())["access_points"]) == 9          # 7 + 2 planned
        r = subprocess.run([sys.executable, str(ROOT / "drift.py"), "--site", "NASH-HQ", "--intent", str(merged),
                            "--observed", str(ROOT / "fixtures/observed_nash_hq.json")], capture_output=True, text=True, cwd=ROOT)
        assert "PLANNED         NASH-HQ-AP-3F-08" in r.stdout and "4 critical, 3 warning, 4 info" in r.stdout, r.stdout


if __name__ == "__main__":
    test_planned_from_esx(); print("planned from esx   ok")
    test_merge_cli_then_drift(); print("merge + drift      ok")
