"""The FreeCAD turning model measured on authored turned solids.

Setup Z is the spindle axis, +Z the free end.  Every shaft is a 12 mm journal
(r 6, z 0..20) stepped to an 8 mm journal (r 4, z 20..40); the variants add a
shoulder fillet, a milled flat or a bore.  Assertions read the engine's JSON.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import IDENTITY, Engine

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

def shaft():
    return Part.makeCylinder(6, 20).fuse(Part.makeCylinder(4, 20, V(0, 0, 20))).removeSplitter()

sharp = shaft()
save("shaft", sharp)
corner = [
    e for e in sharp.Edges
    if abs(e.BoundBox.ZMin - 20) < 1e-6 and abs(e.BoundBox.XMax - 4) < 1e-6
]
save("filleted", sharp.makeFillet(1.0, corner))
save("flatted", sharp.cut(Part.makeBox(10, 10, 10, V(-5, 3, 25))))
save("bored", sharp.cut(Part.makeCylinder(2, 10, V(0, 0, 31))))
"""
_AUTHORED = 4
FINISHED_MM3 = math.pi * (36 * 20 + 16 * 20)


@pytest.fixture(scope="module")
def shafts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("shafts")
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
    assert len(paths) == _AUTHORED, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _turn(subject, feature, nose=0.4, **extra):
    """A right-hand 93-degree triangular-insert tool on a radial QCTP shank."""
    return {
        "subject": subject,
        "feature": feature,
        "do": "finish_turn",
        "approach": "turning",
        "finishing": True,
        "radius_mm": nose,
        "insert_angle_deg": 60.0,
        "entering_angle_deg": 93.0,
        "feed_z": -1,
        "edge_len_mm": 11.0,
        "head_len_mm": 15.0,
        "shank_width_mm": 10.0,
        "functional_width_mm": 12.0,
        "projection_mm": 25.0,
        "holder_body_width_mm": 30.0,
        "holder_body_depth_mm": 20.0,
        **extra,
    }


_CHUCK = {"kind": "chuck_3jaw", "method": "unknown"}


def _bar(length=40.0, dia=12.0):
    return {
        "shape": "round",
        "dia_mm": dia,
        "length_mm": length,
        "origin_mm": [0, 0, 0],
        "axis": [0, 0, 1],
    }


def _lathe(ops, setup_id="S1"):
    return {"id": setup_id, "frame": IDENTITY, "hold": _CHUCK, "ops": ops}


def _features(engine, step):
    small = engine.refs(step, (-4, -4, 20), (4, 4, 40), kind="Cylinder")
    shoulder = engine.refs(step, (-6, -6, 20), (6, 6, 20), kind="Plane")
    end = engine.refs(step, (-4, -4, 40), (4, 4, 40), kind="Plane")
    fillet = engine.refs(step, (-5, -5, 20), (5, 5, 21), kind="Toroid")
    return {"small": small + shoulder + fillet, "end": end, "shoulder": shoulder}


def test_nose_radius_meets_a_sharp_shoulder_but_clears_a_larger_fillet(engine, shafts):
    sharp_step, round_step = shafts["shaft"], shafts["filleted"]
    sharp = engine.run(
        engine.job(
            sharp_step,
            _features(engine, sharp_step),
            [_lathe([_turn("S1:10", "small", z_from=40.0, z_to=20.0)])],
            stock=_bar(),
        )
    )["ops"]["S1:10"]
    filleted = engine.run(
        engine.job(
            round_step,
            _features(engine, round_step),
            [_lathe([_turn("S1:10", "small", z_from=40.0, z_to=20.0)])],
            stock=_bar(),
        )
    )["ops"]["S1:10"]
    assert sharp["approach"] == filleted["approach"] == "turning"
    assert sharp["corner_radii_mm"] == [0.0] and sharp["min_hits"]["tool"] > 0
    assert sharp["obstacles"]["tool"] == ["part"]
    assert filleted["corner_radii_mm"] == [1.0] and filleted["min_hits"]["tool"] == 0
    # No fixture solid is placed for the chuck here, so a clear sample is not a pass.
    assert filleted["tool_hits"] == "unknown"
    assert "fixture solids unresolved" in filleted["reasons"]["tool_hits"]
    assert filleted["min_hits"]["holder"] == 0 and filleted["holder_wall_hits"] == 0
    # The 12 mm bar is turned to 8 mm: 2 mm of material beside the nose, well inside the edge.
    assert filleted["reach_depth_mm"] == pytest.approx(2.0, abs=1e-3)


