"""Exact transverse pickup proofs on real FreeCAD stock and fixture B-reps.

The helper consumes the native job's existing exact cylinder/stadium sweeper;
these tests do not substitute sampled positions, fake shapes or host verdicts.
The parent coordinated gate owns execution with PRECHIPS_REQUIRE_KERNEL=1.
"""

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from prechips import kernel

_FINDER = {
    "tip_dia_mm": 5.08,
    "tip_length_mm": 6.35,
    "shank_dia_mm": 9.525,
    "projection_mm": 50.8,
    "holder_dia_mm": 32.0,
    "holder_gauge_len_mm": 20.0,
}


def _request(axis="x", *, top=None):
    upright = top is not None
    return {
        "model": "transverse_finder_v1",
        "axis": axis,
        "from": "-" + axis if upright else "+x",
        "method": "edge_then_set",
        "face": "stock:-" + axis if upright else "#304",
        "edge_mm": (-6.2865 if axis == "x" else 0.0) if upright else 12.7,
        "at_mm": [10.541 if axis == "x" else 0.0, top - 2.54] if upright else [-5.08, -2.54],
        "approach_mm": 2.54,
        "retract_clearance_mm": 12.7,
        "check_jog_mm": 6.35,
        "tool": "edge-finder",
        "holder": "collet-9.525",
        "finder": deepcopy(_FINDER),
        "surface": (
            {"kind": "stock", "face": "stock:-" + axis, "side": "-" + axis}
            if upright
            else {"kind": "stock", "face": "#304", "workpiece_id": "nut1"}
        ),
        "reasons": [],
        "errors": [],
    }


def _case(request=None, **geometry):
    return {"request": _request() if request is None else request, **geometry}


