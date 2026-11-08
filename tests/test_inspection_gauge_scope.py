"""Limit pairs belong to authored features, not touching faces or sibling blanks."""

from dataclasses import replace

import pytest
from test_practical_inspection import practical_bundle

from prechips.rules import inspection

DEFINITIONS = {
    "hub_land": {"kind": "shaft", "faces": ["#1"], "dia": [10.18, 10.20]},
    "hub_supply_bore": {"kind": "hole", "faces": ["#2"], "dia": [6.24, 6.35]},
    "strap_socket": {"kind": "hole", "faces": ["#3"], "dia": [10.16, 10.18]},
    "rod_hole": {"kind": "hole", "faces": ["#4"], "dia": [2.0, 2.09]},
}


def gauge_scope_bundle():
    """Use the real split-route host fixture; no native survival proof is required."""
    bundle = replace(
        practical_bundle(),
        features={
            "units": "mm",
            "features": {
                name: {**definition, "requirements": ["dia"]}
                for name, definition in DEFINITIONS.items()
            },
        },
        inventory={"gauges": {}},
    )
    for setup in bundle.plan["setups"]:
        setup["ops"] = [op for op in setup["ops"] if op["do"] == "cut_off"]
    for setup in bundle.plan["setups"][-4:]:
        member = f"nut{setup['id'][-1]}"
        for index, (name, definition) in enumerate(DEFINITIONS.items(), 1):
            gauge = f"{name}-limits"
            low, high = definition["dia"]
            external = definition["kind"] == "shaft"
            bundle.inventory["gauges"][gauge] = {
                "kind": "ring_gauge" if external else "plug_gauge",
                "sizes_mm": [low, high],
            }
            setup["ops"].append(
                {
                    "op": index * 10,
                    "do": "inspect",
                    "feature": name,
                    # The whole piece is touched/used as a datum at each station.
                    # Physical overlap must not turn a flat dia entry into a check
                    # of the three unrelated diameters on this same member.
                    "workpiece_faces": {member: ["#1", "#2", "#3", "#4"]},
                    "checks": {"dia": gauge},
                    "go_no_go": {
                        "dia": {
                            "go": high if external else low,
                            "no_go": low if external else high,
                        },
                    },
                }
            )
    return bundle


def findings(bundle):
    return {row.subject: row for row in inspection.evaluate(bundle)}


def test_touching_joint_and_datum_faces_does_not_own_their_limit_checks():
    rows = findings(gauge_scope_bundle())
    for member in ("nut1", "nut2", "nut3", "nut4"):
        for index, name in enumerate(DEFINITIONS, 1):
            row = rows[f"{member}/{name}:dia"]
            assert row.status == "pass", row.sentence
            assert row.numbers["identity"] == {
                "workpiece": member,
                "feature_owner": name,
                "requirement": "dia",
            }
            assert row.numbers["op"] == f"E{member[-1]}:{index * 10}"
            assert row.numbers["gauge"] == f"{name}-limits"
            assert "other_go_no_go" not in row.numbers


def test_legacy_route_keeps_flat_pair_with_its_feature_not_overlapping_datums():
    bundle = gauge_scope_bundle()
    del bundle.plan["workpieces"]
    for setup in bundle.plan["setups"][-4:]:
        for op in setup["ops"]:
            op["faces"] = next(iter(op.pop("workpiece_faces").values()))
    rows = findings(bundle)
    for name in DEFINITIONS:
        row = rows[f"{name}:dia"]
        assert row.status == "pass", row.sentence
        assert row.numbers["identity"]["workpiece"] is None
        assert row.numbers["op"] == f"E4:{list(DEFINITIONS).index(name) * 10 + 10}"
        assert "other_go_no_go" in row.numbers
        assert all(
            previous["gauge"] == f"{name}-limits" for previous in row.numbers["other_go_no_go"]
        )


def test_unknown_pair_stays_unresolved_only_for_the_selected_feature_and_member():
    bundle = gauge_scope_bundle()
    bundle.plan["setups"][-3]["ops"][-1]["go_no_go"] = "unknown"
    rows = findings(bundle)
    row = rows["nut2/rod_hole:dia"]
    assert row.status == "unknown"
    assert "GO / NO-GO pair is explicitly unknown" in row.sentence
    assert rows["nut1/rod_hole:dia"].status == "pass"
    for name in ("hub_land", "hub_supply_bore", "strap_socket"):
        assert rows[f"nut2/{name}:dia"].status == "pass"


@pytest.mark.parametrize("failure", ["outside_band", "wrong_gauge_kind"])
def test_earlier_incompatible_pair_still_fails_only_its_feature_and_branch(failure):
    bundle = gauge_scope_bundle()
    setup = bundle.plan["setups"][-3]  # E2, an actual sibling of E1 in the split route.
    rod = setup["ops"][-1]
    setup["ops"].append({**rod, "op": 50})
    if failure == "outside_band":
        rod["go_no_go"] = {"dia": {"go": 1.99, "no_go": 2.09}}
        expected = "GO / NO-GO sizes accept work outside the band"
    else:
        rod["checks"] = {"dia": "hub_land-limits"}
        expected = "named gauge cannot make a GO / NO-GO check of this feature"
    rows = findings(bundle)
    bad = rows["nut2/rod_hole:dia"]
    assert bad.numbers["op"] == "E2:50"  # The final checkpoint itself is capable.
    assert bad.status == "error"
    assert expected in bad.sentence
    assert len(bad.numbers["other_go_no_go"]) == 1
    previous = bad.numbers["other_go_no_go"][0]
    assert previous["op"] == "E2:40"
    assert previous["status"] == "error"
    assert expected in previous["message"]
    assert rows["nut1/rod_hole:dia"].status == "pass"
    assert "other_go_no_go" not in rows["nut1/rod_hole:dia"].numbers
    for name in ("hub_land", "hub_supply_bore", "strap_socket"):
        row = rows[f"nut2/{name}:dia"]
        assert row.status == "pass", row.sentence
        assert "other_go_no_go" not in row.numbers
