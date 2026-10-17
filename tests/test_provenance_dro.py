"""Declared instruction precision is separate from certification of the DRO grid.

All geometry here is synthetic bundle data; these regressions launch no kernel and do
not read or alter a real shop inventory.
"""

from copy import deepcopy
from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.measurements import measurement_checklist
from prechips.rules import consistency, coordinates, tip_endpoints
from prechips.rules.zero_recipe import rule as zero_recipe_rule
from prechips.rules.zero_recipe import tool_setting as zero_recipe_tool_setting
from prechips.sheet import _Traveler

FRAME = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "nominal",
}


def fact(status="measured", value=0.005):
    return {
        "value": value,
        "measured": {
            "status": status,
            "by": "synthetic fixture operator",
            "date": "2026-10-01",
            "instrument": "synthetic DRO verification",
        },
    }


def resolution_cases():
    legacy = fact()
    legacy["measured"].pop("status")
    incomplete = fact()
    incomplete["measured"].pop("instrument")
    return [
        pytest.param(None, "missing", 0.001, id="absent"),
        pytest.param("unknown", "missing", 0.001, id="declared-unknown"),
        pytest.param(0.005, "nominal", 0.005, id="bare-unmeasured"),
        pytest.param(legacy, "assumed", 0.005, id="legacy-status-absent"),
        pytest.param(fact("assumed"), "assumed", 0.005, id="assumed"),
        pytest.param(fact("illustrative"), "illustrative", 0.005, id="illustrative"),
        pytest.param(incomplete, "measured", 0.005, id="incomplete-measured"),
        pytest.param({**fact(), "verify": True}, "measured", 0.005, id="verify-true"),
        pytest.param({**fact(), "verify": "unknown"}, "measured", 0.005, id="verify-unknown"),
        pytest.param(fact(), None, 0.005, id="complete-measured"),
        pytest.param({**fact(), "verify": False}, None, 0.005, id="measured-verify-false"),
    ]


