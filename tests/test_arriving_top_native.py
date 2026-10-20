"""Real OCC arriving-top contact lands and occupied-stack vertical sweeps.

Run at the coordinated native barrier; no host/native verdicts are substituted.
The flat-end projection is the qualified contact model, not exact flute geometry.
"""

import hashlib
import json
import math
import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from prechips import kernel

_ENVELOPE = {
    "contact_kind": "flat_end",
    "nose_radius_mm": 0.0,
    "tip_dia_mm": 4.0,
    "tip_length_mm": 2.0,
    "shank_dia_mm": 6.0,
    "projection_mm": 8.0,
    "holder_dia_mm": 10.0,
    "holder_gauge_len_mm": 4.0,
}


def _request():
    return {
        "model": "arriving_top_v1",
        "axis": "z",
        "from": "+z",
        "scene_id": "arriving-batch-scene",
        "tool": "qualified-flat-end-4",
        "holder": "collet-6",
        "tool_kind": "endmill",
        "method": "paper",
        "surface": {"kind": "stock", "face": "stock:+z", "side": "+z"},
        "at_mm": [0.0, 0.0],
        "edge_mm": 10.0,
        "paper_mm": 0.1,
        "contact_land_mm": 0.5,
        "retract_clearance_mm": 5.0,
        "check_jog_mm": 3.0,
        "tool_envelope": deepcopy(_ENVELOPE),
        "reasons": [],
        "errors": [],
    }


def _case(**geometry):
    return {"request": _request(), **geometry}


