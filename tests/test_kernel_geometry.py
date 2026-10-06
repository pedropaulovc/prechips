"""The FreeCAD geometry engine measured on authored solids and a real filleted part.

FreeCAD-backed tests run ``src/prechips/kernel/freecad_job.py`` under ``freecadcmd``
(``FREECAD_CMD`` override, else the installed path, else PATH) and skip when it is
absent.  The solids are authored here in FreeCAD and exported to STEP; every
assertion reads the engine's JSON output.

``tests/data/kernel/summing-lever.STEP`` is ``step/summing-lever.STEP`` from the
harmonic-analyzer v38 release archive (``harmonic-analyzer-v38.zip``, sha256
e1a96557f7c5029b97cd32ba1aeff1346f867a2e2f0489186cbe703d2fa7d7dc; SolidWorks 2026
AP214 export), copied byte for byte (sha256
1394593920ddab668bb2bdd343134448667dfcaddb6c32047711d1312691c101).

The labelled bundles are harmonic-analyzer ``cad/out/features`` exports (SolidWorks
STEP with every ADVANCED_FACE named by its feature label, plus the generated
``features.toml`` binding feature faces to those refs), copied byte for byte from
``C:/src/dt-logs/features-bundles``: ``tests/data/kernel/pivot-shaft`` (STEP sha256
c78673d5ab2ac12cf04b43017f0c4f60952488bdbdbd8989ce11e769e0aa003d) and
``tests/data/kernel/cone-pivot-post`` (STEP sha256
a3321157fc48cd8193ba81345611538d9c8c35fe7c6ba35e12fe8dc7a2416036); the rocker-arm
bundle is read where the repository keeps it, ``examples/rocker-arm``.
"""

import base64
import hashlib
import json
import math
import struct
import subprocess
import tomllib
from pathlib import Path

import pytest

from prechips.kernel.step_faces import FaceRefError, StepFile, face_ref, parse_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data" / "kernel"
ENGINE = ROOT / "src" / "prechips" / "kernel" / "freecad_job.py"
SUMMING_LEVER = DATA / "summing-lever.STEP"
# Labelled exports and one label each that the exporter split into periodic patches.
LABELLED = {
    "rocker-arm": (ROOT / "examples" / "rocker-arm", "HAF_PIVOT_BORE__P01"),
    "pivot-shaft": (DATA / "pivot-shaft", "HAF_PIVOT_BEARING__P01"),
    "cone-pivot-post": (DATA / "cone-pivot-post", "HAF_CRANK_BOSS__P01"),
}
STEP_KINDS = {
    "PLANE": "Plane",
    "CYLINDRICAL_SURFACE": "Cylinder",
    "CONICAL_SURFACE": "Cone",
    "SPHERICAL_SURFACE": "Sphere",
    "TOROIDAL_SURFACE": "Toroid",
}
IDENTITY = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}

