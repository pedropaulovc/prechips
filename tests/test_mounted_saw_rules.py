"""Finite-saw consumers require complete, independent native evidence."""

import pytest
from test_slitting_saw import op_row, slitting_bundle

from prechips import kernel
from prechips.rules import (
    accessibility,
    geometry_common,
    purchased_tooling,
    reach,
    saw_cut,
    tool_resolves,
)
from prechips.rules.geometry_common import finite_saw_evidence, mounted_saw_assembly_evidence
from prechips.rules.resolution import setup_items
from prechips.sheet import _Traveler


def normalized_assembly():
    return {
        "model": "finite_disk_v1",
        "assembly_reasons": {},
        "assembly_errors": {},
        "reasons": {},
        "errors": {},
        "blade": {
            "dia_mm": 50.8,
            "root_dia_mm": 48.0,
            "bore_dia_limits_mm": [12.7, 12.71],
            "thickness_mm": 3.05,
            "kerf_mm": 3.175,
            "kerf_offset_mm": 0.0,
            "flutes": 36,
            "tooth_spacing": "uniform",
        },
        "arbor": {
            "projection_mm": 45.0,
            "gauge_len_mm": 3.0,
            "pilot_dia_limits_mm": [12.69, 12.7],
            "bore_clearance_max_mm": 0.025,
            "blade_thickness_limits_mm": [3.0, 3.2],
            "envelope_state": "complete",
            "components": [
                {"id": "flange", "dia_mm": 20.0, "z_min_mm": -43.475, "z_max_mm": -40.0},
                {"id": "stem", "dia_mm": 12.7, "z_min_mm": -40.0, "z_max_mm": 3.0},
            ],
            "cutting_rotation": "cw",
            "retaining_side": "minus_z",
            "retaining_thread_hand": "right",
        },
        "spindle_rotation": "cw",
    }


def zero_evidence():
    return {
        "status": "pass",
        "reasons": [],
        "selected": 0,
        "touches": [
            {
                "index": 0,
                "status": "pass",
                "reasons": [],
                "blade_side": "minus_z",
                "surface_side": "+z",
                "spindle_state": "stopped",
                "plane_z_mm": 10.0,
                "plane_normal_z": 1,
                "point_mm": [15.0, 0.0, 10.0],
                "axis_xy_mm": [0.0, 0.0],
                "paper_mm": 0.05,
                "body_thickness_mm": 3.05,
                "kerf_offset_mm": 0.0,
                "body_face_z_mm": 10.05,
                "cutting_midplane_z_mm": 11.575,
                "contact_radius_mm": 15.0,
                "exposed_inner_radius_mm": 10.0,
                "root_radius_mm": 24.0,
                "approach_start_z_mm": 16.575,
                "approach_end_z_mm": 11.575,
                "assembly_swept_bounds_mm": [-25.4, -25.4, 9.9875, 25.4, 25.4, 64.575],
                "collisions": [],
            }
        ],
    }


def finite_saw():
    return {
        "model": "finite_disk_v1",
        "status": "pass",
        "reasons": [],
        "body_band_mm": [3.475, 6.525],
        "cutting_band_mm": [3.4125, 6.5875],
        "gauge_plane_z_mm": 50.0,
        "spindle_nose_z_mm": 53.0,
        "axis_path_bounds_mm": [-40.0, -10.541, 5.0, 40.0, 0.0, 64.575],
        "assembly_swept_bounds_mm": [-65.4, -35.941, 3.4125, 65.4, 25.4, 64.575],
        "spindle_nose_bounds_mm": [-40.0, -10.541, 53.0, 40.0, 0.0, 64.575],
        "feed_direction": [1.0, 0.0, 0.0],
        "cut_move_index": 0,
        "collisions": [],
        "required_kerf_volume_mm3": 635.0,
        "uncovered_kerf_volume_mm3": 0.0,
        "removed_kerf_volume_mm3": 635.0,
        "unintended_removal_volume_mm3": 0.0,
        "stock_volume_before_mm3": 20000.0,
        "stock_volume_after_mm3": 19365.0,
        "outputs": [
            {"side": "below", "volume_mm3": 10000.0, "bbox_mm": [0, 0, 0, 100, 20, 3.4125]},
            {"side": "above", "volume_mm3": 9365.0, "bbox_mm": [0, 0, 6.5875, 100, 20, 10]},
        ],
        "capture": {
            "status": "pass",
            "reasons": [],
            "contacts": ["capture:fixture", "capture:moving_clamp"],
            "moving_clamp_contact": True,
        },
        "engagement": {
            "status": "pass",
            "reasons": [],
            "radius_mm": 25.4,
            "transverse_interval_mm": [10.541, 20.541],
            "first_contact_mm": 0.0,
            "entry_complete_mm": 10.0,
            "exit_begins_mm": 20.0,
            "last_contact_mm": 30.0,
            "established_interval_mm": [10.0, 20.0],
            "engaged_angle_rad": 0.7,
            "entry": {
                "from_mm": 0.0,
                "to_mm": 10.0,
                "monotone": True,
                "tooth_loading_certified": False,
            },
            "exit": {
                "from_mm": 20.0,
                "to_mm": 30.0,
                "monotone": True,
                "tooth_loading_certified": False,
            },
            "tooth_count": 36,
            "tooth_spacing": "uniform",
            "pitch_rad": 0.174532925,
            "minimum_teeth_in_work": 3,
            "minimum_teeth_tie": False,
        },
        "zero": zero_evidence(),
    }


