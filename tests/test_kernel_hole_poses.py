"""Hole cuts end at their own bores, and host hole metadata reaches the engine in mm.

A through hole exits where its claimed bores end, not at the entry-stock floor; a
not-yet-drilled bore reserves stock only along its own length; the host resolves the
hole's thru/depth/entry exactly as ``tip_endpoints`` does. FreeCAD-backed tests skip
without ``freecadcmd``.
"""

import hashlib
import math
import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise
from test_kernel_stock import _bundle

from prechips import kernel
from prechips.rules import reach
from prechips.rules.tip_endpoints import evaluate

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

# 60x40x20 block: a 30x20 pocket with its floor at z=10 over a 6.5 mm hole through z 0..10.
pocket = Part.makeBox(60, 40, 20).cut(Part.makeBox(30, 20, 11, V(15, 10, 10)))
save("pocket-hole", pocket.cut(Part.makeCylinder(3.25, 12, V(30, 20, -1))))
# An R4 cross bore along x at (y=20, z=8) leaves a solid leg z 0..4 under a vertical
# 4 mm hole that runs from the top face into the cross bore.
cross = Part.makeBox(60, 40, 20).cut(Part.makeCylinder(4, 62, V(-1, 20, 8), V(1, 0, 0)))
save("crossbore", cross.cut(Part.makeCylinder(2, 13, V(30, 20, 8))))
# A 6.5 mm bore through the whole block.
save("hole", Part.makeBox(60, 40, 20).cut(Part.makeCylinder(3.25, 22, V(30, 20, -1))))
# Two overlapping R3 through bores 3 mm apart: one figure-eight void, two bore axes.
pair = Part.makeBox(60, 40, 20).cut(Part.makeCylinder(3, 22, V(30, 20, -1)))
save("overlap", pair.cut(Part.makeCylinder(3, 22, V(33, 20, -1))).removeSplitter())
"""
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [40.0, 20.0],
}
HOLD = _vise(5.0, centre=30.0)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("hole-solids")
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
    assert len(paths) == 4, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def test_pocket_clearing_leaves_no_pin_above_a_later_drilled_hole_mouth(engine, solids):
    step = solids["pocket-hole"]
    pocket = engine.refs(step, (15, 10, 10), (45, 30, 20), kind="Plane")
    hole = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 10), kind="Cylinder")
    assert len(pocket) == 5 and hole  # floor and four walls; the bore below the floor
    clear = {
        **_op("S1:10", "pocket", 3.0, 15.0, 30.0),
        "do": "rough_pocket",
        "to_z": 10.0,
        "stock_removal_bounds": {"x": [15.0, 45.0], "y": [10.0, 30.0], "z": [10.0, 20.0]},
    }
    drill = {
        **_op("S2:10", "hole", 3.25, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": True, "entry_z_mm": 10.0},
    }
    setups = [
        _setup([clear], HOLD, setup_id="S1"),
        _setup([drill], HOLD, setup_id="S2"),
        _setup([], HOLD, setup_id="S3"),
    ]
    rows = engine.run(engine.job(step, {"pocket": pocket, "hole": hole}, setups, stock=BLANK))[
        "setups"
    ]
    # The bore's reserved column ends LIFT (1 um) above its mouth: no 10 mm pin.
    assert rows["S2"]["stock_volume_mm3"] == pytest.approx(42000.0, abs=0.05)
    assert rows["S3"]["stock_volume_mm3"] == pytest.approx(42000.0 - math.pi * 3.25**2 * 10)


def test_through_hole_into_a_cross_bore_ends_at_its_own_exit(engine, solids):
    step = solids["crossbore"]
    hole = engine.refs(step, (28, 18, 11), (32, 22, 20), kind="Cylinder")
    assert hole
    drill = {
        **_op("S1:10", "hole", 2.0, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": True, "entry_z_mm": 20.0},
    }
    result = engine.run(engine.job(step, {"hole": hole}, [_setup([drill], HOLD)], stock=BLANK))
    detail = result["ops"]["S1:10"]
    # The solid leg under the cross bore is never on the drill's path.
    assert detail["tool_hits"] == 0
    exit_z = 8.0 + math.sqrt(4.0**2 - 2.0**2)  # lowest point of the bore's saddle exit
    assert detail["reach_depth_mm"] == pytest.approx(20.0 - exit_z, abs=1e-4)


def test_overlapping_through_bores_are_two_known_axes_not_ambiguous_debt(engine, solids):
    step = solids["overlap"]
    bores = engine.refs(step, (27, 17, 0), (36, 23, 20), kind="Cylinder")
    assert len(bores) >= 2
    drill = {
        **_op("S1:10", "holes", 3.0, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": True, "entry_z_mm": 20.0},
    }
    setups = [_setup([drill], HOLD, setup_id="S1"), _setup([], HOLD, setup_id="S2")]
    result = engine.run(engine.job(step, {"holes": bores}, setups, stock=BLANK))
    assert result["ops"]["S1:10"]["tool_hits"] == 0
    r, d = 3.0, 3.0
    lens = 2 * r**2 * math.acos(d / (2 * r)) - d / 2 * math.sqrt(4 * r**2 - d**2)
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(
        48000.0 - 20.0 * (2 * math.pi * r**2 - lens)
    )


def _host(tmp_path, step, units, feature, op):
    """A host bundle whose S1 makes one hole op from machine entry z=20 mm; S2 receives it."""
    bundle = _bundle(tmp_path)
    bundle.paths["step"] = step
    bundle.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    bundle.features["units"] = units
    bundle.features["features"] = {"bore": feature}
    first = bundle.plan["setups"][0]
    hold = {**first["hold"], "jaw_center_along_mm": 30.0}
    first.update(hold=hold, stock_state={"top_z": 20.0})
    first["ops"] = [{"op": 10, "feature": "bore", "tool": "em", "holder": "holder", **op}]
    bundle.plan["setups"].append(
        {"id": "S2", "machine": "mill", "frame": "A", "stock_in": "S1", "hold": hold, "ops": []}
    )
    return bundle


@pytest.mark.parametrize(
    "units, feature, op, depth",
    [
        # No thru on the feature means blind, as in tip_endpoints.
        ("mm", {"kind": "counterbore"}, {"do": "counterbore", "depth_mm": 6.0}, 6.0),
        # A tap without depth_mm stops at its feature's upper depth band.
        ("mm", {"kind": "threaded_hole", "depth": [5.0, 6.0]}, {"do": "tap"}, 6.0),
        # Inch feature depths convert; the machine-mm entry is never scaled.
        ("in", {"kind": "threaded_hole", "depth": [0.4 / 25.4, 0.5 / 25.4]}, {"do": "tap"}, 0.5),
        # An explicit depth_mm is mm in an inch bundle too.
        ("in", {"kind": "hole", "thru": False}, {"do": "bore", "depth_mm": 0.5}, 0.5),
    ],
)
def test_host_hole_depth_and_entry_reach_the_engine_in_machine_mm(
    engine, solids, tmp_path, units, feature, op, depth
):
    step = solids["hole"]
    feature = {**feature, "faces": engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20))}
    bundle = _host(tmp_path, step, units, feature, op)
    (finding,) = [f for f in evaluate(bundle) if f.subject == "bore"]
    assert finding.numbers["endpoints"][0]["tip_z"] == pytest.approx(20.0 - depth)
    result = engine.run(kernel.engine_job(kernel.build_job(bundle)))
    detail = result["ops"]["S1:10"]
    assert detail["reach_depth_mm"] == pytest.approx(depth)
    # The em tool's 3 mm radius cylinder from the entry down to the same physical tip.
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(
        48000.0 - math.pi * 3.0**2 * depth
    )


@pytest.mark.parametrize(
    "stock_state, exit_mm, cut_height",
    [
        # The plan runs the tool out of the 22 mm stock: no skin stays over the bore mouth.
        ({"local_thickness": {"bore": 22.0}}, 0.5, 22.0),
        # No planned exit: the tool stops where the finished bore ends, 2 mm of stock on.
        ({}, None, 20.0),
    ],
)
def test_a_through_hole_runs_out_of_the_stock_it_carries_past_the_finished_bore(
    engine, solids, tmp_path, stock_state, exit_mm, cut_height
):
    step = solids["hole"]
    bore = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20))
    op = {"do": "bore"} if exit_mm is None else {"do": "bore", "exit_mm": exit_mm}
    bundle = _host(tmp_path, step, "mm", {"kind": "hole", "thru": True, "faces": bore}, op)
    # The stock stands 2 mm below the part's bottom face, z -2..20.
    bundle.plan["stock"].update(origin_mm=[0.0, 0.0, -2.0], section_mm=[40.0, 22.0])
    bundle.plan["setups"][0]["stock_state"].update(stock_state)
    result = engine.run(kernel.engine_job(kernel.build_job(bundle)))
    assert result["setups"]["S1"]["stock_volume_mm3"] == pytest.approx(60.0 * 40.0 * 22.0)
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(
        60.0 * 40.0 * 22.0 - math.pi * 3.0**2 * cut_height
    )


@pytest.mark.parametrize(
    "thickness, exit_mm, cut_height, conflict",
    [
        # The plan says 10 mm of stock under the entry: its exit, z 9.5, lies 9.5 mm above
        # the finished bore's end at z 0. The tool still plunges only 10.5 mm.
        (10.0, 0.5, 10.5, True),
        # An exit exactly at the bore's end agrees with it.
        (20.0, 0.0, 20.0, False),
    ],
)
def test_a_planned_exit_short_of_the_finished_bore_end_is_cut_as_planned_and_is_an_error(
    engine, solids, tmp_path, thickness, exit_mm, cut_height, conflict
):
    step = solids["hole"]
    bore = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20))
    op = {"do": "bore", "exit_mm": exit_mm}
    bundle = _host(tmp_path, step, "mm", {"kind": "hole", "thru": True, "faces": bore}, op)
    bundle.plan["stock"].update(origin_mm=[0.0, 0.0, -2.0], section_mm=[40.0, 22.0])
    bundle.plan["setups"][0]["stock_state"].update(local_thickness={"bore": thickness})
    # Flutes long enough for the whole bore: reach can fail only on the conflict.
    bundle.inventory["tools"]["em"]["flute_len_mm"] = 40.0
    (finding,) = [f for f in evaluate(bundle) if f.subject == "bore"]
    assert finding.numbers["endpoints"][0]["tip_z"] == pytest.approx(20.0 - cut_height)
    result = engine.run(kernel.engine_job(kernel.build_job(bundle)))
    detail = result["ops"]["S1:10"]
    # Never deeper than planned: the kernel cuts what the traveler's endpoint cuts.
    assert detail["reach_depth_mm"] == pytest.approx(cut_height)
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(
        60.0 * 40.0 * 22.0 - math.pi * 3.0**2 * cut_height
    )
    # The plan contradicting the finished bore is a finding, never a silent choice.
    assert ("stock_removal_error" in detail) is conflict, detail
    if conflict:
        (row,) = [f for f in reach.evaluate(bundle) if f.subject == "S1:10"]
        assert row.status == "error", row
