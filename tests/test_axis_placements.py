"""Shared process axes preserve source identity and refuse nominal fallback.

Host contracts use the immutable cone export; native tests below exercise analytic
material, not merely a serialized job request. This module does not claim shop
measurement, fixture safety or first-article acceptance.
"""

import shutil
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from prechips.axis_placements import member_placement, resolve_placements
from prechips.inputs import BadInput, load_bundle

ROOT = Path(__file__).resolve().parents[1]
PLACEMENT = {
    "boss": "crank_boss",
    "bore": "crank_bore",
    "caps": "crank_boss_faces",
    "support": "head",
    "separation_mm": 43.2735,
}


@pytest.fixture
def placed_cone(tmp_path):
    source = ROOT / "examples" / "cone-pivot-post"
    for name in ("features.toml", "dt-cone-pivot-post.STEP"):
        shutil.copyfile(source / name, tmp_path / name)
    plan = tmp_path / "plan.toml"
    plan.write_text(
        'part = "dt-cone-pivot-post"\nfeatures = "features.toml"\n'
        '[axis_placements.crank]\nboss = "crank_boss"\nbore = "crank_bore"\n'
        'caps = "crank_boss_faces"\nsupport = "head"\nseparation_mm = 43.2735\n'
        '[[setups]]\nid = "S1"\n[[setups.ops]]\nop = 10\n'
        'do = "inspect"\nfeature = "crank_bore"\n',
        encoding="utf-8",
    )
    return load_bundle(
        plan,
        inventory=ROOT / "examples" / "inventory" / "pedro-shop.toml",
        policy=ROOT / "examples" / "shop-policy.toml",
        cutting_data=ROOT / "examples" / "cutting-data.toml",
    )


def _changed(bundle):
    return replace(bundle, plan=deepcopy(bundle.plan), features=deepcopy(bundle.features))


def test_loaded_cone_resolves_one_shared_printed_band_target_without_source_edits(placed_cone):
    bundle = placed_cone
    original = deepcopy(bundle.features)
    hashes = dict(bundle.hashes)
    records = deepcopy(bundle.input_records)
    source_bytes = {name: path.read_bytes() for name, path in bundle.paths.items()}
    (placement,) = resolve_placements(bundle)
    assert placement["name"] == "crank"
    assert {key: placement[key] for key in PLACEMENT} == PLACEMENT
    assert placement["reference"] == "journal_bore"
    # Printed 3-place bounds, not the raw exported band, select this midpoint.
    assert placement["band_mm"] == pytest.approx([43.096, 43.451])
    assert placement["separation_mm"] == pytest.approx(sum(placement["band_mm"]) / 2)
    for name in ("crank_boss", "crank_bore", "crank_boss_faces"):
        assert member_placement(bundle, name) == placement
    assert placement["origin_mm"] == pytest.approx([0, 81.19564350289599, 0])
    assert placement["delta_mm"] == pytest.approx([0, 0.177856497104, 0], abs=1e-12)
    assert placement["reference_origin_mm"] == pytest.approx([0, 38.1, 0])
    assert member_placement(bundle, "head") is None
    assert bundle.features == original
    assert bundle.hashes == hashes
    assert bundle.input_records == records
    assert {name: path.read_bytes() for name, path in bundle.paths.items()} == source_bytes


@pytest.mark.parametrize(
    "declaration",
    [
        'boss = "unknown"',
        'boss = "missing"',
        "boss = 17",
        "separation_mm = 0",
        "separation_mm = nan",
        "separation_mm = inf",
        "separation_mm = true",
        'separation_mm = "unknown"',
    ],
)
def test_loader_refuses_invalid_declarations_before_returning_bundle(placed_cone, declaration):
    path = placed_cone.paths["plan"]
    text = path.read_text(encoding="utf-8")
    old = 'boss = "crank_boss"' if declaration.startswith("boss") else "separation_mm = 43.2735"
    path.write_text(text.replace(old, declaration), encoding="utf-8")
    with pytest.raises(BadInput):
        load_bundle(
            path,
            inventory=ROOT / "examples" / "inventory" / "pedro-shop.toml",
            policy=ROOT / "examples" / "shop-policy.toml",
            cutting_data=ROOT / "examples" / "cutting-data.toml",
        )


