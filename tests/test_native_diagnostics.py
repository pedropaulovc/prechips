"""Exact publication projections, never tolerance-based acceptance of raw proofs.

The drift values below are measured native diagnostic pairs. The arriving-top
boundary fixtures are synthetic geometry contracts, not native geometry runs.
"""

import hashlib
import json
import math
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from test_arriving_top_rule_consumers import (
    install_proof,
    install_selected_patch_proof,
    proof_bundle,
)
from test_kernel_outputs import _inspection_bundle
from test_validate_examples import validator_test_bundle

from prechips.findings import Finding
from prechips.native_diagnostics import publish_native_diagnostics
from prechips.report import build_report, canonical_bytes, render_assets
from prechips.rules.resolution import LENGTH_TOLERANCE_MM
from prechips.rules.zero_recipe import rule as zero_rule
from prechips.rules.zero_recipe.native import zero_pickup_evidence

_WITNESS_Y = (2.8148227397287773, 2.814822739728779)
_VOLUMES = (
    (4242.718684577403, 2980.028808269518),
    (4242.718684577404, 2980.0288082695183),
)
_CONTACT_Y = (-14.287500000000152, -14.28750000000015)
_AREAS = (
    (243.8959612494547, 41.12699574288723),
    (243.89596124945473, 41.126995742887246),
)


def _diagnostics(variant):
    """Small publication payload, deliberately not a complete geometry proof."""
    area, patch = _AREAS[variant]
    y = _CONTACT_Y[variant]
    pickup = {
        "model": "arriving_top_v1",
        "path": {
            "legs": [{"components": [{"swept_volume_mm3": volume} for volume in _VOLUMES[variant]]}]
        },
        "resolved_contact": {
            "contact_model": "flat_end_projection_v1",
            "land_bbox_mm": [0.0, -14.287500000000152, 10.0, 1.0, 5.0, 10.0],
            "patch_bbox_mm": [0.0, y, 10.0, 2.0, 6.0, 10.0],
            "land_area_mm2": 41.12699574288723,
            "missing_land_area_mm2": -1e-12,
            "footprint_area_mm2": 243.8959612494547,
            "contact_area_mm2": area,
            "uncovered_area_mm2": 1e-12,
            "patch_area_mm2": patch,
        },
    }
    minimum = {
        "mm": 1e-12,
        "from_mm": [0.0, _WITNESS_Y[variant], 1.0],
        "to_mm": [0.0, _WITNESS_Y[variant], 2.0],
    }
    clearance = {
        "model": "finite_disk_v1",
        "source": "finite_occupied_sweeps",
        "scope": "machining_trajectory",
        "frame": "setup",
        "minimum": minimum,
        "sweeps": [{"minimum": {**deepcopy(minimum), "mm": 0.0}}],
    }
    return {"pickup": pickup, "clearance": clearance}


def _expected_diagnostics():
    # Independent literals: do not obtain expected numbers by invoking the helper,
    # round(), a Finding, a report, or the validator under test.
    return {
        "pickup": {
            "model": "arriving_top_v1",
            "path": {
                "legs": [
                    {
                        "components": [
                            {"swept_volume_mm3": 4242.718685},
                            {"swept_volume_mm3": 2980.028808},
                        ]
                    }
                ]
            },
            "resolved_contact": {
                "contact_model": "flat_end_projection_v1",
                "land_bbox_mm": [0.0, -14.287500000000152, 10.0, 1.0, 5.0, 10.0],
                "patch_bbox_mm": [0.0, -14.2875, 10.0, 2.0, 6.0, 10.0],
                "land_area_mm2": 41.12699574288723,
                "missing_land_area_mm2": -1e-12,
                "footprint_area_mm2": 243.8959612494547,
                "contact_area_mm2": 243.895961,
                "uncovered_area_mm2": 0.0,
                "patch_area_mm2": 41.126996,
            },
        },
        "clearance": {
            "model": "finite_disk_v1",
            "source": "finite_occupied_sweeps",
            "scope": "machining_trajectory",
            "frame": "setup",
            "minimum": {
                "mm": 1e-12,
                "from_mm": [0.0, 2.814823, 1.0],
                "to_mm": [0.0, 2.814823, 2.0],
            },
            "sweeps": [
                {
                    "minimum": {
                        "mm": 0.0,
                        "from_mm": [0.0, 2.814823, 1.0],
                        "to_mm": [0.0, 2.814823, 2.0],
                    }
                }
            ],
        },
    }


