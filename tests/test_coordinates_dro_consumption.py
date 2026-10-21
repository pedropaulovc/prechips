"""Host-only DRO debt follows authored/emitted targets, not machine selection.

Every fact is synthetic and every bundle is isolated; these rules never prepare a
kernel or read an example, golden, real shop inventory or native cache.
"""

import runpy
from copy import deepcopy
from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.measurements import measurement_checklist
from prechips.rules import coordinates
from prechips.sheet import _Traveler

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))

FRAME = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "nominal",
}
NOT_USED = {"step": "not used", "decimals": "not used"}
TABLES = ("rows", "profiles", "arc_table", "line_table", "contours")


def fact(value=0.005, status="measured"):
    return {
        "value": value,
        "measured": {
            "status": status,
            "by": "synthetic fixture operator",
            "date": "2026-10-01",
            "instrument": "synthetic fixture verification",
        },
    }


def bundle(tmp_path, resolution=None):
    machine = {"kind": "bandsaw", "name": "Synthetic saw"}
    if resolution is not None:
        machine["resolution_mm"] = deepcopy(resolution)
    return Bundle(
        plan={
            "dro": {"controller": "el400", "radius_mode": False},
            "setups": [
                {
                    "id": "S1",
                    "machine": "saw",
                    "frame": "F",
                    "stock_state": {"top_z": 10.0, "bottom_z": 0.0},
                    "ops": [{"op": 10, "do": "saw_cut"}],
                }
            ],
        },
        inventory={"machines": {"saw": machine}},
        features={
            "units": "mm",
            "frames": {"F": deepcopy(FRAME), "model": deepcopy(FRAME)},
            "features": {},
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def validator_uses_grid(data, numbers):
    setup = data.plan["setups"][0]
    machine = data.inventory["machines"]["saw"]
    return VALIDATOR["coordinates_use_grid"](
        setup,
        data.feature_definitions,
        data.features["frames"],
        numbers,
        machine["kind"] == "lathe",
        data.inventory,
    )


def assert_grid_debt(row, status):
    assert row.status == "unknown", row.sentence
    assert row.numbers["dro_grid_debt"]
    assert "DRO grid debt:" in row.sentence
    (entry,) = row.numbers["measurements"]
    assert entry["id"] == "machines.saw.resolution"
    assert entry["status"] == status
    assert entry["units"] == "mm"
    assert entry["instruction"].startswith("measure:")
    assert entry["reason"]
    assert "inventory.machines.saw.resolution" in entry["cite"]
    assert measurement_checklist([row]) == [entry]


@pytest.mark.parametrize(
    "resolution",
    [
        pytest.param(None, id="missing"),
        pytest.param("unknown", id="explicit-unknown"),
        pytest.param(fact(status="assumed"), id="assumed"),
        pytest.param(fact(status="illustrative"), id="illustrative"),
        pytest.param(fact(), id="measured"),
    ],
)
def test_bare_saw_cut_does_not_consume_a_dro_grid(tmp_path, resolution):
    data = bundle(tmp_path, resolution)
    row = coordinates.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert not validator_uses_grid(data, row.numbers)
    assert row.numbers["dro_grid"] == NOT_USED
    assert row.numbers["operations"] == [{"op": 10, "do": "saw_cut"}]
    assert all(row.numbers[key] == [] for key in TABLES)
    assert not row.numbers.get("level_paths")
    assert not row.numbers.get("stair_tables")
    assert not row.numbers.get("plunges")
    assert "dro_grid_debt" not in row.numbers
    assert "measurements" not in row.numbers
    assert measurement_checklist([row]) == []
    assert "DRO grid debt:" not in row.sentence
    # The report mapping must also be visible, not hidden by the saw renderer shortcut.
    shown = _Traveler(data, [row], {}, None).dro_resolution(data.plan["setups"])
    assert shown is not None and "no coordinate targets" in shown
    assert "provisional" not in shown and "unverified" not in shown
    assert data.kernel is None


@pytest.mark.parametrize(
    ("resolution", "status", "step", "printed"),
    [
        pytest.param(None, "missing", 0.001, 1.003, id="missing"),
        pytest.param(fact(status="assumed"), "assumed", 0.005, 1.005, id="assumed"),
    ],
)
def test_one_printed_coordinate_on_the_same_machine_consumes_its_grid(
    tmp_path, resolution, status, step, printed
):
    data = bundle(tmp_path, resolution)
    data.plan["setups"][0]["ops"][0]["to_z"] = 1.0021
    row = coordinates.evaluate(data)[0]
    assert row.numbers["operations"] == [
        {"op": 10, "do": "saw_cut", "to_z": 1.0021, "dro_to_z": printed}
    ]
    assert all(row.numbers[key] == [] for key in TABLES)
    assert row.numbers["dro_grid"] == {"step": step, "decimals": 3}
    assert_grid_debt(row, status)
    assert validator_uses_grid(data, row.numbers)


def test_verifying_the_consumed_grid_changes_only_debt_not_the_printed_coordinate(tmp_path):
    data = bundle(tmp_path, fact(status="assumed"))
    data.plan["setups"][0]["ops"][0]["to_z"] = 1.0021
    provisional = coordinates.evaluate(data)[0]
    assert_grid_debt(provisional, "assumed")
    data.inventory["machines"]["saw"]["resolution_mm"]["measured"]["status"] = "measured"
    trusted = coordinates.evaluate(data)[0]
    assert trusted.status == "pass", trusted.sentence
    assert trusted.numbers["dro_grid"] == {"step": 0.005, "decimals": 3}
    assert trusted.numbers["operations"][0]["dro_to_z"] == 1.005
    assert "dro_grid_debt" not in trusted.numbers
    assert "measurements" not in trusted.numbers
    assert measurement_checklist([trusted]) == []
    assert trusted.numbers == {
        key: value
        for key, value in provisional.numbers.items()
        if key not in {"dro_grid_debt", "measurements"}
    }


@pytest.mark.parametrize("known_trajectory", [False, True], ids=["unknown-path", "known-path"])
@pytest.mark.parametrize(
    ("resolution", "status", "step", "start", "end"),
    [
        pytest.param(
            None,
            "missing",
            0.001,
            [1.002, 2.002, 3.002],
            [4.007, 2.002, 3.002],
            id="missing-grid",
        ),
        pytest.param(
            "unknown",
            "missing",
            0.001,
            [1.002, 2.002, 3.002],
            [4.007, 2.002, 3.002],
            id="unknown-grid",
        ),
        pytest.param(
            fact(status="assumed"),
            "assumed",
            0.005,
            [1.0, 2.0, 3.0],
            [4.005, 2.0, 3.0],
            id="assumed-grid",
        ),
        pytest.param(
            fact(),
            "measured",
            0.005,
            [1.0, 2.0, 3.0],
            [4.005, 2.0, 3.0],
            id="measured-grid",
        ),
    ],
)
def test_mounted_saw_consumes_grid_even_without_proven_or_emitted_trajectory(
    tmp_path, known_trajectory, resolution, status, step, start, end
):
    data = bundle(tmp_path, resolution)
    data.inventory["machines"]["saw"]["kind"] = "mill"
    data.inventory["tools"] = {"blade": {"kind": "slitting_saw"}}
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(tool="blade", cut_plane={"axis": "z", "value": 3.002})
    op["saw_trajectory"] = (
        {
            "start_mm": [1.002, 2.002, 3.002],
            "moves": [{"to_mm": [4.007, 2.002, 3.002], "mode": "cut"}],
        }
        if known_trajectory
        else "unknown"
    )

    row = coordinates.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert all(row.numbers[key] == [] for key in TABLES)
    assert row.numbers["dro_grid"] == {"step": step, "decimals": 3}
    (operation,) = row.numbers["operations"]
    path = operation["mounted_saw_trajectory"]
    assert path["status"] == "unknown"
    assert path["coordinate_reference"] == "spindle_xy_cutting_midplane_z"
    if known_trajectory:
        assert path["start_mm"] == [1.002, 2.002, 3.002]
        assert path["moves"] == [{"to_mm": [4.007, 2.002, 3.002], "mode": "cut"}]
        assert path["dro_start"] == start
        assert path["dro_moves"] == [{"to": end, "mode": "cut"}]
    else:
        assert path["start_mm"] == "unknown"
        assert path["moves"] == "unknown"
        assert path["dro_start"] == ["unknown"] * 3
        assert path["dro_moves"] == []
    if status == "measured":
        assert "dro_grid_debt" not in row.numbers
        assert "measurements" not in row.numbers
        assert measurement_checklist([row]) == []
    else:
        assert_grid_debt(row, status)

    # Independently authored report: no engine numbers are an expected-value oracle.
    # Omitting the emitted path cannot erase the authored mounted saw's grid use.
    finding = {
        "status": "unknown",
        "cite": [],
        "numbers": {
            "dro_grid": {"step": step, "decimals": 3},
            "operations": [{"op": 10, "do": "saw_cut"}],
        },
    }
    if status != "measured":
        finding["numbers"]["dro_grid_debt"] = True
    entries = VALIDATOR["Entries"](data.inventory)

    def check():
        VALIDATOR["check_coordinates"](
            setup, data.features, finding, data.plan, entries, data.inventory, None
        )

    check()
    if status != "measured":
        del finding["numbers"]["dro_grid_debt"]
        with pytest.raises(ValueError, match="grid debt"):
            check()
        finding["numbers"]["dro_grid_debt"] = True
    finding["numbers"]["dro_grid"] = deepcopy(NOT_USED)
    with pytest.raises(ValueError, match="DRO grid step"):
        check()
    assert data.kernel is None


@pytest.mark.parametrize("field", ["to_z", "z_from", "z_to"])
@pytest.mark.parametrize("resolution", [None, fact(status="assumed")], ids=["missing", "assumed"])
def test_an_authored_unknown_z_target_still_consumes_the_grid(tmp_path, field, resolution):
    data = bundle(tmp_path, resolution)
    data.plan["setups"][0]["ops"][0][field] = "unknown"
    row = coordinates.evaluate(data)[0]
    assert all(row.numbers[key] == [] for key in TABLES)
    assert row.numbers["operations"][0][field] == "unknown"
    if field == "to_z":
        assert row.numbers["operations"][0]["dro_to_z"] == "unknown"
    assert row.numbers["dro_grid"] != NOT_USED
    assert_grid_debt(row, "missing" if resolution is None else "assumed")
    # No producer outputs: the validator must recover the authored target independently.
    assert validator_uses_grid(data, {"dro_grid": NOT_USED})


@pytest.mark.parametrize(
    "method", ["linear_table", "stairs", "chain_drill", "chords", "rotary_table", "axial_table"]
)
def test_authored_contour_with_no_computable_rows_still_consumes_the_grid(tmp_path, method):
    data = bundle(tmp_path)
    machine = data.inventory["machines"]["saw"]
    machine.update(kind="mill", spindle={"rotation": fact("cw")})
    data.inventory["tools"] = {"cutter": {"kind": "endmill", "dia_mm": fact(4.0)}}
    data.features["features"]["body"] = {"kind": "profile", "frame": "model"}
    data.plan["setups"][0]["ops"] = [
        {
            "op": 10,
            "do": "profile",
            "feature": "body",
            "tool": "cutter",
            "direction": "conventional",
            "contour": {"method": method},
        }
    ]
    row = coordinates.evaluate(data)[0]
    assert row.numbers["rows"] == []
    assert row.numbers["arc_table"] == [] and row.numbers["line_table"] == []
    assert row.numbers["contours"] == []
    assert not row.numbers.get("level_paths")
    (profile,) = row.numbers["profiles"]
    assert profile["cutter_centre"] == "unknown"
    assert profile["dro_to_z"] == "unknown"
    assert row.numbers["dro_grid"] == {"step": 0.001, "decimals": 3}
    assert_grid_debt(row, "missing")


@pytest.mark.parametrize("location", [None, "unknown", [1.0021, 2.0031, 3.0041]])
def test_requested_feature_location_consumes_the_grid_even_when_unresolved(tmp_path, location):
    data = bundle(tmp_path)
    feature = {"kind": "hole", "frame": "model"}
    if location is not None:
        feature["at"] = location
    data.features["features"]["hole"] = feature
    data.plan["setups"][0]["ops"] = [{"op": 10, "do": "drill", "feature": "hole"}]
    row = coordinates.evaluate(data)[0]
    (target,) = row.numbers["rows"]
    assert target["feature"] == "hole"
    if isinstance(location, list):
        assert target["dro"] == [1.002, 2.003, 3.004]
        assert target["dro_xy"] == [1.002, 2.003]
    else:
        assert target["setup"] == ["unknown"] * 3
    assert_grid_debt(row, "missing")


@pytest.mark.parametrize("stations", [[], [1.0021], ["unknown"]])
def test_only_nonempty_lathe_drawing_stations_consume_the_grid(tmp_path, stations):
    data = bundle(tmp_path)
    data.inventory["machines"]["saw"]["kind"] = "lathe"
    data.features["features"]["body"] = {
        "kind": "profile",
        "frame": "model",
        "dia_nominal": 8.0,
        "z_mm": stations,
    }
    data.plan["setups"][0]["ops"] = [{"op": 10, "do": "inspect", "feature": "body"}]
    row = coordinates.evaluate(data)[0]
    assert len(row.numbers["rows"]) == len(stations)
    if stations:
        assert row.numbers["rows"][0]["point"] == "drawing station 1"
        assert_grid_debt(row, "missing")
    else:
        assert row.status == "pass", row.sentence
        assert row.numbers["dro_grid"] == NOT_USED
        assert "dro_grid_debt" not in row.numbers
        assert measurement_checklist([row]) == []


def test_unused_grid_does_not_clear_independent_frame_debt(tmp_path):
    data = bundle(tmp_path)
    data.features["frames"]["F"]["binding"] = "unknown"
    row = coordinates.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert row.numbers["dro_grid"] == NOT_USED
    assert "dro_grid_debt" not in row.numbers
    assert measurement_checklist([row]) == []


@pytest.mark.parametrize("contour", [None, {}], ids=["missing", "empty"])
def test_stock_metadata_and_an_unlocated_feature_do_not_invent_a_dro_target(tmp_path, contour):
    data = bundle(tmp_path)
    data.features["features"]["body"] = {"kind": "profile", "frame": "model"}
    setup = data.plan["setups"][0]
    setup["stock_state"]["entry_z"] = {"body": 9.0021}
    setup["ops"][0]["feature"] = "body"
    if contour is not None:
        setup["ops"][0]["contour"] = contour
    row = coordinates.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert all(row.numbers[key] == [] for key in TABLES)
    assert row.numbers["dro_grid"] == NOT_USED
    assert "dro_grid_debt" not in row.numbers
    assert measurement_checklist([row]) == []
    assert not validator_uses_grid(data, {"dro_grid": NOT_USED})


@pytest.mark.parametrize(
    ("resolution", "status", "step"),
    [
        pytest.param(None, "missing", 0.001, id="missing"),
        pytest.param(fact(status="assumed"), "assumed", 0.005, id="assumed"),
        pytest.param(fact(status="illustrative"), "illustrative", 0.005, id="illustrative"),
        pytest.param(fact(), "measured", 0.005, id="measured"),
    ],
)
def test_an_authored_unknown_contour_consumes_the_grid_without_inventing_targets(
    tmp_path, resolution, status, step
):
    data = bundle(tmp_path, resolution)
    data.features["features"]["body"] = {"kind": "profile", "frame": "model"}
    setup = data.plan["setups"][0]
    setup["stock_state"]["entry_z"] = {"body": 9.0021}
    setup["ops"][0].update(feature="body", contour="unknown")
    row = coordinates.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert all(row.numbers[key] == [] for key in TABLES)
    assert not row.numbers.get("level_paths")
    assert not row.numbers.get("stair_tables")
    assert not row.numbers.get("plunges")
    assert row.numbers["dro_grid"] == {"step": step, "decimals": 3}
    # No emitted targets: the independent oracle must retain the author's intent.
    assert validator_uses_grid(data, {"dro_grid": NOT_USED})
    if status == "measured":
        assert "dro_grid_debt" not in row.numbers
        assert "measurements" not in row.numbers
        assert measurement_checklist([row]) == []
        assert "DRO grid debt:" not in row.sentence
    else:
        assert_grid_debt(row, status)
        data.inventory["machines"]["saw"]["resolution_mm"] = fact(value=step)
        trusted = coordinates.evaluate(data)[0]
        assert trusted.status == "unknown", trusted.sentence
        assert "dro_grid_debt" not in trusted.numbers
        assert "measurements" not in trusted.numbers
        assert measurement_checklist([trusted]) == []
        assert trusted.numbers == {
            key: value
            for key, value in row.numbers.items()
            if key not in {"dro_grid_debt", "measurements"}
        }
    assert data.kernel is None


@pytest.mark.parametrize("consumed", [False, True])
def test_independent_allowance_error_keeps_error_precedence_over_grid_debt(tmp_path, consumed):
    data = bundle(tmp_path)
    op = data.plan["setups"][0]["ops"][0]
    op["rough_allowance_mm"] = -0.5
    if consumed:
        op["to_z"] = 1.0021
    row = coordinates.evaluate(data)[0]
    assert row.status == "error", row.sentence
    assert row.numbers["allowance_errors"]
    if consumed:
        assert row.numbers["dro_grid"] == {"step": 0.001, "decimals": 3}
        assert row.numbers["dro_grid_debt"]
        (entry,) = row.numbers["measurements"]
        assert entry["id"] == "machines.saw.resolution"
        assert entry["status"] == "missing"
    else:
        assert row.numbers["dro_grid"] == NOT_USED
        assert "dro_grid_debt" not in row.numbers
        assert measurement_checklist([row]) == []


@pytest.mark.parametrize(
    ("table", "target"),
    [
        ("rows", {"feature": "body", "setup": [1.0, 2.0, 3.0], "dro": [1.0, 2.0, 3.0]}),
        ("profiles", {"op": 10, "cutter_centre": [[1.0, 2.0], [2.0, 2.0]]}),
        ("arc_table", {"op": 10, "rows": [{"dro_xy": [1.0, 2.0]}]}),
        ("line_table", {"op": 10, "dro_xy": [[1.0, 2.0], [2.0, 2.0]]}),
        ("contours", {"op": 10, "rows": [{"setup_xz": [1.0, 2.0]}]}),
        ("level_paths", {"op": 10, "entries": [{"xy": [1.0, 2.0]}], "levels": [3.0]}),
    ],
)
def test_validator_detects_emitted_targets_without_trusting_an_unused_grid_label(
    tmp_path, table, target
):
    data = bundle(tmp_path)
    assert not validator_uses_grid(data, {"dro_grid": NOT_USED})
    assert validator_uses_grid(data, {"dro_grid": NOT_USED, table: [target]})


@pytest.mark.parametrize(
    ("field", "target"),
    [
        ("dro_to_z", 1.002),
        ("blade", {"corner_dro_z": 1.002}),
        ("z_levels", {"levels": [1.002]}),
    ],
)
def test_validator_detects_emitted_operation_targets_on_an_otherwise_bare_saw(
    tmp_path, field, target
):
    data = bundle(tmp_path)
    numbers = {"dro_grid": NOT_USED, "operations": [{"op": 10, field: target}]}
    assert validator_uses_grid(data, numbers)