@pytest.mark.parametrize("field", ["boss", "bore", "caps", "support"])
@pytest.mark.parametrize("reference", ["unknown", "missing", "", 17])
def test_invalid_member_reference_never_resolves_nominal_axis(placed_cone, field, reference):
    bundle = _changed(placed_cone)
    bundle.plan["axis_placements"]["crank"][field] = reference
    with pytest.raises(BadInput):
        resolve_placements(bundle)
    with pytest.raises(BadInput):
        member_placement(bundle, "crank_bore")
    from prechips.rules.coordinates import evaluate

    with pytest.raises(BadInput):
        evaluate(bundle)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "unknown", True])
def test_nonpositive_unknown_or_nonfinite_separation_refuses(placed_cone, value):
    bundle = _changed(placed_cone)
    bundle.plan["axis_placements"]["crank"]["separation_mm"] = value
    with pytest.raises(BadInput):
        resolve_placements(bundle)


@pytest.mark.parametrize("value", [43.0959, 43.4511])
def test_target_outside_printed_band_refuses_even_when_raw_band_would_differ(placed_cone, value):
    bundle = _changed(placed_cone)
    bundle.plan["axis_placements"]["crank"]["separation_mm"] = value
    with pytest.raises(BadInput):
        resolve_placements(bundle)
    from prechips.rules.coordinates import evaluate

    with pytest.raises(BadInput):
        evaluate(bundle)


@pytest.mark.parametrize(
    ("feature", "field", "value"),
    [
        ("crank_bore", "height_from", "unknown"),
        ("crank_bore", "height_from", "missing"),
        ("crank_bore", "at", "unknown"),
        ("crank_bore", "thru", False),
        ("crank_bore", "axis", [1, 0, 0]),
        ("crank_boss", "z_mm", "unknown"),
        ("crank_boss", "dia_nominal", 0),
        ("head", "kind", "face"),
        ("journal_bore", "at", "unknown"),
    ],
)
def test_unsupported_or_unresolved_source_facts_refuse(placed_cone, feature, field, value):
    bundle = _changed(placed_cone)
    bundle.features["features"][feature][field] = value
    with pytest.raises(BadInput):
        resolve_placements(bundle)
    from prechips.rules.coordinates import evaluate

    with pytest.raises(BadInput):
        evaluate(bundle)


@pytest.mark.parametrize("conflict", ["second placement", "aim", "workpieces", "faced aim"])
def test_conflicting_plan_geometry_is_not_silently_ignored(placed_cone, conflict):
    bundle = _changed(placed_cone)
    if conflict == "second placement":
        bundle.plan["axis_placements"]["other"] = dict(PLACEMENT)
    elif conflict == "workpieces":
        bundle.plan["workpieces"] = {"copy": {"pose": "unknown", "cite": "test"}}
    elif conflict == "faced aim":
        bundle.plan["aims"] = {
            "head": {"face": "Face1", "requirement": "height", "value_mm": 26.67, "reason": "test"}
        }
    else:
        bundle.plan["aims"] = {
            "crank_bore": {"requirement": "separation", "value_mm": 43.2735, "reason": "test"}
        }
    with pytest.raises(BadInput):
        resolve_placements(bundle)


def test_boss_and_bore_candidate_targets_share_one_axis_without_mutating_manifest(placed_cone):
    from prechips.rules.coordinates import planned_point

    before = deepcopy(placed_cone.features)
    for member in ("crank_boss", "crank_bore"):
        point, metadata, why = planned_point(placed_cone, member)
        assert why is None
        assert point == pytest.approx([0, 81.3735, 0])
        assert "axis_placement" in metadata
    assert placed_cone.features == before


@pytest.mark.parametrize("proof", ["absent", "stale", "failed", "kernel failed"])
def test_unproved_variant_withholds_all_machining_tables_not_nominal_fallback(placed_cone, proof):
    from prechips.rules import coordinates

    request = resolve_placements(placed_cone)[0]
    fact = {"status": "pass", "request": deepcopy(request)}
    if proof == "stale":
        fact["request"]["delta_mm"][1] += 0.001
    elif proof == "failed":
        fact["status"] = "unknown"
    evidence = {"status": "ok", "axis_placements": [fact]}
    if proof == "absent":
        evidence.pop("axis_placements")
    elif proof == "kernel failed":
        evidence["status"] = "error"
    bundle = replace(placed_cone, kernel=evidence)
    (finding,) = coordinates.evaluate(bundle)
    assert finding.status == "unknown"
    assert finding.numbers["axis_placement_debt"]
    for table in ("rows", "profiles", "arc_table", "line_table", "contours", "operations"):
        assert finding.numbers[table] == []