_PROBE = r"""
import importlib.util
import json
import os
import sys
from copy import deepcopy
import FreeCAD as App
import Part

out = sys.argv[sys.argv.index("--") + 1]
source = os.environ["PICKUP_KERNEL_SOURCE"]
spec = importlib.util.spec_from_file_location("native_pickup_job", source)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
import zero_pickup
V = App.Vector
with open(os.path.join(out, "cases.json"), encoding="utf-8") as handle:
    cases = json.load(handle)


def box(name, at, size):
    return {"name": name, "solid": Part.makeBox(*size, V(*at))}


def capture(zc, inner):
    parts = [
        box("capture-post", [-20, 40, -75], [40, 10, 225]),
        box("capture-base", [-30, 30, -75], [60, 30, 10]),
        box("capture-left-pad", [-28, 1, zc + 12], [16.8875, 4, 12]),
        box("capture-left-arm", [-28, 1, zc + 24], [28 + inner, 24, 12]),
        box("capture-right-arm", [23, 1, zc + 24], [5, 24, 12]),
        box("capture-rear-rail", [-28, 20, zc + 30], [56, 30, 6]),
        box("capture-moving-pad", [11.1125, 1, zc + 12], [8.8875, 4, 12]),
        box("capture-screw-housing", [20, 0, zc + 12], [8, 6, 18]),
    ]
    for x in (-24, 24):
        parts.append({"name": "capture-base-bolt:" + str(x),
                      "solid": Part.makeCylinder(6, 12, V(x, 45, -65))})
    for name, radius, height, origin, axis in (
        ("capture-screw", 3, 18, [20, 3, zc + 18], [1, 0, 0]),
        ("capture-handle", 5, 6, [38, 3, zc + 18], [1, 0, 0]),
        ("capture-collar-screw", 3, 36, [0, 20, zc + 33], [0, 1, 0]),
        ("capture-collar-head", 5, 6, [0, 14, zc + 33], [0, 1, 0]),
    ):
        parts.append({
            "name": name, "solid": Part.makeCylinder(radius, height, V(*origin), V(*axis))
        })
    return parts


results = {}
for name, case in cases.items():
    request = deepcopy(case["request"])
    axis = case.get("axis_key", request.get("axis", "x"))
    setup = {"id": case.get("setup_id", "E1a"), "zero_pickups": {axis: request}}
    if case.get("no_request"):
        setup.pop("zero_pickups")
    setup["zero_pickup_reasons"] = case.get("scene_reasons", [])
    fixtures = []
    if "top" in case:
        top = case["top"]
        stock = Part.makeBox(22.225, 6.35, top, V(-11.1125, 0, 0)).fuse(
            Part.makeBox(12.573, 6.35, top, V(-6.2865, 6.35, 0))
        ).removeSplitter()
        fixtures = capture(case["zc"], case.get("arm_inner", -23))
        faces = {}
    else:
        left = case.get("left", -13.335)
        stock = Part.makeBox(12.7 - left, 22.225, 6.35, V(left, -11.1125, -12.7)).fuse(
            Part.makeBox(12.7 - left, 12.573, 6.35, V(left, -6.2865, -6.35))
        ).removeSplitter()
        right_faces = [face for face in stock.Faces if abs(face.CenterOfMass.x - 12.7) < 1e-6]
        left_faces = [face for face in stock.Faces if abs(face.CenterOfMass.x - left) < 1e-6]
        faces = {("nut1", "#304"): right_faces, ("nut1", "#320"): left_faces}
        stop_top = case.get("stop_top", -6.35)
        fixtures = [{
            "name": "retained-end-stop",
            "solid": Part.makeCylinder(3.175, 50, V(12.7, 0, stop_top - 3.175), V(1, 0, 0)),
        }]
    for extra in case.get("obstacles", []):
        fixtures.append(box(extra["name"], extra["at"], extra["size"]))
    if case.get("missing_fixture"):
        fixtures.append({"name": "unresolved-support", "solid": None})
    if case.get("fixture_target"):
        fixtures.append(box("datum-pad", [40.0, -6.2865, -12.7], [5.0, 12.573, 12.7]))
    helpers = {"bbox": job._bbox, "sweep": job._FiniteSaw._sweep, "model_faces": faces,
               "plane_tol": job.PLANE_TOL, "hit_mm3": job.HIT_MM3, "area_tol": job.AREA_ABS}
    found = zero_pickup.prove_pickups(App, Part, setup, None if case.get("no_stock") else stock,
                                    fixtures, helpers=helpers)
    results[name] = found if case.get("no_request") or axis == "z" else found[axis]
with open(os.path.join(out, "pickups.json"), "w", encoding="utf-8") as handle:
    json.dump(results, handle)
"""


