"""Per-sample covering axes and their real FreeCAD collision/stock consequences.

The private probe uses the same source through KERNEL_SOURCE, never as a second
FreeCAD script argument. Authored BREP retains sub-STEP equality perturbations;
public Engine jobs separately prove the ordinary-floor consumer path.
"""

import json
import math
import os
import subprocess
from pathlib import Path

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise

from prechips import kernel

_AUTHOR = r"""
import math, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
shapes = {}

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shapes[name] = shape
    shape.exportStep(out + "/" + name + ".step")
    shape.exportBrep(out + "/" + name + ".brep")

block = Part.makeBox(60, 40, 20)
save("sharp", Part.makeBox(40, 30, 8).cut(Part.makeBox(20, 20, 8, V(5, 5, 1))))
for name, radius in (("orbit", 5.1), ("circle", 3.0), ("small-circle", 2.9995)):
    save(name, block.cut(Part.makeCylinder(radius, 7, V(30, 20, 14))))
save("blind-core", block.cut(Part.makeCylinder(3, 11, V(30, 20, 10))))
above_tilted_cap = Part.makeBox(100, 100, 30, V(-20, -30, 10))
above_tilted_cap.rotate(V(30, 20, 10), V(0, 1, 0), math.degrees(1e-5))
tilted_void = Part.makeCylinder(3, 12, V(30, 20, 9)).common(above_tilted_cap)
save("tilted-blind-core", block.cut(tilted_void))
save("strip", block.cut(Part.makeBox(62, 6, 9, V(-1, 17, 12))))
cutter = Part.makeBox(30, 12, 7, V(15, 14, 14))
vertical = [edge for edge in cutter.Edges if abs(edge.tangentAt(edge.FirstParameter).z) > .99]
save("round-corner", block.cut(cutter.makeFillet(3, vertical)))
save("rough-step", block.cut(Part.makeBox(31, 42, 11, V(30, -1, 10))))
save("low-wall", Part.makeBox(60, 40, 12).cut(Part.makeBox(31, 42, 3, V(30, -1, 10))))
loop = [V(30, 0, 10), V(30, 0, 11), V(35, 0, 20), V(61, 0, 20),
    V(61, 0, 10), V(30, 0, 10)]
save("overhang", block.cut(Part.Face(Part.makePolygon(loop)).extrude(V(0, 40, 0))))
plate = Part.makeBox(60, 40, 10)
save("tie", plate.fuse(Part.makeBox(6, 6, 6, V(42, 26, 10))).removeSplitter())

# The floor centroid is exactly 10 mm at 160 degrees from a convex vertex.
# Removing the thin triangular island is accounted for before placing the plate.
a = V(5*math.cos(math.radians(269)), 5*math.sin(math.radians(269)), 10)
b = V(5*math.cos(math.radians(271)), 5*math.sin(math.radians(271)), 10)
triangle = Part.Face(Part.makePolygon([V(0, 0, 10), a, b, V(0, 0, 10)]))
target = V(10*math.cos(math.radians(160)), 10*math.sin(math.radians(160)), 0)
centre = (target*(800-triangle.Area) + triangle.CenterOfMass*triangle.Area)/800
near_plate = Part.makeBox(40, 20, 10, V(centre.x-20, centre.y-10, 0))
save("near-centre", near_plate.fuse(triangle.extrude(V(0, 0, 6))).removeSplitter())

# Both unsupported curves exist at the floor's actual Z. Only the far curve is
# outside every covering axis' possible clearance neighbourhood.
spline = Part.BSplineCurve()
spline.interpolate([V(38.5, 20, 14), V(40, 20.8, 14), V(41.5, 20, 14)])
pad = Part.Face(Part.Wire([spline.toShape(),
    Part.LineSegment(V(41.5, 20, 14), V(38.5, 20, 14)).toShape()])).extrude(V(0, 0, 6))
base = Part.makeBox(60, 40, 14)
for name, radius in (("far-bsp", 5.1), ("near-bsp", 2.5)):
    ring = Part.makeCylinder(8, 6, V(15, 15, 14)).cut(
        Part.makeCylinder(radius, 6, V(15, 15, 14)))
    save(name, base.fuse([ring, pad]).removeSplitter())

# Two separate section obstacles share a base: the outward wall projection is
# blocked by the spline pad, although a farther supported axis is genuinely clear.
base = Part.makeBox(60, 40, 10)
wall = Part.makeBox(2, 20, 6, V(30, 10, 10))
spline = Part.BSplineCurve()
spline.interpolate([V(37.5, 19.9, 10), V(37.2, 20, 10), V(37.5, 20.1, 10)])
loop = [V(37.5, 20.1, 10), V(37.5, 20.5, 10), V(38.5, 20.5, 10),
    V(38.5, 19.9, 10), V(37.5, 19.9, 10)]
pad = Part.Face(Part.Wire([spline.toShape()] +
    [Part.LineSegment(a, b).toShape() for a, b in zip(loop, loop[1:])])).extrude(V(0, 0, 6))
save("blocked-supported", base.fuse([wall, pad]).removeSplitter())

# A horizontal future bore spans z7..11, genuinely CROSSING the z10 floor.
# Its top opening is an inner wire of that floor, not an unrelated enclosed void.
core = Part.makeCylinder(2, 20, V(20, 20, 9), V(1, 0, 0))
save("cross-core", plate.cut(core))
save("unclaimed-core", plate.cut(core).cut(Part.makeBox(15, 40, 2, V(45, 0, 8))))
# One bore opens onto two claimed floor heights. Its highest claimed cut is z10;
# material between z8 and z10 must not be freed by crediting the lower claim.
stepped = plate.cut(Part.makeBox(30, 40, 2, V(0, 0, 8)))
save("multilevel-core", stepped.cut(Part.makeCylinder(2, 40, V(10, 20, 9), V(1, 0, 0))))
"""

