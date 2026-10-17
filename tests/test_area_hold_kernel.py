"""Area holds in the kernel (docs/design/area-hold.md §2.4, §3.1–3.3, #295 phase 3): the
seat, the gap the work sits at above it, the contact footprint and its polar moment, the
tape layer drawn only from a measured pair, and each op's contact islands and cut.

Engine tests run ``freecad_job.py`` on solids authored here and read only its JSON; host
tests check which declared facts reach the engine.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import IDENTITY, Engine, _op

from prechips.kernel import _engine_hold, hold_inputs

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
V = FreeCAD.Vector
# The section 10 strap: 350 x 40 x 2.75, centred on the setup origin, bottom at z 0.
Part.makeBox(350, 40, 2.75, V(-175, -20, 0)).exportStep(out + "/strap.step")
# 60 x 40 x 20 block stepped down to z 10 over x 30..60.
Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10))).exportStep(out + "/step.step")
"""

UP = {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
PAIR = [0.090, 0.110]
PART = {"shape": "part"}
STEP_STOCK = {
    "shape": "box",
    "origin_mm": [0.0, -5.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [50.0, 22.0],
}


@pytest.fixture(scope="module")
def parts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("area-hold")
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


def _plate(top=-0.1, x=(-200.0, 200.0), name="sub:plate"):
    """A 100 wide, 10 deep plate whose top is at ``top``."""
    return {
        "name": name,
        "local": name.split(":")[1],
        "shape": "box",
        "at_mm": [x[0], -50.0, top - 10.0],
        "size_mm": [x[1] - x[0], 100.0, 10.0],
    }


def _hold(solids=None, area=None, pose=None):
    area = {"on": "sub:plate", "thickness_mm": PAIR} if area is None else area
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": pose or {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": solids or [_plate()],
        "area": area,
        "debts": [],
        "gaps": [],
    }


def _run(engine, step, hold, ops=(), features=None, stock=PART):
    setup = {"id": "S1", "frame": IDENTITY, "hold": hold, "ops": list(ops)}
    return engine.run(engine.job(step, features, [setup], stock=stock))


def _rectangle_polar(a, b, n=700):
    """∫|ρ| dA of an a × b rectangle about its centre, midpoint rule on an n × n grid."""
    dx, dy = a / n, b / n
    return sum(
        math.hypot(-a / 2 + (i + 0.5) * dx, -b / 2 + (j + 0.5) * dy) * dx * dy
        for i in range(n)
        for j in range(n)
    )


# --- seat, gap, footprint ----------------------------------------------------------------


def test_strap_footprint_matches_the_section_10_worked_example(engine, parts):
    facts = _run(engine, parts["strap"], _hold())["setups"]["S1"]
    area = facts["area_hold"]
    assert area["seat"] == "sub:plate"
    assert area["seat_normal"] == [0.0, 0.0, 1.0]
    assert area["seat_z_mm"] == pytest.approx(-0.1)
    assert area["contact_z_mm"] == pytest.approx(0.0)
    assert area["gap_mm"] == pytest.approx(0.1)
    footprint = area["footprint"]
    assert footprint["area_mm2"] == pytest.approx(350 * 40)
    assert footprint["centroid_mm"] == pytest.approx([0.0, 0.0], abs=1e-6)
    # §10: J = 1.245e6 mm³ for the 350 × 40 rectangle.
    assert footprint["polar_mm3"] == pytest.approx(_rectangle_polar(350, 40), rel=1e-3)
    assert footprint["polar_mm3"] == pytest.approx(1.245e6, rel=2e-3)
    (face,) = footprint["outline_mm"]
    xs = [p[0] for p in face["outer"]]
    ys = [p[1] for p in face["outer"]]
    assert (min(xs), max(xs), min(ys), max(ys)) == (-175.0, 175.0, -20.0, 20.0)
    assert face["holes"] == []
    assert area["overhang_mm2"] == pytest.approx(0.0)


def test_a_measured_pair_draws_the_layer_without_clashing_the_work(engine, parts):
    facts = _run(engine, parts["strap"], _hold())["setups"]["S1"]
    assert facts["area_hold"]["layer"] == "drawn"
    assert facts["area_hold"]["layer_thickness_mm"] == pytest.approx(0.1)
    assert facts["fixture_clashes"] == []
    assert not any("touch neither" in d for d in facts["render_scene"]["debts"])


def test_an_unmeasured_pair_draws_no_layer_and_says_why(engine, parts):
    area = {"on": "sub:plate", "thickness_reason": "thickness_mm is not a measured pair: x"}
    facts = _run(engine, parts["strap"], _hold(area=area))["setups"]["S1"]
    assert facts["area_hold"]["layer"] == "not_drawn"
    assert "layer_thickness_mm" not in facts["area_hold"]
    assert (
        "tape layer not drawn: thickness_mm is not a measured pair: x"
        in (facts["render_scene"]["debts"])
    )
    # The gap is still measured: the seat check does not need the layer drawn.
    assert facts["area_hold"]["gap_mm"] == pytest.approx(0.1)


def test_a_pose_written_for_other_tape_reports_its_gap(engine, parts):
    facts = _run(engine, parts["strap"], _hold([_plate(top=-0.25)]))["setups"]["S1"]
    assert facts["area_hold"]["gap_mm"] == pytest.approx(0.25)


def test_work_overhanging_the_seat_bonds_only_over_it(engine, parts):
    facts = _run(engine, parts["strap"], _hold([_plate(x=(-100.0, 100.0))]))["setups"]["S1"]
    area = facts["area_hold"]
    assert area["footprint"]["area_mm2"] == pytest.approx(200 * 40)
    assert area["overhang_mm2"] == pytest.approx(150 * 40)
    assert area["footprint"]["polar_mm3"] == pytest.approx(_rectangle_polar(200, 40), rel=1e-3)


def test_a_leftover_tape_box_clashes_the_drawn_layer(engine, parts):
    leftover = {
        "name": "sub:tape",
        "local": "tape",
        "shape": "box",
        "at_mm": [-175.0, -20.0, -0.1],
        "size_mm": [350.0, 40.0, 0.1],
    }
    facts = _run(engine, parts["strap"], _hold([_plate(), leftover]))["setups"]["S1"]
    assert any(
        {"tape layer", "sub:tape"} <= set(clash.split(" (")[0].split(" interpenetrates "))
        for clash in facts["fixture_clashes"]
    )


@pytest.mark.parametrize(
    "hold,reason",
    [
        (_hold(area={"on": "sub:missing"}), "seat solid sub:missing is not drawn"),
        (
            _hold(pose={"origin_mm": [0.0, 0.0, 0.0], "x": [0.0, 1.0, 0.0], "z": [1.0, 0.0, 0.0]}),
            "the seat's +z face does not face setup +Z",
        ),
        (_hold(area={"reason": "host said why"}), "host said why"),
    ],
)
def test_an_unusable_seat_leaves_only_a_reason(engine, parts, hold, reason):
    area = _run(engine, parts["strap"], hold)["setups"]["S1"]["area_hold"]
    assert area["reason"].startswith(reason)
    assert "footprint" not in area and "gap_mm" not in area


def test_a_round_seat_has_no_flat_top(engine, parts):
    bar = {
        "name": "sub:plate",
        "local": "plate",
        "shape": "cylinder",
        "at_mm": [-200.0, 0.0, -10.1],
        "axis": [1.0, 0.0, 0.0],
        "dia_mm": 20.0,
        "length_mm": 400.0,
    }
    area = _run(engine, parts["strap"], _hold([bar]))["setups"]["S1"]["area_hold"]
    assert area["reason"] == "the seat solid has no flat +z face"


# --- per-op islands ----------------------------------------------------------------------


def test_an_op_that_removes_nothing_keeps_the_footprint_island(engine, parts):
    step = parts["strap"]
    top = engine.refs(step, (-175, -20, 2.75), (175, 20, 2.75))
    result = _run(engine, step, _hold(), [_op("S1:10", "top", 3.0, 10.0, 40.0)], {"top": top})
    (island,) = result["ops"]["S1:10"]["area_hold"]["islands"]
    footprint = result["setups"]["S1"]["area_hold"]["footprint"]
    assert island["area_mm2"] == footprint["area_mm2"]
    assert island["polar_mm3"] == footprint["polar_mm3"]
    assert island["kept"] is True
    assert island["cut"] is None


def test_a_clearing_cut_reports_its_reach_and_the_before_top(engine, parts):
    step = parts["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    clear = {
        **_op("S1:10", "wall", 3.0, 15.0, 30.0),
        "stock_removal_bounds": {"x": [30.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 22.0]},
        "faces": wall + floor,
    }
    hold = _hold([_plate(top=-0.1, x=(-20.0, 80.0))])
    result = _run(engine, step, hold, [clear], {"wall": wall, "floor": floor}, STEP_STOCK)
    (island,) = result["ops"]["S1:10"]["area_hold"]["islands"]
    assert island["area_mm2"] == pytest.approx(60 * 50)
    assert island["centroid_mm"] == pytest.approx([30.0, 20.0], abs=1e-6)
    cut = island["cut"]
    assert cut["volume_mm3"] == pytest.approx(30 * 40 * 12)
    # The farthest removed point from the centroid (30, 20) is a corner of the clearing
    # box: (60, 0) or (60, 40), 36.06 mm away.
    assert cut["reach_mm"] == pytest.approx(math.hypot(30, 20), abs=1e-6)
    assert cut["top_z_mm"] == pytest.approx(22.0)
    assert all(30.0 - 1e-6 <= x <= 60.0 + 1e-6 for x, _ in cut["points_mm"])


def test_no_area_hold_emits_no_area_facts(engine, parts):
    hold = _hold()
    del hold["area"]
    result = _run(engine, parts["strap"], hold)
    assert "area_hold" not in result["setups"]["S1"]


# --- host payload -------------------------------------------------------------------------


def test_the_engine_hold_carries_the_area_payload():
    hold = {"kind": "custom", "solids": [], "pose": {}, "area": {"on": "sub:plate"}}
    assert _engine_hold(hold)["area"] == {"on": "sub:plate"}
    assert "area" not in _engine_hold({"kind": "custom", "solids": [], "pose": {}})


class _Inventory:
    def __init__(self, inventory):
        self.inventory = inventory


MEASURED = {"status": "measured", "by": "test", "date": "2026-10-11", "instrument": "mic"}
_PLATE_ITEM = {
    "kind": "custom",
    "solids": [
        {
            "name": "plate",
            "shape": "box",
            "at_mm": [-200.0, -50.0, -10.1],
            "size_mm": [400.0, 100.0, 10.0],
        }
    ],
}


def _host(thickness, fixture=None, on="plate"):
    tape = {"kind": "adhesive_tape", "thickness_mm": thickness}
    bundle = _Inventory(
        {
            "fixtures": {"sub": fixture or _PLATE_ITEM},
            "consumables": {"tape": tape},
            "machines": {"mill": {"kind": "mill"}},
        }
    )
    hold = {
        "fixture": "sub",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "area": {"ref": "tape", "on": on},
    }
    return hold_inputs(bundle, {"id": "S1", "machine": "mill", "hold": hold})


def test_a_measured_pair_reaches_the_engine_as_the_layer_thickness():
    hold = _host({"value": PAIR, "measured": MEASURED})
    assert hold["area"] == {"on": "sub:plate", "thickness_mm": PAIR}
    assert _engine_hold(hold)["area"] == hold["area"]


@pytest.mark.parametrize(
    "thickness",
    [
        PAIR,  # a datasheet pair is printed, never drawn (D4)
        {"value": PAIR, "measured": {**MEASURED, "status": "assumed"}},
        {"value": PAIR, "measured": MEASURED, "verify": True},
    ],
)
def test_an_unmeasured_pair_reaches_the_engine_without_a_thickness(thickness):
    area = _host(thickness)["area"]
    assert area["on"] == "sub:plate" and "thickness_mm" not in area
    assert area["thickness_reason"].startswith("thickness_mm is not a measured pair")


def test_an_area_hold_on_a_kind_without_solids_reaches_the_engine_as_a_reason():
    area = _host(PAIR, fixture={"kind": "custom"})["area"]
    assert set(area) == {"reason"}


def test_an_unknown_seat_reaches_the_engine_as_a_reason():
    area = _host(PAIR, on="unknown")["area"]
    assert area == {"reason": "the area hold names no seat solid (hold.area.on)"}