@pytest.fixture(scope="module")
def native_pickups(tmp_path_factory, freecad_kernel):
    cases = {
        "e1": _case(),
        "raw_end_longer": _case(left=-13.97),
        "raised_stop": _case(stop_top=0.0),
        "boundary_stop": _case(stop_top=-1.27),
        "missing_fixture": _case(missing_fixture=True),
        "no_stock": _case(no_stock=True),
        "scene_debt": _case(scene_reasons=["placed support geometry is unknown"]),
        "no_request": _case(no_request=True),
        "signed_negative": _case(),
    }
    cases["signed_negative"]["request"]["check_jog_mm"] = -6.35
    request = _request()
    request.pop("axis")
    cases["missing_axis_identity"] = _case(request, axis_key="x")
    request = _request()
    request["axis"] = "y"
    cases["wrong_axis_identity"] = _case(request, axis_key="x")
    request = _request("x", top=113.665)
    request["surface"].pop("side")
    cases["missing_raw_side"] = _case(request, top=113.665, zc=86.0425)
    for key in _FINDER:
        request = _request()
        request["finder"][key] = "unknown"
        cases["missing_" + key] = _case(request)
    partial = _request()
    partial["finder"]["holder_dia_mm"] = "unknown"
    cases["partial_and_hit"] = _case(partial, stop_top=0.0)
    for key, value in (
        ("approach_mm", "unknown"),
        ("retract_clearance_mm", "unknown"),
        ("approach_mm", 0.0),
        ("retract_clearance_mm", -1.0),
        ("check_jog_mm", "unknown"),
        ("edge_mm", 13.0),
        ("from", "-x"),
        ("from", "+y"),
        ("at_mm", [-5.08, -25.0]),
        ("at_mm", [100.0, -2.54]),
    ):
        request = _request()
        request[key] = value
        cases[f"mutation_{key}_{value}"] = _case(request)
    request = _request()
    request["finder"]["tip_length_mm"] = 2.0
    cases["short_tip_shank_hits_stock"] = _case(request)
    request = _request()
    request["finder"]["projection_mm"] = 5.0
    cases["short_projection"] = _case(request)
    request = _request()
    request["surface"]["face"] = "#missing"
    cases["missing_target"] = _case(request)
    request = _request()
    request["surface"]["workpiece_id"] = "nut2"
    cases["wrong_member"] = _case(request)
    request = _request()
    request["surface"]["face"] = "#320"
    cases["opposite_target"] = _case(request)
    request = _request()
    request["surface"] = {"kind": "fixture", "name": "missing", "side": "+x"}
    cases["missing_fixture_target"] = _case(request)
    request = _request()
    request["surface"] = {"kind": "fixture", "name": "datum-pad", "side": "+x"}
    request["edge_mm"] = 45.0
    cases["fixture_target"] = _case(request, fixture_target=True)
    cases["fixture_target_no_stock_hit"] = _case(
        deepcopy(request),
        fixture_target=True,
        no_stock=True,
        obstacles=[
            {"name": "fixture-path-blocker", "at": [49.0, -5.2, -2.0], "size": [0.5, 0.2, 1.0]}
        ],
    )
    request = _request()
    request["surface"] = {"kind": "fixture", "name": "retained-end-stop", "side": "+x"}
    cases["fixture_side_mismatch"] = _case(request)
    cases["fixture_side_mismatch"]["request"]["from"] = "-x"
    for name, top, zc in (
        ("c1a", 113.665, 86.0425),
        ("c1b", 84.455, 56.8325),
        ("c2", 55.245, 27.6225),
    ):
        for axis in ("x", "y"):
            cases[name + "_" + axis] = _case(
                _request(axis, top=top), top=top, zc=zc, setup_id=name.upper()
            )
        cases[name + "_narrow_arm"] = _case(_request("x", top=top), top=top, zc=zc, arm_inner=-15.0)
    jog_obstacle = {
        "name": "mid-jog-only",
        "at": [19.4, -0.40, 25.0],
        "size": [0.2, 0.02, 1.0],
    }
    cases["mid_jog_hit"] = _case(obstacles=[jog_obstacle])
    cases["negative_avoids_mid_jog"] = _case(
        deepcopy(cases["signed_negative"]["request"]), obstacles=[jog_obstacle]
    )
    low_bridge = {
        "name": "low-check-bridge",
        "at": [23.0, -6.0, 0.0],
        "size": [1.0, 2.0, 5.0],
    }
    cases["high_clearance"] = _case(obstacles=[low_bridge])
    request = _request()
    request["retract_clearance_mm"] = 1.0
    cases["low_clearance"] = _case(request, obstacles=[low_bridge])
    holder_post = {
        "name": "holder-only-post",
        "at": [30.0, -5.5, 53.0],
        "size": [1.0, 1.0, 2.0],
    }
    cases["holder_hit"] = _case(obstacles=[holder_post])
    cases["z_not_transverse"] = _case(axis_key="z")
    for case in cases.values():
        request = case["request"]
        request["recipe_id"] = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    directory = tmp_path_factory.mktemp("native-pickups")
    script = directory / "prove_pickups.py"
    script.write_text(_PROBE, encoding="utf-8")
    (directory / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
        env={
            **os.environ,
            "PICKUP_KERNEL_SOURCE": str(Path(kernel.__file__).with_name("freecad_job.py")),
        },
    )
    report = directory / "pickups.json"
    assert report.exists(), process.stdout[-4000:] + process.stderr[-4000:]
    return json.loads(report.read_text(encoding="utf-8")), cases


