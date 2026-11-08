"""Shared process axes preserve source identity and refuse nominal fallback.

Host contracts use explicit synthetic source declarations; native tests below exercise analytic
material, not merely a serialized job request. This module does not claim shop
measurement, fixture safety or first-article acceptance.
"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from prechips.axis_placements import member_placement, resolve_placements
from prechips.inputs import BadInput

ROOT = Path(__file__).resolve().parents[1]
PLACEMENT = {
    "boss": "crank_boss",
    "bore": "crank_bore",
    "caps": "crank_boss_faces",
    "support": "head",
    "separation_mm": 10.2,
}


@pytest.fixture
def placed_axis(tmp_path):
    """Host-only source declarations; actual STEP construction is tested natively below."""
    import hashlib
    import json

    from prechips.inputs import Bundle

    identity = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    frames = {
        "model": identity,
        "boss": {**identity, "origin": [0, 15, 0]},
        "support": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, -1], "z": [0, 1, 0]},
    }
    definitions = {
        "crank_boss": {"kind": "boss", "frame": "boss", "dia_nominal": 8, "z_mm": [-11, 16]},
        "crank_bore": {
            "kind": "hole",
            "at": [0, 15, 0],
            "axis": [0, 0, 1],
            "nominal_dia": 4,
            "thru": True,
            "requirements": ["separation"],
            "separation": [10.0996, 10.3004],
            "precision": {"separation": 3},
            "height_from": "journal_bore",
        },
        "crank_boss_faces": {"kind": "face", "frame": "boss", "at": [0, 0, -11]},
        "head": {"kind": "boss", "frame": "support", "dia_nominal": 20, "z_mm": [0, 30]},
        "journal_bore": {"kind": "hole", "at": [0, 5, 0], "axis": [0, 0, 1], "nominal_dia": 2},
    }
    for index, (name, feature) in enumerate(definitions.items(), start=1):
        feature["faces"] = [f"#{index}/ADVANCED_FACE[{index}]/{name}"]
    plan = {
        "part": "axis-contract",
        "axis_placements": {"crank": dict(PLACEMENT)},
        "setups": [
            {
                "id": "S1",
                "frame": "model",
                "ops": [{"op": 10, "do": "inspect", "feature": "crank_bore"}],
            }
        ],
    }
    # Explicitly not a native STEP fixture. These bytes exercise immutable input
    # identity only; the FreeCAD test exports and reimports a genuine STEP solid.
    step = tmp_path / "host-identity.step"
    step.write_bytes(b"host-only source identity; not native geometry")
    manifest = {
        "units": "mm",
        "step_sha256": hashlib.sha256(step.read_bytes()).hexdigest(),
        "frames": frames,
        "features": definitions,
    }
    paths = {"step": step}
    for key, value in (("plan", plan), ("features", manifest)):
        paths[key] = tmp_path / f"{key}.json"
        paths[key].write_text(json.dumps(value), encoding="utf-8")
    return Bundle(
        plan,
        manifest,
        {},
        {},
        {},
        paths,
        {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()},
        tmp_path,
    )


def _changed(bundle):
    return replace(bundle, plan=deepcopy(bundle.plan), features=deepcopy(bundle.features))


def test_source_resolves_one_shared_printed_band_target_without_source_edits(placed_axis):
    bundle = placed_axis
    original = deepcopy(bundle.features)
    hashes = dict(bundle.hashes)
    records = deepcopy(bundle.input_records)
    source_bytes = {name: path.read_bytes() for name, path in bundle.paths.items()}
    (placement,) = resolve_placements(bundle)
    assert placement["name"] == "crank"
    assert {key: placement[key] for key in PLACEMENT} == PLACEMENT
    assert placement["reference"] == "journal_bore"
    # Printed 3-place bounds, not the raw exported band, select this midpoint.
    assert placement["band_mm"] == pytest.approx([10.1, 10.3])
    assert placement["separation_mm"] == pytest.approx(sum(placement["band_mm"]) / 2)
    for name in ("crank_boss", "crank_bore", "crank_boss_faces"):
        assert member_placement(bundle, name) == placement
    assert placement["origin_mm"] == pytest.approx([0, 15.0, 0])
    assert placement["delta_mm"] == pytest.approx([0, 0.2, 0], abs=1e-12)
    assert placement["reference_origin_mm"] == pytest.approx([0, 5.0, 0])
    assert member_placement(bundle, "head") is None
    assert bundle.features == original
    assert bundle.hashes == hashes
    assert bundle.input_records == records
    assert {name: path.read_bytes() for name, path in bundle.paths.items()} == source_bytes


@pytest.mark.parametrize("field", ["boss", "bore", "caps", "support"])
@pytest.mark.parametrize("reference", ["unknown", "missing", "", 17])
def test_invalid_member_reference_never_resolves_nominal_axis(placed_axis, field, reference):
    bundle = _changed(placed_axis)
    bundle.plan["axis_placements"]["crank"][field] = reference
    with pytest.raises(BadInput):
        resolve_placements(bundle)
    with pytest.raises(BadInput):
        member_placement(bundle, "crank_bore")
    from prechips.rules.coordinates import evaluate

    with pytest.raises(BadInput):
        evaluate(bundle)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "unknown", True])
def test_nonpositive_unknown_or_nonfinite_separation_refuses(placed_axis, value):
    bundle = _changed(placed_axis)
    bundle.plan["axis_placements"]["crank"]["separation_mm"] = value
    with pytest.raises(BadInput):
        resolve_placements(bundle)


@pytest.mark.parametrize("value", [10.0999, 10.3001])
def test_target_outside_printed_band_refuses_even_when_raw_band_would_differ(placed_axis, value):
    bundle = _changed(placed_axis)
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
def test_unsupported_or_unresolved_source_facts_refuse(placed_axis, feature, field, value):
    bundle = _changed(placed_axis)
    bundle.features["features"][feature][field] = value
    with pytest.raises(BadInput):
        resolve_placements(bundle)
    from prechips.rules.coordinates import evaluate

    with pytest.raises(BadInput):
        evaluate(bundle)


@pytest.mark.parametrize("conflict", ["second placement", "aim", "workpieces", "faced aim"])
def test_conflicting_plan_geometry_is_not_silently_ignored(placed_axis, conflict):
    bundle = _changed(placed_axis)
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
            "crank_bore": {"requirement": "separation", "value_mm": 10.2, "reason": "test"}
        }
    with pytest.raises(BadInput):
        resolve_placements(bundle)


def test_boss_and_bore_candidate_targets_share_one_axis_without_mutating_manifest(placed_axis):
    from prechips.rules.coordinates import planned_point

    before = deepcopy(placed_axis.features)
    for member in ("crank_boss", "crank_bore"):
        point, metadata, why = planned_point(placed_axis, member)
        assert why is None
        assert point == pytest.approx([0, 15.2, 0])
        assert "axis_placement" in metadata
    assert placed_axis.features == before


def _host_native_evidence(bundle):
    """Injected consumer-boundary evidence, not a claim of native construction."""
    request = resolve_placements(bundle)[0]
    source = {
        role: bundle.features["features"][request[role]]["faces"]
        for role in ("boss", "bore", "caps", "support", "reference")
    }
    members = [(role, ref) for role, refs in source.items() for ref in refs]
    provenance = [
        {
            "ref": ref,
            "index": index,
            "role": role,
            "change": "translated"
            if role in ("bore", "caps")
            else "retrimmed"
            if role in ("boss", "support")
            else "unchanged",
        }
        for index, (role, ref) in enumerate(members)
    ]
    digest = "a1" * 32
    return {
        "status": "ok",
        "axis_placements": [
            {
                "status": "pass",
                "request": request,
                "source": deepcopy(source),
                "provenance": provenance,
                "proof": {"solid_count": 1},
            }
        ],
        "process_shape_sha256": digest,
        "process_shape": {
            "sha256": digest,
            "source_step_sha256": bundle.features["step_sha256"],
            "faces": [{"ref": item["ref"], "index": item["index"]} for item in provenance],
        },
    }


@pytest.mark.parametrize(
    "proof",
    [
        "absent",
        "stale",
        "failed",
        "kernel failed",
        "missing construction",
        "missing provenance",
        "missing source",
        "stale source",
        "missing shape",
        "stale shape",
        "duplicate",
    ],
)
def test_unproved_variant_withholds_all_machining_tables_not_nominal_fallback(placed_axis, proof):
    from prechips.rules import coordinates

    evidence = _host_native_evidence(placed_axis)
    fact = evidence["axis_placements"][0]
    if proof == "stale":
        fact["request"]["delta_mm"][1] += 0.001
    elif proof == "failed":
        fact["status"] = "unknown"
    if proof == "absent":
        evidence.pop("axis_placements")
    elif proof == "kernel failed":
        evidence["status"] = "error"
    elif proof == "missing construction":
        fact.pop("proof")
    elif proof == "missing provenance":
        fact.pop("provenance")
    elif proof == "missing source":
        fact.pop("source")
    elif proof == "stale source":
        evidence["process_shape"]["source_step_sha256"] = "b2" * 32
    elif proof == "missing shape":
        evidence.pop("process_shape")
    elif proof == "stale shape":
        evidence["process_shape"]["sha256"] = "b2" * 32
    elif proof == "duplicate":
        evidence["axis_placements"].append(deepcopy(fact))
    bundle = replace(placed_axis, kernel=evidence)
    (finding,) = coordinates.evaluate(bundle)
    assert finding.status == "unknown"
    assert finding.numbers["axis_placement_debt"]
    for table in ("rows", "profiles", "arc_table", "line_table", "contours", "operations"):
        assert finding.numbers[table] == []


def test_matching_native_proof_releases_same_boss_and_bore_targets(placed_axis):
    from test_travel_m5 import measured

    from prechips.rules import coordinates

    bundle = replace(_changed(placed_axis), inventory=deepcopy(placed_axis.inventory))
    bundle.inventory.setdefault("machines", {})["axis_test_mill"] = {
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
    # This exercises the host proof-consumer boundary; native construction itself
    # is independently checked against material below, not mocked there.
    bundle = replace(bundle, kernel=_host_native_evidence(bundle))
    (finding,) = coordinates.evaluate(bundle)
    rows = {row["feature"]: row for row in finding.numbers["rows"]}
    assert set(rows) == {"crank_boss", "crank_bore"}
    for row in rows.values():
        assert row["model"] == pytest.approx([0, 15.2, 0])
        assert row["setup"] == pytest.approx([0, 15.2, 0])
        assert row["source_model"] == pytest.approx([0, 15.0, 0])
        assert row["axis_placement"]["separation_mm"] == 10.2
    assert rows["crank_bore"]["band_check"]["value_mm"] == pytest.approx(10.2)


_NATIVE_AXIS = r"""
import hashlib
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
    # Open through the boss wall: a single-shell source binds independently of
    # closed internal-shell orientation, while missing protrusion still refuses.
    source = source.cut(Part.makeBox(2, 0.6, 0.6, V(2.7, 14.7, 12.7))).removeSplitter()
