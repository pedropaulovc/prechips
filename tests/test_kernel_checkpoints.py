"""Every printed DRO cutter-centre checkpoint stands where the stock model lets the cutter.

The kernel stands the op's cutter cylinder at each printed row, from its tip up above the
setup-entry stock. A bounded op's cutter may meet only stock inside its clearing box; an
unbounded profile op's printed run-out may run on through stock any cut of the setup
removes, but not through stock the setup keeps, and the stock builder credits the
run-out, so its held-split check sees it. Finished material and fixture solids always
error. FreeCAD-backed tests run ``src/prechips/kernel/freecad_job.py`` under
``freecadcmd`` and skip without it.
"""

import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup
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


def _printed(subject, stage, tables):
    """Coordinates checkpoints as build_job passes them: each table a path of named rows."""
    rows, paths = [], []
    for name, points in tables:
        rows += [
            {"id": f"{subject} {stage} {name}[{i}]", "xy_mm": list(xy), "tip_z_mm": 0.0}
            for i, xy in enumerate(points)
        ]
        paths.append({"xy_mm": [list(xy) for xy in points], "tip_z_mm": 0.0})
    return {"rows": rows, "paths": paths}


def _job(engine, step, ops, **walls):
    features = {}
    for name, (lo, hi) in walls.items():
        features[name] = engine.refs(step, lo, hi, kind="Plane")
        assert len(features[name]) == 1, name
    setups = [_setup(ops, HOLD, setup_id="S1"), _setup([], HOLD, setup_id="S2")]
    return engine.job(step, features, setups, stock=BLANK)


def _profile(radius, tables):
    """A full-depth finish profile of the west wall printing ``tables``."""
    op = _op("S1:10", "west", radius, 25.0, 30.0)
    return {
        **op,
        "do": "finish_profile",
        "to_z": 0.0,
        "checkpoints": _printed("S1:10", "finish", tables),
    }


def _errors(op):
    return {(error["row"], error["obstacle"]) for error in op["checkpoint_errors"]}


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


def test_a_run_out_may_cross_stock_a_later_cut_removes_never_stock_the_setup_keeps(
    engine, island
):
    # The cutter runs past the wall's north end, 3 mm beyond the corridor's end disc.
    tables = [("line -X", [(2.0, 5.0), (2.0, 45.0), (2.0, 51.0)])]
    clears = {
        **_op("S1:20", "north", 3.0, 25.0, 30.0),
        "do": "rough_profile",
        "rough_allowance_mm": 0.0,
        "to_z": 0.0,
        "stock_removal_bounds": {"x": [0.0, 70.0], "y": [45.0, 55.0], "z": [0.0, 20.0]},
    }
    alone = _job(engine, island, [_profile(3.0, tables)], west=WEST)
    cleared = _job(engine, island, [_profile(3.0, tables), clears], west=WEST, north=NORTH)
    kept, later = engine.run({"jobs": [alone, cleared]})["results"]
    facts = kept["ops"]["S1:10"]
    assert _errors(facts) == {("S1:10 finish line -X[2]", "stock the setup keeps")}, facts
    assert facts["checkpoint_hits"] == 1
    # The builder credits the run-out, so its own after-stock alone would never show it.
    assert "stock_reason" not in kept["setups"]["S2"], kept["setups"]["S2"]
    facts = later["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], facts


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
    assert facts["checkpoint_hits"] == "unknown"
    assert "the setup's output stock is not derived" in facts["checkpoint_reason"]