def _finding(numbers, status="pass"):
    return Finding(
        "native_publication",
        "S1",
        status,
        numbers,
        ["synthetic native contract"],
        "Raw classification precedes publication.",
    )


@pytest.mark.parametrize("model", ["transverse_finder_v1", "arriving_top_v1"])
@pytest.mark.parametrize("variant", [0, 1])
def test_measured_drift_has_independent_exact_canonical_values(model, variant):
    raw = _diagnostics(variant)
    raw["pickup"]["model"] = model
    before = deepcopy(raw)
    expected = _expected_diagnostics()
    expected["pickup"]["model"] = model
    if model == "transverse_finder_v1":
        expected["pickup"]["resolved_contact"] = deepcopy(raw["pickup"]["resolved_contact"])
    published = publish_native_diagnostics(raw)
    assert published == expected
    assert raw == before
    contact = published["pickup"]["resolved_contact"]
    assert contact["missing_land_area_mm2"] == -1e-12
    assert contact["uncovered_area_mm2"] == (0.0 if model == "arriving_top_v1" else 1e-12)
    assert math.copysign(1.0, contact["uncovered_area_mm2"]) == 1.0
    assert published["clearance"]["minimum"]["mm"] == 1e-12
    assert published["clearance"]["sweeps"][0]["minimum"]["mm"] == 0.0


def test_report_bytes_hash_and_both_scene_families_ignore_only_diagnostic_drift(tmp_path):
    bundle, sid, key, _, _ = _inspection_bundle(tmp_path)
    assets = render_assets(bundle)
    reports = []
    for variant in (0, 1):
        facts = bundle.kernel["setups"][sid]
        facts["render_scene"]["native_diagnostics"] = _diagnostics(variant)
        facts["inspection_scenes"][key]["native_diagnostics"] = _diagnostics(variant)
        raw = _diagnostics(variant)
        finding = _finding(raw)
        kernel_before, numbers_before = deepcopy(bundle.kernel), deepcopy(raw)
        report = build_report(bundle, [finding], assets=assets)
        expected = _expected_diagnostics()
        assert report["findings"][0]["numbers"] == expected
        assert report["renders"][sid]["scene"]["native_diagnostics"] == expected
        assert report["renders"][sid]["inspections"][key]["scene"]["native_diagnostics"] == expected
        payload = {name: value for name, value in report.items() if name != "hash"}
        independently_serialized = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        assert report["hash"] == hashlib.sha256(independently_serialized).hexdigest()
        assert bundle.kernel == kernel_before
        assert finding.numbers == numbers_before
        reports.append(report)
    assert reports[0]["hash"] == reports[1]["hash"]
    assert canonical_bytes(reports[0]) == canonical_bytes(reports[1])

    report = reports[1]
    report["renders"][sid]["scene"]["native_diagnostics"]["pickup"]["path"]["legs"].clear()
    inspection_scene = report["renders"][sid]["inspections"][key]["scene"]
    inspection_scene["native_diagnostics"]["clearance"]["minimum"]["from_mm"][1] = 99
    inspection_scene["print_panels"][0]["label"] = "changed"
    assert bundle.kernel == kernel_before


def test_repeated_finding_publications_have_no_mutable_aliases():
    raw = {**_diagnostics(0), "other": [{"nested": [1.234567891]}]}
    finding = _finding(raw)
    before, citations = deepcopy(raw), list(finding.cite)
    first, second = finding.to_dict(), finding.to_dict()
    assert first["numbers"]["pickup"] == _expected_diagnostics()["pickup"]
    first["numbers"]["pickup"]["path"]["legs"][0]["components"][0]["swept_volume_mm3"] = 0
    first["numbers"]["other"][0]["nested"].append(99)
    first["cite"].append("not a source citation")
    assert finding.numbers == before
    assert finding.cite == citations
    assert second["numbers"]["pickup"] == _expected_diagnostics()["pickup"]
    assert second["numbers"]["other"] == [{"nested": [1.234567891]}]
    assert second["cite"] == ["synthetic native contract"]
    second["numbers"]["clearance"]["sweeps"].clear()
    second["cite"].clear()
    third = finding.to_dict()
    assert third["numbers"] == {**_expected_diagnostics(), "other": [{"nested": [1.234567891]}]}
    assert third["cite"] == citations
    assert finding.numbers == before


