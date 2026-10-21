"""Regression coverage for authored report validation against plan touch surfaces."""

import copy
import functools
import json
import math
import runpy
import tomllib
from dataclasses import replace
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from split_patch import patch_split, split_attr
from test_cli import copy_examples
from test_contour_order import carried_entry_bundle
from test_deep_hole_speed import DEEP, drill_bundle
from test_mounted_saw_zero import normalized_zero, prove_zero
from test_operative_surface import plan as surface_plan
from test_prepared_blank import synthetic_prep_geometry
from test_process_features import (
    set_process_key,
    set_tool_fact,
    shaft,
    synthetic_centre_tool,
    synthetic_shaft_cutting_geometry,
)
from test_sheet_fixture import END_MILL, MAKE_OP
from test_tool_change_touch import (
    carried_bbox_mill_bundle,
    carried_native_datum_bundle,
    carried_native_source_plane_bundle,
    carried_rectangular_source_plane_bundle,
    carried_rectangular_stock_bundle,
    carry_with_refaced_hole,
    carry_with_through_drill,
    measured_native_retouch_bundle,
)
from test_zero_opposed_midpoint import midpoint_bundle

from prechips.findings import Finding
from prechips.inputs import Bundle, load_bundle
from prechips.kernel import run_geometry, zero_pickup_inputs
from prechips.model import Inventory
from prechips.rules import (
    RULES,
    Rule,
    coordinates,
    headroom,
    indexing,
    joints,
    prepared_blank,
    speeds_feeds,
    stickout,
    tip_endpoints,
    tool_resolves,
)
from prechips.rules._bench import manual_bench
from prechips.rules.geometry_common import provenance
from prechips.rules.resolution import LENGTH_TOLERANCE_MM, inch_sizes, setup_items
from prechips.rules.tip_endpoints import evaluate as endpoint_findings
from prechips.rules.zero_recipe import native as zero_recipe_native
from prechips.rules.zero_recipe import rule as zero_recipe_rule
from prechips.rules.zero_recipe import tool_setting as zero_recipe_tool_setting

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))


def validator_test_bundle(data):
    """Keep loaded provenance intact; wrap only source-free synthetic test inputs."""
    if isinstance(data, Bundle):
        return data
    assert isinstance(data, SimpleNamespace)
    assert not any(hasattr(data, name) for name in ("paths", "hashes", "root"))
    assert not data.features.get("solids"), "Source solids require a loaded Bundle"
    return Bundle(
        plan=data.plan,
        features=data.features,
        inventory=data.inventory,
        policy=getattr(data, "policy", {}),
        cutting_data=getattr(data, "cutting_data", {}),
        paths={},
        hashes={},
        root=ROOT,
        kernel=getattr(data, "kernel", None),
    )


@pytest.mark.parametrize("setup_id", ["C1a", "E1a", "E1b"])
@pytest.mark.parametrize("mismatch", ["setup", "request"])
def test_zero_inputs_keeps_canonical_source_and_rejects_misbound_native_proof(setup_id, mismatch):
    """A registered member cannot borrow another setup's or request's native result."""
    bundle = load_bundle(ROOT / "examples" / "blondihacks-t-nuts" / "plan.toml")
    setup = next(item for item in bundle.plan["setups"] if item["id"] == setup_id)
    assert bundle.finished_feature_owners["retained-saw-end"] == "canonical-nut"
    assert set(bundle.workpiece_registrations) == {"nut1", "nut2", "nut3", "nut4"}
    own = VALIDATOR["zero_inputs"](bundle, lambda: {"status": "ok", "setups": {}})
    assert own.finished_feature_owners["retained-saw-end"] == "canonical-nut"
    requests = zero_pickup_inputs(own, setup)["requests"]
    assert requests
    citations = provenance(own, "zero_check", setup, setup["ops"][0], "retained-saw-end")
    assert f"kernel: STEP SHA-256 {bundle.hashes['step']}; FreeCAD B-rep measurements" in citations
    for citation in bundle.features["features"]["retained-saw-end"]["cite"]:
        assert citation in citations
    for key, request in requests.items():
        # Explicit test-owned native failure: matching matters even for collision errors.
        proof = {
            "model": request["model"],
            "setup_id": setup_id,
            "axis": request["axis"],
            "recipe_id": request["recipe_id"],
            "request": copy.deepcopy(request),
            "status": "error",
            "errors": ["test fixture: finder collides with this member's clamp"],
        }
        own.kernel["setups"][setup_id] = {"zero_pickups": {key: proof}}
        current = zero_recipe_native.zero_pickup_evidence(own, setup, key)
        assert current["status"] == "error"
        assert proof["errors"][0] in current["reasons"]
        if mismatch == "setup":
            proof["setup_id"] = "another-member-setup"
        else:
            # Keep the recipe digest unchanged: full request binding must also match.
            proof["request"]["at_mm"][0] += 1.0
        rejected = zero_recipe_native.zero_pickup_evidence(own, setup, key)
        assert "no matching native proof for the current pickup recipe" in rejected["reasons"]
        assert proof["errors"][0] not in rejected["reasons"]
        assert rejected["proof"] == {}
        assert rejected["resolved_contact"] == {}


def test_zero_inputs_recomputes_cached_tnut_ownership_and_rejects_pre_move_proof():
    bundle = load_bundle(ROOT / "examples" / "blondihacks-t-nuts" / "plan.toml")
    original_definitions = bundle.feature_definitions
    original_owners = bundle.finished_feature_owners
    original_registrations = bundle.workpiece_registrations
    setup = next(item for item in bundle.plan["setups"] if item["id"] == "E1a")
    original_pickups = zero_pickup_inputs(bundle, setup)
    plan, features = copy.deepcopy(bundle.plan), copy.deepcopy(bundle.features)
    plan["workpieces"]["nut1"]["pose"]["origin"][0] += 1.0
    features["features"]["test-source-alias"] = copy.deepcopy(
        features["features"]["retained-saw-end"]
    )
    changed = replace(bundle, plan=plan, features=features)
    own = VALIDATOR["zero_inputs"](changed, lambda: {"status": "ok", "setups": {}})
    assert "test-source-alias" not in original_definitions
    assert "test-source-alias" not in original_owners
    assert own.feature_definitions["test-source-alias"] == features["features"]["test-source-alias"]
    assert own.finished_feature_owners["test-source-alias"] == "canonical-nut"
    assert own.workpiece_registrations != original_registrations
    changed_setup = next(item for item in plan["setups"] if item["id"] == "E1a")
    changed_pickups = zero_pickup_inputs(own, changed_setup)
    assert changed_pickups["requests"]
    for key, request in original_pickups["requests"].items():
        assert changed_pickups["requests"][key]["recipe_id"] != request["recipe_id"]
        own.kernel["setups"]["E1a"] = {
            "zero_pickups": {
                key: {
                    "model": request["model"],
                    "setup_id": "E1a",
                    "axis": request["axis"],
                    "recipe_id": request["recipe_id"],
                    "request": copy.deepcopy(request),
                    "status": "error",
                    "errors": ["test fixture: collision at the old member pose"],
                }
            }
        }
        rejected = zero_recipe_native.zero_pickup_evidence(own, changed_setup, key)
        assert "no matching native proof for the current pickup recipe" in rejected["reasons"]
        assert "test fixture: collision at the old member pose" not in rejected["reasons"]
        assert rejected["proof"] == {}


def test_zero_inputs_rejects_report_native_plane_against_independent_geometry():
    """The report's usable datum cannot override an independently misbound native face."""
    # Both the primary pickup and later drill retouch need usable native land.
    # The oblique datum-only fixture cannot certify land after the spotting plunge.
    data = carried_rectangular_source_plane_bundle(source_grid=0.001)
    source = validator_test_bundle(data)
    setup = source.plan["setups"][-1]
    forged = zero_recipe_rule.evaluate(source)[-1].to_dict()
    assert forged["status"] == "pass"
    assert forged["numbers"]["axes"]["z"]["axis_set"] == 21.005
    face = setup["zero"]["z"]["face"]
    (ref,) = source.feature_definitions[face]["faces"]
    independent = copy.deepcopy(source.kernel)
    # The rectangular fixture resolves its flat native box through mapping[ref],
    # not features[face]. Rebind both to a declared cylindrical native face so the
    # receiving-plane check consumes genuinely different geometry.
    wrong_face = next(item for item in independent["faces"] if item["kind"] == "Cylinder")
    wrong_index = wrong_face["index"]
    assert wrong_index > 0
    assert source.kernel["mapping"][ref] != wrong_index
    assert wrong_face["kind"] == "Cylinder"
    assert wrong_face["bbox_mm"][2] < wrong_face["bbox_mm"][5]
    independent["mapping"][ref] = wrong_index
    independent["features"][face] = [wrong_index]
    own = VALIDATOR["zero_inputs"](source, lambda: independent)
    honest = zero_recipe_rule.evaluate(own)[-1].to_dict()
    assert honest["status"] == "unknown"
    assert honest["numbers"]["axes"]["z"]["axis_set"] == "unknown"
    entries = VALIDATOR["Entries"](source.inventory)
    VALIDATOR["check_zero"](setup, honest, entries, own)
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)
    # Downgrading the verdict alone cannot launder the report's numeric datum evidence.
    forged["status"] = honest["status"]
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("diameter", [0.1, 0.2, 0.5])
def test_zero_oracle_accepts_opposed_midpoint_without_a_finder_radius_offset(axis, diameter):
    data = midpoint_bundle(axis, center=12.5, jog=-2.5)
    data.inventory["tools"]["finder"]["tip_in"] = diameter
    setup, entries, own = zero_oracle(data)
    finding = zero_recipe_rule.evaluate(data)[0].to_dict()
    assert finding["status"] == "pass"
    row = finding["numbers"]["axes"][axis]
    assert [row[key] for key in ("axis_set", "check_reading", "mirrored_reading")] == [
        12.5,
        10.0,
        15.0,
    ]
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)
    for field in ("axis_set", "check_reading", "mirrored_reading"):
        forged = copy.deepcopy(finding)
        forged["numbers"]["axes"][axis][field] += diameter * 25.4 / 2
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, forged, entries, own)


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize(
    ("debt", "verdict"),
    [
        ("center", "unknown"),
        ("jog", "unknown"),
        ("finder-size", "unknown"),
        ("finder-rpm", "unknown"),
        ("finder-type", "unknown"),
        ("finder-verification", "unknown"),
        ("single-contact", "unknown"),
        ("swivel", "unknown"),
        ("wrong-axis", "error"),
        ("lathe", "error"),
        ("from", "error"),
        ("wrong-tool", "error"),
    ],
)
def test_zero_oracle_independently_refuses_unready_opposed_midpoint(axis, debt, verdict):
    data = midpoint_bundle(axis, center=12.5, jog=-2.5)
    setup = data.plan["setups"][0]
    recipe = setup["zero"][axis]
    finder = data.inventory["tools"]["finder"]
    if debt == "center":
        recipe["edge_mm"] = "unknown"
    elif debt == "jog":
        recipe["check_jog_mm"] = "unknown"
    elif debt == "finder-size":
        finder["tip_in"] = "unknown"
    elif debt == "finder-rpm":
        finder["rpm_range"] = "unknown"
    elif debt == "finder-type":
        finder["finder_type"] = "unknown"
    elif debt == "finder-verification":
        finder["verify"] = True
    elif debt == "single-contact":
        recipe["at_mm"] = [5, 8]
    elif debt == "swivel":
        data.inventory.setdefault("fixtures", {})["vise"] = {"kind": "vise"}
        setup["hold"] = {"fixture": "vise", "jaws_angle_deg": 30.0}
    elif debt == "wrong-axis":
        axis = "z"
        setup["zero"][axis]["method"] = "opposed_edge_midpoint"
    elif debt == "lathe":
        setup["machine"] = "lathe"
    elif debt == "from":
        recipe["from"] = f"-{axis}"
    elif debt == "wrong-tool":
        recipe["tool"] = "mill"
    setup, entries, own = zero_oracle(data)
    finding = zero_recipe_rule.evaluate(data)[0].to_dict()
    assert finding["status"] == verdict
    row = finding["numbers"]["axes"][axis]
    assert all(
        row[field] == "unknown" for field in ("axis_set", "check_reading", "mirrored_reading")
    )
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)
    forged = copy.deepcopy(finding)
    forged["status"] = "pass"
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)
    # An unchanged adverse verdict cannot launder numeric midpoint settings either.
    for field in ("axis_set", "check_reading", "mirrored_reading"):
        forged = copy.deepcopy(finding)
        forged["numbers"]["axes"][axis][field] = 12.5
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, forged, entries, own)


def test_validator_test_bundle_rejects_source_solids_without_real_provenance():
    synthetic = SimpleNamespace(features={"solids": {"part": "#15/MANIFOLD_SOLID_BREP[1]/"}})
    with pytest.raises(AssertionError, match="Source solids require a loaded Bundle"):
        validator_test_bundle(synthetic)


@pytest.mark.parametrize(
    "citation",
    [
        ["AUTHOR'S CHOICE"],
        "geometry-provenance.md: AUTHOR'S CHOICE local datum",
        ["geometry-provenance.md: AUTHOR'S CHOICE batch frame", "https://example.com/source"],
    ],
)
def test_authored_frame_provenance_is_carried_by_its_citation(citation):
    frame = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "binding": "nominal",
        "cite": citation,
        "note": "Establish the physical pickup before cutting.",
    }
    plan = {"frames": {"setup-frame": frame}}
    check = VALIDATOR["check_frames"]
    check({"frames": {}}, plan)
    frame["cite"] = []
    frame["note"] = "AUTHOR'S CHOICE"
    with pytest.raises(ValueError):
        check({"frames": {}}, plan)


def test_speed_oracle_preserves_unknown_cutting_collections_as_debt():
    data = drill_bundle()
    data.cutting_data.update(cut="unknown", deep_hole="unknown")
    finding, check = speed_finding(data)
    check()
    assert finding["status"] == "unknown"
    assert finding["numbers"]["rpm"] == "unknown"
    finding["numbers"]["rpm"] = 1500.0
    with pytest.raises(ValueError, match="RPM"):
        check()


def test_speed_oracle_keeps_authored_request_distinct_from_derated_recommendation():
    data = drill_bundle(depth_mm=40.0)
    data.plan["setups"][0]["ops"][0]["rpm"] = 380.5
    finding, check = speed_finding(data)
    row = finding["numbers"]
    # The 1/4-inch drill's 100 sfm is halved: 12*50/(pi*0.25) rounds to 750.
    assert finding["status"] == "pass"
    assert row["requested_rpm"] == 380.5
    assert row["computed_rpm"] == 750
    assert row["rpm"] == 380.5
    assert row["feed_mm_min"] == pytest.approx(380.5 * 2 * 0.05)
    assert row["rpm_basis"] == "authored"
    assert row["rpm_status"] == "pass"
    check()
    row.update(rpm=750, feed_mm_min=750 * 2 * 0.05)
    with pytest.raises(ValueError, match="RPM"):
        check()


@pytest.mark.parametrize("kind", ["mill", "lathe"])
@pytest.mark.parametrize("debt", ["cutting", "limits", "depth", "diameter", "tool", "machine"])
def test_speed_oracle_preserves_known_request_when_recommendation_is_unknown(kind, debt):
    data = drill_bundle(depth_mm=40.0)
    op = data.plan["setups"][0]["ops"][0]
    op["rpm"] = 450.0
    data.inventory["machines"]["mill"]["kind"] = kind
    if kind == "lathe":
        op["feed_mm_rev"] = 0.05
    if debt == "cutting":
        data.cutting_data["cut"] = "unknown"
    elif debt == "limits":
        data.inventory["machines"]["mill"]["spindle"]["rpm_min"] = "unknown"
    elif debt == "depth":
        del op["depth_mm"]
    elif debt == "diameter":
        data.inventory["tools"]["drill"]["dia_mm"] = "unknown"
    elif debt == "tool":
        data.inventory["tools"].clear()
    else:
        data.inventory["machines"].clear()
    finding, check = speed_finding(data)
    row = finding["numbers"]
    assert finding["status"] == "unknown"
    assert row["rpm_status"] == "unknown"
    assert row["requested_rpm"] == 450.0
    assert row["rpm"] == 450.0
    assert row["computed_rpm"] == "unknown"
    if kind == "lathe" and debt != "machine":
        assert row["feed_mm_min"] == pytest.approx(450.0 * 0.05)
    elif debt in {"cutting", "diameter", "tool"}:
        assert row["feed_mm_min"] == "unknown"
    else:
        assert row["feed_mm_min"] == pytest.approx(450.0 * 2 * 0.05)
    check()
    finding["status"] = row["rpm_status"] = "pass"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("requested", "spindle"),
    [
        (0, {"rpm_min": 50, "rpm_max": 3000}),
        (-10, {"rpm_min": 50, "rpm_max": 3000}),
        (49, {"rpm_min": 50, "rpm_max": "unknown"}),
        (3001, {"rpm_min": "unknown", "rpm_max": 3000}),
        (700, {"rpm_min": 50, "rpm_max": 3000, "ranges_rpm": [[50, 500], [1000, 3000]]}),
    ],
)
def test_speed_oracle_keeps_known_request_contradictions_dominant_over_cutting_debt(
    requested, spindle
):
    data = drill_bundle(depth_mm=5.0, deep=())
    data.plan["setups"][0]["ops"][0]["rpm"] = requested
    data.inventory["machines"]["mill"]["spindle"] = spindle
    data.cutting_data["cut"] = "unknown"
    finding, check = speed_finding(data)
    row = finding["numbers"]
    assert finding["status"] == "error"
    assert row["rpm_status"] == "error"
    assert row["requested_rpm"] == requested
    assert row["rpm"] == (requested if requested > 0 else "unknown")
    assert row["computed_rpm"] == "unknown"
    assert row["feed_mm_min"] == "unknown"
    check()
    finding["status"] = row["rpm_status"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("authored", [False, True])
@pytest.mark.parametrize("cutting_known", [False, True])
def test_speed_oracle_keeps_unknown_and_omitted_requests_on_their_own_paths(
    authored, cutting_known
):
    data = drill_bundle(depth_mm=5.0, deep=())
    if authored:
        data.plan["setups"][0]["ops"][0]["rpm"] = "unknown"
    if not cutting_known:
        data.cutting_data["cut"] = "unknown"
    finding, check = speed_finding(data)
    row = finding["numbers"]
    # The un-derated fixture computes 12*100/(pi*0.25), rounded to 1550.
    recommended = 1550 if cutting_known else "unknown"
    effective = "unknown" if authored else recommended
    status = "pass" if cutting_known and not authored else "unknown"
    assert finding["status"] == status
    assert row["rpm"] == effective
    assert row["feed_mm_min"] == (155.0 if status == "pass" else "unknown")
    if authored:
        assert row["requested_rpm"] == "unknown"
        assert row["computed_rpm"] == recommended
        assert row["rpm_status"] == "unknown"
    else:
        authored_fields = {
            "requested_rpm",
            "computed_rpm",
            "rpm_basis",
            "rpm_status",
            "rpm_reason",
        }
        assert not authored_fields & row.keys()
    check()
    wrong_rpm = 1500 if status == "pass" else 1550
    row.update(rpm=wrong_rpm, feed_mm_min=wrong_rpm * 2 * 0.05)
    with pytest.raises(ValueError, match="RPM"):
        check()


@pytest.mark.parametrize(
    ("field", "corruption"),
    [
        ("requested_rpm", 380.0),
        ("computed_rpm", 1550),
        ("rpm_basis", "computed"),
        ("rpm_status", "unknown"),
        ("rpm_reason", ""),
    ],
)
def test_speed_oracle_checks_authored_rpm_evidence_against_inputs(field, corruption):
    data = drill_bundle(depth_mm=40.0)
    data.plan["setups"][0]["ops"][0]["rpm"] = 380.5
    finding, check = speed_finding(data)
    check()
    finding["numbers"][field] = corruption
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    "field", ["requested_rpm", "computed_rpm", "rpm_basis", "rpm_status", "rpm_reason"]
)
def test_speed_oracle_requires_even_unknown_authored_rpm_evidence(field):
    data = drill_bundle(depth_mm=5.0, deep=())
    data.plan["setups"][0]["ops"][0]["rpm"] = "unknown"
    data.cutting_data["cut"] = "unknown"
    finding, check = speed_finding(data)
    check()
    del finding["numbers"][field]
    with pytest.raises(ValueError):
        check()


def test_subject_oracle_allows_unknown_limits_without_invented_decimal_precision():
    # This example intentionally has no published acceptance limits. T-nut's now
    # authored numeric bands must not define the unknown-limit contract.
    folder = ROOT / "examples" / "blondihacks-brass-ring"
    data = load_bundle(folder / "plan.toml")
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    check = VALIDATOR["check_subjects"]
    check(data.plan, data.features, findings, data.inventory)
    feature = data.features["features"]["back-face"]
    assert feature["length"] == "unknown"
    assert not isinstance(feature.get("precision"), dict)
    feature["length"] = [2.49, 2.59]
    with pytest.raises(ValueError, match="back-face: per-dimension precision"):
        check(data.plan, data.features, findings, data.inventory)


@pytest.mark.parametrize("location", ["stock", "feature", "operation"])
@pytest.mark.parametrize(
    "reference",
    [
        "#42/ADVANCED_FACE[1]/O'Brien",
        "#99/ADVANCED_FACE[1]/O'Brien",
        "#42/ADVANCED_FACE[2]/O'Brien",
        "#42/ADVANCED_FACE[1]/OTHER",
        "ADVANCED_FACE[1]",
    ],
)
def test_bound_step_face_identity_checks_every_authored_claim(tmp_path, location, reference):
    step = tmp_path / "part.STEP"
    step.write_text("#42 = ADVANCED_FACE('O''Brien', (), #1, .T.);", encoding="utf-8")
    plan = {"stock": {}, "setups": [{"ops": [{}]}]}
    features = {"features": {"base": {}}}
    target = {
        "stock": plan["stock"],
        "feature": features["features"]["base"],
        "operation": plan["setups"][0]["ops"][0],
    }[location]
    target["as_is_faces" if location == "stock" else "faces"] = [reference]
    validate = VALIDATOR["check_step_face_references"]
    if reference == "#42/ADVANCED_FACE[1]/O'Brien":
        validate(step, plan, features)
    else:
        with pytest.raises(ValueError, match="(?:face reference|face ordinal)"):
            validate(step, plan, features)


@pytest.mark.parametrize("corruption", ["construction", "cutting_speed"])
def test_standalone_validator_rejects_semantic_report_mutations(
    tmp_path, monkeypatch, pilot_kernel_cache, corruption
):
    """Valid report hashes do not excuse evidence that contradicts authored inputs."""
    examples = copy_examples(tmp_path, mode="with-expected")
    case = VALIDATOR["STANDALONE_CASES"][0]
    folder = examples / case[0]
    pilot_kernel_cache(folder / case[1])
    validate = VALIDATOR["validate_standalone_fixture"]
    namespace = validate.__globals__
    original = namespace["read_report"]

    def corrupted_report(path):
        report = original(path)
        if corruption == "construction":
            row = next(row for row in report["findings"] if row["rule"] == "construction")
            row["numbers"]["plan_construction"] = "invented-construction"
        else:
            row = next(
                row
                for row in report["findings"]
                if row["rule"] == "speeds_feeds" and "sfm" in row["numbers"]
            )
            row["numbers"]["sfm"] = 123456.0
        return report

    monkeypatch.setitem(namespace, "EXAMPLES", examples)
    monkeypatch.setitem(namespace, "ROOT", examples.parent)
    validate(case)
    # Mutate after canonical/hash parsing: this regression exercises the independent
    # semantic checks, rather than merely proving the report checksum detects edits.
    monkeypatch.setitem(namespace, "read_report", corrupted_report)
    rejected_by = (
        "construction evidence" if corruption == "construction" else r"(?:sfm|saw row speed)"
    )
    with pytest.raises(ValueError, match=rejected_by):
        validate(case)


@pytest.mark.parametrize("verification_debt", [False, True])
@pytest.mark.parametrize("kind", ["slitting_saw", "unknown"])
def test_mounted_saw_zero_debt_cannot_be_waived(verification_debt, kind):
    data = drill_bundle()
    setup = data.plan["setups"][0]
    setup["ops"] = [{"op": 10, "do": "cut_off", "tool": "disk", "holder": "arbor"}]
    data.inventory["tools"]["disk"] = {
        "kind": kind,
        "verify": verification_debt,
    }
    finding = zero_recipe_rule.evaluate(data)[0].to_dict()
    entries = VALIDATOR["Entries"](data.inventory)
    VALIDATOR["check_zero"](setup, finding, entries, data)
    assert finding["status"] == "unknown"
    finding["status"] = "not_applicable"
    with pytest.raises(ValueError, match="mounted.*zero"):
        VALIDATOR["check_zero"](setup, finding, entries, data)


def mounted_zero_oracle_case(monkeypatch, *, kind="axis", side="minus_z", offset=0.0):
    """Authored facts plus a separate complete native contact/approach fixture."""
    data, setup, mounted = normalized_zero(monkeypatch)
    data.inventory["tools"]["blade"].update(
        thickness_mm=synthetic_fact(3.05),
        kerf_offset_mm=synthetic_fact(offset),
        kerf_mm=synthetic_fact(4.0),
    )
    data.inventory.setdefault("holders", {})["holder"] = {"kind": "slitting_saw_arbor"}
    touch = mounted["zero"]["touches"][0]
    touch["check_jog_mm"] = "unknown"
    touch["mounted_saw"]["blade_side"] = side
    setup["zero"]["tool_touches"][0]["mounted_saw"]["blade_side"] = side
    mounted["blade"]["kerf_offset_mm"] = offset
    if kind == "axis":
        touch.update(kind="axis", position=0, check_jog_mm=5)
        touch.pop("before_ops")
        setup["ops"] = [setup["ops"][-1]]
        setup["zero"]["z"].update(
            tool="blade",
            holder="holder",
            method="mounted_saw_side",
            mounted_saw=copy.deepcopy(touch["mounted_saw"]),
            check_jog_mm=5,
        )
        setup["zero"]["tool_touches"] = []
    proof = prove_zero(data, mounted)
    sense = 1 if side == "minus_z" else -1
    expected = 10 + sense * (0.05 + 3.05 / 2) + offset
    proof.update(
        blade_side=side,
        surface_side="+z" if sense == 1 else "-z",
        plane_normal_z=sense,
        kerf_offset_mm=offset,
        body_face_z_mm=10 + sense * 0.05,
        cutting_midplane_z_mm=expected,
        approach_start_z_mm=expected + sense * 5,
        approach_end_z_mm=expected,
    )
    finding = zero_recipe_rule.evaluate(data)[0].to_dict()
    _, entries, own = zero_oracle(data)
    return data, setup, finding, entries, own, expected


@pytest.mark.parametrize("kind", ["axis", "tool"])
@pytest.mark.parametrize("side,offset", [("minus_z", 0.0), ("plus_z", 0.0), ("minus_z", 0.2)])
def test_supported_mounted_zero_uses_body_side_not_kerf(monkeypatch, kind, side, offset):
    _, setup, finding, entries, own, expected = mounted_zero_oracle_case(
        monkeypatch, kind=kind, side=side, offset=offset
    )
    assert finding["status"] == "pass"
    VALIDATOR["check_zero"](setup, finding, entries, own)
    row = finding["numbers"]["mounted_saw_settings"]["20"]
    assert row["axis_set_mm"] == pytest.approx(expected)
    assert row["mounted_saw_setting"]["body_thickness_mm"] == 3.05
    assert finding["numbers"]["spindle_saw_debt"] == ""
    if kind == "axis":
        axis = finding["numbers"]["axes"]["z"]
        assert axis["check_reading"] == pytest.approx(expected + 5)
        assert axis["mirrored_reading"] == pytest.approx(expected - 5)
    else:
        assert finding["numbers"]["axes"]["z"]["axis_set"] == pytest.approx(10.05)
        assert finding["numbers"]["tool_touches"][0]["z_axis_set"] == pytest.approx(expected)
    finding["status"] = "not_applicable"
    with pytest.raises(ValueError, match="mounted.*zero"):
        VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize("kind", ["axis", "tool"])
@pytest.mark.parametrize(
    "mutation",
    [
        "kerf_arithmetic",
        "paper",
        "body",
        "side",
        "tool",
        "holder",
        "stopped",
        "native",
        "drop_setting",
    ],
)
def test_mounted_zero_rejects_report_operand_and_proof_mutations(monkeypatch, kind, mutation):
    _, setup, finding, entries, own, _ = mounted_zero_oracle_case(monkeypatch, kind=kind)
    VALIDATOR["check_zero"](setup, finding, entries, own)
    row = finding["numbers"]["mounted_saw_settings"]["20"]
    if mutation == "kerf_arithmetic":
        row.update(axis_set_mm=12.05, z_axis_set=12.05)
        row["mounted_saw_setting"]["axis_set_mm"] = 12.05
        if kind == "axis":
            finding["numbers"]["axes"]["z"].update(
                axis_set=12.05,
                check_reading=17.05,
                mirrored_reading=7.05,
            )
        else:
            finding["numbers"]["tool_touches"][0]["z_axis_set"] = 12.05
    elif mutation in {"paper", "body", "side"}:
        key, value = {
            "paper": ("paper_mm", 0.0),
            "body": ("body_thickness_mm", 4.0),
            "side": ("blade_side", "plus_z"),
        }[mutation]
        row["mounted_saw_setting"][key] = value
    elif mutation in {"tool", "holder"}:
        row[mutation] = f"{mutation}s.some-other-item"
    elif mutation == "stopped":
        row["mounted_saw"]["spindle_state"] = "running"
    elif mutation == "native":
        row["proof"]["zero"]["touches"][0]["collisions"] = ["arbor"]
    else:
        del finding["numbers"]["mounted_saw_settings"]
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize("mutation", ["paper", "side", "tool", "holder", "stopped", "body"])
def test_mounted_checker_helper_cannot_define_authored_contact_oracle(monkeypatch, mutation):
    data, setup, finding, entries, _, _ = mounted_zero_oracle_case(monkeypatch)
    original = zero_recipe_tool_setting.mounted_saw_settings
    frozen = copy.deepcopy(original(data, setup))
    # Keep both the checker and the report self-consistent with old contact facts.
    # Independent source selection/measurements must still reject them.
    monkeypatch.setattr(
        zero_recipe_tool_setting,
        "mounted_saw_settings",
        lambda *args, **kwargs: copy.deepcopy(frozen),
    )
    recipe = setup["zero"]["z"]
    if mutation == "paper":
        recipe["paper_mm"] = 0.2
    elif mutation == "side":
        recipe["mounted_saw"]["blade_side"] = "plus_z"
    elif mutation in {"tool", "holder"}:
        recipe[mutation] = "other"
    elif mutation == "stopped":
        recipe["mounted_saw"]["spindle_state"] = "running"
    else:
        data.inventory["tools"]["blade"]["thickness_mm"] = synthetic_fact(4.0)
    _, entries, own = zero_oracle(data)
    with pytest.raises(ValueError, match="mounted zero"):
        VALIDATOR["check_zero"](setup, finding, entries, own)


def test_mounted_zero_normalizes_authored_inch_contact_before_body_compensation(monkeypatch):
    data, setup, _, entries, _, expected = mounted_zero_oracle_case(monkeypatch)
    data.features["units"] = "in"
    for field in ("edge_mm", "paper_mm", "check_jog_mm"):
        setup["zero"]["z"][field] /= 25.4
    _, _, own = zero_oracle(data)
    row = VALIDATOR["mounted_zero_settings"](setup, own, entries)["20"]
    assert row["axis_set_mm"] == pytest.approx(expected)
    assert row["z_axis_set"] == pytest.approx(expected / 25.4)


