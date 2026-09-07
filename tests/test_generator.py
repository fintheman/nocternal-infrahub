"""The generator's decision logic is a pure function; the IO around it is a thin InfrahubGenerator. Test the decision."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generators.site_wireless import STANDARDS, plan  # noqa: E402


def test_every_vertical_has_three_distinct_slots():
    for vertical, rows in STANDARDS.items():
        assert len(rows) == 3, vertical
        assert len({r["number"] for r in rows}) == 3 and len({r["name"] for r in rows}) == 3, vertical
        assert all(r["auth_mode"] in ("open", "psk", "ipsk", "dot1x") for r in rows)
        assert all(r["band"] in ("dual", "five_only", "six_capable") for r in rows)


def test_healthcare_plan_creates_and_adopts():
    rows = plan("healthcare", existing={"Guest": {"id": "guest-uuid"}})
    by = {r["name"]: r for r in rows}
    assert by["Clinical"]["action"] == "create" and by["Clinical"]["auth_mode"] == "dot1x"
    assert by["Guest"]["action"] == "adopt" and by["Guest"]["id"] == "guest-uuid"
    assert by["Biomed"]["hidden"] is True and by["Biomed"]["auth_mode"] == "ipsk"


def test_no_vertical_means_no_generation():
    assert plan(None, {}) == [] and plan("", {}) == [] and plan("spaceport", {}) == []


def test_generator_class_is_wired():
    import yaml
    from infrahub_sdk.generator import InfrahubGenerator
    from generators.site_wireless import SiteWirelessGenerator
    assert issubclass(SiteWirelessGenerator, InfrahubGenerator)
    cfg = yaml.safe_load((ROOT / ".infrahub.yml").read_text())
    gen = next(g for g in cfg["generator_definitions"] if g["name"] == "site_wireless_standard")
    assert gen["class_name"] == "SiteWirelessGenerator" and gen["targets"] == "wireless_sites"
    assert gen["query"] in {q["name"] for q in cfg["queries"]}
    assert "vertical" in (ROOT / "queries/site_intent.gql").read_text()


if __name__ == "__main__":
    test_every_vertical_has_three_distinct_slots(); test_healthcare_plan_creates_and_adopts()
    test_no_vertical_means_no_generation(); test_generator_class_is_wired(); print("generator tests ok")
