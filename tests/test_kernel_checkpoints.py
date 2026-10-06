"""Every printed DRO cutter-centre checkpoint stands where rule A′ lets the cutter.

The kernel stands the op's cutter cylinder at each printed row, from its tip up above the
setup-entry stock. Finished material, the op's leave and fixture solids always error. A
bounded op's printed paths are first clipped where its cutter first meets stock outside its
clearing box: a path that leaves and re-enters is pieces, never reconnected. An unbounded
profile op's printed run-out is credited removal: its corner miter may nick retained scrap,
but never stock a later setup grips, presses, locates, rests or supports on; a later setup
whose contacts are unresolved leaves the rows unknown. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise
from test_kernel_held_split import UP, _box
from test_kernel_stock_prefix import BLANK, HOLD

from prechips.rules.coordinates import FRAGMENT_FORMAT, ROW_FORMAT

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
Part.makeBox(60, 40, 20, V(5, 5, 0)).exportStep(out + "/island.step")
"""
# The island's west wall is x = 5, y 5..45; the blank is x 0..70, y -5..55, z 0..20.
WEST = ((5, 5, 0), (5, 45, 20))
NORTH = ((5, 45, 0), (65, 45, 20))
# The later setup's vise with its parallels drawn under y -3..3 and 47..53.
SEATED = _vise(5.0, centre=35.0, parallels=(150.0, 6.0, [[35.0, 0.0], [35.0, 50.0]]))
# A cutter centre 3 mm off the west wall and 3 mm off the north wall's line: the corner
# miter of the island's north-west corner, 3 mm past the west wall's corridor end disc.
MITER = [("line -X", [(2.0, 5.0), (2.0, 45.0), (2.0, 48.0)])]