def sheet_disclosure_fixture(
    tmp_path, *, status="unknown", detail="pro", grouped=True, rule="accessibility", prose=None
):
    """Small real HTML contract, with visible debt separate from identity metadata."""
    subjects = ["D1a:30", "D1b:30"] if grouped else ["D1a:30"]
    findings = [
        {"rule": rule, "subject": subject, "status": status, "numbers": {}} for subject in subjects
    ]
    report = {"hash": "synthetic-bound-report", "findings": findings}
    kind = "block" if status == "error" else "caution"
    evidence = [
        {"source": row["rule"], "status": status, "scope": row["subject"], "kind": kind}
        for row in findings
    ]
    owners = [
        {"setup_id": subject.split(":")[0], "op_id": 30, "workpiece": f"nut{index + 1}"}
        for index, subject in enumerate(subjects)
    ]
    if prose is None:
        prose = (
            "Tool or holder collides with the part; STOP."
            if status == "error"
            else ("Claimed face references are unknown or unmapped.")
        )
    decision = (
        f'<div class="decision {"stop" if status == "error" else "caution"}" '
        f'data-decision="{kind}" data-source="{rule}" data-status="{status}" '
        f'data-scope="D1a:30" data-decision-evidence="{escape(json.dumps(evidence))}" '
        f'data-physical-ops="{escape(json.dumps(owners))}"><p>{prose}</p></div>'
    )
    html = (
        "<!doctype html><html><head>"
        f'<meta name="prechips-report" content="{report["hash"]}">'
        "<style>@page { size: Letter; }</style></head>"
        f'<body data-detail="{detail}"><p>PLANNED — NOT APPROVED</p>'
        '<section data-setup-id="D1a"><h2>D1a–D1b</h2>'
        "<p>Op 30: hand-wrench tap.</p>" + decision + "</section></body></html>"
    )
    folder = tmp_path / "expected"
    folder.mkdir(exist_ok=True)
    path = folder / "traveler.html"
    path.write_text(html, encoding="utf-8")
    return report, path, html, decision


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("status", ["unknown", "error"])
def test_sheet_accepts_visible_semantic_grouped_disclosure_without_status_glyphs(
    tmp_path, detail, status
):
    report, _, html, _ = sheet_disclosure_fixture(tmp_path, detail=detail, status=status)
    assert "?" not in html and "✗" not in html
    VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize(
    "prose",
    [
        "a claimed internal corner is smaller than the selected cutter radius.",
        "The 0.997 mm corner radius is smaller\nthan the 4 mm cutter radius.",
    ],
)
def test_sheet_accepts_owned_visible_failure_comparison(tmp_path, detail, prose):
    report, _, _, _ = sheet_disclosure_fixture(
        tmp_path,
        detail=detail,
        status="error",
        rule="internal_corner_radius",
        prose=prose,
    )
    VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize(
    "prose",
    [
        "We need a measured holder envelope before releasing this operation.",
        "This pickup needs a repeatable contact measurement.",
        "The supported contact height must be known before machining.",
    ],
)
@pytest.mark.parametrize(
    "mutation", ["none", "neutral", "empty", "clear", "hidden", "script", "wrong_owner"]
)
def test_sheet_outstanding_obligations_require_visible_owned_modern_debt(
    tmp_path, detail, prose, mutation
):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, detail=detail, prose=prose)
    VALIDATOR["check_sheet"](tmp_path, report)
    if mutation == "none":
        return
    if mutation in {"neutral", "empty", "clear"}:
        replacement = {
            "neutral": "The selected holder envelope is 4 mm.",
            "empty": "",
            "clear": "All clear; the contact height must be known.",
        }[mutation]
        altered = decision.replace(f"<p>{prose}</p>", f"<p>{replacement}</p>")
    elif mutation == "hidden":
        altered = f"<div hidden>{decision}</div>"
    elif mutation == "script":
        altered = f'<script type="text/plain">{decision}</script>'
    else:
        altered = decision.replace(
            "&quot;setup_id&quot;: &quot;D1b&quot;",
            "&quot;setup_id&quot;: &quot;D1c&quot;",
        )
    path.write_text(html.replace(decision, altered), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "rule,subject,numbers",
    [
        ("sizing", "back-face", {}),
        ("op_chain", "back-face", {}),
        ("blind_depth", "back-face", {}),
        ("datum_consistency", "back-face", {}),
        ("inspection", "nut1/back-face:length", {}),
        (
            "inspection",
            "nut1/back-face:length",
            {
                "identity": {
                    "feature_owner": "back-face",
                    "requirement": "length",
                    "workpiece": "nut1",
                }
            },
        ),
    ],
)
@pytest.mark.parametrize("mutation", ["none", "source", "status", "scope", "kind"])
def test_sheet_grouped_secondary_nonphysical_debt_keeps_exact_evidence(
    tmp_path, rule, subject, numbers, mutation
):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path)
    original_evidence = [
        {"source": "accessibility", "status": "unknown", "scope": scope, "kind": "caution"}
        for scope in ("D1a:30", "D1b:30")
    ]
    report["findings"][1].update(rule=rule, subject=subject, numbers=numbers)
    evidence = copy.deepcopy(original_evidence)
    evidence[1].update(source=rule, scope=subject)
    grouped = decision.replace(escape(json.dumps(original_evidence)), escape(json.dumps(evidence)))
    # Only D1a/D1b physical owners exist; neither is this feature/inspection identity.
    # The primary attributes still describe accessibility:D1a:30, not the secondary.
    path.write_text(html.replace(decision, grouped), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)
    if mutation == "none":
        return
    evidence[1][mutation] = {
        "source": "finish_coverage",
        "status": "pass",
        "scope": "nut2/front-face:length",
        "kind": "info",
    }[mutation]
    altered = decision.replace(escape(json.dumps(original_evidence)), escape(json.dumps(evidence)))
    path.write_text(html.replace(decision, altered), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("rule", ["accessibility", "inspection"])
def test_sheet_grouped_secondary_physical_op_cannot_bypass_owner_gate(tmp_path, rule):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path)
    original_evidence = [
        {"source": "accessibility", "status": "unknown", "scope": scope, "kind": "caution"}
        for scope in ("D1a:30", "D1b:30")
    ]
    report["findings"][1].update(rule=rule, subject="S1:10")
    if rule == "inspection":
        report["findings"][1]["numbers"] = {
            "identity": {
                "feature_owner": "back-face",
                "requirement": "length",
                "workpiece": "nut1",
            }
        }
    evidence = copy.deepcopy(original_evidence)
    evidence[1].update(source=rule, scope="S1:10")
    owners = [
        {"setup_id": "D1a", "op_id": 30, "workpiece": "nut1"},
        {"setup_id": "S1", "op_id": 10, "workpiece": "nut2"},
    ]
    original_owners = [
        {"setup_id": sid, "op_id": 30, "workpiece": f"nut{index + 1}"}
        for index, sid in enumerate(("D1a", "D1b"))
    ]
    grouped = decision.replace(
        escape(json.dumps(original_evidence)), escape(json.dumps(evidence))
    ).replace(escape(json.dumps(original_owners)), escape(json.dumps(owners)))
    path.write_text(html.replace(decision, grouped), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)
    altered = grouped.replace(
        "&quot;setup_id&quot;: &quot;S1&quot;",
        "&quot;setup_id&quot;: &quot;S2&quot;",
    )
    path.write_text(html.replace(decision, altered), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "status,rule,prose",
    [
        pytest.param("unknown", "accessibility", None, id="unknown"),
        pytest.param("error", "accessibility", None, id="error"),
        pytest.param(
            "error",
            "internal_corner_radius",
            "The corner radius is smaller than the selected cutter radius.",
            id="failure-comparison",
        ),
    ],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "clear",
        "neutral",
        "script",
        "hidden",
        "aria",
        "inline_css",
        "class_css",
        "drop_evidence",
        "wrong_subject",
        "drop_owner",
        "wrong_op",
        "cleared_status",
    ],
)
def test_sheet_rejects_hidden_cleared_or_unassociated_disclosures(
    tmp_path, status, rule, prose, mutation
):
    report, path, html, decision = sheet_disclosure_fixture(
        tmp_path, status=status, rule=rule, prose=prose
    )
    VALIDATOR["check_sheet"](tmp_path, report)
    if mutation in {"empty", "clear", "neutral"}:
        start, end = decision.index("<p>"), decision.index("</p>")
        replacement = {
            "empty": "",
            "clear": "<p>All clear; proceed.</p>",
            "neutral": "<p>The selected cutter radius is 4 mm.</p>",
        }[mutation]
        altered = decision[:start] + replacement + decision[end + 4 :]
    elif mutation == "script":
        altered = f'<script type="text/plain">{decision}</script>'
    elif mutation in {"hidden", "aria", "inline_css", "class_css"}:
        opening = {
            "hidden": "<div hidden>",
            "aria": '<div aria-hidden="true">',
            "inline_css": '<div style="display: none">',
            "class_css": '<style>.concealed { visibility: hidden; }</style><div class="concealed">',
        }[mutation]
        altered = opening + decision + "</div>"
    elif mutation == "drop_evidence":
        altered = decision.replace(
            escape(
                json.dumps(
                    {
                        "source": rule,
                        "status": status,
                        "scope": "D1b:30",
                        "kind": "block" if status == "error" else "caution",
                    }
                )
            ),
            "",
        )
    elif mutation == "wrong_subject":
        altered = decision.replace("D1b:30", "D1c:30")
    elif mutation == "drop_owner":
        altered = decision.replace(
            "&quot;setup_id&quot;: &quot;D1b&quot;",
            "&quot;setup_id&quot;: &quot;D1c&quot;",
        )
    elif mutation == "wrong_op":
        altered = decision.replace("&quot;op_id&quot;: 30", "&quot;op_id&quot;: 20")
    else:
        altered = decision.replace(f'"{status}"', '"pass"').replace(
            f"&quot;status&quot;: &quot;{status}&quot;", "&quot;status&quot;: &quot;pass&quot;"
        )
    path.write_text(html.replace(decision, altered), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "selector,wrapper,extra_class,visible",
    [
        (".pro .decision", '<div class="pro">', "", False),
        (".pro .decision", '<div class="hobby">', "", True),
        ("body[data-detail='pro'] .decision", "<div>", "", False),
        ("body[data-detail='hobby'] .decision", "<div>", "", True),
        (".pro > .decision", '<div class="pro">', "", False),
        (".pro > .decision", '<div class="pro"><div>', "", True),
        (".decision:not(.shown)", "<div>", "", False),
        (".decision:not(.shown)", "<div>", "shown", True),
        (".decision:not([data-status='error'])", "<div>", "", False),
        (".decision:not([data-status='unknown'])", "<div>", "", True),
        (".unrelated, .pro > .decision", '<div class="pro">', "", False),
        (".unrelated, .hobby > .decision", '<div class="pro">', "", True),
        ("/* print debt */ .decision", "<div>", "", False),
        ("/* print debt */ .unrelated", "<div>", "", True),
        # Unsupported predicates/relationships retain the subject's known scope,
        # rather than supplying false visibility or hiding every unrelated node.
        (".decision:hover", "<div>", "", False),
        (".unrelated:hover", "<div>", "", True),
        (".decision:not(:hover)", "<div>", "", False),
        (".unrelated + .decision", "<div>", "", False),
        (".decision + .unrelated", "<div>", "", True),
    ],
)
@pytest.mark.parametrize("declaration", ["display: none", "visibility: hidden"])
def test_sheet_css_disclosure_visibility_respects_selector_scope(
    tmp_path, selector, wrapper, extra_class, visible, declaration
):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path)
    altered = decision.replace('class="decision ', f'class="decision {extra_class} ')
    closing = "</div>" * wrapper.count("<div")
    html = html.replace(
        decision, f"<style>{selector} {{ {declaration}; }}</style>{wrapper}{altered}{closing}"
    )
    path.write_text(html, encoding="utf-8")
    if visible:
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("status", ["unknown", "error"])
def test_sheet_accepts_scoped_pedantic_legacy_status_boxes(tmp_path, status):
    report, path, html, decision = sheet_disclosure_fixture(
        tmp_path, status=status, detail="pedantic", grouped=False
    )
    legacy = (
        '<div class="stop"><p>✗ STOP — do not run until resolved:</p>'
        "<p>Op 30 — tool or holder hits the part.</p></div>"
        if status == "error"
        else '<div class="unverified"><p>? Not verified by the planner:</p>'
        "<p>Tool access (op 30).</p></div>"
    )
    path.write_text(html.replace(decision, legacy), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)
    path.write_text(html.replace(decision, legacy.replace("30", "20")), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("proof_state", ["missing", "unknown", "error"])
def test_supported_mounted_zero_retains_real_native_contact_debt(monkeypatch, proof_state):
    data, setup, _, _, _, _ = mounted_zero_oracle_case(monkeypatch)
    saw = data.kernel["ops"]["S1:20"]["saw"]
    if proof_state == "missing":
        del saw["zero"]
    else:
        saw["zero"].update(status=proof_state, reasons=["contact/approach not established"])
    finding = zero_recipe_rule.evaluate(data)[0].to_dict()
    _, entries, own = zero_oracle(data)
    assert finding["status"] == ("error" if proof_state == "error" else "unknown")
    assert finding["numbers"]["mounted_saw_settings"]["20"]["z_axis_set"] == "unknown"
    VALIDATOR["check_zero"](setup, finding, entries, own)
    finding["status"] = "pass"
    with pytest.raises(ValueError, match="mounted.*zero"):
        VALIDATOR["check_zero"](setup, finding, entries, own)


def test_proved_mounted_setting_does_not_clear_an_ordinary_reversed_axis(monkeypatch):
    data, setup, _, _, _, _ = mounted_zero_oracle_case(monkeypatch, kind="tool")
    data.plan["dro"]["direction"]["x"] = "left"
    finding = zero_recipe_rule.evaluate(data)[0].to_dict()
    _, entries, own = zero_oracle(data)
    assert finding["status"] == "error"
    VALIDATOR["check_zero"](setup, finding, entries, own)
    finding["status"] = "pass"
    with pytest.raises(ValueError, match="zero verdict"):
        VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize("corruption", ["numeric", "wrong_feature", "wrong_requirement", "hidden"])
def test_legacy_unknown_requirement_cells_remain_visibly_feature_scoped(tmp_path, corruption):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {"rule": "inspection", "subject": "back-face:length", "status": "unknown", "numbers": {}}
    ]
    table = "<table><tr><td>back-face</td><td>length ?; thickness 2</td></tr></table>"
    path.write_text(html.replace(decision, table), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)
    altered = {
        "numeric": table.replace("length ?", "length 2"),
        "wrong_feature": table.replace("back-face", "front-face"),
        "wrong_requirement": table.replace("length ?", "radius ?"),
        "hidden": "<div hidden>" + table + "</div>",
    }[corruption]
    path.write_text(html.replace(decision, altered), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "detail,criterion",
    [
        (
            "pro",
            '<div class="route-inspection"><p>caliper: ? cone boss north face '
            "length 41.50–42.52 mm</p></div>",
        ),
        (
            "hobby",
            '<div class="route-inspection"><p>caliper: ? cone boss north face '
            "length 41.50–42.52 mm</p></div>",
        ),
        (
            "pedantic",
            '<table><tr class="inspection-record"><td>cone boss north face — '
            "? length 41.50–42.52 : caliper</td></tr></table>",
        ),
    ],
)
def test_sheet_accepts_current_unknown_inspection_criterion(tmp_path, detail, criterion):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, detail=detail, grouped=False)
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": "cone_boss_north_face:length",
            "status": "unknown",
            "numbers": {},
        }
    ]
    path.write_text(html.replace(decision, criterion), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "feature,requirement,prose",
    [
        ("body-length", "length", "? body-length 41.50–42.52"),
        ("cap-head-length", "length", "? cap-head-length 41.50–42.52"),
        ("cone_socket", "dia", "? cone socket, crank socket Ø 12.0–12.1"),
        ("crank_socket", "dia", "? cone socket, crank socket Ø 12.0–12.1"),
        ("cone_socket", "dia", "cone socket, crank socket — ? Ø 12.0–12.1 : caliper"),
        ("crank_socket", "dia", "cone socket, crank socket — ? Ø 12.0–12.1 : caliper"),
        ("back-face", "length", "back-face — ? length ? : no gauge chosen"),
    ],
)
def test_sheet_inspection_accepts_complete_current_owner_headings(
    tmp_path, feature, requirement, prose
):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    subject = f"{feature}:{requirement}"
    report["findings"] = [
        {"rule": "inspection", "subject": subject, "status": "unknown", "numbers": {}}
    ]
    criterion = (
        f'<span class="inspection-criterion" data-inspection-ids="{escape(json.dumps([subject]))}">'
        f"{prose}</span>"
    )
    path.write_text(html.replace(decision, criterion), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("presentation", ["span", "pedantic"])
@pytest.mark.parametrize(
    "feature,requirement,prose",
    [
        (
            "body-length",
            "seam_limit",
            "body-length — ? seam limit (no drawing limit): no gauge chosen",
        ),
        ("thread", "thread_class", "thread — ? thread class UNC-2A: thread gauge"),
        ("seat", "finish_ra", "seat — ? Ra smooth: roughness comparator"),
    ],
)
def test_sheet_inspection_accepts_absent_and_string_specifications(
    tmp_path, presentation, feature, requirement, prose
):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    subject = f"{feature}:{requirement}"
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": subject,
            "status": "unknown",
            "numbers": {
                "identity": {
                    "feature_owner": feature,
                    "requirement": requirement,
                    "workpiece": None,
                }
            },
        }
    ]
    ids = escape(json.dumps([subject]))
    criterion = (
        f'<span class="inspection-criterion" data-inspection-ids="{ids}">{prose}</span>'
        if presentation == "span"
        else f'<table><tr class="inspection-message"><td>{prose}</td></tr></table>'
    )
    path.write_text(html.replace(decision, criterion), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("presentation", ["span", "pedantic"])
def test_sheet_inspection_rejects_longer_requirement_registered_by_sibling(tmp_path, presentation):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    subject = "end:length"
    report["findings"] = [
        {"rule": "inspection", "subject": subject, "status": "unknown", "numbers": {}},
        {
            "rule": "inspection",
            "subject": "other:length_overall",
            "status": "pass",
            "numbers": {},
        },
    ]
    prose = "end — ? length overall 5"
    criterion = (
        f'<span class="inspection-criterion" '
        f'data-inspection-ids="{escape(json.dumps([subject]))}">{prose}</span>'
        if presentation == "span"
        else f"<table><tr><td>{prose}</td></tr></table>"
    )
    path.write_text(html.replace(decision, criterion), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "subject,prose",
    [
        ("bore:dia", "pivot bore — ? Ø 10.0–10.1 : caliper"),
        ("cone_boss_north_face:length", "other cone boss north face — ? length 41.50–42.52"),
        ("bore:dia", "pivot bore Ø ?"),
        ("bore:dia", "bore Ø ? pivot bore Ø 10.0–10.1"),
        ("bore:dia", "bore — ? length 10.0–10.1"),
        ("end:length", "end — ? length ref 5"),
        ("bore:dia", "bore — Ø 10.0–10.1"),
        ("bore:dia", "? bore Ø"),
        ("bore:dia", "<span hidden>?</span> bore Ø 10.0–10.1"),
    ],
)
@pytest.mark.parametrize("semantic", [False, True])
def test_sheet_inspection_metadata_cannot_excuse_wrong_visible_criterion(
    tmp_path, subject, prose, semantic
):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {"rule": "inspection", "subject": subject, "status": "unknown", "numbers": {}}
    ]
    attributes = (
        f'class="inspection-criterion" data-inspection-ids="{escape(json.dumps([subject]))}"'
        if semantic
        else ""
    )
    replacement = f"<table><tr {attributes}><td>{prose}</td></tr></table>"
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("mutation", ["none", "wrong_heading", "hidden_marker", "wrong_member"])
def test_sheet_unknown_manual_acceptance_uses_human_requirement_owner(tmp_path, mutation):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    subject = "nut1/part:burrs_and_chips"
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": subject,
            "status": "unknown",
            "numbers": {
                "identity": {
                    "feature_owner": None,
                    "requirement": "burrs_and_chips",
                    "workpiece": "nut1",
                }
            },
        }
    ]
    heading = "stud retention" if mutation == "wrong_heading" else "burrs and chips"
    marker = "<span hidden>?</span>" if mutation == "hidden_marker" else "?"
    member = "nut2" if mutation == "wrong_member" else "nut1"
    replacement = (
        f'<div data-workpiece="{member}"><span class="inspection-criterion" '
        f'data-inspection-ids="{escape(json.dumps([subject]))}">'
        f"{marker} {heading}: no gauge chosen — acceptance criteria not set</span></div>"
    )
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    if mutation == "none":
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("mutation", ["none", "wrong_member", "drop_id", "hidden_marker"])
def test_sheet_compact_criterion_uses_existing_physical_family_ownership(tmp_path, mutation):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    subject = "nut1/end-length:length"
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": subject,
            "status": "unknown",
            "numbers": {
                "identity": {
                    "feature_owner": "end-length",
                    "requirement": "length",
                    "workpiece": "nut1",
                }
            },
        }
    ]
    members = ["nut2"] if mutation == "wrong_member" else ["nut1", "nut2", "nut3", "nut4"]
    physical = [
        {"setup_id": f"E{index}", "op_id": 10, "workpiece": member}
        for index, member in enumerate(members, 1)
    ]
    ids = [] if mutation == "drop_id" else [subject]
    marker = "<span hidden>?</span>" if mutation == "hidden_marker" else "?"
    replacement = (
        f'<div data-physical-ops="{escape(json.dumps(physical))}">'
        f'<p><span class="inspection-criterion" data-inspection-ids="{escape(json.dumps(ids))}">'
        f"{marker} end-length 10–11</span></p></div>"
    )
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    if mutation == "none":
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("target", ["nut1", "nut4"])
def test_sheet_four_member_family_cannot_borrow_one_members_unknown_marker(tmp_path, target):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": f"{target}/end-length:length",
            "status": "unknown",
            "numbers": {
                "identity": {
                    "feature_owner": "end-length",
                    "requirement": "length",
                    "workpiece": target,
                }
            },
        }
    ]
    physical = [
        {"setup_id": f"E{index}", "op_id": 10, "workpiece": f"nut{index}"} for index in range(1, 5)
    ]
    criteria = "".join(
        '<span class="inspection-criterion" '
        f'data-inspection-ids="{escape(json.dumps([f"nut{index}/end-length:length"]))}">'
        f"{'? ' if index == 4 else ''}end-length 10–11</span> "
        for index in range(1, 5)
    )
    replacement = f'<div data-physical-ops="{escape(json.dumps(physical))}"><p>{criteria}</p></div>'
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    if target == "nut4":
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("op", [30, 20])
def test_sheet_process_hold_unknown_retains_scoped_legacy_path(tmp_path, op):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {"rule": "inspection", "subject": "D1a:30", "status": "unknown", "numbers": {}}
    ]
    box = (
        '<div class="unverified"><p>? Not verified by the planner:</p>'
        f"<p>Inspection limits / gauges (op {op}).</p></div>"
    )
    path.write_text(html.replace(decision, box), encoding="utf-8")
    if op == 30:
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


def test_sheet_accepts_owned_undeclared_centre_support_debt(tmp_path):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {"rule": "centre_support", "subject": "D1a", "status": "unknown", "numbers": {}}
    ]
    replacement = (
        '<div class="decision stop" data-decision="block" data-source="centre_support" '
        'data-status="unknown" data-scope="D1a">'
        "<p>which centre the work rides in is undeclared.</p></div>"
    )
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    VALIDATOR["check_sheet"](tmp_path, report)
    path.write_text(html.replace(decision, replacement.replace("D1a", "D1b")), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("mutation", ["none", "wrong_owner", "hidden", "clear"])
def test_sheet_requires_owned_visible_holding_declaration_need(tmp_path, mutation):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {
            "rule": "hold_fields",
            "subject": "D1a",
            "status": "error",
            "numbers": {"missing": ["hold.align"]},
        }
    ]
    owner = "D1b" if mutation == "wrong_owner" else "D1a"
    prose = (
        "All clear; proceed." if mutation == "clear" else "holding declarations need hold.align."
    )
    replacement = (
        '<div class="decision stop" data-decision="block" data-source="hold_fields" '
        f'data-status="error" data-scope="{owner}"><p>{prose}</p></div>'
    )
    if mutation == "hidden":
        replacement = f"<div hidden>{replacement}</div>"
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    if mutation == "none":
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "criterion",
    [
        "? length 41.50–42.52",
        "? cone boss south face length 41.50–42.52",
        "? other cone boss north face lengthwise 41.50–42.52",
        "? cone boss north face radius 41.50–42.52",
        "cone boss north face length 41.50–42.52",
        "cone boss north face length 41.50–42.52 ? cone boss north face Ra 1.6",
        "cone boss north face length 41.50–42.52 ? cone boss south face length 41.50–42.52",
        "cone boss north face Ra 1.6 ? cone boss south face length 41.50–42.52",
        "cone boss north face length 41.50–42.52</p><p>? cone boss north face Ra 1.6",
        "<span hidden>?</span> cone boss north face length 41.50–42.52",
        '<span aria-hidden="true">?</span> cone boss north face length 41.50–42.52',
        '<span style="display:none">?</span> cone boss north face length 41.50–42.52',
        "<script>?</script> cone boss north face length 41.50–42.52",
        "cone boss north face length 41.50–42.52; method: confirm calibration",
    ],
)
def test_sheet_inspection_debt_cannot_borrow_a_sibling_marker(tmp_path, criterion):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": "cone_boss_north_face:length",
            "status": "unknown",
            "numbers": {},
        }
    ]
    replacement = f'<div class="route-inspection"><p>{criterion}</p></div>'
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "replacement",
    [
        "<p>PROCESS HOLD — ? cone boss north face length 42.040–42.080</p>",
        "<table><tr><td>PROCESS HOLD — ? cone boss north face "
        "length 42.040–42.080</td></tr></table>",
        '<div class="route-inspection" data-feature="cone_boss_north_face" '
        'data-requirement="length">?</div>',
        '<div hidden><div class="route-inspection">? cone boss north face '
        "length 41.50–42.52</div></div>",
    ],
)
def test_sheet_inspection_requires_visible_drawing_criterion(tmp_path, replacement):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": "cone_boss_north_face:length",
            "status": "unknown",
            "numbers": {},
        }
    ]
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="sheet hides"):
        VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize(
    "mutation", ["none", "wrong_subject", "wrong_workpiece", "wrong_ancestor", "missing_identity"]
)
def test_sheet_inspection_preserves_physical_workpiece_owner(tmp_path, mutation):
    report, path, html, decision = sheet_disclosure_fixture(tmp_path, grouped=False)
    subject = "nut1/end-length:length"
    report["findings"] = [
        {
            "rule": "inspection",
            "subject": subject,
            "status": "unknown",
            "numbers": {
                "identity": {
                    "feature_owner": "end-length",
                    "requirement": "length",
                    "workpiece": "nut1",
                }
            },
        }
    ]
    recorded_subject = "nut2/end-length:length" if mutation == "wrong_subject" else subject
    workpiece = "nut2" if mutation == "wrong_workpiece" else "nut1"
    ancestor_workpiece = "nut2" if mutation == "wrong_ancestor" else workpiece
    attributes = (
        f'data-inspection-ids="{escape(json.dumps([recorded_subject]))}" '
        f'data-workpiece="{workpiece}"'
        if mutation != "missing_identity"
        else ""
    )
    replacement = (
        f'<div data-workpiece="{ancestor_workpiece}"><table>'
        f'<tr class="inspection-record" {attributes}><td>'
        "end-length — ? length 10–11</td></tr></table></div>"
    )
    path.write_text(html.replace(decision, replacement), encoding="utf-8")
    if mutation == "none":
        VALIDATOR["check_sheet"](tmp_path, report)
    else:
        with pytest.raises(ValueError, match="sheet hides"):
            VALIDATOR["check_sheet"](tmp_path, report)


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_generated_final_inspection_debt_is_visible_to_validator(tmp_path, freecad_kernel, detail):
    from test_arithmetic import (
        CUTTING,
        FEATURES,
        HEADER,
        INVENTORY,
        POLICY,
        drill,
        face,
        one_setup,
        release,
        setup,
        spot,
    )
    from test_cli import run_cli

    s1 = one_setup(face(), spot(), drill(), release(40))
    s2 = setup("S2", "[10]", 'stock_in = "S1"\n', align="", top_z=0.0) + face()
    for name, text in (
        ("features.toml", FEATURES),
        ("inventory.toml", INVENTORY),
        ("cutting.toml", CUTTING),
        ("policy.toml", POLICY),
        ("plan.toml", HEADER + s1 + s2),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    out = tmp_path / "expected"
    result = run_cli("traveler", tmp_path / "plan.toml", "--out", out, "--detail", detail)
    assert result.returncode == 4, result.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    finding = next(
        row
        for row in report["findings"]
        if row["rule"] == "inspection" and row["subject"] == "h1:dia"
    )
    assert finding["status"] == "unknown"
    assert finding["numbers"]["unresolved_cut_effects"] == ["S2:10"]
    # Exercise the real consumer against this debt, without making unrelated
    # findings in the numerical fixture part of the disclosure assertion.
    VALIDATOR["check_sheet"](tmp_path, {**report, "findings": [finding]})


def test_inspection_domain_tracks_four_physical_members_and_manual_part_relationships(monkeypatch):
    data = load_bundle(ROOT / "examples" / "blondihacks-t-nuts" / "plan.toml")
    definitions = VALIDATOR["operative_definitions"](data.plan, data.features)
    subjects = VALIDATOR["inspection_subjects"](data.plan, definitions, data.features)
    per_member = {
        "all-surfaces",
        "base-envelope:height",
        "base-envelope:width",
        "end-length:length",
        "part:actual_slot_fit",
        "part:stud_retention",
        "retained-saw-end",
        "shoulders:thickness",
        "shoulders:width",
        "threaded-hole",
    }
    expected = {f"nut{member}/{subject}" for member in range(1, 5) for subject in per_member}
    assert subjects == expected
    # A presentation family cannot collapse final inspection ownership.
    for setup in data.plan["setups"]:
        setup["presentation_group"] = "one-printed-family"
    assert VALIDATOR["inspection_subjects"](data.plan, definitions, data.features) == expected
    evaluate = tool_resolves.evaluate

    def evaluate_with_manifest(own):
        # Identity and make-op adapters must retain this source manifest, not a
        # dummy context that loses mounted-saw units, frames or feature bindings.
        assert own.features is data.features
        return evaluate(own)

    monkeypatch.setattr(tool_resolves, "evaluate", evaluate_with_manifest)
    domains = VALIDATOR["rule_subjects"](
        data.plan, data.features, VALIDATOR["Entries"](data.inventory), lambda rule: {}
    )
    assert domains["inspection"] == expected
    VALIDATOR["check_inspection_declarations"](data.plan, data.features, {})


def test_explicit_shared_inspection_suppresses_only_its_covered_member_dimension():
    data = load_bundle(ROOT / "examples" / "blondihacks-t-nuts" / "plan.toml")
    setup = next(setup for setup in data.plan["setups"] if setup["id"] == "S1")
    setup["ops"].append(
        {
            "op": 999,
            "do": "inspect",
            "feature": ["base-envelope"],
            "inspect_workpieces": ["nut1", "nut2"],
            "checks": {"width": "calipers"},
        }
    )
    definitions = VALIDATOR["operative_definitions"](data.plan, data.features)
    subjects = VALIDATOR["inspection_subjects"](data.plan, definitions, data.features)
    assert "S1:999/base-envelope:width" in subjects
    assert "nut1/base-envelope:width" not in subjects
    assert "nut2/base-envelope:width" not in subjects
    assert "nut3/base-envelope:width" in subjects
    assert "nut4/base-envelope:width" in subjects
    assert all(f"nut{member}/base-envelope:height" in subjects for member in range(1, 5))
    assert all(f"nut{member}/part:actual_slot_fit" in subjects for member in range(1, 5))
    assert all(f"nut{member}/part:stud_retention" in subjects for member in range(1, 5))


@pytest.mark.parametrize("corruption", ["drop", "canonical_alias", "sibling", "cleared"])
def test_missing_inspection_requirement_stays_on_its_arriving_member(corruption):
    data = load_bundle(ROOT / "examples" / "blondihacks-t-nuts" / "plan.toml")
    setup = next(setup for setup in data.plan["setups"] if setup["id"] == "F1b")
    setup["ops"].append(
        {
            "op": 999,
            "do": "inspect",
            "feature": "base-envelope",
            "missing_requirements": {"surface_finish": "unknown"},
        }
    )
    findings = {
        ("inspection", "nut2/base-envelope:surface_finish"): {
            "status": "unknown",
            "numbers": {"missing_requirement": True},
        }
    }
    check = VALIDATOR["check_inspection_declarations"]
    check(data.plan, data.features, findings)
    row = findings.pop(("inspection", "nut2/base-envelope:surface_finish"))
    if corruption == "canonical_alias":
        findings["inspection", "base-envelope:surface_finish"] = row
    elif corruption == "sibling":
        findings["inspection", "nut1/base-envelope:surface_finish"] = row
    elif corruption == "cleared":
        findings["inspection", "nut2/base-envelope:surface_finish"] = {**row, "status": "pass"}
    with pytest.raises(ValueError, match="nut2/base-envelope:surface_finish"):
        check(data.plan, data.features, findings)


def synthetic_fact(value):
    """A new isolated test measurement, never a relabelling of shipped example evidence."""
    return {
        "value": value,
        "measured": {
            "status": "measured",
            "by": "synthetic test operator",
            "date": "2026-10-03",
            "instrument": "synthetic test gauge",
        },
    }


@pytest.mark.parametrize(
    ("measurement", "trusted"),
    [
        (synthetic_fact(6.35)["measured"], True),
        ({"by": "shop operator", "date": "2026-10-03", "instrument": "micrometer"}, False),
        ({**synthetic_fact(6.35)["measured"], "status": "assumed"}, False),
        ({**synthetic_fact(6.35)["measured"], "status": "illustrative"}, False),
        ({**synthetic_fact(6.35)["measured"], "by": ""}, False),
        ({**synthetic_fact(6.35)["measured"], "by": "unknown"}, False),
        ({**synthetic_fact(6.35)["measured"], "instrument": "  "}, False),
        ({**synthetic_fact(6.35)["measured"], "date": "2026-02-30"}, False),
        ({**synthetic_fact(6.35)["measured"], "date": "20261003"}, False),
        ({**synthetic_fact(6.35)["measured"], "instrument": None}, False),
        ({"status": "measured", "by": "test", "date": "2026-10-03"}, False),
    ],
)
def test_measurement_oracle_requires_explicit_status_and_complete_metadata(measurement, trusted):
    fact = {"value": 6.35, "measured": measurement}
    assert VALIDATOR["accepted"](fact) is trusted
    entries = VALIDATOR["Entries"]({"tools": {"drill": {"kind": "drill", "dia_mm": fact}}})
    assert VALIDATOR["tool_length_mm"]("drill", "dia", entries) == (6.35 if trusted else "unknown")


def test_measurement_oracle_never_guesses_status_from_prose():
    measurement = {
        "by": "shop operator: physically measured and checked",
        "date": "2026-10-03",
        "instrument": "micrometer",
    }
    assert not VALIDATOR["accepted"]({"value": 6.35, "measured": measurement})
    assert VALIDATOR["accepted"]({"value": 6.35, "measured": {**measurement, "status": "measured"}})


def test_nominal_fact_contract_remains_distinct_from_measurement_provenance():
    assert VALIDATOR["accepted"](6.35)
    assert VALIDATOR["accepted"]({"value": 6.35})
    assert VALIDATOR["accepted"]({"value": 6.35, "measured": "unknown"})
    assert not VALIDATOR["accepted"](synthetic_fact(6.35) | {"verify": True})
    assert not VALIDATOR["accepted"](synthetic_fact(6.35) | {"verify": "unknown"})


@pytest.mark.parametrize("status", ["assumed", "illustrative", None])
def test_centre_oracle_cannot_print_a_numeric_tool_fact_on_untrusted_provenance(status):
    tool = {
        "kind": "center_drill",
        "dia_mm": synthetic_fact(1.98),
        "pilot_len_mm": synthetic_fact(1.98),
        "angle_deg": synthetic_fact(60.0),
        "shank_in": synthetic_fact(0.1875),
        "point_angle": synthetic_fact(118.0),
    }
    for fact in tool.values():
        if isinstance(fact, dict):
            if status is None:
                del fact["measured"]["status"]
            else:
                fact["measured"]["status"] = status
    entries = VALIDATOR["Entries"]({"tools": {"centre": tool}})
    assert VALIDATOR["centre_tool_facts"]("centre", entries) == dict.fromkeys(
        VALIDATOR["CENTRE_TOOL_FACTS"], "unknown"
    )


def test_length_oracle_never_uses_an_alternate_key_to_bypass_provenance_debt():
    fact = synthetic_fact(6.35)
    fact["measured"]["status"] = "illustrative"
    entries = VALIDATOR["Entries"](
        {"tools": {"drill": {"kind": "drill", "dia_mm": fact, "dia_in": 0.25}}}
    )
    assert VALIDATOR["tool_length_mm"]("drill", "dia", entries) == "unknown"


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
@pytest.mark.parametrize(
    ("field", "value", "millimetres"),
    [("resolution_mm", 0.001, 0.001), ("resolution_in", 0.0001, 0.00254)],
)
def test_gauge_oracle_independently_requires_trusted_resolution(status, field, value, millimetres):
    fact = synthetic_fact(value)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    gauge = {"kind": "dial_indicator", field: fact}
    resolution = VALIDATOR["gauge_resolution"](gauge)
    if status == "measured":
        assert resolution == pytest.approx(millimetres)
        assert VALIDATOR["blank_form_check"](gauge, "sweep the face", 0.01, {}) == "pass"
    else:
        assert resolution == "unknown"
        assert VALIDATOR["blank_form_check"](gauge, "sweep the face", 0.01, {}) == "unknown"


@pytest.mark.parametrize("verification", [True, "unknown"])
def test_gauge_oracle_keeps_fact_and_plain_range_verification_debt(verification):
    gauge = {
        "kind": "caliper",
        "range_mm": [0.0, 300.0],
        "resolution_mm": synthetic_fact(0.001),
    }
    assert VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, {}) == "pass"
    gauge["resolution_mm"]["verify"] = verification
    assert VALIDATOR["gauge_resolution"](gauge) == "unknown"
    assert VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, {}) == "unknown"
    gauge["resolution_mm"] = synthetic_fact(0.001)
    gauge["verify"] = verification
    assert VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, {}) == "unknown"


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
@pytest.mark.parametrize(
    ("field", "value", "maximum"),
    [("range_mm", 300.0, 300.0), ("range_in", 12.0, 304.8)],
)
def test_scalar_gauge_range_oracle_requires_its_own_explicit_measured_status(
    status, field, value, maximum
):
    # An isolated reader-seam record, not a promotion or schema change to shop data.
    fact = synthetic_fact(value)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    gauge = {"kind": "caliper", field: fact, "resolution_mm": synthetic_fact(0.001)}
    row = {}
    verdict = VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, row)
    assert row["resolution_mm"] == 0.001
    if status == "measured":
        assert verdict == "pass"
        assert row["range_mm"] == pytest.approx([0.0, maximum])
        assert row["band_mm"] == pytest.approx(0.1)
    else:
        assert verdict == "unknown"
        assert row["range_mm"] == "unknown"
        assert "band_mm" not in row


@pytest.mark.parametrize("verification", [True, "unknown"])
def test_scalar_gauge_range_oracle_preserves_fact_verification_debt(verification):
    fact = synthetic_fact(300.0) | {"verify": verification}
    gauge = {"kind": "caliper", "range_mm": fact, "resolution_mm": synthetic_fact(0.001)}
    row = {}
    assert VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, row) == "unknown"
    assert row["range_mm"] == "unknown"
    assert row["resolution_mm"] == 0.001


@pytest.mark.parametrize(
    ("range_fact", "maximum"),
    [
        ({"range_mm": 300.0}, 300.0),
        ({"range_in": 12.0}, 304.8),
        ({"range_mm": [0.0, 300.0]}, 300.0),
    ],
)
def test_plain_catalogue_gauge_ranges_keep_their_numeric_contract(range_fact, maximum):
    gauge = {"kind": "caliper", **range_fact, "resolution_mm": synthetic_fact(0.001)}
    row = {}
    assert VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, row) == "pass"
    assert row["range_mm"] == pytest.approx([0.0, maximum])
    assert row["resolution_mm"] == 0.001
    assert row["band_mm"] == pytest.approx(0.1)


def test_worked_example_gauge_resolutions_are_demo_facts_and_ranges_remain_bare_nominals():
    inventory = tomllib.loads(
        (ROOT / "examples" / "inventory" / "pedro-shop.toml").read_text(encoding="utf-8")
    )
    for name in (
        "rocker-profile-template",
        "rocker-datum-indicator",
        "rocker-position-height-gauge",
        "rocker-position-pins",
        "rocker-position-blocks",
        "radius-gauge",
        "bracket-cross-bore-pins",
        "rocker-outline-template",
        "calipers-18in",
    ):
        gauge = inventory["gauges"][name]
        assert gauge["resolution_mm"]["measured"] == {
            "status": "measured",
            "by": "example value (realistic, not a shop measurement)",
            "date": "2026-10-11",
            "instrument": "example fixture (no physical measurement)",
        }, name
        assert "verify" not in gauge, name
        assert VALIDATOR["gauge_resolution"](gauge) == gauge["resolution_mm"]["value"], name


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
@pytest.mark.parametrize(
    ("field", "value", "step"),
    [("resolution_mm", 0.005, 0.005), ("resolution_in", 0.0005, 0.0127)],
)
def test_dro_oracle_keeps_declared_grid_without_certifying_its_provenance(
    status, field, value, step
):
    fact = synthetic_fact(value)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    entries = VALIDATOR["Entries"]({"machines": {"mill": {field: fact}}})
    grid = VALIDATOR["dro_grid"]({"machine": "mill"}, {"units": "mm"}, entries)
    assert grid[0] == pytest.approx(step)
    assert VALIDATOR["dro_up"](7.497, grid) == pytest.approx(
        7.5 if field == "resolution_mm" else 7.5057
    )
    assert VALIDATOR["accepted"](fact) is (status == "measured")
    assert VALIDATOR["dro_grid_trusted"]({"machine": "mill"}, {"units": "mm"}, entries) is (
        status == "measured"
    )


