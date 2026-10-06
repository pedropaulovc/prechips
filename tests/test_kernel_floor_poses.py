"""Floor tool poses next to rising walls, measured on solids authored in FreeCAD.

A floor sample on a wall's floor edge stands tangent to that wall; near a concave
two-wall pocket corner it stands tangent to both, while convex island corners keep the
one-wall pose of their edge samples and gain no corner pose. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
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

# 60x40x20 block, 30x12 pocket 6 deep with sharp corners (floor z=14).
save("slot", Part.makeBox(60, 40, 20).cut(Part.makeBox(30, 12, 7, V(15, 14, 14))))
# 60x40x10 plate with two 8.8 mm square bosses 6 tall whose convex corners face each
# other across a 2.4 mm diagonal gap at (22.8, 14.8) and (25.2, 17.2).
plate = Part.makeBox(60, 40, 10)
a = Part.makeBox(8.8, 8.8, 6, V(14, 6, 10))
b = Part.makeBox(8.8, 8.8, 6, V(25.2, 17.2, 10))
save("two-bosses", plate.fuse([a, b]).removeSplitter())
"""
_AUTHORED = 2


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("floor-solids")
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


def test_floor_edge_samples_near_a_pocket_corner_are_tangent_to_both_walls(engine, solids):
    # R1: the 12 mm edges' first samples sit 0.5 mm from the corner, inside the cutter
    # radius of the other wall; the interior grid stays 1.2 mm clear of every wall.
    step = solids["slot"]
    floor = engine.refs(step, (15, 14, 14), (45, 26, 14))
    assert len(floor) == 1
    op = _op("S1:10", "floor", 1.0, 10.0, 20.0)
    detail = engine.run(
        engine.job(step, {"floor": floor}, [_setup([op], _vise(5.0, centre=30.0))])
    )["ops"]["S1:10"]
    assert detail["sample_count"] > 0
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == []


def test_convex_island_corner_gets_no_pose_reaching_a_diagonal_neighbour(engine, solids):
    # R1.5 across a 2.4 mm diagonal gap: a pose tangent to both walls of one boss's
    # convex corner would stand 1.27 mm from the other boss's corner.
    step = solids["two-bosses"]
    floor = engine.refs(step, (0, 0, 10), (60, 40, 10))
    assert len(floor) == 1
    op = _op("S1:10", "floor", 1.5, 10.0, 20.0)
    detail = engine.run(
        engine.job(step, {"floor": floor}, [_setup([op], _vise(5.0, centre=30.0))])
    )["ops"]["S1:10"]
    assert detail["sample_count"] > 0
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == []
