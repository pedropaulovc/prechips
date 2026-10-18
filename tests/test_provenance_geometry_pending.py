"""A pending bounding-box computation is not a new physical measurement request.

These host-only fixtures inject geometry states; they launch no native kernel and
retain real authored Z, fixture measurement, and DRO measurement debts.
"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.measurements import measurement_checklist
from prechips.rules import coordinates, envelope, travel
from prechips.rules._envelope import stock_extents

SUPPORTED_HEIGHT = "plan.setups.S1.supported_height"
XY_GEOMETRY = "plan.setups.S1.ops.20.xy_geometry"
Z_GEOMETRY = "plan.setups.S1.ops.20.z_geometry"
BED_HEIGHT = "fixtures.vise.bed_height"
DRO_RESOLUTION = "machines.mill.resolution"
FRAME = {
    "origin": [2.0, 3.0, 4.0],
    "x": [0.0, 1.0, 0.0],
    "y": [-1.0, 0.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "nominal",
}
BBOX_MM = [0.0, 0.0, 0.0, 10.0, 30.0, 20.0]


def fact(value, status="measured"):
    return {
        "value": value,
        "measured": {
            "status": status,
            "by": "synthetic fixture operator",
            "date": "2026-10-01",
            "instrument": "synthetic shop measurement",
        },
    }


def bundle(*, units="mm", pending=True):
    kernel = {
        "status": "unknown",
        # Human prose alone must not classify geometric computation debt.
        "reason": "FreeCAD geometry was not requested for the host-only measurement checklist.",
    }
    if pending is not None:
        kernel["geometry_pending"] = pending
    return Bundle(
        plan={
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "F",
                    "hold": {"fixture": "vise"},
                    "stock_state": {"top_z": "unknown", "bottom_z": "unknown"},
                    "ops": [
                        {
                            "op": 20,
                            "do": "face",
                            "feature": "subject",
                            "tool": "cutter",
                            "holder": "collet",
                            "to_z": "unknown",
                            "approach_mm": "unknown",
                        }
                    ],
                }
            ]
        },
        features={
            "units": units,
            "frames": {"F": deepcopy(FRAME)},
            "features": {"subject": {"kind": "face", "frame": "F", "requirements": []}},
        },
        inventory={
            "machines": {
                "mill": {
                    "kind": "mill",
                    "resolution_mm": fact(0.005, "assumed"),
                    "envelope": {
                        "spindle_to_table_min_mm": fact(0.0),
                        "spindle_to_table_max_mm": fact(300.0),
                        "travel_mm": {axis: fact(300.0) for axis in ("x", "y", "z")},
                    },
                }
            },
            "tools": {"cutter": {"kind": "endmill", "oal_mm": fact(80.0)}},
            "holders": {
                "collet": {"kind": "collet", "gauge_len_mm": fact(20.0), "grip_mm": fact(20.0)},
            },
            "fixtures": {"vise": {"kind": "vise", "bed_height_mm": fact(20.0, "assumed")}},
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel=kernel,
    )


def findings(data):
    return [row for rule in (envelope, travel, coordinates) for row in rule.evaluate(data)]


def identities(data):
    return {entry["id"] for entry in measurement_checklist(findings(data))}


def test_typed_pending_geometry_preserves_real_authored_z_shop_and_grid_measurement_debt():
    data = bundle()
    rows = findings(data)
    assert all(row.status == "unknown" for row in rows)
    ids = {entry["id"] for entry in measurement_checklist(rows)}
    assert {Z_GEOMETRY, BED_HEIGHT, DRO_RESOLUTION} <= ids
    assert SUPPORTED_HEIGHT not in ids
    # The stock-sized broad cut owes its X/Y extent as plan input (its approach and exit
    # are undeclared, #297), never a request to measure the pending geometry.
    (xy,) = [entry for entry in measurement_checklist(rows) if entry["id"] == XY_GEOMETRY]
    assert xy["instruction"].startswith("author:")
    assert all(
        "Geometry pending" in row.sentence for row in rows if row.rule in {"envelope", "travel"}
    )
    (dro,) = [entry for entry in measurement_checklist(rows) if entry["id"] == DRO_RESOLUTION]
    assert dro["status"] == "assumed"
    assert data.kernel["status"] == "unknown"


def test_pending_bbox_and_ready_bbox_checklists_have_identical_real_measurement_ids():
    pending = bundle()
    ready = replace(pending, kernel={"status": "ok", "bbox_mm": list(BBOX_MM)})
    assert identities(pending) == identities(ready)
    assert {Z_GEOMETRY, BED_HEIGHT, DRO_RESOLUTION} <= identities(ready)
    assert all(row.status == "unknown" for row in findings(ready))


@pytest.mark.parametrize("marker", [None, False])
def test_missing_or_false_typed_marker_does_not_suppress_authored_geometry_requests(marker):
    data = bundle(pending=marker)
    ids = identities(data)
    assert {SUPPORTED_HEIGHT, XY_GEOMETRY, Z_GEOMETRY, BED_HEIGHT, DRO_RESOLUTION} <= ids
    extents, _ = stock_extents(data, data.plan["setups"][0])
    assert "geometry_pending_axes" not in extents


@pytest.mark.parametrize("units", ["mm", "in"])
def test_normalized_mm_bbox_derivation_is_pending_in_both_recognized_manifest_units(units):
    data = bundle(units=units)
    setup = data.plan["setups"][0]
    extents, _ = stock_extents(data, setup)
    assert extents["geometry_pending_axes"] == ["x", "y", "z"]
    assert all(extents[axis] == "unknown" for axis in ("x", "y", "z"))
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert SUPPORTED_HEIGHT not in {entry["id"] for entry in row.numbers["measurements"]}
    assert Z_GEOMETRY in {entry["id"] for entry in row.numbers["measurements"]}
    # The native bbox is normalized mm. Frame axes are unitless; translation cancels
    # when taking a span, including a nonzero origin expressed in manifest inches.
    ready = replace(data, kernel={"status": "ok", "bbox_mm": list(BBOX_MM)})
    ready_extents, _ = stock_extents(ready, setup)
    assert ready_extents == {"x": 30.0, "y": 10.0, "z": 20.0}
    assert SUPPORTED_HEIGHT not in identities(ready)


@pytest.mark.parametrize("defect", ["unknown-origin", "scaled-axis"])
def test_unknown_or_nonorthonormal_setup_basis_remains_authored_geometry_debt(defect):
    data = bundle()
    frame = data.features["frames"]["F"]
    if defect == "unknown-origin":
        frame["origin"][0] = "unknown"
    else:
        frame["x"] = [0.0, 2.0, 0.0]
    extents, _ = stock_extents(data, data.plan["setups"][0])
    assert "geometry_pending_axes" not in extents
    assert {SUPPORTED_HEIGHT, XY_GEOMETRY, Z_GEOMETRY, BED_HEIGHT, DRO_RESOLUTION} <= identities(
        data
    )


def test_unknown_manifest_units_do_not_turn_authoring_debt_into_pending_geometry():
    data = bundle(units="unknown")
    extents, _ = stock_extents(data, data.plan["setups"][0])
    assert "geometry_pending_axes" not in extents
    assert {SUPPORTED_HEIGHT, XY_GEOMETRY, Z_GEOMETRY, BED_HEIGHT} <= identities(data)


def test_known_supported_height_is_not_marked_as_bbox_computation_debt():
    data = bundle()
    setup = data.plan["setups"][0]
    setup["stock_state"].update(top_z=5.0, bottom_z=-5.0)
    extents, _ = stock_extents(data, setup)
    assert extents["z"] == 10.0
    assert extents["geometry_pending_axes"] == ["x", "y"]
    assert SUPPORTED_HEIGHT not in identities(data)
    assert {Z_GEOMETRY, BED_HEIGHT, DRO_RESOLUTION} <= identities(data)