@pytest.mark.parametrize(
    "resolution",
    [{}, {"resolution_mm": "unknown"}, {"resolution_mm": 0.0}, {"resolution_mm": -0.005}],
)
def test_dro_oracle_preserves_missing_and_nonpositive_default_semantics(resolution):
    entries = VALIDATOR["Entries"]({"machines": {"mill": resolution}})
    grid = VALIDATOR["dro_grid"]({"machine": "mill"}, {"units": "mm"}, entries)
    assert grid[0] == VALIDATOR["DRO_DEFAULT_STEP"]
    assert not VALIDATOR["dro_grid_trusted"]({"machine": "mill"}, {"units": "mm"}, entries)


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_dro_oracle_inherits_bench_source_grid_and_its_measurement_trust(status):
    fact = synthetic_fact(0.01)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    producer = {"id": "S1", "machine": "mill", "stock_in": "stock"}
    bench = {"id": "S2", "machine": "bench", "stock_in": "S1"}
    plan = {"setups": [producer, bench]}
    entries = VALIDATOR["Entries"](
        {"machines": {"mill": {"kind": "mill", "resolution_mm": fact}, "bench": {"kind": "manual"}}}
    )
    assert VALIDATOR["dro_grid_source"](bench, entries, plan) is producer
    assert VALIDATOR["dro_grid"](bench, {"units": "mm"}, entries, plan) == (0.01, 2)
    assert VALIDATOR["dro_grid_trusted"](bench, {"units": "mm"}, entries, plan) is (
        status == "measured"
    )


def test_dro_oracle_keeps_bare_nominal_step_but_never_certifies_it():
    entries = VALIDATOR["Entries"]({"machines": {"mill": {"resolution_mm": 0.005}}})
    assert VALIDATOR["dro_grid"]({"machine": "mill"}, {"units": "mm"}, entries) == (0.005, 3)
    assert not VALIDATOR["dro_grid_trusted"]({"machine": "mill"}, {"units": "mm"}, entries)


def test_shared_inventory_uses_exact_demo_markers_and_preserves_real_vise_readings():
    inventory_path = ROOT / "examples" / "inventory" / "pedro-shop.toml"
    inventory = tomllib.loads(inventory_path.read_text(encoding="utf-8"))
    filename = "cone-pivot-post/built-up.toml"
    plans = {filename: tomllib.loads((ROOT / "examples" / filename).read_text(encoding="utf-8"))}
    found = VALIDATOR["check_example_measurements"](inventory, plans)
    assert len(found["real"]) == 6
    assert len(found["demo"]) == 818
    assert len(found["assumed"]) == 2
    for path, fact in VALIDATOR["example_measurement_records"](inventory):
        measurement = fact["measured"]
        if path in found["real"]:
            assert measurement["status"] == "measured", path
            assert measurement["by"] == "Pedro Paulo Vezza Campos", path
            assert measurement["date"] == "2026-10-05", path
            assert VALIDATOR["accepted"](fact), path
        else:
            status = "assumed" if path in found["assumed"] else "measured"
            assert measurement == {
                "status": status,
                "by": "example value (realistic, not a shop measurement)",
                "date": "2026-10-11",
                "instrument": "example fixture (no physical measurement)",
            }, path
            assert VALIDATOR["accepted"](fact) is (status == "measured"), path
    assert ("machines", "PM-30MV", "resolution_mm") in found["demo"]


def shifted(value):
    """``value`` moved 1 mm: a number, or a measured-edge ``M ±n`` reading's offset."""
    if isinstance(value, str):
        offset = float(value.removeprefix("M ")) + 1.0
        return "M " + f"{offset:+.6f}".rstrip("0").rstrip(".")
    return value + 1.0


def zero_case(part, setup_id):
    """``(setup, finding, entries, own)`` for ``check_zero`` on one example setup: the
    plan's setup, its expected ``zero_check`` finding and the validator's own inputs
    (plan, manifest, inventory, policy and its own kernel run)."""
    folder = ROOT / "examples" / part
    bundle = load_bundle(folder / "plan.toml")
    plan, inventory = bundle.plan, bundle.inventory
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    setup = next(s for s in plan["setups"] if s["id"] == setup_id)
    finding = next(
        f for f in report["findings"] if f["rule"] == "zero_check" and f["subject"] == setup_id
    )
    kernel = VALIDATOR["independent_kernel"](folder / "plan.toml")
    own = VALIDATOR["zero_inputs"](bundle, kernel)
    return setup, finding, VALIDATOR["Entries"](inventory), own


@pytest.mark.parametrize(
    ("part", "feature", "action", "reason"),
    [
        ("pivot-bracket", "ear_relief", "rough_pocket", "touched edge"),
        ("pivot-bracket", "outer_face", "face", "touched edge"),
        ("pivot-shaft", "pivot_bearing", "finish_turn", "touched edge"),
        # The bench shoulder-to-stub reading M, not its nominal length, sets Z.
        ("pivot-shaft", "north_dome", "face", "measured-edge"),
    ],
)
def test_rejects_self_consistent_wrong_z_edge(freecad_kernel, part, feature, action, reason):
    plan = tomllib.loads((ROOT / "examples" / part / "plan.toml").read_text(encoding="utf-8"))
    setup_ids = [
        setup["id"]
        for setup in plan["setups"]
        if any(op.get("feature") == feature and op.get("do") == action for op in setup["ops"])
    ]
    assert setup_ids, (part, feature, action)
    for setup_id in setup_ids:
        setup, finding, entries, own = zero_case(part, setup_id)
        VALIDATOR["check_zero"](setup, finding, entries, own)

        corrupted = copy.deepcopy(finding)
        row = corrupted["numbers"]["axes"]["z"]
        fields = ("edge_mm", "offset_mm", "axis_set", "check_reading", "mirrored_reading")
        fields += ("check_expression", "mirrored_expression")
        for field in fields:
            if field in row:
                row[field] = shifted(row[field])

        with pytest.raises(ValueError, match=reason):
            VALIDATOR["check_zero"](setup, corrupted, entries, own)


def cone_inputs(*, fresh_pure=False, joint_kernel=None):
    folder = ROOT / "examples" / "cone-pivot-post"
    bundle = load_bundle(folder / "built-up.toml")
    report = json.loads((folder / "expected" / "built-up" / "report.json").read_bytes())
    if fresh_pure:
        # These checks consume rule evidence, not frozen SHA/path bindings.
        # Refresh only non-kernel findings; keep native assembly evidence intact.
        bench_bundle = replace(
            bundle,
            plan={
                **bundle.plan,
                "setups": [setup for setup in bundle.plan["setups"] if manual_bench(bundle, setup)],
            },
        )
        derived = [
            *zero_recipe_rule.evaluate(bundle),
            *joints.evaluate_fit(bundle),
            *coordinates.evaluate(bench_bundle),
            *headroom.evaluate(bench_bundle),
        ]
        refreshed = {(row.rule, row.subject): row.to_dict() for row in derived}
        report["findings"] = [
            refreshed.pop((row["rule"], row["subject"]), row) for row in report["findings"]
        ] + list(refreshed.values())
    if joint_kernel is not None:
        # Explicit test kernel facts isolate assembly outcome discrimination; the
        # shipped report keeps its honest unknowns from illustrative shop dimensions.
        synthetic_bundle = replace(bundle, kernel=joint_kernel())
        refreshed = {
            (row.rule, row.subject): row.to_dict()
            for row in joints.evaluate_assembly(synthetic_bundle)
        }
        report["findings"] = [
            refreshed.pop((row["rule"], row["subject"]), row) for row in report["findings"]
        ] + list(refreshed.values())
    return bundle.plan, bundle.features, bundle.inventory, bundle.policy, report


@pytest.mark.parametrize("corruption", ["nearest", "spaces", "basic_band", "closure"])
def test_rejects_cone_indexing_arithmetic_even_when_unverified(corruption):
    plan, features, inventory, _, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S5")
    finding = next(
        f for f in report["findings"] if f["rule"] == "indexing" and f["subject"] == "S5"
    )
    entries = VALIDATOR["Entries"](inventory)
    VALIDATOR["check_indexing"](setup, features, entries, finding)
    corrupted = copy.deepcopy(finding)
    row = corrupted["numbers"]
    if corruption == "nearest":
        # A plausible actual setting on another declared circle, but not the
        # nearest one. Matching its own signed error must not legitimize it.
        row.update(plate="C", circle=41, turns=1, spaces=16, actual_angle_deg=513 / 41)
        error = 513 / 41 - 12.5182
        row.update(position_errors_deg=[error], max_position_error_deg=abs(error))
    elif corruption == "spaces":
        row["spaces"] += 1
    elif corruption == "basic_band":
        row["tolerance_deg"] = 1.0
    else:
        row["closure"] = {"error_deg": 0.0, "within_tolerance": True}
    with pytest.raises(ValueError):
        VALIDATOR["check_indexing"](setup, features, entries, corrupted)


def test_rejects_unsourced_finished_diameter_in_unbound_profile(freecad_kernel):
    plan, features, inventory, policy, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = next(
        f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1"
    )
    kernel = VALIDATOR["independent_kernel"](
        ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    )
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)
    corrupted = copy.deepcopy(finding)
    corrupted["numbers"]["diameter_mm"] = 21.93
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, corrupted, kernel)


def test_accepts_cited_kernel_revolved_bases_without_declared_diameters(freecad_kernel):
    documents = {
        path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
        for path in (ROOT / "examples").rglob("*.toml")
    }
    code, missing = VALIDATOR["validate_fixture"]("pivot-shaft", documents)
    assert code == 0  # explicit measured-branch demo facts preserve the worked positive control
    assert missing == []


def test_exposed_profile_converts_inch_dia_alias_and_declared_dome_base():
    # Synthetic manifest and kernel facts: an inch shaft declared by its ``dia`` alias and
    # a dome by its base radius, each measured revolved about setup Z.
    setup = {
        "id": "S1",
        "frame": "F",
        "stock_state": {"north_end_z": 0.0, "south_end_z": 12.0},
        "hold": {"stickout_mm": 12.0},
        "ops": [],
    }
    features = {
        "units": "in",
        "frames": {"F": {"origin": [0.0, 0.0, 0.0]}},
        "features": {
            "neck": {"kind": "shaft", "dia": 0.25},
            "cap": {"kind": "dome", "base_radius": 0.125},
        },
    }
    revolved = {
        "neck": {"z_mm": [0.0, 10.0]},
        "cap": {"z_mm": [10.0, 12.0], "end_radii_mm": [3.175, 0.0]},
    }
    facts = {"status": "ok", "setups": {"S1": {"revolved": revolved}}}
    profile = VALIDATOR["kernel_exposed_profile"](
        setup, {"setups": [setup]}, features, 10.0, lambda: facts
    )
    assert profile["diameter_mm"] == pytest.approx(6.35)
    assert [(s["z_mm"], s["features"]) for s in profile["segments"]] == [
        ([0.0, 10.0], ["neck"]),
        ([10.0, 12.0], ["cap"]),
    ]
    assert [s["diameter_mm"] for s in profile["segments"]] == pytest.approx([6.35, 6.35])


@pytest.mark.parametrize(
    "corruption",
    [
        "dome_cap",
        "dome_cap_with_nominal",
        "groove_envelope",
        "non_axial_kind",
        "unknown_nominal",
        "uncited_kernel",
        "unknown_feature",
        "outside_stock",
        # Self-consistent: the shoulder stretched over the 5.7 mm relief, dropped, so the
        # least exposed diameter (and the L/D limit) reads the 6.35 mm journal instead.
        "stretched_shoulder",
    ],
)
def test_rejects_self_consistent_wrong_exposed_profiles(freecad_kernel, corruption):
    plan, features, inventory, policy, report = pivot_shaft_inputs()
    folder = ROOT / "examples" / "pivot-shaft"
    kernel = VALIDATOR["independent_kernel"](folder / "plan.toml")
    sid = "S3" if corruption in {"dome_cap", "dome_cap_with_nominal"} else "S1"
    setup = next(item for item in plan["setups"] if item["id"] == sid)
    finding = next(
        item for item in report["findings"] if item["rule"] == "stickout" and item["subject"] == sid
    )
    VALIDATOR["check_stickout"](
        setup, plan, features, inventory, policy, copy.deepcopy(finding), kernel
    )
    segments = finding["numbers"]["segments"]
    feature = {
        "groove_envelope": "south_relief",
        "non_axial_kind": "pivot_bearing",
    }.get(corruption, "south_dome")
    segment = next(item for item in segments if feature in item["features"])
    definition = features["features"][feature]
    if corruption in {"dome_cap", "dome_cap_with_nominal"}:
        segment["diameter_mm"] = segment["base_diameter_mm"] = 6.0
        if corruption == "dome_cap_with_nominal":
            definition["dia_nominal"] = 6.0
    elif corruption == "groove_envelope":
        for key in ("dia_nominal", "nominal_dia", "dia"):
            definition.pop(key, None)
        segment["diameter_mm"] = segment["base_diameter_mm"]
    elif corruption == "non_axial_kind":
        definition["kind"] = "hole"
    elif corruption == "unknown_nominal":
        definition["dia_nominal"] = "unknown"
    elif corruption == "uncited_kernel":
        finding["cite"] = [
            cite
            for cite in finding["cite"]
            if not cite.startswith("kernel: setups.S1.revolved.south_dome (")
        ]
    elif corruption == "unknown_feature":
        segment["features"] = ["undeclared_dome"]
        finding["cite"].append("kernel: setups.S1.revolved.undeclared_dome (forged witness)")
    elif corruption == "stretched_shoulder":
        shoulder = next(item for item in segments if item["features"] == ["shoulder_od"])
        relief = next(item for item in segments if item["features"] == ["south_relief"])
        shoulder["z_mm"][1] = relief["z_mm"][1]
        segments.remove(relief)
        finding["numbers"]["diameter_features"] = ["pivot_bearing"]
    else:
        definition["base_radius"] = 5.5
        segment["diameter_mm"] = segment["base_diameter_mm"] = 11.0
    diameter = min(item["diameter_mm"] for item in segments)
    finding["numbers"].update(
        diameter_mm=diameter,
        unsupported_limit_mm=diameter * policy["numbers"]["stickout_ld_max"],
    )
    with pytest.raises(ValueError, match="finished exposed diameter"):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)


def pivot_shaft_inputs():
    folder = ROOT / "examples" / "pivot-shaft"
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    return plan, features, inventory, policy, report


@pytest.mark.parametrize(
    "case", ["support_unselected", "support_unverified", "ratio_halved", "report_named_support"]
)
def test_stickout_verdict_and_support_come_from_the_plan_hold_and_inventory(shaft_bundle, case):
    # The isolated shaft has known test-owned cutting geometry. S1 holds 167.5 mm
    # out against a 22.8 mm unsupported limit and passes only on its selected,
    # verified dead centre; S2 holds 14 mm, inside its limit. Change only the support
    # or ratio: the derived row is accepted and the unchanged approval is not.
    bundle = copy.deepcopy(shaft_bundle)
    plan, features, inventory, policy = (
        bundle.plan,
        bundle.features,
        bundle.inventory,
        bundle.policy,
    )

    def kernel():
        return bundle.kernel

    sid = "S1" if case.startswith("support_") else "S2"
    setup = next(item for item in plan["setups"] if item["id"] == sid)
    baseline = next(item.to_dict() for item in stickout.evaluate(bundle) if item.subject == sid)
    assert baseline["status"] == "pass"
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, baseline, kernel)
    derived = copy.deepcopy(baseline)
    row = derived["numbers"]
    if case == "support_unselected":
        setup["hold"]["support"] = "none"  # the follow rest alone is no stick-out support
        row["supports"] = [s for s in row["supports"] if s["reference"] == "follow_rest"]
        row["support_status"], derived["status"] = "not_applicable", "error"
    elif case == "support_unverified":
        inventory["fixtures"]["dead_centre_tailstock_mt3"]["verify"] = True
        row["supports"][0]["status"] = "unknown"
        row["support_status"], derived["status"] = "unknown", "unknown"
    else:
        policy["numbers"]["stickout_ld_max"] = 2.0
        row.update(stickout_ld_max=2.0, unsupported_limit_mm=row["diameter_mm"] * 2.0)
        baseline["numbers"].update(
            stickout_ld_max=2.0, unsupported_limit_mm=row["diameter_mm"] * 2.0
        )
        derived["status"] = "error"
        if case == "report_named_support":
            baseline["numbers"]["support_status"] = "pass"
            baseline["numbers"]["supports"] = [
                {"reference": "tailstock", "kind": "accessory", "status": "pass", "source": "x"}
            ]
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, derived, kernel)
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, baseline, kernel)


def test_stickout_cannot_call_a_lathe_hold_inapplicable(freecad_kernel):
    plan, features, inventory, policy, report = pivot_shaft_inputs()
    kernel = VALIDATOR["independent_kernel"](ROOT / "examples" / "pivot-shaft" / "plan.toml")
    setup = next(item for item in plan["setups"] if item["id"] == "S1")
    finding = next(
        item
        for item in report["findings"]
        if item["rule"] == "stickout" and item["subject"] == "S1"
    )
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)
    finding["status"] = "not_applicable"
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)


def test_stickout_reads_a_machine_selected_by_its_category_as_that_machine(freecad_kernel):
    """A setup selecting its machine as ``machines.<key>`` is on that machine, as on its
    bare key: the engine's stick-out finding (a lathe's verdict, another machine's
    inapplicable) is accepted with its own status, and no other status is."""
    plan_path = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    bundle = load_bundle(plan_path)
    assert run_geometry(bundle)["status"] == "ok"
    kernel = VALIDATOR["independent_kernel"](plan_path)
    for setup in bundle.plan["setups"]:
        setup["machine"] = f"machines.{setup['machine']}"
    native = {f.subject: json.loads(json.dumps(f.to_dict())) for f in stickout.evaluate(bundle)}
    assert {row["status"] for row in native.values()} - {"not_applicable"}
    for setup in bundle.plan["setups"]:
        args = (setup, bundle.plan, bundle.features, bundle.inventory, bundle.policy)
        finding = native[setup["id"]]
        VALIDATOR["check_stickout"](*args, finding, kernel)
        for forged in sorted({"pass", "unknown", "error", "not_applicable"} - {finding["status"]}):
            with pytest.raises(ValueError):
                VALIDATOR["check_stickout"](*args, {**finding, "status": forged}, kernel)


@pytest.mark.parametrize("kind", ["bandsaw", "lathe", "unknown"])
@pytest.mark.parametrize(
    "policy_case",
    [
        "cited_limit",
        "missing_ratio",
        "missing_citation",
        "missing_verification",
        "unverified",
        "missing_tables",
    ],
)
def test_stickout_optional_policy_preserves_machine_applicability(shaft_bundle, kind, policy_case):
    bundle = copy.deepcopy(shaft_bundle)
    setup = next(item for item in bundle.plan["setups"] if item["id"] == "S1")
    setup["machine"] = "validator-test-machine"
    bundle.inventory["machines"]["validator-test-machine"] = {"kind": kind}
    setup["hold"]["support"] = "none"
    setup["hold"].pop("supports", None)
    policy = bundle.policy
    policy["numbers"]["stickout_ld_max"] = 4.0
    policy["numbers_cite"]["stickout_ld_max"] = "Test-owned unsupported L/D limit"
    policy["numbers_verify"]["stickout_ld_max"] = False
    if policy_case == "missing_tables":
        for table in ("numbers", "numbers_cite", "numbers_verify"):
            policy.pop(table)
    elif policy_case.startswith("missing_"):
        table = {
            "missing_ratio": "numbers",
            "missing_citation": "numbers_cite",
            "missing_verification": "numbers_verify",
        }[policy_case]
        policy[table].pop("stickout_ld_max")
    elif policy_case == "unverified":
        policy["numbers_verify"]["stickout_ld_max"] = True
    finding = next(
        item.to_dict() for item in stickout.evaluate(bundle) if item.subject == setup["id"]
    )
    expected = (
        "not_applicable"
        if kind == "bandsaw"
        else "error"
        if kind == "lathe" and policy_case in {"cited_limit", "missing_verification"}
        else "unknown"
    )
    assert finding["status"] == expected
    if policy_case in {"missing_ratio", "missing_tables"}:
        assert finding["numbers"]["stickout_ld_max"] == "unknown"
    if policy_case in {"missing_ratio", "missing_citation", "unverified", "missing_tables"}:
        assert finding["numbers"]["unsupported_limit_mm"] == "unknown"
    args = (setup, bundle.plan, bundle.features, bundle.inventory, policy)

    def kernel():
        return bundle.kernel

    VALIDATOR["check_stickout"](*args, finding, kernel)
    for forged in {"pass", "unknown", "error", "not_applicable"} - {expected}:
        with pytest.raises(ValueError, match="stick-out verdict"):
            VALIDATOR["check_stickout"](*args, {**finding, "status": forged}, kernel)
    if policy_case in {"missing_ratio", "missing_tables"}:
        forged = copy.deepcopy(finding)
        forged["numbers"]["stickout_ld_max"] = 4.0
        with pytest.raises(ValueError, match="stick-out shop ratio"):
            VALIDATOR["check_stickout"](*args, forged, kernel)


@pytest.fixture(scope="module")
def shaft_bundle(tmp_path_factory, freecad_kernel):
    """Native shaft stock for numeric stick-out tests, not proof of the shipped inputs."""
    plan = shaft(tmp_path_factory.mktemp("validator-shaft"))
    synthetic_centre_tool(plan)
    bundle = load_bundle(plan)
    synthetic_shaft_cutting_geometry(bundle)
    blade = bundle.inventory["tools"]["parting-blade-lms-1728"]
    for key, value in {
        "nose_radius_mm": 0.1,
        "insert_angle_deg": 87.0,
        "entering_angle_deg": 90.0,
        "edge_len_mm": 1.6,
        "head_len_mm": 12.7,
        "shank_width_mm": 1.6,
        "functional_width_mm": 1.6,
        "blade_width_mm": 1.6,
        "reach_mm": 15.0,
        "shank_in": 0.5,
    }.items():
        blade[key] = synthetic_fact(value)
    blade["projection_mm"] = {"qctp-axa-lms-2280/7-parting": synthetic_fact(15.0)}
    holder = bundle.inventory["holders"]["qctp-axa-lms-2280"]["members"]["7-parting"]
    holder.update(body_width_mm=synthetic_fact(50.0), body_depth_mm=synthetic_fact(32.0))
    bundle.inventory["machines"]["PM-1127VF-LB"]["resolution_mm"] = synthetic_fact(0.01)
    facts = run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    return bundle


@pytest.mark.parametrize("sid", ["S1", "S2"])
@pytest.mark.parametrize(
    "case",
    [
        "fallback_unverified",
        "fallback_verify_unknown",
        "fallback_dia_unknown",
        "held_unknown",
        "held_zero",
        "stock_state_unknown",
        "fallback_verified",
    ],
)
def test_stickout_holds_only_a_verified_held_diameter(shaft_bundle, sid, case):
    # With no od_mm in the setup's stock state the held diameter falls back to the
    # stock's dia_mm, which is evidence only when the stock's form is verified. The
    # engine's own stick-out row is accepted: unknown for an unverified, unknown or
    # unusable held diameter, a pass on the verified fallback. A row that holds the
    # unverified fallback (or any number the plan does not give) as evidence and
    # passes is not.
    bundle = copy.deepcopy(shaft_bundle)
    stock = bundle.plan["stock"]
    setup = next(item for item in bundle.plan["setups"] if item["id"] == sid)
    fallback = stock["dia_mm"]
    if case.startswith("fallback"):
        setup["stock_state"].pop("od_mm", None)
        stock["form_verify"] = {
            "fallback_unverified": True,
            "fallback_verify_unknown": "unknown",
        }.get(case, False)
        if case == "fallback_dia_unknown":
            stock["dia_mm"] = "unknown"
    elif case == "held_unknown":
        setup["stock_state"]["od_mm"] = "unknown"
    elif case == "held_zero":
        setup["stock_state"]["od_mm"] = 0
    else:
        setup["stock_state"] = "unknown"
    native = next(f.to_dict() for f in stickout.evaluate(bundle) if f.subject == sid)

    def check(finding):
        VALIDATOR["check_stickout"](
            setup,
            bundle.plan,
            bundle.features,
            bundle.inventory,
            bundle.policy,
            finding,
            lambda: bundle.kernel,
        )

    check(native)
    if case == "fallback_verified":
        assert (native["status"], native["numbers"]["held_diameter_mm"]) == ("pass", fallback)
        return
    assert native["status"] == "unknown"
    forged = copy.deepcopy(native)
    forged["status"] = "pass"
    forged["numbers"]["held_diameter_mm"] = fallback
    with pytest.raises(ValueError):
        check(forged)


@pytest.mark.parametrize(
    ("setup", "stock", "expected"),
    [
        ({}, {"dia_mm": 25.4}, 25.4),
        ({"stock_state": {}}, {"dia_mm": 25.4}, 25.4),
        ({"stock_state": {"top_z": "unknown"}}, {"dia_mm": 25.4}, 25.4),
        ({}, {"dia_mm": 25.4, "form_verify": False}, 25.4),
        ({}, {"dia_mm": 25.4, "form_verify": True}, "unknown"),
        ({}, {"dia_mm": 25.4, "form_verify": "unknown"}, "unknown"),
        ({"stock_state": "unknown"}, {"dia_mm": 25.4}, "unknown"),
        ({"stock_state": {"od_mm": "unknown"}}, {"dia_mm": 25.4}, "unknown"),
        ({"stock_state": {"od_mm": 0}}, {"dia_mm": 25.4}, "unknown"),
        ({"stock_state": {"od_mm": -1}}, {"dia_mm": 25.4}, "unknown"),
        ({"stock_state": {"od_mm": 19.0}}, {"dia_mm": 25.4}, 19.0),
        ({"stock_state": {"od_mm": 19.0}}, {"dia_mm": 25.4, "form_verify": True}, 19.0),
        ({}, {"dia_mm": "unknown"}, "unknown"),
        ({}, {"dia_mm": 0}, "unknown"),
        ({}, {}, "unknown"),
        ({}, "unknown", "unknown"),
    ],
)
def test_held_stock_oracle_distinguishes_omission_from_explicit_unknown(setup, stock, expected):
    # These are declared-input cases, not measurements or approval of a physical hold.
    plan = {"stock": stock}
    assert VALIDATOR["held_stock"](setup, plan) == expected
    assert stickout.held_diameter(SimpleNamespace(plan=plan), setup) == expected


def test_stickout_oracle_keeps_ring_bench_nominal_fallback_without_resolving_its_hold():
    data = load_bundle(ROOT / "examples" / "blondihacks-brass-ring" / "plan.toml")
    setup = next(item for item in data.plan["setups"] if item["id"] == "H1")
    assert "stock_state" not in setup
    assert data.plan["stock"]["dia_mm"] == 25.4
    finding = next(item.to_dict() for item in stickout.evaluate(data) if item.subject == "H1")
    row = finding["numbers"]
    assert finding["status"] == "not_applicable"
    assert row["held_diameter_mm"] == 25.4
    assert row["stickout_mm"] == "unknown"
    assert setup["hold"]["grip_mm"] == "unknown"

    def check():
        VALIDATOR["check_stickout"](
            setup,
            data.plan,
            data.features,
            data.inventory,
            data.policy,
            finding,
            lambda: data.kernel,
        )

    check()
    row["held_diameter_mm"] = 26.4
    with pytest.raises(ValueError, match="held diameter"):
        check()


@pytest.mark.parametrize("action", ["tap", "ream", "drill"])
def test_endpoint_oracle_checks_member_facts_units_and_action_specific_depth(action):
    # Isolated synthetic facts, never a claim about shop inventory.
    operation = {"op": 10, "do": action, "feature": "h", "tool": "cutter/installed"}
    operation.update({"depth_mm": 5.0} if action == "tap" else {"exit_mm": 0.5})
    measured = synthetic_fact(0)["measured"]
    bundle = SimpleNamespace(
        plan={
            "setups": [
                {
                    "id": "S",
                    "machine": "test-mill",
                    "stock_state": {"top_z": 10.0, "local_thickness": {"h": 20.0}},
                    "ops": [operation],
                }
            ]
        },
        features={
            "units": "mm",
            "features": {
                "h": {
                    "kind": "threaded_hole" if action == "tap" else "hole",
                    "thru": action != "tap",
                    "depth": [4.0, 8.0],
                },
            },
        },
        inventory={
            "machines": {"test-mill": {"kind": "mill", "resolution_mm": synthetic_fact(0.001)}},
            "tools": {
                "cutter": {
                    "kind": "drill_set",
                    "dia_mm": 20.0,
                    "point_angle": 118.0,
                    "lead_mm": 2.0,
                    "members": {
                        "installed": {
                            "kind": action,
                            "dia_mm": {"value": 6.0, "measured": measured},
                            "point_angle": {"value": 90.0, "measured": measured},
                            "lead_mm": {"value": 3.175, "measured": measured},
                            "flute_len_in": 1.0,
                        }
                    },
                },
            },
        },
    )
    bundle.feature_definitions = bundle.features["features"]
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    row = findings["blind_depth", "h"]["numbers"]["endpoints"][0]
    expected_tip = {"tap": 5.0, "ream": -13.675, "drill": -13.5}[action]
    assert row["tip_z"] == pytest.approx(expected_tip)
    entries = VALIDATOR["Entries"](bundle.inventory)
    VALIDATOR["check_endpoints"](validator_test_bundle(bundle), findings, entries)
    field = {"tap": "flute_len_mm", "ream": "lead_mm", "drill": "point_mm"}[action]
    row[field] += 1.0
    if action != "tap":
        row["tip_z"] -= 1.0
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](validator_test_bundle(bundle), findings, entries)


# The pivot-shaft centre as the engine reports it: prepared, contradicted (plan or tool),
# unconfirmed, misplaced or unplaced.
CENTRE_CASES = [
    (None, None, None),
    ("plan", "drill_length_mm", "2.48"),
    ("plan", "mouth_dia_mm", "5.0"),
    ("tool", "point_angle", "40"),
    ("tool", "point_angle", "{ value = 118, verify = true }"),
    ("tool", "verify", "true"),
    ("plan", "at", "[0.0, 0.0, -173.25]"),
    ("plan", "at", "[0.5, 0.0, -173.5]"),
    ("plan", "axis", "[0.0, 0.0, -1.0]"),
    ("plan", "at", '"unknown"'),
]


def centre_findings(tmp_path, where=None, key=None, value=None):
    """The engine's own blind_depth findings for a changed pivot-shaft centre: its endpoint
    row, a validator call that checks them, and the centre's finding."""
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    if where == "plan":
        set_process_key(plan, "plain_end_centre", key, value)
    elif where == "tool":
        set_tool_fact(plan, key, value)
    bundle = load_bundle(plan)
    # Fresh isolated DRO readings, with the source grids' physical precision preserved.
    for machine, resolution in (("PM-30MV", 0.005), ("PM-1127VF-LB", 0.01)):
        bundle.inventory["machines"][machine]["resolution_mm"] = synthetic_fact(resolution)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    entries = VALIDATOR["Entries"](bundle.inventory)
    finding = findings["blind_depth", "plain_end_centre"]
    (row,) = finding["numbers"]["endpoints"]
    return (
        row,
        lambda: VALIDATOR["check_endpoints"](validator_test_bundle(bundle), findings, entries),
        finding,
    )


@pytest.mark.parametrize(("where", "key", "value"), CENTRE_CASES)
def test_centre_oracle_prints_a_quill_depth_only_for_the_centre_its_tool_cuts(
    tmp_path, where, key, value
):
    row, check, _ = centre_findings(tmp_path, where, key, value)
    check()
    # A quill depth the inputs do not derive: one printed for a centre that is not the
    # selected tool's own on the touched end, or a prepared one moved.
    if row["depth_mm"] == "unknown":
        row["depth_mm"] = 1.98 + (3.0 - 1.98) / 2 / math.tan(math.radians(30.0))
    else:
        row["depth_mm"] += 1.0
    row["tip_z"] = row["entry_z"] - row["depth_mm"]
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("countersink_depth_mm", 0.9),
        ("drill_length_mm", 2.48),
        ("mouth_z", 1.0),
        ("depth_scale", "dro"),
        # Table 6 C already includes the pilot point: no drill-point lead is added.
        ("point_mm", 0.0),
    ],
)
def test_centre_oracle_rejects_a_centre_row_its_inputs_do_not_derive(tmp_path, field, value):
    row, check, _ = centre_findings(tmp_path)
    check()
    row[field] = value
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("fact", ["drill_dia_mm", "drill_length_mm", "point_angle_deg"])
def test_centre_oracle_holds_the_reported_tool_facts_to_the_inventory(tmp_path, fact):
    row, check, _ = centre_findings(tmp_path)
    check()
    row["tool_centre"][fact] += 1.0
    with pytest.raises(ValueError):
        check()


def test_centre_oracle_takes_the_touched_surface_from_the_plan_not_the_report(tmp_path):
    # The centre misplaced 0.25 into the end that S0 op 10 faces to setup Z 0: the engine
    # errors and prints no quill depth. Made self-consistent, the report claims the
    # touched surface is where the buried mouth lies and passes the prepared depth.
    row, check, finding = centre_findings(tmp_path, "plan", "at", "[0.0, 0.0, -173.25]")
    check()
    row["entry_z"] = row["mouth_z"]
    row["depth_mm"] = row["drill_length_mm"] + row["countersink_depth_mm"]
    row["tip_z"] = row["entry_z"] - row["depth_mm"]
    finding["status"] = "pass"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("corruption", ["surface", "source"])
def test_endpoint_oracle_takes_a_blind_hole_entry_from_the_plan(corruption):
    data = drill_bundle(depth_mm=40.0)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
    (row,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    if corruption == "surface":
        # The whole hole moved 1 mm into the part, its depth unchanged: self-consistent.
        for field in ("entry_z", "tip_z", "dro_entry_z", "dro_tip_z"):
            row[field] -= 1.0
    else:
        # The right Z, credited to a surface the plan never leaves there.
        row["entry_from"] = "S1 op 10 to_z"
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)


def printed_endpoint(data):
    """The engine's one endpoint row for ``data``'s hole and a validator call on it."""
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    (row,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]

    def check():
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)

    check()
    return row, check


def faced_endpoint_bundle(tmp_path):
    """Scratch S2 drills from a bounded face S1 cut on its coarser grid."""
    data = load_bundle(surface_plan(tmp_path, coarse=True, depth="[2.95, 3.0]"))
    producer, consumer = data.plan["setups"]
    target = data.features["features"]["target"]
    target.update(kind="face")
    # Model frame Z is setup A's Z + 1; these authored bounds describe the cut plane.
    target["bounds"]["z"] = [-1.27825, -1.27825]
    op = producer["ops"][0]
    op["stock_removal_bounds"] = {
        "x": [-6.0, 16.0],
        "y": [-3.0, 9.0],
        "z": [-4.0, 0.0],
    }
    op["contour"] = {
        "method": "linear_table",
        "sweep_frame": "A",
        "step_mm": 2.0,
        "keep_out": [{"at": [100.0, 100.0], "dia_mm": 2.0}],
    }
    producer["stock_state"]["top_feature"] = "target"
    consumer["stock_state"]["top_feature"] = "target"
    del consumer["stock_state"]["entry_z"]
    return data


def test_endpoint_oracle_uses_inventory_for_authored_face_coverage_without_a_kernel(tmp_path):
    # The island is far outside the face, but proving that still needs the cutter radius.
    # Keep the kernel-free oracle call in printed_endpoint: omitted inventory used to
    # derive an unknown printed entry. No native evidence is needed.
    row, check = printed_endpoint(faced_endpoint_bundle(tmp_path))
    assert row["entry_z"] == -2.27825
    assert row["dro_entry_z"] == -2.27
    row["dro_entry_z"] = "unknown"
    with pytest.raises(ValueError, match="printed entry Z"):
        check()


