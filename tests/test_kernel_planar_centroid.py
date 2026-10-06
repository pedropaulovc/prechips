"""A +Z planar floor that fits wholly inside the cutter disc stands on one derived pose.

The pose is the area centroid of the axes whose disc covers the face, a certified single
covering axis, or the shared centre of concave rising R-arc walls; it is never searched.
A face no disc covers, a rough leave or any other rising wall keeps the surface samples;
an undecidable outer contour drops only that floor's poses and leaves the op unknown
while other faces' certain hits stay. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise

_AUTHOR = r"""
import math
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape, merge=True):
    shape = shape.removeSplitter() if merge else shape
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

def arc(a, m, b, z):
    return Part.Arc(V(a[0], a[1], z), V(m[0], m[1], z), V(b[0], b[1], z)).toShape()

plate = Part.makeBox(40, 30, 10)
block = Part.makeBox(60, 40, 20)
# 4 x 2 pad, top z=14, about (20, 15): its circumradius is sqrt(5).
save("pad", plate.fuse(Part.makeBox(4, 2, 4, V(18, 14, 10))))
# The same pad with an r0.3 pin rising 2 from its top: an island wall on the face.
save("pad-pin", plate.fuse(Part.makeBox(4, 2, 4, V(18, 14, 10))).fuse(
    Part.makeCylinder(0.3, 2, V(20, 15, 14))))
# An r2 pad (top z=14) inside an r2.3 pocket of a block topped at z=20.
save("tight", Part.makeBox(40, 30, 20).cut(Part.makeCylinder(2.3, 11, V(20, 15, 10))).fuse(
    Part.makeCylinder(2, 4, V(20, 15, 10))))
# R3 pocket floors (z=14) about (30, 20): one wall face, two half-arc wall faces, and an
# r3.0005 circle that no R3 disc covers.
save("circle", block.cut(Part.makeCylinder(3, 7, V(30, 20, 14))))
halves = Part.Wire([arc((33, 20), (30, 23), (27, 20), 14), arc((27, 20), (30, 17), (33, 20), 14)])
save("split-circle", block.cut(Part.Face(halves).extrude(V(0, 0, 7))), merge=False)
save("near-circle", block.cut(Part.makeCylinder(3.0005, 7, V(30, 20, 14))))
# Lens pocket floor (z=14): R3 arcs about (29.5, 20) and (30.5, 20) that an R3 disc covers.
lens = Part.makeCylinder(3, 7, V(29.5, 20, 14)).common(Part.makeCylinder(3, 7, V(30.5, 20, 14)))
save("lens", block.cut(lens))
# Walls the tool cannot clear, though an R3 disc covers the floor: an R2.9995 circle, and
# R3 arcs about centres 5e-4 apart.
save("small-circle", block.cut(Part.makeCylinder(2.9995, 7, V(30, 20, 14))))
save("close-lens", block.cut(Part.makeCylinder(3, 7, V(29.99975, 20, 14)).common(
    Part.makeCylinder(3, 7, V(30.00025, 20, 14)))))
# An R2.5 pocket floor (z=14) at (15, 20) and a 3 x 0.8 B-spline pad top (z=24).
spline = Part.BSplineCurve()
spline.interpolate([V(38.5, 20, 20), V(40, 20.8, 20), V(41.5, 20, 20)])
top = Part.Wire([spline.toShape(), Part.LineSegment(V(41.5, 20, 20), V(38.5, 20, 20)).toShape()])
save("pocket-and-spline", block.cut(Part.makeCylinder(2.5, 7, V(15, 20, 14))).fuse(
    Part.Face(top).extrude(V(0, 0, 4))))