_PROBE = r"""
import importlib.util, json, math, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("legal_centre_kernel", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

def read(name):
    solid = Part.Shape()
    solid.read(out + "/" + name + ".brep")
    assert solid.isValid() and len(solid.Solids) == 1
    return solid

def setup(name):
    solid = read(name)
    owner = job._Job({"version": 1, "setups": []})
    owner.solid = solid
    owner.labels = [name + ":" + str(index) for index in range(len(solid.Faces))]
    owner.raw_supplies = {"stock": (solid, None)}
    owner.protected = {"stock": solid}
    owner.ownership_reasons = {}
    owner.joint_features = {}
    owner.sweep_mm = 200
    runner = job._Setup(owner, {}, held=solid,
        state={"components": {"stock"}, "completed": {}, "joined": set(), "consumed": set()})
    runner.matrix = FreeCAD.Matrix()
    runner.finished = runner.protected = solid
    runner.faces = solid.Faces
    runner.face_boxes = [job._tolerant_box(face) for face in runner.faces]
    runner.certain = runner._certain_material()
    runner._use(solid)
    runner.box = job._bbox(solid)
    return runner

def floor(runner, bounds):
    found = [index for index, face in enumerate(runner.faces)
        if isinstance(face.Surface, Part.Plane)
        and job._normal_at(face, face.CenterOfMass).z > .99
        and all(abs(value - wanted) < 1e-6
            for value, wanted in zip(job._bbox(face), bounds))]
    assert len(found) == 1, (bounds, found)
    return found[0]

def axis(name, bounds, point, radius, leave=0, z=None, flute=10):
    runner = setup(name)
    index = floor(runner, bounds)
    z = point[2] + leave + job.LIFT if z is None else z
    p = V(*point)
    xy = runner._planar_axis(index, p, radius, leave, z)
    tip = V(xy[0], xy[1], z)
    edges = [edge for wire in runner.certain.slice(V(0, 0, 1), z) for edge in wire.Edges]
    distance = min((edge.distToShape(Part.Vertex(tip))[0] for edge in edges), default=None)
    return {"axis": list(xy), "displacement": math.hypot(xy[0]-p.x, xy[1]-p.y),
        "clearance": distance, "centroid": list(runner.faces[index].CenterOfMass)[:2],
        "collision_mm3": Part.makeCylinder(radius, flute, tip).common(runner.certain).Volume}

result = {}
result["sharp"] = axis("sharp", (5, 5, 1, 25, 25, 1), (5, 5, 1), 2)
result["sharp-old"] = {"axis": [7, 7], "displacement": math.sqrt(8),
    "collision_mm3": Part.makeCylinder(2, 10, V(7, 7, 1 + job.LIFT)).common(read("sharp")).Volume}
for index in range(8):
    angle = index * math.pi / 4
    point = (30 + 5.1 * math.cos(angle), 20 + 5.1 * math.sin(angle), 14)
    result["orbit:" + str(index)] = axis("orbit", (24.9, 14.9, 14, 35.1, 25.1, 14), point, 4.7625)
for delta in (-1e-8, 0, 1e-8, 1.25e-7, 5e-4):
    result["circle:" + str(delta)] = axis("circle", (27, 17, 14, 33, 23, 14),
        (33, 20, 14), 3 + delta)
    result["strip:" + str(delta)] = axis("strip", (0, 17, 12, 60, 23, 12),
        (30, 17, 12), 3 + delta)
result["fillet"] = axis("round-corner", (15, 14, 14, 45, 26, 14), (15, 17, 14), 3)
result["rough"] = axis("rough-step", (30, 0, 10, 60, 40, 10), (30, 20, 10), 1, .2)
result["low-wall:low"] = axis("low-wall", (30, 0, 10, 60, 40, 10), (30, 20, 10), 1, .2)
result["low-wall:high"] = axis("low-wall", (30, 0, 10, 60, 40, 10),
    (30, 20, 10), 1, .2, z=14 + job.LIFT)
result["overhang"] = axis("overhang", (30, 0, 10, 60, 40, 10), (30, 20, 10), 1)
result["tie"] = axis("tie", (0, 0, 10, 60, 40, 10), (42, 26, 10), 2)
bb = job._bbox(read("near-centre"))
result["near-centre"] = axis("near-centre", (bb[0], bb[1], 10, bb[3], bb[4], 10),
    (9e-8*math.cos(math.radians(60)), 9e-8*math.sin(math.radians(60)), 10), 1)
result["far-bsp"] = axis("far-bsp", (9.9, 9.9, 14, 20.1, 20.1, 14), (20.1, 15, 14), 4.7625)

def certificate_case(name, bounds, point, witnesses=()):
    runner = setup(name)
    index = floor(runner, bounds)
    p = V(point[0], point[1], point[2] + job.LIFT)
    section = runner._planar_section(p.z)
    distance, pairs, infos = job._distance(section["shape"], Part.Vertex(p))
    row = {"distance": distance,
        "inside": any(s.isInside(p, 1e-9, True) for s in runner.certain.Solids),
        "strict_inside": any(s.isInside(p, 1e-9, False) for s in runner.certain.Solids),
        "closest": []}
    for pair, info in zip(pairs, infos):
        q = pair[0]
        kind, slot, parameter = info[:3]
        closest = {"q": list(q), "kind": kind,
            "coordinate_distance": math.hypot(p.x-q.x, p.y-q.y),
            "in_material": any(s.isInside(q, 1e-9, True) for s in runner.certain.Solids)}
        if kind == "Edge":
            edge = section["shape"].Edges[slot]
            closest.update(spline=isinstance(edge.Curve, Part.BSplineCurve),
                interior=min(edge.FirstParameter, edge.LastParameter) < parameter <
                    max(edge.FirstParameter, edge.LastParameter),
                tolerance=edge.getTolerance(1))
        row["closest"].append(closest)

    def measure(xy):
        tip = V(xy[0], xy[1], p.z)
        return {"axis": list(xy), "displacement": math.hypot(tip.x-p.x, tip.y-p.y),
            "inside": any(s.isInside(tip, 1e-9, True) for s in runner.certain.Solids),
            "legal": runner._planar_legal(section, tip.x, tip.y, tip.z, 3),
            "clearance": job._distance(section["shape"], Part.Vertex(tip))[0],
            "collision_mm3": Part.makeCylinder(3, 10, tip).common(runner.certain).Volume}

    row["witnesses"] = [measure(xy) for xy in witnesses]
    row["sample"] = measure((p.x, p.y))
    if len(pairs) == 1 and row["closest"][0]["coordinate_distance"] > job.PLANAR_EQUAL_MM:
        q = pairs[0][0]
        d = row["closest"][0]["coordinate_distance"]
        row["bound"] = 3-d
        row["projection"] = measure((q.x+3*(p.x-q.x)/d, q.y+3*(p.y-q.y)/d))
    try:
        xy = runner._planar_axis(index, V(*point), 3, 0, p.z)
        row["selected"] = measure(xy)
    except ValueError as exc:
        row["undefined"] = str(exc)
    return row

for label, point, witnesses in (
    ("near-bsp", (44, 20, 14), ()),
    ("bsp-line-boundary", (39.25, 20, 14), ((39.25, 17), (39.25, 23))),
    ("bsp-boundary", (40, 20.8, 14), ()),
    ("bsp-interior", (40, 20.4, 14), ()),
    ("bsp-vertex", (41.5, 20, 14), ()),
    ("bsp-precision", (40, 21.8, 14), ((40, 23.8),)),
):
    result[label] = certificate_case("near-bsp", (0, 0, 14, 60, 40, 14), point, witnesses)
result["blocked-supported"] = certificate_case("blocked-supported",
    (0, 0, 10, 60, 40, 10), (34, 20, 10), ((35, 22.1583123951777),))
# The farther witness meets the wall's supported offset line x35 and a native
# endpoint circle; it is not merely an arbitrary point outside the material.
blocked_section = setup("blocked-supported")._planar_section(10 + job.LIFT)
endpoint = min(blocked_section["shape"].Vertexes,
    key=lambda vertex: (vertex.Point-V(37.5, 20.5, 10+job.LIFT)).Length)
result["blocked-supported"]["supported_endpoint"] = list(endpoint.Point)
result["blocked-supported"]["witness_endpoint_distance"] = job._distance(
    endpoint, Part.Vertex(V(35, 22.1583123951777, 10+job.LIFT)))[0]

# Exercise real bounded removal, with actual future bores discovered from features.
# No stand-in column or mocked _hole_columns result is installed.
def bounded(name, bounds, claims, action="face", to_z=10):
    runner = setup(name)
    solid = runner.finished
    bore = [index for index, face in enumerate(solid.Faces)
        if isinstance(face.Surface, Part.Cylinder) and job._cylinder_concave(face)]
    assert len(bore) == 1
    runner.owner.mapping = {label: index for index, label in enumerate(runner.owner.labels)}
    runner.owner.errors = {}
    runner.owner.job["features"] = {"future-bore": [runner.owner.labels[index] for index in bore]}
    runner.owner.job["setups"] = [{"ops": [{"feature": "future-bore",
        "do": "bore", "hole": {"thru": False, "depth_mm": 20}}]}]
    stock = Part.makeBox(60, 40, 20)
    runner.held = stock
    runner.owner.raw_supplies = {"stock": (stock, None)}
    runner.certain = runner._certain_material()
    runner._use(stock)
    runner.box = job._bbox(stock)
    indices = [floor(runner, claim) for claim in claims]
    records = runner._hole_columns(indices)
    assert len(records) == 1
    columns = records[0][1]
    removed, why = runner._bounded(bounds, stock, indices, [], to_z, 3, 0, action)
    assert why is None, why
    rest = stock if removed is None else stock.cut(removed)
    below = Part.makeBox(80, 60, to_z + 5, V(-10, -10, -5))
    above = Part.makeBox(80, 60, 30, V(-10, -10, to_z))
    # All intersection volumes are measured natively, including outside the author box.
    window = Part.makeBox(bounds["x"][1]-bounds["x"][0], bounds["y"][1]-bounds["y"][0],
        bounds["z"][1]-bounds["z"][0], V(bounds["x"][0], bounds["y"][0], bounds["z"][0]))
    highest = max(max(to_z, runner.faces[index].Surface.Position.z) for index in indices)
    below_highest = Part.makeBox(80, 60, highest + 5, V(-10, -10, -5))
    lowest = min(max(to_z, runner.faces[index].Surface.Position.z) for index in indices)
    facing_sweep = runner._sweep(indices, "face")[1]
    lower_band = columns.common(runner._above(lowest)).common(below_highest).common(stock)
    blind = name in ("blind-core", "tilted-blind-core")
    contact = V(33, 20, 10) if blind else V(30, 20-math.sqrt(3), 10)
    face = runner.faces[indices[0]]
    u, v = face.Surface.parameter(contact)
    contact = face.valueAt(u, v)
    z = max(contact.z, to_z) + job.LIFT
    xy = (runner._planar_axis(indices[0], contact, 3, 0, z)
        if name == "cross-core" or blind else None)
    tip = V(xy[0], xy[1], z) if xy is not None else V(contact.x, contact.y, z)
    flute = Part.makeCylinder(3, 5, tip)
    return {"axis": list(xy) if xy is not None else None,
        "normal": list(job._normal_at(face, face.CenterOfMass)),
        "flute_core_before_mm3": columns.common(stock).common(flute).Volume,
        "crossing_above_mm3": columns.common(above).common(stock).Volume,
        "crossing_below_mm3": columns.common(below).common(stock).Volume,
        "removed_core_above_mm3": (
            0 if removed is None else columns.common(above).common(removed).Volume),
        "removed_core_below_mm3": (
            0 if removed is None else columns.common(below).common(removed).Volume),
        "removed_core_outside_window_mm3": (
            0 if removed is None else columns.cut(window).common(removed).Volume),
        "removed_core_below_highest_mm3": (
            0 if removed is None else columns.common(below_highest).common(removed).Volume),
        "remaining_core_below_highest_mm3": columns.common(below_highest).common(rest).Volume,
        "core_below_highest_mm3": columns.common(below_highest).common(stock).Volume,
        "lower_sweep_below_highest_mm3": lower_band.common(facing_sweep).Volume,
        "flute_core_remaining_mm3": columns.common(rest).common(flute).Volume,
        "remaining_core_above_mm3": columns.common(above).common(rest).Volume,
        "remaining_core_below_mm3": columns.common(below).common(rest).Volume}

wide = {"x": [0, 60], "y": [0, 40], "z": [10, 20]}
claim = [(0, 0, 10, 60, 40, 10)]
result["core:face"] = bounded("cross-core", wide, claim)
result["core:mill"] = bounded("cross-core", wide, claim, action="mill")
result["core:narrow"] = bounded("cross-core", {**wide, "x": [0, 25]}, claim)
result["core:unclaimed"] = bounded("unclaimed-core",
    {"x": [0, 60], "y": [0, 40], "z": [8, 20]}, [(45, 0, 8, 60, 40, 8)], to_z=8)
result["core:multilevel"] = bounded("multilevel-core",
    {"x": [0, 60], "y": [0, 40], "z": [8, 20]},
    [(0, 0, 8, 30, 40, 8), (30, 0, 10, 60, 40, 10)], to_z=8)
result["core:blind-cap"] = bounded("blind-core",
    {"x": [27, 33], "y": [17, 23], "z": [10, 20]}, [(27, 17, 10, 33, 23, 10)])
tilted = setup("tilted-blind-core")
cap = [face for face in tilted.faces if isinstance(face.Surface, Part.Plane)
    and job._bbox(face)[2] > 9 and job._bbox(face)[5] < 11]
assert len(cap) == 1
result["core:tilted-blind-cap"] = bounded("tilted-blind-core",
    {"x": [27, 33], "y": [17, 23], "z": [9.99, 20]}, [job._bbox(cap[0])])
with open(out + "/native.json", "w") as handle:
    json.dump(result, handle)
"""

