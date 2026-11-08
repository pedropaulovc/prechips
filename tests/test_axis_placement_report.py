"""Host-only report projection of explicitly injected native placement facts.

These tests do not construct or certify a manufacturing solid. Actual native
construction is covered independently in test_axis_placements.py.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_axis_placements import placed_cone  # noqa: F401 - shared host-only fixture

from prechips.axis_placements import resolve_placements
from prechips.report import build_report, canonical_bytes, report_hash


@pytest.fixture
def reported_cone(placed_cone):
    """Inject facts at the host consumer boundary; never invoke a native kernel."""
    request = resolve_placements(placed_cone)[0]
    fact = {
        "name": request["name"],
        "status": "pass",
        "request": deepcopy(request),
        "delta_mm": deepcopy(request["delta_mm"]),
        "separation_mm": 43.273500123456,
        "source_separation_mm": 43.09564350289599,
        "source": {"boss": ["Face1"], "bore": ["Face2"]},
        "provenance": [
            {"ref": "Face1", "index": 0, "role": "boss", "change": "retrimmed"},
            {"ref": "Face2", "index": 1, "role": "bore", "change": "translated"},
        ],
        "proof": {
            "solid_count": 1,
            "source_face_count": 2,
            "process_face_count": 2,
            "symmetric_difference_mm3": 0.000000123456789,
            "old_bore_material_mm3": 0.0,
            "old_protrusion_missing_mm3": 0.0,
            "new_protrusion_overlap_mm3": 0.0,
            "new_bore_missing_mm3": 0.0,
            "support_end_margin_mm": 1.234567890123,
            "boss_wall_mm": 2.345678901234,
            "unrelated_surface_clearance_mm": None,
        },
    }
    digest = "a1" * 32
    return replace(
        placed_cone,
        kernel={
            "status": "ok",
            "axis_placements": [fact],
            "process_shape_sha256": digest,
            "process_shape": {
                "sha256": digest,
                "source_step_sha256": placed_cone.features["step_sha256"],
                "bbox_mm": [-12.345678901234, 0.0, -11.0, 12.345678901234, 90.123456789, 16.0],
                "volume_mm3": 1234.567890123456,
                "faces": [{"ref": "Face1", "index": 0}, {"ref": "Face2", "index": 1}],
                "brep": "HOST_FIXTURE_BREP_MUST_NOT_BE_PUBLISHED",
            },
            "brep": "HOST_FIXTURE_KERNEL_BREP_MUST_NOT_BE_PUBLISHED",
        },
    )


def test_placement_report_preserves_exact_evidence_without_process_geometry(reported_cone):
    bundle = reported_cone
    before = deepcopy(bundle.kernel)
    source_features = deepcopy(bundle.features)
    source_inputs = deepcopy(bundle.input_records)
    report = build_report(bundle, [])
    definition = {
        "definition_contract": "shared_cylindrical_axis_v1",
        "source_step_sha256": bundle.features["step_sha256"],
        "feature_manifest_sha256": bundle.hashes["features"],
        "requested_axis_placements": resolve_placements(bundle),
    }
    shape = report["manufacturing_shape"]
    assert shape == {
        "status": "pass",
        "source_step_sha256": bundle.features["step_sha256"],
        "requested_axis_placements": resolve_placements(bundle),
        "feature_manifest_sha256": bundle.hashes["features"],
        "definition_contract": "shared_cylindrical_axis_v1",
        "process_definition_sha256": hashlib.sha256(canonical_bytes(definition)).hexdigest(),
        "axis_placements": before["axis_placements"],
        "bbox_mm": before["process_shape"]["bbox_mm"],
        "volume_mm3": before["process_shape"]["volume_mm3"],
        "face_count": len(before["process_shape"]["faces"]),
    }
    encoded = canonical_bytes(report)
    assert json.loads(encoded)["manufacturing_shape"] == shape
    assert b"HOST_FIXTURE" not in encoded
    assert "faces" not in shape
    assert "process_shape" not in shape
    assert "process_shape_sha256" not in shape
    assert bundle.kernel["process_shape_sha256"].encode() not in encoded
    assert report["step_sha256"] == bundle.features["step_sha256"]
    assert report["inputs"] == source_inputs
    assert bundle.features == source_features
    assert bundle.kernel == before
    assert report["hash"] == report_hash(report)
    unsigned = {key: value for key, value in report.items() if key != "hash"}
    assert report["hash"] == hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    # Published data is a copy, not a mutable alias into raw native operands.
    shape["axis_placements"][0]["proof"]["boss_wall_mm"] = -1
    shape["requested_axis_placements"][0]["delta_mm"][1] = -1
    shape["bbox_mm"][0] = -999
    assert bundle.kernel == before
    assert resolve_placements(bundle) == [before["axis_placements"][0]["request"]]


@pytest.mark.parametrize("declaration", [None, {}], ids=["absent", "empty"])
def test_no_placement_plan_has_no_manufacturing_shape_even_with_native_facts(
    reported_cone, declaration
):
    plan = deepcopy(reported_cone.plan)
    plan.pop("axis_placements")
    if declaration is not None:
        plan["axis_placements"] = declaration
    report = build_report(replace(reported_cone, plan=plan), [])
    assert "manufacturing_shape" not in report
    assert b'"manufacturing_shape"' not in canonical_bytes(report)


@pytest.mark.parametrize(
    "case",
    [
        "no kernel",
        "missing proof",
        "empty proof",
        "extra proof",
        "non-map proof",
        "failed proof",
        "missing request",
        "stale request",
        "partial request",
        "missing process",
        "wrong source",
        "missing source",
        "wrong process",
        "missing process digest",
        "missing kernel digest",
        "short digest",
        "nonhex digest",
        "unknown native status",
        "kernel error",
    ],
)
def test_unproved_report_exposes_request_and_reason_but_no_native_success(reported_cone, case):
    kernel = deepcopy(reported_cone.kernel)
    if case == "no kernel":
        kernel = None
    elif case == "missing proof":
        kernel.pop("axis_placements")
    elif case == "empty proof":
        kernel["axis_placements"] = []
    elif case == "extra proof":
        kernel["axis_placements"].append(deepcopy(kernel["axis_placements"][0]))
    elif case == "non-map proof":
        kernel["axis_placements"] = [None]
    elif case == "failed proof":
        kernel["axis_placements"][0]["status"] = "unknown"
    elif case == "missing request":
        kernel["axis_placements"][0].pop("request")
    elif case == "stale request":
        kernel["axis_placements"][0]["request"]["delta_mm"][1] += 0.001
    elif case == "partial request":
        kernel["axis_placements"][0]["request"].pop("support_radius_mm")
    elif case == "missing process":
        kernel.pop("process_shape")
    elif case == "wrong source":
        kernel["process_shape"]["source_step_sha256"] = "b2" * 32
    elif case == "missing source":
        kernel["process_shape"].pop("source_step_sha256")
    elif case == "wrong process":
        kernel["process_shape"]["sha256"] = "b2" * 32
    elif case == "missing process digest":
        kernel["process_shape"].pop("sha256")
    elif case == "missing kernel digest":
        kernel.pop("process_shape_sha256")
    elif case in ("short digest", "nonhex digest"):
        digest = "a" * 63 if case == "short digest" else "g" * 64
        kernel["process_shape"]["sha256"] = kernel["process_shape_sha256"] = digest
    elif case == "unknown native status":
        kernel["status"] = "unknown"
    elif case == "kernel error":
        kernel["status"] = "error"
        kernel["reason"] = "host-injected native construction error"
    bundle = replace(reported_cone, kernel=kernel)
    report = build_report(bundle, [])
    shape = report["manufacturing_shape"]
    assert set(shape) == {"status", "source_step_sha256", "requested_axis_placements", "reason"}
    assert shape["status"] == ("error" if case == "kernel error" else "unknown")
    assert shape["source_step_sha256"] == bundle.features["step_sha256"]
    assert shape["requested_axis_placements"] == resolve_placements(bundle)
    assert isinstance(shape["reason"], str) and shape["reason"]
    assert json.loads(canonical_bytes(report))["manufacturing_shape"] == shape
    assert report["hash"] == report_hash(report)


@pytest.mark.parametrize(
    ("owner", "field", "value"),
    [
        ("fact", "proof", None),
        ("fact", "proof", []),
        ("fact", "provenance", None),
        ("fact", "provenance", {}),
        ("fact", "source", None),
        ("fact", "source", []),
        ("shape", "bbox_mm", None),
        ("shape", "bbox_mm", [0, 0, 0]),
        ("shape", "volume_mm3", "unknown"),
        ("shape", "faces", []),
        ("shape", "faces", {}),
    ],
)
def test_incomplete_native_evidence_is_not_published_as_success(
    reported_cone, owner, field, value
):
    kernel = deepcopy(reported_cone.kernel)
    target = kernel["axis_placements"][0] if owner == "fact" else kernel["process_shape"]
    target[field] = value
    report = build_report(replace(reported_cone, kernel=kernel), [])
    shape = report["manufacturing_shape"]
    assert shape["status"] == "unknown"
    assert set(shape) == {"status", "source_step_sha256", "requested_axis_placements", "reason"}
    assert shape["reason"]
    assert shape["source_step_sha256"] == reported_cone.features["step_sha256"]
    assert shape["requested_axis_placements"] == resolve_placements(reported_cone)
    assert json.loads(canonical_bytes(report))["manufacturing_shape"] == shape
    assert report["hash"] == report_hash(report)


def test_changing_only_native_proof_changes_canonical_report_hash(reported_cone):
    before = build_report(reported_cone, [])
    kernel = deepcopy(reported_cone.kernel)
    kernel["axis_placements"][0]["proof"]["symmetric_difference_mm3"] += 1e-12
    after = build_report(replace(reported_cone, kernel=kernel), [])
    assert before["inputs"] == after["inputs"]
    assert (
        before["manufacturing_shape"]["requested_axis_placements"]
        == after["manufacturing_shape"]["requested_axis_placements"]
    )
    assert (
        before["manufacturing_shape"]["process_definition_sha256"]
        == after["manufacturing_shape"]["process_definition_sha256"]
    )
    assert before["hash"] != after["hash"]
    assert canonical_bytes(before) != canonical_bytes(after)
    assert after["hash"] == report_hash(after)


def test_raw_native_serialization_digest_does_not_change_public_report(reported_cone):
    before = build_report(reported_cone, [])
    kernel = deepcopy(reported_cone.kernel)
    kernel["process_shape_sha256"] = kernel["process_shape"]["sha256"] = "c3" * 32
    after = build_report(replace(reported_cone, kernel=kernel), [])
    assert canonical_bytes(before) == canonical_bytes(after)
    assert before["hash"] == after["hash"]
    assert (
        before["manufacturing_shape"]["process_definition_sha256"]
        == after["manufacturing_shape"]["process_definition_sha256"]
    )


@pytest.mark.parametrize("change", ["manifest digest", "requested placement"])
def test_definition_identity_binds_manifest_and_complete_resolved_request(reported_cone, change):
    before = build_report(reported_cone, [])
    hashes = dict(reported_cone.hashes)
    plan = deepcopy(reported_cone.plan)
    kernel = deepcopy(reported_cone.kernel)
    if change == "manifest digest":
        hashes["features"] = "d4" * 32
    else:
        plan["axis_placements"]["crank"]["separation_mm"] = 43.3
    bundle = replace(reported_cone, hashes=hashes, plan=plan, kernel=kernel)
    kernel["axis_placements"][0]["request"] = deepcopy(resolve_placements(bundle)[0])
    after = build_report(bundle, [])
    shape = after["manufacturing_shape"]
    definition = {
        "definition_contract": "shared_cylindrical_axis_v1",
        "source_step_sha256": bundle.features["step_sha256"],
        "feature_manifest_sha256": bundle.hashes["features"],
        "requested_axis_placements": resolve_placements(bundle),
    }
    assert shape["status"] == "pass"
    assert shape["process_definition_sha256"] == hashlib.sha256(
        canonical_bytes(definition)
    ).hexdigest()
    assert (
        before["manufacturing_shape"]["process_definition_sha256"]
        != shape["process_definition_sha256"]
    )
    assert before["hash"] != after["hash"]
    assert after["hash"] == report_hash(after)


@pytest.mark.parametrize("digest", [None, "", "unknown", "a" * 63, "g" * 64])
def test_missing_or_malformed_feature_manifest_digest_withholds_identity_and_proof(
    reported_cone, digest
):
    hashes = dict(reported_cone.hashes)
    paths = dict(reported_cone.paths)
    if digest is None:
        hashes.pop("features")
        # Keep input_records coherent while injecting an absent manifest binding.
        paths.pop("features")
    else:
        hashes["features"] = digest
    report = build_report(replace(reported_cone, hashes=hashes, paths=paths), [])
    shape = report["manufacturing_shape"]
    assert shape["status"] == "unknown"
    assert set(shape) == {"status", "source_step_sha256", "requested_axis_placements", "reason"}
    assert shape["reason"]
    assert shape["source_step_sha256"] == reported_cone.features["step_sha256"]
    assert shape["requested_axis_placements"] == resolve_placements(reported_cone)
    assert report["hash"] == report_hash(report)