def native_faced_endpoint_bundle(tmp_path):
    """The same bounded producer, with native extent and incidental round metadata."""
    data = faced_endpoint_bundle(tmp_path)
    target = data.features["features"]["target"]
    del target["bounds"]
    target.update(at=[10.0, 5.0, -1.27825], axis=[0.0, 0.0, 1.0], dia=2.0)
    ref = "#40/ADVANCED_FACE[1]/NONE"
    target["faces"] = [ref]
    producer, consumer = data.plan["setups"]
    # The source touches incoming stock, not the future CAD floor; only S2 binds
    # its received top to that floor.
    del producer["stock_state"]["top_feature"]
    producer["stock_in"] = "stock"
    for context in (producer, consumer):
        context["zero"]["z"]["from"] = "+z"
    facts = {
        "status": "ok",
        "mapping": {ref: 0},
        "faces": [
            {
                "index": 0,
                "kind": "Plane",
                "bbox_mm": [0.0, 0.0, -1.27825, 20.0, 10.0, -1.27825],
            }
        ],
        "ops": {
            f"{producer['id']}:{producer['ops'][0]['op']}": {
                "approach": "milling",
                "claimed_indices": [0],
                "faced_side": 1,
            }
        },
    }
    return replace(data, kernel=facts)


@pytest.mark.parametrize("available", [True, False], ids=["matched-plane", "missing-kernel"])
def test_endpoint_oracle_needs_independent_native_evidence_for_a_face_without_bounds(
    tmp_path, available
):
    data = native_faced_endpoint_bundle(tmp_path)
    facts = data.kernel
    independent = copy.deepcopy(facts) if available else None
    reported = replace(data, kernel=facts if available else None)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(reported)}
    entries = VALIDATOR["Entries"](data.inventory)
    (row,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    assert row["entry_z"] == -2.27825
    assert row["dro_entry_z"] == (-2.27 if available else "unknown")

    def check():
        return VALIDATOR["check_endpoints"](
            validator_test_bundle(data), findings, entries, lambda: independent
        )

    check()
    if available:
        # Even a report with complete numeric endpoints cannot supply missing native facts.
        with pytest.raises(ValueError, match="printed entry Z.*unknown"):
            VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
        independent["mapping"].clear()
    else:
        # An unavailable kernel leaves the native surface unknown, never a known entry.
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
        row["dro_entry_z"] = -2.27
    with pytest.raises(ValueError, match="printed entry Z.*unknown"):
        check()


def trap_native_coverage(monkeypatch, forged_whole=False):
    """Neither shared coverage nor a checker-native operand may answer the oracle."""

    def checker_helper(*args, **kwargs):
        pytest.fail("native coverage oracle called a checker coverage helper")

    coverage = (lambda *args, **kwargs: "whole") if forged_whole else checker_helper
    monkeypatch.setitem(VALIDATOR["surface_cut_coverage"].__globals__, "cut_coverage", coverage)
    for helper in ("_corners", "_kernel_face_boxes", "_setup_footprint", "_keep_out_circles"):
        monkeypatch.setattr(tip_endpoints, helper, checker_helper)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("whole", "whole"),
        ("incidental-disc", "partial"),
        ("empty-bounds", "unknown"),
        ("unknown-bounds", "unknown"),
        ("unbounded-empty-bounds", "unknown"),
        ("unbounded-unknown-bounds", "unknown"),
        ("unbounded-own", "whole"),
        ("unbounded-own-islands", "unknown"),
        ("unbounded-cross-feature", "unknown"),
        ("list-feature", "whole"),
        ("other-z-disjoint", "partial"),
        ("other-z-disjoint-missing-ref", "unknown"),
        ("unknown-z-disjoint", "partial"),
        ("non-finite-z-disjoint", "partial"),
        ("unknown-z-disjoint-missing-ref", "unknown"),
        ("missing-kernel", "unknown"),
        ("missing-match", "unknown"),
        ("missing-refs", "unknown"),
        ("boolean-index", "unknown"),
        ("mapping-error", "unknown"),
        ("missing-extra-ref", "unknown"),
        ("missing-box", "unknown"),
        ("malformed-box", "unknown"),
        ("non-finite-box", "unknown"),
        ("ambiguous-box", "unknown"),
        ("no-eligible-plane", "unknown"),
        ("missing-to-z", "unknown"),
        ("nonplanar-box", "unknown"),
        ("thin-known-cylinder", "unknown"),
        ("thin-known-bspline", "unknown"),
        ("missing-removal-z", "unknown"),
        ("removal-z-above", "unknown"),
        ("removal-z-descending", "unknown"),
        ("removal-z-non-finite", "unknown"),
        ("boundary", "unknown"),
        ("keep-out", "partial"),
        ("missing-cutter", "unknown"),
        ("missing-sweep-frame", "unknown"),
        ("missing-frame", "unknown"),
        ("signed-permutation", "whole"),
        ("inches", "whole"),
        ("oblique-contained", "whole"),
        ("oblique-overlap", "unknown"),
        ("oblique-disjoint", "partial"),
        ("oblique-keep-out", "unknown"),
    ],
)
def test_native_face_coverage_oracle_uses_only_matched_boxes(tmp_path, monkeypatch, case, expected):
    data = native_faced_endpoint_bundle(tmp_path)
    producer = data.plan["setups"][0]
    op, target = producer["ops"][0], data.feature_definitions["target"]
    box = data.kernel["faces"][0]["bbox_mm"]
    if case == "incidental-disc":
        # This contains the incidental authored disc, but not the native 20x10 face.
        op["stock_removal_bounds"].update(x=[4.0, 6.0], y=[2.0, 4.0])
    elif case in {"empty-bounds", "unknown-bounds"}:
        target["bounds"] = {} if case == "empty-bounds" else "unknown"
    elif case.startswith("unbounded-"):
        del op["stock_removal_bounds"]
        if case != "unbounded-own-islands":
            op["contour"]["keep_out"] = []
        if case in {"unbounded-empty-bounds", "unbounded-unknown-bounds"}:
            target["bounds"] = {} if case == "unbounded-empty-bounds" else "unknown"
        if case == "unbounded-cross-feature":
            data.features["features"]["sweep"] = {
                "kind": "plane",
                "frame": "model",
                "bounds": {"x": [9.0, 11.0], "y": [4.0, 6.0], "z": [-1.27825, -1.27825]},
            }
            op["feature"] = "sweep"
    elif case == "list-feature":
        op["feature"] = ["target", "hole"]
    elif "z-disjoint" in case:
        op["stock_removal_bounds"].update(x=[30.0, 40.0], y=[30.0, 40.0])
        if case.startswith("unknown-z-"):
            op["to_z"] = "unknown"
        elif case.startswith("non-finite-z-"):
            op["to_z"] = math.nan
        else:
            op["to_z"] -= 2.0
        if case.endswith("missing-ref"):
            target["faces"].append("#41/UNMATCHED")
    elif case == "missing-kernel":
        data = replace(data, kernel=None)
    elif case == "missing-match":
        data.kernel["mapping"].clear()
    elif case == "missing-refs":
        target["faces"].clear()
    elif case == "boolean-index":
        data.kernel["mapping"][target["faces"][0]] = True
    elif case == "mapping-error":
        data.kernel["mapping_errors"] = {target["faces"][0]: "ambiguous"}
    elif case == "missing-extra-ref":
        # All refs resolve before any eligible patch can receive whole credit.
        target["faces"].append("#41/UNMATCHED")
    elif case == "missing-box":
        del data.kernel["faces"][0]["bbox_mm"]
    elif case == "malformed-box":
        box.pop()
    elif case == "non-finite-box":
        box[0] = math.nan
    elif case == "ambiguous-box":
        data.kernel["faces"].append(copy.deepcopy(data.kernel["faces"][0]))
    elif case == "no-eligible-plane":
        box[2] += 1.0
        box[5] += 1.0
    elif case == "missing-to-z":
        del op["to_z"]
    elif case == "nonplanar-box":
        box[5] += 0.1
    elif case == "boundary":
        op["stock_removal_bounds"].update(x=[-5.0, 15.0], y=[-2.0, 8.0])
    elif case == "keep-out":
        op["contour"]["keep_out"] = [{"at": [5.0, 3.0], "dia_mm": 2.0}]
    elif case == "missing-cutter":
        op["tool"] = "missing"
    elif case == "missing-sweep-frame":
        op["contour"]["sweep_frame"] = "missing"
    elif case == "missing-frame":
        producer["frame"] = "unknown"
    elif case in {"thin-known-cylinder", "thin-known-bspline"}:
        # Flat at to_z within tolerance, but a known non-planar STEP face is no plane.
        kind = "Cylinder" if case == "thin-known-cylinder" else "BSplineSurface"
        data.kernel["faces"][0]["kind"] = kind
    elif case.startswith(("missing-removal-z", "removal-z-")):
        # X/Y still hold the face; the removal volume's Z never establishes its plane.
        bounds = op["stock_removal_bounds"]
        if case == "missing-removal-z":
            del bounds["z"]
        else:
            bounds["z"] = {
                "removal-z-above": [op["to_z"] + 0.5, 0.0],
                "removal-z-descending": [0.0, -4.0],
                "removal-z-non-finite": [-4.0, math.nan],
            }[case]
    elif case == "signed-permutation":
        data.features["frames"]["A"].update(x=[0.0, 1.0, 0.0], y=[-1.0, 0.0, 0.0])
        op["stock_removal_bounds"].update(x=[-3.0, 9.0], y=[-16.0, 6.0])
    elif case == "inches":
        data.features["units"] = "in"
        data.features["frames"]["A"]["origin"] = [v / 25.4 for v in [5.0, 2.0, 1.0]]
        op["to_z"] /= 25.4
        for axis, span in op["stock_removal_bounds"].items():
            op["stock_removal_bounds"][axis] = [v / 25.4 for v in span]
        op["contour"]["keep_out"][0]["at"] = [100.0 / 25.4, 100.0 / 25.4]
    elif case.startswith("oblique-"):
        c = math.sqrt(0.5)
        data.features["frames"]["A"].update(x=[c, c, 0.0], y=[-c, c, 0.0])
        if case == "oblique-overlap":
            op["stock_removal_bounds"].update(x=[0.0, 5.0], y=[0.0, 5.0])
        elif case == "oblique-disjoint":
            op["stock_removal_bounds"].update(x=[30.0, 40.0], y=[30.0, 40.0])
        else:
            op["stock_removal_bounds"].update(x=[-30.0, 30.0], y=[-30.0, 30.0])
            if case == "oblique-keep-out":
                op["contour"]["keep_out"] = [{"at": [0.0, 0.0], "dia_mm": 2.0}]
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    trap_native_coverage(monkeypatch, forged_whole=case != "unbounded-own")
    assert (
        VALIDATOR["surface_cut_coverage"](
            own, VALIDATOR["Entries"](data.inventory), producer, op, target
        )
        == expected
    )


def test_endpoint_native_coverage_rejects_old_disc_credit_with_its_own_kernel(
    tmp_path, monkeypatch
):
    data = native_faced_endpoint_bundle(tmp_path)
    # Three mm of full-diameter depth also needs the 6 mm/118-degree drill's point clearance.
    data.features["features"]["hole"]["depth"] = [2.95, 5.0]
    consumer = data.plan["setups"][-1]
    # Isolate entry-producer coverage from the other, legacy zero surface routes.
    del consumer["zero"]
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    assert findings["blind_depth", "hole"]["status"] == "pass"
    entries = VALIDATOR["Entries"](data.inventory)
    independent = copy.deepcopy(data.kernel)
    calls = []

    def kernel():
        calls.append(True)
        return copy.deepcopy(independent)

    trap_native_coverage(monkeypatch)
    VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries, kernel)
    assert calls == [True]
    # The report's kernel remains whole. Only the oracle's own native face grows
    # outside the cut; the incidental disc still lies wholly within it.
    independent["faces"][0]["bbox_mm"][3] = 40.0
    with pytest.raises(ValueError, match="printed entry Z"):
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries, kernel)


@pytest.mark.parametrize("candidate", ["local-source", "cross-feature", "unbounded-cross-feature"])
@pytest.mark.parametrize(
    "coverage", ["whole", "partial", "missing-box", "empty-bounds", "unknown-bounds"]
)
def test_native_entry_producer_ignores_authored_disc_and_containment(
    tmp_path, monkeypatch, candidate, coverage
):
    data = native_faced_endpoint_bundle(tmp_path)
    producer, consumer = data.plan["setups"]
    op = producer["ops"][0]
    if coverage == "partial":
        op["stock_removal_bounds"].update(x=[4.0, 6.0], y=[2.0, 4.0])
    elif coverage == "missing-box":
        del data.kernel["faces"][0]["bbox_mm"]
    elif coverage in {"empty-bounds", "unknown-bounds"}:
        data.features["features"]["target"]["bounds"] = (
            {} if coverage == "empty-bounds" else "unknown"
        )
    if candidate in {"cross-feature", "unbounded-cross-feature"}:
        # Native coverage, not this incidental-disc-sized authored footprint,
        # decides whether another feature's cut produces the matched face.
        data.features["features"]["sweep"] = {
            "kind": "plane",
            "frame": "model",
            "bounds": {"x": [9.0, 11.0], "y": [4.0, 6.0], "z": [-1.27825, -1.27825]},
        }
        if candidate == "unbounded-cross-feature":
            del op["stock_removal_bounds"]
            op["contour"]["keep_out"] = []
        op["feature"] = "sweep"
        setup, source = consumer, f"{consumer['id']} stock_state.top_z"
    else:
        setup, source = producer, f"{producer['id']} op {op['op']} to_z"
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    trap_native_coverage(monkeypatch, forged_whole=True)
    monkeypatch.setitem(
        VALIDATOR["entry_producer"].__globals__,
        "covers_xy",
        lambda *args: pytest.fail("native producer used authored containment"),
    )
    result = VALIDATOR["entry_producer"](
        own, setup, -2.27825, "target", source, VALIDATOR["Entries"](data.inventory)
    )
    if candidate == "unbounded-cross-feature":
        assert result == "unknown"
    elif coverage == "whole":
        assert result == (producer, op)
    else:
        expected = None if coverage == "partial" and candidate == "cross-feature" else "unknown"
        assert result == expected


def test_endpoint_native_coverage_missing_match_rejects_numeric_stops_and_pass(
    tmp_path, monkeypatch
):
    data = native_faced_endpoint_bundle(tmp_path)
    # Keep the point below a valid guard so missing native coverage, not a real error, decides.
    data.features["features"]["hole"]["depth"] = [2.95, 5.0]
    del data.plan["setups"][-1]["zero"]
    numeric = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    independent = copy.deepcopy(data.kernel)
    independent["mapping"].clear()
    unknown = {
        (f.rule, f.subject): f.to_dict()
        for f in endpoint_findings(replace(data, kernel=independent))
    }
    assert unknown["blind_depth", "hole"]["status"] == "unknown"
    entries = VALIDATOR["Entries"](data.inventory)
    trap_native_coverage(monkeypatch, forged_whole=True)

    def check(report):
        return VALIDATOR["check_endpoints"](
            validator_test_bundle(data), report, entries, lambda: copy.deepcopy(independent)
        )

    check(unknown)
    with pytest.raises(ValueError, match="printed entry Z.*unknown"):
        check(numeric)
    forged = copy.deepcopy(unknown)
    forged["blind_depth", "hole"]["status"] = "pass"
    with pytest.raises(ValueError, match="endpoint verdict pass is not the unknown"):
        check(forged)


def test_local_native_entry_rejects_a_real_checker_whole_claim_with_own_partial_boxes(
    tmp_path, monkeypatch
):
    data = native_faced_endpoint_bundle(tmp_path)
    data.features["features"]["hole"]["depth"] = [2.95, 5.0]
    producer, consumer = data.plan["setups"]
    del consumer["zero"]
    local_face = copy.deepcopy(producer["ops"][0])
    local_face["op"] = 5
    consumer["ops"].insert(0, local_face)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    finding = findings["blind_depth", "hole"]
    assert finding["status"] == "pass"
    (row,) = finding["numbers"]["endpoints"]
    assert row["entry_from"] == f"{consumer['id']} op 5 to_z"
    assert VALIDATOR["numeric"](row["dro_entry_z"])
    independent = copy.deepcopy(data.kernel)
    independent["faces"][0]["bbox_mm"][3] = 40.0
    # Shared stock_states must reproduce the false whole/local-source claim. The
    # independent boxes prove partial, even though nominal and producer DRO grids
    # are identical here; partial->None would print the same claimed numeric entry.
    monkeypatch.setattr(tip_endpoints, "cut_coverage", lambda *args, **kwargs: "whole")
    trap_native_coverage(monkeypatch, forged_whole=True)
    with pytest.raises(ValueError, match="printed entry Z.*unknown"):
        VALIDATOR["check_endpoints"](
            validator_test_bundle(data),
            findings,
            VALIDATOR["Entries"](data.inventory),
            lambda: copy.deepcopy(independent),
        )


def test_native_entry_producer_skips_list_feature_inspection(tmp_path, monkeypatch):
    data = native_faced_endpoint_bundle(tmp_path)
    producer, consumer = data.plan["setups"]
    del consumer["stock_state"]["top_feature"]
    face_op = producer["ops"][0]
    producer["ops"].append({"op": 20, "do": "inspect", "feature": ["target", "hole"]})
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    trap_native_coverage(monkeypatch)
    assert VALIDATOR["entry_producer"](
        own,
        consumer,
        -2.27825,
        "top",
        f"{consumer['id']} stock_state.top_z",
        VALIDATOR["Entries"](data.inventory),
    ) == (producer, face_op)


@pytest.mark.parametrize(
    ("overlap", "to_z"),
    [(False, -4.27825), (True, -4.27825), (False, "unknown"), (True, "unknown")],
    ids=["disjoint", "overlapping", "unknown-z-disjoint", "unknown-z-overlapping"],
)
def test_native_entry_producer_keeps_an_earlier_plane_past_an_unrelated_other_depth_cut(
    tmp_path, monkeypatch, overlap, to_z
):
    data = native_faced_endpoint_bundle(tmp_path)
    producer, consumer = data.plan["setups"]
    face_op = producer["ops"][0]
    data.features["features"]["elsewhere"] = {"kind": "plane", "frame": "model"}
    later = copy.deepcopy(face_op)
    later.update(op=20, do="pocket", feature="elsewhere", to_z=to_z)
    if not overlap:
        later["stock_removal_bounds"].update(x=[30.0, 40.0], y=[30.0, 40.0])
    producer["ops"].append(later)
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    trap_native_coverage(monkeypatch, forged_whole=True)
    result = VALIDATOR["entry_producer"](
        own,
        consumer,
        -2.27825,
        "target",
        f"{consumer['id']} stock_state.top_z",
        VALIDATOR["Entries"](data.inventory),
    )
    assert result == ("unknown" if overlap else (producer, face_op))


@pytest.mark.parametrize(
    "coverage",
    [
        "whole",
        "partial",
        "missing-box",
        "empty-bounds",
        "unknown-bounds",
        "later-disjoint",
        "unknown-before-remake",
    ],
)
def test_carried_native_plane_coverage_cannot_fall_back_to_checker_credit(monkeypatch, coverage):
    data = carried_rectangular_source_plane_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    face = receiver["zero"]["z"]["face"]
    target = data.feature_definitions[face]
    target.update(at=[0.0, 0.0, 21.0055], axis=[0.0, 0.0, 1.0], dia=0.2)
    # A finite removal Z reaching the plane; only X/Y coverage varies below.
    source["ops"][0]["stock_removal_bounds"] = {
        "x": [-2.0, 2.0],
        "y": [-2.0, 2.0],
        "z": [20.0, 22.0],
    }
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    if coverage in {"empty-bounds", "unknown-bounds"}:
        own.feature_definitions[face]["bounds"] = {} if coverage == "empty-bounds" else "unknown"
    elif coverage == "partial":
        source["ops"][0]["stock_removal_bounds"].update(x=[-0.2, 0.2], y=[-0.2, 0.2])
    elif coverage == "missing-box":
        del own.kernel["faces"][0]["bbox_mm"]
    elif coverage == "later-disjoint":
        later = copy.deepcopy(source["ops"][0])
        later["op"] = 20
        later["stock_removal_bounds"] = {
            "x": [3.0, 4.0],
            "y": [-0.2, 0.2],
            "z": [20.0, 22.0],
        }
        source["ops"].append(later)
        key = f"{source['id']}:{source['ops'][0]['op']}"
        own.kernel["ops"][f"{source['id']}:20"] = copy.deepcopy(own.kernel["ops"][key])
    elif coverage == "unknown-before-remake":
        remake = copy.deepcopy(source["ops"][0])
        remake["op"] = 20
        source["ops"][0]["to_z"] = 22.0
        source["ops"].append(remake)
        key = f"{source['id']}:{source['ops'][0]['op']}"
        own.kernel["ops"][f"{source['id']}:20"] = copy.deepcopy(own.kernel["ops"][key])
    trap_native_coverage(monkeypatch, forged_whole=True)
    plane = VALIDATOR["carried_source_plane"](
        own, VALIDATOR["Entries"](data.inventory), receiver, face, 0
    )
    if coverage in {"whole", "later-disjoint", "unknown-before-remake"}:
        assert plane["physical"] == pytest.approx(21.01)
        assert plane["ref"] == target["faces"][0]
    else:
        assert "unknown" in plane


@pytest.mark.parametrize(
    ("thickness", "forged"),
    [
        # The printed blind tip 1 mm deeper than the planned one; every analytical Z intact.
        (None, {"dro_tip_z": -1.0}),
        # The printed entry and tip both 1 mm into the part: the same depth, self-consistent.
        (None, {"dro_entry_z": -1.0, "dro_tip_z": -1.0}),
        # The depth the printed tip leaves claimed 1 mm deeper than it is.
        (None, {"dro_depth_mm": 1.0}),
        # A through hole's printed exit face and tip moved together.
        (20.0, {"dro_exit_face": -1.0, "dro_tip_z": -1.0}),
        # The break-through the printed tip leaves claimed 1 mm longer.
        (20.0, {"dro_exit_mm": 1.0}),
    ],
)
def test_endpoint_oracle_holds_the_printed_endpoint_to_the_plan_on_the_grid(thickness, forged):
    row, check = printed_endpoint(
        drill_bundle(depth_mm=None if thickness else 40.0, thickness=thickness)
    )
    for field, delta in forged.items():
        row[field] += delta
    with pytest.raises(ValueError):
        check()


def test_endpoint_oracle_holds_the_depth_band_floor_the_traveler_stops_on():
    # A 38-42 depth band: the printed floor is what the traveler's STOP box compares the
    # printed depth against. Reported unknown, the box can never print.
    data = drill_bundle(depth_mm=40.0)
    data.features["features"]["hole"]["depth"] = [38.0, 42.0]
    row, check = printed_endpoint(data)
    assert row["depth_floor_mm"] == 38.0
    row["depth_floor_mm"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("producer_grid", [0.01, 0.1])
def test_endpoint_oracle_starts_a_hole_on_the_face_its_producer_cut_on_its_own_grid(
    tmp_path, producer_grid
):
    # S1, a coarser mill, faces the hole's entry to -2.27825; S2 (0.005 grid) drills a
    # 2.95-3.00 deep blind hole from it. That face stands where S1's DRO stopped, rounded up
    # on S1's grid, not where S2's grid would round the nominal.
    path = surface_plan(tmp_path, coarse=True, depth="[2.95, 3.0]")
    inventory = path.with_name("inventory.toml")
    text = inventory.read_text(encoding="utf-8")
    authored = "resolution_mm = { value = 0.01,"
    assert text.count(authored) == 1
    coarse = text.replace(authored, f"resolution_mm = {{ value = {producer_grid},", 1)
    inventory.write_text(coarse, encoding="utf-8")
    data = load_bundle(path)
    row, check = printed_endpoint(data)
    entries = VALIDATOR["Entries"](data.inventory)
    consumer = next(setup for setup in data.plan["setups"] if setup["id"] == "S2")
    grid = VALIDATOR["dro_grid"](consumer, data.features, entries)
    # Forged: the entry rounded on S2's grid and the drill run from there with its depth
    # claimed unchanged, so its tip runs past the 3.00 mm limit below the face S1 cut.
    entry = VALIDATOR["dro_up"](row["entry_z"], grid)
    assert entry < row["dro_entry_z"]
    planned_tip = row["tip_z"] + entry - row["entry_z"]
    tip = VALIDATOR["dro_up"](planned_tip, grid)
    row.update(dro_entry_z=entry, dro_tip_z=tip, dro_depth_mm=row["depth_mm"] - (tip - planned_tip))
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("status", ["assumed", "illustrative", None, "bare"])
def test_endpoint_oracle_keeps_declared_stops_without_certifying_untrusted_grid(status):
    data = drill_bundle(thickness=20.0)
    baseline = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    assert baseline["blind_depth", "hole"]["status"] == "pass"
    machine = data.inventory["machines"][data.plan["setups"][0]["machine"]]
    fact = machine["resolution_mm"]
    if status == "bare":
        machine["resolution_mm"] = fact["value"]
    elif status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    finding = findings["blind_depth", "hole"]
    assert finding["status"] == "unknown"
    (before,) = baseline["blind_depth", "hole"]["numbers"]["endpoints"]
    (after,) = finding["numbers"]["endpoints"]
    assert {key: value for key, value in after.items() if key != "dro_grid_debt"} == before
    entries = VALIDATOR["Entries"](data.inventory)
    VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
    finding["status"] = "pass"
    with pytest.raises(ValueError, match="endpoint verdict"):
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
    finding["status"] = "unknown"
    after["dro_tip_z"] -= 1.0
    with pytest.raises(ValueError, match="printed tip Z"):
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)


def test_centre_oracle_holds_the_printed_quill_endpoint(tmp_path):
    # The prepared pivot-shaft centre, its printed tip 0.5 mm deeper and its printed
    # depth to match: the traveler would send the quill past the Table 6 depth.
    row, check, _ = centre_findings(tmp_path)
    check()
    row["dro_tip_z"] -= 0.5
    row["dro_depth_mm"] += 0.5
    with pytest.raises(ValueError):
        check()


DEEPER = {**DEEP, "depth_over_dia": 8.0, "sfm_factor": 0.3, "cite": "deeper row"}


def speed_finding(data):
    """The engine's speeds_feeds finding for ``data``'s one drill op, and a validator call
    that checks it against the hole depths the validator derives from the plan."""
    findings = {
        (f.rule, f.subject): f.to_dict()
        for f in [*endpoint_findings(data), *speeds_feeds.evaluate(data)]
    }
    entries = VALIDATOR["Entries"](data.inventory)
    depths = VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
    setup = data.plan["setups"][0]
    finding = findings["speeds_feeds", "S1:10"]

    def check():
        VALIDATOR["check_speeds"](
            data.plan,
            data.features,
            setup,
            setup["ops"][0],
            finding,
            entries,
            data.cutting_data,
            data.feature_definitions,
            depths,
        )

    return finding, check


@pytest.mark.parametrize(
    ("depth_mm", "thickness", "deep", "corruption", "wrong_rpm"),
    [
        # 6.3 x D blind: the derated 750 rpm, reported as the un-derated 1550.
        (40.0, None, (DEEP,), "rpm", 1550),
        # The same, made self-consistent: no derate row, factor or ratio reported.
        (40.0, None, (DEEP,), "fields", 1550),
        # The same, dodging the row by naming an operation no deep-hole row names.
        (40.0, None, (DEEP,), "operation", 1550),
        # 3.1 x D through, by local thickness rather than the tip.
        (None, 20.0, (DEEP,), "rpm", 1550),
        # 9.4 x D: the deepest exceeded tier (450 rpm) governs, not the shallower one.
        (60.0, None, (DEEP, DEEPER), "rpm", 750),
        # Exactly 3 x D is not deeper: the un-derated 1550 stands; a derated one is wrong.
        (3.0 * 6.35, None, (DEEP,), "rpm", 750),
    ],
)
def test_speed_oracle_holds_rpm_to_the_governing_deep_hole_derate(
    depth_mm, thickness, deep, corruption, wrong_rpm
):
    finding, check = speed_finding(drill_bundle(depth_mm=depth_mm, thickness=thickness, deep=deep))
    check()
    row = finding["numbers"]
    if corruption in {"fields", "operation"}:
        for field in ("depth_over_dia", "deep_hole_row", "deep_hole_sfm_factor"):
            row.pop(field)
    if corruption == "operation":
        row["operation"] = "ream"
    row["rpm"] = wrong_rpm
    row["feed_mm_min"] = wrong_rpm * row["flutes"] * row["chip_load_mm_per_tooth"]
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("depth_mm", "deep"),
    [
        # No planned depth: no ratio, so no derate and no RPM.
        (None, (DEEP,)),
        # Two rows claim the same threshold: no one governs.
        (40.0, (DEEP, {**DEEP, "sfm_factor": 0.7, "cite": "tied row"})),
        # The governing row is marked for verification: it derates, but proves nothing.
        (40.0, ({**DEEP, "verify": True},)),
    ],
)
def test_speed_oracle_never_passes_a_derate_it_cannot_resolve(depth_mm, deep):
    finding, check = speed_finding(drill_bundle(depth_mm=depth_mm, deep=deep))
    check()
    finding["status"] = "pass"
    with pytest.raises(ValueError):
        check()


def resped(row, sfm):
    """Recompute ``row``'s derated RPM and feed per tooth from ``sfm`` and its own spindle
    range, diameter, flutes and chip load: a self-consistent report."""
    raw = 12 * sfm * row["deep_hole_sfm_factor"] / (math.pi * row["diameter_in"])
    row["sfm"] = sfm
    row["rpm"] = round(max(row["rpm_min"], min(row["rpm_max"], raw)) / 50) * 50
    row["feed_mm_min"] = row["rpm"] * row["flutes"] * row["chip_load_mm_per_tooth"]


UNRELATED = {
    "material_class": "low_carbon_steel",
    "tool_material": "HSS",
    "operation": "drill",
    "diameter_range": [3.0, 13.0],
    "sfm": 350.0,
    "chip_load_mm_per_tooth": 0.05,
    "cite": "unrelated row",
}


@pytest.mark.parametrize(
    "corruption",
    [
        # The spindle floor raised to 800 so the 750 rpm drill is clamped up to it.
        "machine_bound",
        # A cited 350 sfm row for another operation, or for another tool material.
        "other_operation",
        "other_tool_material",
        # One more flute than the inventory drill has, its feed recomputed.
        "flutes",
        # The inventory drill's diameter is now unknown, the formerly valid row kept.
        "unknown_diameter",
    ],
)
def test_speed_oracle_takes_every_operand_from_the_inputs_not_the_report(corruption):
    data = drill_bundle(depth_mm=40.0)
    finding, check = speed_finding(data)
    check()
    row = finding["numbers"]
    if corruption == "machine_bound":
        row["rpm_min"] = 800
        resped(row, row["sfm"])
        assert row["rpm"] == 800
    elif corruption in {"other_operation", "other_tool_material"}:
        key, value = {"other_operation": ("operation", "ream")}.get(
            corruption, ("tool_material", "carbide")
        )
        data.cutting_data["cut"].append({**UNRELATED, key: value})
        resped(row, UNRELATED["sfm"])
    elif corruption == "flutes":
        row["flutes"] += 1
        resped(row, row["sfm"])
    else:
        data.inventory["tools"]["drill"]["dia_mm"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("flag", [True, "unknown"])
@pytest.mark.parametrize("debt", ["machine", "tool", "material"])
def test_speed_oracle_never_passes_a_row_on_unverified_inputs(debt, flag):
    # The engine leaves the derated 750 rpm unknown on an input flagged for verification
    # or left unknown; the report claims a pass and drops the verification flags it prints.
    data = drill_bundle(depth_mm=40.0)
    if debt == "material":
        data.plan["stock"]["material_verify"] = flag
    else:
        data.inventory[f"{debt}s"][{"machine": "mill", "tool": "drill"}[debt]]["verify"] = flag
    finding, check = speed_finding(data)
    check()
    assert finding["status"] == "unknown"
    finding["status"] = "pass"
    finding["numbers"].update(material_verify=False, rpm_range_verify=False)
    with pytest.raises(ValueError):
        check()


def solids(flag):
    """A one-box body whose own record carries ``flag`` as its verification."""
    box = {"name": "base", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [100, 100, 30]}
    return [{**box, "verify": flag}]


@pytest.mark.parametrize(
    ("path", "value", "verdict"),
    [
        # The drill's verification left unknown, on its record or on a fact it is read by.
        (("tools", "drill", "verify"), "unknown", "unknown"),
        (("tools", "drill", "dia_mm"), {"value": 6.35, "verify": "unknown"}, "unknown"),
        # The drill, or every tool, left unknown.
        (("tools", "drill"), "unknown", "unknown"),
        (("tools",), "unknown", "unknown"),
        # A collection the drill is read through left unknown.
        (("tools", "drill", "flutes"), "unknown", "unknown"),
        # The machine's verification left unknown.
        (("machines", "mill", "verify"), "unknown", "unknown"),
        # A body solid's verification is the solid's, not its owner's identity.
        (("machines", "mill", "solids"), solids("unknown"), "pass"),
        (("machines", "mill", "solids"), solids(True), "pass"),
        (("tools", "drill", "solids"), solids("unknown"), "pass"),
    ],
)
def test_reference_oracle_reads_identity_verification_as_the_checker_does(path, value, verdict):
    """An identity the inventory leaves unknown, or whose own verification it leaves
    unknown, resolves unverified; a record it lists (a body's solid) does not qualify it.
    The engine's verdict is accepted, every other one rejected."""
    data = drill_bundle()
    set_key(path, value)(data.inventory)
    check_reference_verdict(data, path[1] if len(path) > 1 else "drill", verdict)


# A verification and its opposite: an unverified identity's is a verified one.
OPPOSITE = {True: False, False: True, "unknown": False}


@pytest.mark.parametrize("prefix", [False, True])
@pytest.mark.parametrize("flag", [True, False, "unknown"])
def test_reference_oracle_reads_an_accessory_as_the_machine_listing_it(flag, prefix):
    """A machine accessory is as verified as the record of the machine listing it, under
    whatever key: a slash-bearing key names that machine, not a member of an identity its
    prefix names (here, one carrying the opposite verification)."""
    data = drill_bundle()
    machines = data.inventory["machines"]
    machines["spare/mill"] = {"kind": "mill", "included": ["spare-vise"], "verify": flag}
    if prefix:
        machines["spare"] = {"kind": "mill", "verify": OPPOSITE[flag]}
    data.plan["setups"][0].setdefault("hold", {})["fixture"] = "spare-vise"
    check_reference_verdict(data, "spare-vise", "pass" if flag is False else "unknown")


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("slot", ["checks", "zero"])
@pytest.mark.parametrize("flag", [True, False, "unknown"])
def test_reference_oracle_reads_each_item_in_the_category_its_slot_selects(flag, slot, qualified):
    """One key two categories list is two items: the fixture a hold selects, and the gauge
    an inspection check or a zero pick-up selects (a spindle slot reads gauges after
    tools), are each as verified as their own record, never the other's, under the
    subject the checker gives each. A selection naming its category (``gauges.pins``) is
    that item, as its bare key in its slot is."""
    data = drill_bundle()
    data.inventory["fixtures"] = {"pins": {"kind": "fixture", "verify": OPPOSITE[flag]}}
    data.inventory["gauges"] = {"pins": {"kind": "pin_gauge", "verify": flag}}
    fixture, gauge = ("fixtures.pins", "gauges.pins") if qualified else ("pins", "pins")
    setup = data.plan["setups"][0]
    setup["hold"] = {"fixture": fixture}
    if slot == "checks":
        setup["ops"][0]["checks"] = {"dia": gauge}
    else:
        setup["zero"] = {"x": {"tool": gauge}}
    subjects = {
        (row.numbers.get("category"), row.numbers.get("reference")): row.subject
        for row in tool_resolves.evaluate(data)
        if "named_in" not in row.numbers
    }
    for category, flagged in (("gauges", flag), ("fixtures", OPPOSITE[flag])):
        verdict = "pass" if flagged is False else "unknown"
        check_reference_verdict(data, subjects[category, "pins"], verdict)


def check_reference_verdict(data, subject, verdict):
    """The engine's ``tool_resolves`` finding on ``subject`` is ``verdict``: the validator
    accepts it, and rejects it with any other status."""
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    key = "tool_resolves", subject
    assert findings[key]["status"] == verdict
    VALIDATOR["check_references"](data.plan, data.features, entries, findings)
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_references"](
                data.plan,
                data.features,
                entries,
                {**findings, key: {**findings[key], "status": forged}},
            )