_PROBE = r"""
import importlib.util
import json
import os
import sys
from copy import deepcopy
import FreeCAD as App
import Part

out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("top_pickup_job", os.environ["PICKUP_KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
import zero_pickup
V = App.Vector
with open(os.path.join(out, "cases.json"), encoding="utf-8") as handle:
    cases = json.load(handle)


def box(at, size):
    return Part.makeBox(*size, V(*at))


results = {}
for name, case in cases.items():
    pieces = [box(*item) for item in case.get("stock_boxes", [[[-10, -10, 0], [20, 20, 10]]])]
    if case.get("compound_stock"):
        stock = Part.makeCompound(pieces)
    else:
        stock = pieces[0]
        for piece in pieces[1:]:
            stock = stock.fuse(piece)
        stock = stock.removeSplitter()
    if case.get("hole"):
        stock = stock.cut(Part.makeCylinder(0.15, 12, V(0, 0, -1))).removeSplitter()
    fixtures = [{"name": item["name"], "solid": box(item["at"], item["size"])}
                for item in case.get("obstacles", [])]
    if case.get("missing_fixture"):
        fixtures.append({"name": "unresolved-clamp", "solid": None})
    request = deepcopy(case["request"])
    result_key = case.get("result_key", "z")
    setup = {"id": "BATCH-TOP", "zero_pickups": {result_key: request},
             "zero_pickup_reasons": case.get("scene_reasons", [])}
    helpers = {"bbox": job._bbox, "sweep": job._FiniteSaw._sweep,
               "model_faces": {}, "plane_tol": job.PLANE_TOL,
               "hit_mm3": job.HIT_MM3, "area_tol": job.AREA_ABS,
               "arrival": deepcopy(case.get("arrival", {
                   "route": "released-member" if case.get("released") else "batch"}))}
    proof = zero_pickup.prove_pickups(App, Part, setup,
                                     None if case.get("no_stock") else stock,
                                     fixtures, helpers=helpers)[result_key]
    diagnostics = {"stock_bbox_mm": list(job._bbox(stock)), "stock_face_count": len(stock.Faces)}
    if case.get("endpoint_audit"):
        # Independent exact endpoint solids: a fixture between these poses must
        # be detected by the continuous sweep, not either endpoint test.
        obstacle = fixtures[0]["solid"]
        start_z = max(stock.BoundBox.ZMax, obstacle.BoundBox.ZMax) + request["retract_clearance_mm"]
        occupied = []
        for z in (request["edge_mm"] + request["paper_mm"], start_z):
            parts = [Part.makeCylinder(2, 2, V(0, 0, z)),
                     Part.makeCylinder(3, 6, V(0, 0, z + 2)),
                     Part.makeCylinder(5, 4, V(0, 0, z + 8))]
            occupied.append(sum(part.common(obstacle).Volume for part in parts))
        diagnostics["endpoint_hit_mm3"] = occupied
        diagnostics["fixture_volume_mm3"] = obstacle.Volume
    results[name] = {"proof": proof, "geometry": diagnostics}

# Exercise the production setup gate, not an invented passing native verdict.
from types import SimpleNamespace


def runner_for(request, ops, ledger=None):
    runner = job._Setup.__new__(job._Setup)
    runner.owner = SimpleNamespace(mapping={}, workpieces={})
    runner.state = {"components": {"blank"}, "finished_names": {"member-1"},
                    "partitions": {"blank": {()}}}
    runner.setup = {
        "id": "BATCH-TOP", "stock_in": "arriving-batch", "frame": "stock-frame",
        "zero_pickups": {"tool_touch:0": deepcopy(request)}, "ops": ops,
        "preservation_ledger": ledger if ledger is not None else [
            {"subject": op["subject"], "do": op["do"], "effect": "native"} for op in ops],
    }
    runner.ops = ops
    runner.part = box([-10, -10, 0], [20, 20, 10])
    runner.lower_part = runner.part
    runner.matrix = App.Matrix()
    runner.faces = list(runner.part.Faces)
    runner.stock_reason = None
    runner.fixture_debts = []
    runner.fixture_gaps = []
    runner.undrawn = []
    runner.capture_debts = []
    runner.arriving_thread_regions = []
    runner.fixture_ready = True
    runner.fixture_reason = None
    runner.fixture_possible = []
    runner.fixture_errors = []
    runner.fixture = []
    runner.capture_fixture = []
    runner.zero_pickup_facts = {}
    runner.zero_pickup_debts = {}
    runner.cuts = {}
    runner.lower_cuts = {}
    runner.thread_regions = []
    runner._thread_material_ops = {}
    runner.stopped_cut = None
    runner.protection_reason = None
    runner.checkpoint_jobs = []
    return runner


def dependent(number="20"):
    return {"subject": "BATCH-TOP:" + number, "do": "mill", "approach": "+z",
            "zero_pickup_key": "tool_touch:0", "tool": "qualified-flat-end-4",
            "holder": "collet-6", "radius_mm": 2,
            "checkpoints": {"bounded": False, "rows": [{"id": "cut-contact", "at_mm": [0, 0, 5]}]}}


initial = runner_for(cases["batch"]["request"], [dependent()])
initial.zero_pickup_facts = initial._zero_pickups()
integration = {
    "initial_proof": initial.zero_pickup_facts["tool_touch:0"],
    "initial_gate": initial._prove_op_pickup(initial.ops[0], initial.part),
}
for mutation in ("missing_proof", "missing_request", "stale_request", "tool", "holder", "future"):
    runner = runner_for(cases["batch"]["request"], [dependent()])
    runner.zero_pickup_facts = runner._zero_pickups()
    if mutation == "missing_proof":
        runner.zero_pickup_facts.clear()
    elif mutation == "missing_request":
        runner.setup["zero_pickups"].clear()
    elif mutation == "stale_request":
        runner.setup["zero_pickups"]["tool_touch:0"]["at_mm"] = [0.1, 0]
    elif mutation in ("tool", "holder"):
        runner.ops[0][mutation] = "different-" + mutation
    else:
        runner.setup["zero_pickups"]["tool_touch:0"].update(
            {"position": 1, "after_op": "10", "before_ops": ["20"]})
    integration[mutation] = runner._prove_op_pickup(runner.ops[0], runner.part)

rough = {"subject": "BATCH-TOP:10", "do": "mill"}
for mutation in ("match", "missing_position", "missing_snapshot", "unmodeled_bench"):
    request = deepcopy(cases["stage_match"]["request"])
    runner = runner_for(request, [deepcopy(rough), dependent()])
    # This is an exact native stock-removal boolean, not a substituted verdict.
    after = runner.part.cut(box([-10, -10, 6], [20, 20, 4])).removeSplitter()
    runner.cuts[id(runner.ops[0])] = (runner.part, after, None)
    if mutation == "missing_position":
        runner.setup["zero_pickups"]["tool_touch:0"].pop("position")
    elif mutation == "missing_snapshot":
        runner.cuts.clear()
    elif mutation == "unmodeled_bench":
        runner.setup["preservation_ledger"].insert(
            1, {"subject": "BATCH-TOP:15", "do": "file", "effect": "unmodeled"})
        runner.setup["zero_pickups"]["tool_touch:0"].update(
            {"position": 2, "after_op": "15", "before_ops": ["20"]})
    reason = runner._prove_op_pickup(runner.ops[1], after)
    integration["stage_" + mutation] = {
        "reason": reason, "proof": runner.zero_pickup_facts.get("tool_touch:0"),
        "before_volume_mm3": runner.part.Volume, "after_volume_mm3": after.Volume,
    }

# With no native witness the real builder must stop before material removal.
# Its own (None,None,reason) snapshots distinguish the pre-cut guard branch
# from the finally block that records a reached cut, even if that cut fails.
blocked = runner_for(cases["batch"]["request"], [dependent(), dependent("30")])
built, why = blocked._build()
op_facts = blocked._op(blocked.ops[0])
blocked._checkpoint_facts(blocked.ops[0], op_facts)
later_facts = blocked._op(blocked.ops[1])
blocked._checkpoint_facts(blocked.ops[1], later_facts)
integration["blocked_build"] = {
    "stock_out_is_none": built is None, "reason": why,
    "cuts": [{"before_is_none": blocked.cuts[id(op)][0] is None,
              "after_is_none": blocked.cuts[id(op)][1] is None,
              "reason": blocked.cuts[id(op)][2]} for op in blocked.ops],
    "stock_state_volumes_mm3": [shape.Volume for shape in blocked.stock_states],
    "stopped_cut": blocked.stopped_cut,
    "op_facts": op_facts,
    "later_facts": later_facts,
    "checkpoint_jobs": blocked.checkpoint_jobs,
}
results["setup_integration"] = integration


def rectangle(x0, y0, x1, y1):
    corners = [V(x0, y0, 10), V(x1, y0, 10), V(x1, y1, 10), V(x0, y1, 10)]
    return Part.Face(Part.makePolygon([*corners, corners[0]]))


# Keep the fragments as native compounds: fusing/removeSplitter here could
# erase the exact multi-face input that exposed the connectivity regression.
fragments = {
    "shared_edge": [rectangle(-1, -1, 0, 1), rectangle(0, -1, 1, 1)],
    "overlap": [rectangle(-1, -1, 0.25, 1), rectangle(-0.25, -1, 1, 1)],
    "disconnected": [rectangle(-1, -1, -0.1, 1), rectangle(0.1, -1, 1, 1)],
    "point_only": [rectangle(-1, -1, 0, 0), rectangle(0, 0, 1, 1)],
    "edge_chain": [
        rectangle(-0.45, -1, -0.15, 1),
        rectangle(-0.15, -1, 0.15, 1),
        rectangle(0.15, -1, 0.45, 1),
    ],
    "incidental_island": [rectangle(-0.5, -0.5, 0.5, 0.5), rectangle(1, -0.5, 1.5, 0.5)],
}
connectivity = {}
for name, faces in fragments.items():
    contact = Part.makeCompound(faces)
    pairs = []
    for i, first in enumerate(contact.Faces):
        for j, second in enumerate(contact.Faces):
            if j <= i:
                continue
            common = first.common(second)
            section = first.section(second)
            pairs.append({"pair": [i, j], "area_mm2": common.Area,
                          "length_mm": section.Length, "vertices": len(section.Vertexes)})
    land = rectangle(-0.25, -0.25, 0.25, 0.25)
    selected = zero_pickup._contact_land_patch(
        contact, land, area_tol=job.AREA_ABS, length_tol=job.PLANE_TOL)
    connectivity[name] = {
        "face_count": len(contact.Faces), "area_mm2": contact.Area,
        "pairs": pairs, "land_area_mm2": land.Area,
        "land_bbox_mm": list(job._bbox(land)),
        "selected": selected is not None,
        "patch_area_mm2": None if selected is None else selected.Area,
        "patch_bbox_mm": None if selected is None else list(job._bbox(selected)),
        "missing_land_area_mm2": None if selected is None else land.cut(selected).Area,
        "fragment_land_missing_mm2": [land.cut(face).Area for face in contact.Faces],
        "total_missing_land_mm2": land.cut(contact).Area,
    }
results["contact_connectivity"] = connectivity
with open(os.path.join(out, "pickups.json"), "w", encoding="utf-8") as handle:
    json.dump(results, handle)
"""