_STEP = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
ENDSEC;
DATA;
#1 = ADVANCED_FACE('it''s',(),#9,.T.);
#2 = PLANE('',#9);
#3 = ADVANCED_FACE('NONE',(),#9,.F.);
ENDSEC;
END-ISO-10303-21;
"""


def test_face_refs_are_entity_ordinal_and_raw_label():
    step = StepFile(_STEP)
    assert [face.ref for face in step.faces] == [
        "#1/ADVANCED_FACE[1]/it's",
        "#3/ADVANCED_FACE[2]/NONE",
    ]
    assert step.resolve("#3/ADVANCED_FACE[2]/NONE").entity == 3
    assert parse_ref(face_ref(7, 2, "")) == (7, 2, "")


@pytest.mark.parametrize(
    "ref, message",
    [
        ("#9/ADVANCED_FACE[1]/x", "no instance #9"),
        ("#2/ADVANCED_FACE[1]/", "is PLANE, not ADVANCED_FACE"),
        ("#3/ADVANCED_FACE[1]/NONE", "ordinal 2, not 1"),
        ("#3/ADVANCED_FACE[2]/none", "carries label 'NONE'"),
        ("#3/ADVANCED_FACE[0]/NONE", "#3/ADVANCED_FACE[0]/NONE"),
        ("face 3", "face 3"),
    ],
)
def test_wrong_face_ref_is_rejected_naming_the_ref(ref, message):
    with pytest.raises(FaceRefError) as caught:
        StepFile(_STEP).resolve(ref)
    assert ref in str(caught.value) and message in str(caught.value)


# --------------------------------------------------------------------------- FreeCAD


_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

def vertical_edges(shape):
    return [e for e in shape.Edges if abs(e.tangentAt(e.FirstParameter).z) > 0.99]

# 60x40x10 plate with an R4 boss 6 tall at (37, 20), near an interior floor sample.
save("boss", Part.makeBox(60, 40, 10).fuse(Part.makeCylinder(4, 6, V(37, 20, 10))).removeSplitter())
# 60x40x20 block, +X half stepped down to z=10: floor x 30..60 and its wall at x=30.
save("step", Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10))))
# U channel: 60 long (x), rails y 0..5 and 35..40 up to z=20, floor z=10.
save("channel", Part.makeBox(60, 40, 20).cut(Part.makeBox(62, 30, 11, V(-1, 5, 10))))
# 70x50x60 block, 40x24 pocket with R6 vertical corners, 45 deep.
cutter = Part.makeBox(40, 24, 46, V(15, 13, 15))
save("pocket", Part.makeBox(70, 50, 60).cut(cutter.makeFillet(6, vertical_edges(cutter))))
# 60x40x20 block, 30x12 pocket 6 deep with sharp corners.
slot = Part.makeBox(60, 40, 20).cut(Part.makeBox(30, 12, 7, V(15, 14, 14)))
save("slot", slot)
# The same slot with a D2 pin 6 tall standing on its floor, axis 2 mm from the (15, 14) corner.
save("slot-pin", slot.fuse(Part.makeCylinder(1, 6, V(15 + 2 ** 0.5, 14 + 2 ** 0.5, 14))))
# Same pocket with R2 floor-to-wall fillets only (horizontal-axis concave cylinders).
floor = Part.makeBox(30, 12, 7, V(15, 14, 14))
bottom = [
    e for e in floor.Edges
    if abs(e.tangentAt(e.FirstParameter).z) < 0.01 and e.BoundBox.ZMax < 14.5
]
save("floor-fillet", Part.makeBox(60, 40, 20).cut(floor.makeFillet(2, bottom)))
# R10 puck 20 tall: curved jaw contact on both clamp axes.
save("puck", Part.makeCylinder(10, 20))
# 20x10x5 box whose top is two triangles with equal area and equal bounding box.
p = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0)]
q = [v + V(0, 0, 5) for v in p]
loops = [p[::-1], [p[0], p[1], q[1], q[0]], [p[1], p[2], q[2], q[1]], [p[2], p[3], q[3], q[2]],
         [p[3], p[0], q[0], q[3]], [q[0], q[1], q[2]], [q[0], q[2], q[3]]]
shell = Part.Shell([Part.Face(Part.makePolygon(loop + loop[:1])) for loop in loops])
shell.sewShape()
solid = Part.Solid(Part.Shell(shell.Faces))
if solid.Volume < 0:
    solid.reverse()
save("split-top", solid)
# Same step, but its wall leans 5 mm into the floor opening as it rises.
p = [V(30, 0, 10), V(35, 0, 20), V(61, 0, 20), V(61, 0, 10), V(30, 0, 10)]
save(
    "undercut-step",
    Part.makeBox(60, 40, 20).cut(Part.Face(Part.makePolygon(p)).extrude(V(0, 40, 0))),
)
# A planned 6.5 mm through hole, before drilling the supplied rectangular blank.
save("hole", Part.makeBox(60, 40, 20).cut(Part.makeCylinder(3.25, 22, V(30, 20, -1))))
# A blind cylindrical opening with an unclaimed neighbouring boss inside it.
opening = Part.makeBox(60, 40, 20).cut(Part.makeCylinder(4, 19, V(30, 20, 2)))
save("hole-boss", opening.fuse(Part.makeCylinder(0.8, 10, V(31.8, 20, 2))).removeSplitter())
"""
_AUTHORED = 12