FLOORS = {
    "sharp": ((5, 5, 1), (25, 25, 1)),
    "orbit": ((24.9, 14.9, 14), (35.1, 25.1, 14)),
    "circle": ((27, 17, 14), (33, 23, 14)),
    "small-circle": ((27.0005, 17.0005, 14), (32.9995, 22.9995, 14)),
    "strip": ((0, 17, 12), (60, 23, 12)),
    "round-corner": ((15, 14, 14), (45, 26, 14)),
    "rough-step": ((30, 0, 10), (60, 40, 10)),
    "low-wall": ((30, 0, 10), (60, 40, 10)),
    "overhang": ((30, 0, 10), (60, 40, 10)),
    "tie": ((0, 0, 10), (60, 40, 10)),
    "near-centre": ((-100, -100, 10), (100, 100, 10)),
    "far-bsp": ((9.9, 9.9, 14), (20.1, 20.1, 14)),
    "blocked-supported": ((0, 0, 10), (60, 40, 10)),
    "cross-core": ((0, 0, 10), (60, 40, 10)),
    "blind-core": ((27, 17, 10), (33, 23, 10)),
    "tilted-blind-core": ((27, 17, 9.99), (33, 23, 10.01)),
}
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [40.0, 20.0],
}


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("planar-legal-centres")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    names = {*FLOORS, "near-bsp", "unclaimed-core", "multilevel-core"}
    paths = {name: directory / f"{name}.step" for name in names}
    assert all(path.exists() for path in paths.values()), (
        process.stdout[-2000:] + process.stderr[-2000:]
    )
    return paths