def _proof(native_pickups, name):
    return native_pickups[0][name]


def test_e1_contacts_actual_retained_face_above_stop_with_exact_full_stack(native_pickups):
    proof = _proof(native_pickups, "e1")
    assert proof["status"] == "pass", proof
    assert proof["resolved_contact"]["plane_mm"] == pytest.approx(12.7)
    assert proof["resolved_contact"]["axis_mm"] == pytest.approx([15.24, -5.08, -2.54])
    assert proof["resolved_contact"]["tip_span_mm"] == pytest.approx([-2.54, 3.81])
    assert proof["resolved_contact"]["contact_z_mm"] == pytest.approx([-2.54, 0.0])
    assert proof["path"]["stock_top_mm"] == pytest.approx(0.0)
    assert proof["path"]["retract_height_mm"] == pytest.approx(12.7)
    assert proof["path"]["start_mm"] == pytest.approx([17.78, -5.08, 12.7])
    assert [leg["kind"] for leg in proof["path"]["legs"]] == [
        "descend",
        "approach",
        "retract",
        "check_jog",
    ]
    assert all(
        {component["id"] for component in leg["components"]} == {"tip", "shank", "holder"}
        for leg in proof["path"]["legs"]
    )
    assert proof["collisions"] == []


def test_native_pickup_echoes_exact_current_recipe_axis_and_setup_identity(native_pickups):
    proof = _proof(native_pickups, "e1")
    request = native_pickups[1]["e1"]["request"]
    assert proof["model"] == "transverse_finder_v1"
    assert proof["setup_id"] == "E1a" and proof["axis"] == "x"
    assert proof["recipe_id"] == request["recipe_id"]
    assert proof["request"] == request


def test_raw_end_length_cannot_move_the_retained_e1_datum(native_pickups):
    proof = _proof(native_pickups, "raw_end_longer")
    assert proof["status"] == "pass", proof
    assert proof["resolved_contact"]["plane_mm"] == pytest.approx(12.7)
    assert proof["path"]["contact_mm"] == pytest.approx([15.24, -5.08, -2.54])


def test_raised_stop_is_a_known_tip_path_collision(native_pickups):
    proof = _proof(native_pickups, "raised_stop")
    assert proof["status"] == "error", proof
    assert any(
        hit["component"] == "tip" and hit["obstacle"] == "retained-end-stop"
        for hit in proof["collisions"]
    )
    assert all(hit["volume_mm3"] > 1e-6 for hit in proof["collisions"])


def test_exact_stop_boundary_contact_is_accepted(native_pickups):
    proof = _proof(native_pickups, "boundary_stop")
    assert proof["status"] == "pass", proof
    assert proof["collisions"] == []


@pytest.mark.parametrize("setup", ["c1a", "c1b", "c2"])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_all_three_arriving_stock_tops_drive_the_upright_pickup_path(native_pickups, setup, axis):
    proof = _proof(native_pickups, setup + "_" + axis)
    assert proof["status"] == "pass", proof
    expected_top = {"c1a": 113.665, "c1b": 84.455, "c2": 55.245}[setup]
    assert proof["path"]["stock_top_mm"] == pytest.approx(expected_top)
    assert proof["path"]["start_mm"][2] == pytest.approx(expected_top + 12.7)
    assert proof["resolved_contact"]["tip_span_mm"][0] == pytest.approx(expected_top - 2.54)
    if axis == "x":
        assert proof["path"]["start_mm"][0] == pytest.approx(-11.3665)
        assert proof["path"]["contact_mm"][0] == pytest.approx(-8.8265)
        assert proof["resolved_contact"]["plane_mm"] == pytest.approx(-6.2865)
    else:
        assert proof["path"]["start_mm"][1] == pytest.approx(-5.08)
        assert proof["path"]["contact_mm"][1] == pytest.approx(-2.54)
        assert proof["window"]["transverse_axis"] == "x"
        assert proof["window"]["centre_min_mm"] == pytest.approx(-11.1125)
        assert proof["window"]["centre_max_mm"] == pytest.approx(11.1125)
        assert proof["window"]["scope"] == "contact_only"


