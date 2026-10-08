"""Rough leave and authored multipass clearing, measured on solids authored in FreeCAD.

A rough milling op leaves its ``rough_allowance_mm`` normal to the finished surface: its
poses stand that far off, derived stock keeps the leave, and a later finish of the same
faces removes it. An authored clearing box may span several passes beyond the claims'
cutter-dilated footprint, but still never removes finished material, unclaimed
disconnected pockets or not-yet-drilled hole columns. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it; a witness
script loads that same source to test points of an op's output stock against the room
its cutter has to stand clear of what that op may not enter.
"""

import json
import math
import os
import subprocess

import pytest
from test_kernel_geometry import DATA, ENGINE, Engine, _op, _setup, _vise

_AUTHOR = r"""
import math
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
R = 3.25

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

# A 60x40x20 part standing 5 mm in from a blank's x ends and 10 mm in from its y sides.
save("island", Part.makeBox(60, 40, 20, V(5, 5, 0)))
save("block", Part.makeBox(60, 40, 20))
# 60x40x20 block with a 30x12 pocket 6 deep (floor z=14) and sharp corners.
save("slot", Part.makeBox(60, 40, 20).cut(Part.makeBox(30, 12, 7, V(15, 14, 14))))
# The +X half stepped down to z=10, an unclaimed 8x20 pocket 6 deep in the high half and
# a planned blind R3.25 hole 5 deep in the step floor with a 118 degree point cone.
step = Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10)))
step = step.cut(Part.makeBox(8, 20, 7, V(8, 10, 14)))
tip = R / math.tan(math.radians(59.0))
drill = Part.makeCylinder(R, 6, V(45, 20, 5)).fuse(Part.makeCone(0, R, tip, V(45, 20, 5 - tip)))
save("stepcone", step.cut(drill).removeSplitter())
# A 14 wide, 6 thick ear standing 26 tall: an R7 arch crown and an R3 cross bore through
# its thickness, both made after the wall in front of it is roughed.
ear = Part.makeBox(14, 6, 19, V(3, 20, 0))
ear = ear.fuse(Part.makeCylinder(7, 6, V(10, 20, 19), V(0, 1, 0)))
save("ear", ear.cut(Part.makeCylinder(3, 8, V(10, 19, 19), V(0, 1, 0))).removeSplitter())
# A 14 wide, 6 thick plain wall standing the blank's whole 28 mm height.
save("wall", Part.makeBox(14, 6, 28, V(3, 20, 0)))
"""
_AUTHORED = 6
LEAVE = 0.2
R = 3.25
CONE = math.pi * R**2 * (R / math.tan(math.radians(59.0))) / 3


def _blank(origin, length, section):
    return {
        "shape": "box",
        "origin_mm": list(origin),
        "axis": [1.0, 0.0, 0.0],
        "section_axis": [0.0, 1.0, 0.0],
        "length_mm": length,
        "section_mm": list(section),
    }


ISLAND_BLANK = _blank((0.0, -5.0, 0.0), 70.0, (60.0, 20.0))
ISLAND_HOLD = _vise(5.0, centre=35.0)
ISLAND_BOUNDS = {"x": [0.0, 70.0], "y": [-5.0, 55.0], "z": [0.0, 20.0]}


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("rough-solids")
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


def _rough(subject, feature, radius, flute, projection, leave=LEAVE, **extra):
    op = _op(subject, feature, radius, flute, projection)
    return {**op, "do": "rough_profile", "rough_allowance_mm": leave, **extra}


def _island_walls(engine, step):
    walls = {
        name: engine.refs(step, lo, hi, kind="Plane")
        for name, (lo, hi) in {
            "west": ((5, 5, 0), (5, 45, 20)),
            "south": ((5, 5, 0), (65, 5, 20)),
            "east": ((65, 5, 0), (65, 45, 20)),
            "north": ((5, 45, 0), (65, 45, 20)),
        }.items()
    }
    assert all(len(refs) == 1 for refs in walls.values())
    return walls