def test_a_fillet_smaller_than_the_nose_is_a_corner_the_nose_cannot_form(engine, shafts):
    step = shafts["filleted"]
    detail = engine.run(
        engine.job(
            step,
            _features(engine, step),
            [_lathe([_turn("S1:10", "small", nose=1.2, z_from=40.0, z_to=20.0)])],
            stock=_bar(),
        )
    )["ops"]["S1:10"]
    assert detail["corner_radii_mm"] == [1.0] and detail["min_hits"]["tool"] > 0


def test_turned_and_faced_stock_is_what_the_next_setup_receives(engine, shafts):
    step = shafts["filleted"]
    features = _features(engine, step)
    hold = {"reason": "chuck not modelled here"}
    turned = [_turn("S1:10", "small", z_from=40.0, z_to=20.0)]
    result = engine.run(
        engine.job(
            step,
            features,
            [_lathe(turned), {"id": "S2", "frame": IDENTITY, "hold": hold, "ops": []}],
            stock=_bar(),
        )
    )
    fillet = math.pi * (25 * 1 - 16) - _fillet_ring_mm3()
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(
        FINISHED_MM3 + fillet, rel=1e-6
    )
    # Facing a shoulder clears outside its innermost radius up to the finished end only,
    # leaving the stub beyond it; facing the end clears the stub.
    longer, sharp = _bar(length=45.0), shafts["shaft"]
    shoulder = engine.run(
        engine.job(
            sharp,
            _features(engine, sharp),
            [_lathe([_turn("S1:10", "shoulder", to_z=20.0)]), {**_lathe([], "S2"), "hold": hold}],
            stock=longer,
        )
    )["setups"]["S2"]["stock_volume_mm3"]
    assert shoulder == pytest.approx(FINISHED_MM3 + math.pi * 36 * 5, rel=1e-6)
    ends = engine.run(
        engine.job(
            step,
            features,
            [
                _lathe(
                    [
                        _turn("S1:10", "end", to_z=40.0),
                        _turn("S1:20", "small", z_from=40.0, z_to=20.0),
                    ]
                ),
                {**_lathe([], "S2"), "hold": hold},
            ],
            stock=longer,
        )
    )["setups"]["S2"]["stock_volume_mm3"]
    assert ends == pytest.approx(FINISHED_MM3 + fillet, rel=1e-6)


def _fillet_ring_mm3():
    """Volume of the R1 concave fillet's air: ring of quarter-disc section centred r 5, z 21."""
    # Pappus: quarter-disc area x path of its centroid (r = 5 - 4/(3 pi)).
    return (math.pi / 4) * 2 * math.pi * (5 - 4 / (3 * math.pi))


def test_a_milled_flat_is_not_turnable_and_a_bore_is_not_modelled(engine, shafts):
    flat_step, bore_step = shafts["flatted"], shafts["bored"]
    flat_plane = engine.refs(flat_step, (-5, 3, 25), (5, 3, 35), kind="Plane")
    flat = engine.run(
        engine.job(
            flat_step,
            {"flat": flat_plane},
            [_lathe([_turn("S1:10", "flat", z_from=40.0, z_to=20.0)])],
            stock=_bar(),
        )
    )["ops"]["S1:10"]
    assert flat["claim_errors"] == flat_plane and flat["sample_count"] == "unknown"
    bore = engine.refs(bore_step, (-2, -2, 30), (2, 2, 40), kind="Cylinder")
    bored = engine.run(
        engine.job(
            bore_step,
            {"bore": bore},
            [_lathe([_turn("S1:10", "bore", z_from=40.0, z_to=30.0)])],
            stock=_bar(),
        )
    )["ops"]["S1:10"]
    assert "internal turning" in bored["unsupported_reason"]
    assert bored["claimed_indices"] == "unknown"
