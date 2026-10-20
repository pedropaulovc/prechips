"""Host acceptance of complete initial arriving-top proofs, never native execution.

The proof helper is an explicitly synthetic serialized witness for a rectangular
20 x 10 mm stock top. Its circle/rectangle contact areas and stack sweep bounds are
computed from that synthetic geometry; it is not a claim about a real part or seat.
"""

import math
from copy import deepcopy

import pytest
from test_arriving_top_inputs import MEASUREMENT, arriving_top_bundle, measured
from test_procedure_boxes import mill_bundle

from prechips import kernel
from prechips.rules import coordinates
from prechips.rules.coordinates import dro_grid, dro_z
from prechips.rules.resolution import LENGTH_TOLERANCE_MM
from prechips.rules.tip_endpoints import top_reader
from prechips.rules.zero_recipe import native as native_pickup
from prechips.rules.zero_recipe import rule, tool_setting
from prechips.rules.zero_recipe.native import zero_pickup_evidence
from prechips.rules.zero_recipe.tool_setting import face_stands


def proof_bundle(tmp_path, *, units="mm"):
    """A fully declared synthetic stock and low table, with no cached pickup proof."""
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup["zero"]["z"]["check_jog_mm"] = 3.0
    data.plan["stock"].update(
        origin_mm=[0, 0, 0],
        axis=[1, 0, 0],
        section_axis=[0, 1, 0],
        length_mm=20,
        section_mm=[10, 10],
    )
    data.inventory["fixtures"]["table"] = {
        "kind": "custom",
        "solids": [
            {
                "name": "table",
                "shape": "box",
                "at_mm": [-50, -50, -10],
                "size_mm": [100, 100, 5],
                "measured": dict(MEASUREMENT),
            }
        ],
    }
    setup["hold"] = {
        "fixture": "table",
        "pose": {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
    }
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.001)
    if units == "in":
        data.features["units"] = units
        setup["stock_state"]["top_z"] /= 25.4
        source = setup["zero"]["z"]
        source["at_mm"] = [value / 25.4 for value in source["at_mm"]]
        for key in ("paper_mm", "retract_clearance_mm", "check_jog_mm"):
            source[key] /= 25.4
    data.kernel["setups"]["S1"]["zero_pickups"] = {}
    data.kernel["bbox_mm"] = [0, 0, 0, 20, 10, 10]
    return data, setup


def synthetic_top_proof(data, setup, request, *, plane=None):
    """Complete host contract fixture, including legitimate cutter-disk overhang.

    The disk centre is 0.5 mm inside the stock's x=0 edge, so the entire 0.5 mm
    square land fits while part of the cutter disk does not. The positive Z jog
    starts at contact, then retracts; all occupied component boxes stay above stock.
    """
    plane = request["edge_mm"] if plane is None else plane
    x, y = request["at_mm"]
    envelope = request["tool_envelope"]
    radius = envelope["tip_dia_mm"] / 2
    footprint_area = math.pi * radius * radius
    contact_area = radius * radius * (math.pi / 2 + math.asin(x / radius)) + x * math.sqrt(
        radius * radius - x * x
    )
    land = request["contact_land_mm"]
    half = land / 2
    start = [x, y, plane + request["retract_clearance_mm"]]
    contact = [x, y, plane + request["paper_mm"]]
    checked = [x, y, contact[2] + request["check_jog_mm"]]
    points = [start, contact, checked, start]
    legs = []
    for index, kind in enumerate(("descend", "check_jog", "retract")):
        begin, end = points[index], points[index + 1]
        low, high = min(begin[2], end[2]), max(begin[2], end[2])
        components = []
        for identity, dia, bottom, top in (
            ("tip", envelope["tip_dia_mm"], 0, envelope["tip_length_mm"]),
            (
                "shank",
                envelope["shank_dia_mm"],
                envelope["tip_length_mm"],
                envelope["projection_mm"],
            ),
            (
                "holder",
                envelope["holder_dia_mm"],
                envelope["projection_mm"],
                envelope["projection_mm"] + envelope["holder_gauge_len_mm"],
            ),
        ):
            r = dia / 2
            components.append(
                {"id": identity, "bbox_mm": [x - r, y - r, low + bottom, x + r, y + r, high + top]}
            )
        legs.append(
            {
                "index": index,
                "kind": kind,
                "from_mm": list(begin),
                "to_mm": list(end),
                "components": components,
            }
        )
    stock_box = [0, 0, 0, 20, 10, plane]
    native_setup = next(
        entry
        for entry in kernel.engine_job(kernel.build_job(data))["setups"]
        if entry["id"] == setup["id"]
    )
    return {
        "model": request["model"],
        "setup_id": setup["id"],
        "axis": "z",
        "recipe_id": request["recipe_id"],
        "request": deepcopy(request),
        "status": "pass",
        "reasons": [],
        "errors": [],
        "collisions": [],
        "arrival": {
            "position": request["position"],
            "after_op": (
                str(setup["ops"][request["position"] - 1]["op"]) if request["position"] else None
            ),
            "before_op": (
                str(setup["ops"][request["position"]]["op"])
                if request["position"] < len(setup["ops"])
                else "unknown"
            ),
            "stock_in": setup["stock_in"],
            "frame": deepcopy(native_setup["frame"]),
            "components": ["stock"],
            "workpiece_ids": [],
            "partition_path": [],
        },
        "stock_bbox_mm": stock_box,
        "physical_upper_bound_mm": plane,
        "obstacles": [
            {"name": "stock", "bbox_mm": list(stock_box)},
            {
                "name": native_setup["hold"]["solids"][0]["name"],
                "bbox_mm": [-50, -50, -10, 50, 50, -5],
            },
        ],
        "resolved_contact": {
            "surface": deepcopy(request["surface"]),
            "contact_model": "flat_end_projection_v1",
            "plane_mm": plane,
            "point_mm": [x, y, plane],
            "axis_mm": contact,
            "normal": [0, 0, 1],
            "land_mm": land,
            "land_bbox_mm": [x - half, y - half, plane, x + half, y + half, plane],
            "land_area_mm2": land * land,
            "missing_land_area_mm2": 0.0,
            "footprint_radius_mm": radius,
            "footprint_area_mm2": footprint_area,
            "contact_area_mm2": contact_area,
            "uncovered_area_mm2": footprint_area - contact_area,
            "patch_bbox_mm": [0, y - radius, plane, x + radius, y + radius, plane],
            "patch_area_mm2": contact_area,
            "patch_face_indices": [0],
        },
        "path": {
            "complete": True,
            "start_mm": start,
            "contact_mm": contact,
            "stock_top_mm": plane,
            "retract_height_mm": start[2],
            "jog_mm": request["check_jog_mm"],
            "legs": legs,
        },
    }