def test_matching_native_proof_releases_same_boss_and_bore_targets(placed_cone):
    from test_travel_m5 import measured

    from prechips.rules import coordinates

    bundle = replace(_changed(placed_cone), inventory=deepcopy(placed_cone.inventory))
    bundle.inventory["machines"]["axis_test_mill"] = {
        "kind": "mill",
        "verify": False,
        "resolution_mm": measured(0.001),
    }
    setup = bundle.plan["setups"][0]
    setup["frame"] = "model"
    setup["machine"] = "axis_test_mill"
    setup["ops"] = [
        {"op": 10, "do": "inspect", "feature": "crank_boss"},
        {"op": 20, "do": "inspect", "feature": "crank_bore"},
    ]
    request = resolve_placements(bundle)[0]
    # This exercises the host proof-consumer boundary; native construction itself
    # is independently checked against material below, not mocked there.
    bundle = replace(
        bundle,
        kernel={"status": "ok", "axis_placements": [{"status": "pass", "request": request}]},
    )
    (finding,) = coordinates.evaluate(bundle)
    rows = {row["feature"]: row for row in finding.numbers["rows"]}
    assert set(rows) == {"crank_boss", "crank_bore"}
    for row in rows.values():
        assert row["model"] == pytest.approx([0, 81.3735, 0])
        assert row["setup"] == pytest.approx([0, 81.3735, 0])
        assert row["source_model"] == pytest.approx([0, 81.19564350289599, 0])
        assert row["axis_placement"]["separation_mm"] == 43.2735
    assert rows["crank_bore"]["band_check"]["value_mm"] == pytest.approx(43.2735)


