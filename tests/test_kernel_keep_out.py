"""Raster keep-out islands in the FreeCAD kernel, measured on an authored boss plate.

A face raster's ``contour.keep_out`` circle keeps the whole cutter outside it, so the op
neither removes the stock inside the circle nor stands a floor pose nearer the circle
than one cutter radius. The rough leave a later op owns around the boss therefore
survives both face ops, and the finisher's poses do not run into it. The host hands the
engine the circles the coordinates rule mapped into the setup frame.
"""

import math

import pytest
from test_contour_order import keep_out_face
from test_kernel_geometry import Engine, _op, _setup, _vise
from test_kernel_rocker_regression import _author

from prechips import kernel
from prechips.inputs import load_bundle

_BOSS = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
# A 60 x 40 x 10 plate with an R4 boss 6 tall at (37, 20).
solid = Part.makeBox(60, 40, 10).fuse(Part.makeCylinder(4, 6, V(37, 20, 10))).removeSplitter()
solid.exportStep(out + "/boss.step")
"""
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [40.0, 16.0],
}
LEAVE, ISLAND_R = 0.2, 4.5
KEEP_OUT = [{"at_mm": [37.0, 20.0], "dia_mm": 2 * ISLAND_R}]
PART_MM3 = 60 * 40 * 10 + math.pi * 4**2 * 6


@pytest.fixture(scope="module")
def boss(tmp_path_factory, freecad_kernel):
    return _author(tmp_path_factory.mktemp("boss-solid"), _BOSS, "boss.step", freecad_kernel)


def _faces():
    box = {"x": [0.0, 60.0], "y": [0.0, 40.0]}
    rough = {
        **_op("S1:10", "top", 3.0, 15.0, 30.0),
        "do": "rough_face",
        "rough_allowance_mm": LEAVE,
        "to_z": 10.0 + LEAVE,
        "stock_removal_bounds": {**box, "z": [10.0, 16.0]},
        "keep_out": KEEP_OUT,
    }
    finish = {
        **_op("S1:20", "top", 3.0, 15.0, 30.0),
        "do": "finish_face",
        "to_z": 10.0,
        "keep_out": KEEP_OUT,
        "stock_removal_bounds": {**box, "z": [10.0, 10.0 + LEAVE]},
    }
    return [rough, finish]


def _run(engine, boss, ops):
    top = engine.refs(boss, (0, 0, 10), (60, 40, 10), kind="Plane")
    assert len(top) == 1
    hold = _vise(5.0, centre=30.0)
    setups = [_setup(ops, hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
    result = engine.run(engine.job(boss, {"top": top}, setups, stock=BLANK))
    assert result["status"] == "ok", result.get("reason")
    return result


def test_face_rasters_keep_island_stock_and_their_poses_clear_it(tmp_path, freecad_kernel, boss):
    engine = Engine(tmp_path, freecad_kernel)
    result = _run(engine, boss, _faces())
    # The finisher's floor samples beside the boss stand one cutter radius outside the
    # island, never on the R4 boss foot inside it where the rough leave still stands.
    for subject in ("S1:10", "S1:20"):
        op = result["ops"][subject]
        assert op["tool_hits"] == 0, (subject, op.get("obstacles"))
    # Both rasters leave the whole island annulus R4..R4.5 over the boss height; outside
    # it the finisher clears the rough's 0.2 slab down to the plate top.
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    island = math.pi * (ISLAND_R**2 - 4**2) * 6
    assert second["stock_volume_mm3"] == pytest.approx(PART_MM3 + island, abs=0.05)


def test_an_unmapped_keep_out_leaves_the_cut_unknown(tmp_path, freecad_kernel, boss):
    engine = Engine(tmp_path, freecad_kernel)
    rough, finish = _faces()
    result = _run(engine, boss, [rough, {**finish, "keep_out": "unknown"}])
    assert "keep_out" in result["setups"]["S2"]["stock_reason"]
    assert result["ops"]["S1:20"]["tool_hits"] == "unknown"


def test_host_job_carries_the_setup_frame_islands_to_the_engine(tmp_path):
    # A sweep-frame B circle at B (10, 3) is setup (5, 3): the engine job, after the
    # geometry-cache field filter, carries that setup-frame circle, not the authored one.
    _, profile = keep_out_face(tmp_path, "[{ at = [10.0, 3.0], dia_mm = 2.0 }]", sweep_frame="B")
    assert profile["raster"]["keep_out"] == [{"at": [5.0, 3.0], "dia_mm": 2.0}]
    plan = tmp_path / "coordinate-bundle" / "plan.toml"
    job = kernel.engine_job(kernel.build_job(load_bundle(plan)))
    (op,) = [op for setup in job["setups"] for op in setup["ops"] if op["subject"] == "S1:20"]
    assert op["keep_out"] == [{"at_mm": [5.0, 3.0], "dia_mm": 2.0}]
