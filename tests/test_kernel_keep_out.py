"""Raster keep-out islands in the FreeCAD kernel, measured on an authored boss plate.

A face raster's ``contour.keep_out`` circle keeps the whole cutter outside it: the
coordinates rule stops each crossing pass where the cutter edge meets the circle. The op
therefore takes only the stock its printed cutter-centre pieces sweep: the island, and the
cusps the round cutter leaves between the piece ends round it, stay on the workpiece
whatever the op claims, and its floor poses do not run into them. The host hands the engine
the circles and the split passes the coordinates rule mapped into the setup frame.
"""

import math

import pytest
from test_contour_order import keep_out_face
from test_kernel_geometry import IDENTITY, Engine, _op, _setup, _vise
from test_kernel_rocker_regression import _author

from prechips import kernel
from prechips.inputs import load_bundle
from prechips.rules.coordinates import _raster

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
LEAVE, ISLAND_R, RADIUS = 0.2, 4.5, 3.0
CENTRE = (37.0, 20.0)
PLATE_MM3 = 60 * 40 * 10
STOCK_ABOVE = 6.0  # blank top Z16 over the plate top Z10: the boss height


@pytest.fixture(scope="module")
def boss(tmp_path_factory, freecad_kernel):
    return _author(tmp_path_factory.mktemp("boss-solid"), _BOSS, "boss.step", freecad_kernel)


def _split(island_r, step=2 * RADIUS):
    """The coordinates rule's face raster over the plate top round the island at the boss:
    its ``printed`` cutter-centre pieces and the pass parts the island ``skipped`` (setup
    mm). The default step is the cutter diameter, the widest a raster may take."""
    contour = {
        "method": "linear_table",
        "step_mm": step,
        "open_side": "-y",
        "sweep_frame": "model",
        "sweep_bounds": {"x": [0.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 16.0]},
        "keep_out": [{"at": list(CENTRE), "dia_mm": 2 * island_r}],
    }
    record, why = _raster(
        {"frame": "model"},
        {"do": "finish_face", "contour": contour},
        RADIUS,
        RADIUS,
        IDENTITY,
        {"model": IDENTITY},
        1,
        {"cut_order": "conventional"},
        21.0,
        (0.001, 3),
        1.0,
    )
    assert record is not None, why
    return {"printed": record["cutter_centre"], "skipped": record["raster"]["keep_out_skipped"]}


def _faces(island_r=ISLAND_R):
    box = {"x": [0.0, 60.0], "y": [0.0, 40.0]}
    keep_out = {
        "keep_out": [{"at_mm": list(CENTRE), "dia_mm": 2 * island_r}],
        "keep_out_passes": _split(island_r),
    }
    rough = {
        **_op("S1:10", "top", RADIUS, 15.0, 30.0),
        "do": "rough_face",
        "rough_allowance_mm": LEAVE,
        "to_z": 10.0 + LEAVE,
        "stock_removal_bounds": {**box, "z": [10.0, 16.0]},
        **keep_out,
    }
    finish = {
        **_op("S1:20", "top", RADIUS, 15.0, 30.0),
        "do": "finish_face",
        "to_z": 10.0,
        "stock_removal_bounds": {**box, "z": [10.0, 10.0 + LEAVE]},
        **keep_out,
    }
    return [rough, finish]


def _distance(point, segment):
    (ax, ay), (bx, by) = segment
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(point[0] - ax - t * dx, point[1] - ay - t * dy)


def _merged(spans):
    out = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _minus(spans, holes):
    out = []
    for lo, hi in spans:
        for a, b in holes:
            if b <= lo or a >= hi:
                continue
            if a > lo:
                out.append((lo, a))
            lo = max(lo, b)
        if lo < hi:
            out.append((lo, hi))
    return out


def _swept(x, segments, radius):
    """The Y spans a cutter of ``radius`` covers on the line at ``x`` along X passes."""
    spans = []
    for (x0, y0), (x1, y1) in segments:
        assert y0 == y1, "raster passes run along X here"
        gap = max(min(x0, x1) - x, 0.0, x - max(x0, x1))
        if gap < radius:
            half = math.sqrt(radius**2 - gap**2)
            spans.append((y0 - half, y0 + half))
    return _merged(spans)


def _kept_area(island_r, passes, strips=40000):
    """The plate-top area a split raster leaves under stock, integrated strip by strip
    independently of the kernel: the island disc, and what the skipped pass parts would
    have swept less what any printed piece sweeps (the cusps between piece ends)."""
    reach = island_r + 2 * RADIUS + 1.0
    width = 2 * reach / strips
    area = 0.0
    for i in range(strips):
        x = CENTRE[0] - reach + (i + 0.5) * width
        spans = _minus(_swept(x, passes["skipped"], RADIUS), _swept(x, passes["printed"], RADIUS))
        if abs(x - CENTRE[0]) < island_r:
            half = math.sqrt(island_r**2 - (x - CENTRE[0]) ** 2)
            spans.append((CENTRE[1] - half, CENTRE[1] + half))
        area += sum(hi - lo for lo, hi in _merged(spans)) * width
    return area