def finite_bundle(monkeypatch):
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    setup["ops"][0]["cut_plane"] = {"axis": "z", "value": 5.0, "keep": "below"}
    data.inventory["tools"]["blade"].update(flutes=36, tooth_spacing="uniform", kerf_mm=3.175)
    data.kernel["ops"]["S1:20"]["saw"] = finite_saw()
    data.policy.update(
        numbers={"saw_min_teeth_in_work": 3},
        numbers_verify=False,
        numbers_cite={"saw_min_teeth_in_work": "synthetic shop policy"},
    )
    monkeypatch.setattr(kernel, "mounted_saw_inputs", lambda *_: normalized_assembly())
    monkeypatch.setattr(
        geometry_common,
        "prepared_job",
        lambda *_: {
            "setups": [
                {
                    "id": "S1",
                    "hold": {},
                    "frame": {},
                    "ops": [
                        {
                            "subject": "S1:20",
                            "mounted_saw": normalized_assembly(),
                        }
                    ],
                }
            ],
        },
    )
    return data


@pytest.mark.parametrize(
    "check",
    ["geometry", "accessibility", "reach", "engagement", "zero", "envelope", "headroom", "travel"],
)
def test_a_model_and_pass_marker_alone_never_authorize_a_check(check):
    status, reasons, _ = finite_saw_evidence(
        {"saw": {"model": "finite_disk_v1", "status": "pass"}}, check
    )
    assert status == "unknown"
    assert reasons


@pytest.mark.parametrize(
    "check",
    ["geometry", "accessibility", "reach", "engagement", "zero", "envelope", "headroom", "travel"],
)
def test_complete_per_check_evidence_is_accepted(check):
    status, reasons, proof = finite_saw_evidence({"saw": finite_saw()}, check)
    assert status == "pass"
    assert reasons == []
    assert proof["model"] == "finite_disk_v1"


@pytest.mark.parametrize(
    "field",
    [
        "body_band_mm",
        "cutting_band_mm",
        "axis_path_bounds_mm",
        "assembly_swept_bounds_mm",
        "spindle_nose_bounds_mm",
        "required_kerf_volume_mm3",
        "outputs",
        "capture",
        "collisions",
    ],
)
def test_missing_geometry_fact_is_not_replaced_by_other_successes(field):
    proof = finite_saw()
    del proof[field]
    assert finite_saw_evidence({"saw": proof}, "geometry")[0] == "unknown"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "unknown"])
def test_nonfinite_or_boolean_native_volume_is_debt(value):
    proof = finite_saw()
    proof["required_kerf_volume_mm3"] = value
    assert finite_saw_evidence({"saw": proof}, "geometry")[0] == "unknown"


@pytest.mark.parametrize("field", ["uncovered_kerf_volume_mm3", "unintended_removal_volume_mm3"])
def test_certain_bad_geometry_outranks_other_missing_facts(field):
    proof = finite_saw()
    del proof["body_band_mm"]
    proof[field] = 0.25
    assert finite_saw_evidence({"saw": proof}, "geometry")[0] == "error"


def test_geometry_and_engagement_have_independent_status():
    proof = finite_saw()
    proof["engagement"] = {"status": "unknown", "reasons": ["unsupported hollow section"]}
    assert finite_saw_evidence({"saw": proof}, "geometry")[0] == "pass"
    assert finite_saw_evidence({"saw": proof}, "engagement")[0] == "unknown"
    proof["engagement"] = finite_saw()["engagement"]
    proof["status"] = "error"
    proof["reasons"] = ["arbor collision"]
    assert finite_saw_evidence({"saw": proof}, "geometry")[0] == "error"
    assert finite_saw_evidence({"saw": proof}, "engagement")[0] == "pass"