@pytest.mark.parametrize(("field", "value"), [("dia_mm", 6.35), ("dia_in", 0.25), ("dia", 6.35)])
@pytest.mark.parametrize(
    ("case", "verdict"),
    [
        ("bare", "pass"),
        ("catalogue", "pass"),
        ("measured", "pass"),
        ("assumed", "unknown"),
        ("illustrative", "unknown"),
        ("omitted", "unknown"),
        ("unknown_value", "unknown"),
    ],
)
def test_reference_oracle_qualifies_only_its_selected_diameter(field, value, case, verdict):
    data = drill_bundle()
    drill = data.inventory["tools"]["drill"]
    for name in ("dia_mm", "dia_in", "dia"):
        drill.pop(name, None)
    drill["units"] = "mm"
    fact = value if case == "bare" else {"value": value}
    if case not in {"bare", "catalogue"}:
        fact = synthetic_fact(value)
        if case in {"assumed", "illustrative"}:
            fact["measured"]["status"] = case
        elif case == "omitted":
            del fact["measured"]["status"]
        elif case == "unknown_value":
            fact["value"] = "unknown"
    drill[field] = fact
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    key = "tool_resolves", "drill"
    native = findings[key]
    trusted = verdict == "pass"
    assert native["status"] == verdict
    assert native["numbers"]["verified"] is trusted
    if trusted:
        assert native["numbers"]["dia_mm"] == pytest.approx(6.35)
    else:
        assert "dia_mm" not in native["numbers"]
    assert VALIDATOR["check_references"](data.plan, data.features, entries, findings) == []
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_references"](
                data.plan, data.features, entries, {**findings, key: {**native, "status": forged}}
            )
    for numbers in [
        {**native["numbers"], "verified": not trusted},
        {**native["numbers"], "dia_mm": 6.6},
        {
            name: number
            for name, number in native["numbers"].items()
            if name != ("dia_mm" if trusted else "verified")
        },
    ]:
        with pytest.raises(ValueError):
            VALIDATOR["check_references"](
                data.plan, data.features, entries, {**findings, key: {**native, "numbers": numbers}}
            )


@pytest.mark.parametrize("field", ["flute_len_mm", "oal_mm"])
def test_reference_oracle_does_not_consume_unrelated_measurement_records(field):
    data = drill_bundle()
    fact = synthetic_fact(20.0)
    fact["measured"]["status"] = "illustrative"
    data.inventory["tools"]["drill"][field] = fact
    check_reference_verdict(data, "drill", "pass")


@pytest.mark.parametrize("case", ["assumed", "illustrative", "omitted"])
def test_reference_oracle_keeps_named_only_diameters_out_of_identity_verification(case):
    data = drill_bundle()
    fact = synthetic_fact(6.35)
    if case == "omitted":
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = case
    data.inventory["tools"]["named-drill"] = {"kind": "drill", "dia_mm": fact}
    data.plan["setups"][0]["note"] = "Also listed: tools.named-drill."
    check_reference_verdict(data, "tools.named-drill", "pass")


def incomplete_reference_data(field, value, *, named=False):
    """An intentionally invalid measurement for schema and raw-reader boundary tests."""
    data = drill_bundle()
    drill = copy.deepcopy(data.inventory["tools"]["drill"])
    for name in ("dia_mm", "dia_in", "dia"):
        drill.pop(name, None)
    fact = synthetic_fact(value)
    del fact["measured"]["instrument"]
    drill.update(units="mm", **{field: fact})
    data.inventory["tools"]["named-drill" if named else "drill"] = drill
    if named:
        data.plan["setups"][0]["note"] = "Also listed: tools.named-drill."
    return data


@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize(("field", "value"), [("dia_mm", 6.35), ("dia_in", 0.25), ("dia", 6.35)])
def test_reference_measurement_schema_rejects_incomplete_records_even_for_named_items(
    field, value, named
):
    data = incomplete_reference_data(field, value, named=named)
    with pytest.raises(ValidationError, match="instrument"):
        Inventory.model_validate(data.inventory)


@pytest.mark.parametrize(("field", "value"), [("dia_mm", 6.35), ("dia_in", 0.25), ("dia", 6.35)])
def test_reference_oracle_defensively_rejects_incomplete_unvalidated_measurements(field, value):
    """Raw-reader contract only: this inventory cannot pass the producer's schema."""
    data = incomplete_reference_data(field, value)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    key = "tool_resolves", "drill"
    native = findings[key]
    assert native["status"] == "unknown"
    assert native["numbers"]["verified"] is False
    assert "dia_mm" not in native["numbers"]
    assert VALIDATOR["check_references"](data.plan, data.features, entries, findings) == []
    for forged in [
        {**native, "status": "pass"},
        {**native, "numbers": {**native["numbers"], "verified": True}},
        {**native, "numbers": {**native["numbers"], "dia_mm": 6.35}},
    ]:
        with pytest.raises(ValueError):
            VALIDATOR["check_references"](
                data.plan, data.features, entries, {**findings, key: forged}
            )


QUALIFIED_SELECTIONS = {
    # slot: (category, key, its record, where the plan selects it)
    "machine": ("machines", "mill", {"kind": "mill"}, lambda setup: (setup, "machine")),
    "tool": ("tools", "drill", {"kind": "drill"}, lambda setup: (setup["ops"][0], "tool")),
    "fixture": (
        "fixtures",
        "pins",
        {"kind": "fixture"},
        lambda setup: (setup.setdefault("hold", {}), "fixture"),
    ),
    "gauge": (
        "gauges",
        "pins",
        {"kind": "pin_gauge"},
        lambda setup: (setup["ops"][0].setdefault("checks", {}), "dia"),
    ),
}


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("flag", [True, False, "unknown", "absent"])
@pytest.mark.parametrize("slot", sorted(QUALIFIED_SELECTIONS))
def test_reference_coverage_reads_a_selection_as_the_item_it_selects(slot, flag, qualified):
    """A machine, tool, fixture or gauge the plan selects by its bare key or by
    ``<category>.<key>`` is the one item the checker selects: its native finding is
    accepted with its own verdict (an item not listed an error), and no other status is."""
    data = drill_bundle()
    category, key, item, place = QUALIFIED_SELECTIONS[slot]
    data.inventory.setdefault(category, {}).setdefault(key, item)
    if flag == "absent":
        key = "unlisted"
    else:
        data.inventory[category][key]["verify"] = flag
    target, field = place(data.plan["setups"][0])
    target[field] = f"{category}.{key}" if qualified else key
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    items = {name: row for name, row in findings.items() if "category" in row["numbers"]}
    (selected,) = (
        row
        for row in items.values()
        if (row["numbers"]["category"], row["numbers"]["reference"]) == (category, key)
        and "named_in" not in row["numbers"]
    )
    verdict = "error" if flag == "absent" else "pass" if flag is False else "unknown"
    assert selected["status"] == verdict
    entries = VALIDATOR["Entries"](data.inventory)
    VALIDATOR["check_references"](data.plan, data.features, entries, findings)
    for name, row in items.items():
        for forged in sorted({"pass", "unknown", "error"} - {row["status"]}):
            with pytest.raises(ValueError):
                VALIDATOR["check_references"](
                    data.plan, data.features, entries, {**findings, name: {**row, "status": forged}}
                )


@pytest.mark.parametrize(
    ("listing", "fact", "verdict"),
    [
        ("listed", {}, "pass"),
        ("unverified", {}, "unknown"),
        ("listed", {"rpm": "unknown"}, "unknown"),
        ("unlisted", {}, "error"),
        ("accessory", {}, "error"),
    ],
)
def test_make_operation_oracle_holds_each_row_to_its_own_verdict(listing, fact, verdict):
    """Each make operation of a shop-made item a setup holds with is a ``tool_resolves``
    subject of its own (``<category>.<key> make op <n>``). Its native finding is accepted
    with its own verdict: a tool the shop's tools do not list an error, even one a machine
    carries as an accessory; an unverified tool or an unstated fact unknown. A report
    missing it, giving it any other status (alone, or with its unknowns and presence
    restated to agree), or naming another tool, item, operation or solid, is not."""
    data = drill_bundle()
    if listing in ("listed", "unverified"):
        data.inventory["tools"]["endmill-6"] = {**END_MILL, "verify": listing == "unverified"}
    if listing == "accessory":
        data.inventory["machines"]["mill"]["included"] = ["endmill-6"]
    beam = {"name": "beam", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [60, 10, 8]}
    data.inventory["fixtures"] = {
        "bridge": {"kind": "custom", "solids": [beam], "make_ops": [{**MAKE_OP, **fact}]}
    }
    data.plan["setups"][0]["hold"] = {"fixture": "bridge"}
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    key = "tool_resolves", "fixtures.bridge make op 1"
    native = findings[key]
    assert native["status"] == verdict
    entries = VALIDATOR["Entries"](data.inventory)

    def check(rows):
        VALIDATOR["check_make_ops"](data.plan, data.features, entries, rows)

    check(findings)
    with pytest.raises(ValueError):
        check({k: row for k, row in findings.items() if k != key})
    agreeing = {
        "pass": {"present": True, "unknown": []},
        "unknown": {"present": True, "unknown": ["rpm"]},
        "error": {"present": False, "unknown": []},
    }
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        for numbers in (native["numbers"], {**native["numbers"], **agreeing[forged]}):
            with pytest.raises(ValueError):
                check({**findings, key: {**native, "status": forged, "numbers": numbers}})
    identities = {"tool": "endmill-8", "item": "fixtures.other", "make_op": 2, "solid": "head"}
    for field, value in identities.items():
        numbers = {**native["numbers"], field: value}
        with pytest.raises(ValueError):
            check({**findings, key: {**native, "numbers": numbers}})


def test_geometry_validation_holds_a_make_operation_to_its_own_verdict(
    tmp_path, freecad_kernel, monkeypatch
):
    """A geometry bundle's report exits 2 on its expected fixture errors, so its exit
    cannot speak for a make operation's verdict: the row is held to the verdict the
    validator gives it, never forged from unknown to a pass or waived, nor restated with
    evidence made to agree. Here the nest fixture-holds holds S3 with is shop-made by
    one operation whose speed is unknown."""
    examples = ROOT / "examples"
    documents = {
        path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
        for path in examples.rglob("*.toml")
    }
    case = next(c for c in VALIDATOR["GEOMETRY_CASES"] if c[:2] == ("fixture-holds", "plan.toml"))
    folder = examples / "geometry" / "fixture-holds"
    plan = documents[(folder / "plan.toml").resolve()]
    inventory = documents[(examples / "geometry" / "inventory.toml").resolve()]
    features = documents[(folder / plan["features"]).resolve()]
    made = {**MAKE_OP, "tool": "em-8-std", "rpm": "unknown"}
    inventory["fixtures"]["test-nest"]["make_ops"] = [made]
    data = SimpleNamespace(plan=plan, features=features, inventory=inventory)
    native = [json.loads(json.dumps(f.to_dict())) for f in tool_resolves.evaluate(data)]
    subject = "fixtures.test-nest make op 1"
    (row,) = (r for r in native if r["subject"] == subject)
    assert (row["status"], row["numbers"]["unknown"]) == ("unknown", ["rpm"])
    golden = json.loads((folder / "expected" / "report.json").read_bytes())
    validate = VALIDATOR["validate_geometry_fixture"]
    from prechips.sheet import render_traveler

    # The injected make operation is absent from the committed sheet. Render
    # the edited inventory and its real debt, rather than asking that old HTML
    # to disclose a finding which did not exist when it was generated.
    sheet_rows = [r for r in golden["findings"] if r["rule"] != "tool_resolves"] + native
    sheet_report = {**golden, "findings": sheet_rows}
    sheet_findings = [
        Finding(r["rule"], r["subject"], r["status"], r["numbers"], r["cite"], r["message"])
        for r in sheet_rows
    ]
    rendered_bundle = replace(load_bundle(folder / "plan.toml"), inventory=inventory)
    rendered = tmp_path / "expected"
    rendered.mkdir()
    (rendered / "traveler.html").write_text(
        render_traveler(rendered_bundle, sheet_findings, sheet_report),
        encoding="utf-8",
    )
    check_sheet = validate.__globals__["check_sheet"]
    monkeypatch.setitem(
        validate.__globals__,
        "check_sheet",
        lambda _folder, report, _subdir: check_sheet(tmp_path, report),
    )

    def check(make_row):
        # The report re-hashed on the edited inventory: the checker's own tool_resolves
        # rows, with the make operation's as given.
        rows = [r for r in golden["findings"] if r["rule"] != "tool_resolves"]
        rows += [make_row if r["subject"] == subject else r for r in native]
        report = {**golden, "findings": rows}
        monkeypatch.setitem(validate.__globals__, "read_report", lambda path: report)
        validate(case, documents)

    check(row)
    for status, numbers in (
        ("pass", row["numbers"]),
        ("not_applicable", row["numbers"]),
        ("pass", {**row["numbers"], "unknown": []}),
    ):
        with pytest.raises(ValueError, match="make op"):
            check({**row, "status": status, "numbers": numbers})


PILOTS = [
    ROOT / "examples" / "pivot-shaft" / "plan.toml",
    ROOT / "examples" / "rocker-arm" / "plan.toml",
    ROOT / "examples" / "pivot-bracket" / "plan.toml",
    ROOT / "examples" / "cone-pivot-post" / "built-up.toml",
]
CATEGORIES = ("machines", "tools", "holders", "fixtures", "gauges")
# Collections an identity may leave "unknown" (resolution.inventory_record).
COLLECTIONS = ("members", "nominal_dia_mm", "nominal_dia_cite", "holders", "sizes", "sizes_mm")
COLLECTIONS += ("sizes_in", "styles", "ranges_in", "heights_in", "flutes")
COLLECTIONS += ("standard_accessories", "included")
# Members a drill index's declared coverage generates, or not, and a qctp set's holder slots.
INDEX_MEMBERS = ("#1", "#60", "#61", "A", "Z", "1/16", "1/4", "33/64", "1/2", "17/32")
QCTP_MEMBERS = ("1-turning-facing", "2-boring-turning-facing", "4-heavy-boring", "7-parting")


def identities(root, item):
    """Every identity ``root`` names or may generate: itself, each declared member, each
    accessory, each member its declared sizes, flutes, styles, ranges, holders or coverage
    may generate, and one it declares nowhere."""
    if not isinstance(item, dict):
        return {root}

    def declared(*keys):
        return [v for key in keys if isinstance(item.get(key), (list, dict)) for v in item[key]]

    members = declared("members", "holders", "nominal_dia_mm", "sizes", "styles")
    members += [*INDEX_MEMBERS, *QCTP_MEMBERS, *(f"{size}mm" for size in declared("sizes_mm"))]
    for key in ("sizes_in", "heights_in", "ranges_in"):
        members += [f"{size}in" for size in inch_sizes(item.get(key))]
    members += [f"{size}in-{n}fl" for size in inch_sizes(item.get("sizes_in")) for n in (2, 3, 4)]
    accessories = declared("standard_accessories", "included")
    return {root, *accessories, *(f"{root}/{member}" for member in [*members, "undeclared"])}


@functools.cache
def pilot_inventories():
    """``[(inventory, refs)]``: each inventory the pilots read, as authored, with every
    identity its pilots' setups select (resolution.setup_items)."""
    plans = {}
    for path in PILOTS:
        bundle = load_bundle(path)
        inventory = (path.parent / bundle.plan["paths"]["inventory"]).resolve()
        plans.setdefault(inventory, []).append(bundle)
    return [
        (
            tomllib.loads(path.read_text(encoding="utf-8")),
            {
                ref
                for bundle in selecting
                for setup in bundle.plan["setups"]
                for _, ref, _ in setup_items(bundle, setup)
            },
        )
        for path, selecting in plans.items()
    ]


def declared_debts(item):
    """``[(label, record)]``: ``item`` declaring, clearing or leaving unknown each
    verification, presence, coverage, fact, listed solid, collection and member it can
    carry."""
    edits = [
        *((f"verify={flag}", {"verify": flag}) for flag in (True, False, "unknown")),
        *((f"present={flag}", {"present": flag}) for flag in (True, False, "unknown")),
        ("coverage", {"coverage": "verify on site"}),
        *((f"solid verify={flag}", {"solids": solids(flag)}) for flag in (True, False, "unknown")),
        *((f"{key}=unknown", {key: "unknown"}) for key in COLLECTIONS if key in item),
    ]
    if not any(key.startswith("body_dia") for key in item):
        edits += [
            (f"fact verify={flag}", {"body_dia_mm": {"value": 10.0, "verify": flag}})
            for flag in (True, False, "unknown")
        ]
    result = [(label, {**item, **edit}) for label, edit in edits]
    members = item.get("members")
    for name, member in members.items() if isinstance(members, dict) else ():
        edited = [("unknown", "unknown")]
        if isinstance(member, dict):
            edited += declared_debts({key: v for key, v in member.items() if key != "members"})
        result += [
            (f"member {name} {label}", {**item, "members": {**members, name: value}})
            for label, value in edited
        ]
    return result


def rekeyed(root, item):
    """``[(label, {key: record})]``: ``item`` under the slash-bearing key ``root/owner``
    with each verification, alone or beside an identity of its prefix key ``root``
    carrying the opposite one."""
    owner, result = f"{root}/owner", []
    for flag in (True, False, "unknown"):
        prefix = {key: item[key] for key in ("kind",) if key in item}
        record = {**item, "verify": flag}
        result += [
            (f"as {owner} verify={flag}", {owner: record}),
            (
                f"as {owner} verify={flag} beside {root}",
                {owner: record, root: {**prefix, "verify": OPPOSITE[flag]}},
            ),
        ]
    return result


def mutations(inventory):
    """``(label, category, keys, edited category)``: each category left unknown, and each
    identity of it left unknown, carrying each of its :func:`declared_debts`, or re-keyed
    (:func:`rekeyed`); ``keys`` are the identities the edit touches."""
    for category in CATEGORIES:
        items = inventory.get(category, {})
        yield f"{category}=unknown", category, (), "unknown"
        for root, item in items.items():
            edits = [("unknown", {root: "unknown"})]
            if isinstance(item, dict):
                edits += [(label, {root: edited}) for label, edited in declared_debts(item)]
                edits += rekeyed(root, item)
            rest = {key: value for key, value in items.items() if key != root}
            for label, keyed in edits:
                yield f"{root} {label}", category, (root, *keyed), {**rest, **keyed}


def test_identity_model_preserves_authored_and_mutated_inventory_facts():
    """Protect raw-to-model normalization, not agreement between shared resolver wrappers.

    Keep every factory label and transformed identity, including explicit unknown
    categories, slash-bearing owners, nested member debts and generated dimensions.
    The independently authored facts must survive loading without losing verification.
    Focused consumer tests below/above hold those facts to explicit verdicts.
    """
    for inventory, _ in pilot_inventories():
        base = Inventory.model_validate(inventory).model_dump(exclude_unset=True)
        assert base == inventory
        for label, category, _, edited in [("authored", None, (), None), *mutations(inventory)]:
            edit = {} if category is None else {category: edited}
            loaded = {**base, **Inventory.model_validate(edit).model_dump(exclude_unset=True)}
            assert loaded == {**inventory, **edit}, label


def saw_finding(data):
    """The engine's speeds_feeds finding for ``data``'s one saw cut and a validator call."""
    findings = {(f.rule, f.subject): f.to_dict() for f in speeds_feeds.evaluate(data)}
    setup = data.plan["setups"][0]
    finding = findings["speeds_feeds", "S1:10"]

    def check():
        VALIDATOR["check_speeds"](
            data.plan,
            data.features,
            setup,
            setup["ops"][0],
            finding,
            VALIDATOR["Entries"](data.inventory),
            data.cutting_data,
            data.feature_definitions,
            {},
        )

    return finding, check


SAW_ROW = {
    "material_class": "low_carbon_steel",
    "tool_material": "bimetal",
    "operation": "saw_cut",
    "sfm": 150.0,
    "feed_mm_min": 20.0,
    "cite": "test saw row",
}


@pytest.mark.parametrize("corruption", ["material_class", "source", "unverified_machine"])
def test_saw_speed_oracle_takes_its_row_from_the_plan_material_not_the_report(corruption):
    data = drill_bundle()
    data.plan["setups"][0].update(machine="saw", ops=[{"op": 10, "do": "saw_cut", "tool": "blade"}])
    data.inventory["machines"]["saw"] = {"kind": "saw", "blade_speed_sfm": [50, 300]}
    data.inventory["tools"]["blade"] = {"kind": "saw_blade", "material": "bimetal"}
    other = {**SAW_ROW, "material_class": "aluminium", "sfm": 280.0, "cite": "aluminium row"}
    data.cutting_data["cut"] += [SAW_ROW, other]
    data.cutting_data["aliases"]["6061"] = "aluminium"
    if corruption == "unverified_machine":
        data.inventory["machines"]["saw"]["verify"] = True
    finding, check = saw_finding(data)
    check()
    row = finding["numbers"]
    if corruption == "material_class":
        # The report claims the stock is aluminium and takes that class's faster row,
        # self-consistently: the plan's 1018 selects the 150 sfm steel row.
        row.update(material="6061", material_class="aluminium", cutting_data_row=other["cite"])
        row.update(sfm=280.0, blade_speed_sfm=280.0)
    elif corruption == "source":
        row["cutting_data_row"] = "aluminium row"
    else:
        assert finding["status"] == "unknown"
        finding["status"] = "pass"
        row["blade_speed_range_verify"] = False
    with pytest.raises(ValueError):
        check()


def saw_bundle():
    """``drill_bundle`` turned into one verified bimetal blade cut on a verified saw."""
    data = drill_bundle()
    data.plan["setups"][0].update(machine="saw", ops=[{"op": 10, "do": "saw_cut", "tool": "blade"}])
    data.inventory["machines"]["saw"] = {"kind": "saw", "blade_speed_sfm": [50, 300]}
    data.inventory["tools"]["blade"] = {"kind": "saw_blade", "material": "bimetal"}
    data.cutting_data["cut"].append(SAW_ROW)
    return data


@pytest.mark.parametrize("verification_debt", [False, True])
def test_slitting_speed_oracle_uses_disk_rpm_not_bandsaw_descent(verification_debt):
    data = drill_bundle()
    setup = data.plan["setups"][0]
    setup["ops"] = [{"op": 10, "do": "cut_off", "tool": "disk", "holder": "arbor"}]
    data.inventory["tools"]["disk"] = {
        "kind": "slitting_saw",
        "material": "HSS",
        "dia_mm": synthetic_fact(50.8),
        "flutes": 20,
        "verify": verification_debt,
    }
    data.cutting_data["cut"].append(
        {
            "material_class": "low_carbon_steel",
            "tool_material": "HSS",
            "operation": "slitting_saw",
            "diameter_range": [50.0, 51.0],
            "sfm": 100.0,
            "chip_load_mm_per_tooth": 0.01,
            "cite": "synthetic disk speed row",
        }
    )
    finding, check = saw_finding(data)
    check()
    assert finding["numbers"]["operation"] == "slitting_saw"
    assert "rpm" in finding["numbers"]
    assert "blade_speed_sfm" not in finding["numbers"]
    finding["numbers"]["operation"] = "saw_cut"
    with pytest.raises(ValueError, match="cutting-data operation"):
        check()


def test_hand_fed_bandsaw_speed_oracle_does_not_require_descent_feed():
    data = saw_bundle()
    data.plan["setups"][0]["ops"][0]["follows"] = "scribed-line"
    data.cutting_data["cut"][-1] = {
        key: value for key, value in SAW_ROW.items() if key != "feed_mm_min"
    }
    finding, check = saw_finding(data)
    check()
    assert finding["numbers"]["feed_mm_min"] == "not_applicable"
    finding["numbers"]["feed_mm_min"] = 20.0
    with pytest.raises(ValueError, match="descent feed"):
        check()


@pytest.mark.parametrize("cut", ["drill", "saw"])
def test_speed_oracle_certifies_the_row_its_inputs_settle(cut):
    # A sourced RPM (or blade speed) and feed on verified inputs is certified: the
    # report cannot leave it tentative, any more than it can pass an unsettled one.
    if cut == "drill":
        finding, check = speed_finding(drill_bundle(thickness=20.0))
    else:
        finding, check = saw_finding(saw_bundle())
    check()
    assert finding["status"] == "pass"
    finding["status"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("hole", "forged"),
    [
        # A through hole whose tip its verified drill places: pass.
        ("through", "unknown"),
        ("through", "error"),
        ("through", "no_row"),
        # A blind tip 40 mm (plus the drill point) into a 10 mm deep hole: error.
        ("over_guard", "pass"),
        ("over_guard", "unknown"),
        # A blind hole with no depth guard to hold the tip to: unknown.
        ("no_guard", "pass"),
        ("no_guard", "error"),
    ],
)
def test_endpoint_verdict_is_the_one_its_ops_tools_and_depth_guard_decide(hole, forged):
    data = drill_bundle(thickness=20.0) if hole == "through" else drill_bundle(depth_mm=40.0)
    if hole == "over_guard":
        data.features["features"]["hole"]["depth"] = 10.0
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    finding = findings["blind_depth", "hole"]
    native = {"through": "pass", "over_guard": "error", "no_guard": "unknown"}[hole]
    assert finding["status"] == native
    VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)
    if forged == "no_row":
        finding["numbers"]["endpoints"].clear()  # nothing left to place the tip
    else:
        finding["status"] = forged
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](validator_test_bundle(data), findings, entries)


@pytest.mark.parametrize(("where", "key", "value"), CENTRE_CASES)
def test_centre_endpoint_verdict_is_the_one_its_inputs_decide(tmp_path, where, key, value):
    # Prepared, contradicted or unresolved, the centre's verdict is its own row's: an
    # unresolved centre is not an error, and a prepared one is not left tentative.
    _, check, finding = centre_findings(tmp_path, where, key, value)
    check()
    for forged in sorted({"pass", "unknown", "error"} - {finding["status"]}):
        finding["status"] = forged
        with pytest.raises(ValueError):
            check()


@pytest.mark.parametrize(
    ("tolerance", "verified", "native"),
    [
        # The 12.5182 degree setting inside a 1 degree band on the verified head.
        (1.0, True, "pass"),
        # A 0.0001 degree band the nearest setting misses.
        (0.0001, True, "error"),
        # The 1 degree band on an unverified head: tentative.
        (1.0, False, "unknown"),
    ],
)
def test_indexing_verdict_is_the_one_its_head_and_tolerance_decide(tolerance, verified, native):
    plan, features, inventory, _, _ = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S5")
    declaration = setup["hold"]["index"]
    features["features"][declaration["feature"]]["angle_tol_deg"] = tolerance
    inventory["machines"][declaration["fixture"]]["verify"] = not verified
    bundle = SimpleNamespace(
        plan=plan,
        features=features,
        inventory=inventory,
        feature_definitions=features["features"],
    )
    (finding,) = (f.to_dict() for f in indexing.evaluate(bundle) if f.subject == "S5")
    assert finding["status"] == native
    entries = VALIDATOR["Entries"](inventory)
    VALIDATOR["check_indexing"](setup, features, entries, finding)
    for forged in sorted({"pass", "unknown", "error"} - {native}):
        finding["status"] = forged
        with pytest.raises(ValueError):
            VALIDATOR["check_indexing"](setup, features, entries, finding)


@pytest.mark.parametrize(
    ("case", "verdict"),
    [
        ("bonded-stock", "pass"),
        ("native-datum", "unknown"),
        ("native-source-plane", "pass"),
        ("through-drill", "unknown"),
        ("lateral-sweep", "unknown"),
        ("bbox-mill", "pass"),
        ("flipped-bbox-mill", "unknown"),
        ("supplied-no-normal", "unknown"),
        ("measured-retouch", "pass"),
        ("measured-retouch-unknown", "unknown"),
        ("measured-retouch-wrong-edge", "error"),
        ("bounded-reface", "pass"),
        ("unknown-reface", "unknown"),
        ("missing-native-datum", "unknown"),
        ("intervening-cut", "unknown"),
        ("wrong-edge", "error"),
        ("explicit-touch", "unknown"),
        ("listed-retouch", "unknown"),
        ("measured", "pass"),
    ],
)
def test_zero_oracle_uses_its_own_carried_physical_height_and_typed_setting(case, verdict):
    if case in {"bonded-stock", "intervening-cut", "wrong-edge"}:
        data = carried_rectangular_stock_bundle()
    elif case == "native-source-plane":
        data = carried_rectangular_source_plane_bundle()
    elif case in {"through-drill", "lateral-sweep"}:
        data = carry_with_through_drill(aim_shift=0.185)
    elif case in {"bbox-mill", "flipped-bbox-mill", "supplied-no-normal"}:
        data = carried_bbox_mill_bundle(
            mode="supplied" if case == "supplied-no-normal" else "axial",
            flipped=case == "flipped-bbox-mill",
        )
    elif case in {
        "measured-retouch",
        "measured-retouch-unknown",
        "measured-retouch-wrong-edge",
    }:
        data = measured_native_retouch_bundle(bounded=case != "measured-retouch-unknown")
    elif case in {"bounded-reface", "unknown-reface"}:
        data = carry_with_refaced_hole(bounded=case == "bounded-reface", later_setup=True)
    else:
        data = carried_native_datum_bundle()
    setup = data.plan["setups"][-1]
    z = setup["zero"]["z"]
    if case == "missing-native-datum":
        for native in data.kernel["setups"].values():
            native["render_scene"]["datums"] = []
    elif case == "lateral-sweep":
        setup["ops"][1].update(do="face", to_z=0.0)
    elif case == "measured-retouch-wrong-edge":
        setup["stock_state"]["top_z"] = 0.01
    elif case == "intervening-cut":
        bond = data.plan["setups"][-2]
        bond.update(
            machine="mill",
            ops=[
                {
                    "op": 20,
                    "do": "face",
                    "feature": "spigot",
                    "tool": "mill",
                    "to_z": 0.0,
                    "stock_removal_bounds": {
                        "x": [-2.0, 2.0],
                        "y": [-2.0, 2.0],
                        "z": [-22.0, -20.0],
                    },
                }
            ],
        )
        data.kernel["ops"]["S7:20"] = {"claimed_indices": [2]}
    elif case == "wrong-edge":
        z["edge_mm"] = 0.01
    elif case == "explicit-touch":
        setup["zero"]["tool_touches"] = [
            {
                "tool": "drill",
                "z_face": z["face"],
                "edge_mm": 21.0055,
                "paper_mm": 0.0024,
                "method": "touch_then_set",
                "before_ops": [20],
            }
        ]
    elif case == "listed-retouch":
        setup["stock_state"] = {"top_z": 21.0055, "top_feature": z["face"]}
        z.update(face="top", retouch_after=[10])
    elif case == "measured":
        data.kernel["setups"][setup["id"]]["render_scene"]["datums"] = []
        z.update(method="measure_then_set", gauge="mic", measure="bench reading", offset_mm=1.0)
        setup["ops"] = setup["ops"][:1]
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert finding["status"] == verdict
    entries = VALIDATOR["Entries"](data.inventory)
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)
    forged = copy.deepcopy(finding)
    forged["status"] = "unknown" if verdict != "unknown" else "pass"
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)
    if case in {"native-datum", "native-source-plane"}:
        row = finding["numbers"]["axes"]["z"]
        field = "axis_set"
        # Safe down from the as-cut contact: the source-plane producer's lathe grid left
        # it at 21.01; the datum bundle's 21.0055 contact (plus 0.0024 paper) floors.
        typed, residual = (21.01, 0.0) if case == "native-source-plane" else (21.005, 0.0005)
        assert row[field] == typed
        assert row["setting_residual_mm"] == pytest.approx(residual)
        forged = copy.deepcopy(finding)
        forged_row = forged["numbers"]["axes"]["z"]
        forged_row["setting_residual_mm"] = residual + 0.001
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, forged, entries, own)
        row[field] = typed + 0.005  # rounded up: later tips would cut deeper
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, finding, entries, own)
    if case == "native-datum":
        for native in own.kernel["setups"].values():
            native["render_scene"]["datums"] = []
        complete = zero_recipe_rule.evaluate(data)[-1].to_dict()
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, complete, entries, own)
    if case in {"through-drill", "explicit-touch", "listed-retouch"}:
        row = (
            finding["numbers"]["tool_touches"][0]
            if case == "explicit-touch"
            else finding["numbers"]["retouch"][0]
            if case == "listed-retouch"
            else finding["numbers"]["derived_touches"][-1]
        )
        assert row["z_axis_set" if case != "listed-retouch" else "axis_set"] == "unknown"
        assert "touch_exclusion_dia_mm" not in row
        row["touch_exclusion_dia_mm"] = 1.17
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize(
    ("fixture", "inner"),
    [("oblique-plane", 0.0), ("holed-plane", 0.5)],
)
def test_endpoint_zero_oracle_keeps_only_the_primary_contact_without_native_full_shape(
    fixture, inner, monkeypatch
):
    data = (
        carried_native_source_plane_bundle()
        if fixture == "oblique-plane"
        else carried_rectangular_source_plane_bundle()
    )
    setup, entries, own = zero_oracle(data)
    source = data.plan["setups"][1]
    name = setup["zero"]["z"]["face"]
    data.kernel["faces"][0]["fills_bbox"] = False
    data.kernel["setups"][source["id"]]["revolved"][name]["radii_mm"] = [inner, 1.0]
    # Primary native identity is available; the first plunge leaves no certified
    # 0.5 mm square. Neither abundant extrema nor a nominal bore establishes it.
    own = replace(own, kernel=copy.deepcopy(data.kernel))
    primary = VALIDATOR["carried_source_plane"](own, entries, setup, name, 0)
    later = VALIDATOR["carried_source_plane"](own, entries, setup, name, 1)
    assert primary["physical"] == pytest.approx(21.01)
    assert "unknown" in later
    honest = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert honest["status"] == "unknown"
    assert honest["numbers"]["axes"]["z"]["axis_set"] == 21.01
    assert honest["numbers"]["derived_touches"][0]["z_axis_set"] == "unknown"
    VALIDATOR["check_zero"](setup, copy.deepcopy(honest), entries, own)

    # The oracle cannot agree with a checker that invents usable rectangular land.
    def forged_land(bundle, setup, target, plane, footprint, previous, excluded):
        excluded.append(max(previous, footprint[1]))
        return True

    monkeypatch.setattr(zero_recipe_native, "_rectangular_spares_plunge", forged_land)
    forged = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert forged["numbers"]["derived_touches"][0]["z_axis_set"] == 21.01
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)


@pytest.mark.parametrize(
    ("radius", "reach", "fills", "expected"),
    [
        (1.0, 0.4999965, True, True),
        (1.0, 0.4999985, True, False),
        (1.0, 0.5, True, False),
        (10.0, 9.999, True, False),
        (10.0, 0.1, False, False),
        (10.0, 9.999, False, False),
    ],
    ids=[
        "just-usable-rectangle",
        "just-too-small-rectangle",
        "marginal-square",
        "tiny-remaining-land",
        "ample-extrema-without-shape",
        "round-or-holed-sliver",
    ],
)
def test_carried_touch_oracle_requires_the_native_rectangular_square_witness(
    radius, reach, fills, expected
):
    identity = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
    }
    own = SimpleNamespace(
        plan={},
        features={"units": "mm", "frames": {"F": identity}},
    )
    setup = {"id": "S", "frame": "F"}
    plane = {
        "touch_face": {
            "index": 0,
            "kind": "Plane",
            "fills_bbox": fills,
            "bbox_mm": [-radius, -radius, 0.0, radius, radius, 0.0],
        }
    }
    assert (
        VALIDATOR["rectangular_touch_land"](own, setup, plane, [0.0, 0.0, 0.0], reach) is expected
    )


def test_carried_touch_oracle_does_not_substitute_radial_extrema_for_shape_or_ignore_prior_cuts():
    identity = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
    }
    own = SimpleNamespace(plan={}, features={"units": "mm", "frames": {"F": identity}})
    setup = {"id": "S", "frame": "F"}
    plane = {
        "outer_radius_mm": 10.0,
        "touch_face": {
            "index": 0,
            "kind": "Plane",
            "bbox_mm": [-1.0, -1.0, 0.0, 1.0, 1.0, 0.0],
        },
    }
    witness = VALIDATOR["rectangular_touch_land"]
    assert not witness(own, setup, plane, [0.0, 0.0, 0.0], 0.1)
    plane["touch_face"]["fills_bbox"] = True
    assert witness(own, setup, plane, [0.0, 0.0, 0.0], 0.1)
    assert not witness(own, setup, plane, [0.0, 0.0, 0.0], 0.6)
    # A model rectangle oblique to the setup axes does not fill its posed AABB.
    root = math.sqrt(0.5)
    identity.update(x=[root, root, 0.0], y=[-root, root, 0.0])
    assert not witness(own, setup, plane, [0.0, 0.0, 0.0], 0.1)