@pytest.fixture(scope="module")
def island(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("checkpoint-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    step = directory / "island.step"
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _printed(subject, stage, tables, tip=0.0, overshoot=(), bounded=False):
    """Coordinates checkpoints as build_job passes them: each ``(name, points)`` line table
    a path of named rows, its cutter clearing from the left of its travel; ``overshoot``
    names the corner-miter row ids. A ``bounded`` op's tables print on a 0.001 mm DRO."""
    rows, paths = [], []
    for name, points in tables:
        name = f"{subject} {stage} {name}"
        ids = [name + ROW_FORMAT["line_table"].format(i) for i in range(len(points))]
        for row_id, xy in zip(ids, points, strict=True):
            row = {"id": row_id, "xy_mm": list(xy), "tip_z_mm": tip}
            rows.append({**row, "overshoot": True} if row_id in overshoot else row)
        paths.append(
            {
                "table": ids[0],
                "name": name,
                "kind": "line_table",
                "cutter_side": "left",
                "directed": True,
                "xy_mm": [list(xy) for xy in points],
                "tip_z_mm": tip,
                "ids": ids,
                "overshoot": [row_id in overshoot for row_id in ids],
            }
        )
    result = {"rows": rows, "paths": paths, "bounded": bounded}
    if bounded:
        result["dro"] = {"step": 0.001, "decimals": 3, "scale": 1.0}
        result["row_format"], result["fragment_format"] = ROW_FORMAT, FRAGMENT_FORMAT
    return result


def _job(engine, step, ops, later=SEATED, **walls):
    features = {}
    for name, (lo, hi) in walls.items():
        features[name] = engine.refs(step, lo, hi, kind="Plane")
        assert len(features[name]) == 1, name
    setups = [_setup(ops, HOLD, setup_id="S1"), _setup([], later, setup_id="S2")]
    return engine.job(step, features, setups, stock=BLANK)


def _profile(radius, tables, tip=0.0, overshoot=()):
    """A full-depth finish profile of the west wall printing ``tables``."""
    op = _op("S1:10", "west", radius, 25.0, 30.0)
    return {
        **op,
        "do": "finish_profile",
        "to_z": 0.0,
        "checkpoints": _printed("S1:10", "finish", tables, tip, overshoot),
    }


def _clamped(at, gaps=()):
    """A later fixture: a floor plate under the blank and a 10 x 2 x 5 press pad on the
    stock top (z 20) centred at ``at``."""
    pad = _box("pad:pad", [-5.0, -1.0, 0.0], [10.0, 2.0, 5.0])
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [_box("nest:floor", [-5.0, -10.0, -5.0], [80.0, 70.0, 5.0])],
        "clamps": [
            {
                "name": "clamp 1 pad",
                "pose": {"origin_mm": [at[0], at[1], 20.0], **UP},
                "solids": [pad],
                "restraint": "press",
            }
        ],
        "debts": [],
        "gaps": list(gaps),
    }


def _errors(op):
    return {(error["row"], error["obstacle"]) for error in op["checkpoint_errors"]}


def _later(op):
    return {
        (error["row"], error["later_setup"], error["contact"])
        for error in op["checkpoint_errors"]
        if "later_setup" in error
    }


# A rough cutter off the DRO grid, so no contact lands on a grid point; the kernel's cutter
# is LIFT (1 um) narrower than its radius.
RADIUS = 3.0003
RHO = RADIUS - 1e-3


def _bounded(tables, stage="rough", box=(0.0, 5.0, -5.0, 20.0), subject="S1:10"):
    """A west-wall profile bounded by default to the blank's west strip south of y 20;
    a rough one leaves 0.2 mm."""
    op = {
        **_op(subject, "west", RADIUS, 25.0, 30.0),
        "do": f"{stage}_profile",
        "to_z": 0.0,
        "stock_removal_bounds": {"x": list(box[:2]), "y": list(box[2:]), "z": [0.0, 20.0]},
    }
    if stage == "rough":
        op["rough_allowance_mm"] = 0.2
    if tables:
        op["checkpoints"] = _printed(subject, stage, tables, bounded=True)
    return op


def _clips(engine, island, tables, ops=(), **bounded):
    job = _job(engine, island, [*ops, _bounded(tables, **bounded)], west=WEST)
    facts = engine.run(job)["ops"]["S1:10"]
    clips = facts["checkpoint_clips"]
    assert "reason" not in clips, clips
    # The clipped rows are all rule A′ judges, and they are clear.
    assert facts["checkpoint_errors"] == [] and facts["checkpoint_hits"] == 0, facts
    return facts, clips


def test_a_bounded_sweep_grazing_the_finished_part_between_clear_rows_is_not_clipped(
    engine, island
):
    # Op 5 clears the frame about the island's south-west corner; op 10's chord then
    # grazes that corner 0.01 mm between two clear rows, as a printed arc's chord sags
    # into its wall. The finished part is rule A′'s obstacle at the rows, never stock the
    # clip stops at, though it lies outside op 10's box.
    cleared = _bounded([], stage="finish", box=(0.0, 20.0, -5.0, 20.0), subject="S1:5")
    c = 10.0 - (RHO - 0.01) * math.sqrt(2)  # the chord x + y = c
    path = [(1.5, c - 1.5), (c - 1.5, 1.5)]
    box = (0.0, 5.0, -5.0, 5.0)
    facts, clips = _clips(engine, island, [("line S", path)], [cleared], stage="finish", box=box)
    (entry,) = clips["paths"]
    assert entry["pieces"] == [[{"row": 0}, {"row": 1}]] and entry["clip_points"] == []
    assert facts["checkpoint_count"] == 2


def test_a_bounded_path_past_its_box_only_through_air_is_not_clipped(engine, island):
    # Inside the box beside the leave, then west and north past the box in the air beyond
    # the blank's x 0: no stock outside the box is ever met.
    path = [(1.5, 0.0), (1.5, 10.0), (-10.0, 10.0), (-10.0, 40.0)]
    facts, clips = _clips(engine, island, [("line -X", path)])
    (entry,) = clips["paths"]
    assert entry["pieces"] == [[{"row": i} for i in range(4)]]
    assert entry["clip_points"] == [] and entry["dropped_rows"] == []
    assert facts["checkpoint_count"] == 4


def test_a_bounded_path_into_stock_past_its_box_ends_at_the_first_contact(engine, island):
    facts, clips = _clips(engine, island, [("line -X", [(1.5, 0.0), (1.5, 40.0)])])
    (entry,) = clips["paths"]
    ((first, end),) = entry["pieces"]
    assert first == {"row": 0} and entry["dropped_rows"] == ["S1:10 rough line -X[1]"]
    # The cutter first meets the blank past the box's y 20 when its edge reaches it.
    contact = 20.0 - RHO
    assert end["after"] == 0
    assert end["exact_xy"][0] == pytest.approx(1.5)
    assert abs(end["exact_xy"][1] - contact) <= clips["precision_mm"], end
    # Printed on the DRO grid on the legal side: short of the contact, never past it.
    assert end["dro_xy"] == [1.5, 17.0]
    assert facts["checkpoint_count"] == 2


def test_a_bounded_path_that_leaves_and_reenters_its_box_is_two_pieces(engine, island):
    # North into stock past y 20, west out of the blank, then south and back east into the
    # box: the legal parts are two pieces, the stock between them never reconnected.
    path = [(1.5, 0.0), (1.5, 40.0), (-10.0, 40.0), (-10.0, 10.0), (1.5, 10.0)]
    facts, clips = _clips(engine, island, [("line -X", path)])
    (entry,) = clips["paths"]
    leave, enter = entry["pieces"]
    assert leave[0] == {"row": 0} and leave[1]["after"] == 0
    assert enter[0]["after"] == 1 and enter[1:] == [{"row": 2}, {"row": 3}, {"row": 4}]
    assert entry["dropped_rows"] == ["S1:10 rough line -X[1]"]
    # It regains the path once the cutter's edge clears the blank's x 0 face.
    assert abs(enter[0]["exact_xy"][0] + RHO) <= clips["precision_mm"], enter[0]
    assert enter[0]["dro_xy"] == [-3.0, 40.0]
    assert [point["after"] for point in entry["clip_points"]] == [
        "S1:10 rough line -X[0]",
        "S1:10 rough line -X[1]",
    ]
    assert facts["checkpoint_count"] == 6


def test_a_corner_miter_into_retained_scrap_is_legal_and_noted(engine, island):
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    result = engine.run(_job(engine, island, [profile], later=_clamped((35.0, 30.0)), west=WEST))
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], facts
    assert facts["checkpoint_overshoot_ok"] == ["S1:10 finish line -X[2]"]
    # The builder credits the printed miter, so the later setup sees the notch.
    assert "stock_reason" not in result["setups"]["S2"], result["setups"]["S2"]


