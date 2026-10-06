"""A hole's claimed point cap is credited only when its complete-form cut forms it.

The host marks each feature's last drill/ream/bore/counterbore ``complete_form``. The
engine then checks that op's own claimed caps against the setup's final stock. Pilots,
spots and taps are never checked. A cap that still touches stock is named in the op's
``cap_completion`` and makes the output stock debt. ``finish_coverage`` withholds credit
for it even when no later setup consumes that stock. Accessibility facts stay as they
are: a too-flat point that clears the finished cap is no collision. FreeCAD-backed
tests skip without ``freecadcmd``.
"""

import hashlib
import math
import subprocess

import pytest
from test_kernel_geometry import HOLE_BLANK, Engine, _op, _setup, _vise
from test_kernel_stock import _bundle

from prechips import kernel
from prechips.rules import finish_coverage

_AUTHOR = r"""
import math, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

# A 118 degree R3.25 drill's blind hole: full diameter z 10..20, point apex below z 10.
point = 3.25 / math.tan(math.radians(59))
drilled = Part.makeCylinder(3.25, 11, V(30, 20, 10)).fuse(
    Part.makeCone(3.25, 0, point, V(30, 20, 10), V(0, 0, -1))
)
save("drilled", Part.makeBox(60, 40, 20).cut(drilled).removeSplitter())
# An R3.25 blind bore z 10..20 ending in a hemisphere of its own radius.
ball = Part.makeCylinder(3.25, 11, V(30, 20, 10)).fuse(Part.makeSphere(3.25, V(30, 20, 10)))
save("ball", Part.makeBox(60, 40, 20).cut(ball.removeSplitter()).removeSplitter())
"""
HOLD = _vise(5.0, centre=30.0)
DRILL = 3.25
POINT = DRILL / math.tan(math.radians(59.0))
DRILLED_MM3 = 48000.0 - math.pi * DRILL**2 * (10.0 + POINT / 3)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("cap-solids")
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


def _hole_op(subject, complete, angle=118.0, radius=DRILL, do="drill", to_z=None):
    hole = {"thru": False, "depth_mm": 10.0, "entry_z_mm": 20.0, "complete_form": complete}
    if do == "drill":
        hole["point_angle_deg"] = angle
    op = {**_op(subject, "hole", radius, 25.0, 30.0), "do": do, "hole": hole}
    if to_z is not None:
        op["to_z"] = to_z
    return op


def _claims(engine, step):
    """The blind hole's bore plus its own cap (the cone or hemisphere below z 10)."""
    lo, hi = (30 - DRILL, 20 - DRILL), (30 + DRILL, 20 + DRILL)
    bore = engine.refs(step, (*lo, 10), (*hi, 20), "Cylinder")
    caps = [
        ref
        for kind in ("Cone", "Sphere")
        for ref in engine.refs(step, (*lo, 0), (*hi, 10), kind)
    ]
    assert len(bore) == 1 and len(caps) == 1
    return bore, caps[0]


def _run(engine, step, ops):
    """S1 cuts the hole; S2 consumes its output stock."""
    bore, cap = _claims(engine, step)
    setups = [_setup(ops, HOLD, setup_id="S1"), _setup([], HOLD, setup_id="S2")]
    result = engine.run(engine.job(step, {"hole": bore + [cap]}, setups, stock=HOLE_BLANK))
    assert result["status"] == "ok", result
    index = next(face["index"] for face in result["faces"] if face["ref"] == cap)
    return result, cap, index


@pytest.mark.parametrize(
    "solid, angle, complete, formed",
    [
        ("drilled", 118.0, True, True),
        ("drilled", 140.0, True, False),
        ("drilled", 140.0, False, None),
        # A pointed drill never forms a hemisphere, whatever its angle.
        ("ball", 118.0, True, False),
    ],
)
def test_complete_form_cut_must_leave_its_claimed_cap_clear(
    engine, solids, solid, angle, complete, formed
):
    result, cap, index = _run(engine, solids[solid], [_hole_op("S1:10", complete, angle)])
    detail, s2 = result["ops"]["S1:10"], result["setups"]["S2"]
    # A flatter point stays above the finished cap: no collision either way.
    assert detail["tool_hits"] == 0 and detail["holder_hits"] == 0
    if formed is None:
        # A preparation cut keeps its exact partial stock and is never judged.
        assert "cap_completion" not in detail
        assert s2["stock_volume_mm3"] > DRILLED_MM3
    elif formed:
        assert detail["cap_completion"] == {"caps": [index], "unformed": []}
        assert s2["stock_volume_mm3"] == pytest.approx(DRILLED_MM3, abs=1e-3)
    else:
        assert detail["cap_completion"] == {"caps": [index], "unformed": [index]}
        assert "stock_volume_mm3" not in s2
        assert "S1:10" in s2["stock_reason"] and cap in s2["stock_reason"]


def test_cap_is_judged_after_every_cut_of_the_setup(engine, solids):
    # A flatter preparation point first, then the matching final point.
    ops = [_hole_op("S1:10", False, 140.0), _hole_op("S1:20", True, 118.0)]
    result, _, index = _run(engine, solids["drilled"], ops)
    assert result["ops"]["S1:20"]["cap_completion"] == {"caps": [index], "unformed": []}
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(DRILLED_MM3, abs=1e-3)


def test_stock_left_below_a_flat_finishing_floor_still_leaves_the_cap_unformed(engine, solids):
    # Every residue lies below the ream's z 10 floor; a to_z-clipped check would pass it.
    ops = [
        _hole_op("S1:10", False, 118.0, radius=3.0),
        _hole_op("S1:20", True, do="ream", to_z=10.0),
    ]
    result, cap, index = _run(engine, solids["drilled"], ops)
    assert result["ops"]["S1:20"]["cap_completion"]["unformed"] == [index]
    assert "stock_volume_mm3" not in result["setups"]["S2"]
    assert cap in result["setups"]["S2"]["stock_reason"]


