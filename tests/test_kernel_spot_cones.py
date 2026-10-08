"""Spots and pointed drills cut with their point cone and full-radius body.

A spot's cone apex stands at its tip (entry minus depth); a drill's depth locates its
full-diameter body, so its apex is a point length P = r / tan(point_angle / 2) lower.
Each cone widens by tan(point_angle / 2) per mm until the cutter radius. A spot's own
removal never widens its future bore, so an over-deep spot hits that finished wall;
finished material beside the hole stays a flute obstacle; an unknown point angle is
debt. FreeCAD-backed tests skip without ``freecadcmd``.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import HOLE_BLANK, Engine, _op, _setup, _vise

_AUTHOR = r"""
import math, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

bore = Part.makeCylinder(2.286, 22, V(30, 20, -1))
# 60x40x20 plate with an R2.286 through bore at (30, 20).
save("plate", Part.makeBox(60, 40, 20).cut(bore))
# The same bore under an R6 recess 2 deep, with an unclaimed R0.5 pin standing on the
# recess floor 3..4 mm from the bore axis: tall enough to meet the spot cone's flank,
# or so low that only a gross cylinder would reach it.
recessed = Part.makeBox(60, 40, 20).cut(bore).cut(Part.makeCylinder(6, 3, V(30, 20, 18)))
for name, height in (("pin-tall", 1.9), ("pin-low", 0.8)):
    pin = Part.makeCylinder(0.5, height, V(33.5, 20, 18))
    save(name, recessed.fuse(pin).removeSplitter())
# A 118 degree R3.25 drill's blind hole: full diameter z 10..20, point apex below z 10.
point = 3.25 / math.tan(math.radians(59))
drilled = Part.makeCylinder(3.25, 11, V(30, 20, 10)).fuse(
    Part.makeCone(3.25, 0, point, V(30, 20, 10), V(0, 0, -1))
)
save("drilled", Part.makeBox(60, 40, 20).cut(drilled).removeSplitter())
# The R2.286 through bore 3 mm inside the rear (+Y) edge, beside the fixed jaw.
save("edge", Part.makeBox(60, 40, 20).cut(Part.makeCylinder(2.286, 22, V(30, 37, -1))))
# Two such 118 degree blind holes at x 20 and 40: each one's cap is unrelated to the other.
pair = Part.makeBox(60, 40, 20)
for x in (20, 40):
    pair = pair.cut(
        Part.makeCylinder(3.25, 11, V(x, 20, 10)).fuse(
            Part.makeCone(3.25, 0, point, V(x, 20, 10), V(0, 0, -1))
        )
    )
save("pair", pair.removeSplitter())
# The R2.286 through bore under a 90 degree R4 countersink wider than it.
sink = Part.makeCone(2.286, 4, 4 - 2.286, V(30, 20, 20 - (4 - 2.286)))
save("countersunk", Part.makeBox(60, 40, 20).cut(bore).cut(sink).removeSplitter())
# An R3.25 blind bore z 10..20 ending in a hemisphere of its own radius.
ball = Part.makeCylinder(3.25, 11, V(30, 20, 10)).fuse(Part.makeSphere(3.25, V(30, 20, 10)))
save("ball", Part.makeBox(60, 40, 20).cut(ball.removeSplitter()).removeSplitter())
"""
HOLD = _vise(5.0, centre=30.0)
RADIUS, SLOPE = 4.7625, math.tan(math.radians(60.0))  # 3/8 in spot, 120 degree point
BORE = 2.286
DRILL = 3.25


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("spot-solids")
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
    assert len(paths) == 8, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _spot(depth, entry=20.0, angle=120.0):
    return {
        **_op("S1:10", "hole", RADIUS, 12.0, 31.0),
        "do": "spot",
        "hole": {"thru": True, "depth_mm": depth, "entry_z_mm": entry, "point_angle_deg": angle},
    }


def _drill(angle=118.0):
    return {
        **_op("S1:10", "hole", DRILL, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": False, "depth_mm": 10.0, "entry_z_mm": 20.0, "point_angle_deg": angle},
    }


def _bore(engine, step, top):
    return engine.refs(step, (30 - BORE, 20 - BORE, 0), (30 + BORE, 20 + BORE, top), "Cylinder")


def _drilled(engine, step):
    """The drilled hole's full-diameter bore; its point cone stays unclaimed."""
    hole = engine.refs(step, (30 - DRILL, 20 - DRILL, 10), (30 + DRILL, 20 + DRILL, 20), "Cylinder")
    assert len(hole) == 1
    return hole


def _cone(engine, step, x=30.0):
    """The drilled hole's own point cone below its bore."""
    cone = engine.refs(step, (x - DRILL, 20 - DRILL, 0), (x + DRILL, 20 + DRILL, 10), "Cone")
    assert len(cone) == 1
    return cone


def _plate(engine, step, op, features=None, hold=HOLD):
    setups = [_setup([op], hold, setup_id="S1"), _setup([], HOLD, setup_id="S2")]
    features = features or {"hole": _bore(engine, step, 20)}
    return engine.run(engine.job(step, features, setups, stock=HOLE_BLANK))