def test_authored_unrelated_and_unrecognized_values_remain_exact():
    raw = _diagnostics(0)
    raw["pickup"]["request"] = {
        "at_mm": [1.234567891, -1e-12],
        "tool_envelope": {"tip_dia_mm": 6.000000123},
    }
    raw["pickup"]["resolved_contact"]["point_mm"] = [1.234567891, -1e-12, 10]
    raw["pickup"]["path"]["legs"][0]["components"][0]["bbox_mm"] = [1.234567891]
    raw["unrelated"] = {"swept_volume_mm3": 4242.718684577403, "land_area_mm2": 41.12699574288723}
    published = publish_native_diagnostics(raw)
    assert published["pickup"]["request"] == raw["pickup"]["request"]
    assert published["pickup"]["resolved_contact"]["point_mm"] == [1.234567891, -1e-12, 10]
    for field in ("land_bbox_mm", "land_area_mm2", "footprint_area_mm2", "missing_land_area_mm2"):
        assert (
            published["pickup"]["resolved_contact"][field]
            == raw["pickup"]["resolved_contact"][field]
        )
    assert published["pickup"]["path"]["legs"][0]["components"][0]["bbox_mm"] == [1.234567891]
    assert published["unrelated"] == raw["unrelated"]
    unknown = _diagnostics(0)["pickup"]
    unknown["model"] = "future_pickup_v2"
    assert publish_native_diagnostics(unknown) == unknown
    unknown_contact = _diagnostics(0)["pickup"]
    unknown_contact["resolved_contact"]["contact_model"] = "future_projection_v2"
    assert (
        publish_native_diagnostics(unknown_contact)["resolved_contact"]
        == unknown_contact["resolved_contact"]
    )


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("model", "future_disk_v2"),
        ("source", "authored"),
        ("scope", "setup_only"),
        ("frame", "world"),
    ],
)
def test_clearance_projection_requires_all_native_identity_fields(field, replacement):
    raw = _diagnostics(0)["clearance"]
    raw[field] = replacement
    assert publish_native_diagnostics(raw) == raw


@pytest.mark.parametrize("variant", [0, 1])
def test_measured_uncovered_area_has_explicit_canonical_value(variant):
    raw = _diagnostics(variant)
    raw["pickup"]["resolved_contact"]["uncovered_area_mm2"] = _AREAS[variant][1]
    published = publish_native_diagnostics(raw)
    assert published["pickup"]["resolved_contact"]["uncovered_area_mm2"] == 41.126996
    assert raw["pickup"]["resolved_contact"]["uncovered_area_mm2"] == _AREAS[variant][1]


@pytest.mark.parametrize("case", ["patch_area", "patch_bbox"])
def test_raw_top_contact_boundary_is_classified_before_publication(tmp_path, case):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_selected_patch_proof(data, setup, (0.25, 4.75, 0.75, 5.25))
    pristine = deepcopy(proof)
    published_values = []
    for accepted in (False, True):
        proof.clear()
        proof.update(deepcopy(pristine))
        contact = proof["resolved_contact"]
        if case == "patch_area":
            # A microscopic omitted sliver of the 0.5 x 0.5 mm selected pad,
            # bracketing only the existing 1e-6 mm2 selected-land allowance.
            value = 0.2499990001 if accepted else 0.2499989999
            contact["patch_area_mm2"] = value
            assert (value + 1e-6 >= 0.25) is accepted
            field, expected_value = "patch_area_mm2", 0.249999
        else:
            # Trim only the pad's left edge, just inside/outside the existing
            # length allowance; account for the corresponding rectangular area.
            offset = LENGTH_TOLERANCE_MM + (-1e-10 if accepted else 1e-10)
            contact["patch_bbox_mm"][0] = 0.25 + offset
            contact["patch_area_mm2"] = (0.5 - offset) * 0.5
            assert (contact["patch_bbox_mm"][0] <= 0.25 + LENGTH_TOLERANCE_MM) is accepted
            field, expected_value = "patch_bbox_mm", None
        before = deepcopy(data.kernel)
        evidence = zero_pickup_evidence(data, setup, "z", normalized=normalized)
        expected_status = "pass" if accepted else "unknown"
        assert evidence["status"] == expected_status
        finding = _finding({"pickup": evidence}, status=evidence["status"])
        published = finding.to_dict()
        assert published["status"] == expected_status
        published_contact = published["numbers"]["pickup"]["resolved_contact"]
        if case == "patch_area":
            assert published_contact[field] == expected_value
        published_values.append(published_contact[field])
        assert data.kernel == before
        assert finding.numbers["pickup"]["resolved_contact"] == contact
        assert (
            zero_pickup_evidence(data, setup, "z", normalized=normalized)["status"]
            == expected_status
        )
    # The published diagnostic is identical, but must never replace the raw
    # operand and collapse the deliberately different safety classifications.
    assert published_values[0] == published_values[1]