def test_rough_profile_leaves_its_normal_stock_and_a_finish_removes_it_from_its_walls(
    engine, solids
):
    step = solids["island"]
    walls = _island_walls(engine, step)
    features = {"all": sum(walls.values(), []), "corner": walls["west"] + walls["south"]}
    rough = _rough("S1:10", "all", 3.0, 25.0, 30.0, stock_removal_bounds=ISLAND_BOUNDS)
    # A finish's paired rough allowance is the leave it removes, never a leave of its own.
    finish = {**_op("S2:10", "corner", 3.0, 25.0, 30.0), "do": "finish_profile"}
    finish["rough_allowance_mm"] = LEAVE
    setups = [
        _setup([rough], ISLAND_HOLD, setup_id="S1"),
        _setup([finish], ISLAND_HOLD, setup_id="S2"),
        _setup([], ISLAND_HOLD, setup_id="S3"),
    ]
    result = engine.run(engine.job(step, features, setups, stock=ISLAND_BLANK))
    # Standing R + a off every wall, the rough flute meets neither its leave nor the blank.
    assert result["ops"]["S1:10"]["tool_hits"] == 0, result["ops"]["S1:10"]
    # The blank keeps the part offset 0.2 mm along every wall normal, rounded corners included.
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    assert second["stock_bbox_mm"] == [4.8, 4.8, 0.0, 65.2, 45.2, 20.0]
    leave = 20 * (60 * 40 + LEAVE * 2 * (60 + 40) + math.pi * LEAVE**2)
    assert second["stock_volume_mm3"] == pytest.approx(leave, abs=0.01)
    # The unbounded finish of two walls cuts their leave, the convex corner between them
    # included, so its flute meets no part material while unclaimed walls keep theirs.
    assert "part" not in result["ops"]["S2:10"]["obstacles"]["tool"], result["ops"]["S2:10"]
    third = result["setups"]["S3"]
    assert "stock_reason" not in third, third.get("stock_reason")
    skin = 20 * (LEAVE * (40 + 60) + 3 * math.pi * LEAVE**2 / 4)
    assert third["stock_volume_mm3"] == pytest.approx(leave - skin, abs=0.01)


def test_a_bounded_rough_leaves_a_flat_skin_before_its_wall_not_a_later_arch_or_bore(
    engine, solids
):
    step = solids["ear"]
    wall = engine.refs(step, (3, 20, 0), (17, 20, 26), kind="Plane")
    assert len(wall) == 1
    blank = _blank((3.0, 0.0, 0.0), 14.0, (30.0, 28.0))
    hold = _vise(5.0, centre=10.0)
    # The free run in front of the ear, up to its wall plane; the crown behind stays raw.
    run = {"x": [3.0, 17.0], "y": [0.0, 20.0], "z": [0.0, 28.0]}
    rough = {**_rough("S1:10", "wall", 3.0, 30.0, 40.0), "do": "rough_pocket"}
    setups = [
        _setup([{**rough, "stock_removal_bounds": run}], hold, setup_id="S1"),
        _setup([], hold, setup_id="S2"),
    ]
    result = engine.run(engine.job(step, {"wall": wall}, setups, stock=blank))
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    # Its passes stop the leave short of the wall plane across the whole raw crown behind
    # it: one flat 14 x 28 skin. The finished face's arch outline and the bore no setup has
    # drilled yet are not carved into it (that skin would hold about 63 mm^3, not 78).
    flat = 14 * 28 * LEAVE
    assert second["stock_volume_mm3"] == pytest.approx(14 * 10 * 28 + flat, abs=0.01)
    assert second["stock_bbox_mm"] == [3.0, 20 - LEAVE, 0.0, 17.0, 30.0, 28.0]


# Runs one job per case through the kernel, keeping the first setup's output stock, and
# asks of each sample point whether that stock holds it and how much room a cutter of the
# op's radius has to stand clear of what that op may not enter while covering it.
_WITNESS = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("cusp_kernel", os.environ["KERNEL_SOURCE"])
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
runners, run = [], kernel._Setup.run

def capture(self):
    result = run(self)
    runners.append(self)
    return result

kernel._Setup.run = capture

def rectangle(x0, y0, x1, y1, z):
    points = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.Face(Part.makePolygon(points + points[:1]))

def disc(x, y, z, radius):
    return Part.Face(Part.Wire([Part.makeCircle(radius, V(x, y, z), V(0, 0, 1))]))

with open(out + "/cases.json", encoding="utf-8") as handle:
    cases = json.load(handle)
for case in cases:
    runners.clear()
    case["status"] = kernel.run_job(case["job"])["status"]
    stock, case["reason"] = runners[0].stock_out, runners[0].stock_out_reason
    radius, leave = case["radius"], case["leave"]
    for sample in case["samples"]:
        x, y, z = sample["point"]
        # Centres a cutter may not take at this height: within its radius of the raw stock
        # behind the wall plane (y 20) or of the flat skin before the 14 mm wall and, where
        # the wall stands, within its radius of the guard's rounding of the wall's edge.
        obstacle = rectangle(0, 20, 20, 30, z).makeOffset2D(radius, 0, False, False, False)
        skin = rectangle(3, 20 - leave, 17, 20, z)
        obstacle = obstacle.fuse(skin.makeOffset2D(radius, 0, False, False, False))
        if sample["guard"]:
            obstacle = obstacle.fuse(disc(3, 20, z, radius + leave))
        sample["legal_mm2"] = disc(x, y, z, radius).cut(obstacle).Area
        sample["retained"] = stock is not None and stock.isInside(V(x, y, z), 1e-7, True)
with open(out + "/witness.json", "w", encoding="utf-8") as handle:
    json.dump(cases, handle)