def _run(payload, directory, executable):
    source, target = directory / "in.json", directory / "out.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    target.unlink(missing_ok=True)
    process = subprocess.run(
        [executable, str(ENGINE), "--", str(source), str(target)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return target.read_bytes()


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("solids")
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


class Engine:
    def __init__(self, directory, executable):
        self.directory = directory
        self.executable = executable
        self.inventories = {}

    def raw(self, payload):
        return _run(payload, self.directory, self.executable)

    def run(self, payload):
        return json.loads(self.raw(payload))

    def job(self, step, features=None, setups=(), as_is=(), stock=None):
        """A job whose supply is declared explicitly: by default the authored solid itself
        (``shape="part"``: these probes measure an already finished test solid), with each
        setup receiving the previous setup's stock unless it names its own ``stock_in``."""
        data = Path(step).read_bytes()
        chained, previous = [], "stock"
        for setup in setups:
            chained.append({"stock_in": previous, **setup})
            previous = setup["id"]
        return {
            "version": 1,
            "step_path": str(step),
            "step_sha256": hashlib.sha256(data).hexdigest(),
            "features": features or {},
            "as_is_faces": list(as_is),
            "stock": {"shape": "part"} if stock is None else stock,
            "setups": chained,
        }

    def faces(self, step):
        if step not in self.inventories:
            result = self.run(self.job(step))
            assert result["status"] == "ok", result
            self.inventories[step] = result
        return self.inventories[step]["faces"]

    def refs(self, step, lo, hi, kind=None):
        """Refs of faces whose bounding box lies inside [lo, hi] (optionally of one kind)."""
        return [
            face["ref"]
            for face in self.faces(step)
            if (kind is None or face["kind"] == kind)
            and all(
                lo[k] - 1e-6 <= face["bbox_mm"][k] and face["bbox_mm"][k + 3] <= hi[k] + 1e-6
                for k in range(3)
            )
        ]


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _op(subject, feature, radius, flute, projection, holder_radius=10.0, gauge=30.0, oal=100.0):
    return {
        "subject": subject,
        "feature": feature,
        "do": "mill",
        "finishing": True,
        "radius_mm": radius,
        "flute_len_mm": flute,
        "oal_mm": oal,
        "projection_mm": projection,
        "holder_radius_mm": holder_radius,
        "holder_gauge_len_mm": gauge,
    }


def _vise(
    above,
    along="x",
    fixed="rear",
    height=45.0,
    width=150.0,
    depth=20.0,
    centre=None,
    parallels=None,
):
    hold = {
        "kind": "vise",
        "method": "unknown",
        "fixed_jaw": fixed,
        "jaws_along": along,
        "grip_mm": 5.0,
        "jaw_above_parallels_mm": above,
        "jaw_height_mm": height,
        "jaw_width_mm": width,
        "jaw_depth_mm": depth,
        "opening_mm": 150.0,
        "parallels_height_mm": 25.0,
    }
    if centre is not None:
        hold["jaw_center_along_mm"] = centre
    if parallels is not None:
        length, thickness, centres = parallels
        hold.update(
            parallels_length_mm=length, parallels_width_mm=thickness, parallels_centres_mm=centres
        )
    return hold


def _setup(ops, hold, frame=IDENTITY, setup_id="S1"):
    return {"id": setup_id, "frame": frame, "hold": hold, "ops": ops}


def test_plate_samples_near_a_boss_and_its_own_wall_poses_both_clear_it(engine, solids):
    # Each floor sample keeps a nearest covering axis; lateral wall poses stay unchanged.
    step = solids["boss"]
    top = engine.refs(step, (0, 0, 10), (60, 40, 10))
    boss = engine.refs(step, (33, 16, 10), (41, 24, 16))
    side = engine.refs(step, (33, 16, 10), (41, 24, 16), kind="Cylinder")
    assert len(top) == 1 and len(boss) == 2 and len(side) == 1
    ops = [_op("S1:10", "top", 3.0, 10.0, 20.0), _op("S1:20", "boss", 3.0, 10.0, 20.0)]
    result = engine.run(engine.job(step, {"top": top, "boss": boss}, [_setup(ops, _vise(5.0))]))
    for op in (result["ops"]["S1:10"], result["ops"]["S1:20"]):
        assert op["tool_hits"] == 0 and op["obstacles"]["tool"] == [], op


@pytest.mark.parametrize("name, clears", [("step", True), ("undercut-step", False)])
def test_floor_edge_tangent_pose_clears_a_wall_but_not_an_undercut(engine, solids, name, clears):
    step = solids[name]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    wall = engine.refs(step, (30, 0, 10), (35 if not clears else 30, 40, 20))
    assert len(floor) == 1 and len(wall) == 1
    op = _op("S1:10", "floor", 1.0, 15.0, 20.0)
    detail = engine.run(
        engine.job(step, {"floor": floor}, [_setup([op], _vise(5.0, centre=30.0))])
    )["ops"]["S1:10"]
    assert (detail["tool_hits"] == 0) is clears
    if not clears:
        assert wall[0] in detail["hit_refs"]["tool"]
    assert floor[0] not in detail["hit_refs"]["tool"]


def test_corner_samples_keep_claimed_walls_and_unclaimed_pin_as_obstacles(engine, solids):
    step = solids["slot-pin"]
    pin_top = engine.refs(step, (15, 14, 20), (45, 26, 20))
    slot = [
        ref
        for ref in engine.refs(step, (15, 14, 14), (45, 26, 20), kind="Plane")
        if ref not in pin_top
    ]
    pin = engine.refs(step, (15, 14, 14), (45, 26, 20), kind="Cylinder") + pin_top
    assert len(slot) == 5 and len(pin) == 2  # floor and four walls; the pin's side and top
    ops = [_op("S1:10", "slot", 3.0, 10.0, 20.0)]
    op = engine.run(engine.job(step, {"slot": slot}, [_setup(ops, _vise(5.0))]))["ops"]["S1:10"]
    # A pin in the corner opening and adjacent claimed walls both remain obstacles;
    # only the sampled face's tolerance shell is removed.
    assert op["tool_hits"] > 0 and set(pin).issubset(op["hit_refs"]["tool"])
    assert set(slot).intersection(op["hit_refs"]["tool"])
    assert op["corner_radii_mm"] == [0.0]


def test_holder_hits_the_dimensioned_jaws_only_when_they_stand_high_enough(engine, solids):
    step = solids["channel"]
    channel = engine.refs(step, (0, 5, 10), (60, 35, 20))
    assert len(channel) == 3  # floor and both rail inner walls
    # The holder starts 10.5 above the 10 mm floor, clear of the 20 mm rails.
    ops = [_op("S1:10", "channel", 3.0, 4.0, 10.5)]
    high, low = (
        engine.run(engine.job(step, {"channel": channel}, [_setup(ops, _vise(above, centre=30.0))]))
        for above in (30.0, 12.0)
    )
    for result in (high, low):
        assert result["setups"]["S1"]["render_scene"]["jaws"] == "exact"
    standing = high["ops"]["S1:10"]
    assert standing["obstacles"]["holder"] == ["fixed_jaw", "moving_jaw"]
    assert standing["holder_hits"] == standing["min_hits"]["holder"] > 0
    assert low["ops"]["S1:10"]["holder_hits"] == 0


def test_vise_contact_width_and_thin_wall_map_follow_the_jaw_zone(engine, solids):
    step = solids["channel"]
    outer = engine.refs(step, (0, 0, 0), (60, 0, 20))
    channel = engine.refs(step, (0, 5, 10), (60, 35, 20))
    ops = [_op("S1:10", "channel", 3.0, 4.0, 5.0), _op("S1:20", "outer", 3.0, 4.0, 5.0)]
    features = {"channel": channel, "outer": outer}
    rails, base = (
        engine.run(engine.job(step, features, [_setup(ops, _vise(above))]))["setups"]["S1"]
        for above in (12.0, 8.0)
    )
    assert rails["width_mm"] == base["width_mm"] == 40.0
    assert rails["parallel_pair"] is base["parallel_pair"] is True
    assert rails["contact_grip_mm"] == [12.0, 12.0] and base["contact_grip_mm"] == [8.0, 8.0]
    assert rails["claimed_in_jaws"] == base["claimed_in_jaws"] == outer
    assert rails["min_wall_mm"] == 5.0 and base["min_wall_mm"] == 40.0
    lines = rails["wall_map"]["lines"]
    assert {len(line["intervals_mm"]) for line in lines if line["z_mm"] > 10} == {2}
    assert [[0.0, 5.0], [35.0, 40.0]] in [line["intervals_mm"] for line in lines]


@pytest.mark.parametrize("along", ["x", "y"])
def test_curved_jaw_contact_is_a_measured_line_on_either_clamp_axis(engine, solids, along):
    hold = _vise(8.0, along=along, fixed="rear" if along == "x" else "right")
    setup = engine.run(engine.job(solids["puck"], setups=[_setup([], hold)]))["setups"]["S1"]
    assert setup["width_mm"] == 20.0
    assert setup["parallel_pair"] is False and setup["contact_grip_mm"] == [8.0, 8.0]


def test_jaw_centre_places_a_part_longer_than_the_jaws(engine, solids):
    step = solids["channel"]
    channel = engine.refs(step, (0, 5, 10), (60, 35, 20))
    ops = [_op("S1:10", "channel", 3.0, 4.0, 5.0)]
    undeclared, declared = (
        engine.run(
            engine.job(
                step, {"channel": channel}, [_setup(ops, _vise(12.0, width=50.0, centre=centre))]
            )
        )
        for centre in (None, 30.0)
    )
    setup, op = undeclared["setups"]["S1"], undeclared["ops"]["S1:10"]
    assert "jaw position along x is undeclared" in setup["fixture_reason"]
    assert setup["fixture_rendered"] is False and setup["render_png_base64"]
    assert setup["render_scene"]["jaws"] == "absent"
    assert all(
        setup[key] == "unknown"
        for key in ("parallel_pair", "width_mm", "contact_grip_mm", "min_wall_mm")
    )
    assert op["tool_hits"] == "unknown"
    assert "fixture solids unresolved" in op["reasons"]["tool_hits"]
    placed = declared["setups"]["S1"]
    assert placed["width_mm"] == 40.0 and placed["contact_grip_mm"] == [12.0, 12.0]
    assert placed["render_scene"]["jaws"] == "exact"


def test_render_scene_is_complete_only_for_declared_jaw_centre_and_parallels(engine, solids):
    step = solids["pocket"]
    parallels = (150.0, 6.0, [[35.0, 5.0], [35.0, 45.0]])
    holds = {
        "exact": _vise(10.0, centre=35.0, parallels=parallels),
        "undeclared": _vise(10.0),
        "clashing": _vise(10.0, centre=35.0, parallels=(150.0, 6.0, [[35.0, -5.0], [35.0, 45.0]])),
    }
    scenes = {
        name: engine.run(engine.job(step, setups=[_setup([], hold)]))["setups"]["S1"]
        for name, hold in holds.items()
    }
    exact = scenes["exact"]
    scene = exact["render_scene"]
    assert scene["jaws"] == scene["parallels"] == "exact"
    assert {c["name"] for c in scene["components"] if c["exact"]} == {
        "fixed_jaw",
        "moving_jaw",
        "parallel 1",
        "parallel 2",
    }
    assert exact["fixture_rendered"] is True
    undeclared = scenes["undeclared"]
    assert undeclared["render_scene"]["jaws"] == "lateral_undeclared"
    assert undeclared["render_scene"]["parallels"] == "not_modelled"
    assert {c["name"]: c["exact"] for c in undeclared["render_scene"]["components"]} == {
        "fixed_jaw": False,
        "moving_jaw": False,
    }
    assert undeclared["fixture_rendered"] is False
    clashing = scenes["clashing"]
    assert clashing["fixture_rendered"] is False
    assert exact["render_png_base64"] != undeclared["render_png_base64"]


def test_dense_contour_diagram_does_not_erase_geometry_facts(engine, solids):
    step = solids["pocket"]
    hold = _vise(
        10.0,
        centre=35.0,
        parallels=(150.0, 6.0, [[35.0, 7.0], [35.0, 43.0]]),
    )
    setup = _setup([], hold)
    baseline = engine.run(engine.job(step, setups=[setup]))["setups"]["S1"]
    corners = [[15.0, 13.0], [55.0, 13.0], [55.0, 37.0], [15.0, 37.0]]
    paths, waypoints = [], []
    for op in (10, 20, 40, 45, 50, 55):
        paths.append({"op": str(op), "xy": corners + [corners[0]]})
        for point in corners:
            waypoints.append({"label": f"P{len(waypoints) + 1}", "op": str(op), "xy": point})
    setup["render"] = {"paths": paths, "waypoints": waypoints}
    result = engine.run(engine.job(step, setups=[setup]))
    assert result["status"] == "ok", result
    dense = result["setups"]["S1"]
    assert dense["fixture_rendered"] is baseline["fixture_rendered"] is True
    assert dense["stock_bbox_mm"] == baseline["stock_bbox_mm"]
    assert dense["stock_volume_mm3"] == baseline["stock_volume_mm3"]
    assert dense["contact_grip_mm"] == baseline["contact_grip_mm"]
    assert dense["render_png_base64"] != baseline["render_png_base64"]


def test_pocket_reach_needs_long_projection_and_reports_corner_radius(engine, solids):
    step = solids["pocket"]
    pocket = engine.refs(step, (15, 13, 15), (55, 37, 60))
    assert len(pocket) == 9  # floor, four walls, four R6 corners
    ops = [
        _op("S1:10", "pocket", 4.0, 20.0, 30.0, holder_radius=15.0, gauge=40.0, oal=50.0),
        _op("S1:20", "pocket", 4.0, 50.0, 60.0, holder_radius=15.0, gauge=40.0, oal=100.0),
    ]
    result = engine.run(engine.job(step, {"pocket": pocket}, [_setup(ops, _vise(10.0))]))
    short, long = result["ops"]["S1:10"], result["ops"]["S1:20"]
    for op in (short, long):
        assert op["reach_depth_mm"] == 45.0
        assert op["corner_radii_mm"] == [6.0]
    assert short["holder_wall_hits"] > 0 and short["holder_hits"] > 0
    assert long["holder_wall_hits"] == 0 and long["holder_hits"] == 0


def test_corner_radii_sharp_corners_and_unanalysed_floor_fillets(engine, solids):
    sharp = engine.refs(solids["slot"], (15, 14, 14), (45, 26, 20))
    fillet = engine.refs(solids["floor-fillet"], (15, 14, 14), (45, 26, 20))
    ops = [_op("S1:10", "slot", 3.0, 10.0, 20.0)]
    slot = engine.run(engine.job(solids["slot"], {"slot": sharp}, [_setup(ops, _vise(5.0))]))[
        "ops"
    ]["S1:10"]
    assert slot["corner_radii_mm"] == [0.0]
    rounded = engine.run(
        engine.job(solids["floor-fillet"], {"slot": fillet}, [_setup(ops, _vise(5.0))])
    )
    detail = rounded["ops"]["S1:10"]
    assert detail["corner_radii_mm"] == "unknown"
    assert (
        "concave cylinder whose axis is not the tool axis" in detail["reasons"]["corner_radii_mm"]
    )


def test_mapping_survives_reordered_import_faces(engine, solids, tmp_path):
    original = solids["pocket"]
    text = original.read_text(encoding="latin-1")
    shell = next(r for r in StepFile(text).records.values() if r.types == ("CLOSED_SHELL",))
    assert text.count(shell.body) == 1
    reordered = "CLOSED_SHELL('',(" + ",".join(f"#{ref}" for ref in reversed(shell.refs)) + "))"
    permuted = tmp_path / "permuted.step"
    permuted.write_text(text.replace(shell.body, reordered), encoding="latin-1", newline="")
    before, after = engine.faces(original), engine.faces(permuted)
    by_ref = {face["ref"]: face for face in after}
    assert len(after) == len(before) and all(face["ref"] for face in before)
    assert [face["ref"] for face in after] != [face["ref"] for face in before]
    for face in before:
        assert by_ref[face["ref"]]["bbox_mm"] == face["bbox_mm"]
        assert by_ref[face["ref"]]["area_mm2"] == face["area_mm2"]


def test_ambiguous_and_invalid_refs_are_named_never_guessed(engine, solids):
    step = solids["split-top"]
    text_faces = StepFile(step.read_text(encoding="latin-1")).faces
    result = engine.run(engine.job(step))
    errors = result["mapping_errors"]
    ambiguous = sorted(ref for ref, reason in errors.items() if "ambiguous" in reason)
    assert len(ambiguous) == 2 and len(result["mapping"]) == len(text_faces) - 2
    assert sum(face["ref"] is None for face in result["faces"]) == 2
    wrong = text_faces[0].ref + "x"
    features = {"tri": [ambiguous[0]], "bad": [wrong]}
    ops = [_op("S1:10", "tri", 2.0, 5.0, 10.0), _op("S1:20", "bad", 2.0, 5.0, 10.0)]
    result = engine.run(engine.job(step, features, [_setup(ops, _vise(2.0))]))
    assert result["features"] == {"tri": "unknown", "bad": "unknown"}
    assert result["ops"]["S1:10"]["mapping_errors"] == [ambiguous[0]]
    assert result["ops"]["S1:20"]["mapping_errors"] == [wrong]
    assert (
        wrong in result["mapping_errors"][wrong]
        and "carries label" in result["mapping_errors"][wrong]
    )
    assert result["ops"]["S1:20"]["tool_hits"] == "unknown"


@pytest.mark.parametrize("bundle", sorted(LABELLED))
def test_every_labelled_export_ref_maps_to_its_own_face_in_any_import_order(
    engine, tmp_path, bundle
):
    directory, split_label = LABELLED[bundle]
    manifest = tomllib.loads((directory / "features.toml").read_text(encoding="utf-8"))
    step = directory / manifest["step"]
    assert hashlib.sha256(step.read_bytes()).hexdigest() == manifest["step_sha256"]
    text = step.read_text(encoding="latin-1")
    parsed = StepFile(text)
    features = {
        name: spec["faces"]
        for name, spec in manifest["features"].items()
        if isinstance(spec.get("faces"), list)
    }
    claimed = [ref for refs in features.values() for ref in refs]
    assert claimed and len(set(claimed)) == len(claimed)
    # A label the exporter split over several ADVANCED_FACEs is claimed whole, by one feature.
    patches = {}
    for face in parsed.faces:
        patches.setdefault(face.label, []).append(face.ref)
    for refs in features.values():
        for label in {parse_ref(ref)[2] for ref in refs}:
            assert set(patches[label]) <= set(refs), label
    assert len(patches[split_label]) >= 2

    def mapped(path):
        result = engine.run(engine.job(path, features))
        assert result["status"] == "ok" and result["mapping_errors"] == {}, result
        faces = result["faces"]
        assert len(faces) == len(parsed.faces) and all(face["ref"] for face in faces)
        for name, refs in features.items():
            assert result["features"][name] == sorted(result["mapping"][ref] for ref in refs)
        return {ref: faces[result["mapping"][ref]] for ref in claimed}, [
            face["ref"] for face in faces
        ]

    original, order = mapped(step)
    assert len({face["index"] for face in original.values()}) == len(claimed)
    for ref, face in original.items():
        surface = parsed.records[parsed.records[parse_ref(ref)[0]].refs[-1]]
        assert face["ref"] == ref and face["kind"] == STEP_KINDS[surface.types[0]], ref
    # Reverse the shell's face list: import indices move, every ref keeps its own face.
    shell = next(record for record in parsed.records.values() if record.types == ("CLOSED_SHELL",))
    assert text.count(shell.body) == 1
    head = shell.body[: shell.body.index("(", shell.body.index("(") + 1) + 1]
    reordered = head + ",".join(f"#{ref}" for ref in reversed(shell.refs)) + "))"
    permuted = tmp_path / step.name
    permuted.write_text(text.replace(shell.body, reordered), encoding="latin-1", newline="")
    moved, permuted_order = mapped(permuted)
    assert permuted_order != order and any(
        moved[ref]["index"] != original[ref]["index"] for ref in claimed
    )
    for ref in claimed:
        assert [moved[ref][key] for key in ("kind", "bbox_mm", "area_mm2")] == [
            original[ref][key] for key in ("kind", "bbox_mm", "area_mm2")
        ], ref


def test_coverage_inventory_lists_every_imported_face_and_as_is_refs(engine, solids):
    step = solids["step"]
    faces = engine.faces(step)
    refs = [face["ref"] for face in faces]
    result = engine.run(engine.job(step, {"floor": refs[:2]}, as_is=refs[2:]))
    assert [face["index"] for face in result["faces"]] == list(range(len(faces)))
    assert all(result["mapping"][ref] == index for index, ref in enumerate(refs))
    assert result["features"]["floor"] == [0, 1]
    assert result["mapping_errors"] == {}


def test_unknown_inputs_stay_unknown_with_reasons(engine, solids):
    step = solids["pocket"]
    pocket = engine.refs(step, (15, 13, 15), (55, 37, 60))
    partial = {
        key: value
        for key, value in _op("S1:10", "pocket", 4.0, 20.0, 30.0).items()
        if key != "projection_mm"
    }
    setups = [
        _setup([partial], _vise(10.0)),
        _setup(
            [_op("S2:10", "pocket", 4.0, 20.0, 30.0)],
            {"kind": "vise", "reason": "jaw_depth_mm unmeasured"},
            setup_id="S2",
        ),
        _setup(
            [_op("S3:10", "pocket", 4.0, 20.0, 30.0)], _vise(10.0), frame="unknown", setup_id="S3"
        ),
    ]
    result = engine.run(engine.job(step, {"pocket": pocket}, setups))
    op = result["ops"]["S1:10"]
    assert op["reach_depth_mm"] == 45.0
    assert op["holder_hits"] == op["holder_wall_hits"] == "unknown"
    assert "projection_mm" in op["reasons"]["holder_hits"]
    unresolved = result["setups"]["S2"]
    assert (
        unresolved["fixture_reason"] == "jaw_depth_mm unmeasured"
        and unresolved["fixture_rendered"] is False
    )
    assert result["ops"]["S2:10"]["tool_hits"] == "unknown" and result["ops"]["S2:10"][
        "corner_radii_mm"
    ] == [6.0]
    assert "render_png_base64" not in result["setups"]["S3"]
    assert result["ops"]["S3:10"]["corner_radii_mm"] == "unknown"
    stale = engine.job(step)
    stale["step_sha256"] = "0" * 64
    assert engine.run(stale)["status"] == "error"
    stale["step_sha256"] = "unknown"
    assert engine.run(stale)["status"] == "unknown"


def test_setup_frame_turns_the_part_over_without_moving_model_faces(engine, solids):
    step = solids["step"]
    bottom = engine.refs(step, (0, 0, 0), (60, 40, 0))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    assert len(bottom) == 1 and len(floor) == 1
    flipped = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}
    ops = [_op("S1:10", "bottom", 4.0, 15.0, 20.0), _op("S1:20", "floor", 4.0, 15.0, 20.0)]
    result = engine.run(
        engine.job(
            step, {"bottom": bottom, "floor": floor}, [_setup(ops, {"reason": "none"}, flipped)]
        )
    )
    up, down = result["ops"]["S1:10"], result["ops"]["S1:20"]
    assert up["claim_errors"] == [] and up["min_hits"]["tool"] == 0
    # The model floor now faces the table: a claim error, not a sampled collision.
    assert down["claim_errors"] == floor and down["claimed_indices"] == []
    assert down["tool_hits"] == "unknown" and "points away" in down["reasons"]["tool_hits"]
    assert result["faces"] == engine.faces(step)


def test_batch_matches_single_jobs_and_output_is_byte_identical(engine, solids):
    step = solids["channel"]
    channel = engine.refs(step, (0, 5, 10), (60, 35, 20))
    job = engine.job(
        step, {"channel": channel}, [_setup([_op("S1:10", "channel", 3.0, 4.0, 5.0)], _vise(12.0))]
    )
    first, second = engine.raw(job), engine.raw(job)
    assert first == second
    other = engine.job(solids["slot"])
    batch = json.loads(engine.raw({"jobs": [job, other]}))
    assert batch["results"] == [json.loads(first), engine.run(other)]
    png = base64.b64decode(json.loads(first)["setups"]["S1"]["render_png_base64"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert width >= 1600 and height >= 1000  # Print-readable at half-page width.


def test_booleans_on_the_real_filleted_summing_lever(engine):
    faces = engine.faces(SUMMING_LEVER)
    text_refs = [face.ref for face in StepFile(SUMMING_LEVER.read_text(encoding="latin-1")).faces]
    assert len(faces) == len(text_refs) == 93 and sorted(face["ref"] for face in faces) == sorted(
        text_refs
    )
    assert [face["ref"] for face in faces] != text_refs

    def where(kind, test):
        return [face for face in faces if face["kind"] == kind and test(face["bbox_mm"])]

    def near(a, b):
        return abs(a - b) < 1e-6

    # Model +Y up: the web's upper face and two of its through holes.
    web = where("Plane", lambda b: near(b[1], 2.54) and near(b[4], 2.54) and b[0] > 0)
    holes = where(
        "Cylinder", lambda b: near(b[1], -2.54) and near(b[4], 2.54) and b[0] > 30 and b[2] > 59
    )
    # End plates: full-height planes across model Z; the outermost pair meets the jaws.
    seat, top = min(face["bbox_mm"][1] for face in faces), max(face["bbox_mm"][4] for face in faces)
    across = where("Plane", lambda b: b[2] == b[5] and near(b[1], seat) and near(b[4], top))
    outer = max(abs(face["bbox_mm"][2]) for face in across)
    ends = [face for face in across if near(abs(face["bbox_mm"][2]), outer)]
    inner = [face for face in across if not near(abs(face["bbox_mm"][2]), outer)]
    assert len(web) == 1 and len(holes) == 4 and len(ends) == 2 and len(inner) == 2
    hole_radius = (
        holes[0]["bbox_mm"][3] - holes[0]["bbox_mm"][0]
    )  # half-cylinder patch: width = radius
    claimed = [face["ref"] for face in web + holes]
    frame = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, -1], "z": [0, 1, 0]}
    ops = [_op("S1:10", "web", 1.0, 6.0, 12.0, holder_radius=6.0)]
    result = engine.run(
        engine.job(SUMMING_LEVER, {"web": claimed}, [_setup(ops, _vise(8.0), frame)])
    )
    assert result["status"] == "ok"
    op, setup = result["ops"]["S1:10"], result["setups"]["S1"]
    assert "tool_hits" not in op["reasons"]  # offsets and booleans on the filleted solid succeeded
    assert op["corner_radii_mm"] == [pytest.approx(hole_radius, abs=1e-5)]
    assert setup["width_mm"] == pytest.approx(2 * outer)
    assert setup["parallel_pair"] is True and setup["contact_grip_mm"] == [8.0, 8.0]
    assert sorted(setup["contact_faces"]["fixed"] + setup["contact_faces"]["moving"]) == sorted(
        f["ref"] for f in ends
    )
    assert setup["min_wall_mm"] == pytest.approx(
        outer - abs(inner[0]["bbox_mm"][2])
    )  # end plate thickness


def test_sharp_floor_corner_has_no_covering_two_wall_tangent_axis(engine, solids):
    step = solids["slot"]
    floor = engine.refs(step, (15, 14, 14), (45, 26, 14))
    op = _op("S1:10", "floor", 0.5, 10.0, 20.0)
    detail = engine.run(
        engine.job(step, {"floor": floor}, [_setup([op], _vise(5.0, centre=30.0))])
    )["ops"]["S1:10"]
    assert isinstance(detail["tool_hits"], int) and detail["tool_hits"] > 0, detail
    assert detail["obstacles"]["tool"] == ["part"], detail


def test_rough_floor_pose_uses_its_cut_level_and_keeps_holder_obstacles(engine, solids):
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    op = {**_op("S1:10", "floor", 1.0, 15.0, 20.0), "do": "rough_pocket", "to_z": 14.0}
    setup = _setup([op], _vise(5.0, centre=30.0))
    detail = engine.run(engine.job(step, {"floor": floor}, [setup], stock=HOLE_BLANK))["ops"][
        "S1:10"
    ]
    assert detail["tool_hits"] == 0
    assert detail["reach_depth_mm"] == pytest.approx(6.0)
    op["projection_mm"] = 4.0
    low = engine.run(engine.job(step, {"floor": floor}, [setup], stock=HOLE_BLANK))["ops"]["S1:10"]
    assert low["tool_hits"] == 0 and low["holder_hits"] > 0


HOLE_BLANK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [40.0, 20.0],
}