def test_negative_tiny_uncovered_area_cannot_become_a_successful_zero(tmp_path):
    data, setup = proof_bundle(tmp_path)
    # The 3 mm-radius disk is tangent to x=0, wholly on the 20 x 10 mm
    # stock top. Thus zero uncovered area is geometrically plausible, and
    # changing only its sign isolates the strict nonnegative-area check.
    setup["zero"]["z"]["at_mm"] = [3.0, 5.0]
    normalized, proof = install_proof(data, setup)
    contact = proof["resolved_contact"]
    assert contact["footprint_area_mm2"] == contact["contact_area_mm2"]
    for uncovered, status in ((-1e-12, "unknown"), (0.0, "pass")):
        contact["uncovered_area_mm2"] = uncovered
        before = deepcopy(data.kernel)
        evidence = zero_pickup_evidence(data, setup, "z", normalized=normalized)
        assert evidence["status"] == status
        finding = _finding({"pickup": evidence}, status=status)
        published = finding.to_dict()
        assert published["status"] == status
        diagnostic = published["numbers"]["pickup"]["resolved_contact"]["uncovered_area_mm2"]
        assert diagnostic == 0.0
        assert math.copysign(1.0, diagnostic) == 1.0
        assert contact["uncovered_area_mm2"] == uncovered
        assert finding.numbers["pickup"]["resolved_contact"]["uncovered_area_mm2"] == uncovered
        assert data.kernel == before


@pytest.mark.parametrize(
    "invalid", [None, True, "unknown", float("nan"), float("inf"), float("-inf")]
)
def test_malformed_or_nonfinite_contact_is_not_published_as_known_success(tmp_path, invalid):
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_selected_patch_proof(data, setup)
    proof["resolved_contact"]["patch_area_mm2"] = invalid
    evidence = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert evidence["status"] == "unknown"
    published = _finding({"pickup": evidence}, status=evidence["status"]).to_dict()
    assert published["status"] == "unknown"
    value = published["numbers"]["pickup"]["resolved_contact"]["patch_area_mm2"]
    if isinstance(invalid, float) and not math.isfinite(invalid):
        assert not math.isfinite(value)
        with pytest.raises(ValueError):
            canonical_bytes(published)
    else:
        assert value == invalid
        assert type(value) is type(invalid)
    assert proof["resolved_contact"]["patch_area_mm2"] is invalid