def test_shallow_spot_cuts_only_its_point_cone_and_clears_tool_and_holder(engine, solids):
    result = _plate(engine, solids["plate"], _spot(0.6))
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] == 0 and detail["holder_hits"] == 0
    assert detail["reach_depth_mm"] == pytest.approx(0.6)
    # The 0.6 mm deep cone's mouth (R1.04) lies inside the future R2.286 bore: the next
    # stock loses only that cone, not a 0.6 mm deep R4.76 cylinder.
    cone = math.pi * (0.6 * SLOPE) ** 2 * 0.6 / 3
    removed = 48000.0 - result["setups"]["S2"]["stock_volume_mm3"]
    assert removed == pytest.approx(cone, abs=1e-4)


def test_over_deep_spot_hits_its_own_finished_bore_wall_instead_of_widening_it(engine, solids):
    step = solids["plate"]
    result = _plate(engine, step, _spot(5.0))
    detail = result["ops"]["S1:10"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20), "Plane")
    assert detail["tool_hits"] > 0 and detail["obstacles"]["tool"] == ["part"]
    assert top[0] in detail["hit_refs"]["tool"]
    # Only the cone's part inside the future bore is cut: the cone below the bore
    # radius, then the bore's own section up to the entry.
    rise = BORE / SLOPE
    removed = 48000.0 - result["setups"]["S2"]["stock_volume_mm3"]
    assert removed == pytest.approx(math.pi * BORE**2 * (rise / 3 + 5.0 - rise), abs=1e-4)


@pytest.mark.parametrize("name, hits", [("pin-tall", True), ("pin-low", False)])
def test_unclaimed_neighbouring_boss_is_hit_only_where_the_cone_reaches_it(
    engine, solids, name, hits
):
    step = solids[name]
    pin = engine.refs(step, (33, 19.5, 18), (34, 20.5, 19.9))
    assert pin
    features = {"hole": _bore(engine, step, 18)}
    setups = [_setup([_spot(0.6, entry=18.0)], HOLD)]
    detail = engine.run(engine.job(step, features, setups))["ops"]["S1:10"]
    if hits:
        # Its own removal never deletes the unclaimed pin from the flute obstacles.
        refs = set(detail["hit_refs"]["tool"])
        assert detail["tool_hits"] > 0 and refs and refs <= set(pin)
    else:
        # A gross R4.76 cylinder from the tip would hit this pin; the cone's flank and
        # the body above its full-radius rise both pass it.
        assert detail["tool_hits"] == 0 and detail["hit_refs"]["tool"] == []


def test_pointed_drill_removes_its_body_and_point_and_clears_its_own_cone(engine, solids):
    step = solids["drilled"]
    hole = _drilled(engine, step)
    result = _plate(engine, step, _drill(), {"hole": hole})
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] == 0 and detail["holder_hits"] == 0
    point = DRILL / math.tan(math.radians(59.0))
    assert detail["reach_depth_mm"] == pytest.approx(10.0 + point, abs=1e-4)
    removed = 48000.0 - result["setups"]["S2"]["stock_volume_mm3"]
    expected = math.pi * DRILL**2 * (10.0 + point / 3)
    assert removed == pytest.approx(expected, abs=1e-3)


def test_pointed_drill_claiming_its_own_point_cap_keeps_known_clear_facts(engine, solids):
    # The cap is the drill's own cut, not an internal corner or a null own-face offset.
    step = solids["drilled"]
    # A straight-shank drill: its body runs on past the flutes at the cutting diameter.
    drill = {**_drill(), "shank_radius_mm": DRILL, "shank_from_mm": 25.0}
    result = _plate(engine, step, drill, {"hole": _drilled(engine, step) + _cone(engine, step)})
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] == 0 and detail["holder_hits"] == 0
    assert detail["corner_radii_mm"] == [] and detail["reasons"] == {}
    point = DRILL / math.tan(math.radians(59.0))
    removed = 48000.0 - result["setups"]["S2"]["stock_volume_mm3"]
    assert removed == pytest.approx(math.pi * DRILL**2 * (10.0 + point / 3), abs=1e-3)


@pytest.mark.parametrize("angle, depth", [(90.0, 10.0), (100.0, 10.0), (118.0, 11.0)])
def test_sharper_or_deeper_point_still_hits_its_finished_cap(engine, solids, angle, depth):
    # Each such point's apex lies below the finished 118 degree cap's apex.
    step = solids["drilled"]
    op = _drill(angle)
    op["hole"]["depth_mm"] = depth
    result = _plate(engine, step, op, {"hole": _drilled(engine, step) + _cone(engine, step)})
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] > 0 and detail["obstacles"]["tool"] == ["part"]
    assert detail["corner_radii_mm"] == [] and "tool_hits" not in detail["reasons"]