def half_step_source_plane(depth=0.25, shift=0.0):
    """The exact source native plane cut on a 0.0001 lathe grid, so it stands as cut at
    21.0055; with 0.002 paper the contact is 21.0075, half a 0.005 mill step."""
    data = carried_rectangular_source_plane_bundle(source_grid=0.0001, shift=shift)
    receiver = data.plan["setups"][-1]
    receiver["zero"]["z"]["paper_mm"] = 0.002
    receiver["ops"][0]["depth_mm"] = depth
    return data


def zero_oracle(data):
    """The validator's zero inputs, entries and receiving setup for ``data``."""
    own = VALIDATOR["zero_inputs"](validator_test_bundle(data), lambda: copy.deepcopy(data.kernel))
    return data.plan["setups"][-1], VALIDATOR["Entries"](data.inventory), own


def native_survival_oracle_bundle(route="current", cut="unknown", touch="explicit"):
    """A real native plane, one intervening cut and a later contact on that plane."""
    data = carried_rectangular_source_plane_bundle(nominal=21.01 if route == "current" else 21.0055)
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    face = receiver["zero"]["z"]["face"]
    tools = data.inventory["tools"]["centre"]
    tools["sizes"].append(2)
    tools["members"]["2"] = copy.deepcopy(tools["members"]["1"])
    producer = copy.deepcopy(source["ops"][0])
    producer.update(op=5, tool="centre/1")
    plunge = {"op": 10, "do": "drill", "feature": "hole", "tool": "drill", "depth_mm": 0.15}
    consumer = {"op": 20, "do": "spot", "feature": "hole", "tool": "centre/2", "depth_mm": 0.15}
    receiver["stock_state"] = {"top_z": 22.0, "top_feature": face}
    if cut == "unknown":
        del data.inventory["tools"]["drill"]["dia_mm"]
    elif cut == "disjoint":
        plunge["stock_removal_bounds"] = {"x": [30.0, 40.0], "y": [30.0, 40.0], "z": [20.0, 23.0]}
    elif cut == "none":
        plunge = None
    receiver["zero"]["z"].update(face="bench reference", edge_mm=22.0)
    if route == "current":
        receiver["stock_in"] = "stock.sleeve"
        data.plan["setups"] = [receiver]
        receiver["ops"] = [producer, *([plunge] if plunge else []), consumer]
        data.kernel["setups"] = {receiver["id"]: copy.deepcopy(data.kernel["setups"][source["id"]])}
        data.kernel["ops"][f"{receiver['id']}:5"] = {
            "approach": "axial",
            "claimed_indices": [0],
            "faced_side": 1,
        }
    elif route == "receiving":
        receiver["stock_state"]["top_z"] = 21.0055
        receiver["ops"] = [*([plunge] if plunge else []), consumer]
        receiver["zero"]["z"].update(face=face, edge_mm=21.0055)
    else:
        owner = source
        if route == "remount":
            owner = {
                "id": "S4",
                "machine": "mill",
                "frame": receiver["frame"],
                "stock_in": source["id"],
                "ops": [],
            }
            data.plan["setups"].insert(2, owner)
            data.plan["setups"][3]["stock_in"] = [data.plan["setups"][0]["id"], owner["id"]]
        if plunge:
            owner["ops"].append(plunge)
            data.kernel["ops"][f"{owner['id']}:10"] = {"approach": "axial", "claimed_indices": [3]}
            if owner is source:
                plunge["op"] = 15
                data.kernel["ops"][f"{owner['id']}:15"] = data.kernel["ops"].pop(
                    f"{owner['id']}:10"
                )
                # Keep the original face operation's native approach intact.
                data.kernel["ops"][f"{source['id']}:10"] = {
                    "approach": "turning",
                    "claimed_indices": [0],
                    "faced_side": 1,
                }
        receiver["ops"] = [consumer]
        receiver["stock_state"]["top_z"] = 21.0055
        receiver["zero"]["z"].update(face=face, edge_mm=21.0055)
    if route in {"current", "receiving"} and plunge:
        data.kernel["ops"][f"{receiver['id']}:10"] = {"approach": "axial", "claimed_indices": [3]}
    edge = 21.01 if route == "current" else 21.0055
    if touch == "explicit":
        receiver["zero"]["tool_touches"] = [
            {
                "tool": "centre/2",
                "z_face": face,
                "edge_mm": edge,
                "paper_mm": 0.0,
                "method": "touch_then_set",
                "from": "+z",
                "before_ops": [20],
            }
        ]
    elif touch == "listed":
        receiver["zero"]["z"].update(
            face="top",
            method="measure_then_set",
            measure="independent bench registration",
            gauge="mic",
            offset_mm=22.0,
            retouch_after=[10 if plunge else 5],
        )
    elif touch == "primary":
        receiver["zero"]["z"].update(face=face, edge_mm=21.0055)
    return data


def forbid_native_survival_helpers(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("independent native survival called a checker native helper")

    for helper in (
        "_native_scene_plane",
        "_carry_cut",
        "_native_surface_planes",
        "_native_plane_geometry",
        "_axial_cut_footprint",
        "_carried_face_z",
        "_rectangular_spares_plunge",
    ):
        patch_split(monkeypatch, "prechips.rules.zero_recipe", helper, forbidden)
    monkeypatch.setattr(zero_recipe_native, "op_claims", forbidden)


@pytest.mark.parametrize("route", ["current", "receiving", "source", "remount"])
@pytest.mark.parametrize("cut", ["none", "disjoint", "bounded", "unknown"])
def test_native_survival_oracle_scans_every_producer_to_contact_cut(route, cut, monkeypatch):
    touch = "primary" if route in {"source", "remount"} else "explicit"
    data = native_survival_oracle_bundle(route, cut, touch)
    setup, entries, own = zero_oracle(data)
    face = data.feature_definitions[setup["stock_state"]["top_feature"]]
    forbid_native_survival_helpers(monkeypatch)
    plane = VALIDATOR["carried_source_plane"](
        own, entries, setup, setup["stock_state"]["top_feature"], len(setup["ops"]) - 1
    )
    if cut == "unknown":
        assert "unknown" in plane
        assert "ref" not in plane and "physical" not in plane and "native" not in plane
    else:
        assert plane["ref"] == face["faces"][0]
        assert plane["physical"] == pytest.approx(21.01)
        assert plane["excluded_mm"] == (0.0 if cut in {"none", "disjoint"} else pytest.approx(0.4))
        assert plane["current"] is (route == "current")


@pytest.mark.parametrize("touch", ["explicit", "listed", "derived"])
@pytest.mark.parametrize("cut", ["none", "disjoint", "unknown"])
def test_current_native_zero_routes_reject_forced_checker_survival(touch, cut, monkeypatch):
    data = native_survival_oracle_bundle(cut=cut, touch=touch)
    setup, entries, own = zero_oracle(data)
    expected = "unknown" if cut == "unknown" else "pass"
    status, numbers, _ = VALIDATOR["zero_rows"](setup, own, entries)
    assert status == expected
    row = (
        numbers["tool_touches"][-1]
        if touch == "explicit"
        else numbers["retouch"][-1]
        if touch == "listed"
        else numbers["derived_touches"][-1]
    )
    field = "axis_set" if touch == "listed" else "z_axis_set"
    assert row[field] == ("unknown" if cut == "unknown" else 21.01)
    if cut == "unknown":
        assert not any(
            key in row for key in ("credited_faces", "touch_exclusion_dia_mm", "native_edge_mm")
        )
    else:
        assert row["credited_faces"] == [
            data.feature_definitions[setup["stock_state"]["top_feature"]]["faces"][0]
        ]
        # A zero keep-off is omitted, exactly as the checker emits it.
        assert "touch_exclusion_dia_mm" not in row
        assert "native_edge_mm" not in row and "setting_residual_mm" not in row
    # Mutate the real shared production cut helper, not merely a supplied verdict.
    # #214 event scheduling is still shared; native survival and emitted operands are not.
    monkeypatch.setattr(zero_recipe_native, "_carry_cut", lambda *args, **kwargs: False)
    assert VALIDATOR["zero_rows"](setup, own, entries)[0] == expected
    forged = zero_recipe_rule.evaluate(data)[-1].to_dict()
    if cut == "unknown":
        forged["status"] = "pass"
        forged_row = (
            forged["numbers"]["tool_touches"][-1]
            if touch == "explicit"
            else forged["numbers"]["retouch"][-1]
            if touch == "listed"
            else forged["numbers"]["derived_touches"][-1]
        )
        assert forged_row[field] == 21.01
        forged_row.update({field: 21.01, "edge_mm": 21.01, "credited_faces": ["#1/NORTH"]})
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, forged, entries, own)
    else:
        VALIDATOR["check_zero"](setup, forged, entries, own)


def test_native_unknown_current_survival_decides_no_contradiction_from_its_producer(monkeypatch):
    data = native_survival_oracle_bundle()
    setup, entries, own = zero_oracle(data)
    setup["zero"]["tool_touches"][0]["edge_mm"] = 22.0
    status, numbers, _ = VALIDATOR["zero_rows"](setup, own, entries)
    # As the checker: a plane whose survival is unproven may be gone, so its producer's
    # height neither credits nor contradicts the reading.
    assert status == "unknown"
    row = numbers["tool_touches"][0]
    assert row["edge_mm"] == row["z_axis_set"] == "unknown"
    assert "credited_faces" not in row
    VALIDATOR["check_zero"](setup, zero_recipe_rule.evaluate(data)[-1].to_dict(), entries, own)


@pytest.mark.parametrize(
    "boundary",
    [{"before_ops": [999]}, {"before_ops": [20, 999]}, {"before_ops": []}, {"after_op": 999}],
    ids=["unresolved-before", "partly-unresolved", "empty-before", "unresolved-after"],
)
def test_an_unresolved_touch_boundary_is_unknown_never_the_initial_plane(boundary):
    data = native_survival_oracle_bundle("receiving", "unknown")
    touch = data.plan["setups"][-1]["zero"]["tool_touches"][0]
    touch.pop("before_ops", None)
    touch.pop("after_op", None)
    touch.update(boundary)
    setup, entries, own = zero_oracle(data)
    # Collapsed to the initial boundary, the upstream plane (before this setup's unknown
    # cut) would print a numeric Axis Set with its native refs.
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    row = finding["numbers"]["tool_touches"][0]
    assert finding["status"] == "unknown"
    assert row["z_axis_set"] == row["edge_mm"] == "unknown"
    assert "credited_faces" not in row
    VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize("cut", ["none", "unknown"])
def test_an_unresolved_primary_z_after_op_is_unknown_never_the_initial_plane(cut):
    data = native_survival_oracle_bundle("receiving", cut)
    receiver = data.plan["setups"][-1]
    receiver["zero"]["tool_touches"] = []
    receiver["zero"]["z"]["after_op"] = 999
    setup, entries, own = zero_oracle(data)
    # Collapsed to the initial boundary, the carried plane would print 21.01 with its
    # native refs, and with no intervening cut the zero check would pass.
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    axis = finding["numbers"]["axes"]["z"]
    assert finding["status"] == "unknown"
    assert axis["axis_set"] == "unknown" and "credited_faces" not in axis
    VALIDATOR["check_zero"](setup, finding, entries, own)
    forged = copy.deepcopy(finding)
    forged["status"] = "pass"
    forged["numbers"]["axes"]["z"].update(axis_set=21.01, credited_faces=["#1/NORTH"])
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)


@pytest.mark.parametrize("contradiction", [False, True], ids=["datum-debt", "known-over-guard"])
def test_endpoint_oracle_never_recovers_unknown_current_touch_from_an_original_local_producer(
    contradiction, monkeypatch
):
    data = native_survival_oracle_bundle()
    setup, entries, own = zero_oracle(data)
    setup["ops"][-1]["do"] = "drill"
    hole = data.feature_definitions["hole"]
    hole.update(thru=False, depth=0.1 if contradiction else 1.0)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    row = findings["blind_depth", "hole"]["numbers"]["endpoints"][-1]
    assert row["entry_from"] == f"{setup['id']} op 5 to_z"
    # Real checker survival is forced safe, while the oracle's own unknown drill
    # footprint must still forbid re-fetching that local producer's numeric Z.
    monkeypatch.setattr(zero_recipe_native, "_carry_cut", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        zero_recipe_tool_setting,
        "_carried_face_z",
        lambda *args, **kwargs: pytest.fail("endpoint oracle delegated native survival"),
    )
    findings["zero_check", setup["id"]] = {"status": "pass"}
    row["dro_entry_z"] = row["dro_tip_z"] = "unknown"
    row["dro_depth_mm"] = "unknown"
    for key in ("physical_entry_z", "setting_residual_mm"):
        row[key] = "unknown"
    expected = "error" if contradiction else "unknown"
    findings["blind_depth", "hole"]["status"] = expected
    VALIDATOR["check_endpoints"](
        validator_test_bundle(data), findings, entries, lambda: copy.deepcopy(own.kernel)
    )
    forged = copy.deepcopy(findings)
    forged["blind_depth", "hole"]["numbers"]["endpoints"][-1]["dro_entry_z"] = 21.01
    with pytest.raises(ValueError, match="printed entry Z.*unknown"):
        VALIDATOR["check_endpoints"](
            validator_test_bundle(data), forged, entries, lambda: copy.deepcopy(own.kernel)
        )
    forged = copy.deepcopy(findings)
    forged["blind_depth", "hole"]["status"] = "pass"
    with pytest.raises(ValueError, match=rf"endpoint verdict pass is not the {expected}"):
        VALIDATOR["check_endpoints"](
            validator_test_bundle(data), forged, entries, lambda: copy.deepcopy(own.kernel)
        )


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({}, 0),
        ({"after_op": None}, 0),
        ({"after_op": 5}, 1),
        ({"before_ops": [20, 10]}, 1),
        ({"after_op": 20}, 3),
        ({"after_op": 999}, "unknown"),
        ({"before_ops": []}, "unknown"),
        ({"before_ops": [20, 999]}, "unknown"),
    ],
)
def test_native_touch_boundary_is_derived_from_own_raw_operation_names(record, expected):
    assert VALIDATOR["touch_position"]([{"op": 5}, {"op": 10}, {"op": 20}], record) == expected


def test_declared_native_touch_cannot_skip_unknown_cut_via_shared_position_helper(monkeypatch):
    data = native_survival_oracle_bundle()
    setup, entries, own = zero_oracle(data)
    patch_split(monkeypatch, "prechips.rules.zero_recipe", "_position", lambda *args, **kwargs: 0)
    monkeypatch.setattr(zero_recipe_native, "_carry_cut", lambda *args, **kwargs: False)
    status, numbers, _ = VALIDATOR["zero_rows"](setup, own, entries)
    row = numbers["tool_touches"][0]
    assert status == "unknown" and row["z_axis_set"] == "unknown"
    assert "credited_faces" not in row and "native_edge_mm" not in row
    forged = {"status": "pass", "numbers": copy.deepcopy(numbers)}
    forged["numbers"]["tool_touches"][0].update(
        {"z_axis_set": 21.01, "edge_mm": 21.01, "credited_faces": ["#1/NORTH"]}
    )
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)


@pytest.mark.parametrize("absence", ["route", "frame"])
def test_native_proof_absence_never_delegates_to_checker_credit(absence, monkeypatch):
    data = native_survival_oracle_bundle(cut="none")
    setup, entries, own = zero_oracle(data)
    if absence == "route":
        setup["stock_in"] = "missing-setup"
    elif absence == "frame":
        own.features["frames"][setup["frame"]]["x"] = "unknown"
    forbid_native_survival_helpers(monkeypatch)
    plane = VALIDATOR["carried_source_plane"](
        own, entries, setup, setup["stock_state"]["top_feature"], len(setup["ops"]) - 1
    )
    assert "unknown" in plane
    assert not any(key in plane for key in ("ref", "physical", "native", "excluded_mm"))


@pytest.mark.parametrize("cut", ["none", "disjoint"])
def test_endpoint_oracle_retains_numeric_current_touch_when_own_plane_survives(cut, monkeypatch):
    data = native_survival_oracle_bundle(cut=cut)
    setup, entries, own = zero_oracle(data)
    setup["ops"][-1]["do"] = "drill"
    data.feature_definitions["hole"].update(thru=False, depth=1.0)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    monkeypatch.setattr(zero_recipe_native, "_carry_cut", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        zero_recipe_tool_setting,
        "_carried_face_z",
        lambda *args, **kwargs: pytest.fail("endpoint oracle delegated native survival"),
    )
    VALIDATOR["check_endpoints"](
        validator_test_bundle(data), findings, entries, lambda: copy.deepcopy(own.kernel)
    )


@pytest.mark.parametrize("invalid", ["claims", "mapping", "bounds", "action", "unfilled-land"])
def test_native_postproducer_cut_with_invalid_or_ambiguous_own_inputs_fails_closed(
    invalid, monkeypatch
):
    data = native_survival_oracle_bundle(cut="bounded")
    setup, entries, own = zero_oracle(data)
    cut = setup["ops"][1]
    detail = own.kernel["ops"][f"{setup['id']}:10"]
    if invalid == "claims":
        detail["claimed_indices"] = [False]
    elif invalid == "mapping":
        detail["mapping_errors"] = ["#4/BORE"]
    elif invalid == "bounds":
        cut["stock_removal_bounds"] = {"x": [-1.0, 1.0], "y": [-1.0, 1.0]}
    elif invalid == "action":
        cut["do"] = "unknown"
    else:
        own.kernel["faces"][0]["fills_bbox"] = False
    forbid_native_survival_helpers(monkeypatch)
    plane = VALIDATOR["carried_source_plane"](
        own, entries, setup, setup["stock_state"]["top_feature"], 2
    )
    assert "unknown" in plane
    assert not any(key in plane for key in ("ref", "physical", "native", "excluded_mm"))


@pytest.mark.parametrize("route", ["receiving", "source", "remount"])
def test_carried_native_routes_reject_numeric_credit_from_real_forced_safe_cut_helper(
    route, monkeypatch
):
    data = native_survival_oracle_bundle(route, "unknown")
    setup, entries, own = zero_oracle(data)
    monkeypatch.setattr(zero_recipe_native, "_carry_cut", lambda *args, **kwargs: False)
    status, numbers, _ = VALIDATOR["zero_rows"](setup, own, entries)
    row = numbers["tool_touches"][0]
    assert status == "unknown" and row["z_axis_set"] == "unknown"
    assert "credited_faces" not in row and "native_edge_mm" not in row
    forged = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert forged["numbers"]["tool_touches"][0]["z_axis_set"] == pytest.approx(21.01)
    forged["status"] = "pass"
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)


def oracle_turned_window_plane(normal):
    """The sleeve's lathe source and one of its end planes in the oracle's own form,
    with the spigot's turned radius inside that plane so no radial proof spares it."""
    from test_tool_change_touch import carried_rectangular_stock_bundle

    data = carried_rectangular_stock_bundle()
    source = data.plan["setups"][1]
    data.kernel["setups"][source["id"]]["revolved"]["spigot"]["radii_mm"] = [0.5, 0.5]
    data.inventory["tools"].update(
        {
            "blade-1": {"kind": "grooving_blade", "blade_width_mm": 1.0},
            "blade-2": {"kind": "grooving_blade", "blade_width_mm": 2.0},
            "blade-unknown": {"kind": "grooving_blade"},
            "blade-witness": {"kind": "grooving_blade", "blade_width_mm": 1.002},
        }
    )
    _, entries, own = zero_oracle(data)
    height = 0.0 if normal == 1 else -72.0
    plane = {
        "source": source["id"],
        "frame": VALIDATOR["setup_frame"](source, own.plan, own.features),
        "formed": height,
        "z_mm": height,
        "normal_z": normal,
        "outer_radius_mm": math.sqrt(2.0),
    }
    return own, entries, source, plane


@pytest.mark.parametrize(
    ("normal", "window"), [(1, (0.0, 3.0)), (-1, (-72.0, -80.0))], ids=["plus-z", "minus-z"]
)
def test_oracle_turning_window_on_the_open_side_spares_the_plane(normal, window, monkeypatch):
    own, entries, source, plane = oracle_turned_window_plane(normal)
    forbid_native_survival_helpers(monkeypatch)
    at_plane, far = window
    cut = {"op": 20, "do": "finish_turn", "feature": "spigot", "tool": "turner"}
    cut.update(z_from=far, z_to=at_plane)
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) == 0.0
    crossing = {**cut, "z_to": at_plane - 2 * LENGTH_TOLERANCE_MM * normal}
    assert VALIDATOR["plane_cut_reach"](own, entries, source, crossing, plane, 0.0) is None


@pytest.mark.parametrize("excluded", ["to_z", "part_off"])
def test_oracle_cut_outside_window_limited_turning_still_invalidates(excluded, monkeypatch):
    own, entries, source, plane = oracle_turned_window_plane(1)
    forbid_native_survival_helpers(monkeypatch)
    cut = {"op": 20, "do": "finish_turn", "feature": "spigot", "tool": "turner"}
    cut.update(z_from=3.0, z_to=0.0)
    if excluded == "to_z":
        cut["to_z"] = 0.0
    else:
        cut["do"] = "part_off"
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) is None


def test_oracle_turning_window_spares_no_plane_tilted_off_its_axis(monkeypatch):
    from test_contour_order import tilted

    own, entries, source, plane = oracle_turned_window_plane(1)
    forbid_native_survival_helpers(monkeypatch)
    cut = {"op": 20, "do": "finish_turn", "feature": "spigot", "tool": "turner"}
    cut.update(z_from=20.0, z_to=0.0)
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) == 0.0
    leaning = {**plane, "frame": tilted(plane["frame"])}
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, leaning, 0.0) is None


@pytest.mark.parametrize(
    ("tool", "spared"),
    [("blade-1", True), ("blade-2", False), ("blade-unknown", False)],
    ids=["inside", "wider", "unknown"],
)
def test_oracle_blade_groove_spares_the_plane_only_over_its_whole_known_width(
    tool, spared, monkeypatch
):
    own, entries, source, plane = oracle_turned_window_plane(-1)
    forbid_native_survival_helpers(monkeypatch)
    cut = {"op": 20, "do": "groove", "feature": "spigot", "tool": tool}
    cut.update(z_from=-73.0, z_to=-72.5)
    reach = VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0)
    assert reach == 0.0 if spared else reach is None


def test_oracle_turning_window_spares_the_plane_only_at_its_dialled_ends(monkeypatch):
    own, entries, source, plane = oracle_turned_window_plane(-1)
    forbid_native_survival_helpers(monkeypatch)
    cut = {"op": 20, "do": "finish_turn", "feature": "spigot", "tool": "turner"}
    cut.update(z_from=-80.0, z_to=-72.5)
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) == 0.0
    oracle = VALIDATOR["plane_cut_reach"].__globals__
    monkeypatch.setitem(oracle, "dro_grid", lambda *args: (5.0, 0))
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) is None


def test_oracle_blade_groove_grows_its_width_from_the_dialled_chuck_side_end(monkeypatch):
    own, entries, source, plane = oracle_turned_window_plane(-1)
    forbid_native_survival_helpers(monkeypatch)
    cut = {"op": 20, "do": "groove", "feature": "spigot", "tool": "blade-witness"}
    cut.update(z_from=-73.003, z_to=-72.5)
    oracle = VALIDATOR["plane_cut_reach"].__globals__
    # On a 0.001 grid the wall stops at -72.001; dialled to -73.000 on 0.005, -71.998.
    monkeypatch.setitem(oracle, "dro_grid", lambda *args: (0.001, 3))
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) == 0.0
    monkeypatch.setitem(oracle, "dro_grid", lambda *args: (0.005, 3))
    assert VALIDATOR["plane_cut_reach"](own, entries, source, cut, plane, 0.0) is None


@pytest.mark.parametrize("shift", [0.0, 0.5], ids=["same-centre", "shifted-centre"])
def test_oracle_accepts_only_an_unknown_reface_about_another_centre(tmp_path, shift):
    from test_contour_order import refaced_about

    data, _, _ = refaced_about(tmp_path, shift)
    setup, entries, own = zero_oracle(data)
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert finding["status"] == ("pass" if shift == 0.0 else "unknown")
    VALIDATOR["check_zero"](setup, finding, entries, own)


def test_oracle_exclusion_centre_axis_is_its_own_frame_comparison():
    from test_contour_order import tilted

    own, _, source, plane = oracle_turned_window_plane(1)
    frame = plane["frame"]
    axes = VALIDATOR["frame_basis"](frame)
    origin = VALIDATOR["model_point"]([0.0, 0.0, 0.0], frame)
    shares = VALIDATOR["shares_plane_axis"]

    def moved(x, z):
        shifted = zip(origin, axes[0], axes[2], strict=True)
        return {**frame, "origin": [o + x * a + z * b for o, a, b in shifted]}

    assert shares(own, plane, frame)
    assert shares(own, plane, moved(0.0, 3.0))  # along the axis: same centre line
    assert not shares(own, plane, moved(2.0, 0.0))  # across it: another centre
    assert not shares(own, plane, tilted(frame))
    assert not shares(own, None, frame)


@pytest.mark.parametrize(
    ("depth", "diameter"),
    [(0.15, 0.3), (0.25, 0.3 + 0.1 * math.tan(math.radians(30))), (0.8, 0.4)],
    ids=["pilot-only", "countersink-mouth", "body-radius-cap"],
)
def test_zero_oracle_types_a_half_step_carried_contact_down_past_a_resolved_countersink(
    depth, diameter
):
    data = half_step_source_plane(depth)
    spot = data.plan["setups"][-1]["ops"][0]
    assert spot["tool"] == "centre/1"
    assert data.inventory["tools"]["centre"]["kind"] == "center_drill_set"
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert finding["status"] == "pass", finding
    zero, (touch,) = finding["numbers"]["axes"]["z"], finding["numbers"]["derived_touches"]
    assert zero["edge_mm"] == pytest.approx(21.0055)
    # 21.0075 types down to 21.005, never the nearest 21.010 a later tip would cut under.
    assert zero["axis_set"] == touch["z_axis_set"] == 21.005
    assert zero["setting_residual_mm"] == pytest.approx(0.0025)
    assert touch["setting_residual_mm"] == pytest.approx(0.0025)
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(diameter)
    setup, entries, own = zero_oracle(data)
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)
    for path, field, value in (
        (("axes", "z"), "axis_set", 21.01),
        (("derived_touches", 0), "z_axis_set", 21.01),
        (("derived_touches", 0), "touch_exclusion_dia_mm", 0.3 if depth > 0.15 else 0.25),
    ):
        forged = copy.deepcopy(finding)
        forged["numbers"][path[0]][path[1]][field] = value
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, forged, entries, own)


def test_zero_oracle_moves_a_carried_plunge_footprint_by_its_dialled_aim():
    # The planned point reads the hole's plan aim, which asks whether a mill setup dials
    # it (an inventory question); the aimed spot's countersink mouth widens the keep-off.
    data = half_step_source_plane(depth=0.25)
    hole = data.feature_definitions["hole"]
    data.feature_definitions["reference_axis"] = {
        "kind": "boss",
        "frame": "model",
        "at": [hole["at"][0], hole["at"][1] - 1.0, hole["at"][2]],
        "axis": list(hole["axis"]),
    }
    hole.update(height_from="reference_axis", separation=[0.9, 1.5], precision={"separation": 3})
    data.plan["aims"] = {
        "hole": {
            "requirement": "separation",
            "value_mm": 1.185,
            "reason": "Synthetic dialled aim moves the carried plunge footprint",
        }
    }
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert finding["status"] == "pass", finding
    (touch,) = finding["numbers"]["derived_touches"]
    mouth = 0.15 + 0.05 * math.tan(math.radians(30))
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(2 * (mouth + 0.185))
    setup, entries, own = zero_oracle(data)
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)
    touch["touch_exclusion_dia_mm"] = 2 * mouth  # the unaimed footprint
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize(
    "depth", [0.25, "unknown", None], ids=["op-wins", "op-debt", "feature-only"]
)
def test_zero_oracle_keeps_a_centre_drill_footprint_on_the_resolved_op_depth(depth):
    data = half_step_source_plane()
    data.feature_definitions["hole"]["depth"] = [0.1, 0.15]
    spot = data.plan["setups"][-1]["ops"][0]
    if depth is None:
        del spot["depth_mm"]
    else:
        spot["depth_mm"] = depth
    setup, entries, own = zero_oracle(data)
    footprint = VALIDATOR["plunge_footprint"](own, entries, setup, spot)
    if depth == 0.25:
        assert footprint is not None
        assert footprint[1] == pytest.approx(0.15 + 0.05 * math.tan(math.radians(30)))
    else:
        assert footprint is None
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)


def forge_carry(monkeypatch, target):
    """Patch one checker carry helper to a plausible wrong answer."""
    original = split_attr("prechips.rules.zero_recipe", target)

    def nearest_setting(*args, **kwargs):
        original(*args, **kwargs)
        row, field = args[2], args[3]
        typed, residual = row.get(field), row.get("setting_residual_mm")
        if isinstance(typed, float) and isinstance(residual, float):
            desired = typed + residual
            row[field] = round(round(desired / 0.005) * 0.005, 6)
            row["setting_residual_mm"] = round(desired - row[field], 9)

    def raised_plane(*args, **kwargs):
        height = original(*args, **kwargs)
        return height + 0.005 if isinstance(height, float) else height

    def narrow_footprint(*args, **kwargs):
        footprint = original(*args, **kwargs)
        return footprint if footprint is None else (footprint[0], footprint[1] / 2)

    forged = {
        "_carried_setting": nearest_setting,
        "_plane_in_frame": raised_plane,
        "_axial_cut_footprint": narrow_footprint,
    }[target]
    patch_split(monkeypatch, "prechips.rules.zero_recipe", target, forged)


@pytest.mark.parametrize("target", ["_carried_setting", "_plane_in_frame", "_axial_cut_footprint"])
def test_zero_oracle_derives_a_carried_source_plane_without_the_checkers_carry(monkeypatch, target):
    # A shared answer would agree with a forged checker; the oracle's own carry does not.
    data = half_step_source_plane()
    setup, entries, own = zero_oracle(data)
    honest = zero_recipe_rule.evaluate(data)[-1].to_dict()
    VALIDATOR["check_zero"](setup, copy.deepcopy(honest), entries, own)
    forge_carry(monkeypatch, target)
    forged = zero_recipe_rule.evaluate(data)[-1].to_dict()
    assert forged != honest
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, forged, entries, own)


@pytest.mark.parametrize("thickness", [2.0, None], ids=["declared-thickness", "no-thickness"])
def test_endpoint_oracle_reads_a_carried_touch_off_its_typed_setting(thickness):
    # Off grid: physical 21.0147 types down to 21.010; the native nominal 21.0102, where
    # the received stock's top (the carried face) is entered, would round up to 21.015.
    data = carried_rectangular_source_plane_bundle(shift=0.0047)
    receiver = data.plan["setups"][-1]
    receiver["stock_state"] = {"top_z": 21.0102, "top_feature": receiver["zero"]["z"]["face"]}
    if thickness is not None:
        # The through drill's planned local thickness: the only source of its exit bound.
        receiver["stock_state"]["local_thickness"] = {"hole": thickness}
    drill = receiver["ops"][1]
    assert drill["do"] == "drill" and data.feature_definitions["hole"]["thru"] is True
    drill["exit_mm"] = 0.1
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    rows = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    spot, through = rows
    assert spot["entry_z"] == pytest.approx(21.0102)
    assert spot["physical_entry_z"] == pytest.approx(21.0147)
    # The entry reads off the typed 21.010, not the raw plane re-rounded up to 21.015.
    assert spot["dro_entry_z"] == pytest.approx(21.01)
    for row in rows:
        assert row["setting_residual_mm"] == pytest.approx(0.0047)
        assert "physical_exit_face" not in row
    assert "physical_exit_bound_z" not in spot
    if thickness is None:
        # No planned thickness: the exit and its bound stay honestly unknown.
        assert through["exit_face"] == "unknown"
        assert through["physical_exit_bound_z"] == "unknown"
    else:
        assert through["exit_face"] == pytest.approx(19.0102)
        # The as-cut entry less the planned thickness: a bound, not an as-cut exit plane.
        assert through["physical_exit_bound_z"] == pytest.approx(19.0147)

    def check(report):
        VALIDATOR["check_endpoints"](
            validator_test_bundle(data), report, entries, lambda: copy.deepcopy(data.kernel)
        )

    check(findings)
    forgeries = [
        (0, "dro_entry_z", spot["dro_entry_z"] + 0.005),
        (0, "dro_tip_z", spot["dro_tip_z"] - 0.005),
        (0, "setting_residual_mm", 0.0),
        (0, "physical_entry_z", spot["entry_z"]),
        # A blind spot has no exit to bound; an invented one is a forgery.
        (0, "physical_exit_bound_z", spot["tip_z"]),
        # No endpoint names an as-cut exit plane the local thickness only bounds.
        (0, "physical_exit_face", spot["tip_z"]),
        (1, "physical_exit_face", 19.0147),
        (1, "setting_residual_mm", 0.0),
        # Neither a nominal exit nor a number for an unknown one.
        (1, "physical_exit_bound_z", 19.0102 if thickness is not None else 19.0147),
    ]
    if thickness is not None:
        forgeries.append((1, "dro_exit_face", through["dro_exit_face"] + 0.005))
    for index, field, value in forgeries:
        forged = copy.deepcopy(findings)
        forged["blind_depth", "hole"]["numbers"]["endpoints"][index][field] = value
        with pytest.raises(ValueError):
            check(forged)


@pytest.mark.parametrize("land", [True, False], ids=["usable-land", "unproven-land"])
@pytest.mark.parametrize("endpoint", ["blind", "through", "centre", "over-guard"])
def test_endpoint_oracle_requires_its_own_carried_datum_before_passing(land, endpoint, monkeypatch):
    data = carried_rectangular_source_plane_bundle()
    receiver = data.plan["setups"][-1]
    receiver["stock_state"] = {
        "top_z": 21.0055,
        "top_feature": receiver["zero"]["z"]["face"],
    }
    # The initial spot has a primary contact. A different tool must retouch the
    # native plane after that plunge; only its filled rectangle proves usable land.
    data.kernel["faces"][0]["fills_bbox"] = land
    second = receiver["ops"][1]
    if endpoint == "centre":
        tools = data.inventory["tools"]["centre"]
        tools["sizes"].append(2)
        tools["members"]["2"] = copy.deepcopy(tools["members"]["1"])
        data.plan["process_features"] = {
            "seat": {
                "kind": "centre_hole",
                "at": [0.0, 0.0, 21.0055],
                "axis": [0.0, 0.0, -1.0],
                "drill_dia_mm": 0.3,
                "drill_length_mm": 0.2,
                "mouth_dia_mm": 0.35,
                "countersink_angle_deg": 60.0,
                "cite": ["test: a synthetic centre on the carried native source plane"],
            }
        }
        data.feature_definitions = VALIDATOR["operative_definitions"](data.plan, data.features)
        second.update(do="center_drill", feature="seat", tool="centre/2")
        subject = "seat"
    else:
        subject = "hole"
        hole = data.feature_definitions["hole"]
        hole["thru"] = endpoint == "through"
        if hole["thru"]:
            receiver["stock_state"]["local_thickness"] = {"hole": 0.5}
            second["exit_mm"] = 0.1
        else:
            hole["depth"] = 0.2 if endpoint == "over-guard" else 1.0
            second["depth_mm"] = 0.25
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    finding = findings["blind_depth", subject]
    expected = "error" if endpoint == "over-guard" else "pass" if land else "unknown"
    assert finding["status"] == expected
    row = finding["numbers"]["endpoints"][-1]
    assert VALIDATOR["numeric"](row["tip_z"])
    assert VALIDATOR["numeric"](row["dro_tip_z"]) is land

    # Reports were produced before these traps. The supported rectangular route
    # must now derive its datum from the oracle's own kernel getter, not checker
    # surface helpers or a zero finding's status.
    def checker_surface(*args, **kwargs):
        pytest.fail("endpoint oracle called a checker surface helper")

    for helper in ("face_stands", "_carried_face_z", "_rectangular_spares_plunge"):
        patch_split(monkeypatch, "prechips.rules.zero_recipe", helper, checker_surface)
    findings["zero_check", receiver["id"]] = {"status": "unknown" if land else "pass"}
    entries = VALIDATOR["Entries"](data.inventory)

    def check(report):
        return VALIDATOR["check_endpoints"](
            validator_test_bundle(data), report, entries, lambda: copy.deepcopy(data.kernel)
        )

    depths = check(findings)
    # Datum debt changes the verdict, never the independently planned material depth.
    assert VALIDATOR["positive"](depths[receiver["id"], second["op"]])
    forged = copy.deepcopy(findings)
    forged["blind_depth", subject]["status"] = "unknown" if expected != "unknown" else "pass"
    with pytest.raises(ValueError, match=rf"endpoint verdict .* is not the {expected}"):
        check(forged)


