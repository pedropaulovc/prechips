"""Requested native pickup proof is independent of visible Axis Set arithmetic."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_procedure_boxes import mill_bundle

from prechips import kernel
from prechips.rules.zero_recipe import rule
from prechips.rules.zero_recipe.native import zero_pickup_evidence


def normalized_request(axis="x"):
    return {
        "model": "transverse_finder_v1",
        "axis": axis,
        "recipe_id": f"current-{axis}-recipe",
        "from": f"-{axis}",
        "method": "edge finder",
        "face": f"stock:-{axis}",
        "surface": {"kind": "stock", "side": f"-{axis}"},
        "at_mm": [5, 8],
        "edge_mm": 0,
        "approach_mm": 2.54,
        "retract_clearance_mm": 12.7,
        "check_jog_mm": 5,
        "tool": "tools.finder",
        "holder": "holders.collet",
        "finder": {
            "tip_dia_mm": 5.08,
            "tip_length_mm": 6.35,
            "shank_dia_mm": 9.525,
            "projection_mm": 30,
            "holder_dia_mm": 20,
            "holder_gauge_len_mm": 25,
        },
        "reasons": [],
        "errors": [],
    }


def native_proof(request, *, status="pass"):
    points = [
        [-5.08, 5, 22.7],
        [-5.08, 5, 8],
        [-2.54, 5, 8],
        [-2.54, 5, 22.7],
        [2.46, 5, 22.7],
    ]
    return {
        "model": request["model"],
        "setup_id": "S1",
        "axis": request["axis"],
        "recipe_id": request["recipe_id"],
        "request": deepcopy(request),
        "status": status,
        "reasons": [],
        "errors": [],
        "collisions": [],
        "obstacles": [{"name": "stock", "bbox_mm": [0, 0, 0, 20, 10, 10]}],
        "resolved_contact": {
            "surface": deepcopy(request["surface"]),
            "plane_mm": 0,
            "normal": [-1, 0, 0],
            "axis_mm": [-2.54, 5, 8],
            "point_mm": [0, 5, 9],
            "tip_span_mm": [8, 14.35],
            "contact_z_mm": [8, 10],
        },
        "window": {
            "scope": "contact_only",
            "transverse_axis": "y",
            "centre_min_mm": 0,
            "centre_max_mm": 10,
            "at_mm": 5,
            "contact_z_mm": [8, 10],
        },
        "path": {
            "start_mm": [-5.08, 5, 22.7],
            "contact_mm": [-2.54, 5, 8],
            "stock_top_mm": 10,
            "retract_height_mm": 22.7,
            "jog_mm": 5,
            "legs": [
                {
                    "index": index,
                    "kind": kind,
                    "from_mm": points[index],
                    "to_mm": points[index + 1],
                    "components": [
                        {"id": name, "bbox_mm": [-10, 0, 0, 10, 10, 80]}
                        for name in ("tip", "shank", "holder")
                    ],
                }
                for index, kind in enumerate(("descend", "approach", "retract", "check_jog"))
            ],
        },
    }


def pickup_bundle():
    setup = {"id": "S1", "zero": {"x": {"at_mm": [5, 8]}}}
    return SimpleNamespace(kernel={"status": "ok", "setups": {"S1": {"zero_pickups": {}}}}), setup


def test_absent_transverse_point_remains_arithmetic_only_without_normalization(monkeypatch):
    bundle, setup = pickup_bundle()
    del setup["zero"]["x"]["at_mm"]
    monkeypatch.setattr(
        kernel, "zero_pickup_inputs", lambda *args: pytest.fail("unrequested normalization")
    )
    assert zero_pickup_evidence(bundle, setup, "x") is None


def test_current_complete_pickup_exposes_only_its_proved_physical_window():
    bundle, setup = pickup_bundle()
    request = normalized_request()
    bundle.kernel["setups"]["S1"]["zero_pickups"]["x"] = native_proof(request)
    result = zero_pickup_evidence(bundle, setup, "x", normalized={"requests": {"x": request}})
    assert result["status"] == "pass"
    assert result["window"] == {
        "scope": "contact_only",
        "transverse_axis": "y",
        "centre_min_mm": 0,
        "centre_max_mm": 10,
        "at_mm": 5,
        "contact_z_mm": [8, 10],
    }
    assert result["resolved_contact"]["surface"] == {"kind": "stock", "side": "-x"}
    assert [leg["kind"] for leg in result["path"]["legs"]] == [
        "descend",
        "approach",
        "retract",
        "check_jog",
    ]


@pytest.mark.parametrize(
    "mutation", ["missing", "recipe", "axis", "setup", "request", "marker_only"]
)
def test_missing_stale_or_other_subject_pickup_proof_stays_debt(mutation):
    bundle, setup = pickup_bundle()
    request = normalized_request()
    proof = native_proof(request)
    if mutation == "recipe":
        proof["recipe_id"] = "old-recipe"
    elif mutation == "axis":
        proof["axis"] = "y"
    elif mutation == "setup":
        proof["setup_id"] = "S2"
    elif mutation == "request":
        proof["request"]["at_mm"] = [6, 8]
    elif mutation == "marker_only":
        proof.pop("path")
    if mutation != "missing":
        bundle.kernel["setups"]["S1"]["zero_pickups"]["x"] = proof
    result = zero_pickup_evidence(bundle, setup, "x", normalized={"requests": {"x": request}})
    assert result["status"] == "unknown"
    assert result["reasons"]
    if mutation != "marker_only":
        assert result["proof"] == {}
        assert result["window"] == {}


def test_matching_native_collision_error_dominates_other_missing_facts():
    bundle, setup = pickup_bundle()
    request = normalized_request()
    request["reasons"] = ["selected holder gauge length is unresolved"]
    proof = native_proof(request, status="error")
    proof["errors"] = ["finder shank collides with raised stop"]
    proof["collisions"] = [{"component": "shank", "obstacle": "raised stop", "volume_mm3": 1}]
    bundle.kernel["setups"]["S1"]["zero_pickups"]["x"] = proof
    result = zero_pickup_evidence(bundle, setup, "x", normalized={"requests": {"x": request}})
    assert result["status"] == "error"
    assert "finder shank collides with raised stop" in result["reasons"]


def test_stale_native_error_is_not_borrowed_but_current_input_error_survives():
    bundle, setup = pickup_bundle()
    request = normalized_request()
    stale = native_proof(request, status="error")
    stale["recipe_id"] = "old"
    bundle.kernel["setups"]["S1"]["zero_pickups"]["x"] = stale
    result = zero_pickup_evidence(bundle, setup, "x", normalized={"requests": {"x": request}})
    assert result["status"] == "unknown"
    request["errors"] = ["finder tip length must be positive"]
    result = zero_pickup_evidence(bundle, setup, "x", normalized={"requests": {"x": request}})
    assert result["status"] == "error"
    assert "finder tip length must be positive" in result["reasons"]


@pytest.mark.parametrize("proof_status", [None, "pass", "unknown", "error"])
def test_zero_rule_keeps_arithmetic_visible_and_never_starts_native(monkeypatch, proof_status):
    data = mill_bundle()
    setup = data.plan["setups"][0]
    setup["zero"]["x"]["at_mm"] = [5, 8]
    request = normalized_request()
    normalized = {"requests": {"x": request}, "measurement_debts": []}
    monkeypatch.setattr(kernel, "zero_pickup_inputs", lambda *args: deepcopy(normalized))
    monkeypatch.setattr(
        kernel, "run_geometry", lambda *args: pytest.fail("zero/M5 launched native")
    )
    data.kernel = {"status": "ok", "setups": {"S1": {"zero_pickups": {}}}}
    if proof_status is not None:
        proof = native_proof(request, status=proof_status)
        if proof_status == "error":
            proof["errors"] = ["finder shank collides with stop"]
        data.kernel["setups"]["S1"]["zero_pickups"]["x"] = proof
    finding = rule.evaluate(data)[0]
    axis = finding.numbers["axes"]["x"]
    assert axis["axis_set"] == pytest.approx(-2.54)
    assert axis["check_reading"] == pytest.approx(2.46)
    assert axis["axis_set_status"] == "computed"
    assert axis["pickup_proof"]["status"] == (proof_status or "unknown")
    assert finding.numbers["zero_pickups"]["x"] == axis["pickup_proof"]
    if proof_status != "pass":
        assert finding.status == ("error" if proof_status == "error" else "unknown")
        assert "Arithmetic Axis Sets do not establish pickup clearance" in finding.sentence