def test_unrelated_cap_keeps_its_corner_and_own_face_debt(engine, solids):
    step = solids["pair"]
    hole = engine.refs(step, (20 - DRILL, 20 - DRILL, 10), (20 + DRILL, 20 + DRILL, 20), "Cylinder")
    assert len(hole) == 1
    detail = _plate(engine, step, _drill(), {"hole": hole + _cone(engine, step, 40.0)})["ops"][
        "S1:10"
    ]
    assert detail["corner_radii_mm"] == "unknown"
    assert "concave Cone surface" in detail["reasons"]["corner_radii_mm"]
    assert detail["tool_hits"] != 0


def test_another_op_never_borrows_a_hole_ops_own_cap_exemption(engine, solids):
    step = solids["drilled"]
    hole = _drilled(engine, step) + _cone(engine, step)
    mill = _op("S1:20", "cap", DRILL, 25.0, 30.0)
    features = {"hole": hole, "cap": hole}
    setups = [_setup([_drill(), mill], HOLD)]
    ops = engine.run(engine.job(step, features, setups, stock=HOLE_BLANK))["ops"]
    assert ops["S1:10"]["tool_hits"] == 0 and ops["S1:10"]["corner_radii_mm"] == []
    # A mill on the same bore and cone keeps the cone's corner and own-face offset debt,
    # not the drill's own-cap stock region.
    assert ops["S1:20"]["corner_radii_mm"] == "unknown"
    assert ops["S1:20"]["tool_hits"] == "unknown"


def test_wider_countersink_is_not_the_bores_own_cap(engine, solids):
    step = solids["countersunk"]
    sink = engine.refs(step, (26, 16, 18), (34, 24, 20), "Cone")
    assert len(sink) == 1
    detail = _plate(engine, step, _spot(0.6), {"hole": _bore(engine, step, 20) + sink})["ops"][
        "S1:10"
    ]
    assert detail["corner_radii_mm"] == "unknown"
    assert "concave Cone surface" in detail["reasons"]["corner_radii_mm"]


@pytest.mark.parametrize("depth, hits", [(10.0, False), (11.0, True)])
def test_spherical_cap_is_the_holes_own_without_a_spherical_tool_profile(
    engine, solids, depth, hits
):
    # The hemisphere caps the bore exactly, so it is no internal corner. No spherical tool
    # profile is inferred: the 118 degree point stays a cone, wholly above the hemisphere
    # at the authored depth, meeting its flank near the rim only 1 mm deeper.
    step = solids["ball"]
    ball = engine.refs(step, (30 - DRILL, 20 - DRILL, 0), (30 + DRILL, 20 + DRILL, 10), "Sphere")
    assert len(ball) == 1
    op = _drill()
    op["hole"]["depth_mm"] = depth
    result = _plate(engine, step, op, {"hole": _drilled(engine, step) + ball})
    detail = result["ops"]["S1:10"]
    assert detail["corner_radii_mm"] == [] and "tool_hits" not in detail["reasons"]
    if hits:
        assert detail["tool_hits"] > 0 and detail["obstacles"]["tool"] == ["part"]
    else:
        assert detail["tool_hits"] == 0 and detail["holder_hits"] == 0
        point = DRILL / math.tan(math.radians(59.0))
        removed = 48000.0 - result["setups"]["S2"]["stock_volume_mm3"]
        assert removed == pytest.approx(math.pi * DRILL**2 * (10.0 + point / 3), abs=1e-3)


@pytest.mark.parametrize("depth, jaw", [(0.6, False), (2.0, True)])
def test_spot_cone_meets_a_jaw_only_where_its_flank_reaches_it(engine, solids, depth, jaw):
    # The fixed jaw stands 0.5 above the part, 3 mm from the spot axis: a gross R4.76
    # cylinder from either tip reaches it, but a 0.6 deep cone is only 3 mm wide 1.73
    # above its tip at z 19.4, clear over the jaw top; a 2 deep cone reaches it at 19.73.
    step = solids["edge"]
    hole = engine.refs(step, (30 - BORE, 37 - BORE, 0), (30 + BORE, 37 + BORE, 20), "Cylinder")
    result = _plate(engine, step, _spot(depth), {"hole": hole}, _vise(20.5, centre=30.0))
    detail = result["ops"]["S1:10"]
    jaws = {"fixed_jaw", "moving_jaw"} & set(detail["obstacles"]["tool"])
    assert detail["holder_hits"] == 0
    if jaw:
        assert detail["tool_hits"] > 0 and jaws == {"fixed_jaw"}
    else:
        assert detail["tool_hits"] == 0 and not jaws


@pytest.mark.parametrize("action", ["spot", "drill"])
@pytest.mark.parametrize("angle", ["unknown", 180.0])
def test_unknown_point_angle_leaves_access_and_later_stock_unknown(engine, solids, action, angle):
    if action == "spot":
        result = _plate(engine, solids["plate"], _spot(0.6, angle=angle))
    else:
        step = solids["drilled"]
        hole = _drilled(engine, step)
        result = _plate(engine, step, _drill(angle), {"hole": hole})
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] == "unknown" and detail["holder_hits"] == "unknown"
    assert "point_angle_deg" in detail["reasons"]["tool_hits"]
    assert "stock_volume_mm3" not in result["setups"]["S2"]
    assert "point_angle_deg" in result["setups"]["S2"]["stock_reason"]
