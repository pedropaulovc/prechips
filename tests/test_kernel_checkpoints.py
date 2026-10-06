"""Every printed DRO cutter-centre checkpoint stands where rule A′ lets the cutter.

The kernel stands the op's cutter cylinder at each printed row, from its tip up above the
setup-entry stock. Finished material, the op's leave and fixture solids always error, and
a bounded op's cutter may meet only stock inside its clearing box. An unbounded profile
op's printed run-out is credited removal: its corner miter may nick retained scrap, but
never stock a later setup grips, presses, locates, rests or supports on; a later setup
whose contacts are unresolved leaves the rows unknown. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise
from test_kernel_held_split import UP, _box
from test_kernel_stock_prefix import BLANK, HOLD

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


def _printed(subject, stage, tables, tip=0.0, overshoot=()):
    """Coordinates checkpoints as build_job passes them: each table a path of named rows;
    ``overshoot`` names the corner-miter row ids."""
    rows, paths = [], []
    for name, points in tables:
        for i, xy in enumerate(points):
            row = {"id": f"{subject} {stage} {name}[{i}]", "xy_mm": list(xy), "tip_z_mm": tip}
            rows.append({**row, "overshoot": True} if row["id"] in overshoot else row)
        paths.append({"xy_mm": [list(xy) for xy in points], "tip_z_mm": tip})
    return {"rows": rows, "paths": paths}


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


def test_a_bounded_cutter_meets_only_stock_inside_its_box(engine, island):
    op = _op("S1:10", "west", 3.0, 25.0, 30.0)
    rough = {
        **op,
        "do": "rough_profile",
        "rough_allowance_mm": 0.2,
        "to_z": 0.0,
        # The box clears the west strip's south half only.
        "stock_removal_bounds": {"x": [0.0, 5.0], "y": [-5.0, 20.0], "z": [0.0, 20.0]},
        # 1.8 = 5 - 0.2 leave - 3 radius: tangent to the leave.
        "checkpoints": _printed(
            "S1:10", "rough", [("line -X", [(1.8, 10.0), (1.8, 25.0), (8.0, 30.0), (35.0, -8.0)])]
        ),
    }
    result = engine.run(_job(engine, island, [rough], west=WEST))
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_count"] == 4
    # Inside the box beside the leave: clear. Past the box's y 20: stock it never removes.
    # Over the island: the finished part. South of the blank: the front (moving) vise jaw.
    assert _errors(facts) == {
        ("S1:10 rough line -X[1]", "stock outside its stock_removal_bounds"),
        ("S1:10 rough line -X[2]", "finished part"),
        ("S1:10 rough line -X[3]", "moving_jaw"),
    }, facts
    assert facts["checkpoint_hits"] == 3
    assert all(error["volume_mm3"] > 1.0 for error in facts["checkpoint_errors"])


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


def test_unclipped_rows_gouging_a_rail_a_later_setup_clamps_are_errors(engine, island):
    # The box clears y 45..52 above z 10 and keeps the 3 mm rail y 52..55; its inset box
    # lets the cutter centre reach y 49. The clipped row stands at y 48; the old unclipped
    # one at y 50.5 runs 1.5 mm into the rail, under the later pad on y 53..55.
    rough = {
        **_op("S1:20", "north", 3.0, 25.0, 30.0),
        "do": "rough_profile",
        "rough_allowance_mm": 0.0,
        "to_z": 10.0,
        "stock_removal_bounds": {"x": [0.0, 70.0], "y": [45.0, 52.0], "z": [0.0, 20.0]},
        "checkpoints": _printed(
            "S1:20", "rough", [("line clipped", [(30.0, 48.0)]), ("line old", [(40.0, 50.5)])], 10.0
        ),
    }
    result = engine.run(_job(engine, island, [rough], later=_clamped((40.0, 54.0)), north=NORTH))
    facts = result["ops"]["S1:20"]
    assert _errors(facts) == {
        ("S1:20 rough line old[0]", "stock outside its stock_removal_bounds"),
        ("S1:20 rough line old[0]", "pad:pad"),
    }, facts
    assert _later(facts) == {("S1:20 rough line old[0]", "S2", "clamp press")}
    assert facts["checkpoint_hits"] == 1


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
