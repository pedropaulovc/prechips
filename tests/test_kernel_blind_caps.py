"""A not-yet-drilled blind hole keeps its whole void, cap included, as stock for its op.

A bounded profile that claims a part's outer walls removes the overstock around it but
reserves each known hole bore's nominal column, extended over a drill-point cone or
ball-end sphere cap that shares an edge with the bore, sits on its axis and stays
within its radius. A coaxial cone reaching outside the bore radius is not a cap.
FreeCAD-backed tests skip without ``freecadcmd``.
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

# A 50x30x20 part inside a 60x40 blank, with an R3.25 hole from its top face.
part = Part.makeBox(50, 30, 20, V(5, 5, 0))
# Blind 10 mm bore ending in a 118 degree drill-point cone.
tip = R / math.tan(math.radians(59.0))
drill = Part.makeCylinder(R, 11, V(30, 20, 10)).fuse(Part.makeCone(0, R, tip, V(30, 20, 10 - tip)))
save("drill-cone", part.cut(drill).removeSplitter())
# Blind 10 mm bore ending in an R5 spherical dish whose pole is inside its face.
centre = V(30, 20, 10 + math.sqrt(5.0**2 - R**2))
dish = Part.makeSphere(5.0, centre, V(1, 1, 1)).common(Part.makeCylinder(6, 10, V(30, 20, 0)))
save("ball-cap", part.cut(Part.makeCylinder(R, 11, V(30, 20, 10)).fuse(dish)).removeSplitter())
# Through bore opening into a coaxial R6 back countersink 2.75 mm deep at the bottom.
sink = Part.makeCylinder(R, 21, V(30, 20, 0)).fuse(Part.makeCone(6, R, 6 - R, V(30, 20, 0)))
save("back-sink", part.cut(sink).removeSplitter())
"""
R = 3.25
HOLD = _vise(5.0, centre=30.0)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("cap-solids")
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
    assert len(paths) == 3, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _profile_then_hole(engine, step, hole, low, hole_meta):
    """S2's stock after S1 rough-profiles the four outer walls over the blank's height."""
    walls = [
        ref
        for lo, hi in (
            ((5, 5, 0), (5, 35, 20)),
            ((55, 5, 0), (55, 35, 20)),
            ((5, 5, 0), (55, 5, 20)),
            ((5, 35, 0), (55, 35, 20)),
        )
        for ref in engine.refs(step, lo, hi, kind="Plane")
    ]
    assert len(walls) == 4 and hole
    profile = {
        **_op("S1:10", "walls", 5.0, 25.0, 30.0),
        "do": "rough_profile",
        "stock_removal_bounds": {"x": [0.0, 60.0], "y": [0.0, 40.0], "z": [low, 20.0]},
    }
    drill = {**_op("S2:10", "hole", R, 25.0, 30.0), "do": "drill", "hole": hole_meta}
    blank = {
        "shape": "box",
        "origin_mm": [0.0, 0.0, low],
        "axis": [1.0, 0.0, 0.0],
        "section_axis": [0.0, 1.0, 0.0],
        "length_mm": 60.0,
        "section_mm": [40.0, 20.0 - low],
    }
    setups = [_setup([profile], HOLD, setup_id="S1"), _setup([drill], HOLD, setup_id="S2")]
    job = engine.job(step, {"walls": walls, "hole": hole}, setups, stock=blank)
    return engine.run(job)["setups"]["S2"]


@pytest.mark.parametrize(
    "name, cap_kind",
    [("drill-cone", "Cone"), ("ball-cap", "Sphere")],
)
def test_profile_keeps_a_blind_hole_cap_core_for_its_own_op(engine, solids, name, cap_kind):
    step = solids[name]
    bore = engine.refs(step, (26.75, 16.75, 10), (33.25, 23.25, 20), kind="Cylinder")
    cap = engine.refs(step, (26.75, 16.75, 8), (33.25, 23.25, 10), kind=cap_kind)
    assert len(bore) == 1 and cap
    blind = {"thru": False, "entry_z_mm": 20.0, "depth_mm": 10.0}
    row = _profile_then_hole(engine, step, bore + cap, 0.0, blind)
    # The overstock ring is gone; the bore and its cap stay solid stock for the drill.
    assert "stock_reason" not in row, row.get("stock_reason")
    assert row["stock_volume_mm3"] == pytest.approx(50 * 30 * 20, abs=0.05)


def test_coaxial_cone_outside_the_bore_radius_is_not_reserved(engine, solids):
    step = solids["back-sink"]
    bore = engine.refs(step, (26.75, 16.75, 2.75), (33.25, 23.25, 20), kind="Cylinder")
    assert len(bore) == 1
    row = _profile_then_hole(engine, step, bore, -2.0, {"thru": True, "entry_z_mm": 20.0})
    # The countersink void below the bore is cleared with the slab under the part; only
    # the bore's own column (and its LIFT-thick foot into the countersink) remains.
    sink = math.pi * 2.75 / 3 * (6.0**2 + 6.0 * R + R**2)
    expected = 50 * 30 * 20 - sink + math.pi * R**2 * 1e-3
    assert "stock_reason" not in row, row.get("stock_reason")
    assert row["stock_volume_mm3"] == pytest.approx(expected, abs=0.05)
