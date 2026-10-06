"""An unbounded profile op clears exactly the corridor its cutter sweeps beside its walls.

The corridor is every point within the cutter radius of its centre path (the claimed walls
offset outward by that radius): 2r beside each wall, a 2r tube about each convex join and
an r disc at each path end, from ``to_z`` up. Stock past it stays, so a concave wall never
clears its whole circle and a web wider than 2r is never parted. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import math
import re
import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup
from test_kernel_stock_prefix import BLANK, HOLD

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
island = Part.makeBox(60, 40, 20, V(5, 5, 0))
island.exportStep(out + "/island.step")
# A 2 mm deep R100 dent in the north wall, centred on x = 35.
dent = Part.makeCylinder(100, 22, V(35, 143, -1))
dented = island.cut(dent).removeSplitter()
assert dented.isValid() and len(dented.Solids) == 1
dented.exportStep(out + "/dented.step")
"""
BLANK_MM3 = 70.0 * 60.0 * 20.0  # x 0..70, y -5..55, z 0..20
WALLS = {
    "south": ((5, 5, 0), (65, 5, 20)),
    "north": ((5, 45, 0), (65, 45, 20)),
    "west": ((5, 5, 0), (5, 45, 20)),
    "east": ((65, 5, 0), (65, 45, 20)),
}


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("corridor-solids")
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


def _profile(radius, to_z=0.0):
    op = _op("S1:10", "walls", radius, 25.0, 30.0)
    return {**op, "do": "finish_profile", "to_z": to_z}


def _run(engine, step, refs, op):
    setups = [_setup([op], HOLD, setup_id="S1"), _setup([], HOLD, setup_id="S2")]
    return engine.run(engine.job(step, {"walls": refs}, setups, stock=BLANK))


def _island_walls(engine, step):
    refs = [ref for lo, hi in WALLS.values() for ref in engine.refs(step, lo, hi, kind="Plane")]
    assert len(refs) == 4
    return refs


def test_a_closed_profile_clears_its_wall_band_and_2r_tubes_about_convex_joins(engine, solids):
    # Stopping 1 mm above the floor keeps the island joined to the frame below it.
    step = solids["island"]
    result = _run(engine, step, _island_walls(engine, step), _profile(2.0, to_z=1.0))
    entry = result["setups"]["S2"]
    assert entry.get("stock_reason") is None, entry
    # 2r beside the 200 mm perimeter plus four quarter tubes of radius 2r: one 2r disc.
    corridor = 19.0 * (200.0 * 4.0 + math.pi * 4.0**2)
    assert entry["stock_volume_mm3"] == pytest.approx(BLANK_MM3 - corridor, abs=1e-2)


@pytest.mark.parametrize(("radius", "pieces"), [(2.0, 2), (3.0, 3)])
def test_a_web_is_parted_only_inside_the_2r_corridor(engine, solids, radius, pieces):
    # The blank leaves 5 mm webs beside the x walls and 10 mm beside the y walls. A full
    # depth profile frees the island; a 6 mm corridor also parts both 5 mm webs, so the
    # frame falls into a north and a south rail. Nothing presses them: the split stays
    # refused and names each piece.
    step = solids["island"]
    result = _run(engine, step, _island_walls(engine, step), _profile(radius))
    reason = result["setups"]["S2"].get("stock_reason")
    assert f"splits an input stock piece into {pieces} pieces" in reason, reason
    volumes = sorted(float(v) for v in re.findall(r"\(([\d.]+) mm\^3", reason))
    assert len(volumes) == pieces and volumes[-1] == pytest.approx(48000.0, abs=1e-2)
    if pieces == 2:  # the whole frame less the 2r ring, its convex joins rounded
        frame = 36000.0 - 20.0 * (800.0 + math.pi * 16.0)
        assert volumes[0] == pytest.approx(frame, abs=1e-2)


def test_a_concave_wall_clears_its_corridor_never_its_whole_circle(engine, solids):
    step = solids["dented"]
    refs = engine.refs(step, (14, 43, 0), (56, 46, 20), kind="Cylinder")
    assert len(refs) == 1
    result = _run(engine, step, refs, _profile(2.0))
    entry = result["setups"]["S2"]
    assert entry.get("stock_reason") is None, entry
    # The centre path is the R98 arc over the dent's angle; the corridor is the R96..R100
    # band over it and an r disc at each end (a sliver of each lies in the part's guard).
    half = math.asin(math.sqrt(100.0**2 - 98.0**2) / 100.0)
    corridor = 20.0 * (2 * 2.0 * 98.0 * 2 * half + math.pi * 2.0**2)
    removed = BLANK_MM3 - entry["stock_volume_mm3"]
    assert corridor * 0.98 < removed <= corridor + 1e-2, (removed, corridor)
