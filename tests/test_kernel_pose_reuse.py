"""Reused pose outcomes keep every count and ref; region culls keep containment answers.

Engine cases run ``freecad_job.py`` on solids authored here and read only its JSON. Cull
cases load the engine under ``freecadcmd`` and query the culls of a real stock and of
that stock after a removal, on real B-reps. FreeCAD-backed tests skip without
``freecadcmd``.
"""

import json
import math
import os
import subprocess

import pytest
from test_kernel_geometry import ENGINE, Engine, _op, _setup, _vise

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

# 60x40x10 plate, its top split at x 29..31 by a 2 mm deep groove: an R2 boss 6 tall
# at (25, 20) on the left top and one at (40, 20) on the right top.
plate = Part.makeBox(60, 40, 10).fuse(Part.makeCylinder(2, 6, V(25, 20, 10)))
plate = plate.fuse(Part.makeCylinder(2, 6, V(40, 20, 10))).removeSplitter()
save("bosses", plate.cut(Part.makeBox(2, 42, 3, V(29, -1, 8))))
# 60x40x20 block, R4 opening from the top to z=2, and a D1.6 pin from its floor to z=25.
opening = Part.makeBox(60, 40, 20).cut(Part.makeCylinder(4, 19, V(30, 20, 2)))
save("pin-bore", opening.fuse(Part.makeCylinder(0.8, 23, V(31.8, 20, 2))).removeSplitter())
"""

_CULLED = r"""
import importlib.util
import json
import os
import sys
import FreeCAD, Part
V = FreeCAD.Vector
target = sys.argv[sys.argv.index("--") + 1] + "/culled.json"
spec = importlib.util.spec_from_file_location("culled_engine", os.environ["CULLED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

# 60x60x20 stock stepped down to z=10 wherever x > 30 or y > 30: one L-shaped floor
# whose box spans the raised 30x30 corner. The removal takes the stock under the floor's
# y > 30 leg, leaving that floor a 30x60 rectangle clear of the raised corner.
loop = [V(30, -1, 10), V(61, -1, 10), V(61, 61, 10), V(-1, 61, 10), V(-1, 30, 10), V(30, 30, 10)]
air = Part.Face(Part.makePolygon(loop + loop[:1])).extrude(V(0, 0, 11))
stock = Part.makeBox(60, 60, 20).cut(air).removeSplitter()
region_shape = stock.cut(stock.common(Part.makeBox(31, 31, 11, V(-1, 30, -1))))

def square(x, y, z):
    steps = ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5))
    corners = [V(x + dx, y + dy, z) for dx, dy in steps]
    return Part.Face(Part.makePolygon(corners + corners[:1]))

def answer(shape, faces=()):
    if shape is None:
        return None
    distances = [engine._distance(shape, face)[0] for face in faces]
    return {"type": shape.ShapeType, "volume": shape.Volume, "distances": distances}

rows = {}
corner = (15.0, 15.0, 2.0, 5.0, 15.0)
faces = [square(15, 15, 10)]  # a finished face buried in the raised corner
rows["corner"] = {
    "stock": answer(engine._Culled(stock).common(*corner), faces),
    "region": answer(engine._Culled(region_shape).common(*corner), faces),
}
leg = (45.0, 15.0, 2.0, 5.0, 15.0)
floor = [
    f for f in region_shape.Faces
    if f.BoundBox.XMin > 29 and f.BoundBox.ZMin > 10 - 1e-6 and f.BoundBox.ZMax < 10 + 1e-6
]
assert len(floor) == 1
faces = [square(45, 15, 7), floor[0]]  # buried below the floor, and the floor itself
rows["leg"] = answer(engine._Culled(region_shape).common(*leg), faces)
rows["straddle"] = answer(engine._Culled(region_shape).common(15.0, 30.0, 2.0, 5.0, 15.0))
rows["notch"] = answer(engine._Culled(region_shape).common(45.0, 45.0, 2.0, 15.0, 19.0))
for name, (cx, cy, radius, z0, z1) in (("corner", corner), ("leg", leg)):
    cutter = engine._pointed_cutter(cx, cy, z0, radius, 1.0, z1 - z0)
    region = engine._Culled(region_shape)
    cylinder_first = answer(region.common(cx, cy, radius, z0, z1))
    pointed_after = answer(region.common(cx, cy, radius, z0, z1, cutter))
    region = engine._Culled(region_shape)
    pointed_first = answer(region.common(cx, cy, radius, z0, z1, cutter))
    cylinder_after = answer(region.common(cx, cy, radius, z0, z1))
    rows["pointed-" + name] = {
        "cylinder_first": cylinder_first,
        "pointed_after": pointed_after,
        "pointed_first": pointed_first,
        "cylinder_after": cylinder_after,
        "exact": region_shape.common(cutter).Volume,
    }
