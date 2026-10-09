"""Nearest covering floor axes against native straight and circular walls.

Circular pockets and exact two-radius grooves admit covering tangent axes.
Sharp line/arc or arc/arc corners that require a farther axis report the physical
wall collision instead of accepting an uncovered sample. Native corner probes
compare covering collisions with independently placed, noncovering clear axes;
public jobs attribute hits to the authored corner walls. FreeCAD-backed tests
run ``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import json
import math
import os
import subprocess
from pathlib import Path

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise
from test_kernel_planar_legal_centres import _AXIS_PROBE

from prechips import kernel

_AUTHOR = r"""
import math
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")
    shape.exportBrep(out + "/" + name + ".brep")

block = Part.makeBox(60, 40, 20)
# Circular pockets 6 deep (floor z=14) about (30, 20): R10, R3 and R2.5.
for name, radius in (("circle", 10.0), ("exact-circle", 3.0), ("small-circle", 2.5)):
    save(name, block.cut(Part.makeCylinder(radius, 7, V(30, 20, 14))))
# D pocket 6 deep: the R10 circle about (30, 20) cut by the chord x=24, which meets the
# arc at sharp concave corners (24, 12) and (24, 28).
d = Part.makeCylinder(10, 7, V(30, 20, 14)).common(Part.makeBox(20, 30, 7, V(24, 5, 14)))
save("d-pocket", block.cut(d))
# Lens pocket 6 deep: the overlap of R10 circles about (24, 19) and (36, 21), whose arcs
# meet at acute concave cusps near (31.3, 12.2) and (28.7, 27.8).
lens = Part.makeCylinder(10, 7, V(24, 19, 14)).common(Part.makeCylinder(10, 7, V(36, 21, 14)))
save("lens", block.cut(lens))
# Through groove 6 wide (y 17..23), floor z=12.
save("groove", block.cut(Part.makeBox(62, 6, 9, V(-1, 17, 12))))
# V pocket 6 deep, 40 degrees, tip (10, 20), with an r0.5 boss 6 tall on its bisector
# 4.086 from the tip, both turned 7 degrees about the tip. For R1.5 the two-wall tangent
# axis (R/sin 20 = 4.386 from the tip) lies inside the boss; axes past it clear.
half = math.radians(20.0)
wedge = Part.Face(Part.makePolygon([
    V(10, 20, 14), V(40, 20 - 30 * math.tan(half), 14), V(40, 20 + 30 * math.tan(half), 14),
    V(10, 20, 14),
])).extrude(V(0, 0, 7))
boss = Part.makeCylinder(0.5, 6, V(14.086, 20, 14))
for shape in (wedge, boss):
    shape.rotate(V(10, 20, 14), V(0, 0, 1), 7.0)
save("v-boss", block.cut(wedge).fuse(boss).removeSplitter())
# Plate 10 thick with a 1 mm rib 6 tall (y 19.5..20.5, x 10..50) standing on it.
plate = Part.makeBox(60, 40, 10)
save("rib", plate.fuse(Part.makeBox(40, 1, 6, V(10, 19.5, 10))).removeSplitter())
# The plate's 5x5 floor grid samples x 6..54 step 12, y 4..36 step 8. Square island
# x 31..41 y 21..31: the sample (30, 20) is past both walls' ends at its convex corner.
save("corner-island", plate.fuse(Part.makeBox(10, 10, 6, V(31, 21, 10))).removeSplitter())
# Island A (x 23.99..29.99, y from 19.9991) puts the sample (30, 20) 0.01 in front of its
# right wall and 0.01 past its bottom wall's end; B (x from 35.99) leaves a slot exactly
# 6 wide, which C closes at y 23.01.
save("partial-gap", plate.fuse([
    Part.makeBox(6, 30 - 19.9991, 6, V(23.99, 19.9991, 10)),
    Part.makeBox(6, 20, 6, V(35.99, 10, 10)),
    Part.makeBox(6, 30 - 23.01, 6, V(29.99, 23.01, 10)),
]).removeSplitter())
"""
_AUTHORED = 10

_CORNER_PROBE = (
    _AXIS_PROBE
    + r"""
result = {}
for name, point, radius, far in (
    ("v-boss", (10, 20, 14), 1.5,
        (10 + 8*math.cos(math.radians(7)), 20 + 8*math.sin(math.radians(7)))),
    ("partial-gap", (29.99, 23.01, 10), 3, (32.99, 20.01)),
):
    solid = read(name)
    floors = [face for face in solid.Faces
        if isinstance(face.Surface, Part.Plane)
        and abs(face.CenterOfMass.z - point[2]) < 1e-6
        and job._normal_at(face, face.CenterOfMass).z > .99]
    assert len(floors) == 1
    result[name] = axis(name, job._bbox(floors[0]), point, radius)
    result[name + "-far"] = {
        "displacement": math.hypot(far[0]-point[0], far[1]-point[1]),
        "collision_mm3": Part.makeCylinder(radius, 10,
            V(far[0], far[1], point[2] + job.LIFT)).common(solid).Volume,
    }