def _numeric_leaves(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _numeric_leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _numeric_leaves(item, (*path, index))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield path


def test_validator_uses_independent_raw_findings_and_exact_publication(tmp_path, monkeypatch):
    validator = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/validate_examples.py")
    )
    checker_findings = validator["checker_findings"]
    data, setup = proof_bundle(tmp_path)
    normalized, proof = install_selected_patch_proof(data, setup)
    # Classify actual complete fixture inputs before injecting any diagnostic
    # pair. The checker receives its own raw Finding, never the report operand.
    evidence = zero_pickup_evidence(data, setup, "z", normalized=normalized)
    assert evidence["status"] == "pass"
    checker_raw = _diagnostics(1)
    checker_finding = _finding(checker_raw, status=evidence["status"])
    calls = []

    def load(plan_path):
        calls.append(("load", plan_path))
        return data

    def geometry(loaded):
        assert loaded is data
        calls.append(("geometry", loaded))

    class TinyRule:
        def evaluate(self, loaded):
            assert loaded is data
            calls.append(("evaluate", loaded))
            return [checker_finding]

    monkeypatch.setitem(checker_findings.__globals__, "load_bundle", load)
    monkeypatch.setitem(checker_findings.__globals__, "run_geometry", geometry)
    path = tmp_path / "independent-plan.toml"
    checked = checker_findings(path)
    rule = TinyRule()
    actual = checked(rule)["S1"]
    expected = {
        "rule": "native_publication",
        "subject": "S1",
        "status": "pass",
        "numbers": _expected_diagnostics(),
        "cite": ["synthetic native contract"],
        "message": "Raw classification precedes publication.",
    }
    assert actual == expected
    report = build_report(data, [_finding(_diagnostics(0))], assets={})
    assert canonical_bytes(report["findings"][0]) == canonical_bytes(expected)
    assert canonical_bytes(actual) == canonical_bytes(expected)
    assert [call[0] for call in calls] == ["load", "geometry", "evaluate"]
    assert calls[0][1] == path
    assert checked(rule)["S1"] == expected
    assert len(calls) == 3
    assert checker_finding.numbers == _diagnostics(1)
    assert proof["status"] == "pass"

    # Exact comparisons remain strict for every reported numeric leaf, including
    # canonical zeros and tiny positive scalar safety distances.
    for leaf in _numeric_leaves(expected["numbers"]):
        corrupted = deepcopy(report["findings"][0])
        owner = corrupted["numbers"]
        for part in leaf[:-1]:
            owner = owner[part]
        owner[leaf[-1]] += 0.000001
        assert corrupted != actual, leaf
        assert canonical_bytes(corrupted) != canonical_bytes(actual), leaf


@pytest.mark.parametrize("corruption", [None, "contact_area", "patch_bbox", "axis_set", "status"])
def test_zero_consumer_compares_publication_after_independent_raw_derivation(
    tmp_path, corruption
):
    validator = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/validate_examples.py")
    )
    data, setup = proof_bundle(tmp_path)
    _, proof = install_selected_patch_proof(data, setup)
    entries = validator["Entries"](data.inventory)
    own = validator["zero_inputs"](validator_test_bundle(data), lambda: deepcopy(data.kernel))
    status, raw = validator["derive_zero"](setup, own, entries)
    raw_before, kernel_before = deepcopy(raw), deepcopy(own.kernel)
    raw_contact = raw["axes"]["z"]["pickup_proof"]["resolved_contact"]
    assert raw_contact["contact_area_mm2"] == proof["resolved_contact"]["contact_area_mm2"]
    assert raw_contact["contact_area_mm2"] != round(raw_contact["contact_area_mm2"], 6)

    findings = zero_rule.evaluate(data)
    report = build_report(data, findings, assets={})
    finding = next(row for row in report["findings"] if row["subject"] == setup["id"])
    assert finding["status"] == status
    published_contact = finding["numbers"]["axes"]["z"]["pickup_proof"]["resolved_contact"]
    assert published_contact["contact_area_mm2"] == round(raw_contact["contact_area_mm2"], 6)
    # Before the consumer migration this fresh canonical finding was rejected:
    # the independently derived contact area still has its raw native precision.
    assert not validator["same_evidence"](finding["numbers"], raw)
    validator["check_zero"](setup, finding, entries, own)

    if corruption == "contact_area":
        published_contact["contact_area_mm2"] += 0.01
    elif corruption == "patch_bbox":
        published_contact["patch_bbox_mm"][0] += 0.01
    elif corruption == "axis_set":
        finding["numbers"]["axes"]["z"]["axis_set"] += 0.01
    elif corruption == "status":
        finding["status"] = "error" if status != "error" else "pass"
    if corruption is not None:
        with pytest.raises(ValueError):
            validator["check_zero"](setup, finding, entries, own)

    assert raw == raw_before
    assert own.kernel == kernel_before
    after_status, after_raw = validator["derive_zero"](setup, own, entries)
    assert after_status == status
    assert after_raw == raw_before