@pytest.mark.parametrize("setup", ["c1a", "c1b", "c2"])
def test_earlier_narrow_capture_arm_hits_the_shank_during_exact_approach(native_pickups, setup):
    proof = _proof(native_pickups, setup + "_narrow_arm")
    assert proof["status"] == "error", proof
    assert any(
        hit["component"] == "shank"
        and hit["obstacle"] == "capture-left-arm"
        and hit["kind"] in ("descend", "approach")
        for hit in proof["collisions"]
    )


@pytest.mark.parametrize("dimension", list(_FINDER))
def test_missing_measured_finder_or_selected_holder_extent_never_passes(native_pickups, dimension):
    proof = _proof(native_pickups, "missing_" + dimension)
    assert proof["status"] == "unknown", proof
    assert any(dimension in reason for reason in proof["reasons"])


def test_partial_geometry_cannot_hide_a_known_tip_collision(native_pickups):
    proof = _proof(native_pickups, "partial_and_hit")
    assert proof["status"] == "error", proof
    assert any("holder_dia_mm" in reason for reason in proof["reasons"])
    assert any(hit["component"] == "tip" for hit in proof["collisions"])


@pytest.mark.parametrize("name", ["missing_fixture", "no_stock", "scene_debt"])
def test_incomplete_actual_arriving_scene_is_debt(native_pickups, name):
    proof = _proof(native_pickups, name)
    assert proof["status"] == "unknown", proof
    assert proof["reasons"]


@pytest.mark.parametrize("name", ["missing_target", "wrong_member", "missing_fixture_target"])
def test_missing_selected_target_never_borrows_another_face(native_pickups, name):
    proof = _proof(native_pickups, name)
    assert proof["status"] == "unknown", proof
    assert "resolved_contact" not in proof


@pytest.mark.parametrize(
    "name",
    [
        "mutation_from_-x",
        "mutation_from_+y",
        "opposite_target",
        "fixture_side_mismatch",
        "wrong_axis_identity",
    ],
)
def test_known_approach_sign_or_selected_face_contradiction_is_error(native_pickups, name):
    proof = _proof(native_pickups, name)
    assert proof["status"] == "error", proof
    assert proof["errors"]


@pytest.mark.parametrize(
    "name",
    [
        "mutation_approach_mm_unknown",
        "mutation_retract_clearance_mm_unknown",
        "mutation_check_jog_mm_unknown",
    ],
)
def test_missing_requested_path_fact_is_unknown(native_pickups, name):
    proof = _proof(native_pickups, name)
    assert proof["status"] == "unknown", proof
    if name == "mutation_approach_mm_unknown":
        assert "path" not in proof
    else:
        assert proof["path"]["complete"] is False
        kinds = [leg["kind"] for leg in proof["path"]["legs"]]
        assert kinds == (
            ["approach"]
            if name == "mutation_retract_clearance_mm_unknown"
            else ["descend", "approach", "retract"]
        )


@pytest.mark.parametrize(
    "name",
    [
        "mutation_approach_mm_0.0",
        "mutation_retract_clearance_mm_-1.0",
        "mutation_edge_mm_13.0",
        "mutation_at_mm_[-5.08, -25.0]",
        "mutation_at_mm_[100.0, -2.54]",
        "short_projection",
        "short_tip_shank_hits_stock",
    ],
)
def test_known_bad_path_contact_or_stack_dimensions_are_errors(native_pickups, name):
    proof = _proof(native_pickups, name)
    assert proof["status"] == "error", proof
    assert proof["errors"]


