"""Finite mounted-saw proofs from the real ``freecad_job.py`` JSON boundary.

The protected STEP target is a small finished part in the lower remainder, not
our supplied block.  Every case supplies its complete cut/withdraw/lift cycle in
one job; the module fixture submits those jobs together to the existing native
Engine.  No manufactured native result or host-rule verdict is used here.

Required native smoke (PowerShell, from the repository root)::

    $env:PRECHIPS_REQUIRE_KERNEL = "1"
    uv run pytest tests/test_mounted_saw_native.py -q
"""

import hashlib
import json
import math
import os
import subprocess
from copy import deepcopy

import pytest
from test_kernel_geometry import ENGINE, IDENTITY, Engine

from prechips.kernel.step_faces import StepFile

POSE = {"origin_mm": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
STOCK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 40.0,
    "section_mm": [12.7, 30.0],
}

_AUTHOR = r"""
import sys
import Part
from FreeCAD import Vector as V
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

# Finished material stops at Z8, well below the Z13.4125..16.5875 kerf.
save("target", Part.makeBox(6, 3, 6, V(2, 1, 2)))
block = Part.makeBox(40, 12.7, 30)
# A polygonal through-hole gives two feed intervals at some transverse positions.
save("hollow", block.cut(Part.makeBox(4, 4, 32, V(18, 4, -1))))
# A single connected section with a curved outside boundary, not a hollow section.
save("curved", block.cut(Part.makeCylinder(2, 32, V(20, 0, -1))))
# The XY section varies inside the kerf: its mid-plane alone cannot certify it.
save("nonuniform", block.cut(Part.makeBox(4, 3, 2, V(18, 0, 14.9))))
save("upper-target", Part.makeBox(6, 3, 5, V(2, 1, 25)))
"""


def _box(name, at, size):
    return {"name": name, "shape": "box", "at_mm": list(at), "size_mm": list(size)}


def _pad(radius=22.0):
    return _box("setting-pad", [-140.0 + radius - 1.0, -101.0, 5.0], [2.0, 2.0, 5.0])


def _hold():
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": deepcopy(POSE),
        "solids": [
            _box("lower-front-jaw", [0.0, -3.0, 0.0], [40.0, 3.0, 10.0]),
            _box("lower-rear-jaw", [0.0, 12.7, 0.0], [40.0, 3.0, 10.0]),
            _pad(),
        ],
        "clamps": [],
        "debts": [],
        "gaps": [],
    }


def _capture():
    # Three upper-child side contacts, never intersecting its volume or the kerf.
    components = [
        ("capture-back", "fixture", [1.0, 12.7, 20.0], [38.0, 3.0, 5.0]),
        ("capture-left", "fixture", [-3.0, 8.0, 20.0], [3.0, 3.0, 5.0]),
        ("capture-right", "moving_clamp", [40.0, 8.0, 20.0], [3.0, 3.0, 5.0]),
    ]
    return {
        "fixture": "capture-frame",
        "pose": deepcopy(POSE),
        "moving_clamp": "capture-screw",
        "moving_clamp_pose": deepcopy(POSE),
        "state": "clamped",
        "components": [
            {
                "name": name,
                "role": role,
                "pose": deepcopy(POSE),
                "solids": [_box(name, at, size)],
            }
            for name, role, at, size in components
        ],
        "reasons": [],
        "errors": [],
    }


def _zero():
    return {
        "touches": [
            {
                "kind": "axis_zero",
                "axis": "z",
                "method": "mounted_saw_side",
                "tool": "blade",
                "holder": "arbor",
                "face": "fixture:setting-pad:+z",
                "edge_mm": 10.0,
                "paper_mm": 0.05,
                "position": 0,
                "before_ops": [10],
                "mounted_saw": {
                    "blade_side": "minus_z",
                    "axis_xy_mm": [-140.0, -100.0],
                    "point_mm": [-118.0, -100.0, 10.0],
                    "spindle_state": "stopped",
                },
                "surface": {"kind": "fixture", "name": "setting-pad", "side": "+z"},
            }
        ],
        "selected": 0,
        "fixtures": [{"name": "setting-pad", "pose": deepcopy(POSE), "solids": [_pad()]}],
        "reasons": [],
        "errors": [],
    }


def _mounted():
    return {
        "model": "finite_disk_v1",
        "blade": {
            "dia_mm": 50.8,
            "root_dia_mm": 48.0,
            "bore_dia_limits_mm": [12.7, 12.71],
            "thickness_mm": 3.048,
            "kerf_mm": 3.175,
            "kerf_offset_mm": 0.0,
            "flutes": 36,
            "tooth_spacing": "uniform",
        },
        "arbor": {
            "projection_mm": 45.0,
            "gauge_len_mm": 3.0,
            "pilot_dia_limits_mm": [12.7, 12.7],
            "bore_clearance_max_mm": 0.02,
            "blade_thickness_limits_mm": [3.0, 3.1],
            "envelope_state": "complete",
            "components": [
                {"id": "lower-flange", "dia_mm": 19.05, "z_min_mm": -49.0, "z_max_mm": -46.524},
                {"id": "upper-flange", "dia_mm": 19.05, "z_min_mm": -43.476, "z_max_mm": -40.0},
                {"id": "pilot", "dia_mm": 12.7, "z_min_mm": -46.524, "z_max_mm": -43.476},
                {"id": "stem", "dia_mm": 12.0, "z_min_mm": -40.0, "z_max_mm": 0.0},
                {"id": "nose", "dia_mm": 31.75, "z_min_mm": 0.0, "z_max_mm": 3.0},
            ],
            "cutting_rotation": "cw",
            "retaining_side": "minus_z",
            "retaining_thread_hand": "right",
        },
        "trajectory": {
            "start_mm": [-35.0, -10.541, 15.0],
            "moves": [
                {"to_mm": [75.0, -10.541, 15.0], "mode": "cut"},
                {"to_mm": [75.0, -60.0, 15.0], "mode": "clear"},
                {"to_mm": [75.0, -60.0, 80.0], "mode": "clear"},
            ],
        },
        "spindle_rotation": "cw",
        "direction": "conventional",
        "capture": _capture(),
        "zero": _zero(),
        "reasons": {},
        "errors": {},
    }


def _job(engine, target):
    op = {
        "subject": "S1:10",
        "do": "cut_off",
        "saw_tool": "slitting_saw",
        "cut_plane": {"axis": "z", "value": 15.0, "keep": "below"},
        "kerf_mm": 3.175,
        "mounted_saw": _mounted(),
    }
    setups = [
        {
            "id": "S1",
            "frame": deepcopy(IDENTITY),
            "machine_kind": "mill",
            "hold": _hold(),
            "ops": [op],
        },
        {
            "id": "S2",
            "frame": deepcopy(IDENTITY),
            "machine_kind": "mill",
            "hold": _hold(),
            "ops": [],
        },
    ]
    return engine.job(target, setups=setups, stock=deepcopy(STOCK))