assert source.isValid() and len(source.Solids) == 1
step_path = out / "source.step"
source.exportStep(str(step_path))
source_bytes = step_path.read_bytes()
imported = Part.Shape()
imported.read(str(step_path))
source = imported.Solids[0]
mapping, errors = module["_map_faces"](
    module["StepFile"](source_bytes.decode("latin-1")),
    [module["_signature"](face) for face in source.Faces],
)
assert not errors, errors
labels = [None] * len(source.Faces)
for ref, index in mapping.items():
    labels[index] = ref
assert all(labels)

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
job = {"version": 1, "step_path": str(step_path),
       "step_sha256": hashlib.sha256(source_bytes).hexdigest(), "features": features,
       "as_is_faces": [], "stock": {"shape": "part"}, "setups": []}
baseline_result = module["run_job"](job)
assert baseline_result["status"] == "ok", baseline_result
assert baseline_result["mapping_errors"] == {}, baseline_result
assert "axis_placements" not in baseline_result
result = module["run_job"]({**job, "axis_placements": [spec]})
assert step_path.read_bytes() == source_bytes
if mode == "unrelated cavity":
    assert result["status"] != "ok", result
    assert "process_shape" not in result
    assert "old bore or boss contains unrelated material/voids" in result["reason"], result
else:
    assert result["status"] == "ok", result
    assert result["faces"] == baseline_result["faces"]
    assert result["mapping"] == baseline_result["mapping"] == mapping
    assert result["process_shape"]["source_step_sha256"] == job["step_sha256"]
    assert result["process_shape"]["sha256"] == result["process_shape_sha256"]
    assert len(result["process_shape_sha256"]) == 64
    assert result["axis_placements"][0]["request"] == spec
    assert {face["ref"]: face["index"] for face in result["process_shape"]["faces"]} == mapping
