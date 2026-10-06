"""The rough-leave guard of a part whose whole-part offset OCC cannot build.

The cone pivot post has tangent zero-height lands (journal pads and the crank land tangent
to their cylinders); its whole finished-part offset by 0.3 mm fails with both join types.
A small authored solid with the same features offsets fine, so the stock test drives the
tracked example STEP; the skin's edge and Boolean judgements are probed on authored solids.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from test_kernel_geometry import Engine, _vise

from prechips import kernel

_PROBE = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("kernel_under_test", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

def kind(solid, inside):
    box = FreeCAD.BoundBox(*inside)
    found = [
        job._dihedral(edge, solid.Faces[a], solid.Faces[b])
        for edge, a, b in job._shared_edges(solid.Faces, range(len(solid.Faces)))
        if box.isInside(edge.BoundBox)
    ]
    assert len(found) == 1, found
    return found[0]

def material(shape):
    try:
        kept = job._material(shape, "it")
    except ValueError:
        return "invalid"
    return "empty" if kept is None else "solid"

box = Part.makeBox(10, 10, 10)
ell = box.fuse(Part.makeBox(10, 20, 5)).removeSplitter()
post = box.fuse(Part.makeCylinder(3, 5, V(5, 5, 10))).removeSplitter()
rounded = box.makeFillet(2, [e for e in box.Edges if e.BoundBox.ZLength == 10][:1])
nurbs = box.toNurbs()
speck = [Part.makeBox(0.005, 0.005, 0.005, V(5, 5, 5))]
corner = [Part.makeBox(1, 1, 1)]
taken = box.cut(Part.makeBox(1, 1, 1 - 5e-7, V(0, 0, 5e-7)))
result = {
    "line": kind(box, (9.9, -0.1, 9.9, 10.1, 10.1, 10.1)),
    "inner line": kind(ell, (-0.1, 9.9, 4.9, 10.1, 10.1, 5.1)),
    "arc": kind(post, (1.9, 1.9, 14.9, 8.1, 8.1, 15.1)),
    "inner arc": kind(post, (1.9, 1.9, 9.9, 8.1, 8.1, 10.1)),
    "fillet": kind(rounded, (-0.1, 1.9, -0.1, 0.1, 2.1, 10.1)),
    "freeform": sorted({
        str(job._dihedral(edge, nurbs.Faces[a], nurbs.Faces[b]))
        for edge, a, b in job._shared_edges(nurbs.Faces, range(len(nurbs.Faces)))
    }),
    "apart": material(box.common(Part.makeBox(1, 1, 1, V(50, 50, 50)))),
    "overlapping": material(box.common(Part.makeBox(5, 5, 5, V(5, 5, 5)))),
    "shell": material(Part.Shell(box.Faces[:3])),
    "speck whole": job._cleared(box, box, speck),
    "speck elsewhere": job._cleared(box, box, [Part.makeBox(0.005, 0.005, 0.005, V(50, 0, 0))]),
    "corner whole": job._cleared(box, box, corner),
    "corner gone": job._cleared(box, box.cut(Part.makeBox(2, 2, 2, V(-1, -1, -1))), corner),
    "corner residue": job._cleared(box, taken, corner),
}
with open(out + "/skin.json", "w") as handle:
    json.dump(result, handle)
"""

STEP = Path(__file__).resolve().parents[1] / "examples/cone-pivot-post/cone-pivot-post.STEP"
# The user's pnos6 plan for that part, setups S1-S5 verbatim.
PNOS6 = Path(__file__).resolve().parent / "data/kernel/cone-pivot-post/pnos6-s1-s5.json"
BOSS = ["#247/ADVANCED_FACE[6]/HAF_CRANK_BOSS__P02", "#313/ADVANCED_FACE[8]/HAF_CRANK_BOSS__P02"]
TOP = ["#291/ADVANCED_FACE[7]/HAF_CRANK_BOSS_FACES__P02"]
UNDER = ["#329/ADVANCED_FACE[9]/HAF_CRANK_BOSS_FACES__P01"]
BAR = {
    "shape": "box",
    "origin_mm": [-25.4, -3.0, 52.2],
    "axis": [0.0, 1.0, 0.0],
    "length_mm": 140.0,
    "section_axis": [1.0, 0.0, 0.0],
    "section_mm": [50.8, 76.2],
}
CRANK = {
    "origin": [0.0, 72.7, 50.6591],
    "x": [0.0, -1.0, 0.0],
    "y": [1.0, 0.0, 0.0],
    "z": [0.0, 0.0, 1.0],
}
UNDERSIDE = {
    "origin": [0.0, 72.7, -21.3753],
    "x": [0.0, -1.0, 0.0],
    "y": [-1.0, 0.0, 0.0],
    "z": [0.0, 0.0, -1.0],
}
WALL = {"x": [-25.0, 25.0], "y": [-25.4, 25.4], "z": [-29.2838, 1.5409]}
LEAVE = 0.3


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _op(subject, do, faces, feature, bounds, to_z, **extra):
    return {
        "subject": subject,
        "do": do,
        "feature": feature,
        "faces": faces,
        "radius_mm": 6.35,
        "flute_len_mm": 31.75,
        "oal_mm": 100.0,
        "projection_mm": 48.0,
        "holder_radius_mm": 15.875,
        "holder_gauge_len_mm": 6.0,
        "stock_removal_bounds": bounds,
        "to_z": to_z,
        **extra,
    }