@pytest.fixture(scope="module")
def native(solids, freecad_kernel):
    directory = solids["sharp"].parent
    script = directory / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
        env={**os.environ, "KERNEL_SOURCE": str(source)},
    )
    report = directory / "native.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(report.read_text(encoding="utf-8"))


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _floor(engine, solids, name, radius, **extra):
    step = solids[name]
    refs = engine.refs(step, *FLOORS[name], kind="Plane")
    assert len(refs) == 1
    op = {**_op("S1:10", "floor", radius, 10.0, 20.0), **extra}
    centre = 20.0 if name == "sharp" else 30.0
    job = engine.job(step, {"floor": refs}, [_setup([op], _vise(0.5, centre=centre))])
    return engine.run(job)["ops"]["S1:10"]


def test_sharp_corner_keeps_uncovered_sample_and_public_engine_reports_physical_hit(
    native, engine, solids
):
    old, new = native["sharp-old"], native["sharp"]
    assert old["axis"] == [7, 7]
    assert old["displacement"] == pytest.approx(math.sqrt(8))
    assert old["displacement"] > 2 and old["collision_mm3"] == pytest.approx(0, abs=1e-9)
    assert new["axis"] == pytest.approx([5, 5], rel=0, abs=1e-9)
    assert new["collision_mm3"] > 1
    detail = _floor(engine, solids, "sharp", 2)
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert detail["obstacles"]["tool"] == ["part"], detail


