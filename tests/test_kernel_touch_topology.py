"""Native STEP wires must explain every credited planar touch face.

These tests author actual solids under the existing FreeCAD fixture. They are not
mock native facts; execution is reserved for the parent's explicit native GO.
"""

import math
import subprocess
import tomllib

import pytest
from test_kernel_geometry import DATA, IDENTITY, Engine
from test_touch_land_topology import assert_square

from prechips.rules.touch_land import certify

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index('--') + 1]

def save(name, shape):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + '/' + name + '.step')

puck = Part.makeCylinder(10, 5, V(2, 3, 0))
save('annulus', puck.cut(Part.makeCylinder(4, 7, V(2, 3, -1))))
save('thin', puck.cut(Part.makeCylinder(9.999, 7, V(2, 3, -1))))
save('offcentre', puck.cut(Part.makeCylinder(2, 7, V(5, 3, -1))))
save('disk', puck)
# Neither a sector nor a slit is a closed complete circle, despite its cylinder.
save('sector', Part.makeCylinder(10, 5, V(2, 3, 0), V(0, 0, 1), 120))
save('slit', puck.cut(Part.makeBox(11, 0.1, 7, V(2, 2.95, -1))))
# A concave all-straight outline is exact polygon topology, not a rectangle/disk.
save('notch', Part.makeBox(20, 10, 5).cut(Part.makeBox(4, 4, 7, V(16, 6, -1))))
# Every hole must survive serialization, including an offcentre second inner wire.
save('two-holes', puck.cut(Part.makeCylinder(1, 7, V(-1, 3, -1))).cut(
    Part.makeCylinder(2, 7, V(5, 3, -1))))