def _crank_job(engine, finish):
    top = {"x": [-17.315, 17.315], "y": [-17.315, 17.315], "z": [0.0, 1.5409]}
    ops = [
        _op("S2:10", "face", TOP, "crank_boss_faces", top, 0.0),
        _op("S2:20", "rough_profile", BOSS, "crank_boss", WALL, -29.2838, rough_allowance_mm=LEAVE),
    ]
    if finish:
        ops.append(_op("S2:30", "finish_profile", BOSS, "crank_boss", WALL, -29.2838))
    under = {"x": [-15.7275, 15.7275], "y": [-15.7275, 15.7275], "z": [0.0, 2.6247]}
    after = _op("S3:10", "face", UNDER, "crank_boss_faces", under, 0.0)
    setups = [
        {"id": "S2", "frame": CRANK, "hold": _vise(10.0), "ops": ops},
        {"id": "S3", "frame": UNDERSIDE, "hold": _vise(10.0), "ops": [after]},
    ]
    features = {"crank_boss": BOSS, "crank_boss_faces": TOP + UNDER}
    return engine.run(engine.job(STEP, features, setups, stock=BAR))["setups"]["S3"]


def test_rough_leave_on_a_part_whose_whole_offset_fails_is_kept_and_its_finish_takes_it(engine):
    roughed = _crank_job(engine, finish=False)
    finished = _crank_job(engine, finish=True)
    # Neither the rough nor the finish turns the stock they hand on into debt.
    assert "stock_reason" not in roughed and "stock_reason" not in finished
    # The rough leaves its 0.3 mm normal leave on the two claimed walls (each about
    # 1000 mm^2 inside the bar); the finish's lineage band then takes at least that.
    assert roughed["stock_volume_mm3"] - finished["stock_volume_mm3"] > LEAVE * 2000.0


def test_offsets_never_change_the_finished_part_a_later_leave_free_finish_cuts_against(engine):
    # The user's cone plan through S5: S2's 0.3 mm rough and its finish, then the journal
    # pad finishes at leave 0 (S4:20, S5:20) beside zero-height lands tangent to the body.
    # Offsetting the setup's own finished faces in place used to drift that solid's edge
    # tolerances with every guard built, until S4:20's clearance cut left invalid stock.
    plan = json.loads(PNOS6.read_text(encoding="utf-8"))
    digest = hashlib.sha256(STEP.read_bytes()).hexdigest()
    job = {"version": 1, "step_path": str(STEP), "step_sha256": digest, **plan}
    setups = engine.run(job)["setups"]
    # Every stock through S5's entry is known: S4's pad finish hands on one valid solid.
    assert all("stock_reason" not in setups[setup] for setup in ("S2", "S3", "S4", "S5"))


def test_skin_and_band_judgements_are_exact_and_never_waive_material(tmp_path, freecad_kernel):
    script = tmp_path / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(source)},
    )
    report = tmp_path / "skin.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    result = json.loads(report.read_text(encoding="utf-8"))
    # Lines and arcs both faces are invariant along get one exact kind for their length.
    assert result["line"] == "convex" and result["arc"] == "convex"
    assert result["inner line"] == "concave" and result["inner arc"] == "concave"
    assert result["fillet"] == "tangent"
    # The same convex box as B-spline surfaces is unproven, so its skin becomes debt.
    assert result["freeform"] == ["None"]
    # A Boolean that meets nothing is empty; faces without a solid are invalid, not empty.
    assert result["apart"] == "empty" and result["overlapping"] == "solid"
    assert result["shell"] == "invalid"
    # A band group is skipped only when none of it is in the stock or earlier cuts left a
    # mere residue (5e-7 mm^3) of more; a tiny group still whole (1.25e-7 mm^3) is cut.
    assert result["speck elsewhere"] and result["corner gone"] and result["corner residue"]
    assert not result["speck whole"] and not result["corner whole"]
