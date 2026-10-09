"""A rotary table is an authored-solids fixture: base, table, bore and T-slots, worm housing
and handwheel at the setup's ``hold.pose``.

The engine places and draws it like an angle plate: the part clamped on its top renders
with every component exact and no debt, and a profile op's printed cutter-centre
checkpoints are checked against it. Engine tests run ``freecad_job.py`` under
``freecadcmd`` and skip without it; host tests check which inventory facts reach it.
"""

import math
import subprocess

import pytest
from test_fixture_solids import MEASURED, UP, _box, _cylinder, _hold
from test_kernel_geometry import Engine, _op, _setup

from prechips.kernel import _engine_hold

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
# R15 x 10 puck on the setup Z axis, bottom face z = 0.
Part.makeCylinder(15, 10).exportStep(out + "/puck.step")
"""
CUTTER = 3.0
TIP = 0.5


def _table_solids():
    """A 150 mm rotary table, its top at local z = 0 on the local Z axis."""
    return [
        _box("base", [-80.0, -80.0, -60.0], [160.0, 160.0, 30.0]),
        _cylinder("table", [0.0, 0.0, -30.0], 150.0, 30.0),
        {**_cylinder("bore", [0.0, 0.0, -61.0], 20.0, 62.0), "void": True},
        {**_box("slot x", [-75.0, -6.0, -10.0], [150.0, 12.0, 11.0]), "void": True},
        {**_box("slot y", [-6.0, -75.0, -10.0], [12.0, 150.0, 11.0]), "void": True},
        _box("worm housing", [80.0, -20.0, -58.0], [30.0, 40.0, 26.0]),
        _cylinder("handwheel", [110.0, 0.0, -45.0], 60.0, 15.0, axis=[1.0, 0.0, 0.0]),
    ]


def _owned(owner, solids):
    """Engine primitives as the host names them (``owner:name``)."""
    return [
        {**solid, "name": f"{owner}:{solid['name']}", "local": solid["name"]} for solid in solids
    ]


def _washer():
    """A 20 mm washer on the puck's top, clear of the cutter running round its side."""
    return {
        "name": "clamp 1 kit/washer",
        "pose": {"origin_mm": [0.0, 0.0, 10.0], **UP},
        "solids": [{**_cylinder("kit/washer:washer", [0.0, 0.0, 0.0], 20.0, 4.0), "local": "w"}],
    }


@pytest.fixture(scope="module")
def puck(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("rotary-table")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    path = directory / "puck.step"
    assert path.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return path


def test_a_part_clamped_on_a_rotary_table_renders_exact_and_its_checkpoints_clear_it(
    tmp_path, freecad_kernel, puck
):
    engine = Engine(tmp_path, freecad_kernel)
    side = engine.refs(puck, (-15, -15, 0), (15, 15, 10), kind="Cylinder")
    assert len(side) == 1
    hold = {
        "kind": "solids",
        "fixture_kind": "rotary_table",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": _owned("rotary-table", _table_solids()),
        "clamps": [_washer()],
        "debts": [],
        "gaps": [],
    }
    # The cutter centre runs round the R15 side on R18 every 30 degrees, its tip 0.5 above
    # the table top.
    radius = 15.0 + CUTTER
    rows = [
        {
            "id": f"A{index}",
            "xy_mm": [
                radius * math.cos(math.radians(30 * index)),
                radius * math.sin(math.radians(30 * index)),
            ],
            "tip_z_mm": TIP,
        }
        for index in range(12)
    ]
    op = {
        **_op("S1:10", "side", CUTTER, 15.0, 30.0),
        "do": "finish_profile",
        "to_z": TIP,
        "checkpoints": {"rows": rows, "paths": [], "bounded": False},
    }
    result = engine.run(engine.job(puck, {"side": side}, [_setup([op], hold)]))
    assert result["status"] == "ok", result
    setup = result["setups"]["S1"]
    scene = setup["render_scene"]
    assert scene["fixture_kind"] == "rotary_table"
    assert scene["debts"] == [] and scene["render_debts"] == []
    assert setup["fixture_rendered"] is True
    names = {component["name"] for component in scene["components"]}
    assert {
        "rotary-table:base",
        "rotary-table:table",
        "rotary-table:worm housing",
        "rotary-table:handwheel",
        "kit/washer:washer",
    } <= names
    assert all(component["exact"] for component in scene["components"])
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_count"] == len(rows)
    assert facts["checkpoint_errors"] == [] and facts["checkpoint_hits"] == 0, facts

    # A separate printed position sinks the cutter 2 mm into solid table material:
    # x=y=18 is outside the R15 part and beyond both 12 mm wide T-slots. Keep A0
    # as an above-table clear control in the same checkpoint evaluation.
    colliding_op = {
        **op,
        "checkpoints": {
            "rows": [
                rows[0],
                {"id": "TABLE", "xy_mm": [18.0, 18.0], "tip_z_mm": -2.0},
            ],
            "paths": [],
            "bounded": False,
        },
    }
    colliding = engine.run(engine.job(puck, {"side": side}, [_setup([colliding_op], hold)]))
    collision_facts = colliding["ops"]["S1:10"]
    assert collision_facts["checkpoint_count"] == 2
    assert collision_facts["checkpoint_hits"] == 1, collision_facts
    errors = collision_facts["checkpoint_errors"]
    assert [(error["row"], error["obstacle"]) for error in errors] == [
        ("TABLE", "rotary-table:table")
    ], errors
    assert errors[0]["volume_mm3"] > 10.0, errors


def test_a_rotary_table_hold_reaches_the_engine_as_posed_solids():
    table = {
        "kind": "rotary_table",
        "t_slots": 4,
        "graduation_deg": 1.0,
        "vernier_deg": 0.1,
        "dial_increases": "counterclockwise",
        "solids": [{**solid, "measured": MEASURED} for solid in _table_solids()],
    }
    pose = {"origin_mm": [0.0, 0.0, 0.0], **UP}
    hold = _hold({"rt": table}, {"fixture": "rt", "pose": pose}, {"mill": {"kind": "mill"}})
    assert "reason" not in hold and hold["gaps"] == []
    engine = _engine_hold(hold)
    assert engine["kind"] == "solids" and engine["fixture_kind"] == "rotary_table"
    assert engine["pose"] == pose
    assert [solid["name"] for solid in engine["solids"]] == [
        f"rt:{solid['name']}" for solid in _table_solids()
    ]
    unposed = _hold({"rt": table}, {"fixture": "rt"}, {"mill": {"kind": "mill"}})
    assert "pose" in unposed["reason"] and "pose" not in _engine_hold(unposed)