"""
# (cutter radius, rough leave) pairs: a large cutter beside a thin and a thick leave, and
# cutters near the leave's own size.
PAIRS = [(3.0, 0.2), (3.0, 0.5), (0.15, 0.2), (0.5, 0.5)]


def _cusp_samples(radius, leave, z, guard=True):
    """Points in front of a wall plane at y 20 past its skin's end at x 3, at height ``z``:
    two between the cusp a cutter clearing only a sharp skin corner would leave and the one
    it leaves clearing the guard's rounding of radius ``leave`` too (both tangent to the
    plane), one beyond that and one well past both. These depths only place the points;
    the witness's legal-centre area decides which of them a cutter reaches."""
    rounded = math.sqrt((radius + leave) ** 2 - radius**2)
    sharp = math.sqrt(radius**2 - (radius - min(leave, radius)) ** 2)

    def depth(reach, t):
        return radius - math.sqrt(radius**2 - (reach - t) ** 2) if t < reach else 0.0

    if not guard:
        rounded = sharp
    middle = (leave + rounded) / 2
    points = []
    for t in (leave + 0.05, middle):
        need, short = depth(rounded, t), depth(sharp, t)
        points.append((t, (short + need) / 2 if need > short else need / 2))
    points += [(middle, (depth(rounded, middle) + leave) / 2), (rounded + 0.2, 0.01)]
    return [{"point": [3 - t, 20 - d, z], "guard": guard} for t, d in points]