def _op(job):
    return job["setups"][0]["ops"][0]


def _saw_input(job):
    return _op(job)["mounted_saw"]


def _change_pad(job, radius):
    _saw_input(job)["zero"]["touches"][0]["mounted_saw"]["point_mm"][0] = -140.0 + radius
    job["setups"][0]["hold"]["solids"][2] = _pad(radius)
    _saw_input(job)["zero"]["fixtures"][0]["solids"] = [_pad(radius)]


def _cases(engine, paths):
    jobs = {"positive": _job(engine, paths["target"])}

    def case(name):
        job = deepcopy(jobs["positive"])
        jobs[name] = job
        return job, _saw_input(job)

    _, saw = case("teeth-18")
    saw["blade"]["flutes"] = 18

    for field in ("flutes", "tooth_spacing"):
        _, saw = case(f"missing-{field}")
        saw["blade"][field] = "unknown"
        saw["reasons"][f"engagement.{field}"] = f"blade.{field} is unmeasured"

    for field in ("projection_mm", "components", "envelope_state"):
        _, saw = case(f"missing-{field}")
        saw["arbor"][field] = "unknown"
        saw["reasons"][f"arbor.{field}"] = f"arbor.{field} is unmeasured"
    _, saw = case("incomplete-envelope")
    saw["arbor"]["envelope_state"] = "incomplete"
    _, saw = case("missing-envelope-component")
    saw["arbor"]["components"][-1]["dia_mm"] = "unknown"
    saw["reasons"]["assembly.arbor.components.nose.dia_mm"] = "spindle-nose envelope is unmeasured"
    job, _ = case("scene-debt")
    job["setups"][0]["hold"]["debts"].append("an installed stop envelope is unmeasured")
    _, saw = case("assumed-projection")
    saw["arbor"]["projection_mm"] = "unknown"
    saw["reasons"]["arbor.projection_mm"] = "arbor.projection_mm is assumed, not measured"
    job, saw = case("missing-kerf")
    saw["blade"]["kerf_mm"] = "unknown"
    saw["reasons"]["blade.kerf_mm"] = "blade.kerf_mm is unmeasured"
    _op(job)["kerf_mm"] = "unknown"

    _, saw = case("wrong-installed-rotation")
    saw["arbor"]["cutting_rotation"] = "ccw"
    _, saw = case("loosening-thread")
    saw["arbor"]["retaining_thread_hand"] = "left"
    _, saw = case("wrong-feed-sense")
    saw["direction"] = "climb"
    _, saw = case("incompatible-bore")
    saw["blade"]["bore_dia_limits_mm"] = [12.6, 12.61]
    _, saw = case("incompatible-body-fit")
    saw["arbor"]["blade_thickness_limits_mm"] = [2.0, 2.5]
    _, saw = case("body-outside-kerf")
    saw["blade"]["kerf_offset_mm"] = 0.2

    _, saw = case("radial-miss")
    saw["trajectory"]["start_mm"][1] = -15.0
    saw["trajectory"]["moves"][0]["to_mm"][1] = -15.0
    _, saw = case("short-path")
    saw["trajectory"]["moves"][0]["to_mm"][0] = 25.0
    saw["trajectory"]["moves"][1]["to_mm"][0] = 25.0
    saw["trajectory"]["moves"][2]["to_mm"][0] = 25.0
    # A very small far-edge ligament is still material, not an epsilon-sized pass.
    _, saw = case("residual-ligament")
    saw["trajectory"]["start_mm"][1] = -12.71
    saw["trajectory"]["moves"][0]["to_mm"][1] = -12.71

    job, _ = case("mid-sweep-obstacle")
    job["setups"][0]["hold"]["solids"].append(
        _box("mid-sweep-stop", [19.0, -20.0, 14.0], [2.0, 1.0, 2.0])
    )
    job, _ = case("raised-jaw")
    job["setups"][0]["hold"]["solids"][0]["size_mm"][2] = 14.0
    _, saw = case("large-flange")
    saw["arbor"]["components"][0]["dia_mm"] = 25.4
    _, saw = case("post-cut-upper-collision")
    saw["trajectory"]["moves"] = [
        {"to_mm": [50.0, -10.541, 15.0], "mode": "cut"},
        {"to_mm": [50.0, -10.541, 80.0], "mode": "clear"},
        {"to_mm": [50.0, -60.0, 80.0], "mode": "clear"},
    ]
    _, saw = case("pre-cut-clear-through-stock")
    saw["trajectory"]["start_mm"] = [20.0, -10.541, 80.0]
    saw["trajectory"]["moves"].insert(0, {"to_mm": [20.0, -10.541, 15.0], "mode": "clear"})

    _, saw = case("pre-cut-clear-positive")
    saw["trajectory"]["start_mm"] = [-35.0, -60.0, 15.0]
    saw["trajectory"]["moves"].insert(0, {"to_mm": [-35.0, -10.541, 15.0], "mode": "clear"})
    _, saw = case("initially-embedded")
    saw["trajectory"]["start_mm"][0] = -10.0
    _, saw = case("axial-cut")
    saw["trajectory"]["start_mm"] = [20.0, -10.541, 80.0]
    saw["trajectory"]["moves"][0]["to_mm"] = [20.0, -10.541, 15.0]
    saw["trajectory"]["moves"][1]["to_mm"][0] = 20.0
    saw["trajectory"]["moves"][2]["to_mm"][0] = 20.0
    _, saw = case("diagonal-cut")
    saw["trajectory"]["start_mm"][1] = -11.0
    _, saw = case("diagonal-clear")
    saw["trajectory"]["moves"][1]["to_mm"] = [76.0, -60.0, 15.0]
    saw["trajectory"]["moves"][2]["to_mm"][0] = 76.0
    _, saw = case("multiple-cuts")
    saw["trajectory"]["moves"][1]["mode"] = "cut"

    _, saw = case("released-capture")
    saw["capture"]["state"] = "released"
    _, saw = case("missing-capture")
    saw["capture"]["state"] = "unknown"
    saw["capture"]["reasons"] = ["capture state is unmeasured"]
    _, saw = case("capture-gap")
    saw["capture"]["components"][2]["solids"][0]["at_mm"][0] = 40.5
    _, saw = case("capture-interpenetration")
    saw["capture"]["components"][2]["solids"][0]["at_mm"][0] = 39.5
    _, saw = case("capture-extra-embedded")
    saw["capture"]["components"].append(
        {
            "name": "capture-hidden",
            "role": "fixture",
            "pose": deepcopy(POSE),
            "solids": [_box("capture-hidden", [1.0, 8.0, 1.0], [2.0, 2.0, 2.0])],
        }
    )
    job, _ = case("primary-upper-only")
    # Both primary jaws contact the upper child, not the retained lower remainder.
    # Keep them above/beside the independent capture so that overlap is not the cause.
    job["setups"][0]["hold"]["solids"][0] = _box(
        "lower-front-jaw", [10.0, -3.0, 20.0], [20.0, 3.0, 10.0]
    )
    job["setups"][0]["hold"]["solids"][1] = _box(
        "lower-rear-jaw", [10.0, 12.7, 27.0], [20.0, 3.0, 3.0]
    )

    for section in ("hollow", "curved", "nonuniform"):
        job, _ = case(f"section-{section}")
        path = paths[section]
        job["stock"] = {
            "shape": "profiled",
            "step_path": str(path),
            "step_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    _, saw = case("missing-zero")
    saw["zero"] = {
        "touches": [],
        "selected": "unknown",
        "fixtures": [],
        "reasons": ["mounted setting is absent"],
        "errors": [],
    }
    _, saw = case("running-zero")
    saw["zero"]["touches"][0]["mounted_saw"]["spindle_state"] = "running"
    _, saw = case("unknown-spindle-zero")
    saw["zero"]["touches"][0]["mounted_saw"]["spindle_state"] = "unknown"
    for name, radius in (("flange-zero", 8.0), ("root-zero", 24.5)):
        job, _ = case(name)
        _change_pad(job, radius)
    _, saw = case("wrong-plane-zero")
    saw["zero"]["touches"][0]["mounted_saw"]["point_mm"][2] = 9.0
    _, saw = case("wrong-normal-zero")
    touch = saw["zero"]["touches"][0]
    touch["surface"]["side"] = "-z"
    touch["face"] = "fixture:setting-pad:-z"
    touch["edge_mm"] = 5.0
    touch["mounted_saw"]["point_mm"][2] = 5.0
    job = _job(engine, paths["upper-target"])
    jobs["broad-stock-top-zero"] = job
    job["features"] = {
        "setting-top": [
            face.ref for face in StepFile(paths["upper-target"].read_text(encoding="latin-1")).faces
        ]
    }
    saw = _saw_input(job)
    touch = saw["zero"]["touches"][0]
    touch["surface"] = {"kind": "stock", "side": "+z", "face": "setting-top"}
    touch["face"] = "setting-top"
    touch["edge_mm"] = 30.0
    touch["mounted_saw"]["axis_xy_mm"] = [-2.0, 6.35]
    touch["mounted_saw"]["point_mm"] = [20.0, 6.35, 30.0]
    _, saw = case("upper-body-zero")
    touch = saw["zero"]["touches"][0]
    touch["mounted_saw"]["blade_side"] = "plus_z"
    touch["mounted_saw"]["point_mm"][2] = 5.0
    touch["surface"]["side"] = "-z"
    touch["face"] = "fixture:setting-pad:-z"
    touch["edge_mm"] = 5.0
    _, saw = case("offset-zero")
    # 0.04 mm is smaller than the (kerf-body)/2 available containment margin.
    saw["blade"]["kerf_offset_mm"] = 0.04

    job, _ = case("finite-rear-post")
    # This post intersects the old all-holding Z kerf slab, but never the finite saw.
    job["setups"][0]["hold"]["solids"].append(
        _box("rear-post", [-20.0, 40.0, -75.0], [40.0, 10.0, 225.0])
    )
    job, _ = case("withdrawal-distance")
    job["setups"][0]["hold"]["solids"].append(
        _box("withdrawal-stop", [101.0, -50.0, 13.0], [1.0, 1.0, 3.0])
    )
    job, _ = case("lift-distance")
    job["setups"][0]["hold"]["solids"].append(
        _box("lift-stop", [91.125, -61.0, 110.0], [1.0, 2.0, 1.0])
    )
    job, saw = case("pre-cut-distance")
    saw["trajectory"]["start_mm"] = [-35.0, -60.0, 15.0]
    saw["trajectory"]["moves"].insert(0, {"to_mm": [-35.0, -10.541, 15.0], "mode": "clear"})
    job["setups"][0]["hold"]["solids"].append(
        _box("pre-cut-stop", [-61.65, -50.0, 14.0], [1.0, 1.0, 2.0])
    )
    return jobs


@pytest.fixture(scope="module")
def native_cases(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("mounted-saw-native")
    author = directory / "author.py"
    author.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(author), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {
        name: directory / f"{name}.step"
        for name in ("target", "upper-target", "hollow", "curved", "nonuniform")
    }
    assert all(path.exists() for path in paths.values()), (
        process.stdout[-2000:] + process.stderr[-2000:]
    )
    engine = Engine(directory, freecad_kernel)
    jobs = _cases(engine, paths)
    batch = engine.run({"jobs": list(jobs.values())})
    results = batch["results"]
    assert len(results) == len(jobs), batch
    return dict(zip(jobs, results, strict=True))


def _detail(native_cases, name):
    result = native_cases[name]
    assert result["status"] == "ok", result
    detail = result["ops"]["S1:10"]
    saw = detail["saw"]
    assert saw["model"] == "finite_disk_v1", saw
    assert saw["status"] in {"pass", "error", "unknown"}, saw
    return detail, saw


def test_complete_finite_geometry_has_two_physical_children_and_conserves_stock(native_cases):
    detail, saw = _detail(native_cases, "positive")
    assert saw["status"] == "pass", saw
    assert saw["reasons"] == []
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    assert saw["body_band_mm"] == pytest.approx([13.476, 16.524])
    assert saw["cutting_band_mm"] == pytest.approx([13.4125, 16.5875])
    assert saw["gauge_plane_z_mm"] == pytest.approx(60.0)
    assert saw["spindle_nose_z_mm"] == pytest.approx(63.0)
    assert saw["feed_direction"] == pytest.approx([1.0, 0.0, 0.0])
    assert saw["cut_move_index"] == 0
    assert saw["collisions"] == []
    assert saw["required_kerf_volume_mm3"] == pytest.approx(1612.9)
    assert saw["removed_kerf_volume_mm3"] == pytest.approx(1612.9)
    assert saw["uncovered_kerf_volume_mm3"] == pytest.approx(0.0, abs=1e-5)
    assert saw["unintended_removal_volume_mm3"] == pytest.approx(0.0, abs=1e-5)
    assert saw["stock_volume_before_mm3"] == pytest.approx(15240.0)
    assert saw["stock_volume_after_mm3"] == pytest.approx(13627.1)
    children = saw["outputs"]
    assert [child["side"] for child in children] == ["below", "above"]
    assert [child["volume_mm3"] for child in children] == pytest.approx([6813.55, 6813.55])
    assert children[0]["bbox_mm"] == pytest.approx([0.0, 0.0, 0.0, 40.0, 12.7, 13.4125])
    assert children[1]["bbox_mm"] == pytest.approx([0.0, 0.0, 16.5875, 40.0, 12.7, 30.0])
    assert saw["stock_volume_before_mm3"] == pytest.approx(
        saw["removed_kerf_volume_mm3"] + sum(child["volume_mm3"] for child in children)
    )
    assert detail["kerf_volume_mm3"] == pytest.approx(1612.9)
    assert detail["removed_volume_mm3"] == pytest.approx(1612.9)
    assert detail["offcut_volume_mm3"] == 0.0
    following = native_cases["positive"]["setups"]["S2"]
    assert following["stock_volume_mm3"] == pytest.approx(13627.1)
    assert following["stock_bbox_mm"] == pytest.approx([0.0, 0.0, 0.0, 40.0, 12.7, 30.0])


def test_assembly_axis_and_nose_bounds_cover_calibration_and_the_entire_withdrawal(native_cases):
    _, saw = _detail(native_cases, "positive")
    assert saw["axis_path_bounds_mm"] == pytest.approx(
        [-140.0, -100.0, 11.574, 75.0, -10.541, 128.0]
    )
    assert saw["assembly_swept_bounds_mm"] == pytest.approx(
        [-165.4, -125.4, 7.574, 100.4, 14.859, 128.0]
    )
    assert saw["spindle_nose_bounds_mm"] == pytest.approx(
        [-140.0, -100.0, 59.574, 75.0, -10.541, 128.0]
    )
    _, precut = _detail(native_cases, "pre-cut-clear-positive")
    assert precut["status"] == "pass", precut
    assert precut["cut_move_index"] == 1
    assert precut["axis_path_bounds_mm"] == pytest.approx(
        [-140.0, -100.0, 11.574, 75.0, -10.541, 128.0]
    )
    assert precut["collisions"] == []


def test_capture_is_solid_contact_with_the_actual_upper_child(native_cases):
    _, saw = _detail(native_cases, "positive")
    capture = saw["capture"]
    assert capture["status"] == "pass", capture
    assert set(capture["contacts"]) == {"capture-back", "capture-left", "capture-right"}
    assert capture["moving_clamp_contact"] is True
    assert capture["reasons"] == []


@pytest.mark.parametrize("case,teeth,minimum", [("positive", 36, 4), ("teeth-18", 18, 2)])
def test_established_engagement_uses_circular_geometry_and_worst_tooth_phase(
    native_cases, case, teeth, minimum
):
    _, saw = _detail(native_cases, case)
    assert saw["status"] == "pass", saw
    engagement = saw["engagement"]
    assert engagement["status"] == "pass", engagement
    # Independent rectangular-section solution: u is +Y from the Y=-10.541 axis.
    radius, near, far = 25.4, 10.541, 23.241
    q_near = math.sqrt(radius * radius - near * near)
    q_far = math.sqrt(radius * radius - far * far)
    first, complete, exits, last = 35.0 - q_near, 35.0 - q_far, 75.0 - q_near, 75.0 - q_far
    angle = math.asin(far / radius) - math.asin(near / radius)
    assert engagement["radius_mm"] == radius
    assert engagement["transverse_interval_mm"] == pytest.approx([near, far])
    assert engagement["first_contact_mm"] == pytest.approx(first)
    assert engagement["entry_complete_mm"] == pytest.approx(complete)
    assert engagement["exit_begins_mm"] == pytest.approx(exits)
    assert engagement["last_contact_mm"] == pytest.approx(last)
    assert engagement["established_interval_mm"] == pytest.approx([complete, exits])
    assert engagement["engaged_angle_rad"] == pytest.approx(angle)
    assert engagement["tooth_count"] == teeth
    assert engagement["tooth_spacing"] == "uniform"
    assert engagement["pitch_rad"] == pytest.approx(2.0 * math.pi / teeth)
    assert engagement["minimum_teeth_in_work"] == minimum
    assert engagement["minimum_teeth_tie"] is False
    assert (minimum >= 3) is (teeth == 36)
    for name, start, end in (("entry", first, complete), ("exit", exits, last)):
        transition = engagement[name]
        assert transition["from_mm"] == pytest.approx(start)
        assert transition["to_mm"] == pytest.approx(end)
        assert transition["monotone"] is True
        assert transition["tooth_loading_certified"] is False


@pytest.mark.parametrize("case", ["missing-flutes", "missing-tooth_spacing"])
def test_engagement_debt_does_not_erase_complete_geometry_or_zero(native_cases, case):
    _, saw = _detail(native_cases, case)
    assert saw["status"] == "pass", saw
    assert saw["engagement"]["status"] == "unknown", saw["engagement"]
    assert saw["engagement"]["reasons"]
    assert saw["zero"]["status"] == "pass", saw["zero"]
    assert saw["removed_kerf_volume_mm3"] == pytest.approx(1612.9)


@pytest.mark.parametrize("case", ["radial-miss", "short-path", "residual-ligament"])
def test_incomplete_finite_cut_reports_real_uncovered_material(native_cases, case):
    detail, saw = _detail(native_cases, case)
    assert saw["status"] != "pass", saw
    assert saw["required_kerf_volume_mm3"] == pytest.approx(1612.9)
    assert saw["uncovered_kerf_volume_mm3"] > 0.0, saw
    assert saw["removed_kerf_volume_mm3"] < 1612.9, saw
    assert "stock_bbox_mm" not in native_cases[case]["setups"]["S2"]
    assert "saw_error" in detail or "saw_reason" in detail


@pytest.mark.parametrize(
    "case,component,obstacle,move,mode",
    [
        ("mid-sweep-obstacle", None, "mid-sweep-stop", 0, "cut"),
        ("raised-jaw", None, "lower-front-jaw", 0, "cut"),
        ("large-flange", "arbor:lower-flange", "stock", 0, "cut"),
        ("post-cut-upper-collision", None, "child:upper", 1, "clear"),
    ],
)
def test_exact_assembly_sweeps_report_component_obstacle_and_positive_collision_volume(
    native_cases, case, component, obstacle, move, mode
):
    detail, saw = _detail(native_cases, case)
    assert saw["status"] == "error", saw
    assert "saw_error" in detail, detail
    assert saw["engagement"]["status"] == "pass", saw["engagement"]
    assert saw["zero"]["status"] == "pass", saw["zero"]
    hits = [
        hit
        for hit in saw["collisions"]
        if hit["obstacle"] == obstacle
        and hit["move_index"] == move
        and hit["mode"] == mode
        and (component is None or hit["component"] == component)
    ]
    assert hits, saw["collisions"]
    for hit in hits:
        assert hit["component"] in {"blade_cutting", "blade_body"} or hit["component"].startswith(
            "arbor:"
        )
        assert hit["volume_mm3"] > 0.0
        bounds = hit["bbox_mm"]
        assert len(bounds) == 6 and all(bounds[axis] < bounds[axis + 3] for axis in range(3))
    if case == "mid-sweep-obstacle":
        # The stop is >54 mm from both endpoint axes, but inside the occupied feed sweep.
        assert math.hypot(19.0 - (-35.0), -19.0 - (-10.541)) > 25.4
        assert math.hypot(21.0 - 75.0, -19.0 - (-10.541)) > 25.4


@pytest.mark.parametrize(
    "case",
    [
        "missing-projection_mm",
        "assumed-projection",
        "missing-components",
        "missing-envelope-component",
        "missing-envelope_state",
        "incomplete-envelope",
        "missing-kerf",
        "scene-debt",
    ],
)
def test_missing_mount_or_kerf_facts_never_become_geometry_passes(native_cases, case):
    detail, saw = _detail(native_cases, case)
    assert saw["status"] == "unknown", saw
    assert saw["reasons"]
    assert "saw_reason" in detail and "saw_error" not in detail, detail
    assert "stock_bbox_mm" not in native_cases[case]["setups"]["S2"]
    assert saw["zero"]["status"] != "pass", saw["zero"]
    assert saw["zero"]["reasons"]


@pytest.mark.parametrize(
    "case",
    [
        "wrong-installed-rotation",
        "loosening-thread",
        "wrong-feed-sense",
        "incompatible-bore",
        "incompatible-body-fit",
        "body-outside-kerf",
    ],
)
def test_incompatible_mount_and_cutting_sense_are_known_geometry_errors(native_cases, case):
    detail, saw = _detail(native_cases, case)
    assert saw["status"] == "error", saw
    assert saw["reasons"]
    assert "saw_error" in detail, detail
    assert "stock_bbox_mm" not in native_cases[case]["setups"]["S2"]


def test_an_extra_capture_solid_cannot_hide_inside_the_lower_stock(native_cases):
    _, saw = _detail(native_cases, "capture-extra-embedded")
    assert saw["status"] == "error", saw
    assert saw["capture"]["status"] == "error", saw["capture"]
    assert saw["capture"]["reasons"]
    assert saw["stock_volume_before_mm3"] == pytest.approx(15240.0)
    assert saw["removed_kerf_volume_mm3"] == pytest.approx(1612.9)


def test_primary_holding_must_contact_the_actual_lower_child(native_cases):
    _, saw = _detail(native_cases, "primary-upper-only")
    assert saw["status"] != "pass", saw
    assert any("lower" in reason for reason in saw["reasons"]), saw
    assert saw["capture"]["status"] == "pass", saw["capture"]
    assert saw["capture"]["moving_clamp_contact"] is True


@pytest.mark.parametrize(
    "case", ["released-capture", "missing-capture", "capture-gap", "capture-interpenetration"]
)
def test_capture_must_be_clamped_and_touch_without_interpenetration(native_cases, case):
    _, saw = _detail(native_cases, case)
    assert saw["status"] != "pass", saw
    assert saw["capture"]["status"] != "pass", saw["capture"]
    assert saw["capture"]["reasons"]


@pytest.mark.parametrize(
    "case,before,removed",
    [
        ("section-hollow", 14760.0, 1562.1),
        ("section-curved", 15240.0 - 60.0 * math.pi, 1612.9 - 6.35 * math.pi),
        ("section-nonuniform", 15216.0, 1592.65),
    ],
)
def test_unsupported_engagement_sections_do_not_borrow_their_bounding_box(
    native_cases, case, before, removed
):
    _, saw = _detail(native_cases, case)
    assert saw["status"] == "pass", saw
    assert saw["stock_volume_before_mm3"] == pytest.approx(before)
    assert saw["required_kerf_volume_mm3"] == pytest.approx(removed)
    assert saw["removed_kerf_volume_mm3"] == pytest.approx(removed)
    assert len(saw["outputs"]) == 2
    assert saw["uncovered_kerf_volume_mm3"] == pytest.approx(0.0, abs=1e-5)
    assert saw["stock_volume_before_mm3"] == pytest.approx(
        saw["removed_kerf_volume_mm3"] + sum(child["volume_mm3"] for child in saw["outputs"])
    )
    assert saw["engagement"]["status"] == "unknown", saw["engagement"]
    assert saw["engagement"]["reasons"]
    assert saw["zero"]["status"] == "pass", saw["zero"]


@pytest.mark.parametrize(
    "case",
    [
        "initially-embedded",
        "axial-cut",
        "diagonal-cut",
        "diagonal-clear",
        "multiple-cuts",
        "pre-cut-clear-through-stock",
    ],
)
def test_unsupported_or_embedded_trajectories_never_certify_removal(native_cases, case):
    detail, saw = _detail(native_cases, case)
    assert saw["status"] != "pass", saw
    assert saw["reasons"]
    assert "saw_error" in detail or "saw_reason" in detail
    assert "stock_bbox_mm" not in native_cases[case]["setups"]["S2"]
    if case == "pre-cut-clear-through-stock":
        assert any(
            hit["obstacle"] == "stock"
            and hit["move_index"] == 0
            and hit["mode"] == "clear"
            and hit["volume_mm3"] > 0.0
            for hit in saw["collisions"]
        ), saw["collisions"]


def test_stopped_lower_body_touch_uses_body_thickness_not_kerf(native_cases):
    _, saw = _detail(native_cases, "positive")
    zero = saw["zero"]
    assert zero["status"] == "pass", zero
    assert zero["selected"] == 0
    (touch,) = zero["touches"]
    assert touch["status"] == "pass", touch
    assert touch["index"] == 0
    assert touch["blade_side"] == "minus_z"
    assert touch["surface_side"] == "+z"
    assert touch["spindle_state"] == "stopped"
    assert touch["plane_z_mm"] == 10.0 and touch["plane_normal_z"] == 1
    assert touch["point_mm"] == pytest.approx([-118.0, -100.0, 10.0])
    assert touch["axis_xy_mm"] == pytest.approx([-140.0, -100.0])
    assert touch["paper_mm"] == pytest.approx(0.05)
    assert touch["body_thickness_mm"] == pytest.approx(3.048)
    assert touch["kerf_offset_mm"] == 0.0
    assert touch["body_face_z_mm"] == pytest.approx(10.05)
    assert touch["cutting_midplane_z_mm"] == pytest.approx(11.574)
    assert touch["cutting_midplane_z_mm"] != pytest.approx(11.6375)
    assert touch["contact_radius_mm"] == pytest.approx(22.0)
    assert touch["exposed_inner_radius_mm"] == pytest.approx(9.525)
    assert touch["root_radius_mm"] == pytest.approx(24.0)
    assert touch["approach_start_z_mm"] > touch["approach_end_z_mm"]
    assert touch["approach_start_z_mm"] == pytest.approx(15.0)
    assert touch["assembly_swept_bounds_mm"] == pytest.approx(
        [-165.4, -125.4, 7.574, -114.6, -74.6, 63.0]
    )
    assert touch["collisions"] == []


def test_upper_body_and_signed_kerf_offset_setting_arithmetic(native_cases):
    _, upper = _detail(native_cases, "upper-body-zero")
    assert upper["status"] == "pass", upper
    assert upper["zero"]["status"] == "pass", upper["zero"]
    (touch,) = upper["zero"]["touches"]
    assert touch["plane_z_mm"] == 5.0 and touch["plane_normal_z"] == -1
    assert touch["body_face_z_mm"] == pytest.approx(4.95)
    assert touch["cutting_midplane_z_mm"] == pytest.approx(3.426)
    assert touch["approach_start_z_mm"] < touch["approach_end_z_mm"]
    assert touch["collisions"] == []
    _, offset = _detail(native_cases, "offset-zero")
    assert offset["status"] == "pass", offset
    assert offset["body_band_mm"] == pytest.approx([13.436, 16.484])
    assert offset["gauge_plane_z_mm"] == pytest.approx(59.96)
    assert offset["zero"]["status"] == "pass", offset["zero"]
    (shifted,) = offset["zero"]["touches"]
    assert shifted["cutting_midplane_z_mm"] == pytest.approx(11.614)
    assert shifted["body_face_z_mm"] == pytest.approx(10.05)


def test_from_below_local_clearance_does_not_certify_lower_stop_reachability(
    native_cases, monkeypatch
):
    from test_envelope_m5 import measured
    from test_mounted_saw_limits import mounted_bundle

    from prechips.rules import envelope

    _, saw = _detail(native_cases, "upper-body-zero")
    assert saw["zero"]["status"] == "pass", saw["zero"]
    assert saw["spindle_nose_bounds_mm"][2] == pytest.approx(4.0)
    data, evidence = mounted_bundle(monkeypatch)
    evidence.clear()
    evidence.update(deepcopy(saw))
    setup = data.plan["setups"][0]
    data.plan["stock"].update(length_mm=40, section_mm=[12.7, 30])
    setup["stock_state"].update(top_z=30, bottom_z=0)
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = measured(0)
    data.inventory["fixtures"]["parallel"]["height_mm"] = measured(0)
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_min_mm"] = measured(5)
    row = envelope.evaluate(data)[0]
    assert row.status == "error", row.sentence
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"][0] == pytest.approx(4)
    # This same locally clear from-below motion is not categorically forbidden:
    # a measured raised fixture moves the whole pose above the lower stop.
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = measured(10)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"][0] == pytest.approx(14)


def test_missing_touch_does_not_invent_calibration_extents(native_cases):
    _, saw = _detail(native_cases, "missing-zero")
    assert saw["zero"]["status"] == "unknown"
    assert saw["axis_path_bounds_mm"] == pytest.approx([-35.0, -60.0, 15.0, 75.0, -10.541, 128.0])
    assert saw["spindle_nose_bounds_mm"] == pytest.approx(
        [-35.0, -60.0, 63.0, 75.0, -10.541, 128.0]
    )


@pytest.mark.parametrize(
    "case,status",
    [
        ("missing-zero", "unknown"),
        ("unknown-spindle-zero", "unknown"),
        ("running-zero", "error"),
        ("flange-zero", "error"),
        ("root-zero", "error"),
        ("wrong-plane-zero", "error"),
        ("wrong-normal-zero", "error"),
        ("broad-stock-top-zero", "error"),
    ],
)
def test_zero_geometry_and_spindle_state_are_independent_of_cut_geometry(
    native_cases, case, status
):
    detail, saw = _detail(native_cases, case)
    assert saw["status"] == "pass", saw
    assert saw["engagement"]["status"] == "pass", saw["engagement"]
    assert saw["removed_kerf_volume_mm3"] == pytest.approx(1612.9)
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    zero = saw["zero"]
    assert zero["status"] == status, zero
    assert zero["reasons"]
    if case == "broad-stock-top-zero":
        (touch,) = zero["touches"]
        assert touch["plane_z_mm"] == 30.0
        assert touch["contact_radius_mm"] == pytest.approx(22.0)
        assert any(
            hit["obstacle"] == "stock" and hit["volume_mm3"] > 0.0 for hit in touch["collisions"]
        ), touch


def test_finite_fixture_minimum_replaces_the_all_holding_kerf_plane(native_cases):
    _, saw = _detail(native_cases, "finite-rear-post")
    proof = saw["fixture_clearance"]
    assert proof["status"] == "complete", proof
    assert proof["source"] == "finite_occupied_sweeps"
    assert proof["scope"] == "machining_trajectory" and proof["frame"] == "setup"
    assert proof["model"] == "finite_disk_v1"
    binding = proof["binding"]
    assert binding["setup"] == "S1" and binding["op"] == "S1:10"
    assert len(binding["step_sha256"]) == len(binding["request_sha256"]) == 64
    # The actual lower flange is 1 mm above the lower jaw. The infinite kerf plane
    # would instead claim 0 to rear-post, which lies beyond every finite component.
    near = proof["minimum"]
    assert near["mm"] == pytest.approx(1.0, abs=1e-6)
    assert near["tag"] == "lower-front-jaw"
    assert near["component"] == "arbor:lower-flange"
    assert (near["move_index"], near["mode"], near["stage"]) == (0, "cut", "cut")
    assert near["from_mm"][2] == pytest.approx(11.0)
    assert near["to_mm"][2] == pytest.approx(10.0)
    assert math.dist(near["from_mm"], near["to_mm"]) == pytest.approx(near["mm"])
    scene = native_cases["finite-rear-post"]["setups"]["S1"]["render_scene"]
    cut = scene["closest_cut"]
    assert cut is not None and scene["cut_clearances"] == []
    for key in ("mm", "from_mm", "to_mm"):
        assert cut[key] == pytest.approx(near[key], abs=1e-6)
    for key in ("tag", "component", "move_index", "mode", "stage"):
        assert cut[key] == near[key]
    assert cut["blade"] is True and cut["op"] == "10"
    assert cut["binding"] == binding and cut["scope"] == "machining_trajectory"
    assert sum("closest_cut" in panel["annotations"] for panel in scene["print_panels"]) == 1


@pytest.mark.parametrize(
    "case,tag,component,index,stage,mm,near,far",
    [
        (
            "pre-cut-distance",
            "pre-cut-stop",
            "blade_cutting",
            0,
            "pre_cut",
            0.25,
            [-60.4, -50.0, 16.0],
            [-60.65, -50.0, 16.0],
        ),
        (
            "withdrawal-distance",
            "withdrawal-stop",
            "blade_cutting",
            1,
            "post_cut",
            0.6,
            [100.4, -50.0, 16.0],
            [101.0, -50.0, 16.0],
        ),
        (
            "lift-distance",
            "lift-stop",
            "arbor:nose",
            2,
            "post_cut",
            0.25,
            [90.875, -60.0, 111.0],
            [91.125, -60.0, 111.0],
        ),
    ],
)
def test_fixture_distance_includes_clear_and_arbor_sweeps(
    native_cases, case, tag, component, index, stage, mm, near, far
):
    _, saw = _detail(native_cases, case)
    proof = saw["fixture_clearance"]
    assert proof["status"] == "complete", proof
    minimum = proof["minimum"]
    assert minimum["mm"] == pytest.approx(mm, abs=1e-6)
    assert minimum["tag"] == tag and minimum["component"] == component
    assert (minimum["move_index"], minimum["mode"], minimum["stage"]) == (index, "clear", stage)
    assert minimum["from_mm"] == pytest.approx(near, abs=1e-6)
    assert minimum["to_mm"] == pytest.approx(far, abs=1e-6)
    assert math.dist(minimum["from_mm"], minimum["to_mm"]) == pytest.approx(mm, abs=1e-6)
    rows = proof["sweeps"]
    moves = 4 if case == "pre-cut-distance" else 3
    components = {
        "blade_cutting",
        "blade_body",
        "arbor:lower-flange",
        "arbor:upper-flange",
        "arbor:pilot",
        "arbor:stem",
        "arbor:nose",
    }
    assert len(rows) == proof["expected_sweeps"] == len(components) * moves
    assert {(row["component"], row["move_index"]) for row in rows} == {
        (component, move) for component in components for move in range(moves)
    }
    assert all(row["tested_fixtures"] == len(proof["scene"]) for row in rows)
    assert all(row["move_index"] >= 0 and row["mode"] != "calibration" for row in rows)
    assert not {"stock", "child:lower", "child:upper"} & {item["tag"] for item in proof["scene"]}
    cut = native_cases[case]["setups"]["S1"]["render_scene"]["closest_cut"]
    assert cut["mm"] == pytest.approx(mm, abs=1e-6) and cut["component"] == component
    assert cut["stage"] == stage and cut["move_index"] == index


def test_native_zero_distance_is_not_replaced_with_a_positive_clearance(native_cases):
    _, saw = _detail(native_cases, "mid-sweep-obstacle")
    assert saw["status"] == "error", saw
    # The stop is wholly inside both occupied sweeps. A CompSolid's positive
    # boundary-to-boundary distance must not replace their actual shared material.
    hits = [
        hit
        for hit in saw["collisions"]
        if hit["obstacle"] == "mid-sweep-stop" and hit["move_index"] == 0
    ]
    assert {hit["component"] for hit in hits} == {"blade_cutting", "blade_body"}
    assert all(hit["volume_mm3"] == pytest.approx(4.0, abs=1e-6) for hit in hits)
    proof = saw["fixture_clearance"]
    assert proof["status"] == "complete", proof
    near = proof["minimum"]
    assert near["mm"] == 0.0 and near["tag"] == "mid-sweep-stop"
    assert near["component"] == "blade_cutting" and near["stage"] == "cut"
    assert near["from_mm"] == pytest.approx(near["to_mm"], abs=1e-6)
    rows = [
        row
        for row in proof["sweeps"]
        if row["move_index"] == 0 and row["component"] in {"blade_cutting", "blade_body"}
    ]
    assert len(rows) == 2
    for row in rows:
        minimum = row["minimum"]
        assert minimum["mm"] == 0.0 and minimum["tag"] == "mid-sweep-stop"
        assert minimum["from_mm"] == pytest.approx(minimum["to_mm"], abs=1e-6)
    cut = native_cases["mid-sweep-obstacle"]["setups"]["S1"]["render_scene"]["closest_cut"]
    assert cut["mm"] == 0.0 and cut["tag"] == "mid-sweep-stop"


@pytest.mark.parametrize(
    "case",
    ["scene-debt", "incomplete-envelope", "missing-envelope-component", "diagonal-clear"],
)
def test_incomplete_finite_scene_or_cycle_never_falls_back_to_plane_distance(native_cases, case):
    _, saw = _detail(native_cases, case)
    proof = saw["fixture_clearance"]
    assert proof["status"] == "unknown" and proof["minimum"] == "unknown", proof
    assert proof["reasons"]
    assert native_cases[case]["setups"]["S1"]["render_scene"]["closest_cut"] is None


def test_calibration_contact_does_not_replace_machining_cycle_minimum(native_cases):
    _, saw = _detail(native_cases, "positive")
    proof = saw["fixture_clearance"]
    assert proof["minimum"]["mm"] == pytest.approx(1.0)
    assert saw["zero"]["touches"][0]["body_face_z_mm"] - 10.0 == pytest.approx(0.05)
    assert all(row["mode"] in {"cut", "clear"} for row in proof["sweeps"])
    assert (
        proof["binding"]["request_sha256"]
        != _detail(native_cases, "finite-rear-post")[1]["fixture_clearance"]["binding"][
            "request_sha256"
        ]
    )


_ZERO_STAGES = r"""
import importlib.util
import json
import os
import sys
from copy import deepcopy
from types import SimpleNamespace
import FreeCAD
import Part

directory = sys.argv[sys.argv.index("--") + 1]
source = os.environ["MOUNTED_SAW_KERNEL_SOURCE"]
sys.path.insert(0, os.path.dirname(source))
spec = importlib.util.spec_from_file_location("mounted_stage_job", source)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
V = FreeCAD.Vector
with open(directory + "/cases.json", encoding="utf-8") as handle:
    payload = json.load(handle)
answers = {}
for name, case in payload["cases"].items():
    base = Part.makeBox(40, 12.7, 30)
    boss = Part.makeBox(4, 4, 55, V(-142, -102, 0))
    arriving = base if case.get("clear_arrival") else Part.makeCompound([base, boss])
    unrelated = Part.makeBox(1, 1, 1, V(39, 11.7, 29))
    after_b = (base if case.get("clear_after_b") else arriving).cut(unrelated)
    after_c = base.cut(unrelated)
    ops = [
        {"subject": "S1:B", "do": "mill"},
        {"subject": "S1:C", "do": "mill"},
        {"subject": "S1:D", "do": "cut_off", "mounted_saw": deepcopy(payload["mounted"])},
    ]
    ledger = [
        {"subject": op["subject"], "do": op["do"], "effect": "native"} for op in ops
    ]
    if case.get("metadata", True):
        ledger.insert(0, {"subject": "S1:A", "do": "inspect", "effect": "metadata"})
    if case.get("unmodeled"):
        ledger[0].update(do="file", effect="unmodeled")
    native_setup = {"id": "S1", "ops": ops, "preservation_ledger": ledger}
    if case.get("missing_ledger"):
        native_setup.pop("preservation_ledger")
    pad = Part.makeBox(2, 2, 5, V(-119, -101, 5))
    fixtures = [{"name": "setting-pad", "envelope": pad}]
    if "obstacle_at" in case:
        fixtures.append({
            "name": "tall-calibration-obstacle",
            "envelope": Part.makeBox(4, 4, 500, V(*case["obstacle_at"])),
        })
    if "nose_dia_mm" in case:
        ops[-1]["mounted_saw"]["arbor"]["components"][-1]["dia_mm"] = case["nose_dia_mm"]
    setup = SimpleNamespace(
        setup=native_setup, ops=ops, part=arriving,
        cuts={
            id(ops[0]): (arriving, after_b, case.get("prior_reason")),
            id(ops[1]): (after_b, after_c, None),
        },
        stopped_cut=id(ops[0]) if case.get("stopped") else None,
        stock_reason="arriving stock unresolved" if case.get("unknown_arrival") else None,
        arriving_thread_regions=[{}] if case.get("bounded_arrival") else [],
        thread_regions=[{}] if case.get("bounded_touch") else [],
        fixture=fixtures,
        fixture_ready=True, fixture_debts=[], fixture_gaps=[], undrawn=[], fixture_possible=[],
        _subject=lambda op: op["subject"], owner=SimpleNamespace(job={}),
    )
    touch = ops[-1]["mounted_saw"]["zero"]["touches"][0]
    touch["position"] = case.get("position", 2)
    saw = job._FiniteSaw(setup, ops[-1], after_c)
    assembly = saw._assembly()
    assert assembly and not saw.reasons and not saw.errors, (saw.reasons, saw.errors)
    answers[name] = saw._zero(assembly)
with open(directory + "/answers.json", "w", encoding="utf-8") as handle:
    json.dump(answers, handle)
"""


@pytest.fixture(scope="module")
def native_zero_stages(tmp_path_factory, freecad_kernel):
    """Real stock/contact/sweep proofs, isolated from unrelated full-job geometry."""
    directory = tmp_path_factory.mktemp("mounted-zero-stages")
    cases = {
        "filtered": {},
        "unfiltered": {"metadata": False, "position": 1},
        "filtered-clear": {"clear_after_b": True},
        "unfiltered-clear": {"metadata": False, "position": 1, "clear_after_b": True},
        "initial": {"position": 0},
        "initial-clear": {"position": 0, "clear_arrival": True},
        "metadata-only": {"position": 1},
        "metadata-only-clear": {"position": 1, "clear_arrival": True},
        "before-saw": {"position": 3},
        "remote-tall": {"position": 0, "clear_arrival": True, "obstacle_at": [-100, -102, 0]},
        "column-tall": {"position": 0, "clear_arrival": True, "obstacle_at": [-142, -102, 0]},
        "outer-nose-tall": {
            "position": 0,
            "clear_arrival": True,
            "obstacle_at": [-110, -102, 0],
            "nose_dia_mm": 70,
        },
        "unmodeled": {"unmodeled": True},
        "missing-ledger": {"missing_ledger": True},
        "future": {"position": 4},
        "stopped": {"stopped": True},
        "unresolved-prior": {"position": 3, "prior_reason": "prior cut was not derived"},
        "bounded-arrival": {"position": 0, "bounded_arrival": True},
        "bounded-touch": {"bounded_touch": True},
        "unknown-arrival": {"position": 0, "unknown_arrival": True},
    }
    (directory / "cases.json").write_text(
        json.dumps({"mounted": _mounted(), "cases": cases}), encoding="utf-8"
    )
    script = directory / "probe.py"
    script.write_text(_ZERO_STAGES, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        env={**os.environ, "MOUNTED_SAW_KERNEL_SOURCE": str(ENGINE)},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    answers = directory / "answers.json"
    assert answers.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(answers.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", ["filtered", "unfiltered", "initial", "metadata-only"])
def test_mounted_touch_sweeps_stock_at_its_authored_boundary(native_zero_stages, case):
    zero = native_zero_stages[case]
    assert zero["status"] == "error", zero
    assert zero["reasons"] == ["complete assembly collides during the axial calibration approach"]
    touch = zero["touches"][0]
    assert touch["contact_radius_mm"] == pytest.approx(22)
    assert touch["approach_start_z_mm"] == pytest.approx(60)
    assert {collision["component"] for collision in touch["collisions"]} == {
        "arbor:lower-flange",
        "arbor:upper-flange",
        "arbor:pilot",
        "arbor:stem",
    }
    assert all(collision["obstacle"] == "stock" for collision in touch["collisions"])
    assert all(collision["volume_mm3"] > 600 for collision in touch["collisions"])


@pytest.mark.parametrize(
    "case",
    ["filtered-clear", "unfiltered-clear", "initial-clear", "metadata-only-clear", "before-saw"],
)
def test_mounted_touch_keeps_valid_clear_and_initial_stock_proofs(native_zero_stages, case):
    zero = native_zero_stages[case]
    assert zero["status"] == "pass", zero
    assert zero["reasons"] == []
    assert zero["touches"][0]["collisions"] == []
    assert zero["touches"][0]["approach_start_z_mm"] == pytest.approx(15)


def test_remote_tall_obstacle_does_not_raise_the_local_calibration_start(native_zero_stages):
    zero = native_zero_stages["remote-tall"]
    assert zero["status"] == "pass", zero
    touch = zero["touches"][0]
    assert touch["approach_start_z_mm"] == pytest.approx(15)
    assert touch["assembly_swept_bounds_mm"][5] == pytest.approx(63)
    assert touch["collisions"] == []


@pytest.mark.parametrize("case", ["column-tall", "outer-nose-tall"])
def test_calibration_column_keeps_tall_obstacles_for_every_assembly_component(
    native_zero_stages, case
):
    zero = native_zero_stages[case]
    assert zero["status"] == "error", zero
    touch = zero["touches"][0]
    assert touch["approach_start_z_mm"] == pytest.approx(505)
    hits = [
        collision
        for collision in touch["collisions"]
        if collision["obstacle"] == "tall-calibration-obstacle"
    ]
    assert hits, touch
    assert all(collision["volume_mm3"] > 0 for collision in hits)
    if case == "outer-nose-tall":
        assert any(collision["component"] == "arbor:nose" for collision in hits)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("unmodeled", "unmodeled preceding bench step"),
        ("missing-ledger", "authored operation ledger is missing"),
        ("future", "future operation boundary"),
        ("stopped", "stock at the calibration touch is unresolved"),
        ("unresolved-prior", "stock at the calibration touch is unresolved"),
        ("bounded-arrival", "bounded thread material"),
        ("bounded-touch", "bounded thread material"),
        ("unknown-arrival", "arriving stock unresolved"),
    ],
)
def test_mounted_touch_refuses_unproved_material_boundaries(native_zero_stages, case, reason):
    zero = native_zero_stages[case]
    assert zero["status"] == "unknown", zero
    assert any(reason in item for item in zero["reasons"])
    assert zero["touches"][0]["collisions"] == []