def test_assembly_does_not_borrow_trajectory_or_zero_status():
    assembly = normalized_assembly()
    assembly["reasons"] = {"zero": "no setting"}
    assert mounted_saw_assembly_evidence(assembly) == ("pass", [])
    assembly["assembly_errors"] = {"pilot": "pilot exceeds blade bore"}
    assembly["blade"]["root_dia_mm"] = "unknown"
    assert mounted_saw_assembly_evidence(assembly)[0] == "error"


@pytest.mark.parametrize("rule", [accessibility, reach, saw_cut, tool_resolves])
def test_rule_consumers_accept_complete_finite_not_axial_evidence(monkeypatch, rule):
    data = finite_bundle(monkeypatch)
    assert op_row(rule, data).status == "pass"


@pytest.mark.parametrize("rule", [accessibility, reach, saw_cut])
def test_mid_sweep_collision_is_an_error_even_beside_missing_body_fact(monkeypatch, rule):
    data = finite_bundle(monkeypatch)
    proof = data.kernel["ops"]["S1:20"]["saw"]
    del proof["body_band_mm"]
    proof["collisions"] = [
        {
            "component": "arbor:flange",
            "obstacle": "raised_jaw",
            "move_index": 1,
            "mode": "cut",
            "volume_mm3": 2.0,
            "bbox_mm": [0, 0, 4, 1, 1, 5],
        }
    ]
    assert op_row(rule, data).status == "error"


@pytest.mark.parametrize(
    ("teeth", "minimum", "tie", "expected"),
    [
        (3, 3, False, "pass"),
        (1, 3, False, "error"),
        (2, 3, True, "unknown"),
        (3, 3, True, "pass"),
        (1, 3, True, "error"),
    ],
)
def test_circular_threshold_uses_strict_interior_minimum_and_resolves_ties(
    monkeypatch, teeth, minimum, tie, expected
):
    data = finite_bundle(monkeypatch)
    proof = data.kernel["ops"]["S1:20"]["saw"]
    proof["engagement"].update(minimum_teeth_in_work=teeth, minimum_teeth_tie=tie)
    data.policy["numbers"]["saw_min_teeth_in_work"] = minimum
    [row] = saw_cut.evaluate_teeth(data)
    assert row.status == expected


def test_circular_count_must_match_installed_teeth_not_linear_tpi(monkeypatch):
    data = finite_bundle(monkeypatch)
    data.inventory["tools"]["blade"].update(flutes=18, tpi=200)
    [row] = saw_cut.evaluate_teeth(data)
    assert row.status == "unknown"


def test_sheet_debt_follows_each_actual_finite_check(monkeypatch):
    data = finite_bundle(monkeypatch)
    setup = data.plan["setups"][0]
    traveler = _Traveler(data, [], {}, None)
    assert not traveler.spindle_saw_debt(setup, "geometry")
    assert not traveler.spindle_saw_debt(setup, "zero")
    proof = data.kernel["ops"]["S1:20"]["saw"]
    proof["zero"]["status"] = "unknown"
    proof["zero"]["reasons"] = ["fixture setting contact not established"]
    assert traveler.spindle_saw_debt(setup, "zero")
    assert not traveler.spindle_saw_debt(setup, "geometry")
    proof["collisions"] = [
        {
            "component": "blade_body",
            "obstacle": "raised_jaw",
            "move_index": 0,
            "mode": "cut",
            "volume_mm3": 1.0,
            "bbox_mm": [0, 0, 4, 1, 1, 5],
        }
    ]
    assert traveler.spindle_saw_debt(setup, "geometry")
    del data.kernel["ops"]["S1:20"]["saw"]
    assert traveler.spindle_saw_debt(setup, "geometry")


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_sheet_reach_accepts_complete_finite_saw_without_axial_debt(monkeypatch, detail):
    data = finite_bundle(monkeypatch)
    setup = data.plan["setups"][0]
    finding = op_row(reach, data)
    assert finding.status == "pass"
    assert set(finding.numbers) == {"operation", "saw"}
    traveler = _Traveler(data, [finding], {}, None, detail=detail)
    candidates, actions = [], []

    traveler.reach_candidates(setup, setup["ops"][0], candidates, actions)

    assert candidates == []
    assert actions == []
    assert traveler.producer_decisions.get("S1", []) == []


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
@pytest.mark.parametrize(
    "evidence,status",
    [
        ("missing", "unknown"),
        ("model-marker-only", "unknown"),
        ("missing-body-band", "unknown"),
        ("collision", "error"),
        ("native-error", "error"),
    ],
)
def test_sheet_reach_preserves_finite_saw_debt_without_axial_fallback(
    monkeypatch, detail, evidence, status
):
    data = finite_bundle(monkeypatch)
    setup = data.plan["setups"][0]
    native = data.kernel["ops"]["S1:20"]
    if evidence == "missing":
        del native["saw"]
    elif evidence == "model-marker-only":
        native["saw"] = {"model": "finite_disk_v1", "status": "pass"}
    elif evidence == "missing-body-band":
        del native["saw"]["body_band_mm"]
    elif evidence == "native-error":
        native["saw"]["status"] = "error"
        native["saw"]["reasons"] = ["native finite sweep failed"]
    else:
        native["saw"]["collisions"] = [
            {
                "component": "blade_body",
                "obstacle": "raised_jaw",
                "move_index": 0,
                "mode": "cut",
                "volume_mm3": 1.0,
                "bbox_mm": [0, 0, 4, 1, 1, 5],
            }
        ]
    finding = op_row(reach, data)
    assert finding.status == status
    traveler = _Traveler(data, [finding], {}, None, detail=detail)
    candidates, actions = [], []

    traveler.reach_candidates(setup, setup["ops"][0], candidates, actions)

    assert candidates == []
    (action,) = actions
    assert (action.source, action.status, action.scope, action.kind) == (
        "finite_saw",
        status,
        "S1:20",
        "block",
    )
    (decision,) = traveler.producer_decisions["S1"]
    assert (decision.source, decision.status, decision.scope, decision.kind) == (
        "finite_saw",
        status,
        "S1:20",
        "block",
    )
    assert str(action)
    assert decision.text == str(action)