@pytest.fixture(scope="module")
def witness(solids, freecad_kernel, tmp_path_factory):
    """Each case's samples with the stock its bounded rough leaves and the witness's area."""
    directory = tmp_path_factory.mktemp("cusp-witness")
    engine = Engine(directory, freecad_kernel)
    blank = _blank((0.0, 0.0, 0.0), 20.0, (30.0, 28.0))
    run = {"x": [0.0, 20.0], "y": [0.0, 20.0], "z": [0.0, 28.0]}
    hold = _vise(5.0, centre=10.0)

    def case(name, step, top, radius, leave, samples):
        wall = engine.refs(step, (3, 20, 0), (17, 20, top), kind="Plane")
        assert len(wall) == 1
        rough = _rough("S1:10", "wall", radius, 30.0, 40.0, leave, stock_removal_bounds=run)
        setups = [
            _setup([{**rough, "do": "rough_pocket"}], hold, setup_id="S1"),
            _setup([], hold, setup_id="S2"),
        ]
        job = engine.job(step, {"wall": wall}, setups, stock=blank)
        return {"name": name, "job": job, "radius": radius, "leave": leave, "samples": samples}

    cases = [
        case(f"wall r{r} a{a}", solids["wall"], 28, r, a, _cusp_samples(r, a, 10.0))
        for r, a in PAIRS
    ]
    # Above the ear's 26 mm crown no guard stands: the skin's sharp corner alone shapes
    # the cusp there, and the review's witness point just off that corner stays.
    crown = [{"point": [2.99, 19.99, 27.0], "guard": False}]
    crown += _cusp_samples(3.0, LEAVE, 27.0, guard=False)
    cases.append(
        case("ear", solids["ear"], 26, 3.0, LEAVE, crown + _cusp_samples(3.0, LEAVE, 10.0))
    )
    (directory / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    script = directory / "witness.py"
    script.write_text(_WITNESS, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=1800,
        env={**os.environ, "KERNEL_SOURCE": str(ENGINE)},
    )
    report = directory / "witness.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return {case["name"]: case for case in json.loads(report.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("name", [*(f"wall r{r} a{a}" for r, a in PAIRS), "ear"])
def test_a_bounded_rough_keeps_what_no_legal_cutter_centre_reaches_past_its_skins_end(
    witness, name
):
    # Raw stock stands behind the wall plane past both of the wall's ends, so the passes
    # run on at the plane there and step up onto the flat skin. A point stays exactly when
    # no centre clear of that stock, the skin and the guard's rounding covers it: the op's
    # own cutter must clear all three at once, and no later op is credited with it.
    case = witness[name]
    assert case["status"] == "ok" and case["reason"] is None, case
    unreached = [s for s in case["samples"] if s["legal_mm2"] < 1e-9]
    reached = [s for s in case["samples"] if s["legal_mm2"] > 1e-6]
    assert unreached and reached, case["samples"]
    assert len(unreached) + len(reached) == len(case["samples"]), case["samples"]
    assert [s for s in unreached if not s["retained"]] == []
    assert [s for s in reached if s["retained"]] == []


@pytest.mark.parametrize(
    ("start", "met"),
    [
        # The side box stands behind the front wall's plane: never credited with the cusp
        # the front cutter leaves past the wall's edge, its flute meets it at the corner.
        (20.0, True),
        # Its author declares it reaching in front of the plane by the leave, so it clears
        # that cusp as its cutter turns the corner.
        (20.0 - LEAVE, False),
    ],
)
def test_a_flat_skin_stops_at_its_walls_edge_and_only_a_box_covering_its_cusp_clears_it(
    engine, solids, start, met
):
    step = solids["ear"]
    front = engine.refs(step, (3, 20, 0), (17, 20, 26), kind="Plane")
    side = engine.refs(step, (3, 20, 0), (3, 26, 19), kind="Plane")
    assert len(front) == 1 and len(side) == 1
    blank = _blank((0.0, 0.0, 0.0), 20.0, (30.0, 28.0))
    hold = _vise(5.0, centre=10.0)
    rough = {**_rough("S1:10", "front", 3.0, 30.0, 40.0), "do": "rough_pocket"}
    beside = {**_rough("S1:20", "side", 3.0, 30.0, 40.0), "do": "rough_pocket"}
    setups = [
        _setup(
            [
                {**rough, "stock_removal_bounds": {"x": [0, 20], "y": [0, 20], "z": [0, 28]}},
                {
                    **beside,
                    "stock_removal_bounds": {"x": [0, 3], "y": [start, 30], "z": [0, 28]},
                },
            ],
            hold,
            setup_id="S1",
        ),
        _setup([], hold, setup_id="S2"),
    ]
    features = {"front": front, "side": side}
    result = engine.run(engine.job(step, features, setups, stock=blank))
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    # The front pass stops short of the front wall over its 14 mm width only, so no front
    # skin runs on past its edge. There the front cutter's own sweep leaves the cusp
    # between the skin's end and the raw stock behind the plane. Below the ear's crown it
    # reaches this far past it, to where the cutter touches the plane while clear of the
    # guard's rounding of the wall's edge.
    reach = math.sqrt((3.0 + LEAVE) ** 2 - 3.0**2)
    side_op = result["ops"]["S1:20"]
    assert ("part" in side_op["obstacles"]["tool"]) is met, side_op
    # Left in place, the cusp is the work's edge; cleared, the side box's own skin is.
    assert second["stock_bbox_mm"][0] == pytest.approx(3 - reach if met else 3 - LEAVE, abs=1e-4)


# What a bounded rough keeps past a flat skin's end is certain where the faces of a
# level section meet: two of the pivot bracket's S1:20 sections (leave 0.3, cutter radius
# 4.7625) as the cusp handed them to ``_out_of_reach``, dumped as one compound of the band,
# the reach, the legal-centre neighbourhood and then the faces of what stays. In "arcs"
# (lines and arcs, eight faces nested in one another) the cuts tool by tool, and in
# "b-spline" (the guard's rounding of the wall's edge a B-spline, its faces sharing the
# rounding's ends) each edge's own disc about a shared end, left a legal centre a sliver
# within the cutter's radius of what stays, and the stock unknown. The witness never asks
# the kernel: it rebuilds what stays from plain rectangles and the rounding's circle,
# a hair smaller and a hair larger than the dump (checked against it), grows them with
# OCC's own arc offsets and measures how much room a cutter has to cover each sample.
_REACH = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("reach_kernel", os.environ["KERNEL_SOURCE"])
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
with open(out + "/case.json", encoding="utf-8") as handle:
    case = json.load(handle)
dump = Part.Shape()
dump.importBrep(case["brep"])
band, reach, centres, *obstacle = dump.childShapes()
radius = case["radius"]
try:
    kept = kernel._out_of_reach(obstacle, band, reach, centres, radius)
    case["reason"] = None
except ValueError as exc:
    kept, case["reason"] = [], str(exc)

def rectangle(x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    return Part.Face(Part.makePolygon(points + points[:1]))

def disc(x, y, size):
    return Part.Face(Part.Wire([Part.makeCircle(size, V(x, y, 0))]))

def stays(slack, grow=0.0):
    rectangles = [rectangle(*corners) for corners in case["rectangles"]]
    if grow:
        rectangles = [face.makeOffset2D(grow, 0, False, False, False) for face in rectangles]
    discs = [disc(x, y, size + slack + grow) for x, y, size in case["guards"]]
    return rectangles[0].fuse(rectangles[1:] + discs)

tol = case["tol"]
union = obstacle[0].fuse(obstacle[1:])
case["dump_outside_witness"] = sum(face.cut(stays(tol)).Area for face in obstacle)
case["witness_outside_dump"] = stays(-tol).cut(union).Area
least, most = stays(tol, radius), stays(-tol, radius)
for sample in case["samples"]:
    point = V(*sample["point"], 0)
    room = disc(point.x, point.y, radius).common(centres)
    sample["legal_least"] = room.cut(least).Area
    sample["legal_most"] = room.cut(most).Area
    sample["retained"] = any(face.isInside(point, 1e-7, True) for face in kept)
with open(out + "/kept.json", "w", encoding="utf-8") as handle:
    json.dump(case, handle)
"""


def _reach_case(name):
    radius, leave = 4.7625, 0.3
    if name == "arcs":
        # The wall plane x -8, its skin to x -8.3 above y -3, its rounding about (-8, -3).
        return {
            "radius": radius,
            "rectangles": [(-8.3, -3.0, 6.2875, 11.2875), (-8.0, -3.3, 6.2875, 11.2875)],
            "guards": [(-8.0, -3.0, leave)],
            # Inside the rounding, beside it past the skin's corner, below the floor's
            # corner and far down the band.
            "samples": [
                {"point": [-8.1, -3.1], "kept": True},
                {"point": [-8.05, -3.25], "kept": True},
                {"point": [-8.25, -3.25], "kept": False},
                {"point": [-8.02, -3.4], "kept": False},
                {"point": [-8.15, -8.0], "kept": False},
            ],
        }
    # The wall plane y -3, its skin to y -3.3 out to x 7, its rounding about (6.9875, -3).
    tangent = 6.9875 + math.sqrt((radius + leave) ** 2 - radius**2)
    return {
        "radius": radius,
        "rectangles": [(-7.2875, -3.0, 9.0, 4.0), (-7.0, -3.3, 7.0, -3.0)],
        "guards": [(6.9875, -3.0, leave), (-6.9875, -3.0, leave)],
        # Just in front of the plane short of the cutter tangent to the plane and the
        # rounding (beyond its disc by 0.04 and 0.012), past it, and well past it lower
        # in the band.
        "samples": [
            {"point": [8.0, -3.01], "kept": True},
            {"point": [8.3, -3.005], "kept": True},
            {"point": [tangent + 0.2, -3.01], "kept": False},
            {"point": [10.5, -3.2], "kept": False},
        ],
    }


@pytest.mark.parametrize("name", ["arcs", "b-spline"])
def test_a_skin_ends_cusp_is_certain_where_its_sections_faces_meet(freecad_kernel, tmp_path, name):
    case = {
        **_reach_case(name),
        "brep": str(DATA / "cusp-reach" / f"pivot-bracket-{name}.brep"),
        # The rounding's B-spline strays up to 1.4e-4 mm inside its circle.
        "tol": 2e-4,
    }
    (tmp_path / "case.json").write_text(json.dumps(case), encoding="utf-8")
    script = tmp_path / "reach.py"
    script.write_text(_REACH, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
        env={**os.environ, "KERNEL_SOURCE": str(ENGINE)},
    )
    report = tmp_path / "kept.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    result = json.loads(report.read_text(encoding="utf-8"))
    # The witness brackets the dump: what stays lies inside its larger shape and holds its
    # smaller one, so the room it leaves a cutter brackets the dump's.
    assert result["dump_outside_witness"] < 1e-8, result
    assert result["witness_outside_dump"] < 1e-8, result
    samples = result["samples"]
    assert [s for s in samples if s["kept"] and s["legal_most"] > 1e-9] == []
    assert [s for s in samples if not s["kept"] and s["legal_least"] < 1e-6] == []
    assert result["reason"] is None, result["reason"]
    assert [s for s in samples if s["retained"] != s["kept"]] == []


# A level face of legal cutter centres can carry a boundary arc shorter than PLANE_TOL:
# the rocker arm's S1:40 cusp left one 6.2e-7 mm long on a circle of R4.9625. OCC cannot
# pass an arc through three points that close, so the arc's band either raised there
# ("Intersection cannot be computed") and left the stock unknown, or, as on this square
# whose corner is such an arc, came out a stray sliver that left the discs grown back
# from the legal centres short of the square grown by the radius. Grown by ``radius``,
# the face is that grown square, to the sliver no wider than half the arc's length that
# its ends' discs miss. The witness never asks the kernel: it grows the plain square with
# rectangles and discs, and measures the growth as the cusp does, in one Boolean with
# all its faces, and face by face.
_SHORT_ARC = r"""
import importlib.util, json, math, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("arc_kernel", os.environ["KERNEL_SOURCE"])
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
with open(out + "/case.json", encoding="utf-8") as handle:
    case = json.load(handle)
size, length, radius = case["arc_radius"], case["arc_length"], case["radius"]
# The 10 x 10 square's top right corner (10, 10) starts the short arc, centred inside.
square = [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)]
start = math.radians(45.0)
sweep = length / size
centre = square[2] - V(math.cos(start), math.sin(start), 0) * size
arc = Part.ArcOfCircle(Part.Circle(centre, V(0, 0, 1), size), start, start + sweep).toShape()
p, q = arc.Vertexes[0].Point, arc.Vertexes[1].Point
line = lambda a, b: Part.LineSegment(a, b).toShape()
edges = [line(square[0], square[1]), line(square[1], p), arc, line(q, square[3])]
face = Part.Face(Part.Wire(edges + [line(square[3], square[0])]))
case["arc_edge_mm"] = arc.Length
case["corner_gap_mm"] = (p - square[2]).Length

def disc(point, r):
    return Part.Face(Part.Wire([Part.makeCircle(r, point)]))

def stadium(a, b, r):
    side = V(-(b - a).y, (b - a).x, 0).normalize() * r
    points = [a + side, b + side, b - side, a - side]
    return Part.Face(Part.makePolygon(points + points[:1]))

ring = square + square[:1]
witness = Part.Face(Part.makePolygon(ring)).fuse(
    [stadium(a, b, radius) for a, b in zip(ring, ring[1:])] + [disc(c, radius) for c in square]
).removeSplitter()
middle = start + sweep / 2
outward = V(math.cos(middle), math.sin(middle), 0)
beside = centre + outward * (size + radius - 0.01)
past = centre + outward * (size + radius + 0.01)
for outer in (True, False):
    key = "outer" if outer else "inner"
    try:
        grown = kernel._grown([face], radius, outer=outer)
    except Exception as exc:
        case[key] = {"reason": f"{type(exc).__name__}: {exc}"}
        continue
    case[key] = {
        "reason": None,
        "witness_uncovered": witness.Area - witness.common(grown).Area,
        "witness_left": sum(piece.Area for piece in witness.cut(grown).Faces),
        "grown_outside": sum(piece.Area - piece.common(witness).Area for piece in grown),
        "beside_arc_inside": any(piece.isInside(beside, 1e-9, True) for piece in grown),
        "past_arc_inside": any(piece.isInside(past, 1e-9, True) for piece in grown),
    }
case["witness_area"] = witness.Area
with open(out + "/grown.json", "w", encoding="utf-8") as handle:
    json.dump(case, handle)
"""


def test_a_face_whose_boundary_arc_is_shorter_than_plane_tol_grows_by_the_radius(
    freecad_kernel, tmp_path
):
    radius = 4.7625
    case = {"arc_radius": 4.9625, "arc_length": 6.2e-7, "radius": radius}
    (tmp_path / "case.json").write_text(json.dumps(case), encoding="utf-8")
    script = tmp_path / "short_arc.py"
    script.write_text(_SHORT_ARC, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(ENGINE)},
    )
    report = tmp_path / "grown.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["arc_edge_mm"] == pytest.approx(6.2e-7, rel=1e-3)
    assert result["corner_gap_mm"] < 1e-12
    # The 10 x 10 square grown by the radius: its sides' bands and corners' discs, to
    # OCC's integration of the discs' areas.
    area = 100 + 40 * radius + math.pi * radius**2
    assert result["witness_area"] == pytest.approx(area, abs=1e-4)
    for key in ("outer", "inner"):
        grown = result[key]
        assert grown["reason"] is None, grown
        # None misses or adds more than the arc's sliver and OCC's integration of areas.
        assert grown["witness_uncovered"] < 1e-4, grown
        assert grown["witness_left"] < 1e-4, grown
        assert grown["grown_outside"] < 1e-4, grown
        assert grown["beside_arc_inside"] and not grown["past_arc_inside"], grown


# The rocker arm's S2:40 bounded rough (leave 0.2, cutter radius 4.7625) as it met its
# skins' eight ends: the stock and what its box removes before the cusp, dumped, with the
# steps. Taking a level section of a prism swept down from a fillet face with the
# neighbourhood box's own face, whose side lies on the prism's, OCC failed ("Null shape");
# faces of what it keeps there start and stop a thousandth of a millimetre apart, and a
# cusp slab that thin between them left the box's own removal, less the cusp, cutting an
# invalid piece from the stock. Either left the stock unknown. The kernel's own removal
# judges the piece; the volumes are checked apart from it.
_SLABS = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("slab_kernel", os.environ["KERNEL_SOURCE"])
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
with open(out + "/case.json", encoding="utf-8") as handle:
    case = json.load(handle)
with open(case["steps"], encoding="utf-8") as handle:
    dump = json.load(handle)
stock, removed = Part.Shape(), Part.Shape()
stock.importBrep(case["stock"])
removed.importBrep(case["removed"])
steps = [
    (tuple(V(*v) if isinstance(v, list) else v for v in frame), end, sign)
    for frame, end, sign in dump["steps"]
]
setup = kernel._Setup
cusps = setup._skin_cusps(setup, stock, removed, steps, dump["span"], dump["leave"], dump["radius"])
left = removed.cut(cusps[0].fuse(cusps[1:]))
pieces = [piece for piece in left.Solids if piece.Volume > kernel.HIT_MM3]
own = pieces[0].fuse(pieces[1:]) if len(pieces) > 1 else pieces[0]
kept, case["reason"] = setup._remove(stock, own, [])
kept = kept or []
case["cusps"] = [cusp.Volume for cusp in cusps]
case["kept"] = [piece.Volume for piece in kept]
case["kept_cusp"] = sum(piece.common(cusp).Volume for piece in kept for cusp in cusps)
case["stock_mm3"], case["own_mm3"] = stock.Volume, own.Volume
with open(out + "/kept.json", "w", encoding="utf-8") as handle:
    json.dump(case, handle)
"""


def test_a_skin_ends_cusp_leaves_the_box_removal_one_valid_stock_piece_beside_fillets(
    freecad_kernel, tmp_path
):
    data = DATA / "cusp-slabs"
    case = {
        "stock": str(data / "rocker-arm-stock.brep"),
        "removed": str(data / "rocker-arm-removed.brep"),
        "steps": str(data / "rocker-arm.json"),
    }
    (tmp_path / "case.json").write_text(json.dumps(case), encoding="utf-8")
    script = tmp_path / "slabs.py"
    script.write_text(_SLABS, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=900,
        env={**os.environ, "KERNEL_SOURCE": str(ENGINE)},
    )
    report = tmp_path / "kept.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["reason"] is None, result["reason"]
    # One piece, holding what the cusps keep, with the stock's volume less the removal's.
    assert len(result["cusps"]) == 8 and min(result["cusps"]) > 0, result["cusps"]
    assert len(result["kept"]) == 1, result["kept"]
    assert result["kept"][0] == pytest.approx(result["stock_mm3"] - result["own_mm3"], abs=1e-3)
    assert result["kept_cusp"] == pytest.approx(sum(result["cusps"]), abs=1e-3)


@pytest.mark.parametrize("action", ["mill", "finish_profile"])
def test_finish_wall_beside_raw_stock_thicker_than_the_lineage_leave(engine, solids, action):
    step = solids["island"]
    walls = _island_walls(engine, step)
    west = {"x": [0.0, 5.0], "y": [-5.0, 55.0], "z": [0.0, 20.0]}
    rough = _rough("S1:10", "west", 3.0, 25.0, 30.0, stock_removal_bounds=west)
    finish = {**_op("S2:10", "south", 3.0, 25.0, 30.0), "do": action}
    setups = [
        _setup([rough], ISLAND_HOLD, setup_id="S1"),
        _setup([finish], ISLAND_HOLD, setup_id="S2"),
        _setup([], ISLAND_HOLD, setup_id="S3"),
    ]
    result = engine.run(engine.job(step, walls, setups, stock=ISLAND_BLANK))
    second, third = result["setups"]["S2"], result["setups"]["S3"]
    assert "stock_reason" not in second
    if action == "mill":
        # A +Z sweep of the wall cuts only a lineage-leave-thick skin; the raw 9.8 mm
        # beyond it remains on the wall.
        reason = third["stock_reason"]
        assert "S2:10" in reason and "overstock still touches claimed wall" in reason, reason
        return
    # The profile cutter clears its 6 mm corridor beside the 60 mm wall and an r disc
    # past the open east end; the west disc meets only the rough's 0.2 mm leave strip.
    # The raw 4 mm beyond the corridor stays stock, clear of the wall.
    assert "stock_reason" not in third, third["stock_reason"]
    removed = second["stock_volume_mm3"] - third["stock_volume_mm3"]
    corridor = 20 * (60 * 6 + math.pi * 3**2 / 2)
    assert corridor < removed < corridor + 20 * LEAVE * 6, removed
    assert third["stock_bbox_mm"][1] == pytest.approx(-5.0)


def test_rough_floor_to_z_at_its_leave_is_that_endpoint(engine, solids):
    step = solids["slot"]
    floor = engine.refs(step, (15, 14, 14), (45, 26, 14))
    assert len(floor) == 1
    hold = _vise(5.0, centre=30.0)
    blank = _blank((0.0, 0.0, 0.0), 60.0, (40.0, 20.0))

    def job(leave):
        op = {**_rough("S1:10", "floor", 1.0, 10.0, 20.0, leave), "do": "rough_pocket"}
        op["to_z"] = 14.0 + LEAVE
        setups = [_setup([op], hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
        return engine.job(step, {"floor": floor}, setups, stock=blank)

    known, unknown, negative = engine.run({"jobs": [job(LEAVE), job("unknown"), job(-0.1)]})[
        "results"
    ]
    op = known["ops"]["S1:10"]
    # to_z already at floor + a is the tip: reach is 20 - 14.2, not 20 - 14.4.
    assert op["reach_depth_mm"] == pytest.approx(20.0 - 14.0 - LEAVE)
    # Sharp floor corners are not coverable by the cutter disc; their collision is
    # exercised separately. Here the endpoint and retained leave remain measurable.
    # The pocket is cleared to its 0.2 mm floor and wall leave.
    removed = (30 - 2 * LEAVE) * (12 - 2 * LEAVE) * (6 - LEAVE)
    assert known["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000.0 - removed, abs=0.01)
    for result in (unknown, negative):
        op = result["ops"]["S1:10"]
        assert op["tool_hits"] == "unknown" and "rough_allowance_mm" in op["reasons"]["tool_hits"]
        reason = result["setups"]["S2"]["stock_reason"]
        assert "S1:10" in reason and "rough_allowance_mm" in reason, reason


def test_finish_floor_to_z_above_the_floor_is_its_tip_and_its_own_cut_stops_there(engine, solids):
    step = solids["slot"]
    floor = engine.refs(step, (15, 14, 14), (45, 26, 14))
    assert len(floor) == 1
    hold = _vise(5.0, centre=30.0)
    blank = _blank((0.0, 0.0, 0.0), 60.0, (40.0, 20.0))
    spring = {**_op("S1:10", "floor", 1.0, 10.0, 20.0), "to_z": 14.1}
    full = {**_op("S1:20", "floor", 1.0, 10.0, 20.0), "to_z": 14.0}

    def job(ops):
        setups = [_setup(ops, hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
        return engine.job(step, {"floor": floor}, setups, stock=blank)

    shallow, both = engine.run({"jobs": [job([spring]), job([spring, full])]})["results"]
    finished = 48000.0 - 30 * 12 * 6
    # The spring pass stops 0.1 above the floor: that skin is real stock below its tip.
    # Sharp pocket corners still collide independently of the authored floor endpoint.
    assert shallow["ops"]["S1:10"]["reach_depth_mm"] == pytest.approx(20.0 - 14.1)
    skin = 30 * 12 * 0.1
    assert shallow["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(finished + skin, abs=0.01)
    assert both["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(finished, abs=0.01)


def test_rough_face_flute_sits_on_its_leave_while_a_low_holder_meets_raw_stock(engine, solids):
    step = solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    assert len(top) == 1
    hold = _vise(5.0, centre=30.0)
    blank = _blank((0.0, 0.0, 0.0), 60.0, (40.0, 22.0))

    def job(projection):
        op = {**_rough("S1:10", "top", 3.0, 15.0, projection), "do": "rough_face"}
        setups = [_setup([op], hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
        return engine.job(step, {"top": top}, setups, stock=blank)

    low, high = engine.run({"jobs": [job(1.0), job(3.0)]})["results"]
    for result in (low, high):
        assert result["ops"]["S1:10"]["tool_hits"] == 0, result["ops"]["S1:10"]
        # The face removes the raw top down to its leave, not to the finished face.
        second = result["setups"]["S2"]
        assert second["stock_volume_mm3"] == pytest.approx(60 * 40 * (20 + LEAVE), abs=0.01)
    # The holder still sees the setup-entry 2 mm of raw stock this op removes.
    assert low["ops"]["S1:10"]["holder_hits"] > 0
    assert high["ops"]["S1:10"]["holder_hits"] == 0


def test_wide_multipass_box_clears_known_volume_but_never_unclaimed_pockets_or_caps(engine, solids):
    step = solids["stepcone"]
    features = {
        "step": engine.refs(step, (30, 0, 10), (30, 40, 20))
        + engine.refs(step, (30, 0, 10), (60, 40, 10)),
        "hole": engine.refs(step, (41.75, 16.75, 0), (48.25, 23.25, 10), kind="Cylinder")
        + engine.refs(step, (41.75, 16.75, 0), (48.25, 23.25, 10), kind="Cone"),
    }
    assert len(features["step"]) == 2 and len(features["hole"]) == 2
    hold = _vise(5.0, centre=30.0)
    blank = _blank((0.0, 0.0, 0.0), 60.0, (40.0, 22.0))
    drill = {**_op("S2:10", "hole", R, 25.0, 30.0), "do": "drill"}
    drill["hole"] = {"thru": False, "entry_z_mm": 10.0, "depth_mm": 5.0, "point_angle_deg": 118.0}
    huge = 1e12
    # x from 20: 10 mm, more than two cutter radii, past the claims' footprint.
    wide = {"x": [20.0, huge], "y": [-huge, huge], "z": [-huge, huge]}
    pocketed = {"x": [0.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 20.0]}

    def job(bounds, radius=3.0):
        op = {**_op("S1:10", "step", 3.0, 15.0, 30.0), "stock_removal_bounds": bounds}
        op["radius_mm"] = radius
        setups = [_setup([op], hold, setup_id="S1"), _setup([drill], hold, setup_id="S2")]
        return engine.job(step, features, setups, stock=blank)

    accepted, stray, radiusless = engine.run({"jobs": [job(wide), job(pocketed), job(wide, None)]})[
        "results"
    ]
    second = accepted["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    assert "stock_removal_error" not in accepted["ops"]["S1:10"]
    # Removed: the stepped half above its floor and the 2 mm over the finished high
    # neighbour from x 20; the planned bore and its point cone stay stock for the drill.
    removed = 30 * 40 * 12 + 10 * 40 * 2 - math.pi * R**2 * 1e-3
    assert second["stock_volume_mm3"] == pytest.approx(60 * 40 * 22 - removed, abs=0.01)
    assert CONE > 1.0  # the cap alone would move the volume past the tolerance
    # Within the box, the unclaimed pocket's disconnected 8x20x6 piece is not cleared.
    reason = stray["setups"]["S2"]["stock_reason"]
    assert "S1:10" in reason and "removes 960.0 mm^3 in 1 piece(s) bordering none" in reason, reason
    # Without a measured cutter radius the clearance stays unresolved.
    assert "cutter radius" in radiusless["ops"]["S1:10"]["reasons"]["stock_removal_bounds"]
    assert "cutter radius" in radiusless["setups"]["S2"]["stock_reason"]