def install_proof(data, setup, *, plane=None):
    normalized = kernel.zero_pickup_inputs(data, setup)
    request = normalized["requests"]["z"]
    proof = synthetic_top_proof(data, setup, request, plane=plane)
    data.kernel["setups"][setup["id"]]["zero_pickups"]["z"] = proof
    return normalized, proof


def install_selected_patch_proof(data, setup, selected_bounds=(0, 4.5, 1, 5.5)):
    """A serialized contract fixture with two separate, finite top-contact pads.

    This is a synthetic native-result payload, not a run or a geometry certificate.
    Both rectangles fit the disk; only the selected one must contain the touch land.
    """
    normalized, proof = install_proof(data, setup)
    contact = proof["resolved_contact"]
    patches = [selected_bounds, (2, 4.5, 3, 5.5)]
    x, y = contact["point_mm"][:2]
    radius = contact["footprint_radius_mm"]
    for left, bottom, right, top in patches:
        assert all(
            math.hypot(px - x, py - y) <= radius for px in (left, right) for py in (bottom, top)
        )
    areas = [(right - left) * (top - bottom) for left, bottom, right, top in patches]
    left, bottom, right, top = selected_bounds
    plane = contact["plane_mm"]
    contact.update(
        patch_bbox_mm=[left, bottom, plane, right, top, plane],
        patch_area_mm2=areas[0],
        contact_area_mm2=sum(areas),
        uncovered_area_mm2=contact["footprint_area_mm2"] - sum(areas),
    )
    return normalized, proof


def test_complete_top_witness_accepts_finite_land_even_when_full_disk_overhangs(tmp_path):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["requested"] is True
    assert result["status"] == "pass"
    assert result["model"] == "arriving_top_v1"
    assert result["axis"] == "z"
    assert result["request"] == normalized["requests"]["z"]
    assert result["proof"] == proof
    assert result["resolved_contact"] == proof["resolved_contact"]
    contact = result["resolved_contact"]
    assert contact["point_mm"] == [0.5, 5.0, 10.0]
    assert contact["axis_mm"] == [0.5, 5.0, 10.05]
    assert contact["land_bbox_mm"] == [0.25, 4.75, 10.0, 0.75, 5.25, 10.0]
    assert contact["land_area_mm2"] == 0.25
    assert contact["missing_land_area_mm2"] == 0
    assert contact["contact_model"] == "flat_end_projection_v1"
    assert contact["footprint_radius_mm"] == 3
    assert contact["footprint_area_mm2"] == pytest.approx(math.pi * 9)
    assert contact["uncovered_area_mm2"] > 0
    assert 0.25 < contact["contact_area_mm2"] < contact["footprint_area_mm2"]
    assert result["path"]["complete"] is True
    assert [leg["kind"] for leg in result["path"]["legs"]] == ["descend", "check_jog", "retract"]
    assert result["path"]["legs"][1]["from_mm"] == contact["axis_mm"]
    assert result["path"]["legs"][1]["to_mm"] == [0.5, 5.0, 13.05]
    assert result["collisions"] == result["reasons"] == []