before = source.copy()
baseline, no_facts = apply(source, [], mapping, labels, features)
assert not no_facts and baseline.cut(source).Volume < 1e-8
assert source.cut(baseline).Volume < 1e-8
if mode == "unrelated cavity":
    missing_protrusion = boss.cut(support).cut(bore).cut(source).Volume
    assert 0.4 < missing_protrusion < 0.5
    try:
        apply(source, [spec], mapping, labels, features)
    except module["_Unknown"] as exc:
        assert "old bore or boss contains unrelated material/voids" in str(exc), str(exc)
        (out / "axis-evidence.json").write_text(json.dumps({
            "refused": str(exc),
            "source_face_count": len(source.Faces),
            "bound_face_count": len(mapping),
            "baseline_status": baseline_result["status"],
            "missing_protrusion_mm3": missing_protrusion,
        }))
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
        assert evidence["baseline_status"] == "ok"
        assert evidence["bound_face_count"] == evidence["source_face_count"] == 14
        assert 0.4 < evidence["missing_protrusion_mm3"] < 0.5
        return
    assert evidence["extra_volume_mm3"] + evidence["missing_volume_mm3"] < 1e-6
    assert evidence["nominal_axis_collision_mm3"] > 0.01
    assert evidence["facts"][0]["request"]["delta_mm"] == [0, 0.2, 0]