"""
_AUTHORED = 10
PAD = ((10, 5, 14), (30, 25, 14))
SHORT = {"pad", "pad-pin", "tight"}  # 40 mm long solids; the rest are 60 mm blocks
POCKET = ((26, 16, 14), (34, 24, 14))
ROOT5 = math.sqrt(5)
LEAVE = 0.2
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 40.0,
    "section_mm": [30.0, 24.0],
}
ABOVE_PAD = {"x": [16.0, 24.0], "y": [11.0, 19.0], "z": [14.0, 24.0]}


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("planar-centroid-solids")
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


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _floor(engine, step, boxes, radius, op=None):
    refs = [ref for lo, hi in boxes for ref in engine.refs(step, lo, hi, kind="Plane")]
    assert len(refs) == len(boxes)
    op = op or _op("S1:10", "floor", radius, 10.0, 20.0)
    centre = 20.0 if step.stem in SHORT else 30.0
    job = engine.job(step, {"floor": refs}, [_setup([op], _vise(5.0, centre=centre))])
    return engine.run(job)["ops"]["S1:10"]


@pytest.mark.parametrize(
    "radius, poses",
    [(3.0, 1), (ROOT5 + 1e-3, 1), (ROOT5, 1), (ROOT5 - 1e-6, None)],
)
def test_pad_inside_the_cutter_has_one_pose_down_to_its_exact_circumradius(
    engine, solids, radius, poses
):
    # At R = sqrt(5) the only covering axis is the certified circumcentre; a hair less
    # and no disc covers the pad, so it keeps every surface sample.
    detail = _floor(engine, solids["pad"], [PAD], radius)
    if poses is None:
        assert detail["sample_count"] > 1, detail
    else:
        assert detail["sample_count"] == poses, detail
    assert detail["tool_hits"] == 0, detail


def test_the_one_pose_reports_the_real_pocket_wall_hit_once(engine, solids):
    detail = _floor(engine, solids["tight"], [PAD], 2.5)
    assert detail["sample_count"] == 1 and detail["tool_hits"] == 1, detail
    assert detail["obstacles"]["tool"] == ["part"], detail


@pytest.mark.parametrize("name", ["circle", "split-circle"])
def test_pocket_floor_of_the_cutter_radius_stands_on_its_wall_centre(engine, solids, name):
    detail = _floor(engine, solids[name], [POCKET], 3.0)
    assert detail["sample_count"] == 1 and detail["tool_hits"] == 0, detail


@pytest.mark.parametrize(
    "name, boxes, radius",
    [
        # A 0.0005 mm larger circle: no STOCK_TOL widening of the cover test.
        ("near-circle", [POCKET], 3.0),
        # The face fits the disc, but its walls are R arcs about two centres.
        ("lens", [POCKET], 3.0),
        # An island pin's foot is a rising wall on the pad, whatever the centroid sees.
        ("pad-pin", [PAD], 3.0),
        # Coincident within STOCK_TOL is no waiver of each wall's own tangent bound.
        ("small-circle", [POCKET], 3.0),
        ("close-lens", [POCKET], 3.0),
    ],
)
def test_floor_whose_walls_admit_no_covering_axis_keeps_its_samples(
    engine, solids, name, boxes, radius
):
    detail = _floor(engine, solids[name], boxes, radius)
    assert detail["sample_count"] > 1, detail


def test_rough_leave_keeps_a_walled_floor_on_samples_but_not_an_open_one(engine, solids):
    rough = {**_op("S1:10", "floor", 3.0, 10.0, 20.0), "do": "rough_face"}
    rough["rough_allowance_mm"] = LEAVE
    walled = _floor(engine, solids["circle"], [POCKET], 3.0, op=rough)
    assert walled["sample_count"] > 1 and walled["tool_hits"] > 0, walled
    open_pad = _floor(engine, solids["pad"], [PAD], 3.0, op=rough)
    assert open_pad["sample_count"] == 1 and open_pad["tool_hits"] == 0, open_pad


def test_undecidable_floor_leaves_the_op_unknown_with_other_faces_certain_hits(engine, solids):
    step = solids["pocket-and-spline"]
    detail = _floor(engine, step, [((12, 17, 14), (18, 23, 14)), ((38, 19, 24), (42, 22, 24))], 3.0)
    assert detail["sample_count"] == "unknown" and detail["tool_hits"] == "unknown", detail
    assert "floor tool pose is undefined" in detail["reasons"]["tool_hits"], detail
    assert "BSplineCurve" in detail["reasons"]["tool_hits"], detail
    # The R3 cutter in the R2.5 pocket still certainly hits its wall.
    assert detail["min_hits"]["tool"] > 0 and detail["obstacles"]["tool"] == ["part"], detail
    assert detail["hit_refs"]["tool"], detail


def test_earlier_clearance_frees_the_one_pose_flute_never_its_holder(engine, solids):
    step = solids["pad"]
    refs = engine.refs(step, *PAD, kind="Plane")
    clear = {**_op("S1:10", "floor", 3.0, 25.0, 30.0), "stock_removal_bounds": ABOVE_PAD}
    finish = _op("S1:20", "floor", 3.0, 5.0, 6.0, holder_radius=2.9)
    hold = _vise(5.0, centre=20.0)

    def job(ops):
        setups = [_setup(ops, hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
        return engine.job(step, {"floor": refs}, setups, stock=BLANK)

    forward, backward = engine.run(
        {
            "jobs": [
                job([clear, finish]),
                job([{**finish, "subject": "S1:10"}, {**clear, "subject": "S1:20"}]),
            ]
        }
    )["results"]
    after, before = forward["ops"]["S1:20"], backward["ops"]["S1:10"]
    assert after["sample_count"] == 1 and after["tool_hits"] == 0, after
    assert after["holder_hits"] == 1 and after["obstacles"]["holder"] == ["part"], after
    assert before["sample_count"] == 1 and before["tool_hits"] == 1, before