@pytest.fixture(scope="module")
def native_tops(tmp_path_factory, freecad_kernel):
    cases = {
        "batch": _case(),
        "fragmented_stock": _case(
            stock_boxes=[[[-4, -4, 0], [4, 8, 10]], [[0, -4, 0], [4, 8, 10]]],
            compound_stock=True,
        ),
        "incidental_stock_island": _case(
            stock_boxes=[
                [[-0.5, -0.5, 0], [1, 1, 10]],
                [[1.2, -0.2, 0], [0.4, 0.4, 10]],
            ],
            compound_stock=True,
        ),
        "released_strip": _case(stock_boxes=[[[-0.4, -8, 0], [0.8, 16, 10]]], released=True),
        "tangent": _case(stock_boxes=[[[2, -5, 0], [3, 10, 10]]]),
        "sliver": _case(stock_boxes=[[[-0.1, -5, 0], [0.2, 10, 10]]]),
        "disconnected": _case(
            stock_boxes=[
                [[-1.8, -1, 0], [1.7, 2, 10]],
                [[0.1, -1, 0], [1.7, 2, 10]],
            ]
        ),
        "hole": _case(hole=True),
        "no_stock": _case(no_stock=True),
        "missing_fixture": _case(missing_fixture=True),
        "scene_debt": _case(scene_reasons=["arriving clamp placement unresolved"]),
        "side_intrusion": _case(
            stock_boxes=[
                [[-10, -10, 0], [20, 20, 10]],
                [[1.5, -0.2, 10], [0.4, 0.4, 4]],
            ]
        ),
        "safe_overhang": _case(
            stock_boxes=[[[-0.4, -8, 0], [0.8, 16, 10]]],
            released=True,
            obstacles=[{"name": "low-side-clamp", "at": [2.2, -0.2, 10], "size": [0.4, 0.4, 1]}],
        ),
    }
    for name, key, value in (
        ("wrong_xy", "at_mm", [30, 30]),
        ("wrong_plane", "edge_mm", 11),
        ("bottom_normal", "edge_mm", 0),
        ("wrong_direction", "from", "-z"),
        ("wrong_axis", "axis", "x"),
        ("wrong_tool", "tool_kind", "ballmill"),
        ("wrong_method", "method", "edge_then_set"),
        ("negative_paper", "paper_mm", -0.1),
        ("zero_land", "contact_land_mm", 0),
        ("oversize_land", "contact_land_mm", 4),
        ("negative_jog", "check_jog_mm", -7),
    ):
        cases[name] = _case()
        cases[name]["request"][key] = value
    for key in (
        "at_mm",
        "edge_mm",
        "paper_mm",
        "contact_land_mm",
        "scene_id",
        "tool",
        "holder",
        "retract_clearance_mm",
        "check_jog_mm",
    ):
        cases["missing_" + key] = _case()
        cases["missing_" + key]["request"].pop(key)
    for key in _ENVELOPE:
        cases["missing_" + key] = _case()
        cases["missing_" + key]["request"]["tool_envelope"].pop(key)
    cases["wrong_nose"] = _case()
    cases["wrong_nose"]["request"]["tool_envelope"]["nose_radius_mm"] = 0.2
    cases["wrong_surface_normal"] = _case()
    cases["wrong_surface_normal"]["request"]["surface"]["side"] = "-z"
    for name, at, size in (
        ("mid_sweep", [0, -0.2, 30], [0.4, 0.4, 0.4]),
        ("shank_hit", [2.5, -0.2, 14], [0.4, 0.4, 0.4]),
        ("holder_hit", [4, -0.2, 20], [0.4, 0.4, 0.4]),
    ):
        cases[name] = _case(obstacles=[{"name": name, "at": at, "size": size}])
    cases["mid_sweep"]["endpoint_audit"] = True
    cases["partial_and_hit"] = deepcopy(cases["mid_sweep"])
    cases["partial_and_hit"]["request"]["tool_envelope"].pop("holder_gauge_len_mm")
    stage = _case(stock_boxes=[[[-10, -10, 0], [20, 20, 6]]])
    stage["result_key"] = "tool_touch:0"
    stage["arrival"] = {
        "position": 1,
        "after_op": "10",
        "before_op": "20",
        "stock_in": "after-rough",
        "frame": "rough-frame",
        "components": ["blank"],
        "workpiece_ids": ["member-1"],
        "partition_path": ["release"],
    }
    stage["request"].update(
        {
            "position": 1,
            "after_op": "10",
            "before_ops": ["20"],
            "edge_mm": 6.0,
            "scene_id": "after-rough-scene",
        }
    )
    cases["stage_match"] = stage
    for key, wrong in (("position", 0), ("after_op", "09"), ("before_ops", ["30"])):
        cases["stage_wrong_" + key] = deepcopy(stage)
        cases["stage_wrong_" + key]["request"][key] = wrong
        cases["stage_missing_" + key] = deepcopy(stage)
        cases["stage_missing_" + key]["request"].pop(key)
    cases["stage_initial_witness"] = deepcopy(stage)
    cases["stage_initial_witness"]["request"] = _request()
    # Keep geometry/plane valid so stage identity, not stale Z, denies reuse.
    cases["stage_initial_witness"]["request"]["edge_mm"] = 6.0
    cases["stage_old_plane"] = deepcopy(stage)
    cases["stage_old_plane"]["request"]["edge_mm"] = 10.0
    for case in cases.values():
        request = case["request"]
        request["recipe_id"] = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    directory = tmp_path_factory.mktemp("native-arriving-top")
    script = directory / "prove_arriving_top.py"
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