_NATIVE_AXIS = r"""
import json
import math
import runpy
import sys
from pathlib import Path
import FreeCAD as App
import Part

out = Path(sys.argv[sys.argv.index("--") + 1])
native = Path(__NATIVE_PATH__)
sys.path.insert(0, str(native.parent))
module = runpy.run_path(str(native), run_name="axis_placement_test")
apply = module["_axis_placed_solid"]
mode = __MODE__
V = App.Vector
support = Part.makeCylinder(10, 30, V(0, 0, 0), V(0, 1, 0))
boss = Part.makeCylinder(4, 27, V(0, 15, -11))
bore = Part.makeCylinder(2, 27, V(0, 15, -11))
reference = Part.makeCylinder(1, 22, V(0, 5, -11))
source = support.fuse(boss).cut(bore).cut(reference).removeSplitter()
counterbore = Part.makeCylinder(2, 30, V(5, 0, 0), V(0, 1, 0))
if mode == "support cavity":
    source = source.cut(counterbore).removeSplitter()
elif mode == "unrelated cavity":
    source = source.cut(Part.makeSphere(0.3, V(3, 15, 13))).removeSplitter()
assert source.isValid() and len(source.Solids) == 1
labels = ["Face%d" % (i + 1) for i in range(len(source.Faces))]
mapping = {label: i for i, label in enumerate(labels)}
features = {key: [] for key in ("boss", "bore", "caps", "support", "reference")}
for i, face in enumerate(source.Faces):
    surface = face.Surface
    if isinstance(surface, Part.Cylinder):
        role = {10: "support", 4: "boss", 2: "bore", 1: "reference"}.get(round(surface.Radius))
        if mode == "support cavity" and abs(surface.Axis.y) > 0.9 and surface.Radius < 3:
            role = None
    else:
        z = face.CenterOfMass.z
        role = "caps" if abs(z + 11) < 1e-7 or abs(z - 16) < 1e-7 else None
    if role:
        features[role].append(labels[i])
assert all(features.values()), features
spec = {
    "name": "placed", "boss": "boss", "bore": "bore", "caps": "caps",
    "support": "support", "reference": "reference",
    "separation_mm": 10.2, "band_mm": [10.1, 10.3],
    "delta_mm": [0, 0.2, 0], "origin_mm": [0, 15, 0], "axis": [0, 0, 1],
    "boss_radius_mm": 4, "bore_radius_mm": 2, "z_mm": [-11, 16],
    "support_origin_mm": [0, 0, 0], "support_axis": [0, 1, 0],
    "support_radius_mm": 10, "support_z_mm": [0, 30],
    "reference_origin_mm": [0, 5, 0], "reference_axis": [0, 0, 1],
}
before = source.copy()
baseline, no_facts = apply(source, [], mapping, labels, features)
assert not no_facts and baseline.cut(source).Volume < 1e-8
assert source.cut(baseline).Volume < 1e-8
if mode == "unrelated cavity":
    try:
        apply(source, [spec], mapping, labels, features)
    except module["_Unknown"] as exc:
        assert "old bore or boss contains unrelated material/voids" in str(exc), str(exc)
        (out / "axis-evidence.json").write_text(json.dumps({"refused": str(exc)}))
        sys.exit(0)
    raise AssertionError("unsupported boss cavity earned placed geometry")
placed, facts = apply(source, [spec], mapping, labels, features)
assert placed.isValid() and len(placed.Solids) == 1
# Independent manufacturing solid: reconstruct at the target, not by translating
# the finished input or comparing the helper to its own returned request.
expected = support.fuse(Part.makeCylinder(4, 27, V(0, 15.2, -11)))
expected = expected.cut(Part.makeCylinder(2, 27, V(0, 15.2, -11)))
expected = expected.cut(reference).removeSplitter()
if mode == "support cavity":
    expected = expected.cut(counterbore).removeSplitter()
    assert placed.common(counterbore).Volume < 1e-8
# FreeCAD's Shape.Volume getter uses non-adaptive BRepGProp::VolumeProperties:
# https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/Mod/Part/App/TopoShapePyImp.cpp
# Source-indexed and refined shells can integrate differently. Compare material,
# not subtraction of their separately integrated totals; no cancellation allowed.
extra_volume = placed.cut(expected).Volume
missing_volume = expected.cut(placed).Volume
assert extra_volume + missing_volume < 1e-6
assert source.cut(before).Volume < 1e-8 and before.cut(source).Volume < 1e-8
assert len(placed.Faces) == len(source.Faces)
for ref in features["support"]:
    surface = placed.Faces[mapping[ref]].Surface
    assert abs(surface.Radius - 10) < 1e-7
    assert abs(abs(surface.Axis.y) - 1) < 1e-7
    assert abs(surface.Center.x) < 1e-7 and abs(surface.Center.z) < 1e-7
changed_refs = set().union(*(set(features[role]) for role in ("boss", "bore", "caps", "support")))
for ref in set(labels) - changed_refs:
    i = mapping[ref]
    assert placed.Faces[i].cut(before.Faces[i]).Area < 1e-6
    assert before.Faces[i].cut(placed.Faces[i]).Area < 1e-6
# Source-index association must survive; equal total volume alone cannot prove
# that collision/coverage consumers receive the correct moved wall or cap.
delta = V(0, 0.2, 0)
for role in ("boss", "bore", "caps"):
    for ref in features[role]:
        face = placed.Faces[mapping[ref]]
        if role == "caps":
            old = before.Faces[mapping[ref]].copy()
            old.translate(delta)
            assert face.cut(old).Area < 1e-6 and old.cut(face).Area < 1e-6
            assert abs(face.Area - math.pi * (4**2 - 2**2)) < 1e-6
        else:
            axis = face.Surface
            assert abs(axis.Center.y - 15.2) < 1e-7
            assert abs(axis.Radius - (4 if role == "boss" else 2)) < 1e-7
for ref in features["reference"]:
    i = mapping[ref]
    assert placed.Faces[i].cut(before.Faces[i]).Area < 1e-6
    assert before.Faces[i].cut(placed.Faces[i]).Area < 1e-6
# A real cutter-sized solid on the new bore axis clears manufactured material;
# its former nominal-axis counterpart collides with the shifted bore wall.
new_probe = Part.makeCylinder(1.95, 27, V(0, 15.2, -11))
old_probe = Part.makeCylinder(1.95, 27, V(0, 15, -11))
assert placed.common(new_probe).Volume < 1e-7
assert placed.common(old_probe).Volume > 0.01
assert len(facts) == 1 and facts[0]["status"] == "pass", facts
(out / "axis-evidence.json").write_text(json.dumps({
    "volume_mm3": placed.Volume,
    "expected_volume_mm3": expected.Volume,
    "extra_volume_mm3": extra_volume,
    "missing_volume_mm3": missing_volume,
    "nominal_axis_collision_mm3": placed.common(old_probe).Volume,
    "facts": facts,
}))
"""