@pytest.mark.parametrize("action", ["drill", "spot", "ream", "bore", "tap", "counterbore"])
def test_hole_operation_excludes_its_own_cut_not_its_holder_obstacles(engine, solids, action):
    step = solids["hole"]
    hole = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20), kind="Cylinder")
    radius = 3.256 if action == "ream" else 3.25
    op = {
        **_op("S1:10", "hole", radius, 25.0, 30.0),
        "do": action,
        "hole": {"thru": action != "spot", "depth_mm": 0.5, "entry_z_mm": 20.0},
    }
    if action == "spot":
        op["hole"]["point_angle_deg"] = 90.0
    setup = _setup([op], _vise(5.0, centre=30.0))
    detail = engine.run(engine.job(step, {"hole": hole}, [setup], stock=HOLE_BLANK))["ops"]["S1:10"]
    assert detail["tool_hits"] == 0
    assert detail["corner_radii_mm"] == []
    if action == "drill":
        op["projection_mm"] = 5.0
        low = engine.run(engine.job(step, {"hole": hole}, [setup], stock=HOLE_BLANK))["ops"][
            "S1:10"
        ]
        assert low["tool_hits"] == 0 and low["holder_hits"] > 0


@pytest.mark.parametrize("action", ["spot", "tap"])
def test_depth_limited_hole_op_on_through_feature_does_not_cut_full_stock(engine, solids, action):
    step = solids["hole"]
    hole = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20), kind="Cylinder")
    op = {
        **_op("S1:10", "hole", 3.25, 25.0, 30.0),
        "do": action,
        "hole": {"thru": True, "depth_mm": 0.5, "entry_z_mm": 20.0},
    }
    if action == "spot":
        op["hole"]["point_angle_deg"] = 90.0
    first = {**_setup([op], _vise(5.0, centre=30.0)), "stock_in": "stock"}
    later = {
        **_setup([], _vise(5.0, centre=30.0)),
        "id": "S2",
        "stock_in": "S1",
    }
    result = engine.run(engine.job(step, {"hole": hole}, [first, later], stock=HOLE_BLANK))
    assert result["ops"]["S1:10"]["tool_hits"] == 0
    assert result["ops"]["S1:10"]["reach_depth_mm"] == pytest.approx(0.5)
    removed = math.pi * 0.5**2 * 0.5 / 3.0 if action == "spot" else math.pi * 3.25**2 * 0.5
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000.0 - removed)