@pytest.mark.parametrize("edge", [21.0055, 21.01], ids=["native-edge", "as-cut-edge"])
@pytest.mark.parametrize("entry", [21.0055, "unknown"], ids=["native-entry", "unknown-entry"])
def test_endpoint_oracle_accepts_only_the_nominal_or_unknown_carried_entry(edge, entry):
    data = carried_entry_bundle()
    setup = data.plan["setups"][-1]
    setup["zero"]["z"]["edge_mm"] = edge
    setup["stock_state"]["entry_z"]["hole"] = entry
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    VALIDATOR["check_endpoints"](
        validator_test_bundle(data),
        findings,
        VALIDATOR["Entries"](data.inventory),
        lambda: copy.deepcopy(data.kernel),
    )


@pytest.mark.parametrize(
    ("below_in", "typed"),
    [(0.0, 0.827165354), (1e-8, 0.826968504)],
    ids=["printed-grid-line", "genuinely-below-grid-line"],
)
def test_carried_inch_contact_uses_the_printed_grid_line_without_rounding_a_lower_contact_up(
    below_in, typed
):
    data = carried_entry_bundle("in")
    setup, entries, own = zero_oracle(data)
    frame = data.features["frames"][setup["frame"]]
    frame["origin"] = [below_in * value for value in frame["z"]]
    setup["zero"]["z"]["edge_mm"] -= below_in
    setup["stock_state"]["entry_z"]["hole"] -= below_in
    finding = zero_recipe_rule.evaluate(data)[-1].to_dict()
    contact = finding["numbers"]["axes"]["z"]
    assert finding["status"] == "pass", finding
    assert contact["axis_set"] == typed
    # The genuine displacement is below native LENGTH tolerance, but is not
    # binary roundoff: even that lower contact must never type the higher line.
    assert 0 <= contact["setting_residual_mm"] <= 0.005
    assert contact["setting_residual_mm"] == pytest.approx(
        (contact["edge_mm"] - typed) * 25.4, abs=1e-9
    )
    VALIDATOR["check_zero"](setup, copy.deepcopy(finding), entries, own)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    assert all(
        row["dro_entry_z"] == typed
        for row in findings["blind_depth", "hole"]["numbers"]["endpoints"]
    )
    VALIDATOR["check_endpoints"](
        validator_test_bundle(data), findings, entries, lambda: copy.deepcopy(data.kernel)
    )


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize("side", [-1, 1])
@pytest.mark.parametrize("inside", [True, False], ids=["within-tolerance", "past-tolerance"])
def test_endpoint_oracle_uses_its_own_physical_native_entry_tolerance(units, side, inside):
    data = carried_entry_bundle(units)
    setup, entries, own = zero_oracle(data)
    carried = VALIDATOR["zero_rows"](setup, own, entries)[2][str(setup["ops"][0]["op"])]
    scale = {"mm": 1.0, "in": 25.4}[units]
    nominal = carried["native"]
    # Stay either side of the boundary beyond rigid-frame float residue; this
    # oracle's native height is independently calculated, not the checker's.
    fraction = 0.999 if inside else 1.001
    entry = nominal + side * fraction * LENGTH_TOLERANCE_MM / scale
    assert (abs(entry - nominal) * scale <= LENGTH_TOLERANCE_MM) is inside
    setup["stock_state"]["entry_z"]["hole"] = entry
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}

    def check():
        VALIDATOR["check_endpoints"](
            validator_test_bundle(data), findings, entries, lambda: copy.deepcopy(data.kernel)
        )

    if inside:
        check()
    else:
        with pytest.raises(ValueError, match=r"Bad input: S9 stock_state\.entry_z\.hole"):
            check()


@pytest.mark.parametrize("edge", [21.0055, 21.01], ids=["native-edge", "both-as-cut"])
def test_endpoint_oracle_rejects_an_as_cut_entry_and_a_self_consistent_double_shift(edge):
    data = carried_entry_bundle()
    setup = data.plan["setups"][-1]
    setup["zero"]["z"]["edge_mm"] = edge
    setup["stock_state"]["entry_z"]["hole"] = 21.01
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    assert findings["blind_depth", "hole"]["status"] == "error"
    entries = VALIDATOR["Entries"](data.inventory)
    grid = VALIDATOR["dro_grid"](setup, data.features, entries)

    def check(report):
        VALIDATOR["check_endpoints"](
            validator_test_bundle(data), report, entries, lambda: copy.deepcopy(data.kernel)
        )

    with pytest.raises(ValueError, match=r"Bad input: S9 stock_state\.entry_z\.hole"):
        check(findings)
    forged = copy.deepcopy(findings)
    forged["blind_depth", "hole"]["status"] = "pass"
    shift = 21.01 - 21.0055
    for row in forged["blind_depth", "hole"]["numbers"]["endpoints"]:
        row["dro_entry_z"] = VALIDATOR["dro_up"](row["entry_z"] + shift, grid)
        row["physical_entry_z"] = row["entry_z"] + shift
        if row["exit_face"] == "not_applicable":
            worked = row["tip_z"] + shift
            row["dro_tip_z"] = VALIDATOR["dro_up"](worked, grid)
            row["dro_depth_mm"] = row["depth_mm"] - (row["dro_tip_z"] - worked)
        else:
            read_exit = row["exit_face"] + shift
            row["dro_exit_face"] = VALIDATOR["dro_up"](read_exit, grid)
            row["physical_exit_bound_z"] = row["physical_entry_z"] - row["local_thickness"]
            row["dro_tip_z"] = VALIDATOR["dro_up"](
                row["tip_z"] + row["dro_exit_face"] - row["exit_face"], grid
            )
            row["dro_exit_mm"] = read_exit - row["point_mm"] - row["dro_tip_z"]
    assert forged["blind_depth", "hole"]["numbers"]["endpoints"][0]["dro_entry_z"] == 21.015
    with pytest.raises(ValueError, match=r"Bad input: S9 stock_state\.entry_z\.hole"):
        check(forged)


@pytest.mark.parametrize(
    ("part", "setup_id", "corruption"),
    [
        ("pivot-bracket", "S2", "drop_axis"),
        ("pivot-bracket", "S1", "drop_retouch"),
        ("pivot-bracket", "S2", "unknown_paper:pass"),
        # Only a saw or manual bench setup waives its zero: an unresolved zero, or a
        # settled one, reported as waived or informational is approved by the gate.
        ("pivot-bracket", "S2", "unknown_paper:not_applicable"),
        ("pivot-bracket", "S2", "unknown_paper:info"),
        ("pivot-bracket", "S2", "settled:not_applicable"),
        ("pivot-shaft", "S2", "drop_axis"),
    ],
)
def test_zero_rows_are_the_plans_and_an_unresolved_zero_cannot_pass(
    freecad_kernel, part, setup_id, corruption
):
    setup, finding, entries, own = zero_case(part, setup_id)
    VALIDATOR["check_zero"](setup, finding, entries, own)
    numbers = finding["numbers"]
    if corruption == "drop_axis":
        del numbers["axes"]["x"]  # the X zero left unchecked
    elif corruption == "drop_retouch":
        assert numbers["retouch"]
        numbers["retouch"].pop()
    elif corruption.startswith("unknown_paper"):
        # No paper thickness: the Z Axis Set and its retouches are unknown, as the row
        # says; the zero is not certified.
        setup["zero"]["z"]["paper_mm"] = "unknown"
        z = numbers["axes"]["z"]
        z.update(axis_set="unknown", check_reading="unknown", mirrored_reading="unknown")
        for row in numbers["retouch"]:
            row["axis_set"] = "unknown"
    if ":" in corruption:
        finding["status"] = corruption.split(":")[1]
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, finding, entries, own)


def native_zero(part, setup_id, dro_edit=None, inventory_edit=None):
    """The engine's ``zero_check`` finding for one example setup after ``dro_edit`` (a
    callable on the plan's ``dro`` table) and ``inventory_edit`` (one on the inventory),
    from a kernel run of the unedited plan (neither enters the kernel)."""
    bundle = load_bundle(ROOT / "examples" / part / "plan.toml")
    assert run_geometry(bundle)["status"] == "ok"
    if dro_edit:
        dro_edit(bundle.plan["dro"])
    if inventory_edit:
        inventory_edit(bundle.inventory)
    finding = next(f for f in zero_recipe_rule.evaluate(bundle) if f.subject == setup_id)
    return json.loads(json.dumps(finding.to_dict()))


def set_key(path, value):
    """An edit of a table setting ``path`` (keys under it) to ``value``, or deleting it."""

    def edit(table):
        *parents, key = path
        for parent in parents:
            table = table[parent]
        if value is None:
            del table[key]
        else:
            table[key] = value

    return edit


DRO_EDITS = [
    # A reversed DRO count or a mode other than ABS is the error to stop on, on any axis
    # of a mill or a lathe; one the plan leaves unstated is never settled.
    ("pivot-bracket", "S2", ("direction", "x"), "left", "error"),
    ("pivot-bracket", "S2", ("direction", "y"), "toward", "error"),
    ("pivot-bracket", "S2", ("direction", "z"), "down", "error"),
    ("pivot-bracket", "S2", ("mode",), "inc", "error"),
    ("pivot-bracket", "S2", ("direction", "x"), None, "unknown"),
    ("pivot-bracket", "S2", ("mode",), "unknown", "unknown"),
    ("pivot-shaft", "S1", ("direction", "x"), "toward_spindle_axis", "error"),
    ("pivot-shaft", "S1", ("direction", "z"), "toward_chuck", "error"),
    ("pivot-shaft", "S1", ("radius_mode",), "unknown", "unknown"),
    # The lathe X display scale is the plan's radius/diameter mode, not the report's.
    ("pivot-shaft", "S1", ("radius_mode",), True, "pass"),
]


@pytest.mark.parametrize(("part", "setup_id", "path", "value", "verdict"), DRO_EDITS)
def test_zero_polarity_scale_and_mode_come_from_the_plans_dro(
    freecad_kernel, part, setup_id, path, value, verdict
):
    setup, _, _, own = zero_case(part, setup_id)
    # The DRO modes are this mechanism's variable; supply a fresh local grid without
    # certifying the illustrative source or changing its physical precision.
    machine = setup["machine"]
    resolution = 0.01 if part == "pivot-shaft" else 0.005
    grid_edit = inventory_edits(
        (("machines", machine, "resolution_mm"), synthetic_fact(resolution))
    )
    grid_edit(own.inventory)
    entries = VALIDATOR["Entries"](own.inventory)
    before = native_zero(part, setup_id, inventory_edit=grid_edit)
    set_key(path, value)(own.plan["dro"])
    native = native_zero(part, setup_id, set_key(path, value), inventory_edit=grid_edit)
    assert native["status"] == verdict
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    # The unedited plan's finding printing the edited plan's DRO modes (the reviewer's
    # report): the polarity, scale, readings and verdict stay the plan's, not the report's.
    stale = copy.deepcopy(before)
    stale["numbers"]["dro"] = native["numbers"]["dro"]
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, stale, entries, own)
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, {**native, "status": forged}, entries, own)


def test_zero_oracle_grid_metadata_debt_preserves_readings_without_certification(freecad_kernel):
    setup, _, _, own = zero_case("pivot-shaft", "S1")
    machine = setup["machine"]
    fact = synthetic_fact(0.01)
    grid_edit = inventory_edits((("machines", machine, "resolution_mm"), fact))
    grid_edit(own.inventory)
    baseline = native_zero("pivot-shaft", "S1", inventory_edit=grid_edit)
    assert baseline["status"] == "pass"
    entries = VALIDATOR["Entries"](own.inventory)
    VALIDATOR["check_zero"](setup, baseline, entries, own)
    for status in ("assumed", "illustrative", None):
        if status is None:
            del fact["measured"]["status"]
        else:
            fact["measured"]["status"] = status
        native = native_zero("pivot-shaft", "S1", inventory_edit=grid_edit)
        assert native["status"] == "unknown"
        assert {
            key: value
            for key, value in native["numbers"].items()
            if key not in {"dro_grid_debt", "measurements"}
        } == baseline["numbers"]
        VALIDATOR["check_zero"](setup, native, entries, own)
        with pytest.raises(ValueError, match="zero verdict"):
            VALIDATOR["check_zero"](setup, {**native, "status": "pass"}, entries, own)


@pytest.mark.parametrize(("part", "setup_id"), [("pivot-bracket", "S2"), ("pivot-shaft", "S1")])
@pytest.mark.parametrize("status", ["pass", "error"])
def test_zero_jog_polarity_is_never_the_reports(freecad_kernel, part, setup_id, status):
    """A row printing a reversed X polarity with its readings swapped to match is still
    the plan's DRO counting up: neither approved nor taken as the reversal to stop on."""
    setup, _, entries, own = zero_case(part, setup_id)
    native = native_zero(part, setup_id)
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    row = native["numbers"]["axes"]["x"]
    row["sign"] = -row["sign"]
    row["check_reading"], row["mirrored_reading"] = row["mirrored_reading"], row["check_reading"]
    if "check_expression" in row:  # a measured axis prints its readings as expressions
        row["check_expression"], row["mirrored_expression"] = (
            row["mirrored_expression"],
            row["check_expression"],
        )
    native["status"] = status
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, native, entries, own)


def inventory_edits(*edits):
    """One inventory edit applying each ``(path, value)`` of ``edits`` (:func:`set_key`)."""

    def edit(inventory):
        for path, value in edits:
            set_key(path, value)(inventory)

    return edit


FINDER = ("tools", "edge-finder")
MICROMETERS = ("gauges", "micrometers")
ZERO_INVENTORY_EDITS = [
    # A finder, cutter, tool bit or gauge whose verification the inventory leaves unknown,
    # on its record, on a fact it is read through or on the selected set member, or that
    # the inventory leaves unknown whole or by category, is not ready: never a pass.
    ("pivot-bracket", "S2", [((*FINDER, "verify"), "unknown")], "unknown"),
    (
        "pivot-bracket",
        "S2",
        [((*FINDER, "tip_in"), {"value": 0.2, "verify": "unknown"})],
        "unknown",
    ),
    ("pivot-bracket", "S2", [(FINDER, "unknown")], "unknown"),
    ("pivot-bracket", "S2", [(("tools",), "unknown")], "unknown"),
    ("pivot-bracket", "S2", [(("tools", "bracket-long-endmill", "verify"), "unknown")], "unknown"),
    ("pivot-shaft", "S1", [(("tools", "hss-toolbit-3-8-rh", "verify"), "unknown")], "unknown"),
    ("pivot-shaft", "S1", [((*MICROMETERS, "verify"), "unknown")], "unknown"),
    (
        "pivot-shaft",
        "S1",
        [((*MICROMETERS, "members"), {"0-1in": {"verify": "unknown"}})],
        "unknown",
    ),
    ("pivot-shaft", "S2", [(("gauges", "calipers", "verify"), "unknown")], "unknown"),
    # Flagged outright, the same.
    ("pivot-bracket", "S2", [((*FINDER, "verify"), True)], "unknown"),
    ("pivot-shaft", "S1", [((*MICROMETERS, "present"), "unknown")], "unknown"),
    # A finder's radius is half its tip, else its body, diameter, in either unit.
    ("pivot-bracket", "S2", [((*FINDER, "tip_in"), None), ((*FINDER, "dia_in"), 0.2)], "pass"),
    ("pivot-bracket", "S2", [((*FINDER, "tip_in"), None), ((*FINDER, "tip_mm"), 5.08)], "pass"),
    # A machine the inventory lists as absent is no lathe.
    ("pivot-shaft", "S1", [(("machines", "PM-1127VF-LB", "present"), False)], "unknown"),
    # An edge finder's procedure is the checker's: a band it does not state leaves the
    # zero unknown, and one no spindle band turns is the error to stop on.
    ("pivot-bracket", "S2", [((*FINDER, "rpm_range"), None)], "unknown"),
    ("pivot-bracket", "S2", [((*FINDER, "rpm_range"), [5000, 6000])], "error"),
]


def forged(value):
    """A value other than ``value`` of its own shape."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [] if isinstance(value, list) else {} if isinstance(value, dict) else "forged"
    return value + 1


@pytest.mark.parametrize(
    ("part", "setup_id", "path"),
    [
        # An edge finder's procedure box: its tip, the band it runs at, its verdict.
        ("pivot-bracket", "S2", ("axes", "x", "finder", "tip_dia_mm")),
        ("pivot-bracket", "S2", ("axes", "y", "finder", "rpm")),
        ("pivot-bracket", "S2", ("axes", "x", "finder", "status")),
        ("pivot-bracket", "S2", ("axes", "y", "finder")),
        # A lathe X touch: whether the diameter it measures stands, and its Axis Set.
        ("pivot-shaft", "S2", ("tool_touches", 0, "x_face_status")),
        ("pivot-shaft", "S2", ("tool_touches", 0, "x_axis_set")),
        ("pivot-shaft", "S1", ("tool_touches", 0, "x_face_status")),
    ],
)
def test_zero_rows_only_the_checker_derives_are_its_own_on_the_validators_inputs(
    freecad_kernel, part, setup_id, path
):
    """A zero row the checker derives (an edge finder's procedure, a lathe touch's
    measured diameter and Axis Set) is accepted as the checker derives it on the
    validator's own inputs, and rejected moved or dropped: no report value stands in."""
    setup, _, entries, own = zero_case(part, setup_id)
    native = native_zero(part, setup_id)
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    *parents, key = path
    for change in ("forge", "drop"):
        finding = copy.deepcopy(native)
        table = finding["numbers"]
        for parent in parents:
            table = table[parent]
        if change == "forge":
            table[key] = forged(table[key])
        else:
            del table[key]
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize(("part", "setup_id", "edits", "verdict"), ZERO_INVENTORY_EDITS)
def test_zero_readiness_radius_and_lathe_come_from_the_inventory(
    freecad_kernel, part, setup_id, edits, verdict
):
    """The engine's finding on the edited inventory is accepted with its own verdict only;
    the unedited inventory's (a retained report) no longer stands where the edit moves it."""
    setup, _, _, own = zero_case(part, setup_id)
    edit = inventory_edits(*edits)
    before = native_zero(part, setup_id)
    edit(own.inventory)
    entries = VALIDATOR["Entries"](own.inventory)
    native = native_zero(part, setup_id, inventory_edit=edit)
    assert native["status"] == verdict
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, {**native, "status": forged}, entries, own)
    if before != native:
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, before, entries, own)


def coverage_case():
    """The built-up cone's plan, manifest and report findings keyed by rule and subject,
    and the validator's coverage check on its own inventory read and native bundle load."""
    plan, features, inventory, _, report = cone_inputs()
    entries = VALIDATOR["Entries"](inventory)
    checked = VALIDATOR["checker_findings"](ROOT / "examples" / "cone-pivot-post" / "built-up.toml")

    def check(policy, plan, features, findings):
        VALIDATOR["check_required_coverage"](policy, plan, features, findings, entries, checked)

    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    return plan, features, findings, check


def coverage_row(rule, subject, selector, status="unknown"):
    return {"rule": rule, "subject": subject, "status": status, "numbers": {"required": selector}}


@pytest.mark.parametrize(
    ("rule", "selector", "subject"),
    [
        ("vise", ["S1", "S99"], "S99"),  # a setup the plan does not have
        ("not_implemented_check", "*", "*"),  # a rule no supported check implements
        ("not_implemented_check", [], "*"),  # an empty selection of one
    ],
)
def test_required_coverage_comes_from_the_policy_not_the_report(
    freecad_kernel, rule, selector, subject
):
    plan, features, findings, check = coverage_case()
    policy = {"required": {rule: selector}}
    key = (rule, subject)
    # A required subject no supported check covers has the checker's unknown coverage row.
    check(policy, plan, features, {**findings, key: coverage_row(rule, subject, selector)})
    # It cannot be dropped, approved or waived: no supported check exists to decide it.
    with pytest.raises(ValueError):
        check(policy, plan, features, findings)
    for status in ("pass", "not_applicable", "info"):
        row = coverage_row(rule, subject, selector, status)
        with pytest.raises(ValueError):
            check(policy, plan, features, {**findings, key: row})
    # Nor can a fabricated subject of the rule, which no check evaluates, stand in for it.
    fabricated = (rule, "S99:10" if subject == "S99" else "S1")
    with pytest.raises(ValueError):
        check(policy, plan, features, {**findings, fabricated: coverage_row(*fabricated, {})})
    with pytest.raises(ValueError):
        rows = {key: coverage_row(rule, subject, selector), fabricated: {"status": "pass"}}
        check(policy, plan, features, {**findings, **rows})


def test_required_coverage_row_carries_the_policys_selector(freecad_kernel):
    plan, features, findings, check = coverage_case()
    # An empty selection's coverage row is required by the policy's selection of its
    # rule, never by the selector the report prints on it.
    policy = {"required": {"vise": []}}
    star = coverage_row("vise", "*", [])
    assert VALIDATOR["report_exit"]({"findings": [star]}, policy, plan, features) == 4
    star["numbers"]["required"] = "forged"
    assert VALIDATOR["report_exit"]({"findings": [star]}, policy, plan, features) == 4
    policy = {"required": {"not_implemented_check": "*"}}
    key = ("not_implemented_check", "*")
    with pytest.raises(ValueError):
        row = coverage_row(*key, "forged")
        check(policy, plan, features, {**findings, key: row})


def test_rules_only_the_checker_models_are_its_own_rows_on_the_validators_inputs(
    freecad_kernel, tmp_path, monkeypatch
):
    """A rule of the checker's catalogue the validator does not model (consistency,
    purchased_tooling, or one the checker adds later) is the rows its own rule gives on the
    validator's own bundle load and kernel run: each is required with that rule's verdict
    and evidence. A row dropped or fabricated, an unknown reported passed or waived, a
    verdict moved either way, or one standing on other evidence is rejected. Here the shop
    requires purchased tooling and the edge finder's receipt checks are unknown."""
    examples = copy_examples(tmp_path)
    for name, table, line in (
        ("inventory/pedro-shop.toml", "[tools.edge-finder]\n", 'acceptance = "unknown"\n'),
        ("shop-policy.toml", "[required]\n", 'purchased_tooling = "*"\n'),
    ):
        path = examples / name
        text = path.read_text(encoding="utf-8")
        assert table in text
        path.write_text(text.replace(table, table + line, 1), encoding="utf-8")
    plan_path = examples / "pivot-bracket" / "plan.toml"
    bundle = load_bundle(plan_path)
    assert run_geometry(bundle)["status"] == "ok"

    def later(data):
        return [
            Finding("later_rule", s["id"], "unknown", {"setup": s["id"]}, [], "")
            for s in data.plan["setups"]
        ]

    rule_subjects = VALIDATOR["rule_subjects"]
    rules = [*RULES, Rule("later_rule", later)]
    monkeypatch.setitem(rule_subjects.__globals__, "CHECKER_RULES", rules)
    entries = VALIDATOR["Entries"](bundle.inventory)
    checked = VALIDATOR["checker_findings"](plan_path)
    domains = rule_subjects(bundle.plan, bundle.features, entries, checked)
    assert set(domains["later_rule"]) == {setup["id"] for setup in bundle.plan["setups"]}
    native = {
        (f.rule, f.subject): json.loads(json.dumps(f.to_dict()))
        for rule in rules
        for f in rule.evaluate(bundle)
    }
    findings = {
        (rule, subject): native.get((rule, subject), {"status": "pass", "numbers": {}})
        for rule, subjects in domains.items()
        for subject in subjects
    }
    receipts = {row["status"] for key, row in findings.items() if key[0] == "purchased_tooling"}
    assert "unknown" in receipts
    check = VALIDATOR["check_required_coverage"]

    def rejected(changed):
        with pytest.raises(ValueError):
            check(bundle.policy, bundle.plan, bundle.features, changed, entries, checked)

    check(bundle.policy, bundle.plan, bundle.features, findings, entries, checked)
    for rule in ("later_rule", "consistency", "purchased_tooling"):
        rejected({key: row for key, row in findings.items() if key[0] != rule})
        rejected({**findings, (rule, "S99"): {"status": "pass", "numbers": {}}})
        for key, row in findings.items():
            if key[0] != rule:
                continue
            for status in sorted({"pass", "unknown", "error", "not_applicable"} - {row["status"]}):
                rejected({**findings, key: {**row, "status": status}})
            rejected({**findings, key: {**row, "numbers": {**row["numbers"], "forged": True}}})


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_consistency_oracle_independently_rejects_uncertified_picture_grid(monkeypatch, status):
    fact = synthetic_fact(0.01)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    setup = {"id": "S1", "machine": "mill", "ops": []}
    plan = {"setups": [setup]}
    features = {"units": "mm", "features": {}}
    entries = VALIDATOR["Entries"]({"machines": {"mill": {"kind": "mill", "resolution_mm": fact}}})
    row = {
        "status": "pass",
        "numbers": {"claims": 1, "contradictions": [], "unchecked": []},
        "cite": ["kernel setup picture: closest_cut and per-op cut_clearances"],
    }
    check = VALIDATOR["check_required_coverage"]
    # Emulate a checker trust regression: equality to its own row alone would accept
    # this provisional printed claim. The oracle reads the unchanged source number.
    monkeypatch.setitem(
        check.__globals__, "rule_subjects", lambda *args: {"consistency": {"S1": row}}
    )
    findings = {("consistency", "S1"): row}
    if status == "measured":
        check({"required": {}}, plan, features, findings, entries, None)
    else:
        with pytest.raises(ValueError, match="unverified picture grid cannot pass"):
            check({"required": {}}, plan, features, findings, entries, None)
        row["status"] = "unknown"
        row["numbers"]["unchecked"] = ["synthetic picture grid is provisional"]
        check({"required": {}}, plan, features, findings, entries, None)


def cone_coordinates(tmp_path, setup_id, aim=None, measured=False):
    """The engine's coordinates finding for one setup of the built-up cone (``aim``
    replaces the requirement and value of plan ``aims.crank_bore``, which asks 39.517 of
    its 39.34-39.70 printed separation; ``measured`` runs the kernel first, as the CLI
    does, so kernel spans place rows), and a validator call that checks it against a
    plan."""
    plan_path = copy_examples(tmp_path) / "cone-pivot-post" / "built-up.toml"
    if aim is not None:
        text = plan_path.read_text(encoding="utf-8")
        authored = 'requirement = "separation"\nvalue_mm = 39.517\n'
        assert authored in text
        plan_path.write_text(text.replace(authored, aim), encoding="utf-8")
    # Fresh test grids in the copied input: both the native run and the validator's
    # independent kernel load must read the same facts. Shipped records stay illustrative.
    inventory_path = plan_path.parents[1] / "inventory" / "pedro-shop.toml"
    lines = inventory_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for machine, resolution in (("PM-30MV", 0.005), ("PM-1127VF-LB", 0.01)):
        start = lines.index(f"[machines.{machine}]\n")
        end = next(n for n in range(start + 1, len(lines)) if lines[n].startswith("["))
        reading = (
            f'resolution_mm = {{ value = {resolution}, measured = {{ status = "measured", '
            'by = "synthetic test operator", date = "2026-10-03", '
            'instrument = "synthetic test DRO" } }\n'
        )
        lines[start + 1 : end] = [
            reading if line.startswith("resolution_mm =") else line
            for line in lines[start + 1 : end]
        ]
    inventory_path.write_text("".join(lines), encoding="utf-8")
    bundle = load_bundle(plan_path)
    if measured:
        assert run_geometry(bundle)["status"] == "ok"
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == setup_id)
    finding = next(f for f in coordinates.evaluate(bundle) if f.subject == setup_id).to_dict()
    entries = VALIDATOR["Entries"](bundle.inventory)
    kernel = VALIDATOR["independent_kernel"](plan_path)

    def check(plan=bundle.plan):
        VALIDATOR["check_coordinates"](
            setup, bundle.features, finding, plan, entries, bundle.inventory, kernel
        )

    return bundle, setup, finding, check


def aimed_bore(tmp_path, aim=None):
    """The S8 coordinates of the cone's aimed crank bore (:func:`cone_coordinates`), its
    crank_bore row and the validator call."""
    bundle, _, finding, check = cone_coordinates(tmp_path, "S8", aim)
    (row,) = (row for row in finding["numbers"]["rows"] if row["feature"] == "crank_bore")
    return bundle, finding, row, check


def move(row, distance_mm):
    """Stand the aimed row ``distance_mm`` further along its aim's own direction."""
    nominal, aimed, shift = row["nominal_setup"], row["setup"], row["aim"]["shift_mm"]
    row["setup"] = [a + (a - n) / shift * distance_mm for n, a in zip(nominal, aimed, strict=True)]
    row["aim"]["shift_mm"] += distance_mm


@pytest.mark.parametrize(
    "corruption",
    [
        # The aim dropped: the bore printed at its CAD station.
        "nominal",
        # Moved the same 0.185 mm, away from the band's reference instead of toward it.
        "reversed",
        # Self-consistent: a CAD separation 0.1 mm short, so the bore moved 0.1 mm further.
        "nominal_distance",
        # Self-consistent: the report asks 39.6 where the plan asks 39.517.
        "asked_value",
        # A target the plan never aimed: the plan names no aim for it.
        "unaimed_plan",
    ],
)
def test_coordinate_oracle_stands_an_aimed_target_where_plan_aims_and_its_band_put_it(
    tmp_path, corruption
):
    bundle, finding, row, check = aimed_bore(tmp_path)
    check()
    aim, plan = row["aim"], bundle.plan
    if corruption == "nominal":
        row["setup"] = row.pop("nominal_setup")
        row.pop("aim")
    elif corruption == "reversed":
        move(row, -2 * aim["shift_mm"])
    elif corruption == "nominal_distance":
        move(row, 0.1)
        aim["nominal_mm"] -= 0.1
    elif corruption == "asked_value":
        move(row, 39.6 - aim["value_mm"])
        aim["value_mm"] = aim["value"] = 39.6
    else:
        plan = {key: value for key, value in plan.items() if key != "aims"}
    with pytest.raises(ValueError):
        check(plan)


@pytest.mark.parametrize("corruption", ["moved", "passed"])
def test_coordinate_oracle_holds_an_aim_its_band_cannot_place_to_its_nominal_target(
    tmp_path, corruption
):
    # An in-band diameter aim: the bore holds its separation, not its diameter, from
    # height_from, so the aim names no direction to move the target in.
    _, finding, row, check = aimed_bore(tmp_path, 'requirement = "dia"\nvalue_mm = 11.43\n')
    check()
    # Left at its CAD station the bore's 39.332 separation is also below the printed band.
    assert finding["status"] == "error" and "nominal_setup" not in row
    if corruption == "moved":
        # Moved anyway, as if it were the separation it does not name.
        row["nominal_setup"] = list(row["setup"])
        row["setup"][0] -= 0.185
        row["aim"].pop("why")
    else:
        finding["status"] = "pass"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    "corruption",
    [
        # The aim dropped from what the machinist reads: the feature map's DRO stop and
        # the hole op's dialled X/Y, together or alone, at the bore's CAD station.
        "dro_and_xy",
        "dro",
        "dro_xy",
        # Every stop re-rounded to a 0.01 grid the machine's 0.005 resolution never shows.
        "grid",
        # A station label (which skipped the at check) on the bore, moved along its axis
        # with its setup and nominal targets: self-consistent.
        "station",
        # The same, as if the kernel's faces of revolution placed this at-located bore.
        "kernel_span",
    ],
)
def test_coordinate_oracle_holds_the_printed_dro_target_to_the_aimed_point_on_the_grid(
    tmp_path, corruption
):
    bundle, finding, row, check = aimed_bore(tmp_path)
    check()
    nominal = row["nominal_setup"]
    if corruption in {"dro_and_xy", "dro"}:
        row["dro"][0] = nominal[0]
    if corruption in {"dro_and_xy", "dro_xy"}:
        row["dro_xy"][0] = nominal[0]
    if corruption == "grid":
        finding["numbers"]["dro_grid"] = {"step": 0.01, "decimals": 2}
        for other in finding["numbers"]["rows"]:
            if "dro" in other:
                other["dro"] = [round(value, 2) + 0.0 for value in other["setup"]]
                other["dro_xy"] = other["dro"][:2]
        assert row["dro"][0] != -72.885
    if corruption in {"station", "kernel_span"}:
        row["point"] = "station" if corruption == "station" else "setup Z axis, kernel span start"
        setup = next(s for s in bundle.plan["setups"] if s["id"] == "S8")
        frame = VALIDATOR["setup_frame"](setup, bundle.plan, bundle.features)
        axis = bundle.feature_definitions["crank_bore"]["axis"]
        model = [value + step for value, step in zip(row["model"], axis, strict=True)]
        delta = [
            moved - placed
            for moved, placed in zip(
                VALIDATOR["frame_point"](model, frame),
                VALIDATOR["frame_point"](row["model"], frame),
                strict=True,
            )
        ]
        row["model"] = model
        for key in ("setup", "nominal_setup"):
            row[key] = [value + step for value, step in zip(row[key], delta, strict=True)]
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("status", ["not_applicable", "info"])
def test_a_cutting_setups_coordinates_are_a_verdict_never_a_waiver(tmp_path, status):
    # Only a manual bench setup waives its coordinates; S8 mills the aimed crank bore.
    _, finding, _, check = aimed_bore(tmp_path)
    check()
    finding["status"] = status
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("corruption", ["x_target", "station_z"])
def test_coordinate_oracle_holds_a_lathe_station_to_the_manifest_and_its_op(tmp_path, corruption):
    bundle, setup, finding, check = cone_coordinates(tmp_path, "S1")
    check()
    row = next(
        row
        for row in finding["numbers"]["rows"]
        if row.get("point", "").startswith("op ") and isinstance(row.get("dia_nominal"), float)
    )
    if corruption == "x_target":
        # The feature map's "turn to" diameter 1 mm over the manifest's nominal.
        ratio = row["x_target_mm"] / row["dia_nominal"]
        row["dia_nominal"] += 1.0
        row["x_target_mm"] = row["dia_nominal"] * ratio
    else:
        # The op's Z end 1 mm off its authored value, model and setup moved together.
        frame = VALIDATOR["setup_frame"](setup, bundle.plan, bundle.features)
        row["setup"][2] += 1.0
        row["model"] = VALIDATOR["model_point"](row["setup"], frame)
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("setup_id", ["S11", "S1"])
def test_coordinate_oracle_ends_a_kernel_span_where_its_own_kernel_run_measures_it(
    tmp_path, freecad_kernel, setup_id
):
    # The head's span start, 5 mm further along setup -Z with its model point (and on the
    # S11 mill its DRO stop) moved to match: self-consistent, as if the kernel measured the
    # head that much longer. S1 is the lathe, S11 the mill.
    bundle, setup, finding, check = cone_coordinates(tmp_path, setup_id, measured=True)
    check()
    row = next(
        row
        for row in finding["numbers"]["rows"]
        if row.get("feature") == "head" and row.get("point", "").endswith("kernel span start")
    )
    frame = VALIDATOR["setup_frame"](setup, bundle.plan, bundle.features)
    row["setup"][2] -= 5.0
    row["model"] = VALIDATOR["model_point"](row["setup"], frame)
    if "dro" in row:
        entries = VALIDATOR["Entries"](bundle.inventory)
        grid = VALIDATOR["dro_grid"](setup, bundle.features, entries)
        row["dro"] = [VALIDATOR["dro_target"](value, grid) for value in row["setup"]]
        row["dro_xy"] = row["dro"][:2]
    with pytest.raises(ValueError):
        check()


@pytest.fixture(scope="module")
def rocker_blank(freecad_kernel):
    """An isolated rocker prepared-blank case with fresh test cutter/support/gauge
    facts and its native kernel cut. The shipped example remains unverified."""
    bundle = load_bundle(ROOT / "examples" / "rocker-arm" / "plan.toml")
    synthetic_prep_geometry(bundle)
    bundle.inventory["gauges"]["calipers-18in"] = {
        "kind": "caliper",
        "range_mm": [0.0, 450.0],
        "resolution_mm": synthetic_fact(0.02),
    }
    facts = run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    return bundle, facts