def test_circular_pocket_covers_its_ring_on_the_exact_annular_axis_orbit(native, engine, solids):
    for index in range(8):
        angle = index * math.pi / 4
        row = native[f"orbit:{index}"]
        assert row["axis"] == pytest.approx(
            [30 + 0.3375 * math.cos(angle), 20 + 0.3375 * math.sin(angle)], rel=0, abs=1e-7
        )
        assert row["displacement"] == pytest.approx(4.7625, rel=0, abs=1e-7)
        assert row["clearance"] == pytest.approx(4.7625, rel=0, abs=1e-7)
        assert row["collision_mm3"] == pytest.approx(0, abs=1e-8)
    detail = _floor(engine, solids, "orbit", 4.7625)
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == [], detail


@pytest.mark.parametrize("delta", [-1e-8, 0, 1e-8])
def test_fixed_equality_preserves_circle_singleton_and_two_radius_strip(native, delta):
    circle, strip = native[f"circle:{delta}"], native[f"strip:{delta}"]
    assert circle["axis"] == pytest.approx([30, 20], rel=0, abs=1e-7)
    assert strip["axis"] == pytest.approx([30, 20], rel=0, abs=1e-7)
    assert circle["displacement"] <= 3 + delta + 1e-7
    assert strip["displacement"] <= 3 + delta + 1e-7
    assert circle["clearance"] >= 3 + delta - 1e-7
    assert strip["clearance"] >= 3 + delta - 1e-7


@pytest.mark.parametrize("name, original", [("circle", [33, 20]), ("strip", [30, 17])])
def test_equality_just_beyond_fixed_tolerance_is_not_scaled_by_radius(native, name, original):
    row = native[f"{name}:1.25e-07"]
    assert row["axis"] == pytest.approx(original, rel=0, abs=1e-9)


@pytest.mark.parametrize("name", ["circle", "strip"])
def test_exact_closed_legal_regions_are_accepted_by_the_public_floor_consumer(engine, solids, name):
    detail = _floor(engine, solids, name, 3)
    assert detail["tool_hits"] == 0 and "tool_hits" not in detail["reasons"], detail


@pytest.mark.parametrize(
    "name, radius", [("circle", 3.0005), ("strip", 3.0005), ("small-circle", 3)]
)
def test_separation_smaller_than_stock_tolerance_is_still_a_real_wall_hit(
    native, engine, solids, name, radius
):
    if name != "small-circle":
        row = native[f"{name}:0.0005"]
        expected = [33, 20] if name == "circle" else [30, 17]
        assert row["axis"] == pytest.approx(expected, rel=0, abs=1e-9)
        assert row["collision_mm3"] > 0
    detail = _floor(engine, solids, name, radius)
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert "tool_hits" not in detail["reasons"], detail


def test_corner_fillet_equal_to_tool_radius_has_a_covering_native_clear_axis(
    native, engine, solids
):
    row = native["fillet"]
    assert row["axis"] == pytest.approx([18, 17], rel=0, abs=1e-7)
    assert row["displacement"] == pytest.approx(3, rel=0, abs=1e-7)
    assert row["collision_mm3"] == pytest.approx(0, abs=1e-8)
    detail = _floor(engine, solids, "round-corner", 3)
    assert detail["tool_hits"] == 0, detail


def test_rough_wall_uses_leave_for_both_clearance_and_coverage(native, engine, solids):
    row = native["rough"]
    assert row["axis"] == pytest.approx([31.2, 20], rel=0, abs=1e-7)
    assert row["displacement"] == pytest.approx(1.2, rel=0, abs=1e-7)
    assert row["clearance"] == pytest.approx(1.2, rel=0, abs=1e-7)
    assert row["collision_mm3"] == pytest.approx(0, abs=1e-8)
    detail = _floor(engine, solids, "rough-step", 1, do="rough_pocket", rough_allowance_mm=0.2)
    assert detail["tool_hits"] == 0, detail


def test_actual_tip_height_changes_legality_without_excusing_unclaimed_raw(native, engine, solids):
    assert native["low-wall:low"]["axis"] == pytest.approx([31.2, 20], rel=0, abs=1e-7)
    assert native["low-wall:high"]["axis"] == pytest.approx([30, 20], rel=0, abs=1e-9)
    step = solids["low-wall"]
    floor = engine.refs(step, *FLOORS["low-wall"], kind="Plane")
    op = {
        **_op("S1:10", "floor", 1, 10, 20),
        "do": "rough_face",
        "rough_allowance_mm": 0.2,
        "to_z": 14.0,
    }
    detail = engine.run(
        engine.job(step, {"floor": floor}, [_setup([op], _vise(0.5, centre=30))], stock=BLANK)
    )["ops"]["S1:10"]
    # At z14 the finished low wall no longer constrains this edge sample. The raw
    # left of the face still rises to z20 and the full flute must report it.
    assert detail["reach_depth_mm"] == pytest.approx(6), detail
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail


def test_at_z_axis_does_not_search_away_from_a_full_flute_overhang_hit(native, engine, solids):
    row = native["overhang"]
    assert row["axis"] == pytest.approx([31, 20], rel=0, abs=1e-7)
    assert row["collision_mm3"] > 1
    detail = _floor(engine, solids, "overhang", 1)
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail


def test_continuous_vertex_circle_tie_uses_original_face_centroid_before_xy(native, engine, solids):
    row = native["tie"]
    dx, dy = row["centroid"][0] - 42, row["centroid"][1] - 26
    norm = math.hypot(dx, dy)
    expected = [42 + 2 * dx / norm, 26 + 2 * dy / norm]
    assert row["axis"] == pytest.approx(expected, rel=0, abs=1e-7)
    assert row["axis"][1] < 26 - 0.5  # lex-only would choose (40, 26)
    assert row["displacement"] == pytest.approx(2, rel=0, abs=1e-7)
    assert row["collision_mm3"] == pytest.approx(0, abs=1e-8)
    detail = _floor(engine, solids, "tie", 2)
    assert detail["tool_hits"] == 0, detail


def test_near_vertex_centre_keeps_the_true_radial_minimum_before_centroid_ties(
    native, engine, solids
):
    row = native["near-centre"]
    expected_centroid = [10 * math.cos(math.radians(160)), 10 * math.sin(math.radians(160))]
    assert row["centroid"] == pytest.approx(expected_centroid, rel=0, abs=1e-7)
    px, py = 9e-8 * math.cos(math.radians(60)), 9e-8 * math.sin(math.radians(60))
    true_minimum = 1 - math.hypot(px, py)
    norm = math.hypot(*row["centroid"])
    old_centroid_distance = math.hypot(
        row["centroid"][0] / norm - px, row["centroid"][1] / norm - py
    )
    assert old_centroid_distance - true_minimum > 1e-7
    # Other points inside the fixed tie band may win by centroid preference;
    # the true radial minimum must nevertheless establish that band's origin.
    assert row["displacement"] <= true_minimum + 1e-7 + 1e-12
    assert row["clearance"] >= 1 - 1e-7
    assert row["collision_mm3"] == pytest.approx(0, abs=1e-8)
    detail = _floor(engine, solids, "near-centre", 1)
    assert detail["tool_hits"] == 0, detail


def test_tiny_qualifying_floor_tilt_cannot_take_the_lateral_radius_shift(engine, solids):
    step = solids["tie"]
    floor = engine.refs(step, *FLOORS["tie"], kind="Plane")
    op = _op("S1:10", "floor", 2, 10, 20)
    exact = _setup([op], _vise(0.5, centre=30))
    angle = 1e-8
    tilted = _setup(
        [op],
        _vise(0.5, centre=30),
        {
            "origin": [0, 0, 0],
            "x": [math.cos(angle), 0, -math.sin(angle)],
            "y": [0, 1, 0],
            "z": [math.sin(angle), 0, math.cos(angle)],
        },
    )
    for result in engine.run(
        {"jobs": [engine.job(step, {"floor": floor}, [setup]) for setup in (exact, tilted)]}
    )["results"]:
        detail = result["ops"]["S1:10"]
        assert detail["tool_hits"] == 0 and "tool_hits" not in detail["reasons"], detail


def test_far_unsupported_section_curve_adds_no_floor_debt(native, engine, solids):
    row = native["far-bsp"]
    assert row["axis"] == pytest.approx([15.3375, 15], rel=0, abs=1e-7)
    detail = _floor(engine, solids, "far-bsp", 4.7625)
    assert detail["tool_hits"] == 0 and "tool_hits" not in detail["reasons"], detail


@pytest.mark.parametrize(
    "name, expected, bound",
    [("near-bsp", [44.5, 20], 0.5), ("bsp-line-boundary", [39.25, 17], 3)],
)
def test_near_spline_certified_axis_attains_the_native_displacement_bound(
    native, name, expected, bound
):
    row = native[name]
    selected = row["selected"]
    assert selected["axis"] == pytest.approx(expected, rel=0, abs=1e-7)
    assert selected["displacement"] <= bound + 1e-7 + 1e-12
    assert selected["legal"] and not selected["inside"], row
    assert selected["clearance"] >= 3 - 1e-7
    assert selected["collision_mm3"] == pytest.approx(0, abs=1e-8)
    assert not row["strict_inside"], row
    if name == "near-bsp":
        assert not row["inside"], row
        assert row["distance"] == pytest.approx(2.5, rel=0, abs=1e-7)
        assert row["closest"][0]["q"] == pytest.approx([41.5, 20, 14.001], rel=0, abs=1e-7)
        assert row["closest"][0]["kind"] == "Vertex"
        assert row["closest"][0]["in_material"], row
        assert row["bound"] == pytest.approx(0.5, rel=0, abs=1e-7)
    else:
        assert row["distance"] <= 1e-7
        assert row["closest"][0]["kind"] == "Edge"
        assert row["closest"][0]["interior"] and not row["closest"][0]["spline"], row
        outward, inward = row["witnesses"]
        assert outward["legal"] and not inward["legal"], row
        assert inward["clearance"] < 3 - 1e-7


