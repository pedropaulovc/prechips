"""A center-drill spot at a long through bore's mouth reaches only its authored depth.

A spot stops at its hole entry minus its authored ``depth_mm`` even in a through hole,
and every sample on its claimed bore wall stands at or above that tip. So a 2 mm spot
at the mouth of a 74 or 86 mm bore reaches 2 mm and its drill chuck clears the vise,
while the stub drill through the same bore reaches the whole bore plus its point and
the same chuck meets both jaws once the tip is deep. The jaw gap is the blank width
and the chuck is wider than that gap, so only depth separates the two. The host
resolves the selected center-drill set member, drill and chuck into the engine job and
locates each tip as ``tip_endpoints`` does; the reach and accessibility rules consume
the native result. FreeCAD-backed tests skip without ``freecadcmd``.
"""

import hashlib
import math
import subprocess
from copy import deepcopy

import pytest
from test_kernel_geometry import Engine
from test_kernel_stock import _bundle

from prechips import kernel
from prechips.rules import accessibility, reach
from prechips.rules.tip_endpoints import evaluate

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
# 60x40 blocks 74 and 86 tall, each with a 6.5 mm bore through its height at (30, 20).
for height in (74, 86):
    block = Part.makeBox(60, 40, height).cut(Part.makeCylinder(3.25, height + 2, V(30, 20, -1)))
    assert block.isValid() and len(block.Solids) == 1, height
    block.exportStep(out + "/bore-%d.step" % height)
"""
BORE = 3.25
DEPTH = 2.0  # authored spot depth below the mouth
JAW_TOP = 50.0  # jaw top above the parallels: below every mouth, above the deep chuck
DRILL_POINT = BORE / math.tan(math.radians(59.0))  # the 6.5 mm drill's 118 degree point
SPOT, DRILL = "center-drills-lms-4859/2", "stub-drill-6.5"
INVENTORY = {
    "tools": {
        # LittleMachineShop #2 combined drill and countersink: 3/16 in body, 60 degree
        # countersink, 1-7/8 in long; its chuck projection is OAL minus the chuck grip. Its
        # 3/16 in shank is what lets the shallow spot's reach pass: unknown, it never does.
        "center-drills-lms-4859": {
            "kind": "center_drill_set",
            "sizes": [1, 2, 3, 4, 5],
            "verify": False,
            "members": {
                "2": {
                    "dia_in": 0.1875,
                    "shank_in": 0.1875,
                    "point_angle": 60.0,
                    "flute_len_in": 0.25,
                    "oal_in": 1.875,
                }
            },
        },
        # DIN 1897 stub drill: 70 mm long, 31 mm flutes.
        DRILL: {
            "kind": "drill",
            "dia_mm": 6.5,
            "point_angle": 118.0,
            "flute_len_mm": 31.0,
            "oal_mm": 70.0,
            "verify": False,
        },
    },
    "holders": {
        # A 50 mm keyless chuck body: wider than the 40 mm jaw gap.
        "drill-chuck-r8": {
            "kind": "drill_chuck",
            "gauge_dia_mm": 50.0,
            "gauge_len_mm": 70.0,
            "grip_mm": 25.0,
            "verify": False,
        }
    },
    "fixtures": {
        "vise": {
            "kind": "vise",
            "jaw_width_mm": 150.0,
            "jaw_depth_mm": 20.0,
            "jaw_height_mm": 45.0,
            "opening_mm": 150.0,
            "verify": False,
        },
        "parallels": {"kind": "parallels", "height_mm": 16.0, "verify": False},
    },
}


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("mouth-solids")
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


def _host(tmp_path, engine, step, height):
    """S1 spots the bore's mouth from the 60x40 blank's top, then drills through it."""
    faces = engine.refs(step, (30 - BORE, 20 - BORE, 0), (30 + BORE, 20 + BORE, height), "Cylinder")
    assert faces
    bundle = _bundle(tmp_path)
    bundle.paths["step"] = step
    bundle.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    bundle.features["features"] = {"bore": {"kind": "hole", "thru": True, "faces": faces}}
    bundle.plan["stock"]["section_mm"] = [40.0, float(height)]
    bundle.inventory.update(deepcopy(INVENTORY))
    setup = bundle.plan["setups"][0]
    # Jaws along x clamp the blank's 40 mm width, centred on the bore along x.
    setup["hold"].update(grip_mm=JAW_TOP, jaw_above_parallels_mm=JAW_TOP, jaw_center_along_mm=30.0)
    setup["stock_state"] = {"top_z": float(height), "local_thickness": {"bore": float(height)}}
    hole = {"feature": "bore", "holder": "drill-chuck-r8"}
    setup["ops"] = [
        {"op": 10, "do": "spot", "tool": SPOT, "depth_mm": DEPTH, **hole},
        {"op": 20, "do": "drill", "tool": DRILL, "exit_mm": 0.0, **hole},
    ]
    return bundle


@pytest.mark.parametrize("height", [74, 86])
def test_mouth_spot_reaches_its_depth_where_the_through_drills_chuck_meets_the_jaws(
    engine, solids, tmp_path, monkeypatch, freecad_kernel, kernel_cache, height
):
    monkeypatch.setenv("FREECAD_CMD", freecad_kernel)
    bundle = _host(tmp_path, engine, solids[f"bore-{height}"], height)
    (endpoints,) = [f.numbers["endpoints"] for f in evaluate(bundle) if f.subject == "bore"]
    tips = {row["op"]: row["tip_z"] for row in endpoints}
    assert tips == pytest.approx({10: height - DEPTH, 20: -DRILL_POINT})
    facts = kernel.run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    spot, drill = facts["ops"]["S1:10"], facts["ops"]["S1:20"]
    # Each reach is the blank above the host's tip: the spot's mouth, the drill's bore.
    assert spot["reach_depth_mm"] == pytest.approx(height - tips[10], abs=1e-6)
    assert drill["reach_depth_mm"] == pytest.approx(height - tips[20], abs=1e-4)
    assert spot["tool_hits"] == 0 and spot["holder_hits"] == 0
    assert spot["obstacles"] == {"tool": [], "holder": []}
    # The control: the same chuck behind the deep drill meets both jaws and the block, so
    # the spot's clear chuck is measured against placed fixture solids.
    assert drill["obstacles"]["holder"] == ["fixed_jaw", "moving_jaw", "part"]
    rows = {
        (row.rule, row.subject): row
        for rule in (reach, accessibility)
        for row in rule.evaluate(bundle)
    }
    assert rows["reach", "S1:10"].status == "pass"
    assert rows["reach", "S1:10"].numbers["reach_depth_mm"] == pytest.approx(DEPTH, abs=1e-6)
    assert rows["accessibility", "S1:10"].status == "pass"
    assert rows["accessibility", "S1:20"].status == "error"
