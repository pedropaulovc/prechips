"""Real FreeCAD boundaries for faces a joint forms: a root fillet whose band admits sharp (#301).

The STEP models the boss-to-body root as an R0.2 fillet; the joined branches leave it sharp.
"""

import math
import subprocess

import pytest
from test_joint_geometry import _bar, _joint_job
from test_kernel_geometry import IDENTITY, Engine, _op

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


def _forms(engine, step, refs, band=(0.0, 0.2), interference=True, mouth=None):
    """The join forming ``refs``; the socket's mouths are stated sharp unless ``mouth``."""
    job = _joint_job(engine, step, interference=interference)
    job["features"]["root"] = refs
    joint = job["setups"][2]["joint"]
    joint["forms"] = [{"feature": "root", "faces": refs, "radius_mm": list(band)}]
    joint["socket_break"] = mouth or {"kind": "sharp"}
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


@pytest.mark.parametrize("kind", ["chamfer", "radius"])
def test_a_broken_socket_mouth_leaves_a_groove_the_band_refuses(engine, solids, kind):
    # The title block allows "R0.25 or chamfer 0.25 MAX" on the strap hole's mouth: pressed,
    # that break is a groove round the hub, neither a fillet nor a sharp corner.
    step = solids["filleted"]
    mouth = {"kind": kind, "size_mm": 0.25}
    row = engine.run(_forms(engine, step, _root(engine, step), mouth=mouth))["setups"]["join"]
    error = row["assembly_error"]
    assert f"the socket's {kind} 0.25 mouth break leaves a groove" in error, row
    assert "stock_out_volume_mm3" not in row


@pytest.mark.parametrize(
    "mouth",
    [
        {"reason": "socket socket mouth edge_break is not declared"},
        {"reason": "socket socket mouth chamfer size is unknown"},
    ],
)
def test_an_unknown_mouth_break_leaves_the_formed_corner_unknown(engine, solids, mouth):
    step = solids["filleted"]
    row = engine.run(_forms(engine, step, _root(engine, step), mouth=mouth))["setups"]["join"]
    assert "assembly_error" not in row, row
    assert mouth["reason"] in row["stock_reason"]
    assert "stock_out_volume_mm3" not in row


def _lose_the_cap(engine, step, job):
    """Face the boss top down to z=15 before the join: finished material lost far from the
    root. The spigot owns only z=0..10, so its cap is finished material, not preparation."""
    job["joint_features"]["spigot"]["depth_mm"] = 10.0
    job["setups"][1]["ops"][0]["joint_cut"].update(depth_mm=10.0, z_from=0.0, z_to=20.0)
    job["features"]["top"] = engine.refs(step, (-4.9, -4.9, 20), (4.9, 4.9, 20), kind="Plane")
    job["setups"].insert(
        2,
        {
            "id": "lost-cap",
            "stock_in": "spigot-cut",
            "frame": IDENTITY,
            "hold": {"reason": "fixture not part of this stock-boundary probe"},
            "ops": [
                {
                    **_op("lost-cap:10", "top", 1, 25, 50),
                    "do": "face",
                    "to_z": 15.0,
                    "stock_removal_bounds": {"x": [-6, 6], "y": [-6, 6], "z": [15, 20]},
                }
            ],
        },
    )
    join = job["setups"][3]
    join["stock_in"][1] = "lost-cap"
    join["joint"].update(spigot_ref="lost-cap", refs=list(join["stock_in"]))
    return job


@pytest.mark.parametrize("undecided", ["mouth", "band"])
def test_an_undecided_corner_does_not_excuse_unrelated_lost_material(engine, solids, undecided):
    # Still a certain refusal, never debt the unknown mouth break or band could explain.
    step = solids["filleted"]
    refs = _root(engine, step)
    if undecided == "mouth":
        job = _forms(engine, step, refs, mouth={"reason": "mouth break unknown"})
    else:
        job = _forms(engine, step, refs)
        job["setups"][2]["joint"]["forms"] = [
            {"feature": "root", "faces": refs, "reason": "formed feature root radius unknown"}
        ]
    row = engine.run(_lose_the_cap(engine, step, job))["setups"]["join"]
    assert "protected finished material missing" in row["assembly_error"], row


def test_a_mouth_break_authored_in_air_cannot_be_placed(engine, solids):
    # The socket cylinder starts 1 mm below the body and ends 1 mm above it: a chamfer
    # cut at those authored ends would land in air and leave the mouth looking sharp.
    step = solids["filleted"]
    job = _forms(engine, step, _root(engine, step), mouth={"kind": "chamfer", "size_mm": 0.25})
    shifted = {"at_mm": [0, 0, -1.0], "depth_mm": 12.0}
    job["joint_features"]["socket"].update(shifted)
    job["setups"][0]["ops"][0]["joint_cut"].update(shifted)
    row = engine.run(job)["setups"]["join"]
    assert "assembly_error" not in row, row
    assert "is not a flat socket face square to its axis" in row["stock_reason"], row


def test_a_groove_at_the_root_is_refused_beside_a_mouth_in_air(engine, solids):
    # The socket starts 1 mm below the body (that mouth is in air, its break unplaceable)
    # but ends on the body top at the root, where the chamfer leaves a groove. Until the
    # other break is placed the corner's shape is debt, but the groove already reaches
    # past R0.2 from the fillet faces: a refusal no break can undo, so the join is refused.
    step = solids["filleted"]
    job = _forms(engine, step, _root(engine, step), mouth={"kind": "chamfer", "size_mm": 0.25})
    shifted = {"at_mm": [0, 0, -1.0], "depth_mm": 11.0}
    job["joint_features"]["socket"].update(shifted)
    job["setups"][0]["ops"][0]["joint_cut"].update(shifted)
    row = engine.run(job)["setups"]["join"]
    assert "beyond its R0.2 MAX" in row["assembly_error"], row
