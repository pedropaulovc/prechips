"""Turning on a modelled chuck, routed turned stock and per-piece fragmentation, end to end.

The shafts are authored along model +X (x 30..70), so every lathe setup uses the
nonidentity ``TURN`` frame whose Z is the spindle axis: a 12 mm journal (setup z 0..20)
stepped through an R1 fillet to an 8 mm journal (z 20..40). Assertions read only the
JSON of ``freecad_job.py`` run on these solids.
"""

import math
import subprocess

import pytest
from test_fixture_solids import _chuck
from test_kernel_geometry import IDENTITY, Engine, _op
from test_turning_geometry import FINISHED_MM3, _fillet_ring_mm3, _turn

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
X = V(1, 0, 0)

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

sharp = Part.makeCylinder(6, 20, V(30, 0, 0), X).fuse(
    Part.makeCylinder(4, 20, V(50, 0, 0), X)
).removeSplitter()
corner = [
    e for e in sharp.Edges
    if abs(e.BoundBox.XMin - 50) < 1e-6 and abs(e.BoundBox.XMax - 50) < 1e-6
    and abs(e.BoundBox.ZMax - 4) < 1e-6
]
filleted = sharp.makeFillet(1.0, corner)
save("filleted", filleted)
# A milled flat at model z = 3 across the 8 mm journal (x 55..65).
save("flatted", filleted.cut(Part.makeBox(10, 10, 10, V(55, -5, 3))))
"""
_AUTHORED = 2

# Setup frame: x = model y, y = model z, z = model x - 30 (the spindle axis).
TURN = {
    "origin": [30.0, 0.0, 0.0],
    "x": [0.0, 1.0, 0.0],
    "y": [0.0, 0.0, 1.0],
    "z": [1.0, 0.0, 0.0],
}
BAR = {
    "shape": "round",
    "dia_mm": 12.0,
    "length_mm": 40.0,
    "origin_mm": [30.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
}
BAR_MM3 = math.pi * 36 * 40
# The 12 mm bar turned to the filleted shaft: the R1 fillet's material stays.
TURNED_MM3 = FINISHED_MM3 + math.pi * (25 * 1 - 16) - _fillet_ring_mm3()
JAWS = ["chuck jaw 1", "chuck jaw 2", "chuck jaw 3"]
UNHELD = {"reason": "holding not modelled here"}


@pytest.fixture(scope="module")
def shafts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("routed-shafts")
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


def _lathe(setup_id, ops, hold, **extra):
    """A lathe setup on ``TURN``: rotating chuck solids revolve about setup Z."""
    return {
        "id": setup_id,
        "frame": TURN,
        "machine_kind": "lathe",
        "hold": hold,
        "ops": ops,
        **extra,
    }


def _mill_flat(setup_id, stock_in):
    """A model-frame mill setup cutting the flat from +Z, receiving ``stock_in``."""
    ops = [_op(setup_id + ":10", "flat", 3.0, 15.0, 30.0)]
    return {"id": setup_id, "stock_in": stock_in, "frame": IDENTITY, "hold": UNHELD, "ops": ops}


def _journals(engine, step):
    """Model-frame refs: the gripped 12 mm journal and the exposed 8 mm journal profile."""
    large = engine.refs(step, (30, -6, -6), (50, 6, 6), kind="Cylinder")
    small = engine.refs(step, (50, -4, -4), (70, 4, 4), kind="Cylinder")
    shoulder = engine.refs(step, (50, -6, -6), (50, 6, 6), kind="Plane")
    fillet = engine.refs(step, (50, -5, -5), (51, 5, 5), kind="Toroid")
    assert large and small and shoulder and fillet
    return {"grip": large, "exposed": small + shoulder + fillet}


def test_rotating_chuck_jaws_obstruct_turning_in_the_grip_zone_only(engine, shafts):
    step = shafts["filleted"]
    features = _journals(engine, step)
    ops = [
        _turn("T1:10", "exposed", z_from=40.0, z_to=20.0),
        _turn("T1:20", "grip", z_from=20.0, z_to=0.0),
    ]
    gap = "tailstock centre pose is undeclared"
    held, gapped = engine.run(
        {
            "jobs": [
                engine.job(step, features, [_lathe("T1", ops, hold)], stock=BAR)
                for hold in (_chuck(face_z=10.0), _chuck(face_z=10.0, gaps=[gap]))
            ]
        }
    )["results"]
    setup = held["setups"]["T1"]
    # The jaws close on the 12 mm bar over setup z 0..10; a solid bar's run under each
    # jaw is its full diameter, and only the gripped journal is claimed inside them.
    assert setup["chuck"]["contact_radii_mm"] == [6.0, 6.0, 6.0]
    assert setup["grip_zone_z_mm"] == [0.0, 10.0]
    assert setup["min_wall_mm"] == pytest.approx(12.0)
    assert setup["claimed_in_jaws"] == sorted(features["grip"])
    assert setup["fixture_rendered"] is True
    exposed, grip = held["ops"]["T1:10"], held["ops"]["T1:20"]
    # Placed chuck solids make the exposed journal's clear samples a certain pass.
    assert exposed["tool_hits"] == 0 and exposed["holder_hits"] == 0
    assert exposed["obstacles"] == {"tool": [], "holder": []}
    # Turning the gripped journal runs the insert and toolpost into the revolving jaws
    # near the jaw face, and clear of them beyond it.
    assert grip["obstacles"] == {"tool": JAWS, "holder": JAWS}
    assert 0 < grip["tool_hits"] < grip["sample_count"]
    assert 0 < grip["holder_hits"] <= grip["tool_hits"]
    # An undrawn component leaves clear samples unknown; jaw hits stay certain.
    gapped_exposed, gapped_grip = gapped["ops"]["T1:10"], gapped["ops"]["T1:20"]
    assert gapped_exposed["tool_hits"] == "unknown"
    assert gapped_exposed["min_hits"]["tool"] == 0
    assert "undrawn fixture components" in gapped_exposed["reasons"]["tool_hits"]
    assert gapped_grip["tool_hits"] == "unknown"
    assert gapped_grip["min_hits"] == {"tool": grip["tool_hits"], "holder": grip["holder_hits"]}
    assert gapped_grip["obstacles"] == grip["obstacles"]
    reason = gapped_grip["reasons"]["tool_hits"]
    assert gap in reason and f"{grip['tool_hits']} sample(s) certainly hit" in reason


def test_turned_output_routes_past_an_unrelated_setup_into_a_model_frame_mill(engine, shafts):
    step = shafts["flatted"]
    features = _journals(engine, step)
    features["flat"] = engine.refs(step, (55, -5, 3), (65, 5, 3), kind="Plane")
    assert len(features["flat"]) == 1
    setups = [
        _lathe("T1", [_turn("T1:10", "exposed", z_from=40.0, z_to=20.0)], _chuck(face_z=10.0)),
        _mill_flat("X1", "stock"),
        _mill_flat("M1", "T1"),
    ]
    result = engine.run(engine.job(step, features, setups, stock=BAR))
    rows = result["setups"]
    # T1 holds the bar in its own frame: the spindle axis is setup Z.
    assert rows["T1"]["stock_bbox_mm"] == pytest.approx([-6.0, -6.0, 0.0, 6.0, 6.0, 40.0])
    assert rows["T1"]["stock_volume_mm3"] == pytest.approx(BAR_MM3, rel=1e-6)
    # M1 receives T1's turned shaft (not X1's untouched bar) back in the model frame.
    # The turn stops at the 8 mm meridian, so the overstock above the flat remains.
    for sid, volume in (("X1", BAR_MM3), ("M1", TURNED_MM3)):
        assert rows[sid]["stock_bbox_mm"] == pytest.approx([30.0, -6.0, -6.0, 70.0, 6.0, 6.0])
        assert rows[sid]["stock_volume_mm3"] == pytest.approx(volume, rel=1e-6)
        assert rows[sid]["render_png_base64"] and "stock_reason" not in rows[sid]
    # The flat at z 3 lies under the 8 mm journal's top (z 4), not the raw bar's (z 6).
    assert result["ops"]["X1:10"]["reach_depth_mm"] == pytest.approx(3.0, abs=1e-3)
    assert result["ops"]["M1:10"]["reach_depth_mm"] == pytest.approx(1.0, abs=1e-3)


def _lug(x0, length):
    """A 2 x 4 mm bar-stock lug at model y 8..10, z -2..2 (setup radius 8..10)."""
    return {
        "shape": "box",
        "origin_mm": [x0, 8.0, -2.0],
        "axis": [1.0, 0.0, 0.0],
        "section_axis": [0.0, 1.0, 0.0],
        "length_mm": length,
        "section_mm": [2.0, 4.0],
    }


def test_turning_keeps_a_separate_supply_piece_but_refuses_to_split_one(engine, shafts):
    step = shafts["filleted"]
    features = _journals(engine, step)
    setups = [
        _lathe(
            "T1",
            [_turn("T1:10", "exposed", z_from=40.0, z_to=20.0)],
            UNHELD,
            stock_in=["stock.bar", "stock.lug"],
        ),
        {"id": "S2", "frame": IDENTITY, "hold": UNHELD, "ops": []},
    ]
    # Setup z 0..15 lies below the turned window; z 15..45 straddles both its ends.
    kept, split = engine.run(
        {
            "jobs": [
                engine.job(step, features, setups, stock={"components": {"bar": BAR, "lug": lug}})
                for lug in (_lug(30.0, 15.0), _lug(45.0, 30.0))
            ]
        }
    )["results"]
    row = kept["setups"]["S2"]
    assert row["stock_volume_mm3"] == pytest.approx(TURNED_MM3 + 15 * 2 * 4, rel=1e-6)
    assert row["stock_bbox_mm"] == pytest.approx([30.0, -6.0, -6.0, 70.0, 10.0, 6.0])
    assert row["render_png_base64"] and "stock_reason" not in row
    row = split["setups"]["S2"]
    splits = "T1:10: removing its claimed clearance splits an input stock piece into 2"
    assert splits in row["stock_reason"]
    assert "render_png_base64" not in row and "stock_volume_mm3" not in row
