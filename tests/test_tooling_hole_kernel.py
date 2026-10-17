"""The kernel drills a plan tooling hole in the waste and tracks it to the saw (#293).

A 40 x 40 x 20 part sits in a 60 x 40 x 20 box of stock; X 40..60 is waste. The hole
CL is drilled and reamed through that waste at X 50, Y 20. Later setups see it
``present`` until a saw takes the waste, then ``gone``.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import _op, _vise
from test_kernel_stock import BOX, PackagedEngine

_AUTHOR = r"""
import sys
import Part
out = sys.argv[sys.argv.index("--") + 1]
Part.makeBox(40, 40, 20).exportStep(out + "/part.step")
"""
LABEL = "plan.process_features.cl"
BAND = [6.010, 6.022]


@pytest.fixture(scope="module")
def part(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("tooling-part")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    step = directory / "part.step"
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


@pytest.fixture
def engine(tmp_path, freecad_kernel, kernel_cache):
    return PackagedEngine(tmp_path, freecad_kernel)


def hole(at=(50.0, 20.0, 20.0), axis=(0.0, 0.0, -1.0), depth=None):
    spec = {"kind": "tooling_hole", "label": LABEL, "at_mm": list(at), "axis": list(axis)}
    spec["dia_mm"] = list(BAND)
    if depth is None:
        spec["thru"] = True
    else:
        spec.update(thru=False, depth_mm=depth)
    return spec


def cut_op(subject, action, diameter, spec, exit_mm=1.0):
    op = _op(subject, "cl", diameter / 2, 30.0, 60.0)
    op["do"] = action
    cut = {"process_feature": "cl", "action": action, **spec, "diameter_mm": diameter}
    if action == "drill":
        cut["point_angle_deg"] = 118.0
    if spec.get("thru"):
        cut["exit_mm"] = exit_mm
    op["process_cut"] = cut
    return op


def saw(subject, value, keep="below"):
    return {
        "subject": subject,
        "do": "saw_cut",
        "cut_plane": {"axis": "x", "value": value, "keep": keep},
        "kerf_mm": 1.0,
    }


def setup(sid, ops):
    return {
        "id": sid,
        "frame": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
        "machine_kind": "mill",
        "hold": _vise(12.0),
        "ops": ops,
    }


def run(engine, part, spec, setups):
    job = engine.job(part, setups=setups, stock=BOX)
    job["process_features"] = {"cl": spec}
    result = engine.run(job)
    assert result["status"] == "ok", result
    return result


def states(result):
    return {
        sid: facts.get("tooling_holes", {}).get("cl", {}).get("state")
        for sid, facts in result["setups"].items()
    }


def test_drilled_and_reamed_in_the_waste_then_sawn_off(engine, part):
    spec = hole()
    result = run(
        engine,
        part,
        spec,
        [
            setup(
                "T1", [cut_op("T1:10", "drill", 5.8, spec), cut_op("T1:20", "ream", 6.016, spec)]
            ),
            setup("T3", []),
            setup("T4", [saw("T4:10", 40.6)]),
            setup("T5", []),
        ],
    )
    assert states(result) == {"T1": "undrilled", "T3": "present", "T4": "present", "T5": "gone"}
    ream = math.pi * (6.016 / 2) ** 2 * 20.0
    assert result["setups"]["T3"]["stock_volume_mm3"] == pytest.approx(48000.0 - ream, rel=1e-6)
    for subject in ("T1:10", "T1:20"):
        op = result["ops"][subject]
        # The cut itself is modelled: nothing the op leaves unknown names the hole.
        assert LABEL not in str(op.get("reasons")), op["reasons"]


def test_a_blind_hole_stops_at_its_depth(engine, part):
    spec = hole(depth=8.0)
    result = run(
        engine, part, spec, [setup("T1", [cut_op("T1:10", "ream", 6.016, spec)]), setup("T2", [])]
    )
    assert states(result)["T2"] == "present"
    removed = 48000.0 - result["setups"]["T2"]["stock_volume_mm3"]
    assert removed == pytest.approx(math.pi * 3.008**2 * 8.0, rel=1e-6)


def test_a_saw_through_the_hole_leaves_it_partial(engine, part):
    spec = hole()
    result = run(
        engine,
        part,
        spec,
        [setup("T1", [cut_op("T1:10", "ream", 6.016, spec), saw("T1:20", 51.0)]), setup("T2", [])],
    )
    assert states(result)["T2"] == "partial"


def test_a_hole_off_the_tool_axis_is_not_drilled(engine, part):
    spec = hole(at=(60.0, 20.0, 10.0), axis=(-1.0, 0.0, 0.0), depth=8.0)
    result = run(
        engine, part, spec, [setup("T1", [cut_op("T1:10", "drill", 5.8, spec)]), setup("T2", [])]
    )
    op = result["ops"]["T1:10"]
    # As for a centre hole, the op's tool facts stay unknown; its stock still loses the hole.
    assert "not the setup -Z feed" in op["reason"]
    assert states(result)["T2"] == "present"


def test_a_plan_without_tooling_holes_reports_no_tooling_facts(engine, part):
    result = engine.run(engine.job(part, setups=[setup("T1", [])], stock=BOX))
    assert "tooling_holes" not in result["setups"]["T1"]