def test_signed_check_jog_is_not_multiplied_by_contact_side(native_pickups):
    positive = _proof(native_pickups, "e1")
    negative = _proof(native_pickups, "signed_negative")
    assert positive["status"] == negative["status"] == "pass"
    assert positive["path"]["legs"][-1]["to_mm"] == pytest.approx([21.59, -5.08, 12.7])
    assert negative["path"]["legs"][-1]["to_mm"] == pytest.approx([8.89, -5.08, 12.7])


def test_exact_sweep_finds_mid_jog_obstacle_missed_by_both_endpoint_poses(native_pickups):
    proof = _proof(native_pickups, "mid_jog_hit")
    assert proof["status"] == "error", proof
    hits = [hit for hit in proof["collisions"] if hit["obstacle"] == "mid-jog-only"]
    assert hits and all(hit["kind"] == "check_jog" and hit["component"] == "shank" for hit in hits)
    # The entire obstacle lies outside both shank endpoint disks and the
    # descent standoff disk, but inside the straight run's exact stadium.
    radius = 9.525 / 2
    for centre_x in (15.24, 17.78, 21.59):
        dx = max(19.4 - centre_x, centre_x - 19.6, 0.0)
        assert dx * dx + 4.68 * 4.68 > radius * radius
    negative = _proof(native_pickups, "negative_avoids_mid_jog")
    assert negative["status"] == "pass", negative


def test_retract_clearance_is_used_for_the_checked_jog(native_pickups):
    clear = _proof(native_pickups, "high_clearance")
    blocked = _proof(native_pickups, "low_clearance")
    assert clear["status"] == "pass", clear
    assert blocked["status"] == "error", blocked
    assert blocked["path"]["retract_height_mm"] == pytest.approx(1.0)
    assert any(
        hit["obstacle"] == "low-check-bridge" and hit["kind"] == "check_jog"
        for hit in blocked["collisions"]
    )


def test_selected_holder_is_swept_not_only_tip_and_shank(native_pickups):
    proof = _proof(native_pickups, "holder_hit")
    assert proof["status"] == "error", proof
    assert any(
        hit["component"] == "holder" and hit["obstacle"] == "holder-only-post"
        for hit in proof["collisions"]
    )


def test_absent_requested_proof_preserves_ordinary_arithmetic_boundary(native_pickups):
    assert _proof(native_pickups, "no_request") == {}
    assert _proof(native_pickups, "z_not_transverse") == {}


def test_actual_selected_fixture_face_can_supply_contact_without_canonical_substitution(
    native_pickups,
):
    proof = _proof(native_pickups, "fixture_target")
    assert proof["status"] == "pass", proof
    assert proof["resolved_contact"]["surface"]["name"] == "datum-pad"
    assert proof["resolved_contact"]["plane_mm"] == pytest.approx(45.0)
    assert proof["path"]["contact_mm"] == pytest.approx([47.54, -5.08, -2.54])


def test_missing_stock_top_retains_known_fixture_approach_collision(native_pickups):
    proof = _proof(native_pickups, "fixture_target_no_stock_hit")
    assert proof["status"] == "error", proof
    assert proof["path"]["complete"] is False
    assert proof["path"]["stock_top_mm"] == "unknown"
    assert proof["path"]["start_mm"] == "unknown"
    assert [leg["kind"] for leg in proof["path"]["legs"]] == ["approach"]
    assert any(
        hit["obstacle"] == "fixture-path-blocker" and hit["kind"] == "approach"
        for hit in proof["collisions"]
    )


@pytest.mark.parametrize("name", ["missing_axis_identity", "missing_raw_side"])
def test_missing_native_request_identity_remains_unknown_not_a_known_error(native_pickups, name):
    proof = _proof(native_pickups, name)
    assert proof["status"] == "unknown", proof
    assert proof["errors"] == []