def _proof(native_tops, name):
    return native_tops[0][name]["proof"]


def test_broad_batch_top_has_exact_pose_plane_normal_paper_and_native_echo(native_tops):
    proof = _proof(native_tops, "batch")
    assert proof["status"] == "pass", proof
    assert proof["model"] == "arriving_top_v1"
    assert proof["axis"] == "z"
    assert proof["setup_id"] == "BATCH-TOP"
    assert proof["request"] == native_tops[1]["batch"]["request"]
    assert proof["recipe_id"] == native_tops[1]["batch"]["request"]["recipe_id"]
    assert proof["arrival"] == {"route": "batch"}
    assert proof["physical_upper_bound_mm"] == pytest.approx(10)
    contact = proof["resolved_contact"]
    assert contact["surface"] == {"kind": "stock", "face": "stock:+z", "side": "+z"}
    assert contact["contact_model"] == "flat_end_projection_v1"
    assert contact["plane_mm"] == pytest.approx(10)
    assert contact["normal"] == [0, 0, 1]
    assert contact["point_mm"] == pytest.approx([0, 0, 10])
    assert contact["axis_mm"] == pytest.approx([0, 0, 10.1])
    assert contact["land_mm"] == pytest.approx(0.5)
    assert contact["land_bbox_mm"] == pytest.approx([-0.25, -0.25, 10, 0.25, 0.25, 10])
    assert contact["land_area_mm2"] == pytest.approx(0.25)
    assert contact["missing_land_area_mm2"] == pytest.approx(0, abs=1e-8)
    assert contact["footprint_radius_mm"] == pytest.approx(2)
    assert contact["contact_area_mm2"] == pytest.approx(4 * math.pi)
    assert contact["uncovered_area_mm2"] == pytest.approx(0, abs=1e-8)
    assert contact["patch_bbox_mm"] == pytest.approx([-2, -2, 10, 2, 2, 10])
    assert contact["patch_face_indices"]
    path = proof["path"]
    assert path["complete"] is True
    assert path["start_mm"] == pytest.approx([0, 0, 15])
    assert path["contact_mm"] == pytest.approx([0, 0, 10.1])
    assert path["retract_height_mm"] == pytest.approx(15)
    assert path["jog_mm"] == pytest.approx(3)
    legs = path["legs"]
    assert [leg["kind"] for leg in legs] == ["descend", "check_jog", "retract"]
    for leg, first, last in zip(
        legs,
        ([0, 0, 15], [0, 0, 10.1], [0, 0, 13.1]),
        ([0, 0, 10.1], [0, 0, 13.1], [0, 0, 15]),
        strict=True,
    ):
        assert leg["from_mm"] == pytest.approx(first)
        assert leg["to_mm"] == pytest.approx(last)
        assert {part["id"] for part in leg["components"]} == {"tip", "shank", "holder"}
        assert all(part["swept_volume_mm3"] > 0 for part in leg["components"])
    assert proof["collisions"] == []


