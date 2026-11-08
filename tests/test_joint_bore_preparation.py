"""Physical branch-bore continuation, without executing native geometry."""

from copy import deepcopy

import pytest

from prechips.inputs import Bundle
from prechips.rules import op_chain, op_order

FRAME = {
    "origin": [0, 0, 0],
    "x": [1, 0, 0],
    "y": [0, 1, 0],
    "z": [0, 0, 1],
    "binding": "synthetic bore preparation fixture",
}


@pytest.fixture
def bore_route(tmp_path):
    return Bundle(
        plan={
            "stock": {"components": [{"id": "hub"}, {"id": "strap"}]},
            "joint_features": {
                "supply": {
                    "kind": "cylinder_bore",
                    "component": "hub",
                    "at": [0, 8, 4.25],
                    "axis": [0, 0, -1],
                    "dia": [6.2484, 6.35],
                    "nominal_dia": 6.2484,
                    "depth": 10,
                    "thru": False,
                    "cite": "synthetic CAD detail",
                }
            },
            "setups": [
                {
                    "id": "H1",
                    "stock_in": "stock.hub",
                    "frame": "model",
                    "ops": [
                        {"op": 40, "do": "spot", "feature": "supply"},
                        {"op": 50, "do": "drill", "feature": "supply", "tool": "D", "depth_mm": 10},
                    ],
                },
                {"id": "T4", "stock_in": "stock.strap", "ops": []},
                {"id": "J1", "stock_in": ["H1", "T4"], "ops": []},
                {
                    "id": "F1",
                    "stock_in": "J1",
                    "frame": "model",
                    "ops": [
                        {"op": 20, "do": "ream", "feature": "pivot"},
                    ],
                },
            ],
        },
        features={
            "units": "mm",
            "frames": {"model": deepcopy(FRAME)},
            "features": {
                "pivot": {
                    "kind": "hole",
                    "frame": "model",
                    "at": [0, 8, -3.52825],
                    "axis": [0, 0, 1],
                    "depth": 7.0565,
                    "dia": [6.5024, 6.5278],
                    "process": "ream",
                },
            },
        },
        inventory={"tools": {"D": {"dia_mm": 6.2484}}},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def pivot_chain(bundle):
    return next(row for row in op_chain.evaluate(bundle) if row.subject == "pivot")


def test_branch_join_carries_real_spotted_drill_to_final_ream(bore_route):
    row = pivot_chain(bore_route)
    assert row.status == "pass", row.sentence
    proof = row.numbers["preparation_witnesses"][0]
    assert proof["drill"] == "H1:50"
    assert proof["start_preparation"] == "H1:40"
    assert proof["source_feature"] == "supply"
    assert proof["target_feature"] == "pivot"
    assert proof["coaxial_full_depth"] is True
    final = next(row for row in op_order.evaluate(bore_route) if row.subject == "F1")
    assert final.status == "pass", final.sentence


@pytest.mark.parametrize(
    "change", ["offset", "skew", "short", "oversize", "other_branch", "not_bore"]
)
def test_unrelated_or_inadequate_bore_does_not_prepare_ream(bore_route, change):
    source = bore_route.plan["joint_features"]["supply"]
    if change == "offset":
        source["at"][0] = 0.1
    elif change == "skew":
        source["axis"] = [0, 0.1, -1]
    elif change == "short":
        bore_route.plan["setups"][0]["ops"][1]["depth_mm"] = 5
    elif change == "oversize":
        bore_route.inventory["tools"]["D"]["dia_mm"] = 6.6
    elif change == "other_branch":
        bore_route.plan["setups"][-1]["stock_in"] = "T4"
    else:
        source["kind"] = "cylinder_spigot"
    assert pivot_chain(bore_route).status == "error"
    final = next(row for row in op_order.evaluate(bore_route) if row.subject == "F1")
    assert final.status == "error"


def test_missing_drill_stroke_remains_debt(bore_route):
    del bore_route.plan["setups"][0]["ops"][1]["depth_mm"]
    assert pivot_chain(bore_route).status == "unknown"


def test_spot_on_supply_bore_is_required(bore_route):
    bore_route.plan["setups"][0]["ops"].pop(0)
    assert pivot_chain(bore_route).status == "error"


def test_through_bore_uses_operation_local_stock_span_not_axis_anchor(bore_route):
    pivot = bore_route.features["features"]["pivot"]
    del pivot["depth"]
    pivot.update(at=[0, 8, 0], thru=True)
    final = bore_route.plan["setups"][-1]
    final["stock_state"] = {"top_z": 4.25, "local_thickness": {"pivot": 7.77825}}
    final["ops"].insert(0, {"op": 10, "do": "face", "feature": "upper", "to_z": 3.52825})
    assert pivot_chain(bore_route).status == "pass"


@pytest.mark.parametrize("missing_name", ["supply", "pivot"])
def test_both_source_and_finished_material_survival_are_required(
    bore_route, monkeypatch, missing_name
):
    actual = op_chain._material

    def survival(bundle, setup, producer, name, **kwargs):
        if setup["id"] == "F1" and name == missing_name:
            return None
        return actual(bundle, setup, producer, name, **kwargs)

    monkeypatch.setattr(op_chain, "_material", survival)
    assert pivot_chain(bore_route).status == "unknown"


@pytest.mark.parametrize(
    "command,status", [(-10.0, "pass"), (-5.75, "error"), ("unknown", "unknown")]
)
def test_absolute_drill_tip_does_not_credit_its_point_as_full_bore(bore_route, command, status):
    setup = bore_route.plan["setups"][0]
    setup["stock_state"] = {"top_z": 4.25, "entry_z": {"supply": 4.25}}
    setup["ops"][1].update(to_z=command, depth_mm=100.0)
    bore_route.inventory["tools"]["D"]["point_angle"] = 90.0
    # D6.2484/90 degrees has a 3.1242 point. Z-5.75 travels 10 mm,
    # but only 6.8758 mm is full diameter: short of the 7.77825 far end.
    assert pivot_chain(bore_route).status == status


def test_explicit_drill_with_unknown_point_cannot_prepare_full_bore(bore_route):
    setup = bore_route.plan["setups"][0]
    setup["stock_state"] = {"top_z": 4.25, "entry_z": {"supply": 4.25}}
    setup["ops"][1].update(to_z=-10.0, depth_mm=100.0)
    bore_route.inventory["tools"]["D"]["point_angle"] = "unknown"
    assert pivot_chain(bore_route).status == "unknown"