@pytest.mark.parametrize("selected_bounds", [(0, 4.5, 1, 5.5), (0.25, 4.75, 0.75, 5.25)])
def test_selected_connected_land_need_not_cover_every_separate_disk_contact(
    tmp_path, selected_bounds
):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_selected_patch_proof(data, setup, selected_bounds)
    contact = proof["resolved_contact"]
    selected_area = (selected_bounds[2] - selected_bounds[0]) * (
        selected_bounds[3] - selected_bounds[1]
    )
    assert contact["patch_area_mm2"] == selected_area
    assert contact["contact_area_mm2"] == selected_area + 1
    assert contact["land_area_mm2"] <= selected_area < contact["contact_area_mm2"]
    assert contact["contact_area_mm2"] < contact["footprint_area_mm2"]
    assert zero_pickup_evidence(data, setup, "z", normalized=normalized)["status"] == "pass"


@pytest.mark.parametrize(
    "mutation",
    ["smaller_than_land", "larger_than_total", "off_land", "missing_land", "total_below_selected"],
)
def test_separate_contact_cannot_replace_the_selected_finite_land(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_selected_patch_proof(data, setup)
    contact = proof["resolved_contact"]
    if mutation == "smaller_than_land":
        contact["patch_area_mm2"] = 0.2
    elif mutation == "larger_than_total":
        contact["patch_area_mm2"] = 2.1
    elif mutation == "off_land":
        contact["patch_bbox_mm"] = [2, 4.5, 10, 3, 5.5, 10]
    elif mutation == "missing_land":
        contact["missing_land_area_mm2"] = 0.01
    else:
        contact["contact_area_mm2"] = 0.9
        contact["uncovered_area_mm2"] = contact["footprint_area_mm2"] - 0.9
    assert zero_pickup_evidence(data, setup, "z", normalized=normalized)["status"] == "unknown"


@pytest.mark.parametrize(
    "mutation", ["absent", "recipe", "model", "axis", "setup", "request", "marker_only"]
)
def test_absent_stale_other_subject_or_marker_only_proof_cannot_establish_top(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    if mutation == "absent":
        data.kernel["setups"]["S1"]["zero_pickups"].clear()
    elif mutation == "recipe":
        proof["recipe_id"] = "stale-recipe"
    elif mutation == "model":
        proof["model"] = "transverse_finder_v1"
    elif mutation == "axis":
        proof["axis"] = "x"
    elif mutation == "setup":
        proof["setup_id"] = "S2"
    elif mutation == "request":
        proof["request"]["at_mm"][0] += 0.1
    else:
        for key in ("resolved_contact", "path", "obstacles", "physical_upper_bound_mm"):
            proof.pop(key)
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "unknown"
    assert result["reasons"]
    if mutation != "marker_only":
        assert result["proof"] == result["resolved_contact"] == result["path"] == {}


@pytest.mark.parametrize(
    "path,value",
    [
        (("resolved_contact", "surface"), {"kind": "stock", "face": "stock:-z", "side": "-z"}),
        (("resolved_contact", "contact_model"), "marker_only"),
        (("resolved_contact", "normal"), [0, 0, -1]),
        (("resolved_contact", "plane_mm"), 9.0),
        (("resolved_contact", "point_mm"), [0.6, 5, 10]),
        (("resolved_contact", "axis_mm"), [0.5, 5, 10]),
        (("resolved_contact", "land_mm"), 0.49),
        (("resolved_contact", "land_area_mm2"), 0.2),
        (("resolved_contact", "land_bbox_mm"), [0.25, 4.75, 10, 0.75, 5.25, 10.1]),
        (("resolved_contact", "land_bbox_mm"), [0.2, 4.75, 10, 0.7, 5.25, 10]),
        (("resolved_contact", "missing_land_area_mm2"), 0.01),
        (("resolved_contact", "footprint_radius_mm"), 2.5),
        (("resolved_contact", "footprint_area_mm2"), 1.0),
        (("resolved_contact", "contact_area_mm2"), 0.0),
        (("resolved_contact", "contact_area_mm2"), 0.2),
        (("resolved_contact", "uncovered_area_mm2"), -1.0),
        (("resolved_contact", "patch_area_mm2"), 0.2),
        (("resolved_contact", "patch_bbox_mm"), [0.3, 2, 10, 3.5, 8, 10]),
        (("resolved_contact", "plane_mm"), float("nan")),
        (("resolved_contact", "patch_bbox_mm", 3), float("inf")),
        (("physical_upper_bound_mm",), 9.0),
        (("physical_upper_bound_mm",), 11.0),
        (("physical_upper_bound_mm",), float("inf")),
        (("stock_bbox_mm", 5), 11.0),
        (("path", "complete"), False),
        (("path", "contact_mm"), [0.5, 5, 10]),
        (("path", "start_mm", 0), 0.6),
        (("path", "stock_top_mm"), 9.0),
        (("path", "retract_height_mm"), 11.0),
        (("path", "jog_mm"), -3.0),
        (("path", "legs", 0, "kind"), "approach"),
        (("path", "legs", 1, "from_mm"), [0.5, 5, 10.15]),
        (("path", "legs", 1, "to_mm"), [0.5, 5, 22.7]),
        (("path", "legs", 2, "to_mm"), [0.5, 5, 22.8]),
        (("path", "legs", 0, "components"), []),
        (("path", "legs", 1, "components", 1, "id"), "tip"),
        (("path", "legs", 2, "components", 2, "bbox_mm", 5), float("nan")),
        (("path", "legs", 0, "components", 0, "bbox_mm"), [5, 2, 10.05, 3.5, 8, 32.7]),
        (("obstacles",), []),
        (("obstacles", 0, "name"), "not-stock"),
        (("obstacles", 0, "bbox_mm", 5), 9.0),
        (("obstacles", 1, "bbox_mm", 5), float("inf")),
        (("arrival", "position"), 1),
        (("arrival", "stock_in"), "other-route"),
        (("arrival", "frame", "origin", 0), 1.0),
        (("arrival", "before_op"), "20"),
        (("arrival", "after_op"), "10"),
        (("resolved_contact", "patch_face_indices"), []),
        (("resolved_contact", "patch_face_indices"), [-1]),
    ],
)
def test_invalid_contact_land_upper_bound_or_incomplete_stack_path_stays_unknown(
    tmp_path, path, value
):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    target = proof
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "unknown"
    assert result["reasons"]


@pytest.mark.parametrize(
    "path",
    [
        ("physical_upper_bound_mm",),
        ("stock_bbox_mm",),
        ("arrival",),
        ("resolved_contact", "contact_model"),
        ("resolved_contact", "land_bbox_mm"),
        ("resolved_contact", "land_area_mm2"),
        ("resolved_contact", "missing_land_area_mm2"),
        ("resolved_contact", "patch_face_indices"),
        ("resolved_contact", "footprint_area_mm2"),
        ("resolved_contact", "uncovered_area_mm2"),
        ("path", "complete"),
        ("path", "legs", 0, "components", 0, "bbox_mm"),
    ],
)
def test_required_native_contact_and_path_facts_cannot_be_replaced_by_pass_marker(tmp_path, path):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    target = proof
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    assert zero_pickup_evidence(data, setup, "z", normalized=normalized)["status"] == "unknown"


@pytest.mark.parametrize("facts_status", ["unknown", "error"])
def test_complete_payload_cannot_override_unavailable_native_facts(tmp_path, facts_status):
    data, setup = proof_bundle(tmp_path)
    normalized, _ = install_proof(data, setup)
    data.kernel["status"] = facts_status
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "unknown"
    assert result["reasons"]


@pytest.mark.parametrize("mutation", ["native_unknown", "native_reason", "request_reason"])
def test_complete_shape_does_not_erase_current_native_or_input_debt(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    reason = "synthetic unresolved native contact fact"
    if mutation == "native_unknown":
        proof["status"] = "unknown"
    elif mutation == "native_reason":
        proof["reasons"] = [reason]
    else:
        normalized["requests"]["z"]["reasons"] = [reason]
        proof["request"] = deepcopy(normalized["requests"]["z"])
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "unknown"
    assert result["reasons"]


@pytest.mark.parametrize("mutation", ["native_error", "error_marker", "collision", "input_error"])
def test_matching_errors_dominate_other_missing_facts(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    request = normalized["requests"]["z"]
    request["reasons"] = ["synthetic holder qualification remains unresolved"]
    proof["request"] = deepcopy(request)
    proof.pop("resolved_contact")
    proof.pop("path")
    if mutation == "native_error":
        proof["status"] = "error"
        proof["errors"] = ["synthetic holder collision with raised fixture"]
    elif mutation == "error_marker":
        proof["status"] = "error"
    elif mutation == "collision":
        proof["collisions"] = [
            {"component": "holder", "obstacle": "raised fixture", "volume_mm3": 1}
        ]
    else:
        request["errors"] = ["synthetic cutter diameter must be positive"]
        proof["request"] = deepcopy(request)
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "error"
    assert result["reasons"]
    assert any(
        "collision" in reason or "collides" in reason or "failed" in reason or "positive" in reason
        for reason in result["reasons"]
    )


def test_stale_error_is_not_borrowed_but_current_input_error_survives(tmp_path):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    proof.update(recipe_id="old-recipe", status="error", errors=["stale synthetic collision"])
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "unknown"
    assert "stale synthetic collision" not in result["reasons"]
    normalized["requests"]["z"]["errors"] = ["synthetic current diameter must be positive"]
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "error"
    assert "synthetic current diameter must be positive" in result["reasons"]


@pytest.mark.parametrize("mutation", ["xy", "paper", "tool", "route", "frame", "support"])
def test_proof_is_bound_to_exact_current_request_and_current_scene(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    _, proof = install_proof(data, setup)
    if mutation == "xy":
        setup["zero"]["z"]["at_mm"][0] += 0.1
    elif mutation == "paper":
        setup["zero"]["z"]["paper_mm"] += 0.01
    elif mutation == "tool":
        data.inventory["tools"]["em"]["dia_mm"] = measured(6.1)
    elif mutation == "route":
        setup["stock_in"] = "unknown"
    elif mutation == "frame":
        data.features["frames"]["A"]["origin"][0] += 0.1
    else:
        setup["hold"]["pose"]["origin_mm"][2] -= 0.1
    result = zero_pickup_evidence(data, setup, "z")
    assert result["status"] == "unknown"
    assert result["recipe_id"] != proof["recipe_id"]
    assert result["proof"] == {}


@pytest.mark.parametrize("units", ["mm", "in"])
def test_face_stands_returns_raw_actual_plane_in_plan_units_not_callers_nominal(tmp_path, units):
    data, setup = proof_bundle(tmp_path, units=units)
    _, proof = install_proof(data, setup)
    scale = 25.4 if units == "in" else 1.0
    debts, credited, carried = [], [], []
    standing = face_stands(
        data, setup, "top", 9.0 / scale, done=0, debts=debts, credited=credited, carried=carried
    )
    assert standing == pytest.approx(proof["resolved_contact"]["plane_mm"] / scale)
    assert standing != 9.0 / scale
    assert debts == credited == []
    assert carried and carried[0]["native_edge_mm"] == standing


def test_initial_top_reader_uses_physical_plane_before_rounding_not_authored_nominal(tmp_path):
    data, setup = proof_bundle(tmp_path)
    nominal = setup["stock_state"]["top_z"]
    actual = nominal + LENGTH_TOLERANCE_MM / 2
    _, proof = install_proof(data, setup, plane=actual)
    assert zero_pickup_evidence(data, setup, "z")["status"] == "pass"
    read = top_reader(data, setup)
    assert read(nominal, done=0) == dro_z(actual, dro_grid(data, setup))
    assert read(nominal, done=0) != dro_z(nominal, dro_grid(data, setup))
    assert proof["physical_upper_bound_mm"] == actual
    carried = []
    assert face_stands(data, setup, "top", nominal, done=0, carried=carried) == actual
    assert carried[0]["native_edge_mm"] == actual


@pytest.mark.parametrize("mutation", ["absent", "stale", "error", "malformed_point"])
def test_unproved_initial_top_has_debt_and_never_falls_back_to_nominal(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    _, proof = install_proof(data, setup)
    if mutation == "absent":
        data.kernel["setups"]["S1"]["zero_pickups"].clear()
    elif mutation == "stale":
        proof["recipe_id"] = "old-recipe"
    elif mutation == "error":
        proof.update(status="error", errors=["synthetic top path collision"])
    else:
        setup["zero"]["z"]["at_mm"] = "unknown"
    nominal = setup["stock_state"]["top_z"]
    debts = []
    assert top_reader(data, setup)(nominal, done=0) == "unknown"
    assert face_stands(data, setup, "top", nominal, done=0, debts=debts) == "unknown"
    assert debts


def test_initial_proof_cannot_be_reused_by_afterop_top_reader(tmp_path):
    data, setup = proof_bundle(tmp_path)
    nominal = setup["stock_state"]["top_z"]
    install_proof(data, setup, plane=nominal + LENGTH_TOLERANCE_MM / 2)
    with_proof = top_reader(data, setup)(nominal, done=1)
    data.kernel["setups"]["S1"]["zero_pickups"].clear()
    without_proof = top_reader(data, setup)(nominal, done=1)
    # The later material ledger may independently know a surface; initial evidence
    # must not affect that answer, whatever the ledger can establish.
    assert with_proof == without_proof


@pytest.mark.parametrize("after", [10, 999])
def test_afterop_recipe_neither_borrows_initial_proof_nor_aliases_its_request(tmp_path, after):
    data, setup = proof_bundle(tmp_path)
    _, initial = install_proof(data, setup)
    setup["zero"]["z"]["after_op"] = after
    result = zero_pickup_evidence(data, setup, "z")
    assert result["status"] == "unknown"
    assert result["request"]["recipe_id"] != initial["recipe_id"]
    assert result["proof"] == {}
    assert any("first operation" in reason for reason in result["reasons"])


@pytest.mark.parametrize("mutation", ["unrequested", "nonpaper", "named_top"])
def test_nonrequested_and_named_top_never_read_arriving_top_evidence(
    tmp_path, monkeypatch, mutation
):
    data, setup = proof_bundle(tmp_path)
    _, proof = install_proof(data, setup)
    if mutation == "unrequested":
        del setup["zero"]["z"]["at_mm"]
    elif mutation == "nonpaper":
        setup["zero"]["z"]["method"] = "touch"
    else:
        setup["stock_state"]["top_feature"] = "pocket"
    proof["resolved_contact"]["plane_mm"] = 999.0
    nominal = setup["stock_state"]["top_z"]
    with_proof = top_reader(data, setup)(nominal)
    standing_with_proof = face_stands(data, setup, "top", nominal)
    data.kernel["setups"]["S1"]["zero_pickups"].clear()
    assert top_reader(data, setup)(nominal) == with_proof
    assert face_stands(data, setup, "top", nominal) == standing_with_proof
    monkeypatch.setattr(
        kernel,
        "zero_pickup_inputs",
        lambda *args, **kwargs: pytest.fail("unrequested normalization"),
    )
    assert zero_pickup_evidence(data, setup, "z") is None


@pytest.mark.parametrize("proof_status", [None, "pass", "unknown", "error"])
def test_zero_rule_reports_z_proof_without_launching_native_and_keeps_xy_arithmetic_visible(
    tmp_path, monkeypatch, proof_status
):
    data, setup = proof_bundle(tmp_path)
    legacy = mill_bundle()
    data.plan["dro"] = deepcopy(legacy.plan["dro"])
    data.inventory["tools"]["finder"] = deepcopy(legacy.inventory["tools"]["finder"])
    data.inventory["machines"]["mill"]["spindle"] = deepcopy(
        legacy.inventory["machines"]["mill"]["spindle"]
    )
    for axis in ("x", "y"):
        setup["zero"][axis] = deepcopy(legacy.plan["setups"][0]["zero"][axis])
    setup["zero"]["tool_touches"] = []
    if proof_status is not None:
        _, proof = install_proof(data, setup)
        proof["status"] = proof_status
        if proof_status == "error":
            proof["errors"] = ["synthetic top holder collision"]
    monkeypatch.setattr(
        kernel, "run_geometry", lambda *args, **kwargs: pytest.fail("zero rule launched native")
    )
    finding = rule.evaluate(data)[0]
    axes = finding.numbers["axes"]
    assert axes["x"]["axis_set"] == pytest.approx(-2.54)
    assert axes["x"]["check_reading"] == pytest.approx(2.46)
    assert axes["x"]["axis_set_status"] == "computed"
    assert axes["x"]["finder"]["status"] == axes["y"]["finder"]["status"] == "pass"
    assert axes["z"]["pickup_proof"]["status"] == (proof_status or "unknown")
    assert finding.numbers["zero_pickups"]["z"] == axes["z"]["pickup_proof"]
    if proof_status == "pass":
        assert axes["z"]["axis_set"] == pytest.approx(10.05)
        assert axes["z"]["check_reading"] == pytest.approx(13.05)
        assert finding.status == "pass"
    else:
        assert finding.status == ("error" if proof_status == "error" else "unknown")


def test_complete_z_proof_does_not_clear_unknown_xy_finder_spindle_range(tmp_path, monkeypatch):
    data, setup = proof_bundle(tmp_path)
    legacy = mill_bundle()
    data.plan["dro"] = deepcopy(legacy.plan["dro"])
    data.inventory["tools"]["finder"] = deepcopy(legacy.inventory["tools"]["finder"])
    for axis in ("x", "y"):
        setup["zero"][axis] = deepcopy(legacy.plan["setups"][0]["zero"][axis])
    setup["zero"]["tool_touches"] = []
    install_proof(data, setup)
    monkeypatch.setattr(
        kernel, "run_geometry", lambda *args, **kwargs: pytest.fail("zero rule launched native")
    )

    finding = rule.evaluate(data)[0]
    axes = finding.numbers["axes"]
    assert axes["z"]["pickup_proof"]["status"] == "pass"
    assert axes["z"]["axis_set"] == pytest.approx(10.05)
    assert axes["z"]["check_reading"] == pytest.approx(13.05)
    for axis in ("x", "y"):
        assert axes[axis]["finder"]["status"] == "unknown"
        assert axes[axis]["finder"]["machine_rpm"] == "unknown"
        assert axes[axis]["finder"]["rpm"] == "unknown"
        assert axes[axis]["axis_set_status"] == "computed"
    assert axes["x"]["axis_set"] == pytest.approx(-2.54)
    assert axes["x"]["check_reading"] == pytest.approx(2.46)
    assert finding.status == "unknown"


def test_coherent_higher_before_stock_bound_cannot_certify_a_lower_selected_plane(tmp_path):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_proof(data, setup)
    proof["physical_upper_bound_mm"] += 1
    proof["stock_bbox_mm"][5] += 1
    proof["obstacles"][0]["bbox_mm"][5] += 1
    path = proof["path"]
    path["stock_top_mm"] += 1
    path["retract_height_mm"] += 1
    # Keep the motion and occupied-stack bounds coherent with the raised clearance.
    path["start_mm"][2] += 1
    path["legs"][0]["from_mm"][2] += 1
    path["legs"][2]["to_mm"][2] += 1
    for index in (0, 2):
        for component in path["legs"][index]["components"]:
            component["bbox_mm"][5] += 1
    result = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert result["status"] == "unknown"
    assert result["reasons"]


def test_cold_explicit_command_plane_never_becomes_hot_clearance_evidence(tmp_path):
    data, setup = proof_bundle(tmp_path)
    nominal = setup["stock_state"]["top_z"]
    cold_request = kernel.zero_pickup_inputs(data, setup)["requests"]["z"]
    assert top_reader(data, setup, native_top=False)(nominal, done=0) == nominal
    assert top_reader(data, setup)(nominal, done=0) == "unknown"
    assert zero_pickup_evidence(data, setup, "z")["status"] == "unknown"
    _, proof = install_proof(data, setup)
    assert kernel.zero_pickup_inputs(data, setup)["requests"]["z"] == cold_request
    assert (
        kernel.engine_job(kernel.build_job(data))["setups"][0]["zero_pickups"]["z"] == cold_request
    )
    assert zero_pickup_evidence(data, setup, "z")["status"] == "pass"
    assert top_reader(data, setup)(nominal, done=0) == proof["resolved_contact"]["plane_mm"]


@pytest.mark.parametrize(
    "mutation", [None, "missing_stage", "wrong_stage", "initial_alias", "changed_touch"]
)
def test_explicit_tool_touch_requires_its_own_exact_stage_proof(tmp_path, mutation):
    data, setup = proof_bundle(tmp_path)
    data.inventory["tools"]["second_em"] = deepcopy(data.inventory["tools"]["em"])
    # An inspection is a real raw route boundary without a geometry change. The
    # synthetic rectangle therefore remains truthful at both contact stages.
    setup["ops"] = [
        {"op": 10, "do": "inspect", "feature": "pocket"},
        {**deepcopy(setup["ops"][0]), "op": 20, "tool": "second_em"},
    ]
    touch = {
        "tool": "second_em",
        "holder": "holder",
        "z_face": "top",
        "edge_mm": setup["stock_state"]["top_z"],
        "method": "paper",
        "from": "+z",
        "at_mm": [0.5, 5.0],
        "paper_mm": 0.05,
        "retract_clearance_mm": 12.7,
        "check_jog_mm": 3.0,
        "after_op": 10,
        "before_ops": [20],
    }
    setup["zero"]["tool_touches"] = [touch]
    normalized = kernel.zero_pickup_inputs(data, setup)
    initial = synthetic_top_proof(data, setup, normalized["requests"]["z"])
    staged = synthetic_top_proof(data, setup, normalized["requests"]["tool_touch:0"])
    pickups = data.kernel["setups"]["S1"]["zero_pickups"]
    pickups.update({"z": initial, "tool_touch:0": staged})
    if mutation == "missing_stage":
        del pickups["tool_touch:0"]
    elif mutation == "wrong_stage":
        staged["arrival"]["position"] = 0
    elif mutation == "initial_alias":
        pickups["tool_touch:0"] = deepcopy(initial)
    elif mutation == "changed_touch":
        touch["at_mm"][0] += 0.1
    result = zero_pickup_evidence(data, setup, "tool_touch:0")
    debts, carried = [], []
    standing = face_stands(
        data,
        setup,
        "top",
        touch["edge_mm"],
        done=1,
        touch=touch,
        debts=debts,
        carried=carried,
    )
    if mutation is None:
        assert result["status"] == "pass"
        assert result["axis"] == "z" and result["key"] == "tool_touch:0"
        assert result["request"]["position"] == 1
        assert result["request"]["tool"] == "tools.second_em"
        assert result["proof"]["arrival"]["after_op"] == "10"
        assert result["proof"]["arrival"]["before_op"] == "20"
        assert standing == staged["resolved_contact"]["plane_mm"]
        assert carried[0]["pickup_proof"]["key"] == "tool_touch:0"
        assert top_reader(data, setup)(touch["edge_mm"], done=1) == standing
        assert debts == []
    else:
        assert result["status"] == "unknown"
        assert standing == "unknown"
        assert carried == [] and debts
        assert top_reader(data, setup)(touch["edge_mm"], done=1) == "unknown"


@pytest.mark.parametrize("raise_error", [False, True])
def test_cold_coordinate_compiler_uses_command_plane_and_always_resets_context(
    tmp_path, monkeypatch, raise_error
):
    data, setup = proof_bundle(tmp_path)
    data.plan["dro"] = deepcopy(mill_bundle().plan["dro"])
    setup["zero"]["tool_touches"] = []
    nominal = setup["stock_state"]["top_z"]
    assert kernel._TOP_COMMAND_INPUTS.get() is False

    def forbidden(*args, **kwargs):
        pytest.fail("cold coordinate compiler consulted stored native pickup evidence")

    def consume_command(candidate, *, pre_kernel):
        assert candidate is data and pre_kernel is True
        assert kernel._TOP_COMMAND_INPUTS.get() is True
        reading = tool_setting.z_readings(data, setup)["10"]
        assert reading is not setup["zero"]["z"]
        assert reading["face"] == reading["z_face"] == "top"
        assert reading["at_mm"] == setup["zero"]["z"]["at_mm"]
        carried = []
        assert face_stands(data, setup, "top", nominal, carried=carried, touch=reading) == nominal
        assert carried == [{"native_edge_mm": nominal, "requested_top": True}]
        assert all("pickup_proof" not in entry for entry in carried)
        if raise_error:
            raise RuntimeError("synthetic cold coordinate failure")
        return []

    with monkeypatch.context() as patch:
        patch.setattr(coordinates, "evaluate", consume_command)
        patch.setattr(native_pickup, "top_pickup_evidence", forbidden)
        patch.setattr(native_pickup, "zero_pickup_evidence", forbidden)
        if raise_error:
            with pytest.raises(RuntimeError, match="synthetic cold coordinate failure"):
                kernel._cold_coordinates(data)
        else:
            assert kernel._cold_coordinates(data) == {}
    assert kernel._TOP_COMMAND_INPUTS.get() is False
    debts, carried = [], []
    assert face_stands(data, setup, "top", nominal, debts=debts, carried=carried) == "unknown"
    assert debts and carried == []


@pytest.mark.parametrize("raise_error", [False, True])
def test_native_input_decorator_is_command_only_and_resets_after_return_or_error(
    tmp_path, monkeypatch, raise_error
):
    data, setup = proof_bundle(tmp_path)
    nominal = setup["stock_state"]["top_z"]
    original_scene = kernel._pickup_scene_id
    assert kernel._TOP_COMMAND_INPUTS.get() is False

    def forbidden(*args, **kwargs):
        pytest.fail("native input normalization consulted stored pickup evidence")

    def consume_command(*args, **kwargs):
        assert kernel._TOP_COMMAND_INPUTS.get() is True
        carried = []
        assert face_stands(data, setup, "top", nominal, carried=carried) == nominal
        assert carried == [{"native_edge_mm": nominal, "requested_top": True}]
        if raise_error:
            raise RuntimeError("synthetic native input failure")
        return original_scene(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(kernel, "_pickup_scene_id", consume_command)
        patch.setattr(native_pickup, "top_pickup_evidence", forbidden)
        patch.setattr(native_pickup, "zero_pickup_evidence", forbidden)
        if raise_error:
            with pytest.raises(RuntimeError, match="synthetic native input failure"):
                kernel.zero_pickup_inputs(data, setup)
        else:
            request = kernel.zero_pickup_inputs(data, setup)["requests"]["z"]
            assert request["model"] == "arriving_top_v1"
            assert request["reasons"] == request["errors"] == []
    assert kernel._TOP_COMMAND_INPUTS.get() is False
    debts, carried = [], []
    assert face_stands(data, setup, "top", nominal, debts=debts, carried=carried) == "unknown"
    assert debts and carried == []


def test_upstream_explicit_top_does_not_make_cold_recipe_depend_on_hot_pickup_results(tmp_path):
    data, setup = proof_bundle(tmp_path)
    upstream = deepcopy(setup)
    upstream.update(
        id="UPSTREAM",
        stock_in="stock",
        ops=[{"op": 5, "do": "inspect", "feature": "pocket"}],
    )
    setup["stock_in"] = "UPSTREAM"
    data.plan["setups"] = [upstream, setup]
    data.kernel["setups"]["UPSTREAM"] = {"zero_pickups": {}}
    cold = kernel.zero_pickup_inputs(data, setup)["requests"]["z"]
    upstream_request = kernel.zero_pickup_inputs(data, upstream)["requests"]["z"]
    assert kernel.engine_job(kernel.build_job(data))["setups"][-1]["zero_pickups"]["z"] == cold
    upstream_proof = synthetic_top_proof(data, upstream, upstream_request)
    current_proof = synthetic_top_proof(data, setup, cold)
    data.kernel["setups"]["UPSTREAM"]["zero_pickups"]["z"] = upstream_proof
    data.kernel["setups"]["S1"]["zero_pickups"]["z"] = current_proof
    for status in ("pass", "unknown", "error"):
        for proof in (upstream_proof, current_proof):
            proof["status"] = status
            proof["errors"] = ["synthetic hot pickup error"] if status == "error" else []
        assert kernel.zero_pickup_inputs(data, setup)["requests"]["z"] == cold
        projected = kernel.engine_job(kernel.build_job(data))["setups"][-1]["zero_pickups"]["z"]
        assert projected == cold
        assert kernel._TOP_COMMAND_INPUTS.get() is False