def test_missing_blind_hole_depth_keeps_access_and_later_stock_unknown(engine, solids):
    step = solids["hole"]
    hole = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20), kind="Cylinder")
    op = {
        **_op("S1:10", "hole", 3.25, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": False, "depth_mm": "unknown", "entry_z_mm": 20.0},
    }
    first = {**_setup([op], _vise(5.0, centre=30.0)), "stock_in": "stock"}
    later = {
        **_setup([], _vise(5.0, centre=30.0)),
        "id": "S2",
        "stock_in": "S1",
    }
    result = engine.run(engine.job(step, {"hole": hole}, [first, later], stock=HOLE_BLANK))
    assert result["ops"]["S1:10"]["tool_hits"] == "unknown"
    assert result["ops"]["S1:10"]["reach_depth_mm"] == "unknown"
    assert result["setups"]["S2"]["width_mm"] == "unknown"


def test_hole_own_cylinder_does_not_delete_an_unclaimed_neighbouring_boss(engine, solids):
    step = solids["hole-boss"]
    pin = engine.refs(step, (31, 19.2, 2), (32.6, 20.8, 12), kind="Cylinder")
    hole = [
        ref
        for ref in engine.refs(step, (26, 16, 2), (34, 24, 20), kind="Cylinder")
        if ref not in pin
    ]
    op = {
        **_op("S1:10", "hole", 3.0, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": False, "entry_z_mm": 20.0, "depth_mm": 18.0},
    }
    detail = engine.run(
        engine.job(step, {"hole": hole}, [_setup([op], _vise(5.0, centre=30.0))], stock=HOLE_BLANK)
    )["ops"]["S1:10"]
    assert detail["tool_hits"] > 0 and pin[0] in detail["hit_refs"]["tool"]


def test_facing_clears_hole_mouth_pins_but_profile_clearing_leaves_holes_for_drilling(
    engine, solids
):
    step = solids["hole"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20), kind="Plane")
    hole = engine.refs(step, (26.75, 16.75, 0), (33.25, 23.25, 20), kind="Cylinder")
    face = {**_op("S1:10", "top", 1.5, 15.0, 30.0), "do": "face", "to_z": 20.0}
    profile = {
        **_op("S2:10", "top", 1.5, 15.0, 30.0),
        "do": "rough_profile",
        "stock_removal_bounds": {"x": [0.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 20.0]},
    }
    drill = {
        **_op("S3:10", "hole", 3.25, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": True, "entry_z_mm": 20.0},
    }
    setups = [
        _setup([face], _vise(5.0, centre=30.0), setup_id="S1"),
        _setup([profile], _vise(5.0, centre=30.0), setup_id="S2"),
        _setup([drill], _vise(5.0, centre=30.0), setup_id="S3"),
        _setup([], _vise(5.0, centre=30.0), setup_id="S4"),
    ]
    rows = engine.run(
        engine.job(
            step,
            {"top": top, "hole": hole},
            setups,
            stock={**HOLE_BLANK, "section_mm": [40.0, 22.0]},
        )
    )["setups"]
    assert rows["S2"]["stock_volume_mm3"] == pytest.approx(48000.0)
    assert rows["S3"]["stock_volume_mm3"] == pytest.approx(48000.0)
    assert rows["S4"]["stock_volume_mm3"] == pytest.approx(48000.0 - math.pi * 3.25**2 * 20)