with open(out + "/corners.json", "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""
)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("curved-floor-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert len(paths) == _AUTHORED, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture(scope="module")
def native_corners(solids, freecad_kernel):
    directory = solids["v-boss"].parent
    script = directory / "corners.py"
    script.write_text(_CORNER_PROBE, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
        env={**os.environ, "KERNEL_SOURCE": str(Path(kernel.__file__).with_name("freecad_job.py"))},
    )
    report = directory / "corners.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(report.read_text(encoding="utf-8"))


def _assert_corner_collision(native, name, radius):
    chosen, far = native[name], native[name + "-far"]
    assert chosen["displacement"] <= radius + 1e-7, chosen
    assert chosen["collision_mm3"] > 1e-6, chosen
    assert far["displacement"] > radius, far
    assert far["collision_mm3"] == pytest.approx(0, abs=1e-8), far


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _floor_op(engine, step, lo, hi, radius):
    floor = engine.refs(step, lo, hi, kind="Plane")
    assert len(floor) == 1
    op = _op("S1:10", "floor", radius, 10.0, 20.0)
    job = engine.job(step, {"floor": floor}, [_setup([op], _vise(5.0, centre=30.0))])
    return floor, engine.run(job)["ops"]["S1:10"]


@pytest.mark.parametrize(
    "name, lo, hi",
    [
        # R10 circle: samples 1 and 2 mm inside the wall shift 2 and 1 mm toward the centre.
        ("circle", (20, 10, 14), (40, 30, 14)),
        # Circle exactly the cutter's size: every sample stands on the one centred axis.
        ("exact-circle", (27, 17, 14), (33, 23, 14)),
    ],
)
def test_samples_near_a_curved_pocket_wall_stand_tangent_inside_it(engine, solids, name, lo, hi):
    _, detail = _floor_op(engine, solids[name], lo, hi, 3.0)
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == [], detail


@pytest.mark.parametrize(
    "name, lo, hi",
    [
        ("d-pocket", (24, 10, 14), (40, 30, 14)),
        ("lens", (26, 12, 14), (34, 28, 14)),
    ],
)
def test_sharp_curved_pocket_corners_report_uncoverable_real_wall_hits(
    engine, solids, name, lo, hi
):
    _, detail = _floor_op(engine, solids[name], lo, hi, 3.0)
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert "tool_hits" not in detail["reasons"], detail
    assert detail["obstacles"]["tool"] == ["part"], detail


def test_groove_exactly_two_radii_wide_clears_both_walls(engine, solids):
    _, detail = _floor_op(engine, solids["groove"], (0, 17, 12), (60, 23, 12), 3.0)
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == [], detail


@pytest.mark.parametrize(
    "name, lo, hi, radius",
    [("small-circle", (27, 17, 14), (33, 23, 14), 3.0), ("groove", (0, 17, 12), (60, 23, 12), 3.5)],
)
def test_tool_wider_than_its_circle_or_gap_reports_the_real_wall_hit(
    engine, solids, name, lo, hi, radius
):
    step = solids[name]
    floor, detail = _floor_op(engine, step, lo, hi, radius)
    walls = set(engine.refs(step, (lo[0], lo[1], lo[2]), (hi[0], hi[1], 20))) - set(floor)
    assert walls
    hits = detail["tool_hits"]
    assert isinstance(hits, int) and hits > 0, detail
    assert "tool_hits" not in detail["reasons"]
    assert walls <= set(detail["hit_refs"]["tool"]), detail


def test_a_sharp_v_corner_and_its_island_cannot_gain_a_noncovering_clear_axis(
    engine, solids, native_corners
):
    _assert_corner_collision(native_corners, "v-boss", 1.5)
    step = solids["v-boss"]
    angle = math.radians(7)
    wall_refs = set()
    for sign in (-1, 1):
        dx, dy = 30, sign * 30 * math.tan(math.radians(20))
        x = 10 + dx * math.cos(angle) - dy * math.sin(angle)
        y = 20 + dx * math.sin(angle) + dy * math.cos(angle)
        refs = engine.refs(step, (10, min(20, y), 14), (x, max(20, y), 20), kind="Plane")
        assert len(refs) == 1
        wall_refs.update(refs)
    _, detail = _floor_op(engine, step, (5, 2, 14), (45, 38, 14), 1.5)
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert "tool_hits" not in detail["reasons"], detail
    assert detail["obstacles"]["tool"] == ["part"], detail
    assert wall_refs <= set(detail["hit_refs"]["tool"]), detail


def test_plate_samples_beside_a_thin_rib_stand_clear_of_its_near_face_only(engine, solids):
    # A sample at one face's foot lies behind the rib's other face 1 mm away: it is not
    # inside material, so that far face does not bound it and the near face alone does.
    _, detail = _floor_op(engine, solids["rib"], (0, 0, 10), (60, 40, 10), 3.0)
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == [], detail


def test_plate_sample_past_a_square_islands_convex_corner_stands_clear_of_it(engine, solids):
    # The sample (30, 20) is 1.41 mm from the corner (31, 21) and past both walls' ends:
    # neither wall's line bounds it, the corner does, so it moves straight away to tangency.
    _, detail = _floor_op(engine, solids["corner-island"], (0, 0, 10), (60, 40, 10), 3.0)
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == [], detail


def test_an_exact_width_slot_closed_by_an_island_retains_its_uncoverable_corner_hit(
    engine, solids, native_corners
):
    _assert_corner_collision(native_corners, "partial-gap", 3)
    step = solids["partial-gap"]
    cap = engine.refs(step, (29.99, 23.01, 10), (35.99, 23.01, 16), kind="Plane")
    assert len(cap) == 1
    _, detail = _floor_op(engine, step, (0, 0, 10), (60, 40, 10), 3.0)
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert "tool_hits" not in detail["reasons"], detail
    assert detail["obstacles"]["tool"] == ["part"], detail
    assert set(cap) <= set(detail["hit_refs"]["tool"]), detail