def bundle(resolution):
    machine = {"kind": "mill", "name": "Synthetic mill"}
    if resolution is not None:
        machine["resolution_mm"] = deepcopy(resolution)
    scene = {
        "closest_cut": {"op": "10", "mm": 2.8045, "tag": "fixture:pad"},
        "cut_clearances": [{"op": "10", "mm": 2.8045, "tag": "fixture:pad"}],
    }
    return Bundle(
        plan={
            "dro": {
                "controller": "el400",
                "mode": "abs",
                "radius_mode": False,
                "direction": {"x": "right", "y": "away", "z": "up"},
            },
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "F",
                    "stock_state": {"top_z": 7.938, "bottom_z": 0.0},
                    "ops": [
                        {
                            "op": 10,
                            "do": "drill",
                            "feature": "hole",
                            "tool": "drill",
                            "depth_mm": 2.0,
                        }
                    ],
                }
            ],
        },
        inventory={
            "machines": {"mill": machine},
            "tools": {
                "drill": {"kind": "drill", "dia_mm": 1.0, "point_angle": 118.0},
                "cutter": {"kind": "endmill", "dia_mm": 4.0},
                "finder": {"kind": "edge_finder", "tip_mm": 4.0, "finder_type": "electronic"},
            },
        },
        features={
            "units": "mm",
            "frames": {"F": deepcopy(FRAME), "model": deepcopy(FRAME)},
            "features": {
                "hole": {
                    "kind": "hole",
                    "frame": "model",
                    "at": [1.002, 2.003, 7.938],
                    "dia": [0.95, 1.05],
                    "depth": [1.0, 6.0],
                    "thru": False,
                    "requirements": ["dia", "depth"],
                }
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={
            "status": "ok",
            "setups": {
                "S1": {
                    "stock_bbox_mm": [-5.0, -5.0, 0.0, 5.0, 5.0, 7.938],
                    "render_scene": scene,
                }
            },
        },
    )


def zero(top):
    return {
        "x": {"edge_mm": 0.0, "from": "-x", "tool": "finder", "check_jog_mm": 5.0},
        "y": {"edge_mm": 0.0, "from": "-y", "tool": "finder", "check_jog_mm": 5.0},
        "z": {
            "face": "top",
            "edge_mm": top,
            "from": "+z",
            "tool": "cutter",
            "method": "touch",
            "paper_mm": 0.0,
            "check_jog_mm": 5.0,
            "retouch_after": [],
        },
        "tool_touches": [],
    }


def face_bundle(resolution, stands=7.5):
    """A face cut on a verified 0.001 grid, then touched on the tested machine's grid.

    At 7.497 the face really stands off a 0.005 grid; it is not hand-forged rule output.
    """
    data = bundle(resolution)
    receiving = data.plan["setups"][0]
    receiving.update(
        stock_in="S0",
        stock_state={"top_z": stands, "top_feature": "deck"},
        zero=zero(stands),
        ops=[],
    )
    data.features["features"]["deck"] = {
        "kind": "face",
        "frame": "model",
        "bounds": {"x": [-5.0, 5.0], "y": [-5.0, 5.0], "z": [stands, stands]},
    }
    data.inventory["machines"]["fine_mill"] = {
        "kind": "mill",
        "resolution_mm": fact(value=0.001),
    }
    data.plan["setups"].insert(
        0,
        {
            "id": "S0",
            "machine": "fine_mill",
            "stock_in": "stock",
            "frame": "F",
            "stock_state": {"top_z": 10.0, "top_feature": "deck"},
            "zero": zero(10.0),
            "ops": [
                {
                    "op": 10,
                    "do": "face",
                    "feature": "deck",
                    "tool": "cutter",
                    "to_z": stands,
                }
            ],
        },
    )
    return data


def receiving_zero(data):
    return next(row for row in zero_recipe_rule.evaluate(data) if row.subject == "S1")


def assert_grid_debt(row, debt_status):
    if debt_status is None:
        assert row.status == "pass", row.sentence
        assert "dro_grid_debt" not in row.numbers
        assert not row.numbers.get("measurements")
        return
    assert row.status == "unknown", row.sentence
    assert row.numbers["dro_grid_debt"]
    (entry,) = row.numbers["measurements"]
    assert entry["id"] == "machines.mill.resolution"
    assert entry["status"] == debt_status
    assert entry["units"] == "mm"
    assert entry["instruction"].startswith("measure:")
    assert entry["reason"]
    assert "inventory.machines.mill.resolution" in entry["cite"]
    assert measurement_checklist([row]) == [entry]


@pytest.mark.parametrize(("resolution", "debt_status", "step"), resolution_cases())
def test_declared_grid_and_every_judging_consumer_follow_the_trust_status_matrix(
    resolution, debt_status, step
):
    data = bundle(resolution)
    setup = data.plan["setups"][0]
    assert coordinates.dro_grid(data, setup) == (step, 3)
    assert bool(coordinates.dro_grid_debt(data, setup)) == (debt_status is not None)
    coordinate_row = coordinates.evaluate(data)[0]
    assert coordinate_row.numbers["dro_grid"] == {"step": step, "decimals": 3}
    endpoint_row = tip_endpoints.evaluate(data)[0]
    assert endpoint_row.rule == "blind_depth"
    for row in (
        coordinate_row,
        endpoint_row,
        consistency.evaluate(data)[0],
        receiving_zero(face_bundle(resolution)),
    ):
        assert_grid_debt(row, debt_status)


def test_assumed_0005_grid_never_certifies_a_face_standing_at_7497():
    data = face_bundle(fact("assumed"), stands=7.497)
    receiving = data.plan["setups"][1]
    assert zero_recipe_tool_setting.face_stands(data, receiving, "top", 7.497) == 7.497
    assert coordinates.dro_grid(data, receiving) == (0.005, 3)
    assert_grid_debt(receiving_zero(data), "assumed")
    # Changing only the resolution's provenance reinstates the real off-grid error,
    # rather than accepting the face on a fabricated 0.001 grid.
    data.inventory["machines"]["mill"]["resolution_mm"]["measured"]["status"] = "measured"
    row = receiving_zero(data)
    assert row.status == "error"
    assert "7.497" in row.sentence and "7.5" in row.sentence
    assert "dro_grid_debt" not in row.numbers


def test_consistency_verdict_changes_when_only_resolution_status_changes():
    data = bundle(fact())
    scene = deepcopy(data.kernel["setups"]["S1"]["render_scene"])
    verified = consistency.evaluate(data)[0]
    assert verified.status == "pass"
    data.inventory["machines"]["mill"]["resolution_mm"]["measured"]["status"] = "assumed"
    assert_grid_debt(consistency.evaluate(data)[0], "assumed")
    assert data.kernel["setups"]["S1"]["render_scene"] == scene


@pytest.mark.parametrize("status", ["assumed", "illustrative", "measured"])
def test_trial_like_axial_instructions_keep_z7500_and_one_declared_grid_pass(status):
    data = bundle(fact(status))
    setup = data.plan["setups"][0]
    setup["stock_state"] = {"top_z": 7.9375}
    setup["ops"] = [
        {
            "op": 10,
            "do": "face",
            "feature": "deck",
            "tool": "cutter",
            "to_z": 7.497,
            "doc_mm": 0.4405,
        }
    ]
    data.features["features"]["deck"] = {"kind": "face", "requirements": []}
    row = coordinates.evaluate(data)[0]
    (operation,) = row.numbers["operations"]
    assert operation["dro_to_z"] == 7.5
    assert operation["z_levels"]["dro_start_z"] == 7.94
    assert operation["z_levels"]["levels"] == [7.5]
    assert operation["z_levels"]["count"] == 1
    traveler = _Traveler(data, [row], {}, None)
    traveler.setup = setup
    assert traveler.operative(operation["dro_to_z"]) == "7.500"
    assert "7.498" not in str(operation["z_levels"])
    assert "7.497" not in str(operation["z_levels"])
    assert_grid_debt(row, None if status == "measured" else status)


def test_grid_dependent_depth_residual_is_unknown_until_the_declared_grid_is_verified():
    data = bundle(fact("assumed"))
    setup = data.plan["setups"][0]
    setup["ops"] = [{"op": 10, "do": "face", "feature": "deck", "tool": "cutter", "to_z": 7.497}]
    data.features["features"]["deck"] = {
        "kind": "face",
        "requirements": ["length"],
        "length": [1.0, 1.0005],
    }
    provisional = coordinates.evaluate(data)[0]
    assert_grid_debt(provisional, "assumed")
    assert provisional.numbers["operations"][0]["dro_to_z"] == 7.5
    assert "dro_z_residual_errors" not in provisional.numbers
    data.inventory["machines"]["mill"]["resolution_mm"]["measured"]["status"] = "measured"
    measured = coordinates.evaluate(data)[0]
    assert measured.status == "error"
    assert measured.numbers["dro_z_residual_errors"]
    assert measured.numbers["operations"][0]["dro_to_z"] == 7.5


@pytest.mark.parametrize(("resolution", "debt_status", "step"), resolution_cases())
def test_traveler_distinguishes_declared_untrusted_grid_from_absence(resolution, debt_status, step):
    data = bundle(resolution)
    setups = data.plan["setups"]
    text = _Traveler(data, [], {}, None).dro_resolution(setups)
    assert f"{step:.3f} mm" in text
    if debt_status is None:
        assert "†" not in text and "not verified" not in text and "default" not in text
        return
    if debt_status == "missing":
        assert "†" not in text and "absent/unknown" in text and "provisional default grid" in text
        return
    # A declared, untrusted step: the grid prints as declared and is named unverified
    # once, with no per-setup instruction and no provisional-default or shop-list wording.
    assert "0.005 mm" in text and "grid not verified" in text and "†" not in text
    assert text.count("not verified") == 1
    assert "default" not in text and "not in the shop list" not in text
    assert "installed readout step" in text and "confirm installed readout" not in text
    assert "assumed" not in text and "illustrative" not in text and "unmeasured" not in text
    # Nothing consumed the step: the header says so and binds no JOB record.
    assert "not consumed by a stopped decision" in text and "?M" not in text
    # The coordinate decision refusing the step is the consumer: the setup page registers
    # the exact refused fact once, and the header then cites its JOB record instead.
    row = coordinates.evaluate(data)[0]
    assert_grid_debt(row, debt_status)
    (entry,) = row.numbers["measurements"]
    traveler = _Traveler(data, [row], {}, None)
    traveler.register_measurements(traveler.collect_measurements(setups[0]), setups[0])
    assert list(traveler.measurement_registry()) == [entry["id"]]
    consumed = traveler.dro_resolution(setups)
    assert f"{step:.3f} mm" in consumed and "grid not verified" in consumed
    assert consumed.count("not verified") == 1
    assert "not consumed by a stopped decision" not in consumed
    assert f"el400 installed readout step {traveler.measurement_reference(entry)})" in consumed
    assert consumed.count("?M") == 1
    assert "default" not in consumed and "confirm installed readout" not in consumed
    assert "assumed" not in consumed and "illustrative" not in consumed
    assert "unmeasured" not in consumed and "†" not in consumed
    assert row.numbers["measurements"] == [entry]


@pytest.mark.parametrize("status", ["assumed", "illustrative", "measured"])
def test_bench_lineage_inherits_the_source_grid_and_its_measurement_debt(status):
    data = bundle(fact(status))
    source = data.plan["setups"][0]
    source["ops"] = []
    bench = {
        "id": "B1",
        "machine": "bench",
        "frame": "F",
        "stock_in": "S1",
        "stock_state": {"top_z": 7.938},
        "ops": [],
    }
    data.inventory["machines"]["bench"] = {"kind": "bench"}
    data.plan["setups"].append(bench)
    assert coordinates.dro_grid_source(data, bench) is source
    assert coordinates.dro_grid(data, bench) == coordinates.dro_grid(data, source) == (0.005, 3)
    assert coordinates.dro_grid_debt(data, bench) == coordinates.dro_grid_debt(data, source)
    entries = coordinates.dro_grid_measurements(data, bench)
    assert entries == coordinates.dro_grid_measurements(data, source)
    if status == "measured":
        assert entries == []
    else:
        assert entries[0]["id"] == "machines.mill.resolution"
        assert entries[0]["status"] == status
    traveler = _Traveler(data, [], {}, None)
    assert traveler.surface_z(bench, 7.497) == 7.5
    assert traveler.surface_z(source, 7.497) == 7.5


def test_a_bench_declared_untrusted_grid_does_not_inherit_a_finer_machine_grid():
    data = bundle(fact(value=0.001))
    bench = {"id": "B1", "machine": "bench", "stock_in": "S1", "ops": []}
    data.inventory["machines"]["bench"] = {"kind": "bench", "resolution_mm": fact("assumed")}
    data.plan["setups"].append(bench)
    assert coordinates.dro_grid_source(data, bench) is bench
    assert coordinates.dro_grid(data, bench) == (0.005, 3)
    (entry,) = coordinates.dro_grid_measurements(data, bench)
    assert entry["id"] == "machines.bench.resolution"
    assert entry["status"] == "assumed"


@pytest.mark.parametrize("status", ["assumed", "illustrative", "measured"])
def test_declared_inch_grid_keeps_its_step_and_debt_after_plan_unit_conversion(status):
    data = bundle(fact(status))
    machine = data.inventory["machines"]["mill"]
    machine.pop("resolution_mm")
    machine["resolution_in"] = fact(status, value=0.0005)
    setup = data.plan["setups"][0]
    assert coordinates.dro_grid(data, setup) == pytest.approx((0.0127, 4))
    data.features["units"] = "in"
    assert coordinates.dro_grid(data, setup) == pytest.approx((0.0005, 4))
    assert bool(coordinates.dro_grid_debt(data, setup)) == (status != "measured")
