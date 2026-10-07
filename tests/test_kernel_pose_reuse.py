"""Reused pose outcomes keep every count and ref; region culls keep containment answers.

Engine cases run ``freecad_job.py`` on solids authored here and read only its JSON. Cull
cases load the engine under ``freecadcmd`` and query the culls of real stocks: their
material answers and the part-hit counts that may skip the boolean, on real B-reps.
FreeCAD-backed tests skip without ``freecadcmd``.
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

# 60x40x10 plate, its top split at x 29..31 by a 2 mm deep groove into a left and a right
# floor, each carrying an R1 stem 4 tall under a cap 4 thick (z 14..18). A floor pose is
# legal by its tip disc, which clears the stems, but not the caps overhanging the floor:
# an R5 pose covering a floor point beneath a cap meets it wherever the legal axis
# stands. The near cap, R15 on the left floor's stem at (18, 20), overhangs the groove and
# the right floor to x=33; no R5 pose covering the right floor (axis x >= 26) reaches its
# stem. The far cap, R5 on the right floor's stem at (50, 20), starts at x=45, 6 mm beyond
# any R5 pose covering the left floor (axis x <= 34).
plate = Part.makeBox(60, 40, 10)
for x, cap in ((18, 15), (50, 5)):
    plate = plate.fuse(Part.makeCylinder(1, 4, V(x, 20, 10)))
    plate = plate.fuse(Part.makeCylinder(cap, 4, V(x, 20, 14)))
save("mushrooms", plate.removeSplitter().cut(Part.makeBox(2, 42, 3, V(29, -1, 8))))
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
    cutter = engine._cutter(cx, cy, z0, radius, 1.0, z1 - z0)
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

_HITS = r"""
import importlib.util
import json
import os
import sys
import FreeCAD, Part
V = FreeCAD.Vector
target = sys.argv[sys.argv.index("--") + 1] + "/hits.json"
spec = importlib.util.spec_from_file_location("hits_engine", os.environ["CULLED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

def outcome(call):
    try:
        return call()
    except Exception as exc:
        return "raises " + type(exc).__name__

def measure(shape, queries):
    rows = {}
    for name, query in queries.items():
        cold, warm = engine._Culled(shape), engine._Culled(shape)
        first = outcome(lambda: cold.hits(*query))
        again = outcome(lambda: cold.hits(*query))
        outcome(lambda: warm.common(*query))
        rows[name] = {
            "hits": first,
            "again": again,
            "after_common": outcome(lambda: warm.hits(*query)),
            "legacy": outcome(lambda: engine._Culled(shape).common(*query) is not None),
        }
    return rows

# 60x40x20 plate: pockets x 10..29.99975 and 30.00025..45 (y 5..35, floor z=5) leave
# a 0.0005 mm web at x=30; an R3 through hole at (52, 20); solid strip x 0..10.
plate = Part.makeBox(60, 40, 20)
plate = plate.cut(Part.makeBox(19.99975, 30, 16, V(10, 5, 5)))
plate = plate.cut(Part.makeBox(14.99975, 30, 16, V(30.00025, 5, 5)))
plate = plate.cut(Part.makeCylinder(3, 22, V(52, 20, -1)))
assert plate.isValid() and len(plate.Solids) == 1
PLATE = {
    "deep": (5.0, 20.0, 2.0, 2.0, 18.0),
    "crossing-top": (5.0, 20.0, 2.0, 15.0, 25.0),
    "tiny-inside": (5.0, 20.0, 0.005, 9.0, 9.1),
    "tiny-at-top": (5.0, 20.0, 0.0005, 19.999, 20.0),
    "web-tiny": (30.0, 20.0, 0.02, 12.0, 12.025),
    "web-top": (30.0, 20.0, 0.02, 19.94, 19.97),
    "web-wide": (30.0, 20.0, 2.0, 8.0, 18.0),
    "pocket-air": (20.0, 20.0, 2.0, 8.0, 15.0),
    "pocket-floor-air": (20.0, 20.0, 2.0, 5.0, 15.0),
    "graze-1e-8": (12.0 - 1e-8, 20.0, 2.0, 8.0, 15.0),
    "graze-1e-3": (11.999, 20.0, 2.0, 8.0, 15.0),
    "hole-air": (52.0, 20.0, 2.5, -1.0, 21.0),
    "hole-wall": (52.0, 20.0, 3.5, -1.0, 21.0),
    "outside": (70.0, 20.0, 2.0, 5.0, 15.0),
}
frame = FreeCAD.Placement(V(100, -50, 7), FreeCAD.Rotation(V(0, 0, 1), 30))

def placed(shape):
    copy = shape.copy()
    copy.Placement = frame  # a location, not transformed geometry
    return copy

def moved(query):
    cx, cy, radius, z0, z1 = query
    point = frame.multVec(V(cx, cy, 0))
    return (point.x, point.y, radius, z0 + 7, z1 + 7)

nurbs = plate.toNurbs()
rows = {
    "plate-model": measure(plate, PLATE),
    "plate-placed": measure(placed(plate), {k: moved(q) for k, q in PLATE.items()}),
    "plate-nurbs": measure(placed(nurbs), {k: moved(q) for k, q in PLATE.items()}),
    "nurbs_surfaces": sorted({type(face.Surface).__name__ for face in nurbs.Faces}),
}
# 40 mm cube with a closed 20 mm cavity: a second, inner shell.
hollow = Part.makeBox(40, 40, 40).cut(Part.makeBox(20, 20, 20, V(10, 10, 10)))
rows["hollow"] = measure(hollow, {
    "cavity": (20.0, 20.0, 3.0, 12.0, 28.0),
    "cavity-floor": (20.0, 20.0, 3.0, 10.0, 28.0),
    "cavity-wall": (20.0, 20.0, 3.0, 5.0, 28.0),
    "shell": (5.0, 20.0, 2.0, 5.0, 35.0),
})
# An R5 spherical bowl centred on the top face: a surface with only a box lower bound.
dimple = Part.makeBox(60, 40, 20).cut(Part.makeSphere(5, V(30, 20, 20)))
rows["dimple"] = measure(dimple, {
    "bowl-air": (30.0, 20.0, 1.0, 17.0, 19.5),
    "bowl-bottom": (30.0, 20.0, 1.0, 12.0, 16.0),
    "beside-bowl": (25.2, 20.0, 0.15, 15.5, 16.0),
})
inverted = Part.makeBox(60, 40, 20).reversed()
rows["inverted_volume"] = inverted.Volume
rows["inverted"] = measure(inverted, {
    "inside": (30.0, 20.0, 2.0, 5.0, 15.0),
    "crossing": (30.0, 20.0, 2.0, 15.0, 25.0),
    "above": (30.0, 20.0, 2.0, 20.02, 25.0),
    "outside": (70.0, 20.0, 2.0, 5.0, 15.0),
})
overlap = Part.makeCompound([Part.makeBox(40, 40, 20), Part.makeBox(40, 40, 20, V(20, 0, 0))])
rows["overlap"] = measure(overlap, {
    "both": (30.0, 20.0, 2.0, 5.0, 15.0),
    "single": (10.0, 20.0, 2.0, 15.0, 25.0),
    "air": (70.0, 20.0, 2.0, 5.0, 15.0),
})
# A plain 60x40x20 block: its top face's UV centre (30, 20, 20) seeds a candidate ball
# just below the top, inside a query crossing that face.
block = Part.makeBox(60, 40, 20)
crossing = (30.0, 20.0, 2.0, 15.0, 25.0)
floor = (30.0, 20.0, 2.0, 5.0, 12.0)
# An old generation hits; the next stock cuts an R4 pocket from z=10 through that query.
old = engine._Culled(block)
before = old.hits(*crossing)
drilled = block.cut(Part.makeCylinder(4, 11, V(30, 20, 10)))
new = engine._Culled(drilled)
rows["generation"] = {
    "old": before,
    "new": new.hits(*crossing),
    "new_common_none": new.common(*crossing) is None,
    "old_again": old.hits(*crossing),
    "new_floor": new.hits(*floor),
    "new_floor_volume": engine._Culled(drilled).common(*floor).Volume,
}
culled = engine._Culled(block)
hit = culled.hits(*crossing)
shape = culled.common(*crossing)
reference = engine._Culled(block).common(*crossing)
cutter = engine._cutter(30.0, 20.0, 15.0, 2.0, 1.0, 10.0)
rows["shape"] = {
    "hit": hit,
    "type": shape.ShapeType,
    "volume": shape.Volume,
    "legacy_type": reference.ShapeType,
    "legacy_volume": reference.Volume,
    "pointed": culled.common(*crossing, cutter).Volume,
    "exact": block.common(cutter).Volume,
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


@pytest.fixture(scope="module")
def certified(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("hits")
    script = directory / "hits.py"
    script.write_text(_HITS, encoding="utf-8")
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
    target = directory / "hits.json"
    assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(target.read_text(encoding="utf-8"))


_FACTS = ("sample_count", "tool_hits", "holder_hits", "min_hits", "obstacles", "hit_refs")


def _cap_op(op_id, feature, tool=True, holder=True):
    """R5 cutter 10 long and R5 holder 3 above the tip: each spans the z 14..18 caps."""
    op = _op(op_id, feature, 5.0, 10.0, 3.0, holder_radius=5.0)
    if not tool:
        del op["flute_len_mm"]
    if not holder:
        for key in ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm"):
            del op[key]
    return op


def test_later_ops_on_shared_regions_keep_every_proven_ref_and_count_per_kind(engine, solids):
    step = solids["mushrooms"]
    left = engine.refs(step, (0, 0, 10), (29, 40, 10), kind="Plane")
    right = engine.refs(step, (31, 0, 10), (60, 40, 10), kind="Plane")
    # Each cap's underside, rim and top; never a stem, which no legal pose meets.
    near = engine.refs(step, (2, 4, 14), (34, 36, 18))
    far = engine.refs(step, (44, 14, 14), (56, 26, 18))
    assert len(left) == len(right) == 1 and len(near) == len(far) == 3
    features = {"both": left + right, "left": left, "right": right}
    hold = _vise(5.0)
    # One setup shares each top's own-face region across ops. Whichever top is posed first
    # in S1:10, the other's poses then meet the near cap already proven for that kind;
    # S1:20 and S1:30 pose those same cylinders again from an empty union.
    ops = [_cap_op("S1:10", "both"), _cap_op("S1:20", "right"), _cap_op("S1:30", "left")]
    shared = engine.run(engine.job(step, features, [_setup(ops, hold)]))["ops"]
    # Fresh single-face, single-kind references: no union or region outcome from another
    # op, face or kind.
    alone = [
        _cap_op("S1:10", "left", holder=False),
        _cap_op("S1:20", "right", holder=False),
        _cap_op("S1:30", "left", tool=False),
        _cap_op("S1:40", "right", tool=False),
    ]
    fresh = engine.run(engine.job(step, features, [_setup(alone, hold)]))["ops"]
    tool = {"left": fresh["S1:10"], "right": fresh["S1:20"]}
    holder = {"left": fresh["S1:30"], "right": fresh["S1:40"]}
    # The left top's cutter and holder meet only the near cap above it; the right top's
    # meet the near cap where it overhangs the groove and the far cap around its own stem.
    # Poses far from both caps (the plate corners) stay clear.
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


# Material in each plate query: at or below HIT_MM3 (1e-6 mm^3) is no hit, except that
# a cylinder no face box reaches stays the legacy primitive answer whatever its volume.
PLATE_HITS = {
    "deep": True,
    "crossing-top": True,
    "tiny-inside": True,  # 7.85e-6 mm^3 deep in material: above HIT, below the proof ball
    "tiny-at-top": False,  # 7.9e-10 mm^3 touching the top face takes the boolean
    "web-tiny": False,  # 0.0005 x 0.04 x 0.025 mm of web: 5e-7 mm^3
    "web-top": False,  # top-face UV centre lies on the 0.0005 mm web: ~6e-7 mm^3 of it
    "web-wide": True,
    "pocket-air": False,
    "pocket-floor-air": False,
    "graze-1e-8": False,
    "graze-1e-3": True,  # a 0.001 mm deep segment 7 mm tall: 5.9e-4 mm^3
    "hole-air": False,
    "hole-wall": True,
    "outside": False,
}


def _answers(row):
    return {row["hits"], row["again"], row["after_common"], row["legacy"]}


@pytest.mark.parametrize("frame", ["model", "placed", "nurbs"])
@pytest.mark.parametrize("name, expected", sorted(PLATE_HITS.items()))
def test_material_hit_matches_the_boolean_on_placed_and_bspline_stock(
    certified, frame, name, expected
):
    assert certified["nurbs_surfaces"] == ["BSplineSurface"]
    assert _answers(certified["plate-" + frame][name]) == {expected}


@pytest.mark.parametrize(
    "stock, name, expected",
    [
        ("hollow", "cavity", False),
        ("hollow", "cavity-floor", False),
        ("hollow", "cavity-wall", True),
        ("hollow", "shell", True),
        ("dimple", "bowl-air", False),
        ("dimple", "bowl-bottom", True),
        ("dimple", "beside-bowl", True),
    ],
)
def test_material_hit_respects_inner_shells_and_unanalysed_surfaces(
    certified, stock, name, expected
):
    assert _answers(certified[stock][name]) == {expected}


@pytest.mark.parametrize("stock", ["inverted", "overlap"])
def test_inverted_or_overlapping_stock_keeps_the_native_boolean_answer(certified, stock):
    for row in certified[stock].values():
        assert len(_answers(row)) == 1, row
    if stock == "inverted":
        assert certified["inverted_volume"] < 0
        # Reversed normals put a top-face candidate ball above the box, in air.
        assert _answers(certified["inverted"]["above"]) == {False}
    else:
        assert certified["overlap"]["air"]["legacy"] is False
        assert certified["overlap"]["single"]["legacy"] is True


def test_a_fresh_cut_generation_never_counts_material_its_cut_removed(certified):
    row = certified["generation"]
    assert row["old"] is True and row["old_again"] is True
    assert row["new"] is False and row["new_common_none"] is True
    # Below the pocket floor the new stock keeps z 5..10 of the query.
    assert row["new_floor"] is True
    assert row["new_floor_volume"] == pytest.approx(math.pi * 2.0**2 * 5.0, rel=1e-9)


def test_a_counted_hit_keeps_the_native_common_shape_and_pointed_cutter_answer(certified):
    row = certified["shape"]
    assert row["hit"] is True
    assert row["type"] == row["legacy_type"] == "Compound"
    assert row["volume"] == pytest.approx(row["legacy_volume"], abs=1e-9)
    assert row["volume"] == pytest.approx(math.pi * 2.0**2 * 5.0, rel=1e-9)
    assert row["exact"] < row["volume"] - 1.0
    assert row["pointed"] == pytest.approx(row["exact"], rel=1e-9)