@pytest.mark.parametrize("name", ["bsp-boundary", "bsp-interior", "bsp-vertex"])
def test_uncertified_spline_boundary_interior_and_vertex_remain_named_unknown(native, name):
    row = native[name]
    assert "no exact legal-centre offset" in row["undefined"], row
    assert not row["sample"]["legal"], row
    assert row["sample"]["collision_mm3"] > 0, row
    if name == "bsp-interior":
        assert row["strict_inside"], row
    else:
        assert row["distance"] <= 1e-7 and not row["strict_inside"], row
        closest = row["closest"][0]
        assert closest["in_material"], row
        if name == "bsp-boundary":
            assert closest["kind"] == "Edge" and closest["spline"] and closest["interior"], row
        else:
            assert closest["kind"] == "Vertex", row
            assert closest["q"] == pytest.approx([41.5, 20, 14.001], rel=0, abs=1e-7)


def test_unsupported_interior_native_precision_refuses_even_a_legal_nominal_projection(native):
    row = native["bsp-precision"]
    assert not row["inside"] and not row["strict_inside"], row
    assert row["distance"] == pytest.approx(1, rel=0, abs=1e-7)
    (closest,) = row["closest"]
    assert closest["kind"] == "Edge" and closest["spline"] and closest["interior"], row
    assert closest["in_material"] and closest["tolerance"] > 1e-7, row
    assert closest["q"] == pytest.approx([40, 20.8, 14.001], rel=0, abs=1e-7)
    projection = row["projection"]
    assert projection["axis"] == pytest.approx([40, 23.8], rel=0, abs=1e-7)
    (witness,) = row["witnesses"]
    for candidate in (projection, witness):
        assert candidate["legal"] and not candidate["inside"], row
        assert candidate["clearance"] >= 3 - 1e-7
        assert candidate["collision_mm3"] == pytest.approx(0, abs=1e-8)
        assert candidate["displacement"] <= 2 + 1e-7 + 1e-12
    assert "no exact legal-centre offset" in row["undefined"], row


def test_blocked_native_bound_cannot_fall_back_to_a_farther_clear_supported_axis(native):
    row = native["blocked-supported"]
    assert not row["inside"] and not row["strict_inside"], row
    (closest,) = row["closest"]
    assert closest["in_material"] and closest["kind"] == "Edge", row
    assert not closest["spline"] and closest["interior"], row
    assert closest["q"] == pytest.approx([32, 20, 10.001], rel=0, abs=1e-7)
    assert row["distance"] == pytest.approx(2, rel=0, abs=1e-7)
    assert row["bound"] == pytest.approx(1, rel=0, abs=1e-7)
    projection = row["projection"]
    assert projection["axis"] == pytest.approx([35, 20], rel=0, abs=1e-7)
    assert not projection["legal"] and not projection["inside"], row
    assert projection["clearance"] == pytest.approx(2.2, rel=0, abs=1e-7)
    assert projection["collision_mm3"] > 1, row
    (witness,) = row["witnesses"]
    assert witness["legal"] and not witness["inside"], row
    assert witness["clearance"] == pytest.approx(3, rel=0, abs=1e-7)
    assert witness["collision_mm3"] == pytest.approx(0, abs=1e-8)
    assert witness["displacement"] == pytest.approx(2.3787207476241714, rel=0, abs=1e-7)
    assert row["bound"] + 1e-7 < witness["displacement"] <= 3
    assert row["supported_endpoint"] == pytest.approx([37.5, 20.5, 10.001], rel=0, abs=1e-7)
    assert row["witness_endpoint_distance"] == pytest.approx(3, rel=0, abs=1e-7)
    assert "no exact legal-centre offset" in row["undefined"], row


def test_near_unsupported_curve_is_unknown_without_losing_another_faces_certain_hits(
    native, engine, solids
):
    step = solids["near-bsp"]
    floors = engine.refs(step, (0, 0, 14), (60, 40, 14), kind="Plane")
    pocket = engine.refs(step, (12.5, 12.5, 14), (17.5, 17.5, 14), kind="Plane")
    assert len(floors) == 2 and len(pocket) == 1
    wall = engine.refs(step, (12.5, 12.5, 14), (17.5, 17.5, 20), kind="Cylinder")
    detail = engine.run(
        engine.job(
            step,
            {"floor": floors},
            [_setup([_op("S1:10", "floor", 3, 10, 20)], _vise(0.5, centre=30))],
        )
    )["ops"]["S1:10"]
    assert detail["tool_hits"] == "unknown", detail
    assert detail["min_hits"]["tool"] > 0, detail
    assert set(wall) <= set(detail["hit_refs"]["tool"]), detail
    assert detail["obstacles"]["tool"] == ["part"], detail


def test_future_core_crosses_actual_z_but_only_own_facing_frees_it_above_cut(native):
    face, mill = native["core:face"], native["core:mill"]
    assert face["axis"] == pytest.approx([30, 20 - math.sqrt(3)], rel=0, abs=1e-9)
    assert mill["axis"] == pytest.approx(face["axis"], rel=0, abs=1e-9)
    assert face["flute_core_before_mm3"] > 1
    assert face["crossing_above_mm3"] > 1 and face["crossing_below_mm3"] > 1
    assert face["removed_core_above_mm3"] == pytest.approx(
        face["crossing_above_mm3"], rel=0, abs=1e-7
    )
    assert face["removed_core_below_mm3"] == pytest.approx(0, abs=1e-9)
    assert face["remaining_core_below_mm3"] == pytest.approx(
        face["crossing_below_mm3"], rel=0, abs=1e-7
    )
    assert face["flute_core_remaining_mm3"] == pytest.approx(0, abs=1e-9)
    assert mill["flute_core_remaining_mm3"] > 1
    assert mill["removed_core_above_mm3"] == pytest.approx(0, abs=1e-9)
    assert mill["remaining_core_above_mm3"] == pytest.approx(
        mill["crossing_above_mm3"], rel=0, abs=1e-7
    )