def test_capture_and_fixture_setting_pad_keep_inventory_acceptance_ownership():
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    setup["ops"][0]["saw_capture"] = {
        "fixture": "fixtures.capture",
        "moving_clamp": "fixtures.clamp",
        "state": "clamped",
    }
    setup["zero"] = {
        "z": {
            "method": "mounted_saw_side",
            "tool": "blade",
            "holder": "holder",
            "face": "fixture:fixtures.setting-pad/contact:+z",
        }
    }
    for reference in ("capture", "clamp", "setting-pad"):
        data.inventory["fixtures"][reference] = {
            "kind": "custom",
            "acceptance": "unknown",
            "note": "synthetic fixture",
        }
    # Same-key gauges are not the fixtures the saw physically uses.
    data.inventory["gauges"] = {"capture": {"kind": "caliper", "acceptance": []}}
    identities = {(category, reference) for category, reference, _ in setup_items(data, setup)}
    expected = {("fixtures", reference) for reference in ("capture", "clamp", "setting-pad")}
    assert expected <= identities
    assert ("gauges", "capture") not in identities
    [row] = purchased_tooling.evaluate(data)
    assert row.status == "unknown"
    assert expected <= {(item["category"], item["ref"]) for item in row.numbers["items"]}


def test_ambiguous_selected_native_touch_never_authorizes_zero():
    proof = finite_saw()
    proof["zero"]["touches"].append(dict(proof["zero"]["touches"][0]))
    assert finite_saw_evidence({"saw": proof}, "zero")[0] == "unknown"


@pytest.mark.parametrize("index", [False, "0"])
def test_native_touch_index_is_not_coerced(index):
    proof = finite_saw()
    proof["zero"]["touches"][0]["index"] = index
    assert finite_saw_evidence({"saw": proof}, "zero")[0] == "unknown"


def test_geometry_requires_both_physical_output_sides():
    proof = finite_saw()
    proof["outputs"][1]["side"] = "below"
    assert finite_saw_evidence({"saw": proof}, "geometry")[0] == "unknown"


@pytest.mark.parametrize("diameter", [0, -50.8])
def test_refused_diameter_keeps_host_diagnostic_without_admitting_geometry(monkeypatch, diameter):
    data = finite_bundle(monkeypatch)
    data.inventory["tools"]["blade"]["dia_mm"] = diameter
    assembly = normalized_assembly()
    assembly["blade"]["dia_mm"] = "unknown"
    assembly["assembly_errors"] = {"blade.dia_mm": "blade diameter must be positive"}
    assembly["diagnostics"] = {"blade_diameter_mm": diameter}
    monkeypatch.setattr(kernel, "mounted_saw_inputs", lambda *_: assembly)
    row = op_row(tool_resolves, data)
    assert row.status == "error"
    assert row.numbers["blade_diameter_mm"] == diameter
    assert row.numbers["mounted_saw"]["blade"]["dia_mm"] == "unknown"


