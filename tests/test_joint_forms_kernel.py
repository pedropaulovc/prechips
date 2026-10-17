"""Real FreeCAD boundaries for faces a joint forms: a root fillet whose band admits sharp (#301).

The STEP models the boss-to-body root as an R0.2 fillet; the joined branches leave it sharp.
"""

import math
import subprocess

import pytest
from test_joint_geometry import _bar, _joint_job
from test_kernel_geometry import Engine

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def root(shape, radius, z):
    edges = [
        edge
        for edge in shape.Edges
        if isinstance(edge.Curve, Part.Circle)
        and abs(edge.Curve.Radius - radius) < 1e-6
        and abs(edge.Curve.Center.z - z) < 1e-6
    ]
    assert len(edges) == 1
    return edges

def save(name, shape):
    shape = shape.cut(Part.makeCylinder(2, 20)).removeSplitter()
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

body = Part.makeCylinder(10, 10)
# The Ø9.8 boss meets the body top at z=10 in an R0.2 root fillet the press leaves sharp.
joined = body.fuse(Part.makeCylinder(4.9, 20)).removeSplitter()
save("filleted", joined.makeFillet(0.2, root(joined, 4.9, 10)))
# A collar below the body on the boss alone: its R0.2 root at z=-1 is one component's.
collared = body.multiFuse(
    [Part.makeCylinder(4.9, 25, V(0, 0, -5)), Part.makeCylinder(5.5, 4, V(0, 0, -5))]
).removeSplitter()
save("collared", collared.makeFillet(0.2, root(collared, 4.9, -1)))
"""

JOINED_MM3 = math.pi * (100 * 10 + 4.9**2 * 10)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("joint-forms")
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
    assert set(paths) == {"filleted", "collared"}, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _root(engine, step, z=10.0):
    return engine.refs(step, (-5.2, -5.2, z - 0.25), (5.2, 5.2, z + 0.25), kind="Toroid")


def _forms(engine, step, refs, band=(0.0, 0.2), interference=True):
    job = _joint_job(engine, step, interference=interference)
    job["features"]["root"] = refs
    job["setups"][2]["joint"]["forms"] = [
        {"feature": "root", "faces": refs, "radius_mm": list(band)}
    ]
    return job


@pytest.mark.parametrize("interference", [False, True])
def test_sharp_joined_root_is_lost_material_without_forms(engine, solids, interference):
    row = engine.run(_joint_job(engine, solids["filleted"], interference=interference))
    row = row["setups"]["join"]
    # The R0.2 ring the toroid bounds: what the backstop counts lost at the sharp corner.
    assert "assembled outputs leave 0.2666" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


@pytest.mark.parametrize("interference", [False, True])
def test_forms_admits_the_sharp_root_its_band_allows(engine, solids, interference):
    step = solids["filleted"]
    refs = _root(engine, step)
    assert refs
    facts = engine.run(_forms(engine, step, refs, interference=interference))
    row = facts["setups"]["join"]
    assert "assembly_error" not in row, row
    assert row["stock_out_volume_mm3"] == pytest.approx(JOINED_MM3, abs=1e-3)
    formed = row["forms"]["root"]
    indices = {face["ref"]: face["index"] for face in facts["faces"]}
    assert formed["status"] == "formed"
    assert formed["corner"] == "sharp"
    assert formed["indices"] == sorted(indices[ref] for ref in refs)
    assert formed["admitted_mm3"] == pytest.approx(0.2667, abs=1e-3)
    # The sharp corner sits r(√2 − 1) from the R0.2 toroid, inside the MAX.
    assert formed["reach_mm"] == pytest.approx(0.2 * (math.sqrt(2) - 1), abs=2e-3)


def test_nonzero_lower_band_refuses_the_sharp_corner(engine, solids):
    step = solids["filleted"]
    row = engine.run(_forms(engine, step, _root(engine, step), band=(0.1, 0.2)))
    error = row["setups"]["join"]["assembly_error"]
    assert "the joined corner at root is sharp, outside its radius band [0.1, 0.2]" in error


def test_material_missing_beyond_the_max_is_still_lost(engine, solids):
    step = solids["filleted"]
    row = engine.run(_forms(engine, step, _root(engine, step), band=(0.0, 0.05)))
    error = row["setups"]["join"]["assembly_error"]
    assert "beyond its R0.05 MAX" in error


def test_forms_naming_faces_a_branch_carries_is_an_error(engine, solids):
    step = solids["filleted"]
    top = engine.refs(step, (-10, -10, 10), (10, 10, 10), kind="Plane")
    assert top
    row = engine.run(_forms(engine, step, top))
    assert "the join does not form root" in row["setups"]["join"]["assembly_error"]


def test_a_single_component_root_is_not_formed_by_the_join(engine, solids):
    step = solids["collared"]
    refs = engine.refs(step, (-5.2, -5.2, -1.0), (5.2, 5.2, -0.75), kind="Toroid")
    assert refs
    job = _forms(engine, step, refs)
    job["stock"]["components"]["boss"] = _bar(12, 25, at=(0, 0, -5))
    # The finishing turn runs down to the collar and leaves its root sharp: lost, but the
    # boss branch alone bounds it, so the join cannot have formed it.
    job["setups"][1]["ops"][0]["joint_cut"].update(z_from=-1.0, z_to=20.0)
    row = engine.run(job)["setups"]["join"]
    assert "root is owned by a single component" in row["assembly_error"], row