def _run(engine, boss, ops, features=None):
    top = engine.refs(boss, (0, 0, 10), (60, 40, 10), kind="Plane")
    assert len(top) == 1
    hold = _vise(5.0, centre=30.0)
    setups = [_setup(ops, hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
    result = engine.run(engine.job(boss, features or {"top": top}, setups, stock=BLANK))
    assert result["status"] == "ok", result.get("reason")
    return result


def test_split_face_rasters_leave_the_stock_their_printed_pieces_never_sweep(
    tmp_path, freecad_kernel, boss
):
    engine = Engine(tmp_path, freecad_kernel)
    result = _run(engine, boss, _faces())
    # The finisher's floor poses beside the boss stand outside the island, never on the
    # R4 boss foot inside it where the rough leave still stands.
    for subject in ("S1:10", "S1:20"):
        op = result["ops"][subject]
        assert op["tool_hits"] == 0, (subject, op.get("obstacles"))
    passes = _split(ISLAND_R)
    # A 6 mm step leaves a cusp past the island: (37, 25) is 0.5 outside it, yet 3.575 from
    # the nearest printed cutter axis, beyond the 3 mm cutter radius.
    assert min(_distance((37.0, 25.0), piece) for piece in passes["printed"]) > RADIUS + 0.5
    second = result["setups"]["S2"]
    assert "stock_reason" not in second, second.get("stock_reason")
    # Over the island and those cusps neither raster cuts, so the blank's whole 6 mm above
    # the plate stays; elsewhere the finisher clears the rough's 0.2 slab to the plate top.
    kept = _kept_area(ISLAND_R, passes)
    assert kept > math.pi * ISLAND_R**2 + 1.0
    assert second["stock_volume_mm3"] == pytest.approx(PLATE_MM3 + STOCK_ABOVE * kept, abs=0.05)


def test_a_wall_inside_the_keep_out_keeps_its_inherited_leave(tmp_path, freecad_kernel, boss):
    # The finish pocket's island is the boss plus the rough's 0.2 leave. Its passes never
    # reach the boss wall, so claiming that wall as well as the floor cannot take the leave
    # the rough left on it: the stock is what the floor-only claim leaves.
    engine = Engine(tmp_path, freecad_kernel)
    side = engine.refs(boss, (33, 16, 10), (41, 24, 16), kind="Cylinder")
    top = engine.refs(boss, (0, 0, 10), (60, 40, 10), kind="Plane")
    island = 4 + LEAVE
    volumes = {}
    for name, claims in (("floor", top), ("floor and wall", top + side)):
        rough, finish = _faces(island)
        rough.update(feature="all", finishing=False)
        finish.update(feature="target", do="finish_pocket")
        finish["stock_removal_bounds"]["z"] = [10.0, 16.0]
        result = _run(engine, boss, [rough, finish], {"all": top + side, "target": claims})
        second = result["setups"]["S2"]
        assert "stock_reason" not in second, second.get("stock_reason")
        volumes[name] = second["stock_volume_mm3"]
    assert volumes["floor and wall"] == pytest.approx(volumes["floor"], abs=0.01)
    kept = _kept_area(island, _split(island))
    assert volumes["floor"] == pytest.approx(PLATE_MM3 + STOCK_ABOVE * kept, abs=0.05)


@pytest.mark.parametrize(
    "unmapped",
    [{"keep_out": "unknown"}, {"keep_out_passes": "unknown"}, {"keep_out_passes": None}],
    ids=["circles", "passes", "no-passes"],
)
def test_an_unmapped_keep_out_leaves_the_cut_unknown(tmp_path, freecad_kernel, boss, unmapped):
    # Without its circles or the passes they split, what the finisher leaves is unknown.
    engine = Engine(tmp_path, freecad_kernel)
    rough, finish = _faces()
    finish = {key: value for key, value in {**finish, **unmapped}.items() if value is not None}
    result = _run(engine, boss, [rough, finish])
    assert "keep_out" in result["setups"]["S2"]["stock_reason"]
    assert result["ops"]["S1:20"]["tool_hits"] == "unknown"


def test_host_job_carries_the_setup_frame_islands_to_the_engine(tmp_path):
    # A sweep-frame B circle at B (10, 3) is setup (5, 3): the engine job, after the
    # geometry-cache field filter, carries that setup-frame circle, not the authored one,
    # and the passes it split: the printed pieces and the parts it skipped.
    _, profile = keep_out_face(tmp_path, "[{ at = [10.0, 3.0], dia_mm = 2.0 }]", sweep_frame="B")
    assert profile["raster"]["keep_out"] == [{"at": [5.0, 3.0], "dia_mm": 2.0}]
    plan = tmp_path / "coordinate-bundle" / "plan.toml"
    job = kernel.engine_job(kernel.build_job(load_bundle(plan)))
    (op,) = [op for setup in job["setups"] for op in setup["ops"] if op["subject"] == "S1:20"]
    assert op["keep_out"] == [{"at_mm": [5.0, 3.0], "dia_mm": 2.0}]
    assert op["keep_out_passes"] == {
        "printed": profile["cutter_centre"],
        "skipped": profile["raster"]["keep_out_skipped"],
    }
    assert op["keep_out_passes"]["skipped"]
