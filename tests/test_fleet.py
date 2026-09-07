"""fleet_drift against a synthetic NOCternal-shaped store: split networks group by stem, findings roll up."""
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fleet_drift import site_groups, stem  # noqa: E402


def make_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE device_state (serial TEXT PRIMARY KEY, org TEXT, network TEXT, product_type TEXT, model TEXT, name TEXT, status TEXT, updated_at TEXT NOT NULL, tags TEXT);
    CREATE TABLE rogue_aps (network TEXT, ssid TEXT, bssid TEXT, channel TEXT, rssi INTEGER, on_wire INTEGER, is_spoof INTEGER, first_seen TEXT, last_seen TEXT, updated_at TEXT NOT NULL, triage TEXT, triage_note TEXT, PRIMARY KEY(network,bssid,ssid));
    CREATE TABLE client_info (mac TEXT, network_id TEXT, network TEXT, connection TEXT, ssid TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(mac,network_id));
    """)
    for i in range(1, 4):
        for j in range(1, 6):
            c.execute("INSERT INTO device_state VALUES (?,?,?,?,?,?,?,?,?)",
                      (f"Q-{i}-{j}", "o", f"Alpha {i} - wireless", "wireless", "MR44", f"AP{j}",
                       "alerting" if (i == 2 and j == 5) else "online", "t", ""))
    c.execute("INSERT INTO rogue_aps VALUES ('Alpha 2 - 60001','Corp','aa:bb:cc:dd:ee:01','6',-40,1,1,'t','t','t',NULL,NULL)")
    c.execute("INSERT INTO client_info VALUES ('m1','n','Alpha 2 - 60001','Wireless','Corp','t')")
    c.commit()


def test_stem_and_grouping():
    assert stem("Maple Court  - wireless") == "maple court" and stem("Maple Court - 60019") == "maple court"
    with tempfile.TemporaryDirectory() as d:
        db = pathlib.Path(d) / "events.db"
        make_db(db)
        g = site_groups(str(db))
        assert set(g) == {"alpha 1", "alpha 2", "alpha 3"}
        assert g["alpha 2"]["aliases"] == {"Alpha 2 - wireless", "Alpha 2 - 60001"}


def test_cli_summary():
    with tempfile.TemporaryDirectory() as d:
        db = pathlib.Path(d) / "events.db"
        make_db(db)
        r = subprocess.run([sys.executable, str(ROOT / "fleet_drift.py"), "--nocternal", str(db), "--anonymize"],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, r.stderr
        assert "3 sites, 15 APs" in r.stdout and "1 with an evil twin on the wire" in r.stdout
        assert "Alpha" not in r.stdout                      # --anonymize really anonymizes


if __name__ == "__main__":
    test_stem_and_grouping(); test_cli_summary(); print("fleet tests ok")