def test_future_core_outside_author_window_or_without_owned_opening_is_never_credited(native):
    narrow, unclaimed = native["core:narrow"], native["core:unclaimed"]
    assert narrow["removed_core_above_mm3"] > 1
    assert narrow["remaining_core_above_mm3"] > 1
    assert narrow["removed_core_outside_window_mm3"] == pytest.approx(0, abs=1e-9)
    assert narrow["removed_core_below_mm3"] == pytest.approx(0, abs=1e-9)
    assert unclaimed["crossing_above_mm3"] > 1
    assert unclaimed["removed_core_above_mm3"] == pytest.approx(0, abs=1e-9)
    assert unclaimed["removed_core_below_mm3"] == pytest.approx(0, abs=1e-9)


def test_a_multilevel_claim_does_not_free_one_columns_core_below_its_highest_cut(native):
    row = native["core:multilevel"]
    assert row["crossing_below_mm3"] > 1 and row["crossing_above_mm3"] > 1
    # The lower outer loop really sweeps some core from z8..10; this is not a
    # vacuous max-height assertion about a column wholly outside both sweeps.
    assert row["lower_sweep_below_highest_mm3"] > 1
    assert row["removed_core_below_highest_mm3"] == pytest.approx(0, abs=1e-9)
    assert row["remaining_core_below_highest_mm3"] == pytest.approx(
        row["core_below_highest_mm3"], rel=0, abs=1e-7
    )


@pytest.mark.parametrize(
    "name, key",
    [("blind-core", "core:blind-cap"), ("tilted-blind-core", "core:tilted-blind-cap")],
)
def test_blind_bore_bottom_is_a_closed_cap_not_an_owned_mouth(native, engine, solids, name, key):
    row = native[key]
    if name == "tilted-blind-core":
        assert abs(row["normal"][0]) > 5e-6 and row["normal"][2] > 1 - 1e-9
    assert row["axis"] == pytest.approx([30, 20], rel=0, abs=1e-7)
    assert row["crossing_above_mm3"] > 100
    assert row["removed_core_above_mm3"] == pytest.approx(0, abs=1e-9)
    assert row["remaining_core_above_mm3"] == pytest.approx(
        row["crossing_above_mm3"], rel=0, abs=1e-7
    )
    assert row["flute_core_remaining_mm3"] > 100
    bounds = {"x": [27.0, 33.0], "y": [17.0, 23.0], "z": [9.99, 20.0]}
    result = engine.run(_core_job(engine, solids[name], "face", bounds))
    detail = result["ops"]["S1:10"]
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert "tool_hits" not in detail["reasons"], detail
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000, rel=0, abs=1e-4)


def _core_job(engine, step, action, bounds, projection=20):
    floor = engine.refs(step, *FLOORS[step.stem], kind="Plane")
    blind = step.stem in {"blind-core", "tilted-blind-core"}
    lo, hi = ((27, 17, 9.99), (33, 23, 20)) if blind else ((20, 18, 7), (40, 22, 11))
    bore = engine.refs(step, lo, hi, kind="Cylinder")
    assert len(floor) == len(bore) == 1
    face = {
        **_op("S1:10", "floor", 3, 5, projection, holder_radius=3),
        "do": action,
        "to_z": 10,
        "stock_removal_bounds": bounds,
    }
    # Later bore metadata reserves its real column. Its future removal is not
    # credited to S1's accepted-after flute, whether horizontal or blind vertical.
    drill = {
        **_op("S2:10", "bore", 3 if blind else 2, 25, 30),
        "do": "bore",
        "hole": {"thru": False, "depth_mm": 10 if blind else 20, "entry_z_mm": 20 if blind else 40},
    }
    after = _setup([drill], _vise(0.5, centre=30), setup_id="S2")
    if not blind:
        after["frame"] = {"origin": [0, 0, 0], "x": [0, 1, 0], "y": [0, 0, 1], "z": [1, 0, 0]}
    setups = [_setup([face], _vise(0.5, centre=30)), after]
    return engine.job(step, {"floor": floor, "bore": bore}, setups, stock=BLANK)


def test_public_facing_removes_crossing_core_but_never_credits_later_drilling_or_entry_holder(
    engine, solids
):
    wide = {"x": [0.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 20.0]}
    step = solids["cross-core"]
    face, mill, narrow, holder = engine.run(
        {
            "jobs": [
                _core_job(engine, step, "face", wide),
                _core_job(engine, step, "mill", wide),
                _core_job(engine, step, "face", {**wide, "x": [0.0, 25.0]}),
                _core_job(engine, step, "face", wide, projection=4),
            ]
        }
    )["results"]
    faced = face["ops"]["S1:10"]
    assert faced["tool_hits"] == 0, faced
    # S2 receives the entire below-z10 plate, including the still-undrilled core.
    assert face["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(24000, rel=0, abs=1e-4)
    for result in (mill, narrow):
        detail = result["ops"]["S1:10"]
        assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    held = holder["ops"]["S1:10"]
    assert held["tool_hits"] == 0 and held["holder_hits"] > 0, held
    assert "part" in held["obstacles"]["holder"], held