def test_the_same_miter_under_a_later_press_pad_is_an_error_naming_the_setup(engine, island):
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    # The pad spans y 49..51 over the miter's scrap, which reaches y 51.
    result = engine.run(_job(engine, island, [profile], later=_clamped((2.0, 50.0)), west=WEST))
    facts = result["ops"]["S1:10"]
    assert _later(facts) == {("S1:10 finish line -X[2]", "S2", "clamp press")}, facts
    assert facts["checkpoint_hits"] == 1
    (error,) = facts["checkpoint_errors"]
    assert error["area_mm2"] > 1.0, error
    # A row with an error keeps it: no operator OK note.
    assert facts["checkpoint_overshoot_ok"] == []


def test_an_unresolved_later_contact_leaves_the_rows_unknown(engine, island):
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    later = _clamped((35.0, 30.0), gaps=["a toe clamp is not drawn"])
    result = engine.run(_job(engine, island, [profile], later=later, west=WEST))
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == "unknown", facts
    assert (
        "later setup S2 has undrawn components (a toe clamp is not drawn)"
        in (facts["checkpoint_reason"])
    )
    assert facts["checkpoint_overshoot_ok"] == []


def test_a_run_out_that_parts_the_stock_is_refused_by_the_held_split_check(engine, island):
    # A 4 mm corridor leaves a 1 mm web west of it joining the gripped frame; run-outs
    # west across it at both wall ends cut a free strip out of the frame.
    walled = [("line -X", [(3.0, 5.0), (3.0, 45.0)])]
    run_out = [("line -X", [(-3.0, 5.0), (3.0, 5.0), (3.0, 45.0), (-3.0, 45.0)])]
    plain, parted = engine.run(
        {
            "jobs": [
                _job(engine, island, [_profile(2.0, walled)], west=WEST),
                _job(engine, island, [_profile(2.0, run_out)], west=WEST),
            ]
        }
    )["results"]
    assert "stock_reason" not in plain["setups"]["S2"], plain["setups"]["S2"]
    reason = parted["setups"]["S2"]["stock_reason"]
    assert "S1:10: removing its claimed clearance splits an input stock piece" in reason, reason
    facts = parted["ops"]["S1:10"]
    # Rule A′ cannot judge the rows against a later setup whose entry stock is unknown.
    assert facts["checkpoint_hits"] == "unknown"
    assert "later setup S2's entry stock is unknown" in facts["checkpoint_reason"]