def test_caps_boss_and_bore_share_translation_but_support_and_reference_do_not(placed_axis):
    from prechips.rules.coordinates import _placement_geometry, planned_point

    before = deepcopy(placed_axis.features)
    features, frames = _placement_geometry(placed_axis)
    for name, expected in (
        ("crank_boss", [0, 15.2, 0]),
        ("crank_bore", [0, 15.2, 0]),
        ("crank_boss_faces", [0, 15.2, -11]),
        ("journal_bore", [0, 5, 0]),
    ):
        point, metadata, why = planned_point(placed_axis, name)
        assert why is None
        assert point == pytest.approx(expected)
        assert ("axis_placement" in metadata) == (name != "journal_bore")
    assert features["head"] is placed_axis.feature_definitions["head"]
    assert frames["support"] is placed_axis.features["frames"]["support"]
    assert placed_axis.features == before


def test_native_request_gets_candidate_layout_but_public_layout_withholds_it(placed_axis):
    from prechips.rules.coordinates import arc_layout, evaluate

    setup = placed_axis.plan["setups"][0]
    assert arc_layout(placed_axis, setup, "crank_boss") is None
    candidate = arc_layout(placed_axis, setup, "crank_boss", pre_kernel=True)
    assert candidate["centre_setup_xy"] == pytest.approx([0, 15.2])
    assert candidate["centre_on"] == "crank_bore"
    assert candidate["radius_mm"] == 4
    (candidate_finding,) = evaluate(placed_axis, pre_kernel=True)
    assert "axis_placement_debt" not in candidate_finding.numbers
    assert candidate_finding.numbers["rows"]
    assert evaluate(placed_axis)[0].numbers["rows"] == []


def test_native_model_and_cache_projection_bind_complete_request_only_when_authored(placed_axis):
    from prechips.kernel import _model_inputs, engine_job

    model = _model_inputs(placed_axis)
    request = resolve_placements(placed_axis)
    assert model["axis_placements"] == request
    job = {"version": 1, "step_path": str(placed_axis.paths["step"]), **model, "setups": []}
    projected = engine_job(job)
    assert projected["axis_placements"] == request
    changed = _changed(placed_axis)
    changed.plan["axis_placements"]["crank"]["separation_mm"] = 10.25
    other = engine_job({**job, **_model_inputs(changed)})
    assert other != projected
    assert other["axis_placements"] == resolve_placements(changed)
    plan = deepcopy(placed_axis.plan)
    plan.pop("axis_placements")
    absent = replace(placed_axis, plan=plan)
    empty = replace(absent, plan={**plan, "axis_placements": {}})
    assert _model_inputs(absent) == _model_inputs(empty)
    assert "axis_placements" not in _model_inputs(absent)
    ordinary_job = {**job, **_model_inputs(absent)}
    ordinary_job.pop("axis_placements")
    assert "axis_placements" not in engine_job(ordinary_job)
    assert engine_job({**ordinary_job, "axis_placements": []}) == engine_job(ordinary_job)


