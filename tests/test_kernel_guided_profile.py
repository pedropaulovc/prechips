"""Exact explicit-guided cutter sweeps, measured at the native OCC boundary.

The frozen STEP and the rectangular strip/capsule oracles are independent of the
engine's corridor, lineage band, offset and registration implementations.  This
probe imports the current source only when FreeCAD runs it; collection needs no
FreeCAD Python bindings.  No CLI planning or complete manufacturing build runs.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from prechips import kernel

STEP = Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/t-nut.STEP"
SHA256 = "456cdbe656f84b5b3236b8878c820f1e64a21944a61bdc6165fd39fe2fe5336e"

_PROBE = r"""
import copy, hashlib, importlib.util, json, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out, step = sys.argv[sys.argv.index("--") + 1:]
spec = importlib.util.spec_from_file_location("kernel_under_test", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

# Capture a normally initialized native scene, without manufacturing operations.
# All operations below still use the actual native claims/guards/removal methods.
runners = []
NativeSetup = job._Setup
class CaptureSetup(NativeSetup):
    def run(self):
        result = super().run()
        runners.append(self)
        return result
job._Setup = CaptureSetup
IDENTITY = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
WALLS = ["#192/ADVANCED_FACE[6]/", "#265/ADVANCED_FACE[8]/"]
ORIGINS = [100.33, 71.12, 41.91, 13.335]
live_ops = []  # Native caches key by id(op); retain independent probe inputs.

def initialize(path, stock, frame, members=None):
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    payload = {
        "version": 1, "step_path": path, "step_sha256": digest,
        "features": {}, "as_is_faces": [], "stock": stock,
        "setups": [{"id": "S1", "stock_in": "stock", "frame": frame, "ops": []}],
    }
    if members is not None:
        payload["workpieces"] = members
    result = job.run(payload)
    assert result["status"] == "ok", result
    runner = runners[-1]
    assert runner.part is not None and runner.protection_reason is None
    return runner

def scene(rotated=False):
    members = {}
    for i, x in enumerate(ORIGINS):
        pose = copy.deepcopy(IDENTITY)
        pose["origin"] = [x, 0, 0]
        if i == 3:
            pose.update(x=[-1, 0, 0], y=[0, -1, 0])
        if rotated:
            pose["origin"] = [20, 30 + x, 0]
            pose.update(x=[0, -1 if i == 3 else 1, 0], y=[1 if i == 3 else -1, 0, 0])
        members["nut" + str(i + 1)] = {"pose": pose}
    stock = {
        "shape": "box", "origin_mm": [0, -11.1125, 0],
        "axis": [1, 0, 0], "section_axis": [0, 1, 0],
        "length_mm": 113.665, "section_mm": [22.225, 12.7],
    }
    frame = {**copy.deepcopy(IDENTITY), "origin": [12.7, 0, 12.7]}
    if rotated:
        stock.update(origin_mm=[31.1125, 30, 0], axis=[0, 1, 0], section_axis=[-1, 0, 0])
        frame.update(origin=[20, 42.7, 12.7], x=[0, 1, 0], y=[-1, 0, 0])
    return initialize(step, stock, frame, members)

def operation(leave=.254, y=None, x=None, tip=-6.35):
    y = (12.8905 if leave else 12.6365) if y is None else y
    x = ([-19.304, 107.569] if leave else [-19.05, 107.315]) if x is None else x
    op = {
        "subject": "S1:rough" if leave else "S1:finish",
        "do": "rough_profile" if leave else "finish_profile",
        "profile_model": "guided_sweep",
        "workpiece_faces": {"nut" + str(i): list(WALLS) for i in range(1, 5)},
        "radius_mm": 6.35, "rough_allowance_mm": leave,
        "flute_len_mm": 25.4, "oal_mm": 80, "projection_mm": 40,
        "holder_radius_mm": 10, "holder_gauge_len_mm": 6,
        "to_z": tip,
        "sweep_bounds": {"x": [-25, 115], "y": [-25, 25], "z": [tip, 0]},
        "checkpoints": {"paths": [
            {"method": "linear_table", "xy_mm": [[x[0], sign*y], [x[1], sign*y]], "tip_z_mm": tip}
            for sign in [-1, 1]
        ], "rows": []},
    }
    live_ops.append(op)
    return op

def capsule(x0, x1, y, radius, tip):
    # Explicit elementary OCC primitives, not _centre_sweep/_path_area/_run_out.
    height = 30 - tip
    slab = Part.makeBox(x1-x0, 2*radius, height, V(x0, y-radius, tip))
    return slab.fuse(Part.makeCylinder(radius, height, V(x0, y, tip))).fuse(
        Part.makeCylinder(radius, height, V(x1, y, tip)))

def oracle_sweep(op):
    pieces = []
    for path in op["checkpoints"]["paths"]:
        a, b = path["xy_mm"]
        pieces.append(capsule(a[0], b[0], a[1], op["radius_mm"], path["tip_z_mm"]))
    return pieces[0].fuse(pieces[1])

def ready_paths(op, entry=0):
    # Normalized table packet: printed tables arrive separately as checkpoints.
    # The intermediate level makes full commanded motion distinct from the final cut.
    op["tool_paths"] = {
        "paths": [], "tables": True, "levels_mm": [op["to_z"], -1],
        "entry_z_mm": entry,
    }

def build_facts(runner, ops):
    runner.ops = ops
    runner.built = runner._build()
    return [runner._op(op) for op in ops]

def motion_facts(runner, op):
    try:
        moves = runner._tool_moves(op)
    except job._Unknown as exc:
        return {"unknown": str(exc)}
    return {
        "unknown": None,
        "lateral_levels": [[move[1], move[2]] for move in moves if len(move[0]) > 1],
        "end_tops": [move[2] for move in moves if len(move[0]) == 1],
    }

def distance(a, b):
    return a.cut(b).Volume + b.cut(a).Volume

def cut(runner, op, stock):
    plan, why = runner._cut(op, stock)
    if why is not None or plan is None:
        return None, why, None
    own, groups = plan
    kept, why = runner._remove(stock, own, groups)
    if kept is None:
        return None, why, groups
    return Part.makeCompound(kept), why, groups

canonical = Part.Shape()
canonical.read(step)
assert len(canonical.Solids) == 1 and len(canonical.Faces) == 11
independent_members = []
normal_skin = []
for i, x in enumerate(ORIGINS):
    member = canonical.copy()
    if i == 3:
        member.rotate(V(0, 0, 0), V(0, 0, 1), 180)
    member.translate(V(x-12.7, 0, -12.7))
    independent_members.append(member)
    for index in [5, 7]:
        face = member.Faces[index]
        u0, u1, v0, v1 = face.ParameterRange
        normal = face.normalAt((u0+u1)/2, (v0+v1)/2)
        normal_skin.append(face.extrude(normal * .254))
target = Part.makeCompound(independent_members)
skin = Part.makeCompound(normal_skin)
bar = Part.makeBox(113.665, 22.225, 12.7, V(-12.7, -11.1125, -12.7))
result = {"positive": {}}
for name, rotated in [("registered", False), ("rotated_translated", True)]:
    runner = scene(rotated)
    rough, finish = operation(), operation(0)
    rough_expected = bar.cut(oracle_sweep(rough))
    finish_expected = rough_expected.cut(oracle_sweep(finish))
    after_rough, rough_why, rough_groups = cut(runner, rough, runner.part)
    assert after_rough is not None, rough_why
    after_finish, finish_why, finish_groups = cut(runner, finish, after_rough)
    assert after_finish is not None, finish_why
    guards, leave, guard_why = runner._guided_guard(rough)
    assert guards is not None, guard_why
    guard = Part.makeCompound(guards)
    checkpoint, checkpoint_leave, checkpoint_why = runner._checkpoint_guard(rough)
    assert checkpoint is not None, checkpoint_why
    # Native checkpoint guard's public shape is [(window or None, [solids])].
    checkpoint_shapes = [solid for window, solids in checkpoint for solid in solids]
    checkpoint_guard = Part.makeCompound(checkpoint_shapes)
    # A whole central prism includes every future gap's stem, not only target solids.
    stem = Part.makeBox(113.665, 12.573, 6.35, V(-12.7, -6.2865, -6.35))
    # Unclaimed shelf normal is +Z. Its .254 axial layer is NOT rough leave.
    shelf_layer = Part.makeBox(100, 3, .254, V(-5, 7, -6.35))
    row = {
        "entry_difference": distance(runner.part, bar),
        "target_difference": distance(runner.finished, target),
        "rough_volume": after_rough.Volume, "finish_volume": after_finish.Volume,
        "rough_difference": distance(after_rough, rough_expected),
        "finish_difference": distance(after_finish, finish_expected),
        "rough_target_loss": target.cut(after_rough).Volume,
        "finish_target_loss": target.cut(after_finish).Volume,
        "rough_normal_leave_loss": skin.cut(after_rough).Volume,
        "gapstem_loss": stem.cut(after_finish).Volume,
        "unclaimed_floor_layer_left": shelf_layer.common(after_rough).Volume,
        "rough_extra_groups": len(rough_groups), "finish_extra_groups": len(finish_groups),
        "guard_target_loss": target.cut(guard).Volume,
        "guard_skin_loss": skin.cut(guard).Volume,
        "guard_unclaimed_floor": shelf_layer.common(guard).Volume,
        "checkpoint_difference": distance(checkpoint_guard, guard),
        "leave": leave, "checkpoint_leave": checkpoint_leave,
        "guarded": runner._guarded(rough),
    }
    result["positive"][name] = row

# Entry is measured independently from BEFORE stock intersected with the whole
# raw capsule sweep, in setup mm; neither a declared entry nor a kernel helper
# supplies this oracle. Keep the original unbound-path controls above unchanged.
result["ready_entry"] = {}
for name, rotated in [("registered", False), ("rotated_translated", True)]:
    entry_runner = scene(rotated)
    rough, finish = operation(), operation(0)
    for op in (rough, finish):
        ready_paths(op)
    facts = build_facts(entry_runner, [rough, finish])
    rows = []
    for op, op_facts in zip((rough, finish), facts):
        before, after, why = entry_runner.cuts[id(op)]
        swept = oracle_sweep(op)
        rows.append({
            "actual_entry": before.common(swept).BoundBox.ZMax,
            "difference": distance(after, before.cut(swept)),
            "stock_removal_error": op_facts.get("stock_removal_error"),
            "guided_error": entry_runner.guided_errors.get(id(op)),
            "cut_reason": why, "motion": motion_facts(entry_runner, op),
        })
    result["ready_entry"][name] = {
        "built": entry_runner.built[0] is not None,
        "reason": entry_runner.built[1], "ops": rows,
        "rough_difference": distance(entry_runner.cuts[id(rough)][1], bar.cut(oracle_sweep(rough))),
        "finish_difference": distance(
            entry_runner.cuts[id(finish)][1],
            bar.cut(oracle_sweep(rough)).cut(oracle_sweep(finish))),
    }

result["entry_mismatch"] = {}
for scene_name, rotated in [("registered", False), ("rotated_translated", True)]:
    for label, entry in [("too_low", -1), ("too_high", 1)]:
        for stage, leave in [("rough", .254), ("finish", 0)]:
            entry_runner = scene(rotated)
            op = operation(leave)
            ready_paths(op, entry)
            facts = build_facts(entry_runner, [op])[0]
            before, after, why = entry_runner.cuts[id(op)]
            result["entry_mismatch"][scene_name + "/" + stage + "/" + label] = {
                "actual_entry": bar.common(oracle_sweep(op)).BoundBox.ZMax,
                "failed_build": entry_runner.built[0] is None,
                "reason": entry_runner.built[1],
                "before_difference": distance(before, bar),
                "after_difference": distance(after, bar),
                "guided_error": entry_runner.guided_errors.get(id(op)),
                "stock_removal_error": facts.get("stock_removal_error"),
            }

result["entry_unknown"] = {}
for name, entry in [
    ("missing", None), ("nan", float("nan")),
    ("positive_infinity", float("inf")), ("negative_infinity", -float("inf")),
]:
    entry_runner = scene()
    op = operation()
    ready_paths(op, entry)
    if name == "missing":
        del op["tool_paths"]["entry_z_mm"]
    facts = build_facts(entry_runner, [op])[0]
    before, after, why = entry_runner.cuts[id(op)]
    result["entry_unknown"][name] = {
        "failed_build": entry_runner.built[0] is None,
        "reason": entry_runner.built[1],
        "after_difference": distance(after, before),
        "motion": motion_facts(entry_runner, op),
        "guided_error": entry_runner.guided_errors.get(id(op)),
        "stock_removal_error": facts.get("stock_removal_error"),
    }

result["motion_debt"] = {}
for name in ("absent", "reasoned_unknown"):
    debt_runner = scene()
    op = operation()
    if name == "reasoned_unknown":
        op["tool_paths"] = {"reason": "intermediate levels and entry are unresolved"}
    facts = build_facts(debt_runner, [op])[0]
    before, after, why = debt_runner.cuts[id(op)]
    result["motion_debt"][name] = {
        "built": debt_runner.built[0] is not None, "reason": debt_runner.built[1],
        "difference": distance(after, bar.cut(oracle_sweep(op))),
        "guided_error": debt_runner.guided_errors.get(id(op)),
        "stock_removal_error": facts.get("stock_removal_error"),
        "motion": motion_facts(debt_runner, op),
    }

runner = scene()
result["missing_paths"] = {}
variants = {
    "missing_table": None,
    "missing_paths": {"rows": []},
    "empty_paths": {"paths": []},
    "unknown_table": {"reason": "printed path unavailable", "paths": []},
    "unknown_method": {"paths": [
        {"method": "unknown", "xy_mm": [[-20, 13], [110, 13]], "tip_z_mm": -6.35}
    ]},
    "missing_method": {"paths": [{"xy_mm": [[-20, 13], [110, 13]], "tip_z_mm": -6.35}]},
    "empty_points": {"paths": [{"method": "linear_table", "xy_mm": [], "tip_z_mm": -6.35}]},
    "one_point": {"paths": [{"method": "linear_table", "xy_mm": [[0, 13]], "tip_z_mm": -6.35}]},
    "zero_length": {"paths": [
        {"method": "linear_table", "xy_mm": [[0, 13], [0, 13]], "tip_z_mm": -6.35}
    ]},
    "malformed_point": {"paths": [
        {"method": "linear_table", "xy_mm": [[0, 13], [1]], "tip_z_mm": -6.35}
    ]},
    "unknown_tip": {"paths": [
        {"method": "linear_table", "xy_mm": [[-20, 13], [110, 13]], "tip_z_mm": "unknown"}
    ]},
    "nonfinite_tip": {"paths": [
        {"method": "linear_table", "xy_mm": [[-20, 13], [110, 13]], "tip_z_mm": float("inf")}
    ]},
    "nonfinite_point": {"paths": [
        {"method": "linear_table", "xy_mm": [[0, 13], [float("nan"), 13]], "tip_z_mm": -6.35}
    ]},
}
for name, table in variants.items():
    op = operation()
    if table is None:
        del op["checkpoints"]
    else:
        op["checkpoints"] = table
    removal, why = runner._guided_removal(op, runner.part)
    plan, cut_why = runner._cut(op, runner.part)
    result["missing_paths"][name] = {
        "no_removal": removal is None, "reason": why,
        "no_plan": plan is None, "cut_reason": cut_why,
    }
# A malformed second path cannot borrow the first valid path's proof.
op = operation()
op["checkpoints"]["paths"].append(variants["one_point"]["paths"][0])
removal, why = runner._guided_removal(op, runner.part)
result["missing_paths"]["partially_valid"] = {"no_removal": removal is None, "reason": why}

result["unknown_geometry"] = {}
for name in ["radius", "claims", "protection"]:
    op = operation()
    if name == "radius":
        del op["radius_mm"]
    elif name == "claims":
        op["workpiece_faces"] = {"nut1": ["#999999/ADVANCED_FACE[999999]/stale"]}
    old_reason = runner.protection_reason
    if name == "protection":
        runner.protection_reason = "finished material ownership is unknown"
    try:
        removal, why = runner._guided_removal(op, runner.part)
        result["unknown_geometry"][name] = {
            "no_removal": removal is None, "reason": why,
            "false_error": runner.guided_errors.get(id(op)),
        }
    finally:
        runner.protection_reason = old_reason

result["inward"] = {}
for name, y in [("target", 12.4), ("normal_leave_only", 12.75)]:
    op = operation(y=y)
    swept = oracle_sweep(op)
    inward_runner = scene()
    removal, why = inward_runner._guided_removal(op, inward_runner.part)
    # _op consumes the builder's identity-keyed before/after material records.
    # Derive the real rejected operation, rather than inventing a cuts entry.
    inward_runner.ops = [op]
    inward_runner.built = inward_runner._build()
    assert inward_runner.built[0] is None and inward_runner.built[1]
    facts = inward_runner._op(op)
    result["inward"][name] = {
        "target_intersection": swept.common(target).Volume,
        "normal_leave_intersection": swept.common(skin).Volume,
        "no_removal": removal is None, "reason": why,
        "stock_removal_error": facts.get("stock_removal_error"),
    }

# A short harmless guide cannot clear the remaining claimed walls or carried leave.
op = operation(0, x=[-12, -10])
runner.leave_in = .254
short, why, groups = cut(runner, op, runner.part)
assert short is not None, why
result["short_path"] = {
    "difference": distance(short, bar.cut(oracle_sweep(op))),
    "extra_groups": len(groups),
    "remote_stock_loss": Part.makeBox(10, 3, 5, V(50, 8, -5)).cut(short).Volume,
}

# Authored broad removal remains authoritative even with absent printed paths.
# Compare native broad behavior with the selector absent; never redefine it here.
runner = scene()
# Future drills own the bore columns: broad sidewall clearing must preserve them.
# Declare them before this fresh scene's first planned-hole inventory.
runner.owner.job["setups"].append({
    "id": "S2", "stock_in": "S1",
    "frame": copy.deepcopy(runner.setup["frame"]),
    "material": {"workpieces": sorted(runner.owner.workpieces)},
    "ops": [{
        "subject": "S2:drill-" + name, "do": "drill",
        "workpiece_faces": {name: ["#287/ADVANCED_FACE[9]/"]}, "radius_mm": 4.7625,
        "flute_len_mm": 25.4, "oal_mm": 80, "projection_mm": 40,
        "holder_radius_mm": 10, "holder_gauge_len_mm": 6,
        "shank_radius_mm": 4.7625, "shank_from_mm": 25.4,
        "to_z": -12.7, "rough_allowance_mm": 0,
        "hole": {"thru": True, "depth_mm": 12.7, "entry_z_mm": 0},
    } for name in sorted(runner.owner.workpieces)],
})
runner.leave_in = 0
op = operation(0)
op["stock_removal_bounds"] = {"x": [-12.7, 100.965], "y": [-11.1125, 11.1125], "z": [-6.35, 0]}
del op["checkpoints"]
plain = copy.deepcopy(op)
del plain["profile_model"]
with_flag, why, _ = cut(runner, op, runner.part)
without_flag, other_why, _ = cut(runner, plain, runner.part)
assert with_flag is not None and without_flag is not None, (why, other_why)
result["broad"] = {
    "selected": job._guided_profile(op),
    "difference": distance(with_flag, without_flag),
    "volume": with_flag.Volume,
    "guided_difference": distance(with_flag, bar.cut(oracle_sweep(operation(0)))),
}

# A small independent positive control with finite planar walls and a real shelf.
base = Part.makeBox(20, 20, 5, V(0, -10, -10))
box_target = base.fuse(Part.makeBox(20, 8, 5, V(0, -4, -5))).removeSplitter()
box_path = out + "/control.step"
box_target.exportStep(box_path)
box_runner = initialize(box_path, {
    "shape": "box", "origin_mm": [-5, -10, -10], "axis": [1, 0, 0],
    "section_axis": [0, 1, 0], "length_mm": 30, "section_mm": [20, 10],
}, IDENTITY)
wall_refs = []
for index, face in enumerate(box_runner.faces):
    b = face.BoundBox
    if abs(b.YLength) < 1e-7 and abs(abs(b.YMin)-4) < 1e-7 and abs(b.ZMin+5) < 1e-7:
        wall_refs.append(box_runner.owner.labels[index])
assert len(wall_refs) == 2
op = operation(.5, y=5.5, x=[-7, 27], tip=-5)
op.pop("workpiece_faces")
op.update(faces=wall_refs, radius_mm=1)
after, why, groups = cut(box_runner, op, box_runner.part)
assert after is not None, why
result["box"] = {
    "volume": after.Volume, "target_loss": box_target.cut(after).Volume,
    "difference": distance(after, box_runner.part.cut(oracle_sweep(op))),
    "extra_groups": len(groups),
    "floor_layer_left": Part.makeBox(18, 1, .5, V(1, 5, -5)).common(after).Volume,
}

# A real profiled supply has an elevated boss entirely outside both cutter
# capsules. Its global top is +3, but actual swept-region entry remains zero.
# Fuse to one connected solid so no holding/split exception can mask entry.
remote_boss = Part.makeBox(4, 4, 3, V(5, -2, 0))
local_stock = Part.makeBox(30, 20, 10, V(-5, -10, -10)).fuse(remote_boss).removeSplitter()
local_path = out + "/remote-boss-stock.step"
local_stock.exportStep(local_path)
with open(local_path, "rb") as handle:
    local_digest = hashlib.sha256(handle.read()).hexdigest()
result["local_entry"] = {}
for name, declared in [("actual_surface", 0), ("global_bbox_top", 3)]:
    local_runner = initialize(box_path, {
        "shape": "profiled", "step_path": local_path, "step_sha256": local_digest,
    }, IDENTITY)
    local_refs = []
    for index, face in enumerate(local_runner.faces):
        b = face.BoundBox
        if abs(b.YLength) < 1e-7 and abs(abs(b.YMin)-4) < 1e-7 and abs(b.ZMin+5) < 1e-7:
            local_refs.append(local_runner.owner.labels[index])
    assert len(local_refs) == 2
    op = operation(.5, y=5.5, x=[-7, 27], tip=-5)
    op.pop("workpiece_faces")
    op.update(faces=local_refs, radius_mm=1)
    ready_paths(op, declared)
    swept = oracle_sweep(op)
    facts = build_facts(local_runner, [op])[0]
    before, after, why = local_runner.cuts[id(op)]
    result["local_entry"][name] = {
        "stock_difference": distance(before, local_stock),
        "global_top": local_stock.BoundBox.ZMax,
        "actual_entry": local_stock.common(swept).BoundBox.ZMax,
        "boss_sweep_intersection": remote_boss.common(swept).Volume,
        "built": local_runner.built[0] is not None, "reason": local_runner.built[1],
        "expected_difference": distance(after, local_stock.cut(swept)),
        "unchanged_difference": distance(after, before),
        "boss_loss": remote_boss.cut(after).Volume,
        "target_loss": box_target.cut(after).Volume,
        "guided_error": local_runner.guided_errors.get(id(op)),
        "stock_removal_error": facts.get("stock_removal_error"),
    }
with open(out + "/guided.json", "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


@pytest.fixture(scope="module")
def guided_native(tmp_path_factory, freecad_kernel):
    assert hashlib.sha256(STEP.read_bytes()).hexdigest() == SHA256
    directory = tmp_path_factory.mktemp("guided-profile")
    script = directory / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory), str(STEP)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(source)},
    )
    report = directory / "guided.json"
    assert report.exists(), process.stdout[-4000:] + process.stderr[-4000:]
    return json.loads(report.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scene", ["registered", "rotated_translated"])
def test_registered_guided_rough_and_finish_are_only_exact_sweeps(guided_native, scene):
    facts = guided_native["positive"][scene]
    # Each path spans the entire stock X interval, so its within-stock capsule
    # is exactly a rectangular strip. These decimal volumes are independent OCC
    # results, also reproduced by width * depth * length strip arithmetic.
    assert facts["rough_volume"] == pytest.approx(25482.9087115, abs=1e-4)
    assert facts["finish_volume"] == pytest.approx(25116.2481545, abs=1e-4)
    for key in (
        "entry_difference",
        "target_difference",
        "rough_difference",
        "finish_difference",
        "rough_target_loss",
        "finish_target_loss",
        "rough_normal_leave_loss",
        "gapstem_loss",
    ):
        assert facts[key] == pytest.approx(0, abs=1e-5), (scene, key, facts[key])
    assert facts["rough_extra_groups"] == facts["finish_extra_groups"] == 0


@pytest.mark.parametrize("scene", ["registered", "rotated_translated"])
def test_guided_guards_share_claim_normal_leave_without_unclaimed_floor_leave(guided_native, scene):
    facts = guided_native["positive"][scene]
    assert facts["leave"] == facts["checkpoint_leave"] == 0.254
    assert facts["guarded"] == [0.254, None]
    for key in (
        "guard_target_loss",
        "guard_skin_loss",
        "guard_unclaimed_floor",
        "checkpoint_difference",
        "unclaimed_floor_layer_left",
    ):
        assert facts[key] == pytest.approx(0, abs=1e-5), (scene, key, facts[key])


def test_guided_requires_complete_nonempty_known_validated_paths(guided_native):
    for name, facts in guided_native["missing_paths"].items():
        assert facts["no_removal"] and facts["reason"], (name, facts)
        if "no_plan" in facts:
            assert facts["no_plan"] and facts["cut_reason"], (name, facts)


def test_guided_missing_geometry_is_unknown_not_target_penetration(guided_native):
    for name, facts in guided_native["unknown_geometry"].items():
        assert facts["no_removal"] and facts["reason"], (name, facts)
        assert facts["false_error"] is None, (name, facts)


def test_guided_inward_target_and_normal_leave_penetration_are_errors(guided_native):
    target = guided_native["inward"]["target"]
    leave = guided_native["inward"]["normal_leave_only"]
    assert target["target_intersection"] > 1
    assert leave["target_intersection"] == pytest.approx(0, abs=1e-6)
    assert leave["normal_leave_intersection"] > 1
    for facts in (target, leave):
        assert facts["no_removal"] and facts["reason"]
        assert isinstance(facts["stock_removal_error"], str) and facts["stock_removal_error"]


def test_guided_short_path_never_borrows_nominal_corridor_or_lineage_band(guided_native):
    facts = guided_native["short_path"]
    assert facts["difference"] == pytest.approx(0, abs=1e-5)
    assert facts["remote_stock_loss"] == pytest.approx(0, abs=1e-6)
    assert facts["extra_groups"] == 0


def test_authored_broad_box_precedes_guided_selector(guided_native):
    facts = guided_native["broad"]
    assert not facts["selected"]
    assert facts["difference"] == pytest.approx(0, abs=1e-5)
    assert facts["volume"] == pytest.approx(24152.99604875, abs=1e-4)
    assert facts["guided_difference"] > 900


def test_guided_planar_box_control_has_exact_volume_and_no_axial_shelf_leave(guided_native):
    facts = guided_native["box"]
    # Two 30 x 2 x 5 strips from a 30 x 20 x 10 blank.
    assert facts["volume"] == pytest.approx(5400, abs=1e-5)
    assert facts["target_loss"] == pytest.approx(0, abs=1e-6)
    assert facts["difference"] == pytest.approx(0, abs=1e-5)
    assert facts["floor_layer_left"] == pytest.approx(0, abs=1e-6)
    assert facts["extra_groups"] == 0


@pytest.mark.parametrize("scene", ["registered", "rotated_translated"])
def test_guided_ready_entry_binds_exact_rough_and_finish_geometry(guided_native, scene):
    facts = guided_native["ready_entry"][scene]
    assert facts["built"], facts["reason"]
    assert facts["reason"] is None
    assert facts["rough_difference"] == pytest.approx(0, abs=1e-5)
    assert facts["finish_difference"] == pytest.approx(0, abs=1e-5)
    assert len(facts["ops"]) == 2
    for row in facts["ops"]:
        assert row["actual_entry"] == pytest.approx(0, abs=1e-7)
        assert row["difference"] == pytest.approx(0, abs=1e-5)
        assert row["cut_reason"] is None
        assert row["guided_error"] is row["stock_removal_error"] is None
        assert row["motion"]["unknown"] is None
        assert row["motion"]["lateral_levels"] == [[-6.35, -1], [-6.35, -1]]
        assert row["motion"]["end_tops"] == [0, 0, 0, 0]


@pytest.mark.parametrize("scene", ["registered", "rotated_translated"])
@pytest.mark.parametrize("stage", ["rough", "finish"])
@pytest.mark.parametrize("entry", ["too_low", "too_high"])
def test_guided_ready_entry_mismatch_is_error_and_preserves_stock(
    guided_native, scene, stage, entry
):
    facts = guided_native["entry_mismatch"][scene + "/" + stage + "/" + entry]
    assert facts["actual_entry"] == pytest.approx(0, abs=1e-7)
    assert facts["failed_build"] and facts["reason"]
    assert facts["before_difference"] == pytest.approx(0, abs=1e-5)
    assert facts["after_difference"] == pytest.approx(0, abs=1e-5)
    assert isinstance(facts["guided_error"], str)
    assert "actual guided cut entry" in facts["guided_error"]
    assert facts["stock_removal_error"] == facts["guided_error"]


@pytest.mark.parametrize("entry", ["missing", "nan", "positive_infinity", "negative_infinity"])
def test_guided_ready_missing_or_nonfinite_entry_is_unknown_not_penetration(guided_native, entry):
    facts = guided_native["entry_unknown"][entry]
    assert facts["failed_build"] and facts["reason"]
    assert facts["after_difference"] == pytest.approx(0, abs=1e-5)
    assert facts["guided_error"] is facts["stock_removal_error"] is None
    assert isinstance(facts["motion"]["unknown"], str) and facts["motion"]["unknown"]


@pytest.mark.parametrize("packet", ["absent", "reasoned_unknown"])
def test_guided_unknown_motion_keeps_final_depth_material_without_readiness(guided_native, packet):
    facts = guided_native["motion_debt"][packet]
    assert facts["built"], facts["reason"]
    assert facts["reason"] is None
    assert facts["difference"] == pytest.approx(0, abs=1e-5)
    assert facts["guided_error"] is facts["stock_removal_error"] is None
    assert isinstance(facts["motion"]["unknown"], str) and facts["motion"]["unknown"]
    assert "lateral_levels" not in facts["motion"]
    if packet == "reasoned_unknown":
        assert "intermediate levels and entry are unresolved" in facts["motion"]["unknown"]


def test_guided_entry_uses_local_swept_stock_not_remote_boss_top(guided_native):
    accepted = guided_native["local_entry"]["actual_surface"]
    rejected = guided_native["local_entry"]["global_bbox_top"]
    for facts in (accepted, rejected):
        assert facts["stock_difference"] == pytest.approx(0, abs=1e-5)
        assert facts["actual_entry"] == pytest.approx(0, abs=1e-7)
        assert facts["global_top"] == pytest.approx(3, abs=1e-7)
        assert facts["boss_sweep_intersection"] == pytest.approx(0, abs=1e-7)
        assert facts["boss_loss"] == pytest.approx(0, abs=1e-6)
        assert facts["target_loss"] == pytest.approx(0, abs=1e-6)
    assert accepted["built"], accepted["reason"]
    assert accepted["reason"] is None
    assert accepted["expected_difference"] == pytest.approx(0, abs=1e-5)
    assert accepted["guided_error"] is accepted["stock_removal_error"] is None
    assert not rejected["built"] and rejected["reason"]
    assert rejected["unchanged_difference"] == pytest.approx(0, abs=1e-5)
    assert isinstance(rejected["guided_error"], str)
    assert "actual guided cut entry" in rejected["guided_error"]
    assert rejected["stock_removal_error"] == rejected["guided_error"]
