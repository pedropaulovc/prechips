"""A flute meets the stock this setup's earlier derived cuts leave, never a later cut's.

Holders keep the setup-entry stock. Once an earlier cut cannot be derived, a later flute
keeps only its certain finished-material hits and its tool hits stay unknown. Final
profile-wall debts judged after all cuts never change an op's before-op stock.
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

# A 60x40x20 part standing 5 mm in from a blank's x ends and 10 mm in from its y sides.
island = Part.makeBox(60, 40, 20, V(5, 5, 0))
save("island", island)
# The same part with a finished lip overhanging its west wall by 4 mm, z 16..20.
save("lipped", island.fuse(Part.makeBox(4, 10, 4, V(1, 20, 16))).removeSplitter())
"""
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, -5.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 70.0,
    "section_mm": [60.0, 20.0],
}
HOLD = _vise(5.0, centre=35.0)
LEAVE = 0.2
WEST = {"x": [0.0, 5.0], "y": [-5.0, 55.0], "z": [0.0, 20.0]}
EAST = {"x": [65.0, 70.0], "y": [-5.0, 55.0], "z": [0.0, 20.0]}


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("prefix-solids")
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


def _rough(bounds, leave=LEAVE):
    # The west wall's outside strip, cleared to its leave by the authored box.
    op = _op("S1:10", "west", 3.0, 25.0, 30.0)
    return {
        **op,
        "do": "rough_profile",
        "rough_allowance_mm": leave,
        "stock_removal_bounds": bounds,
    }


def _finish(subject="S1:20"):
    # Its holder (R2.9 from 6 mm above the tip) stands over the strip, clear of the part.
    op = _op(subject, "west", 3.0, 5.0, 6.0, holder_radius=2.9)
    return {**op, "do": "finish_profile", "rough_allowance_mm": LEAVE}


def _job(engine, step, ops):
    west = engine.refs(step, (5, 5, 0), (5, 45, 20), kind="Plane")
    assert len(west) == 1
    setups = [_setup(ops, HOLD, setup_id="S1"), _setup([], HOLD, setup_id="S2")]
    return engine.job(step, {"west": west}, setups, stock=BLANK)


def test_earlier_clearance_frees_a_later_flute_never_its_holder_or_an_earlier_flute(engine, solids):
    step = solids["island"]
    rough, finish = _rough(WEST), _finish()
    reverse = {**_finish("S1:10")}, {**_rough(WEST), "subject": "S1:20"}
    forward, backward = engine.run(
        {"jobs": [_job(engine, step, [rough, finish]), _job(engine, step, list(reverse))]}
    )["results"]
    after = forward["ops"]["S1:20"]
    # The rough cleared the strip and the finish removes the rough's leave.
    assert after["tool_hits"] == 0 and after["obstacles"]["tool"] == [], after
    # The holder still meets the strip as the stock enters the setup.
    assert after["holder_hits"] > 0 and after["obstacles"]["holder"] == ["part"]
    # Run first, the finish meets the whole strip: the later rough is never credited.
    before = backward["ops"]["S1:10"]
    assert before["tool_hits"] > 0 and before["obstacles"]["tool"] == ["part"], before
    assert before["holder_hits"] == after["holder_hits"]
    # Its leave then stays on the finished wall: a final debt of the setup's output stock
    # that leaves the measured flute verdict as it is.
    reason = backward["setups"]["S2"]["stock_reason"]
    assert "S1:10: overstock still touches claimed wall(s)" in reason, reason
    assert "tool_hits" not in before["reasons"]


def test_underivable_earlier_cut_leaves_later_flute_unknown_with_its_finished_hits(engine, solids):
    step = solids["lipped"]
    known, unknown = engine.run(
        {
            "jobs": [
                _job(engine, step, [_rough(WEST, leave=0.0), _finish()]),
                _job(engine, step, [_rough(EAST, leave=0.0), _finish()]),
            ]
        }
    )["results"]
    finish = known["ops"]["S1:20"]
    # With the strip cleared to the finished solid, the flute meets only the overhanging lip.
    assert finish["tool_hits"] > 0 and finish["obstacles"]["tool"] == ["part"], finish
    stopped = unknown["ops"]["S1:20"]
    assert stopped["tool_hits"] == "unknown"
    reason = stopped["reasons"]["tool_hits"]
    assert "the stock before this op is unknown" in reason and "S1:10" in reason, reason
    assert "lie outside its stock_removal_bounds" in reason
    # Certain finished-material hits stay certain; the holder keeps the entry stock.
    assert stopped["min_hits"]["tool"] == finish["tool_hits"]
    assert stopped["holder_hits"] == finish["holder_hits"]
    # The op whose cut stops the builder keeps the known stock before it.
    rough = unknown["ops"]["S1:10"]
    assert isinstance(rough["tool_hits"], int) and rough["tool_hits"] > 0, rough
    assert "S1:10" in unknown["setups"]["S2"]["stock_reason"]
