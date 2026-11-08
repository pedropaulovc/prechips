"""A bounded single-point turn stops at the nose's leading extreme, not its centre.

These probes import the real native kernel in FreeCAD and measure OCC solids.  The
circle and volume oracles below do not use the kernel's torus construction.
"""

import ast
import json
import math
import os
import subprocess
from pathlib import Path

import pytest

from prechips import kernel

_RADIUS = 5.09397
_NOSE = 0.4

_PROBE = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("kernel_under_test", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
V = FreeCAD.Vector
args = json.loads(os.environ["PROBE_ARGS"])
setup = job._Setup(None, {"id": "S1", "ops": []})
op = args["op"]
# Bounds are normalized by the caller, not by the motion helper.
low, high = sorted(args["bounds"])
motion, motion_reason = setup._turn_cylinder_motion(op, low, high)
keep, keep_reason = setup._turn_blend_keep(op, args["radius"], low, high)
result = {
    "motion": motion,
    "motion_reason": motion_reason,
    "keep_reason": keep_reason,
    "keep_none": keep is None,
}
if args.get("geometry"):
    radius = args["radius"]
    raw = Part.makeCylinder(radius + 1, high - low, V(0, 0, low))
    target = Part.makeCylinder(radius, high - low, V(0, 0, low))
    # Finite outside-target annulus: keep is EXCESS only, not the target core.
    annulus = raw.cut(target)
    removal = annulus if keep is None else annulus.cut(keep)
    after = raw.cut(removal)
    result.update({
        "keep_volume": 0 if keep is None else keep.Volume,
        "keep_core_overlap": 0 if keep is None else keep.common(target).Volume,
        "keep_outside_annulus": 0 if keep is None else keep.cut(annulus).Volume,
        "after_volume": after.Volume,
        "removed_volume": removal.Volume,
        "raw_volume": raw.Volume,
        "after_valid": after.isValid(),
        "keep_valid": keep is None or keep.isValid(),
        "sections": [],
    })
    for z in args["sections"]:
        plane = Part.makePlane(40, 40, V(-20, -20, z), V(0, 0, 1))
        section = after.common(plane)
        excess = 0 if keep is None else keep.common(plane).Area
        result["sections"].append({"z": z, "area": section.Area, "excess_area": excess})
with open(os.path.join(out, "probe.json"), "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


def _probe(tmp_path, freecad_kernel, **args):
    """Use the same real-kernel import protocol as test_kernel_contact_keys."""
    script = tmp_path / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(source), "PROBE_ARGS": json.dumps(args)},
    )
    report = tmp_path / "probe.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(report.read_text(encoding="utf-8"))


def _op(feed, low, high):
    return {
        "do": "rough_turn",
        "to_dia_mm": 2 * _RADIUS,
        "z_from": high if feed == -1 else low,
        "z_to": low if feed == -1 else high,
        "radius_mm": _NOSE,
        "feed_z": feed,
        "corners": 1,
    }


def _blend_radius(z, stop, feed):
    centre = stop - feed * _NOSE
    distance = abs(z - centre)
    return _RADIUS + _NOSE - math.sqrt(max(0, _NOSE**2 - distance**2))


def _excess_primitive(x):
    """Integral of pi * ((r + N - sqrt(N*N - x*x))**2 - r*r)."""
    n, r = _NOSE, _RADIUS
    root = math.sqrt(max(0, n * n - x * x))
    return math.pi * (
        (2 * r * n + 2 * n * n) * x - x**3 / 3 - (r + n) * (x * root + n * n * math.asin(x / n))
    )


def _assert_motion(found, low, high, feed):
    assert found["motion_reason"] is None
    motion = found["motion"]
    shift = -feed * _NOSE
    assert motion["nose_mm"] == pytest.approx(_NOSE)
    assert motion["against"] == -feed
    assert motion["centre_z_mm"] == pytest.approx([low + shift, high + shift])
    a, b = max(low, low + shift), min(high, high + shift)
    expected = [a, b] if b > a else []
    assert motion["contact_z_mm"] == pytest.approx(expected)
    stop = low if feed == -1 else high
    assert motion["stop_z_mm"] == pytest.approx(stop)
    assert motion["centre_stop_z_mm"] == pytest.approx(stop + shift)


@pytest.mark.parametrize("feed", [-1, 1], ids=["negative_feed", "positive_feed_mirror"])
@pytest.mark.parametrize("reverse_bounds", [False, True], ids=["ordered", "caller_normalized"])
def test_terminal_blend_is_exact_retained_excess_not_a_square_or_sharp_end(
    tmp_path, freecad_kernel, feed, reverse_bounds
):
    low, high = (-8.5, -7.0) if feed == -1 else (7.0, 8.5)
    sign = -feed
    sections = [sign * z for z in (-8.4, -8.3, -8.2, -8.0)]
    bounds = [high, low] if reverse_bounds else [low, high]
    found = _probe(
        tmp_path,
        freecad_kernel,
        op=_op(feed, low, high),
        bounds=bounds,
        radius=_RADIUS,
        geometry=True,
        sections=sections,
    )
    _assert_motion(found, low, high, feed)
    assert found["keep_reason"] is None
    assert not found["keep_none"]
    assert found["after_valid"] and found["keep_valid"]
    assert found["keep_core_overlap"] == pytest.approx(0, abs=1e-7)
    assert found["keep_outside_annulus"] == pytest.approx(0, abs=1e-7)
    expected_volume = _excess_primitive(_NOSE)
    assert found["keep_volume"] == pytest.approx(expected_volume, abs=1e-6)
    assert found["after_volume"] == pytest.approx(
        math.pi * _RADIUS**2 * (high - low) + expected_volume, abs=1e-6
    )
    assert found["removed_volume"] + found["after_volume"] == pytest.approx(
        found["raw_volume"], abs=1e-6
    )
    stop = low if feed == -1 else high
    for section, original_z in zip(found["sections"], (-8.4, -8.3, -8.2, -8.0), strict=True):
        radius = _blend_radius(section["z"], stop, feed) if original_z < -8.1 else _RADIUS
        assert section["area"] == pytest.approx(math.pi * radius**2, abs=1e-6)
        assert section["excess_area"] == pytest.approx(math.pi * (radius**2 - _RADIUS**2), abs=1e-6)
    # The retained part-off plane is inside the blend, and is genuinely oversize.
    assert found["sections"][1]["area"] > math.pi * _RADIUS**2 + 1
    assert found["sections"][-1]["excess_area"] == pytest.approx(0, abs=1e-7)


@pytest.mark.parametrize("feed", [-1, 1])
def test_real_overtravel_moves_the_blend_into_waste_before_the_kept_plane(
    tmp_path, freecad_kernel, feed
):
    low, high = (-9.1, -7.0) if feed == -1 else (7.0, 9.1)
    sign = -feed
    found = _probe(
        tmp_path,
        freecad_kernel,
        op=_op(feed, low, high),
        bounds=[low, high],
        radius=_RADIUS,
        geometry=True,
        sections=[sign * z for z in (-8.9, -8.5, -8.3, -8.0)],
    )
    _assert_motion(found, low, high, feed)
    assert found["keep_reason"] is None
    assert found["sections"][0]["excess_area"] > 1
    for section in found["sections"][1:]:
        assert section["area"] == pytest.approx(math.pi * _RADIUS**2, abs=1e-6)
        assert section["excess_area"] == pytest.approx(0, abs=1e-7)
    assert found["keep_volume"] == pytest.approx(_excess_primitive(_NOSE), abs=1e-6)


@pytest.mark.parametrize("feed", [-1, 1])
def test_short_window_has_no_full_radius_contact_and_only_a_truncated_blend(
    tmp_path, freecad_kernel, feed
):
    low, high = (-8.5, -8.3) if feed == -1 else (8.3, 8.5)
    sign = -feed
    found = _probe(
        tmp_path,
        freecad_kernel,
        op=_op(feed, low, high),
        bounds=[low, high],
        radius=_RADIUS,
        geometry=True,
        sections=[sign * z for z in (-8.45, -8.4, -8.35)],
    )
    _assert_motion(found, low, high, feed)
    assert found["motion"]["contact_z_mm"] == []
    assert found["keep_reason"] is None
    expected_volume = _excess_primitive(_NOSE) - _excess_primitive(_NOSE - (high - low))
    assert found["keep_volume"] == pytest.approx(expected_volume, abs=1e-6)
    stop = low if feed == -1 else high
    for section in found["sections"]:
        radius = _blend_radius(section["z"], stop, feed)
        assert radius > _RADIUS
        assert section["area"] == pytest.approx(math.pi * radius**2, abs=1e-6)
    assert found["keep_outside_annulus"] == pytest.approx(0, abs=1e-7)


@pytest.mark.parametrize(
    "field,value",
    [
        ("radius_mm", None),
        ("radius_mm", 0),
        ("radius_mm", "unknown"),
        ("feed_z", None),
        ("feed_z", 0),
        ("feed_z", "unknown"),
    ],
)
def test_unknown_nose_or_feed_is_explicit_not_a_sharp_cylinder(
    tmp_path, freecad_kernel, field, value
):
    op = _op(-1, -8.5, -7.0)
    op[field] = value
    found = _probe(
        tmp_path,
        freecad_kernel,
        op=op,
        bounds=[-8.5, -7.0],
        radius=_RADIUS,
    )
    assert found["motion"] is None
    assert found["keep_none"]
    assert isinstance(found["motion_reason"], str) and found["motion_reason"].strip()
    assert isinstance(found["keep_reason"], str) and found["keep_reason"].strip()


def test_blade_bypasses_single_point_motion_and_retained_blend(tmp_path, freecad_kernel):
    op = _op(-1, -8.5, -7.0)
    op.update(corners=2, blade_width_mm=2)
    found = _probe(
        tmp_path,
        freecad_kernel,
        op=op,
        bounds=[-8.5, -7.0],
        radius=_RADIUS,
        geometry=True,
        sections=[-8.3, -8.0],
    )
    assert found["motion"] is None
    assert found["motion_reason"] is None
    assert found["keep_none"] and found["keep_reason"] is None
    assert found["after_volume"] == pytest.approx(math.pi * _RADIUS**2 * 1.5, abs=1e-6)
    assert all(section["excess_area"] == 0 for section in found["sections"])


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((4.0, 20.0), True),
        ((4.1, 20.1), True),
        ((3.99, 20.0), False),  # protected core, never a blend-fitting permission
        ((4.5, 20.0), False),
        ((4.0, 19.9), False),
        ((4.0, 20.5), False),
    ],
)
def test_corner_fitting_permission_is_only_the_known_terminal_excess(point, expected):
    source = Path(kernel.__file__).with_name("freecad_job.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_turn_blend_sample"
    )
    function.decorator_list = []
    namespace = {"math": math, "PLANE_TOL": 1e-6}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    motion = {
        "nose_mm": 0.4,
        "against": 1,
        "centre_z_mm": [20.4, 40.4],
        "stop_z_mm": 20.0,
        "centre_stop_z_mm": 20.4,
    }
    assert namespace["_turn_blend_sample"](point, 4.0, motion) is expected
