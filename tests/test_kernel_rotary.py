"""Rotary dividing-head milling: each sample turned under the vertical spindle.

Engine tests run ``freecad_job.py`` on solids authored here and read only its JSON.
"""

import subprocess

import pytest
from test_fixture_solids import _box, _chuck
from test_kernel_geometry import Engine, _op, _setup

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
V = FreeCAD.Vector
X = V(1, 0, 0)
# R8 tail x -15..0 for the head's chuck, R10 body x 0..60 along setup X.
tail = Part.makeCylinder(8, 15, V(-15, 0, 0), X)
# A 10 x 6 pad standing proud of the body (top z 13) at x 25..35.
pad = Part.makeBox(10, 6, 5, V(25, -3, 8))
body = Part.makeCylinder(10, 60, V(0, 0, 0), X)
tail.fuse(body).fuse(pad).removeSplitter().exportStep(out + "/padded.step")
# The body steps down to R9 at x 30; a pad on the step at x 31..35 rises to z 13.
step = Part.makeCylinder(10, 30, V(0, 0, 0), X).fuse(Part.makeCylinder(9, 30, V(30, 0, 0), X))
near = Part.makeBox(4, 6, 6, V(31, -3, 7))
tail.fuse(step).fuse(near).removeSplitter().exportStep(out + "/stepped.step")
# A round R4 boss standing proud of the body (top z 13) at x 30: its curved wall fans
# away from the radial sweep of the holed body face.
boss = Part.makeCylinder(4, 6, V(30, 0, 7), V(0, 0, 1))
tail.fuse(body).fuse(boss).removeSplitter().exportStep(out + "/bossed.step")
"""

# Head axis along setup +X, jaw face at x = -5: the jaws grip the tail at x -15..-5.
HEAD = {"origin_mm": [-5.0, 0.0, 0.0], "x": [0.0, 0.0, 1.0], "z": [1.0, 0.0, 0.0]}
BODY = ((0, -10, -10), (60, 10, 10))


@pytest.fixture(scope="module")
def parts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("rotary")
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
    assert len(paths) == 3, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _head(pose=HEAD):
    return _chuck(
        fixture_kind="dividing_head",
        pose=pose,
        head_solids=[_box("BS-0:body", [-60.0, -60.0, -80.0], [120.0, 120.0, 80.0])],
    )


def _rotary(engine, step, body, hold, stock=None, **window):
    op = {**_op("S1:10", "body", 3.0, 10.0, 30.0), "approach": "rotary", **window}
    job = engine.job(step, {"body": body}, [_setup([op], hold)], stock=stock)
    result = engine.run(job)
    assert result["status"] == "ok", result
    return result["ops"]["S1:10"]


def test_rotary_floor_beside_an_unclaimed_proud_pad_clears_it(engine, parts):
    step = parts["padded"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    assert len(body) == 1
    op = _rotary(engine, step, body, _head())
    assert op["approach"] == "rotary" and op["claim_errors"] == []
    # Every sample, edges on the pad walls included, is turned to the top and clears.
    assert op["sample_count"] > 25
    assert op["tool_hits"] == 0 and op["holder_hits"] == 0, op


@pytest.mark.xfail(
    strict=True,
    reason="open: the radial sweep of a holed face fans past a curved pad wall, so the "
    "wall-tangent cutter meets the stock kept over the boss (cone #550/#885 shows the same)",
)
def test_rotary_floor_beside_a_round_boss_cuts_the_stock_over_it(engine, parts):
    # Round R15 bar: the boss keeps a fanned stock column; the cutter tangent to the boss
    # wall cuts that stock where it stands and clears the finished boss. The window runs
    # from the jaw face so the relieved bar ends ahead of the body's convex end edge.
    step = parts["bossed"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    assert len(body) == 1
    bar = {"shape": "round", "dia_mm": 30.0, "length_mm": 75.0}
    stock = {**bar, "origin_mm": [-15.0, 0.0, 0.0], "axis": [1.0, 0.0, 0.0]}
    op = _rotary(engine, step, body, _head(), stock, z_from=0.0, z_to=70.0)
    assert op["claim_errors"] == [] and op["sample_count"] > 25
    assert op["tool_hits"] == 0, op


def test_rotary_cutter_hits_a_pad_lying_in_its_path(engine, parts):
    # The claimed R10 band ends at a convex step; the cutter centred on that edge
    # reaches over the R9 step onto the pad 1 mm beyond it.
    step = parts["stepped"]
    body = engine.refs(step, (0, -10, -10), (30, 10, 10), kind="Cylinder")
    assert len(body) == 1
    op = _rotary(engine, step, body, _head())
    assert op["tool_hits"] > 0 and op["obstacles"]["tool"] == ["part"], op
    assert op["hit_refs"]["tool"], op


def test_rotary_claims_outside_the_angle_window_are_claim_errors(engine, parts):
    step = parts["padded"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    full = _rotary(engine, step, body, _head(), angle_window_deg=[-180.0, 180.0])
    assert full["claim_errors"] == [] and full["claimed_indices"] != []
    quarter = _rotary(engine, step, body, _head(), angle_window_deg=[0.0, 90.0])
    assert quarter["claim_errors"] == body and quarter["claimed_indices"] == []


def test_head_axis_not_perpendicular_to_setup_z_is_unsupported(engine, parts):
    step = parts["padded"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    upright = {"origin_mm": [0.0, 0.0, -5.0], "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
    op = _rotary(engine, step, body, _head(upright))
    assert "not perpendicular to setup Z" in op["unsupported_reason"]
    assert op["tool_hits"] == "unknown" and op["claimed_indices"] == "unknown"