def support_calibration_case():
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    data.features["units"] = "mm"
    pose = {"origin_mm": [-119.38, 0, -75], "x": [1, 0, 0], "z": [0, 0, 1]}
    setup["hold"] = {
        "supports": [
            {"placement": "posed", "id": "setting-post", "ref": "saw-setting-post", "pose": pose}
        ]
    }
    setup["zero"] = {
        "z": {
            "method": "mounted_saw_side",
            "tool": "blade",
            "holder": "holder",
            "face": "fixture:fixtures.saw-setting-post/boss:+z",
            "edge_mm": 10.16,
            "paper_mm": 0.05,
            "mounted_saw": {
                "spindle_state": "stopped",
                "blade_side": "minus_z",
                "axis_xy_mm": [-139.7, 0],
                "point_mm": [-119.38, 0, 10.16],
            },
        }
    }
    data.inventory["fixtures"]["saw-setting-post"] = {
        "kind": "custom",
        "solids": [
            {"name": "boss", "shape": "box", "at_mm": [-1, -1, 83.16], "size_mm": [2, 2, 2]}
        ],
    }
    return data, setup


def support_calibration(data, setup):
    from prechips.kernel.mounted_saw import _zero

    return _zero(kernel, data, setup, setup["ops"][0], {"components": []})


@pytest.mark.parametrize("reference", ["saw-setting-post", "fixtures.saw-setting-post"])
def test_mounted_saw_calibration_resolves_posed_support_canonical_component(reference):
    data, setup = support_calibration_case()
    setup["hold"]["supports"][0]["ref"] = reference
    zero = support_calibration(data, setup)
    assert zero["selected"] == 0
    assert zero["reasons"] == []
    assert zero["errors"] == []
    assert zero["touches"][0]["surface"] == {
        "kind": "fixture",
        "name": f"{reference}:boss",
        "side": "+z",
    }
    [fixture] = zero["fixtures"]
    assert fixture["pose"] == setup["hold"]["supports"][0]["pose"]
    assert fixture["solids"][0]["local"] == "boss"
    assert fixture["solids"][0]["size_mm"] == [2, 2, 2]


def test_mounted_saw_calibration_support_unknown_pose_remains_debt():
    data, setup = support_calibration_case()
    setup["hold"]["supports"][0]["pose"] = "unknown"
    zero = support_calibration(data, setup)
    assert zero["fixtures"][0]["pose"] == "unknown"
    assert "calibration needs an orthonormal setup-mm pose" in zero["reasons"]


@pytest.mark.parametrize("debt", ["dimension", "verification"])
def test_mounted_saw_calibration_support_unknown_solid_remains_debt(debt):
    data, setup = support_calibration_case()
    solid = data.inventory["fixtures"]["saw-setting-post"]["solids"][0]
    if debt == "dimension":
        solid["size_mm"] = "unknown"
    else:
        solid["verify"] = True
    zero = support_calibration(data, setup)
    assert zero["fixtures"][0]["solids"] == []
    assert zero["reasons"]
    assert zero["touches"][0]["surface"]["name"] == "unknown"
    assert "mounted-saw calibration names no solid component in its fixture" in zero["errors"]


@pytest.mark.parametrize("other_role", ["support", "clamp"])
def test_mounted_saw_calibration_repeated_support_fixture_is_ambiguous(other_role):
    data, setup = support_calibration_case()
    support = setup["hold"]["supports"][0]
    if other_role == "support":
        setup["hold"]["supports"].append({**support, "id": "second-setting-post"})
    else:
        setup["hold"]["clamps"] = [{"ref": support["ref"], "pose": support["pose"]}]
    zero = support_calibration(data, setup)
    assert len(zero["fixtures"]) == 2
    assert zero["touches"][0]["surface"]["name"] == "unknown"
    assert "mounted-saw calibration fixture placement is ambiguous" in zero["reasons"]


@pytest.mark.parametrize(
    "support",
    [
        "saw-setting-post",
        {"ref": "saw-setting-post"},
        {"placement": "posed", "id": "borrowed-stock", "stock_ref": "saw-setting-post"},
    ],
)
def test_mounted_saw_calibration_does_not_infer_support_fixture_placement(support):
    data, setup = support_calibration_case()
    setup["hold"]["supports"] = [support]
    zero = support_calibration(data, setup)
    assert zero["fixtures"] == []
    assert zero["touches"][0]["surface"]["name"] == "unknown"
    assert "mounted-saw calibration fixture has no explicit posed placement" in zero["reasons"]
