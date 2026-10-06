"""Floor tool poses within a cutter radius of any concave floor edge, curved ones included.

User decision 2026-10-05: a floor sample on or within R of a concave floor/wall edge (a
pocket wall or a boss foot, straight or circular) shifts along that wall's in-plane normal
at the nearest edge point until the cutter is tangent; a concave circle at least R in
radius bounds it exactly, so a sample between an arc and a straight wall stands tangent to
both. A tool wider than its gap or circle still reports the real wall hit, never unknown.
FreeCAD-backed tests run ``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and
skip without it.
"""

import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

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
"""
_AUTHORED = 6


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
        # Arc and chord: a sample near their corner stands tangent to the circle and line.
        ("d-pocket", (24, 10, 14), (40, 30, 14)),
        # Acute cusp: a sample on one arc shifts toward the cusp until the other arc,
        # farther than R from the sample, bounds it too.
        ("lens", (26, 12, 14), (34, 28, 14)),
    ],
)
def test_samples_near_a_curved_pocket_wall_stand_tangent_inside_it(engine, solids, name, lo, hi):
    _, detail = _floor_op(engine, solids[name], lo, hi, 3.0)
    assert detail["sample_count"] > 0
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == [], detail


def test_groove_exactly_two_radii_wide_clears_both_walls(engine, solids):
    _, detail = _floor_op(engine, solids["groove"], (0, 17, 12), (60, 23, 12), 3.0)
    assert detail["sample_count"] > 0
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