def blank_case(rocker_blank, case=None):
    """The engine's own ``prepared_blank`` finding for the rocker-arm with ``case`` changed
    in its plan, inventory or kernel facts, and a validator call that checks a candidate
    finding against those inputs and facts (returning the gauges it cannot resolve)."""
    bundle, facts = copy.deepcopy(rocker_blank)
    prepared = bundle.plan["stock"]["prepared"]
    gauges = bundle.inventory["gauges"]
    cut = facts["setups"]["P5"]
    if case == "missing_form_limit":
        prepared["form_mm"].pop("flat")
    elif case == "unknown_form_limit":
        prepared["form_mm"]["flat"] = "unknown"
    elif case == "missing_form_method":
        prepared["methods"].pop("flat")
    elif case == "gauge_range_short":
        prepared["checks"]["length"] = "calipers"  # a 6 in caliper on the 340 mm length
    elif case == "gauge_resolution_coarse":
        gauges["calipers-18in"]["resolution_mm"] = 1.0
    elif case == "gauge_verify_unknown":
        gauges["calipers-18in"]["verify"] = "unknown"
    elif case == "missing_gauge":
        prepared["checks"]["length"] = "calipers-36in"
    elif case == "undeclared_gauge":
        del prepared["checks"]["flat"]
    elif case == "kernel_unavailable":
        facts = {"status": "unknown", "kernel_unavailable": True}
    elif case == "cut_unexplained":
        cut["stock_out_reason"] = "unknown milling pass"
    elif case == "cut_missing":
        del facts["setups"]["P5"]
    elif case == "cut_half_volume":
        cut["stock_out_volume_mm3"] *= 0.5
    elif case == "cut_long":
        cut["stock_out_bbox_mm"][3] += 5.0
    object.__setattr__(bundle, "kernel", facts)
    native = prepared_blank.evaluate(bundle)[0].to_dict()

    def check(finding):
        """``finding`` None: the report carries no prepared_blank finding."""
        return VALIDATOR["check_prepared_blank"](
            bundle.plan,
            bundle.features,
            bundle.inventory,
            {} if finding is None else {("prepared_blank", "stock.prepared"): finding},
            lambda: facts,
        )

    return bundle, native, check


@pytest.fixture
def host_rocker_blank(monkeypatch):
    """Raw authored inputs with explicitly synthetic handed-on stock, never a native run."""
    bundle = load_bundle(ROOT / "examples" / "rocker-arm" / "plan.toml")
    raw = {
        name: tomllib.loads(bundle.paths[name].read_text(encoding="utf-8"))
        for name in ("plan", "features", "inventory")
    }
    bundle = replace(
        bundle,
        **raw,
        kernel={
            "status": "ok",
            "setups": {
                "P5": {
                    "stock_out_bbox_mm": [-170.0, -20.0, -8.0, 170.0, 45.0, 8.0],
                    "stock_out_volume_mm3": 340.0 * 65.0 * 16.0,
                }
            },
        },
    )

    def injected_geometry(selected):
        if selected.kernel is None:
            pytest.fail("the host prepared-blank oracle fixture must never request native geometry")
        return selected.kernel

    monkeypatch.setattr("prechips.kernel.run_geometry", injected_geometry)
    return bundle


def test_prepared_member_oracle_reads_the_authored_nominal_micrometer_resolution(host_rocker_blank):
    bundle, native, check = blank_case((host_rocker_blank, host_rocker_blank.kernel))
    assert bundle.inventory["gauges"]["micrometers"]["resolution_in"] == 0.0001
    assert native["status"] == "pass"
    for key in ("section_0", "section_1"):
        assert native["numbers"]["checks"][key]["resolution_mm"] == pytest.approx(0.00254)
    assert check(native) == []


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
@pytest.mark.parametrize(
    ("field", "value"), [("resolution_mm", 0.00254), ("resolution_in", 0.0001)]
)
def test_prepared_member_oracle_keeps_fact_local_trust_and_named_debt(
    host_rocker_blank, qualified, status, field, value
):
    gauge = host_rocker_blank.inventory["gauges"]["micrometers"]
    gauge.pop("resolution_in")
    fact = synthetic_fact(value)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    gauge[field] = fact
    if qualified:
        checks = host_rocker_blank.plan["stock"]["prepared"]["checks"]
        for key in ("section_0", "section_1"):
            checks[key] = f"gauges.{checks[key]}"
    _, native, check = blank_case((host_rocker_blank, host_rocker_blank.kernel))
    trusted = status == "measured"
    assert native["status"] == ("pass" if trusted else "unknown")
    assert check(native) == []
    rows = native["numbers"]["checks"]
    for key in ("section_0", "section_1"):
        assert rows[key]["status"] == ("pass" if trusted else "unknown")
        if trusted:
            assert rows[key]["resolution_mm"] == pytest.approx(0.00254)
            assert "measurements" not in rows[key]
        else:
            assert rows[key]["resolution_mm"] == "unknown"
            assert len(rows[key]["measurements"]) == 1
    if trusted:
        assert "measurements" not in native["numbers"]
    else:
        debts = native["numbers"]["measurements"]
        assert {debt["id"] for debt in debts} == {
            "gauges.micrometers/0-1in.resolution",
            "gauges.micrometers/2-3in.resolution",
        }
        for debt in debts:
            assert debt["status"] == (status or "assumed")
            assert debt["instruction"].startswith("measure:")
            assert f"inventory.{debt['id']}" in debt["cite"]
        forged = copy.deepcopy(native)
        forged["status"] = "pass"
        for key in ("section_0", "section_1"):
            forged["numbers"]["checks"][key]["status"] = "pass"
            forged["numbers"]["checks"][key]["resolution_mm"] = 0.00254
        with pytest.raises(ValueError, match="verdict"):
            check(forged)
        for missing in ("row", "aggregate"):
            unnamed = copy.deepcopy(native)
            if missing == "row":
                del unnamed["numbers"]["checks"]["section_0"]["measurements"]
            else:
                del unnamed["numbers"]["measurements"]
            with pytest.raises(ValueError, match="evidence"):
                check(unnamed)


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_prepared_form_oracle_retains_named_resolution_debt(host_rocker_blank, status):
    gauge = host_rocker_blank.inventory["gauges"]["dti"]
    fact = synthetic_fact(0.0005)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    gauge["resolution_in"] = fact
    _, native, check = blank_case((host_rocker_blank, host_rocker_blank.kernel))
    trusted = status == "measured"
    assert native["status"] == ("pass" if trusted else "unknown")
    assert check(native) == []
    for key in ("flat", "square", "parallel"):
        row = native["numbers"]["checks"][key]
        assert row["status"] == ("pass" if trusted else "unknown")
        if trusted:
            assert row["resolution_mm"] == pytest.approx(0.0127)
            assert "measurements" not in row
        else:
            assert row["resolution_mm"] == "unknown"
            assert [debt["id"] for debt in row["measurements"]] == ["gauges.dti.resolution"]
    if trusted:
        assert "measurements" not in native["numbers"]
    else:
        debts = native["numbers"]["measurements"]
        assert len(debts) == 1
        assert debts[0]["id"] == "gauges.dti.resolution"
        assert debts[0]["status"] == (status or "assumed")
        assert debts[0]["instruction"].startswith("measure:")
        forged = copy.deepcopy(native)
        forged["status"] = "pass"
        with pytest.raises(ValueError, match="verdict"):
            check(forged)


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_resolved_member_scalar_range_oracle_keeps_its_own_trust(status):
    fact = synthetic_fact(300.0)
    if status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = status
    gauge = {
        "kind": "micrometer_set",
        "range_mm": fact,
        "resolution_mm": synthetic_fact(0.001),
    }
    row = {}
    verdict = VALIDATOR["blank_size_check"](gauge, [20.0, 20.1], {"units": "mm"}, row)
    assert row["resolution_mm"] == 0.001
    if status == "measured":
        assert verdict == "pass"
        assert row["range_mm"] == [0.0, 300.0]
    else:
        assert verdict == "unknown"
        assert row["range_mm"] == "unknown"


@pytest.mark.parametrize("verification", [True, "unknown"])
@pytest.mark.parametrize("location", ["fact", "item"])
def test_prepared_member_oracle_preserves_legacy_verification_debt(
    host_rocker_blank, verification, location
):
    gauge = host_rocker_blank.inventory["gauges"]["micrometers"]
    if location == "fact":
        gauge["resolution_in"] = synthetic_fact(0.0001) | {"verify": verification}
    else:
        gauge["verify"] = verification
    _, native, check = blank_case((host_rocker_blank, host_rocker_blank.kernel))
    assert native["status"] == "unknown"
    assert check(native) == []
    # Resolution's legacy verify flag propagates to the selected member's identity;
    # both consumed dimensions retain their debt, including its generated raw range.
    assert {debt["id"] for debt in native["numbers"]["measurements"]} == {
        f"gauges.micrometers/{member}.{field}"
        for member in ("0-1in", "2-3in")
        for field in ("range", "resolution")
    }
    forged = copy.deepcopy(native)
    forged["status"] = "pass"
    with pytest.raises(ValueError, match="verdict"):
        check(forged)


@pytest.mark.parametrize("case", ["kernel_unavailable", "cut_unexplained", "cut_missing"])
def test_prepared_member_oracle_never_approves_an_underivable_cut(host_rocker_blank, case):
    _, native, check = blank_case((host_rocker_blank, host_rocker_blank.kernel), case)
    assert native["status"] == "unknown"
    assert check(native) == []
    assert "measurements" not in native["numbers"]
    forged = copy.deepcopy(native)
    forged["status"] = "pass"
    with pytest.raises(ValueError, match="verdict"):
        check(forged)


@pytest.mark.parametrize(
    "case",
    [
        "missing_form_limit",
        "unknown_form_limit",
        "missing_form_method",
        "gauge_range_short",
        "gauge_resolution_coarse",
        "gauge_verify_unknown",
        "missing_gauge",
        "undeclared_gauge",
        "kernel_unavailable",
        "cut_unexplained",
        "cut_missing",
        "cut_half_volume",
        "cut_long",
    ],
)
def test_prepared_blank_approval_comes_from_its_gauges_and_kernel_cut(rocker_blank, case):
    # A blank its gauges cannot read (no form limit or method, a caliper short of the
    # length or too coarse for its band, an unverified, missing or undeclared gauge) or
    # its kernel cut does not explain (no run, an unexplained or missing cut, a cut that
    # is not the declared box) is not approved. The engine's own unresolved or failed
    # finding is accepted; the same finding with every check row and the verdict
    # approved is not.
    _, native, check = blank_case(rocker_blank, case)
    assert native["status"] != "pass"
    check(native)
    forged = copy.deepcopy(native)
    forged["status"] = "pass"
    for row in forged["numbers"].get("checks", {}).values():
        row["status"] = "pass"
    with pytest.raises(ValueError):
        check(forged)


@pytest.mark.parametrize("case", [None, "missing_gauge"])
def test_prepared_blank_reports_the_gauges_it_cannot_resolve(rocker_blank, case):
    bundle, native, check = blank_case(rocker_blank, case)
    entries = VALIDATOR["Entries"](bundle.inventory)
    # No setup names them, so no tool_resolves finding reads them.
    stock_only = {"stock": bundle.plan["stock"], "setups": []}
    assert VALIDATOR["check_references"](stock_only, bundle.features, entries, {}) == []
    assert check(native) == (["calipers-36in"] if case else [])


@pytest.mark.parametrize(
    "corruption",
    [
        "other_gauge",
        "size_band",
        "gauge_range",
        "form_limit",
        "method",
        "row_not_approved",
        "checks_never_read",
        "dropped_row",
        "cut_volume",
        "no_finding",
        "approved_without_blank",
    ],
)
def test_prepared_blank_verdict_holds_to_the_plan_gauges_and_inventory(rocker_blank, corruption):
    bundle, native, check = blank_case(rocker_blank)
    assert native["status"] == "pass"
    check(native)
    finding = copy.deepcopy(native)
    rows = finding["numbers"]["checks"]
    prepared = bundle.plan["stock"]["prepared"]
    if corruption == "other_gauge":
        rows["length"]["gauge"] = "calipers"
    elif corruption == "size_band":
        rows["length"]["limits_mm"] = [339.0, 341.0]
    elif corruption == "gauge_range":
        rows["length"]["range_mm"] = [0, 1000]
    elif corruption == "form_limit":
        rows["flat"]["limit_mm"] = 0.5
    elif corruption == "method":
        rows["square"]["method"] = prepared["methods"]["flat"]
    elif corruption == "row_not_approved":
        rows["square"]["status"] = "unknown"
    elif corruption == "checks_never_read":
        del finding["numbers"]["checks"]
    elif corruption == "dropped_row":
        del rows["parallel"]
    elif corruption == "cut_volume":
        finding["numbers"]["cut_volume_mm3"] *= 1.5
    elif corruption == "no_finding":
        finding = None
    elif corruption == "approved_without_blank":
        del bundle.plan["stock"]["prepared"]
    with pytest.raises(ValueError):
        check(finding)


def test_validator_rejects_a_check_without_its_feature_requirement():
    plan = {
        "setups": [
            {"id": "S3", "ops": [{"op": 10, "feature": "dome", "checks": {"length": "calipers"}}]}
        ]
    }
    features = {"features": {"dome": {"requirements": ["height"]}}}
    with pytest.raises(ValueError, match="dome has no requirement length"):
        VALIDATOR["check_inspection_declarations"](plan, features, {})


@pytest.mark.parametrize("status,missing", [("pass", True), ("unknown", False), (None, None)])
def test_validator_rejects_silently_dropped_or_cleared_missing_requirement(status, missing):
    plan = {
        "setups": [
            {
                "id": "S3",
                "ops": [
                    {
                        "op": 30,
                        "feature": "bearing",
                        "missing_requirements": {"length": "calipers"},
                    }
                ],
            }
        ]
    }
    features = {"features": {"bearing": {"requirements": ["dia"]}}}
    findings = {
        ("inspection", "bearing:length"): {
            "status": status,
            "numbers": {"missing_requirement": missing},
        }
    }
    with pytest.raises(ValueError, match="missing requirement inspection"):
        VALIDATOR["check_inspection_declarations"](plan, features, findings)


@pytest.mark.parametrize(
    ("kind", "action", "requirements", "missing", "expected"),
    [
        ("face", "inspect", [], False, {"surface"}),
        ("face", "inspect", [], True, {"surface:finish_quality"}),
        ("unknown", "inspect", [], True, {"surface", "surface:finish_quality"}),
        ("face", "unknown", [], True, {"surface", "surface:finish_quality"}),
        ("face", "inspect", "unknown", True, {"surface:unknown", "surface:finish_quality"}),
        ("face", "inspect", ["unknown"], True, {"surface:unknown", "surface:finish_quality"}),
        ("face", "inspect", ["length"], True, {"surface:length", "surface:finish_quality"}),
        ("unknown", "inspect", ["length"], True, {"surface:length", "surface:finish_quality"}),
    ],
)
def test_inspection_subject_oracle_preserves_missing_requirements_and_unknown_applicability(
    kind, action, requirements, missing, expected
):
    feature = {"kind": kind, "requirements": requirements, "length": "unknown"}
    op = {"op": 10, "do": action, "feature": "surface"}
    if missing:
        op["missing_requirements"] = {"finish_quality": "unknown"}
    plan = {"setups": [{"id": "S", "ops": [op]}]}
    assert VALIDATOR["inspection_subjects"](plan, {"surface": feature}) == expected


@pytest.mark.parametrize("requirement", ["smooth_open_close", "hidden_seam", "burrs_and_chips"])
@pytest.mark.parametrize("corruption", ["dropped", "passed", "unmarked"])
def test_subject_oracle_keeps_magic_tube_named_inspection_debt_instead_of_a_bare_waiver(
    requirement, corruption
):
    folder = ROOT / "examples" / "blondihacks-magic-tube"
    data = load_bundle(folder / "plan.toml")
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    expected = {
        "all-surfaces:smooth_open_close",
        "all-surfaces:hidden_seam",
        "all-surfaces:burrs_and_chips",
    }
    assert data.features["features"]["all-surfaces"]["requirements"] == []
    assert {
        subject
        for rule, subject in findings
        if rule == "inspection" and subject.split(":", 1)[0] == "all-surfaces"
    } == expected
    for subject in expected:
        row = findings["inspection", subject]
        assert row["status"] == "unknown"
        assert row["numbers"]["missing_requirement"] is True
        assert row["numbers"]["limits"] == "unknown"
    check = VALIDATOR["check_subjects"]
    declarations = VALIDATOR["check_inspection_declarations"]
    check(data.plan, data.features, findings, data.inventory)
    declarations(data.plan, data.features, findings)
    key = "inspection", f"all-surfaces:{requirement}"
    if corruption == "dropped":
        del findings[key]
        with pytest.raises(ValueError, match=f"missing finding inspection:{key[1]}"):
            check(data.plan, data.features, findings, data.inventory)
    else:
        if corruption == "passed":
            findings[key]["status"] = "pass"
        else:
            findings[key]["numbers"]["missing_requirement"] = False
        with pytest.raises(ValueError, match="missing requirement inspection"):
            declarations(data.plan, data.features, findings)


@pytest.mark.parametrize(
    "rule,action",
    [
        ("tool_resolves", "ream"),
        ("tool_resolves", "coating"),
        ("inspection", None),
        ("joint_fit", None),
        ("joint_assembly", None),
    ],
)
def test_built_up_subject_contract_excludes_manual_assembly_but_keeps_joint_debt(rule, action):
    plan, features, inventory, _, report = cone_inputs(fresh_pure=True)
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    joint_setup = next(
        s for s in plan["setups"] if s.get("joint", {}).get("socket") == "crank_socket"
    )
    tool_setup, tool_op = next(
        (s, op)
        for s in plan["setups"]
        for op in s["ops"]
        if op["do"] == (action or "ream")
        and (action == "coating" or op.get("feature") == "crank_socket")
    )
    subject = {
        "tool_resolves": f"{tool_setup['id']}:{tool_op['op']}",
        "inspection": f"{joint_setup['joint']['socket']}:dia",
        "joint_fit": joint_setup["id"],
        "joint_assembly": joint_setup["id"],
    }[rule]
    missing = rule, subject
    # Fitting/inspection requires no cutting assembly. Coating still has a required
    # consumable-process identity finding, even when it uses the same manual bench.
    for setup in plan["setups"]:
        if VALIDATOR["manual_bench"](inventory, setup) is not None:
            for op in setup["ops"]:
                if op["do"] in {"fit", "inspect"}:
                    findings.pop(("tool_resolves", f"{setup['id']}:{op['op']}"), None)
    VALIDATOR["check_subjects"](plan, features, findings, inventory)
    del findings[missing]
    with pytest.raises(ValueError, match=f"missing finding {missing[0]}:{missing[1]}"):
        VALIDATOR["check_subjects"](plan, features, findings, inventory)


def joined(unresolved=None, error=None):
    """Synthetic kernel facts for the built-up cone's joins: S6 and S7 each derive their
    joined stock with these joint features completed. ``unresolved`` names a join whose
    joined stock that run leaves unknown (as it does for unknown fit bands), or, given an
    ``error``, refuses."""
    completed = ["cone_socket", "cone_spigot", "crank_socket"]
    setups = {
        sid: {
            "stock_bbox_mm": [[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]],
            "completed_joint_features": done,
        }
        for sid, done in (("S6", completed), ("S7", [*completed, "crank_spigot"]))
    }
    if unresolved is not None:
        done = setups[unresolved]["completed_joint_features"]
        setups[unresolved] = {"completed_joint_features": done}
        if error is None:
            setups[unresolved]["stock_reason"] = "joint fit diameter bands are unknown"
        else:
            setups[unresolved]["assembly_error"] = error
    return lambda: {"status": "ok", "setups": setups}


@pytest.mark.parametrize(
    "corruption", ["fit_pass", "missing", "socket", "assembly_pass", "branches"]
)
def test_built_up_joint_report_cannot_clear_numeric_debt_or_change_identity(corruption):
    plan, features, _, _, report = cone_inputs(fresh_pure=True, joint_kernel=joined())
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    kernel = joined()
    VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S7")
    fit = findings["joint_fit", "S7"]
    assembly = findings["joint_assembly", "S7"]
    if corruption in {"fit_pass", "missing", "assembly_pass"}:
        # The shipped joint resolves, so declare numeric debt in the plan: the
        # report must then carry it and neither row may approve.
        setup["joint"]["clearance_mm"] = "unknown"
        kernel = joined("S7")
        fit = next(
            row.to_dict()
            for row in joints.evaluate_fit(SimpleNamespace(plan=plan, features=features))
            if row.subject == "S7"
        )
        findings["joint_fit", "S7"] = fit
        assert fit["status"] == "unknown"
        assert fit["numbers"]["missing"] == ["setups[S7].joint.clearance_mm"]
        assert all(
            fit["numbers"][key] == "unknown"
            for key in ("band_mm", "guaranteed_mm", "engagement_mm", "engagement_dia_mm")
        )
        assembly["status"] = "unknown"
        VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)
    if corruption == "fit_pass":
        fit["status"] = "pass"
    elif corruption == "missing":
        fit["numbers"]["missing"] = []
    elif corruption == "socket":
        fit["numbers"]["socket"] = fit["numbers"]["spigot"]
    elif corruption == "assembly_pass":
        assembly["status"] = "pass"
    else:
        assembly["numbers"]["stock_in"].reverse()
    with pytest.raises(ValueError, match="joint|assembly"):
        VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)


@pytest.mark.parametrize(
    "corruption", ["unresolved", "refused", "no_kernel", "no_setup_facts", "completed"]
)
def test_joint_assembly_verdict_is_the_validators_own_kernel_join(corruption):
    # The report's assembly verdict is not accepted when the validator's own kernel leaves
    # its joined stock unknown, refuses it, never ran or derived nothing for S7; or the
    # report claims a joint feature completed that the join never completed.
    plan, features, _, _, report = cone_inputs(joint_kernel=joined())
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    assembly = findings["joint_assembly", "S7"]
    VALIDATOR["check_joint_declarations"](plan, features, findings, joined())
    assert assembly["status"] == "pass"
    facts = joined()()
    if corruption == "unresolved":
        facts = joined("S7")()
    elif corruption == "refused":
        facts = joined("S7", error="spigot insertion sweep meets socket material")()
    elif corruption == "no_kernel":
        facts = {"status": "unknown", "kernel_unavailable": True, "reason": "no FreeCAD"}
    elif corruption == "no_setup_facts":
        del facts["setups"]["S7"]
    else:
        facts["setups"]["S7"]["completed_joint_features"].remove("crank_spigot")
    with pytest.raises(ValueError):
        VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)


UNAVAILABLE = {"status": "unknown", "kernel_unavailable": True, "reason": "no FreeCAD"}
REFUSED = "spigot insertion sweep meets socket material"


@pytest.mark.parametrize(
    ("run", "sid", "status", "numbers"),
    [
        # No kernel ran: an always-required join is unknown debt, never inapplicable,
        # whether the report keeps synthetic joined evidence or the kernel's failure.
        ("unavailable", "S6", "not_applicable", "joined"),
        ("unavailable", "S7", "not_applicable", "joined"),
        ("unavailable", "S7", "not_applicable", None),
        # The validator's run refused S7: the report cannot call it unavailable debt.
        ("refused", "S7", "unknown", {"kernel_status": "unknown", "kernel_unavailable": True}),
        ("refused", "S7", "unknown", {"kernel_status": "unavailable"}),
        ("refused", "S7", "error", {"kernel_status": "error"}),
        # The validator's run joined S7: a reported kernel failure is not that run.
        ("joined", "S7", "unknown", {"kernel_status": "unknown", "kernel_unavailable": True}),
        ("joined", "S7", "error", {"kernel_status": "error"}),
    ],
)
def test_joint_assembly_report_cannot_name_a_kernel_outcome_its_validator_did_not_run(
    run, sid, status, numbers
):
    plan, features, _, _, report = cone_inputs(joint_kernel=joined())
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    joined_numbers = copy.deepcopy(findings["joint_assembly", sid]["numbers"])
    if run == "unavailable":
        facts = UNAVAILABLE
        for subject in ("S6", "S7"):
            findings["joint_assembly", subject].update(
                status="unknown", numbers={"kernel_status": "unknown", "kernel_unavailable": True}
            )
    elif run == "refused":
        facts = joined("S7", error=REFUSED)()
        findings["joint_assembly", "S7"]["status"] = "error"
    else:
        facts = joined()()
    VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)
    findings["joint_assembly", sid]["status"] = status
    if numbers is not None:
        findings["joint_assembly", sid]["numbers"] = (
            joined_numbers if numbers == "joined" else numbers
        )
    with pytest.raises(ValueError):
        VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)


@pytest.mark.parametrize("corruption", ["shared_ancestor", "wrong_role", "finished_face"])
def test_joint_identity_and_exported_face_contract_remain_strict(corruption):
    plan, features, inventory, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S7")
    if corruption == "shared_ancestor":
        setup["stock_in"] = ["S6", "S4"]
    elif corruption == "wrong_role":
        setup["joint"]["socket"] = "crank_spigot"
    else:
        features["features"]["crank_boss"]["faces"] = ["plan.joint_features.crank_spigot"]
    with pytest.raises(ValueError, match="ancestor|kind cylinder_bore|finished STEP faces"):
        VALIDATOR["check_subjects"](plan, features, findings, inventory)


@pytest.mark.parametrize("rule", ["joint_fit", "joint_assembly", "centre_support"])
def test_unresolved_always_required_rule_needs_no_shop_policy_permission(rule):
    plan, features, _, _, _ = cone_inputs()
    report = {"findings": [{"rule": rule, "subject": "S7", "status": "unknown", "numbers": {}}]}
    assert VALIDATOR["report_exit"](report, {"required": {}}, plan, features) == 4


@pytest.mark.parametrize(
    ("selector", "subject"),
    [("holes", "crank_socket"), ("toleranced_features", "crank_spigot:dia")],
)
def test_required_selectors_include_transient_joint_requirements(selector, subject):
    plan, features, _, _, _ = cone_inputs()
    finding = {"rule": "inspection", "subject": subject, "numbers": {}}
    assert VALIDATOR["required_finding"](
        finding, {"required": {"inspection": selector}}, plan, features
    )


def test_joint_checks_use_operative_requirements_without_inventing_drawing_fields():
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S3")
    op = {"op": 60, "feature": "crank_spigot", "checks": {"dia": "calipers"}}
    setup["ops"].append(op)
    VALIDATOR["check_inspection_declarations"](plan, features, findings)
    op["missing_requirements"] = op.pop("checks")
    with pytest.raises(ValueError, match="crank_spigot.dia is an exported requirement"):
        VALIDATOR["check_inspection_declarations"](plan, features, findings)


@pytest.mark.parametrize(
    ("facts", "status"), [(UNAVAILABLE, "unknown"), ({"status": "error", "reason": "x"}, "error")]
)
def test_joint_kernel_failure_cannot_be_approved_without_assembly_evidence(facts, status):
    # The validator's own run failed: each join carries that failure, and none approves.
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    numbers = {"kernel_status": facts["status"]}
    if facts.get("kernel_unavailable"):
        numbers["kernel_unavailable"] = True
    for sid in ("S6", "S7"):
        findings["joint_assembly", sid].update(status=status, numbers=dict(numbers))
    VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)
    findings["joint_assembly", "S7"]["status"] = "pass"
    with pytest.raises(ValueError):
        VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)


@pytest.mark.parametrize(
    ("bands", "expected"),
    [
        ([[100, 500], [1000, 2000]], 500),
        ([[100, 600], [900, 2000]], 600),
        ([[100, 400], [900, 2000]], 400),
        ("unknown", "unknown"),
        ([[4000, 5000]], "unknown"),
    ],
)
def test_speed_oracle_projects_the_derated_rpm_onto_available_bands(bands, expected):
    # 100 sfm, quarter-inch drill, factor 0.5 => rounded 750 RPM. The gap is not turnable;
    # even a closer faster endpoint is refused; feed uses the slower available speed.
    data = drill_bundle(depth_mm=40.0, deep=(DEEP,))
    machine = data.inventory["machines"][data.plan["setups"][0]["machine"]]
    machine["spindle"]["ranges_rpm"] = bands
    finding, check = speed_finding(data)
    assert finding["numbers"]["rpm"] == expected
    assert finding["numbers"]["feed_mm_min"] == (
        expected * finding["numbers"]["flutes"] * finding["numbers"]["chip_load_mm_per_tooth"]
        if isinstance(expected, (int, float))
        else "unknown"
    )
    check()
    finding["numbers"]["rpm"] = 750
    finding["numbers"]["feed_mm_min"] = (
        750 * finding["numbers"]["flutes"] * finding["numbers"]["chip_load_mm_per_tooth"]
    )
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("declaration", "native", "tolerance"),
    [
        ({"fixture": "head", "rotation": "continuous"}, "pass", None),
        ({"fixture": "head", "rotation": "unknown"}, "unknown", None),
        ({"fixture": "head", "rotation": "continuous", "positions": 4}, "error", None),
        ({"fixture": "absent", "rotation": "continuous"}, "error", None),
        ({"fixture": "unknown", "rotation": "continuous"}, "unknown", None),
        ("unknown", "unknown", 1.0),
        ({"fixture": "head", "positions": 4}, "pass", 1.0),
        ({"fixture": "head", "feature": "unknown", "positions": 4}, "unknown", "unknown"),
        ({"fixture": "head", "feature": "pattern", "positions": "unknown"}, "unknown", 1.0),
        ({"fixture": "head", "feature": "pattern", "positions": 1}, "unknown", 1.0),
    ],
)
def test_indexing_oracle_handles_continuous_and_unresolved_declarations(
    declaration, native, tolerance
):
    setup = {"id": "S1", "hold": {"index": declaration}, "ops": []}
    features = {
        "features": {"pattern": {"angle_tol_deg": 1.0}},
        "general_tolerances": {"angular_deg": 1.0},
    }
    inventory = {
        "machines": {
            "head": {
                "kind": "dividing_head",
                "verify": False,
                "worm_ratio": 40,
                "plate_holes": {"A": [15]},
                "direct_index": {"positions": 24},
            }
        }
    }
    bundle = SimpleNamespace(
        plan={"setups": [setup]},
        features=features,
        feature_definitions=features["features"],
        inventory=inventory,
    )
    (finding,) = (f.to_dict() for f in indexing.evaluate(bundle))
    assert finding["status"] == native
    if tolerance is not None:
        assert finding["numbers"]["tolerance_deg"] == tolerance
    entries = VALIDATOR["Entries"](inventory)
    VALIDATOR["check_indexing"](setup, features, entries, finding)
    for forged in {"pass", "unknown", "error"} - {native}:
        with pytest.raises(ValueError):
            VALIDATOR["check_indexing"](setup, features, entries, {**finding, "status": forged})
    if tolerance is not None:
        corrupted = copy.deepcopy(finding)
        corrupted["numbers"]["tolerance_deg"] = "unknown" if tolerance == 1.0 else 1.0
        with pytest.raises(ValueError, match="indexing tolerance_deg"):
            VALIDATOR["check_indexing"](setup, features, entries, corrupted)


@pytest.mark.parametrize("binding", ["nominal", "unknown"])
@pytest.mark.parametrize("kind", ["hole", "profile"])
@pytest.mark.parametrize("z", [3.0, "unknown"])
@pytest.mark.parametrize("grid_status", ["measured", "assumed", "illustrative", None, "bare"])
def test_ordinary_coordinate_verdict_is_derived_from_source_targets(binding, kind, z, grid_status):
    frame = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "binding": binding,
    }
    features = {
        "units": "mm",
        "frames": {"model": frame},
        "features": {"hole": {"kind": kind, "at": [1.0, 2.0, z]}},
    }
    setup = {
        "id": "S1",
        "frame": "model",
        "machine": "mill",
        "ops": [{"op": 10, "do": "inspect", "feature": "hole"}],
    }
    plan = {"setups": [setup]}
    fact = synthetic_fact(0.001)
    if grid_status == "bare":
        fact = fact["value"]
    elif grid_status is None:
        del fact["measured"]["status"]
    else:
        fact["measured"]["status"] = grid_status
    inventory = {"machines": {"mill": {"kind": "mill", "resolution_mm": fact}}}
    entries = VALIDATOR["Entries"](inventory)
    # An inspected profile is not a located/hole feature, but its explicit partial at
    # still prints a target row and leaves the setup unknown (coordinates.evaluate).
    native = (
        "unknown" if binding == "unknown" or z == "unknown" or grid_status != "measured" else "pass"
    )
    finding = {
        "status": native,
        "cite": [],
        "numbers": {
            "dro_grid": {"step": 0.001, "decimals": 3},
            **(
                {"dro_grid_debt": "synthetic declared grid is not measured"}
                if grid_status != "measured"
                else {}
            ),
            "rows": [
                {
                    "feature": "hole",
                    "model": [1.0, 2.0, z],
                    "setup": [1.0, 2.0, z],
                    **({"dro": [1.0, 2.0, z]} if z != "unknown" else {}),
                    "dro_xy": [1.0, 2.0],
                }
            ],
        },
    }
    VALIDATOR["check_coordinates"](setup, features, finding, plan, entries, inventory, None)
    for forged in {"pass", "unknown", "error"} - {native}:
        with pytest.raises(ValueError):
            VALIDATOR["check_coordinates"](
                setup, features, {**finding, "status": forged}, plan, entries, inventory, None
            )


@pytest.mark.parametrize("omitted", ["drawing station 1", "drawing station 2", "op 10 to_z"])
@pytest.mark.parametrize(
    ("radius_mode", "x_target"), [(False, 4.0), (True, 2.0), (None, "unknown")]
)
def test_coordinate_oracle_requires_every_authored_lathe_station(omitted, radius_mode, x_target):
    frame = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "binding": "nominal",
    }
    setup = {
        "id": "S1",
        "frame": "model",
        "machine": "lathe",
        "ops": [{"op": 10, "do": "turn", "feature": "shaft", "to_z": 8.0}],
    }
    features = {
        "units": "mm",
        "frames": {"model": frame},
        "features": {"shaft": {"kind": "shaft", "dia_nominal": 4.0, "z_mm": [0.0, 10.0]}},
    }
    plan = {"setups": [setup], "dro": {} if radius_mode is None else {"radius_mode": radius_mode}}
    inventory = {"machines": {"lathe": {"kind": "lathe", "resolution_mm": synthetic_fact(0.001)}}}
    entries = VALIDATOR["Entries"](inventory)
    finding = {
        "status": "unknown" if radius_mode is None else "pass",
        "cite": [],
        "numbers": {
            "dro_grid": {"step": 0.001, "decimals": 3},
            "rows": [
                {
                    "feature": "shaft",
                    "point": point,
                    "model": [0.0, 0.0, z],
                    "setup": [0.0, 0.0, z],
                    "dia_nominal": 4.0,
                    "x_target_mm": x_target,
                }
                for point, z in [
                    ("drawing station 1", 0.0),
                    ("drawing station 2", 10.0),
                    ("op 10 to_z", 8.0),
                ]
            ],
        },
    }

    def check():
        VALIDATOR["check_coordinates"](setup, features, finding, plan, entries, inventory, None)

    check()
    if radius_mode is None:
        # Omitting the mode cannot silently turn the displayed X into a diameter.
        row = finding["numbers"]["rows"][0]
        row["x_target_mm"] = 4.0
        with pytest.raises(ValueError, match="X target"):
            check()
        row["x_target_mm"] = "unknown"
    finding["numbers"]["rows"] = [
        row for row in finding["numbers"]["rows"] if row["point"] != omitted
    ]
    with pytest.raises(ValueError, match="station is missing"):
        check()


@pytest.mark.parametrize(
    ("measure", "nominal_delta", "native"),
    [
        ("fit-up reading", 0.0, "pass"),
        ("unknown", 0.0, "unknown"),
        ("fit-up reading", 1.0, "error"),
    ],
)
def test_stickout_oracle_merges_fit_up_debt(shaft_bundle, measure, nominal_delta, native):
    bundle = copy.deepcopy(shaft_bundle)
    plan, features, inventory, policy = (
        bundle.plan,
        bundle.features,
        bundle.inventory,
        bundle.policy,
    )

    def kernel():
        return bundle.kernel

    setup = next(item for item in plan["setups"] if item["id"] == "S2")
    finding = next(item.to_dict() for item in stickout.evaluate(bundle) if item.subject == "S2")
    assert finding["status"] == "pass"
    length = setup["hold"]["stickout_mm"]
    fit = {"measure": measure, "nominal_mm": length - 2.0 + nominal_delta, "add_mm": 2.0}
    setup["hold"]["stickout_fit"] = fit
    finding["numbers"]["stickout_fit"] = {**fit, "stickout_mm": length}
    finding["status"] = native
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)
    for forged in {"pass", "unknown", "error"} - {native}:
        with pytest.raises(ValueError):
            VALIDATOR["check_stickout"](
                setup, plan, features, inventory, policy, {**finding, "status": forged}, kernel
            )
    finding["numbers"]["stickout_fit"]["add_mm"] += 1.0
    with pytest.raises(ValueError, match="fit"):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)