@pytest.mark.parametrize("name", ["released_strip", "safe_overhang"])
def test_finite_land_passes_on_released_strip_without_full_disk_support(native_tops, name):
    proof = _proof(native_tops, name)
    assert proof["status"] == "pass", proof
    assert proof["arrival"] == {"route": "released-member"}
    contact = proof["resolved_contact"]
    assert contact["contact_area_mm2"] > 0.25
    assert contact["uncovered_area_mm2"] > 1
    assert contact["footprint_area_mm2"] == pytest.approx(4 * math.pi)
    assert contact["missing_land_area_mm2"] == pytest.approx(0, abs=1e-8)
    assert contact["land_bbox_mm"] == pytest.approx([-0.25, -0.25, 10, 0.25, 0.25, 10])
    assert contact["patch_bbox_mm"] == pytest.approx([-0.4, -2, 10, 0.4, 2, 10])
    assert proof["collisions"] == []


@pytest.mark.parametrize(
    "name,status,message",
    [
        ("tangent", "error", "no positive-area"),
        ("sliver", "unknown", "contact land"),
        ("disconnected", "unknown", "contact land"),
        ("hole", "unknown", "contact land"),
        ("wrong_xy", "error", "no positive-area"),
        ("wrong_plane", "error", "no actual +Z planar"),
        ("bottom_normal", "error", "no actual +Z planar"),
        ("wrong_surface_normal", "unknown", "explicit actual-stock +Z"),
    ],
)
def test_actual_contact_not_bbox_or_positive_area_alone(native_tops, name, status, message):
    proof = _proof(native_tops, name)
    assert proof["status"] == status, proof
    assert any(message in item for item in proof["errors"] + proof["reasons"]), proof
    assert "resolved_contact" not in proof
    assert "path" not in proof
    assert proof["physical_upper_bound_mm"] == pytest.approx(10)
    if name == "hole":
        assert proof["stock_bbox_mm"] == pytest.approx([-10, -10, 0, 10, 10, 10])