@pytest.mark.parametrize("mode", ["plain", "support cavity", "unrelated cavity"])
def test_native_placed_material_caps_and_collision_axis_are_not_nominal(
    tmp_path, freecad_kernel, mode
):
    import json

    from test_kernel_rocker_regression import _author

    native = ROOT / "src" / "prechips" / "kernel" / "freecad_job.py"
    source = _NATIVE_AXIS.replace("__NATIVE_PATH__", repr(str(native)))
    source = source.replace("__MODE__", repr(mode))
    evidence = json.loads(
        _author(tmp_path, source, "axis-evidence.json", freecad_kernel).read_text(encoding="utf-8")
    )
    if mode == "unrelated cavity":
        assert "unrelated material/voids" in evidence["refused"]
        return
    assert evidence["extra_volume_mm3"] + evidence["missing_volume_mm3"] < 1e-6
    assert evidence["nominal_axis_collision_mm3"] > 0.01
    assert evidence["facts"][0]["request"]["delta_mm"] == [0, 0.2, 0]


_EXPORTED_CONE = r"""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import FreeCAD as App
import Part

out = Path(sys.argv[sys.argv.index("--") + 1])
request = json.loads((out / "cone-input.json").read_text(encoding="utf-8"))
native = Path(__NATIVE_PATH__)
sys.path.insert(0, str(native.parent))
module = runpy.run_path(str(native), run_name="axis_placement_cone_test")
job, definitions = request["job"], request["definitions"]
data = Path(job["step_path"]).read_bytes()
assert hashlib.sha256(data).hexdigest() == job["step_sha256"]
shape = Part.Shape()
shape.read(job["step_path"])
assert len(shape.Solids) == 1
source = shape.Solids[0]
mapping, errors = module["_map_faces"](
    module["StepFile"](data.decode("latin-1")),
    [module["_signature"](face) for face in source.Faces],
)
assert not errors, errors
assert len(mapping) == len(source.Faces)
labels = [None] * len(source.Faces)
for ref, index in mapping.items():
    labels[index] = ref
baseline = module["run_job"]({**job, "axis_placements": []})
assert baseline["status"] == "ok", baseline
assert not baseline.get("axis_placements")
result = module["run_job"](job)
assert result["status"] == "ok", result
assert result["mapping"] == baseline["mapping"] == mapping
assert result["faces"] == baseline["faces"]
assert result["process_shape_sha256"] == result["process_shape"]["sha256"]
assert len(result["process_shape_sha256"]) == 64
assert result["process_shape"]["source_step_sha256"] == hashlib.sha256(data).hexdigest()
spec = job["axis_placements"][0]
assert result["axis_placements"][0]["request"] == spec
process, facts = module["_axis_placed_solid"](
    source, job["axis_placements"], mapping, labels, job["features"]
)
assert process.isValid() and len(process.Solids) == 1
assert len(process.Faces) == len(source.Faces)
V = App.Vector
delta = V(*spec["delta_mm"])
axis = V(*spec["axis"])
origin = V(*spec["origin_mm"])
z0, z1 = spec["z_mm"]
support_origin = V(*spec["support_origin_mm"])
support_axis = V(*spec["support_axis"])
s0, s1 = spec["support_z_mm"]
support_mask = Part.makeCylinder(
    spec["support_radius_mm"], s1 - s0, support_origin + support_axis * s0, support_axis
)
old_boss = Part.makeCylinder(spec["boss_radius_mm"], z1 - z0, origin + axis * z0, axis)
old_bore = Part.makeCylinder(spec["bore_radius_mm"], z1 - z0, origin + axis * z0, axis)
new_boss = old_boss.translated(delta)
new_bore = old_bore.translated(delta)
expected = source.fuse(old_bore).cut(old_boss.cut(support_mask))
expected = expected.fuse(new_boss.cut(support_mask)).cut(new_bore)
assert process.cut(expected).Volume + expected.cut(process).Volume < 1e-6
# Before/after cutter-solid controls distinguish the actual manufacturing
# cavity from both unchanged source geometry and a coordinates-only shift.
old_probe = Part.makeCylinder(
    spec["bore_radius_mm"] - 0.02, z1 - z0, origin + axis * z0, axis
)
new_probe = old_probe.translated(delta)
assert source.common(old_probe).Volume < 1e-6
assert source.common(new_probe).Volume > 0.01
assert process.common(new_probe).Volume < 1e-6
assert process.common(old_probe).Volume > 0.01
# Inspect actual canonical source-associated surfaces, not requested coordinates.
for role, radius in (("boss", spec["boss_radius_mm"]), ("bore", spec["bore_radius_mm"])):
    for ref in job["features"][spec[role]]:
        surface = process.Faces[mapping[ref]].Surface
        assert isinstance(surface, Part.Cylinder)
        assert abs(surface.Center.y - 81.3735) < 1e-7
        assert abs(surface.Center.x) < 1e-7
        assert abs(abs(surface.Axis.z) - 1) < 1e-7
        assert abs(surface.Radius - radius) < 1e-7
for ref in job["features"][spec["caps"]]:
    original = source.Faces[mapping[ref]].copy()
    original.translate(delta)
    placed = process.Faces[mapping[ref]]
    assert placed.cut(original).Area < 1e-6
    assert original.cut(placed).Area < 1e-6
unchanged = ["journal_bore", "mount_west", "mount_east",
             "mount_west_counterbore", "mount_east_counterbore"]
for name in unchanged:
    for ref in job["features"][name]:
        i = mapping[ref]
        assert process.Faces[i].cut(source.Faces[i]).Area < 1e-6
        assert source.Faces[i].cut(process.Faces[i]).Area < 1e-6
# Each counterbore must retain its actual negative space within the support
# cylinder. A translated-envelope union that refills either pocket fails this.
voids = {}
for side in ("west", "east"):
    parent = definitions["mount_" + side]
    cavity = definitions["mount_" + side + "_counterbore"]
    axis = V(*parent["axis"])
    probe = Part.makeCylinder(
        cavity["nominal_dia"] / 2 - 0.001,
        cavity["depth_ref"] - 0.002,
        V(*parent["at"]) + axis * 0.001,
        axis,
    )
    assert source.common(probe).Volume < 1e-6
    voids[side] = process.common(probe).Volume
    assert voids[side] < 1e-6
assert Path(job["step_path"]).read_bytes() == data
process_faces = result["process_shape"]["faces"]
assert {row["ref"]: row["index"] for row in process_faces} == mapping
for name in unchanged:
    refs = set(job["features"][name])
    old = {row["ref"]: row for row in baseline["faces"] if row["ref"] in refs}
    new = {row["ref"]: row for row in process_faces if row["ref"] in refs}
    for ref in refs:
        assert old[ref]["bbox_mm"] == new[ref]["bbox_mm"]
        assert abs(old[ref]["area_mm2"] - new[ref]["area_mm2"]) < 1e-6
(out / "cone-evidence.json").write_text(json.dumps({
    "status": result["status"],
    "source_sha256": job["step_sha256"],
    "process_shape_sha256": result["process_shape_sha256"],
    "counterbore_material_mm3": voids,
    "face_count": len(process_faces),
}))
"""