"""

ROTATED = {
    "origin": [7.0, -11.0, 2.0],
    "x": [0.0, 1.0, 0.0],
    "y": [-1.0, 0.0, 0.0],
    "z": [0.0, 0.0, 1.0],
}


def setup(name, frame):
    return {"id": name, "frame": frame, "hold": {"kind": "unknown"}, "ops": []}


@pytest.fixture(scope="module")
def native_topology(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("touch-topology")
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
    assert set(paths) == {
        "annulus",
        "thin",
        "offcentre",
        "disk",
        "sector",
        "slit",
        "notch",
        "two-holes",
    }, process.stdout[-2000:] + process.stderr[-2000:]
    engine = Engine(directory, freecad_kernel)
    records = {}
    for name, path in paths.items():
        faces = engine.faces(path)
        [top] = [
            face
            for face in faces
            if face["kind"] == "Plane"
            and abs(face["bbox_mm"][2] - 5) < 1e-6
            and abs(face["bbox_mm"][5] - 5) < 1e-6
        ]
        job = engine.job(
            path, {"target": [top["ref"]]}, [setup("S1", IDENTITY), setup("S2", ROTATED)]
        )
        job["version"] = 2
        result = engine.run(job)
        assert result["status"] == "ok", result
        records[name] = (top, result)
    return records


def topology_record(native_topology, name, setup_id="S1"):
    top, result = native_topology[name]
    topology = result["setups"][setup_id]["face_topology"][top["ref"]]
    assert topology["ref"] == top["ref"]
    assert topology["index"] == top["index"] == result["mapping"][top["ref"]]
    assert topology["kind"] == "Plane"
    assert topology["area_mm2"] == pytest.approx(top["area_mm2"], rel=1e-9, abs=1e-6)
    assert math.isfinite(topology["error_mm"]) and topology["error_mm"] >= 1e-7
    return topology


def assert_circle(loop, radius, centre):
    assert loop["kind"] == "circle"
    assert loop["radius_mm"] == pytest.approx(radius, abs=1e-6)
    assert loop["centre_mm"] == pytest.approx(centre, abs=1e-6)
    assert abs(loop["normal"][2]) == pytest.approx(1.0, abs=1e-9)
    assert math.isfinite(loop["error_mm"]) and loop["error_mm"] >= 1e-7


def test_native_annulus_keeps_its_complete_outer_and_inner_circle(native_topology):
    topology = topology_record(native_topology, "annulus")
    assert topology["normal"] == pytest.approx([0, 0, 1], abs=1e-9)
    assert topology["z_mm"] == pytest.approx(5.0, abs=1e-9)
    assert topology["area_mm2"] == pytest.approx(math.pi * (100 - 16), abs=1e-5)
    assert_circle(topology["outer"], 10, [2, 3, 5])
    [hole] = topology["inner"]
    assert_circle(hole, 4, [2, 3, 5])
    assert_square(certify(topology, []), topology)


def test_actual_micron_annulus_and_nearly_full_disk_exclusion_refuse_false_credit(native_topology):
    thin = topology_record(native_topology, "thin")
    assert_circle(thin["outer"], 10, [2, 3, 5])
    [hole] = thin["inner"]
    assert_circle(hole, 9.999, [2, 3, 5])
    assert thin["area_mm2"] > 0
    assert certify(thin, []) is None
    disk = topology_record(native_topology, "disk")
    assert disk["inner"] == []
    assert_square(certify(disk, []), disk)
    assert certify(disk, [{"centre_mm": [2, 3, 5], "radius_mm": 9.999, "error_mm": 1e-7}]) is None


def test_native_offcentre_hole_is_not_recentred_or_omitted(native_topology):
    topology = topology_record(native_topology, "offcentre")
    assert_circle(topology["outer"], 10, [2, 3, 5])
    [hole] = topology["inner"]
    assert_circle(hole, 2, [5, 3, 5])
    assert_square(certify(topology, []), topology)
    multiple = topology_record(native_topology, "two-holes")
    assert len(multiple["inner"]) == 2
    holes = sorted(multiple["inner"], key=lambda loop: loop["radius_mm"])
    assert_circle(holes[0], 1, [-1, 3, 5])
    assert_circle(holes[1], 2, [5, 3, 5])
    assert_square(certify(multiple, []), multiple)


def test_setup_transforms_keep_exact_ref_ownership_and_transform_every_loop(native_topology):
    original = topology_record(native_topology, "offcentre")
    rotated = topology_record(native_topology, "offcentre", "S2")
    assert rotated["ref"] == original["ref"] and rotated["index"] == original["index"]
    # Setup coordinates are dot(world - origin, setup basis).
    assert_circle(rotated["outer"], 10, [14, 5, 3])
    [hole] = rotated["inner"]
    assert_circle(hole, 2, [14, 2, 3])
    assert rotated["z_mm"] == pytest.approx(3.0, abs=1e-9)
    assert_square(certify(rotated, []), rotated)
    top, result = native_topology["offcentre"]
    for facts in result["setups"].values():
        for ref, face in facts["face_topology"].items():
            assert face["ref"] == ref
            assert face["index"] == result["mapping"][ref]
    assert top["ref"] in result["setups"]["S2"]["face_topology"]


@pytest.mark.parametrize("name", ["sector", "slit"])
def test_partial_arc_and_slit_native_wires_cannot_masquerade_as_complete_circles(
    native_topology, name
):
    topology = topology_record(native_topology, name)
    assert topology["outer"]["kind"] == "unsupported"
    assert topology["outer"]["reason"]
    assert certify(topology, []) is None


def test_straight_concave_notch_is_ordered_exact_polygon_but_not_a_circular_land(native_topology):
    topology = topology_record(native_topology, "notch")
    loop = topology["outer"]
    assert loop["kind"] == "polygon"
    points = loop["points_mm"]
    assert len(points) == 6 and points[0] != points[-1]
    assert {tuple(round(value, 6) for value in point) for point in points} == {
        (0, 0, 5),
        (20, 0, 5),
        (20, 6, 5),
        (16, 6, 5),
        (16, 10, 5),
        (0, 10, 5),
    }
    signed_area = (
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True))
        / 2
    )
    assert abs(signed_area) == pytest.approx(184.0, abs=1e-6)
    assert topology["inner"] == []
    assert certify(topology, []) is None


def test_real_cone_crank_end_faces_retain_native_annulus_loops(tmp_path, freecad_kernel):
    directory = DATA / "cone-pivot-post"
    features = tomllib.loads((directory / "features.toml").read_text(encoding="utf-8"))
    refs = features["features"]["crank_boss_faces"]["faces"]
    engine = Engine(tmp_path, freecad_kernel)
    job = engine.job(
        directory / "cone-pivot-post.STEP", {"crank_boss_faces": refs}, [setup("S1", IDENTITY)]
    )
    job["version"] = 2
    result = engine.run(job)
    assert result["status"] == "ok", result
    assert len(refs) == 2
    for ref in refs:
        topology = result["setups"]["S1"]["face_topology"][ref]
        assert topology["ref"] == ref and topology["index"] == result["mapping"][ref]
        assert topology["outer"]["kind"] == "circle"
        [hole] = topology["inner"]
        assert hole["kind"] == "circle"
        assert topology["outer"]["radius_mm"] > hole["radius_mm"] > 0
        assert topology["outer"]["centre_mm"] == pytest.approx(hole["centre_mm"], abs=1e-6)
        expected = math.pi * (topology["outer"]["radius_mm"] ** 2 - hole["radius_mm"] ** 2)
        assert topology["area_mm2"] == pytest.approx(expected, rel=1e-6, abs=1e-5)


def test_native_schema_one_is_rejected_before_any_step_read(tmp_path, freecad_kernel):
    engine = Engine(tmp_path, freecad_kernel)
    # No STEP path/hash is provided: the schema gate must be the first failure.
    result = engine.run({"version": 1})
    assert result["status"] == "error"
    assert "version-2 prechips geometry job" in result["reason"]
    assert "step_path" not in result["reason"]