@pytest.mark.parametrize(
    "name,message",
    [
        ("no_stock", "stock is unresolved"),
        ("missing_fixture", "fixture solid is unresolved"),
        ("scene_debt", "clamp placement unresolved"),
        ("wrong_tool", "qualified flat-end mill"),
        ("wrong_method", "explicit paper touch"),
        *[
            ("missing_" + key, message)
            for key, message in (
                ("at_mm", "coordinates are unknown"),
                ("edge_mm", "plane is unknown"),
                ("paper_mm", "paper thickness is unknown"),
                ("contact_land_mm", "contact land is unknown"),
                ("scene_id", "scene_id identity is unknown"),
                ("tool", "tool identity is unknown"),
                ("holder", "holder identity is unknown"),
                ("retract_clearance_mm", "retract_clearance_mm is unknown"),
                ("check_jog_mm", "check jog is unknown"),
                ("contact_kind", "qualification is unknown"),
                ("nose_radius_mm", "nose radius is unknown"),
                *[
                    (key, key + " is unknown")
                    for key in _ENVELOPE
                    if key not in ("contact_kind", "nose_radius_mm")
                ],
            )
        ],
    ],
)
def test_missing_scene_pose_qualification_and_path_stay_debt(native_tops, name, message):
    proof = _proof(native_tops, name)
    assert proof["status"] == "unknown", proof
    assert any(message in item for item in proof["reasons"]), proof
    assert proof["errors"] == []
    if name != "no_stock":
        assert proof["physical_upper_bound_mm"] == pytest.approx(10)
    else:
        assert "physical_upper_bound_mm" not in proof
    if name in (
        "missing_at_mm",
        "missing_paper_mm",
        "missing_edge_mm",
        "missing_contact_land_mm",
        "missing_retract_clearance_mm",
        "missing_check_jog_mm",
        "no_stock",
    ):
        assert "path" not in proof


@pytest.mark.parametrize(
    "name,message",
    [
        ("wrong_nose", "zero nose radius"),
        ("wrong_direction", "setup Z from +Z"),
        ("wrong_axis", "setup Z from +Z"),
        ("negative_paper", "cannot be negative"),
        ("zero_land", "land must be positive"),
        ("oversize_land", "cannot cover the finite contact land"),
    ],
)
def test_invalid_qualification_pose_or_land_is_not_a_pass(native_tops, name, message):
    proof = _proof(native_tops, name)
    assert proof["status"] == "error", proof
    assert any(message in item for item in proof["errors"]), proof


@pytest.mark.parametrize(
    "name,component,obstacle,kind",
    [
        ("mid_sweep", "tip", "mid_sweep", "descend"),
        ("shank_hit", "shank", "shank_hit", "descend"),
        ("holder_hit", "holder", "holder_hit", "descend"),
        ("negative_jog", "tip", "stock", "check_jog"),
        ("side_intrusion", "tip", "stock", "descend"),
        ("partial_and_hit", "tip", "mid_sweep", "descend"),
    ],
)
def test_full_occupied_stack_and_signed_jog_collisions(
    native_tops, name, component, obstacle, kind
):
    proof = _proof(native_tops, name)
    assert proof["status"] == "error", proof
    assert proof["resolved_contact"]["land_area_mm2"] == pytest.approx(0.25)
    hits = [
        hit
        for hit in proof["collisions"]
        if hit["component"] == component and hit["obstacle"] == obstacle and hit["kind"] == kind
    ]
    assert hits, proof
    assert all(hit["volume_mm3"] > 0 for hit in hits)
    if name in ("shank_hit", "holder_hit"):
        assert not any(hit["component"] == "tip" for hit in proof["collisions"])
    if name == "negative_jog":
        assert proof["path"]["legs"][1]["to_mm"] == pytest.approx([0, 0, 3.1])
        assert not any(hit["kind"] == "descend" for hit in proof["collisions"])
    if name == "mid_sweep":
        geometry = native_tops[0][name]["geometry"]
        assert geometry["fixture_volume_mm3"] > 0
        assert geometry["endpoint_hit_mm3"] == pytest.approx([0, 0], abs=1e-8)
    if name == "partial_and_hit":
        assert any("holder_gauge_len_mm is unknown" in reason for reason in proof["reasons"])


def test_stage_bound_top_uses_after_rough_stock_and_arbitrary_touch_key(native_tops):
    proof = _proof(native_tops, "stage_match")
    assert proof["status"] == "pass", proof
    assert proof["axis"] == "z"
    assert proof["request"] == native_tops[1]["stage_match"]["request"]
    assert proof["arrival"] == {
        "position": 1,
        "after_op": "10",
        "before_op": "20",
        "stock_in": "after-rough",
        "frame": "rough-frame",
        "components": ["blank"],
        "workpiece_ids": ["member-1"],
        "partition_path": ["release"],
    }
    assert proof["physical_upper_bound_mm"] == pytest.approx(6)
    assert proof["resolved_contact"]["point_mm"] == pytest.approx([0, 0, 6])
    assert proof["resolved_contact"]["axis_mm"] == pytest.approx([0, 0, 6.1])
    assert proof["path"]["start_mm"] == pytest.approx([0, 0, 11])
    assert proof["collisions"] == []