def test_absent_placement_keeps_original_manifest_and_nominal_point(placed_axis):
    from prechips.rules.coordinates import _placement_geometry, planned_point

    plan = deepcopy(placed_axis.plan)
    plan.pop("axis_placements")
    bundle = replace(placed_axis, plan=plan)
    features, frames = _placement_geometry(bundle)
    assert features is bundle.feature_definitions
    assert frames is bundle.features["frames"]
    assert resolve_placements(bundle) == []
    assert member_placement(bundle, "crank_bore") is None
    point, metadata, why = planned_point(bundle, "crank_bore")
    assert point == [0, 15, 0]
    assert metadata == {}
    assert why is None


def test_unproved_axis_sheet_stops_before_rendering_any_coordinate(placed_axis):
    from prechips.rules.coordinates import evaluate
    from prechips.sheet import _Traveler

    finding = evaluate(placed_axis)[0]
    traveler = object.__new__(_Traveler)
    traveler.bundle = placed_axis
    # Deliberately provide no renderer state: a debt must stop before any table
    # renderer can recover source coordinates or candidate shifted coordinates.
    traveler.records = {("coordinates", "S1"): finding.numbers}
    html = traveler.feature_map(placed_axis.plan["setups"][0])
    assert "STOP" in html
    assert "No nominal or shifted machining coordinates are released" in html
    assert "<table" not in html
    assert "15.2" not in html


@pytest.mark.parametrize(
    "problem", ["overlap", "left handed", "end margin", "sideways", "aim alias"]
)
def test_source_contract_refuses_unsupported_shared_geometry(placed_axis, problem):
    bundle = _changed(placed_axis)
    definitions = bundle.features["features"]
    if problem == "overlap":
        definitions["crank_bore"]["faces"] = definitions["crank_boss"]["faces"]
    elif problem == "left handed":
        bundle.features["frames"]["boss"]["x"] = [-1, 0, 0]
    elif problem == "end margin":
        definitions["head"]["z_mm"] = [0, 19]
    elif problem == "sideways":
        definitions["journal_bore"]["at"] = [1, 5, 0]
    else:
        definitions["alias"] = {"kind": "hole", "parent": "crank_bore"}
        bundle.plan["aims"] = {"alias": {"requirement": "separation", "value_mm": 10.2}}
    with pytest.raises(BadInput):
        resolve_placements(bundle)


def test_inch_source_uses_millimetres_for_native_translation_without_mutation(placed_axis):
    bundle = _changed(placed_axis)
    manifest = bundle.features
    manifest["units"] = "in"
    for frame in manifest["frames"].values():
        frame["origin"] = [value / 25.4 for value in frame["origin"]]
    for feature in manifest["features"].values():
        for key in ("at", "z_mm", "separation"):
            if key in feature:
                feature[key] = [value / 25.4 for value in feature[key]]
        for key in ("dia_nominal", "nominal_dia"):
            if key in feature:
                feature[key] /= 25.4
    before = deepcopy(manifest)
    (request,) = resolve_placements(bundle)
    assert request["origin_mm"] == pytest.approx([0, 15, 0])
    assert request["delta_mm"] == pytest.approx([0, 0.2, 0])
    assert request["boss_radius_mm"] == pytest.approx(4)
    assert request["bore_radius_mm"] == pytest.approx(2)
    assert request["support_radius_mm"] == pytest.approx(10)
    assert request["z_mm"] == pytest.approx([-11, 16])
    assert request["support_z_mm"] == pytest.approx([0, 30])
    # Drawing precision rounds inward, not to nearest: these converted bounds
    # lie between .397/.398 and .405/.406 inches. The upper .406 would loosen
    # the authored band; .405 is the last permitted three-place upper bound.
    low, high = manifest["features"]["crank_bore"]["separation"]
    assert 0.397 < low < 0.398
    assert 0.405 < high < 0.406
    assert request["band_mm"] == pytest.approx([0.398 * 25.4, 0.405 * 25.4])
    assert request["band_mm"][0] / 25.4 >= low
    assert request["band_mm"][1] / 25.4 <= high
    assert manifest == before
