"""A removal that splits the stock is kept only when every piece is pressed onto a support.

A clamp declared ``restraint = "press"`` must bear on each piece and the run through that
piece along its force must end on an anchored fixture component. Locating or undeclared
clamps, pieces over air and unclamped pieces leave the split refused. FreeCAD-backed tests
run ``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import base64
import struct
import subprocess

import pytest
import test_kernel_stock_prefix as prefix
from test_kernel_geometry import Engine, _setup
from test_kernel_stock_prefix import BLANK, _rough

UP = {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
# The box clears the strip south of the part and strands the blank's last 3 mm (y -5..-2).
BOUNDS = {"x": [0.0, 70.0], "y": [-2.0, 5.0], "z": [0.0, 20.0]}
SPLIT = "S1:10: removing its claimed clearance splits an input stock piece into 2 pieces"


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    # The stock-prefix island: a 60 x 40 x 20 part inside the 70 x 60 x 20 blank.
    directory = tmp_path_factory.mktemp("held-split-solids")
    script = directory / "author.py"
    script.write_text(prefix._AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert "island" in paths, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _box(name, at, size):
    return {"name": name, "shape": "box", "at_mm": at, "size_mm": size}


def _pad(index, y, restraint):
    """A 10 x 2 x 5 pad bearing on the stock top (z 20) at ``y``."""
    clamp = {
        "name": f"clamp {index} pad",
        "pose": {"origin_mm": [35.0, y, 20.0], **UP},
        "solids": [_box("pad:pad", [-5.0, -1.0, 0.0], [10.0, 2.0, 5.0])],
    }
    return clamp if restraint is None else {**clamp, "restraint": restraint}


def _hold(strand, main="press", floor_from_y=-10.0):
    """A floor plate under the blank; one pad on the stranded strip, one on the main piece."""
    clamps = [_pad(1, 30.0, main)]
    if strand != "absent":
        clamps.append(_pad(2, -3.5, strand))
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [
            _box("nest:floor", [-5.0, floor_from_y, -5.0], [80.0, 70.0 - floor_from_y, 5.0])
        ],
        "clamps": clamps,
        "debts": [],
        "gaps": [],
    }


def _run(engine, step, hold, bounds=BOUNDS, inspections=None):
    south = engine.refs(step, (5, 5, 0), (65, 5, 20), kind="Plane")
    assert len(south) == 1
    setups = [
        _setup([{**_rough(bounds), "feature": "south"}], hold),
        _setup([], hold, setup_id="S2"),
    ]
    if inspections is not None:
        setups[0]["render"] = {"inspections": inspections}
    return engine.run(engine.job(step, {"south": south}, setups, stock=BLANK))


def test_every_piece_pressed_onto_the_floor_keeps_the_split(engine, solids):
    result = _run(engine, solids["island"], _hold("press"))
    reason = result["setups"]["S2"].get("stock_reason")
    assert reason is None or "splits" not in reason, reason
    rows = result["ops"]["S1:10"]["split_hold"]
    assert [row["held"] for row in rows] == [True, True], rows
    # Each piece's run ends on the floor, under the pad that bears on that piece.
    assert {row["clamp"] for row in rows} == {"clamp 1 pad", "clamp 2 pad"}
    assert all(row["anchor"] == "nest:floor" for row in rows), rows
    assert all(row["exit_mm"][2] == pytest.approx(0.0, abs=1e-3) for row in rows), rows
    volumes = sorted(row["volume_mm3"] for row in rows)
    assert volumes[0] == pytest.approx(70.0 * 3.0 * 20.0, rel=1e-6)


@pytest.mark.parametrize(
    ("strand", "floor_from_y"),
    [
        ("locate", -10.0),  # a locating pad positions, never holds down
        (None, -10.0),  # undeclared restraint is none
        ("none", -10.0),
        ("absent", -10.0),  # the stranded strip is loose
        ("press", 0.0),  # pressed, but over air: no support under the strip
    ],
)
def test_a_piece_without_a_pressed_load_path_refuses_the_split(
    engine, solids, strand, floor_from_y
):
    result = _run(engine, solids["island"], _hold(strand, floor_from_y=floor_from_y))
    reason = result["setups"]["S2"]["stock_reason"]
    assert SPLIT in reason, reason
    assert "has no press-clamp load path to an anchored support" in reason
    rows = result["ops"]["S1:10"]["split_hold"]
    held = {round(row["volume_mm3"]): row["held"] for row in rows}
    assert held[4200] is False and sorted(held.values()) == [False, True], rows


def test_an_inspection_sketch_draws_the_piece_that_holds_the_part_not_the_scrap(engine, solids):
    # The held split strands the blank's last 3 mm (y -5..-2) beside the piece that holds
    # the part. Inspected off the machine, the part is that piece alone: its sketch is the
    # one drawn when the cut clears the whole strip, never framed wider by the scrap.
    view = {
        "title": "VIEW 1",
        "up": [0.0, 0.0, 1.0],
        "toward": [1.0, 0.0, 0.0],
        "marks": [{"label": "A", "at_mm": [35.0, 25.0, 20.0]}],
    }
    inspections = [{"op": 10, "requirement": "height", "views": [view]}]
    cleared = {**BOUNDS, "y": [-5.0, 5.0]}
    heights = []
    for bounds in (BOUNDS, cleared):
        result = _run(engine, solids["island"], _hold("press"), bounds, inspections)
        facts = result["setups"]["S1"]
        png = base64.b64decode(facts["inspection_pngs_base64"]["10:height"])
        heights.append(struct.unpack(">II", png[16:24])[1])
    assert heights[0] == heights[1], heights