@pytest.mark.parametrize(
    "name",
    [
        "stage_wrong_position",
        "stage_missing_position",
        "stage_wrong_after_op",
        "stage_missing_after_op",
        "stage_wrong_before_ops",
        "stage_missing_before_ops",
        "stage_initial_witness",
    ],
)
def test_stage_boundary_cannot_reuse_initial_or_mismatched_witness(native_tops, name):
    proof = _proof(native_tops, name)
    assert proof["status"] == "unknown", proof
    assert proof["reasons"], proof
    assert proof["errors"] == []
    assert proof["physical_upper_bound_mm"] == pytest.approx(6)
    assert proof["arrival"]["position"] == 1
    assert proof["request"] == native_tops[1][name]["request"]


def test_matching_stage_identity_does_not_reuse_pre_rough_contact_plane(native_tops):
    proof = _proof(native_tops, "stage_old_plane")
    assert proof["status"] == "error", proof
    assert any("no actual +Z planar" in error for error in proof["errors"]), proof
    assert proof["physical_upper_bound_mm"] == pytest.approx(6)
    assert "resolved_contact" not in proof


def test_real_setup_gate_consumes_its_own_initial_native_witness(native_tops):
    integration = native_tops[0]["setup_integration"]
    assert integration["initial_proof"]["status"] == "pass", integration
    assert integration["initial_proof"]["resolved_contact"]["plane_mm"] == pytest.approx(10)
    assert integration["initial_gate"] is None


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("missing_proof", "lacks a passing"),
        ("missing_request", "no matching"),
        ("stale_request", "lacks a passing"),
        ("tool", "tool-holder pair"),
        ("holder", "tool-holder pair"),
        ("future", "future operation boundary"),
    ],
)
def test_setup_gate_rejects_absent_stale_or_wrong_tool_witness(native_tops, mutation, message):
    reason = native_tops[0]["setup_integration"][mutation]
    assert isinstance(reason, str)
    assert message in reason


def test_setup_gate_proves_exact_current_stock_after_native_removal(native_tops):
    stage = native_tops[0]["setup_integration"]["stage_match"]
    assert stage["before_volume_mm3"] == pytest.approx(4000)
    assert stage["after_volume_mm3"] == pytest.approx(2400)
    assert stage["reason"] is None, stage
    proof = stage["proof"]
    assert proof["status"] == "pass", proof
    assert proof["resolved_contact"]["plane_mm"] == pytest.approx(6)
    assert proof["physical_upper_bound_mm"] == pytest.approx(6)
    assert proof["arrival"]["position"] == 1
    assert proof["arrival"]["after_op"] == "10"
    assert proof["arrival"]["before_op"] == "20"
    assert proof["request"]["position"] == 1


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("missing_position", "lacks a passing"),
        ("missing_snapshot", "stock at its top touch is unresolved"),
        ("unmodeled_bench", "unmodeled preceding bench step"),
    ],
)
def test_setup_stage_gate_requires_modeled_prior_stock_and_explicit_boundary(
    native_tops, mutation, message
):
    stage = native_tops[0]["setup_integration"]["stage_" + mutation]
    assert stage["after_volume_mm3"] == pytest.approx(2400)
    assert message in stage["reason"], stage
    assert stage["proof"] is None


def test_failed_native_dependency_stops_build_and_guards_later_facts(native_tops):
    blocked = native_tops[0]["setup_integration"]["blocked_build"]
    assert blocked["stock_out_is_none"] is True
    assert "lacks a passing" in blocked["reason"]
    assert len(blocked["cuts"]) == 2
    for snapshot in blocked["cuts"]:
        assert snapshot["before_is_none"] is True
        assert snapshot["after_is_none"] is True
        assert "lacks a passing" in snapshot["reason"]
    assert blocked["stock_state_volumes_mm3"] == pytest.approx([4000])
    assert blocked["stopped_cut"] is None
    assert blocked["op_facts"]["claimed_indices"] == "unknown"
    assert "lacks a passing" in blocked["op_facts"]["reason"]
    assert blocked["later_facts"]["claimed_indices"] == "unknown"
    assert "lacks a passing" in blocked["later_facts"]["reason"]
    assert len(blocked["checkpoint_jobs"]) == 2
    for checkpoint in blocked["checkpoint_jobs"]:
        assert checkpoint["rows"]
        assert any("lacks a passing" in reason for reason in checkpoint["why"])
        assert checkpoint["removed"] == []
        assert checkpoint["errors"] == []


@pytest.mark.parametrize(
    "name,connected,area,length,vertices",
    [
        ("shared_edge", True, 0, 2, 2),
        ("overlap", True, 1, 5, 4),
        ("disconnected", False, 0, 0, 0),
        ("point_only", False, 0, 0, 1),
        ("incidental_island", True, 0, 0, 0),
    ],
)
def test_real_fragment_land_selection_uses_actual_area_or_shared_boundary(
    native_tops, name, connected, area, length, vertices
):
    contact = native_tops[0]["contact_connectivity"][name]
    assert contact["face_count"] == 2
    assert contact["area_mm2"] > 0
    assert len(contact["pairs"]) == 1
    adjacency = contact["pairs"][0]
    assert adjacency["pair"] == [0, 1]
    assert adjacency["area_mm2"] == pytest.approx(area, abs=1e-8)
    assert adjacency["length_mm"] == pytest.approx(length, abs=1e-8)
    assert adjacency["vertices"] == vertices
    assert contact["land_area_mm2"] == pytest.approx(0.25)
    assert contact["selected"] is connected
    if connected:
        assert contact["missing_land_area_mm2"] == pytest.approx(0, abs=1e-8)
    else:
        assert contact["patch_area_mm2"] is None
    if name == "overlap":
        # The selected union counts its shared area once, unlike the compound.
        assert contact["area_mm2"] == pytest.approx(5)
        assert contact["patch_area_mm2"] == pytest.approx(4)
    if name == "disconnected":
        assert contact["total_missing_land_mm2"] == pytest.approx(0.1)
        assert all(0 < missing < 0.25 for missing in contact["fragment_land_missing_mm2"])
    if name == "incidental_island":
        assert contact["area_mm2"] == pytest.approx(1.5)
        assert contact["patch_area_mm2"] == pytest.approx(1)
        assert contact["patch_bbox_mm"] == pytest.approx([-0.5, -0.5, 10, 0.5, 0.5, 10])


def test_real_fragment_connectivity_is_transitive_not_all_pairs_adjacent(native_tops):
    contact = native_tops[0]["contact_connectivity"]["edge_chain"]
    assert contact["face_count"] == 3
    assert contact["selected"] is True
    assert contact["land_bbox_mm"] == pytest.approx([-0.25, -0.25, 10, 0.25, 0.25, 10])
    assert all(missing > 0 for missing in contact["fragment_land_missing_mm2"])
    assert contact["missing_land_area_mm2"] == pytest.approx(0, abs=1e-8)
    assert contact["patch_bbox_mm"] == pytest.approx([-0.45, -1, 10, 0.45, 1, 10])
    assert contact["patch_area_mm2"] == pytest.approx(1.8)
    pairs = {tuple(pair["pair"]): pair for pair in contact["pairs"]}
    assert pairs[0, 1]["length_mm"] == pytest.approx(2)
    assert pairs[1, 2]["length_mm"] == pytest.approx(2)
    assert pairs[0, 2]["length_mm"] == pytest.approx(0, abs=1e-8)
    assert pairs[0, 2]["area_mm2"] == pytest.approx(0, abs=1e-8)
    assert pairs[0, 2]["vertices"] == 0


def test_full_native_top_proof_accepts_land_spanning_fragmented_stock_seam(native_tops):
    result = native_tops[0]["fragmented_stock"]
    assert result["geometry"]["stock_face_count"] == 12
    proof = result["proof"]
    assert proof["status"] == "pass", proof
    contact = proof["resolved_contact"]
    assert len(contact["patch_face_indices"]) == 2
    assert contact["land_bbox_mm"] == pytest.approx([-0.25, -0.25, 10, 0.25, 0.25, 10])
    assert contact["missing_land_area_mm2"] == pytest.approx(0, abs=1e-8)
    assert contact["contact_area_mm2"] == pytest.approx(4 * math.pi)
    assert proof["path"]["complete"] is True
    assert proof["collisions"] == []


def test_native_land_ignores_disconnected_incidental_disk_contact_island(native_tops):
    result = native_tops[0]["incidental_stock_island"]
    assert result["geometry"]["stock_face_count"] == 12
    proof = result["proof"]
    assert proof["status"] == "pass", proof
    contact = proof["resolved_contact"]
    assert contact["contact_area_mm2"] == pytest.approx(1.16)
    assert contact["uncovered_area_mm2"] == pytest.approx(4 * math.pi - 1.16)
    assert contact["patch_area_mm2"] == pytest.approx(1)
    assert contact["patch_bbox_mm"] == pytest.approx([-0.5, -0.5, 10, 0.5, 0.5, 10])
    assert len(contact["patch_face_indices"]) == 1
    assert contact["land_area_mm2"] == pytest.approx(0.25)
    assert contact["missing_land_area_mm2"] == pytest.approx(0, abs=1e-8)
    assert proof["path"]["complete"] is True
    assert proof["collisions"] == []
