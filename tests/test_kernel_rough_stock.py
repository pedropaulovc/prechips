"""Rough leave and authored multipass clearing, measured on solids authored in FreeCAD.

A rough milling op leaves its ``rough_allowance_mm`` normal to the finished surface: its
poses stand that far off, derived stock keeps the leave, and a later finish of the same
faces removes it. An authored clearing box may span several passes beyond the claims'
cutter-dilated footprint, but still never removes finished material, unclaimed
disconnected pockets or not-yet-drilled hole columns. FreeCAD-backed tests run
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
"""
_AUTHORED = 4
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


def test_finish_wall_beside_raw_stock_thicker_than_the_lineage_leave_stays_debt(engine, solids):
    step = solids["island"]
    walls = _island_walls(engine, step)
    west = {"x": [0.0, 5.0], "y": [-5.0, 55.0], "z": [0.0, 20.0]}
    rough = _rough("S1:10", "west", 3.0, 25.0, 30.0, stock_removal_bounds=west)
    finish = {**_op("S2:10", "south", 3.0, 25.0, 30.0), "do": "finish_profile"}
    setups = [
        _setup([rough], ISLAND_HOLD, setup_id="S1"),
        _setup([finish], ISLAND_HOLD, setup_id="S2"),
        _setup([], ISLAND_HOLD, setup_id="S3"),
    ]
    result = engine.run(engine.job(step, walls, setups, stock=ISLAND_BLANK))
    assert "stock_reason" not in result["setups"]["S2"]
    # The finish cuts only a lineage-leave-thick skin; the raw 9.8 mm beyond it remains.
    reason = result["setups"]["S3"]["stock_reason"]
    assert "S2:10" in reason and "overstock still touches claimed wall" in reason, reason


def test_rough_floor_to_z_at_its_leave_is_that_endpoint_and_corners_stand_r_plus_a(engine, solids):
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
    # Edge and corner poses stand r + a off the pocket walls, clear of their leave.
    assert op["tool_hits"] == 0 and op["obstacles"]["tool"] == [], op
    # The pocket is cleared to its 0.2 mm floor and wall leave.
    removed = (30 - 2 * LEAVE) * (12 - 2 * LEAVE) * (6 - LEAVE)
    assert known["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000.0 - removed, abs=0.01)
    for result in (unknown, negative):
        op = result["ops"]["S1:10"]
        assert op["tool_hits"] == "unknown" and "rough_allowance_mm" in op["reasons"]["tool_hits"]
        reason = result["setups"]["S2"]["stock_reason"]
        assert "S1:10" in reason and "rough_allowance_mm" in reason, reason


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