with open(target, "w", encoding="utf-8") as stream:
    json.dump(rows, stream)
"""


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("reuse-solids")
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
    assert len(paths) == 2, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


@pytest.fixture(scope="module")
def culled(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("culled")
    script = directory / "culled.py"
    script.write_text(_CULLED, encoding="utf-8")
    # Only the output directory follows "--": freecadcmd also opens each such argument.
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={
            **os.environ,
            "CULLED_ENGINE": os.environ.get("PRECHIPS_TEST_REGION_ENGINE", str(ENGINE)),
        },
    )
    target = directory / "culled.json"
    assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(target.read_text(encoding="utf-8"))


_FACTS = ("sample_count", "tool_hits", "holder_hits", "min_hits", "obstacles", "hit_refs")


def _boss_op(op_id, feature, tool=True, holder=True):
    """R5 cutter 10 long; R5 holder 3 above the tip, under the 6 mm boss tops."""
    op = _op(op_id, feature, 5.0, 10.0, 3.0, holder_radius=5.0)
    if not tool:
        del op["flute_len_mm"]
    if not holder:
        for key in ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm"):
            del op[key]
    return op


def test_later_ops_on_shared_regions_keep_every_proven_ref_and_count_per_kind(engine, solids):
    step = solids["bosses"]
    left = engine.refs(step, (0, 0, 10), (29, 40, 10), kind="Plane")
    right = engine.refs(step, (31, 0, 10), (60, 40, 10), kind="Plane")
    near = engine.refs(step, (23, 18, 10), (27, 22, 16))
    far = engine.refs(step, (38, 18, 10), (42, 22, 16))
    assert len(left) == len(right) == 1 and len(near) == len(far) == 2  # boss side and top
    features = {"both": left + right, "left": left, "right": right}
    hold = _vise(5.0)
    # One setup shares each top's own-face region across ops. Whichever top is posed first
    # in S1:10, the other's poses then meet the near boss already proven for that kind;
    # S1:20 and S1:30 pose those same cylinders again from an empty union.
    ops = [_boss_op("S1:10", "both"), _boss_op("S1:20", "right"), _boss_op("S1:30", "left")]
    shared = engine.run(engine.job(step, features, [_setup(ops, hold)]))["ops"]
    # Fresh single-face, single-kind references: no union or region outcome from another
    # op, face or kind.
    alone = [
        _boss_op("S1:10", "left", holder=False),
        _boss_op("S1:20", "right", holder=False),
        _boss_op("S1:30", "left", tool=False),
        _boss_op("S1:40", "right", tool=False),
    ]
    fresh = engine.run(engine.job(step, features, [_setup(alone, hold)]))["ops"]
    tool = {"left": fresh["S1:10"], "right": fresh["S1:20"]}
    holder = {"left": fresh["S1:30"], "right": fresh["S1:40"]}
    # The left top's cutter and holder meet only the near boss; the right top's meet the
    # near boss across the groove and discover the far one.
    for kind, facts in (("tool", tool), ("holder", holder)):
        assert facts["left"]["hit_refs"][kind] == sorted(near)
        assert facts["right"]["hit_refs"][kind] == sorted(near + far)
        assert 0 < facts["left"][kind + "_hits"] < facts["left"]["sample_count"]
        assert 0 < facts["right"][kind + "_hits"] < facts["right"]["sample_count"]

    for op_id, face in (("S1:20", "right"), ("S1:30", "left")):
        facts = shared[op_id]
        assert facts["sample_count"] == tool[face]["sample_count"]
        for kind, reference in (("tool", tool[face]), ("holder", holder[face])):
            assert facts[kind + "_hits"] == reference[kind + "_hits"]
            assert facts["min_hits"][kind] == reference["min_hits"][kind]
            assert facts["obstacles"][kind] == reference["obstacles"][kind] == ["part"]
            assert facts["hit_refs"][kind] == reference["hit_refs"][kind]
    both = shared["S1:10"]
    assert both["sample_count"] == tool["left"]["sample_count"] + tool["right"]["sample_count"]
    for kind, reference in (("tool", tool), ("holder", holder)):
        hits = reference["left"][kind + "_hits"] + reference["right"][kind + "_hits"]
        assert both[kind + "_hits"] == both["min_hits"][kind] == hits
        assert both["hit_refs"][kind] == sorted(near + far)


def test_every_repeated_bore_axis_pose_counts_as_its_own_hit(engine, solids):
    step = solids["pin-bore"]
    pin = engine.refs(step, (31, 19.2, 2), (32.6, 20.8, 25))
    walls = engine.refs(step, (26, 16, 2), (34, 24, 20), kind="Cylinder")
    bore = [ref for ref in walls if ref not in pin]
    assert len(pin) == 2 and len(bore) == 1  # pin side and top; the opening wall
    drill = {
        **_op("S1:10", "hole", 3.0, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": False, "entry_z_mm": 20.0, "depth_mm": 18.0},
    }
    setup = _setup([drill], _vise(5.0, centre=30.0))
    facts = engine.run(engine.job(step, {"hole": bore}, [setup]))["ops"]["S1:10"]
    # Every wall sample stands the drill on the one bore axis, so each ring of samples
    # repeats one exact pose; the pin rises past every tip. Each sample row and the axis's
    # own tip row is one certain hit.
    assert facts["sample_count"] > 1
    assert facts["tool_hits"] == facts["min_hits"]["tool"] == facts["sample_count"] + 1
    assert facts["obstacles"]["tool"] == ["part"] and facts["hit_refs"]["tool"] == sorted(pin)


def test_region_cull_keeps_a_primitive_solid_where_only_its_stock_cull_takes_the_boolean(culled):
    row = culled["corner"]
    # The stock's L-floor box reaches the raised corner, so its boolean answer is a
    # Compound from which the buried finished face measures apart.
    assert row["stock"]["type"] == "Compound" and row["stock"]["distances"][0] > 1e-3
    # No face of the cut region reaches it: the answer stays the primitive cylinder, which
    # contains that face.
    region = row["region"]
    assert region["type"] == "Solid" and region["distances"] == [0.0]
    assert region["volume"] == pytest.approx(math.pi * 2.0**2 * 10.0, rel=1e-9)


def test_region_boolean_cull_keeps_its_volume_and_bounding_faces_only(culled):
    leg = culled["leg"]
    assert leg["type"] == "Compound"
    assert leg["volume"] == pytest.approx(math.pi * 2.0**2 * 5.0, rel=1e-9)
    # The floor bounds the common; a face buried below it does not.
    assert leg["distances"][1] < 1e-6 < leg["distances"][0]
    # Across the removed leg's boundary only the kept half of the cylinder is material.
    half = math.pi * 2.0**2 * 10.0 / 2
    assert culled["straddle"]["volume"] == pytest.approx(half, rel=1e-9)


def test_cylinder_in_air_inside_the_region_box_is_never_material(culled):
    assert culled["notch"] is None


@pytest.mark.parametrize("case", ["corner", "leg"])
def test_point_cutter_never_takes_or_leaves_its_gross_cylinders_cached_answer(culled, case):
    row = culled["pointed-" + case]
    cylinder = row["cylinder_first"]["volume"]
    assert row["exact"] < cylinder - 1.0
    for name in ("pointed_after", "pointed_first"):
        assert row[name]["volume"] == pytest.approx(row["exact"], rel=1e-9)
    assert row["cylinder_after"]["volume"] == pytest.approx(cylinder, rel=1e-9)
    assert row["cylinder_after"]["type"] == row["cylinder_first"]["type"]
