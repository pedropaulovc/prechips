"""Rough clearing boxes on the rocker arm's profile, measured in FreeCAD.

A rough leave's guard rounds the arc wall's edges with arc-join tori and corner spheres
that are exact offsets of the wall's own edges; measuring a cleared piece against that
wall must not fail the whole job. Two overlapping boxes from one wall, as the rocker's
S1:40 and S1:50 declare, must both clear even though the first cuts the second's far
band off from the wall.
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
# A 5 mm convex slab: straight sides x = +-40 and y = -30, and an R50 wall about (0, -40)
# meeting the sides at y = -10 with its apex at y = 10.
side = -40 + math.sqrt(50**2 - 40**2)
wire = Part.Wire([
    Part.LineSegment(V(-40, -30, 0), V(40, -30, 0)).toShape(),
    Part.LineSegment(V(40, -30, 0), V(40, side, 0)).toShape(),
    Part.Arc(V(40, side, 0), V(0, 10, 0), V(-40, side, 0)).toShape(),
    Part.LineSegment(V(-40, side, 0), V(-40, -30, 0)).toShape(),
])
slab = Part.Face(wire).extrude(V(0, 0, 5))
assert slab.isValid() and len(slab.Solids) == 1
slab.exportStep(out + "/arc.step")
"""
THICK, LEAVE = 5.0, 0.2
# The slab's section: an 80 x 20 rectangle under the R50 segment 30 off its centre.
SECTION_MM2 = 80 * 20 + 50**2 * math.acos(30 / 50) - 30 * 40
PERIMETER_MM = 80 + 2 * 20 + 2 * 50 * math.asin(40 / 50)
BLANK = {
    "shape": "box",
    "origin_mm": [-50.0, -40.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 100.0,
    "section_mm": [60.0, 8.0],
}
BOUNDS = {"x": [-50.0, 50.0], "y": [-40.0, 20.0], "z": [0.0, 8.0]}
_ISLAND = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
Part.makeBox(60, 40, 20, FreeCAD.Vector(5, 5, 0)).exportStep(out + "/island.step")
"""
ISLAND_BLANK = {
    "shape": "box",
    "origin_mm": [0.0, -5.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 70.0,
    "section_mm": [60.0, 20.0],
}


def _author(directory, source, name, executable):
    script = directory / "author.py"
    script.write_text(source, encoding="utf-8")
    process = subprocess.run(
        [executable, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    path = directory / name
    assert path.is_file(), process.stdout[-2000:] + process.stderr[-2000:]
    return path


@pytest.fixture(scope="module")
def arc(tmp_path_factory, freecad_kernel):
    return _author(tmp_path_factory.mktemp("arc-solid"), _AUTHOR, "arc.step", freecad_kernel)


@pytest.fixture(scope="module")
def island(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("island-solid")
    return _author(directory, _ISLAND, "island.step", freecad_kernel)


def test_rough_clearing_box_around_a_convex_arc_wall_leaves_only_its_rounded_leave(
    tmp_path, freecad_kernel, arc
):
    engine = Engine(tmp_path, freecad_kernel)
    wall = engine.refs(arc, (-40, -10, 0), (40, 10, THICK), kind="Cylinder")
    assert len(wall) == 1
    rough = {
        **_op("S1:10", "wall", 3.0, 25.0, 30.0),
        "do": "rough_profile",
        "rough_allowance_mm": LEAVE,
        "stock_removal_bounds": BOUNDS,
    }
    hold = _vise(5.0)
    setups = [_setup([rough], hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
    result = engine.run(engine.job(arc, {"wall": wall}, setups, stock=BLANK))
    assert result["status"] == "ok", result.get("reason")
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    # The box clears the whole blank down to the slab offset by its leave with round
    # edges, cut at the blank's floor: Steiner's formula for the convex slab, less its
    # bottom half-skin.
    assert second["stock_bbox_mm"] == [-40.2, -30.2, 0.0, 40.2, 10.2, THICK + LEAVE]
    walls = THICK * (SECTION_MM2 + PERIMETER_MM * LEAVE + math.pi * LEAVE**2)
    top = SECTION_MM2 * LEAVE + PERIMETER_MM * math.pi * LEAVE**2 / 4 + 2 * math.pi * LEAVE**3 / 3
    assert second["stock_volume_mm3"] == pytest.approx(walls + top, abs=0.01)


def test_later_clearing_box_beyond_an_earlier_one_borders_its_claim_at_setup_entry(
    tmp_path, freecad_kernel, island
):
    engine = Engine(tmp_path, freecad_kernel)
    north = engine.refs(island, (5, 45, 0), (65, 45, 20), kind="Plane")
    assert len(north) == 1

    def rough(subject, x, y_hi):
        return {
            **_op(subject, "north", 3.0, 25.0, 30.0),
            "do": "rough_profile",
            "rough_allowance_mm": LEAVE,
            "stock_removal_bounds": {"x": x, "y": [44.0, y_hi], "z": [0.0, 20.0]},
        }

    # The first box clears the north wall's skin out to y 50; the narrower second one
    # reaches the blank's edge from the same wall, its band beyond y 50 cut off from the
    # wall only by the first op's removal. The 2 mm end rails keep the stock in one piece.
    hold = _vise(5.0, centre=35.0)
    ops = [rough("S1:10", [2.0, 68.0], 50.0), rough("S1:20", [20.0, 50.0], 55.0)]
    setups = [_setup(ops, hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
    result = engine.run(engine.job(island, {"north": north}, setups, stock=ISLAND_BLANK))
    assert result["status"] == "ok", result.get("reason")
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    # Within the boxes' union (66 x 6 plus 30 x 5) only the wall's leave stays: the island
    # band from y 44 to 45, the 0.2 mm skin and its two rounded convex corners. The first
    # box's clearing outside the second stays cleared.
    kept = 60.4 * 1.0 + 60.0 * LEAVE + 2 * math.pi * LEAVE**2 / 4
    assert second["stock_volume_mm3"] == pytest.approx(
        70 * 60 * 20 - 20 * (66 * 6 + 30 * 5 - kept), abs=0.01
    )