def test_cut_that_removes_nothing_is_still_judged(engine, solids):
    result, _, index = _run(engine, solids["drilled"], [_hole_op("S1:10", True, to_z=21.0)])
    assert result["ops"]["S1:10"]["cap_completion"]["unformed"] == [index]
    assert "stock_volume_mm3" not in result["setups"]["S2"]


def test_unmeasurable_completion_is_unknown_not_formed(engine, solids):
    result, _, index = _run(engine, solids["drilled"], [_hole_op("S1:10", True, "unknown")])
    completion = result["ops"]["S1:10"]["cap_completion"]
    assert completion["caps"] == [index] and completion["unformed"] == "unknown"
    assert "point_angle_deg" in completion["reason"]


# ------------------------------------------------------------------ host classification


def _classify(tmp_path, features, routes):
    bundle = _bundle(tmp_path)
    bundle.features["features"] = features
    bundle.plan["setups"] = [
        {
            "id": sid,
            "machine": "mill",
            "frame": "A",
            "stock_in": "stock",
            "hold": {},
            "ops": [
                {"op": 10 * number, "feature": feature, "tool": "em", **op}
                for number, (feature, op) in enumerate(ops, 1)
            ],
        }
        for sid, ops in routes
    ]
    return {
        op["subject"]: op["hole"]["complete_form"]
        for setup in kernel.build_job(bundle)["setups"]
        for op in setup["ops"]
        if "hole" in op
    }


HOLE = {"kind": "hole", "thru": False, "faces": ["#1"]}
DRILL_OP, DEPTH = {"do": "drill", "depth_mm": 10.0}, {"depth_mm": 10.0}


@pytest.mark.parametrize(
    "features, routes, owners",
    [
        (
            {"h": HOLE},
            [("S1", [("h", {"do": "spot", "depth_mm": 1.0}), ("h", DRILL_OP), ("h", DRILL_OP)])],
            {"S1:30"},
        ),
        ({"h": HOLE}, [("S1", [("h", DRILL_OP), ("h", {"do": "ream", **DEPTH})])], {"S1:20"}),
        (
            {"c": {"kind": "counterbore", "faces": ["#1"]}},
            [("S1", [("c", DRILL_OP), ("c", {"do": "counterbore", "depth_mm": 4.0})])],
            {"S1:20"},
        ),
        ({"h": HOLE}, [("S1", [("h", DRILL_OP)]), ("S2", [("h", DRILL_OP)])], {"S2:10"}),
        # A tap never forms the cone: the thread's last drill owns it.
        (
            {"t": {"kind": "threaded_hole", "depth": [5.0, 6.0], "faces": ["#1"]}},
            [("S1", [("t", DRILL_OP), ("t", {"do": "tap"})])],
            {"S1:10"},
        ),
        (
            {"a": HOLE, "b": HOLE},
            [("S1", [("a", DRILL_OP), ("b", DRILL_OP), ("a", {"do": "bore", **DEPTH})])],
            {"S1:20", "S1:30"},
        ),
    ],
)
def test_only_each_features_last_forming_cut_owns_its_caps(tmp_path, features, routes, owners):
    flags = _classify(tmp_path, features, routes)
    assert {subject for subject, flag in flags.items() if flag is True} == owners
    assert all(flag is False for subject, flag in flags.items() if subject not in owners)


# ------------------------------------------------------- host terminal consumer (finish)


def _finish(tmp_path, solids, engine, angles):
    """One finish-required blind hole drilled in S1 only: nothing consumes its stock."""
    step = solids["drilled"]
    bore, cap = _claims(engine, step)
    bundle = _bundle(tmp_path)
    bundle.paths["step"] = step
    bundle.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    bundle.features["features"] = {
        "hole": {"kind": "hole", "thru": False, "faces": bore + [cap], "finish_ra": 1.6}
    }
    first = bundle.plan["setups"][0]
    first.update(hold={**first["hold"], "jaw_center_along_mm": 30.0}, stock_state={"top_z": 20.0})
    first["ops"] = []
    for number, angle in enumerate(angles, 1):
        bundle.inventory["tools"][f"drill{number}"] = {
            "kind": "drill",
            "dia_mm": 2 * DRILL,
            "flute_len_mm": 25.0,
            "oal_mm": 60.0,
            "projection_mm": {"holder": 30.0},
            "point_angle": angle,
            "verify": False,
        }
        first["ops"].append(
            {
                "op": 10 * number,
                "do": "drill",
                "feature": "hole",
                "tool": f"drill{number}",
                "holder": "holder",
                "depth_mm": 10.0,
            }
        )
    (row,) = [f for f in finish_coverage.evaluate(bundle) if f.subject == "hole"]
    return row, kernel.run_geometry(bundle)


@pytest.mark.parametrize(
    "angles, status",
    [
        ([118.0], "pass"),
        ([140.0], "error"),
        # The flatter pilot's leftover is gone after the matching final drill.
        ([140.0, 118.0], "pass"),
        (["unknown"], "unknown"),
    ],
)
def test_terminal_finish_credit_needs_a_formed_cap(
    tmp_path, solids, engine, kernel_cache, angles, status
):
    row, facts = _finish(tmp_path, solids, engine, angles)
    assert row.status == status
    if status == "error":
        (cap,) = row.numbers["unformed_caps"]
        assert row.numbers["uncovered_faces"] == [cap]
        # The cap is stock debt, not a collision with finished material.
        assert facts["ops"]["S1:10"]["tool_hits"] == 0
    elif status == "unknown":
        assert "point_angle_deg" in row.sentence