def test_exact_exported_cone_native_placement_preserves_journal_and_counterbore_voids(
    tmp_path, freecad_kernel, placed_cone
):
    import hashlib
    import json

    from test_kernel_geometry import Engine
    from test_kernel_rocker_regression import _author

    step = placed_cone.paths["step"]
    definitions = placed_cone.features["features"]
    features = {name: value["faces"] for name, value in definitions.items() if "faces" in value}
    job = Engine(tmp_path, freecad_kernel).job(step, features=features)
    job["axis_placements"] = resolve_placements(placed_cone)
    (tmp_path / "cone-input.json").write_text(
        json.dumps({"job": job, "definitions": definitions}), encoding="utf-8"
    )
    native = ROOT / "src" / "prechips" / "kernel" / "freecad_job.py"
    evidence = json.loads(
        _author(
            tmp_path,
            _EXPORTED_CONE.replace("__NATIVE_PATH__", repr(str(native))),
            "cone-evidence.json",
            freecad_kernel,
        ).read_text(encoding="utf-8")
    )
    assert evidence["status"] == "ok"
    assert evidence["source_sha256"] == hashlib.sha256(step.read_bytes()).hexdigest()
    assert len(evidence["process_shape_sha256"]) == 64
    assert evidence["face_count"] > 0
    assert evidence["counterbore_material_mm3"] == pytest.approx({"west": 0, "east": 0}, abs=1e-6)
