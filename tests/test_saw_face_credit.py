"""Host-only causal saw credit: native certificates, never ordinary face claims."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_mounted_saw_rules import finite_saw, normalized_assembly

from prechips import kernel
from prechips.rules import coverage, finish_coverage
from prechips.rules.geometry_common import finishing_subjects

NUMERIC_WITNESSES = (
    "plane_z_mm",
    "plane_error_mm",
    "area_mm2",
    "area_tolerance_mm2",
    "volume_tolerance_mm3",
    "boundary_uncovered_area_mm2",
    "preexisting_boundary_area_mm2",
    "outward_column_volume_mm3",
    "outward_missing_before_mm3",
    "outward_missing_removed_mm3",
    "inward_column_volume_mm3",
    "inward_missing_child_mm3",
)


def frame(origin=(0, 0, 0)):
    return {
        "origin": list(origin),
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
        "binding": "synthetic saw registration",
        "cite": "synthetic saw proof-boundary fixture",
    }


@pytest.fixture
def certified_saw(monkeypatch):
    feature = {"faces": ["#7"], "requirements": ["finish_ra"], "finish_ra": 3.2}
    op = {
        "op": 20,
        "do": "cut_off",
        "feature": "end",
        "workpiece_faces": {"lower": ["#7"], "upper": ["#7"]},
        "cut_plane": {"axis": "z", "value": 5.0, "keep": "below"},
        "outputs": {
            "lower_blank": {
                "side": "below",
                "carries_workpieces": ["lower"],
                "pose": frame(),
                "cite": "synthetic lower child",
            },
            "upper_blank": {
                "side": "above",
                "carries_workpieces": ["upper"],
                "pose": frame(),
                "cite": "synthetic upper child",
            },
        },
    }
    setup = {"id": "C2", "stock_in": "stock", "ops": [op]}
    bundle = SimpleNamespace(
        plan={
            "part": "synthetic-saw",
            "stock": {"as_is_faces": []},
            "workpieces": {"lower": {"pose": frame()}, "upper": {"pose": frame((0, 0, 8))}},
            "setups": [setup],
        },
        features={"units": "mm", "features": {"end": feature}},
        feature_definitions={"end": feature},
        inventory={},
    )
    request = {
        "subject": "C2:20",
        "do": op["do"],
        "saw_tool": "slitting_saw",
        "kerf_mm": 3.175,
        "cut_plane": deepcopy(op["cut_plane"]),
        "mounted_saw": normalized_assembly(),
        "workpiece_faces": deepcopy(op["workpiece_faces"]),
        "outputs": deepcopy(kernel._retained_output_inputs(op["outputs"], "mm")),
    }
    saw = finite_saw()
    registrations = kernel.workpiece_inputs(bundle.plan["workpieces"], "mm")
    protections, outputs, faces, rows = {}, {}, [], []
    for member, index, side, position in (("lower", 41, "below", 0), ("upper", 73, "above", 1)):
        name = member + "_blank"
        path = [{"split": "C2", "output": name}]
        protections[member] = {
            "workpiece_id": member,
            "status": "pass",
            "reasons": [],
            "registration": deepcopy(registrations[member]),
            "partition_path": [],
        }
        outputs[name] = {
            "status": "pass",
            "side": side,
            "carries_workpieces": [member],
            "whole_targets": [member],
            "partition": "C2:20",
            "partition_path": path,
            "volume_mm3": saw["outputs"][position]["volume_mm3"],
            "bbox_mm": deepcopy(saw["outputs"][position]["bbox_mm"]),
            "stock_volume_before_mm3": saw["stock_volume_before_mm3"],
            "removed_kerf_volume_mm3": saw["removed_kerf_volume_mm3"],
            "children_volume_mm3": [child["volume_mm3"] for child in saw["outputs"]],
            "conservation_error_mm3": 0.0,
        }
        area = 40.0
        band = saw["cutting_band_mm"]
        width = band[1] - band[0]
        rows.append(
            {
                "status": "pass",
                "reasons": [],
                "workpiece_id": member,
                "canonical_ref": "#7",
                "index": index,
                "output": name,
                "side": side,
                "registration": deepcopy(registrations[member]),
                "output_registration": deepcopy(request["outputs"][name]["pose"]),
                "input_partition_path": [],
                "partition_path": deepcopy(path),
                "output_proof": deepcopy(outputs[name]),
                "surface": "plane",
                "normal": [0.0, 0.0, 1.0 if side == "below" else -1.0],
                "plane_z_mm": band[position],
                "cutting_band_mm": deepcopy(band),
                "plane_error_mm": 0.0,
                "area_mm2": area,
                "area_tolerance_mm2": max(1e-6, area * 1e-6),
                "volume_tolerance_mm3": max(1e-6, area * width * 1e-6),
                "boundary_uncovered_area_mm2": 0.0,
                "preexisting_boundary_area_mm2": 0.0,
                "outward_column_volume_mm3": area * width,
                "outward_missing_before_mm3": 0.0,
                "outward_missing_removed_mm3": 0.0,
                "inward_column_volume_mm3": area * min(width, 1e-3),
                "inward_missing_child_mm3": 0.0,
            }
        )
        faces.append({"index": index, "ref": "#7", "canonical_ref": "#7", "workpiece_id": member})
    proof = {
        "model": "finite_saw_face_credit_v1",
        "producer": "C2:20",
        "request": deepcopy(request),
        "faces": rows,
    }
    detail = {"saw": saw, "saw_face_credit": proof, "claimed_indices": [41, 73], "claim_errors": []}
    facts = {
        "status": "ok",
        "faces": faces,
        "mapping": {"#7": 7},
        "workpiece_mapping": {"lower": {"#7": 41}, "upper": {"#7": 73}},
        "workpiece_features": {"lower": {"end": [41]}, "upper": {"end": [73]}},
        "setups": {"C2": {"workpieces": protections, "outputs": outputs}},
        "ops": {"C2:20": detail},
    }
    bundle.kernel = facts
    monkeypatch.setattr(kernel, "op_inputs", lambda *args, **kwargs: deepcopy(request))
    monkeypatch.setattr(kernel, "run_geometry", lambda bundle: facts)
    monkeypatch.setattr(coverage, "provenance", lambda *args, **kwargs: [])
    monkeypatch.setattr(finish_coverage, "provenance", lambda *args, **kwargs: [])
    monkeypatch.setattr(coverage.blank_credit, "credit", lambda *args, **kwargs: {})
    return SimpleNamespace(
        bundle=bundle,
        setup=setup,
        op=op,
        facts=facts,
        request=request,
        proof=proof,
        rows=rows,
        saw=saw,
        detail=detail,
        protections=protections,
        outputs=outputs,
    )


def credit(case):
    return coverage.saw_face_credit(case.bundle, case.facts, case.setup, case.op)


def finding(case):
    return coverage.evaluate(case.bundle)[-1]


def assert_lower_withheld(case):
    indices, evidence = credit(case)
    assert indices == {73}
    assert evidence["status"] == "unknown"
    assert evidence["faces"][0]["status"] == "unknown"
    assert evidence["faces"][0]["reasons"]
    result = finding(case)
    assert result.status == "error"
    assert result.numbers["unclaimed_indices"] == [41]
    assert result.numbers["claimed_face_count"] == 1


def test_both_new_boundaries_credit_only_their_member_global_indices(certified_saw, monkeypatch):
    case = certified_saw
    # Saw coverage must not consult even apparently successful ordinary claims.
    monkeypatch.setattr(coverage, "op_claims", lambda *args: pytest.fail("ordinary saw claim used"))
    indices, evidence = credit(case)
    assert indices == {41, 73}
    assert evidence["status"] == "pass"
    assert evidence["proof"] is case.proof
    assert [row["status"] for row in evidence["faces"]] == ["pass", "pass"]
    result = finding(case)
    assert result.status == "pass"
    assert result.numbers["claimed_face_count"] == 2
    assert result.numbers["unclaimed_indices"] == []
    assert result.numbers["saw_face_credit"][0]["indices"] == [41, 73]
    assert result.numbers["saw_face_credit"][0]["faces"][0]["proof"] is case.rows[0]


def test_registered_cut_off_accepts_certified_creation(certified_saw):
    assert credit(certified_saw)[0] == {41, 73}


def test_saw_cut_cannot_borrow_certificate_from_named_cut_off_outputs(certified_saw):
    case = certified_saw
    case.op["do"] = case.request["do"] = case.proof["request"]["do"] = "saw_cut"
    assert credit(case) == (set(), {})
    assert finding(case).status == "error"
    assert finding(case).numbers["claimed_face_count"] == 0


def test_saw_creation_is_not_surface_finish_credit(certified_saw):
    case = certified_saw
    assert finding(case).status == "pass"
    assert finishing_subjects(case.bundle) == set()
    [result] = finish_coverage.evaluate(case.bundle)
    assert result.status == "error"
    assert result.numbers["uncovered_faces"] == [41, 73]


def test_joint_preparation_cannot_bypass_saw_certificate_requirement(certified_saw, monkeypatch):
    case = certified_saw
    case.bundle.feature_definitions["end"]["joint"] = {"id": "join", "label": "joint:end"}
    case.detail.pop("saw_face_credit")
    monkeypatch.setattr(coverage, "op_claims", lambda *args: ({41, 73}, [], []))
    assert finding(case).numbers["claimed_face_count"] == 0


def test_rotated_normalized_registrations_and_nested_paths_are_exact_identities(certified_saw):
    case = certified_saw
    case.bundle.features["units"] = "in"
    rotated = {
        **frame((1, 2, 3)),
        "x": [0, 0, -1],
        "y": [0, 1, 0],
        "z": [1, 0, 0],
    }
    case.bundle.plan["workpieces"]["lower"]["pose"] = deepcopy(rotated)
    case.op["outputs"]["lower_blank"]["pose"] = deepcopy(rotated)
    case.request["outputs"] = kernel._retained_output_inputs(case.op["outputs"], "in")
    case.proof["request"] = deepcopy(case.request)
    prior = {
        "id": "C1",
        "stock_in": "stock",
        "ops": [
            {
                "op": 10,
                "do": "cut_off",
                "outputs": {
                    "parent": {
                        "side": "below",
                        "carries_workpieces": ["lower", "upper"],
                        "pose": frame(),
                    },
                },
            }
        ],
    }
    case.bundle.plan["setups"].insert(0, prior)
    case.setup["stock_in"] = "stock_out.parent"
    path = [{"split": "C1", "output": "parent"}]
    registrations = kernel.workpiece_inputs(case.bundle.plan["workpieces"], "in")
    for row in case.rows:
        member, name = row["workpiece_id"], row["output"]
        row["registration"] = deepcopy(registrations[member])
        row["input_partition_path"] = deepcopy(path)
        row["partition_path"] = path + [{"split": "C2", "output": name}]
        row["output_registration"] = deepcopy(case.request["outputs"][name]["pose"])
        case.protections[member].update(
            registration=deepcopy(registrations[member]),
            partition_path=deepcopy(path),
        )
        case.outputs[name]["partition_path"] = deepcopy(row["partition_path"])
        row["output_proof"] = deepcopy(case.outputs[name])
    assert case.rows[0]["registration"]["pose"]["origin"] == pytest.approx([25.4, 50.8, 76.2])
    assert case.rows[0]["output_registration"]["x"] == [0, 0, -1]
    assert credit(case)[0] == {41, 73}
    case.rows[0]["input_partition_path"][0]["split"] = "C1:10"
    assert_lower_withheld(case)


@pytest.mark.parametrize("kind", ["bandsaw", "hand_saw", "unknown"])
def test_non_slitting_saws_cannot_borrow_a_finite_certificate(certified_saw, kind):
    case = certified_saw
    case.request["saw_tool"] = case.proof["request"]["saw_tool"] = kind
    assert credit(case) == (set(), {})
    result = finding(case)
    assert result.status == "error"
    assert result.numbers["claimed_face_count"] == 0


@pytest.mark.parametrize("explicit", [False, True])
def test_missing_certificate_never_falls_back_to_bare_claims(certified_saw, explicit):
    case = certified_saw
    case.detail.pop("saw_face_credit")
    if not explicit:
        case.op["faces"] = case.op.pop("workpiece_faces")["lower"]
    result = finding(case)
    assert result.status == "error"
    assert result.numbers["claimed_face_count"] == 0
    assert result.numbers["unclaimed_indices"] == [41, 73]
    if explicit:
        assert "face-creation proof refused for lower:#7" in result.sentence
        assert (
            "current finite slitting-saw request and native geometry are not bound"
            in result.sentence
        )
        assert "faces have no cutting op or as-stock claim" not in result.sentence
    else:
        assert "faces have no cutting op or as-stock claim" in result.sentence
        assert "face-creation proof refused" not in result.sentence


def test_unregistered_plan_is_ineligible_even_with_explicit_native_rows(certified_saw):
    case = certified_saw
    case.bundle.plan.pop("workpieces")
    assert credit(case) == (set(), {})


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "finite_disk_v1"),
        ("producer", "C1:20"),
        ("reasons", ["certificate inventory unresolved"]),
        ("faces", []),
        ("faces", "unknown"),
        ("faces", [None]),
    ],
)
def test_stale_or_malformed_certificate_never_credits(certified_saw, field, value):
    case = certified_saw
    case.proof[field] = value
    assert credit(case)[0] == set()
    assert finding(case).status == "error"


@pytest.mark.parametrize(
    "field",
    [
        "subject",
        "do",
        "saw_tool",
        "kerf_mm",
        "cut_plane",
        "mounted_saw",
        "workpiece_faces",
        "outputs",
    ],
)
def test_certificate_binds_every_current_normalized_request_field(certified_saw, field):
    case = certified_saw
    case.proof["request"].pop(field)
    assert credit(case)[0] == set()
    assert finding(case).numbers["claimed_face_count"] == 0


def test_changed_current_mounted_assembly_refuses_old_geometry_certificate(certified_saw):
    case = certified_saw
    case.request["mounted_saw"]["blade"]["dia_mm"] += 1
    assert credit(case)[0] == set()


def test_numeric_request_binding_rejects_equal_boolean_substitution(certified_saw):
    case = certified_saw
    case.proof["request"]["outputs"]["lower_blank"]["pose"]["x"][0] = True
    assert credit(case)[0] == set()


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("status", "error"),
        ("cutting_band_mm", [3.4125, 6.5]),
        ("required_kerf_volume_mm3", None),
        ("stock_volume_before_mm3", float("nan")),
        ("removed_kerf_volume_mm3", True),
        ("uncovered_kerf_volume_mm3", 0.01),
        ("unintended_removal_volume_mm3", 0.01),
        ("collisions", ["blade meets clamp"]),
        ("outputs", []),
    ],
)
def test_incomplete_or_failed_native_finite_geometry_refuses_certificate(
    certified_saw, field, value
):
    case = certified_saw
    case.saw[field] = value
    assert credit(case)[0] == set()
    assert finding(case).numbers["claimed_face_count"] == 0


def test_model_and_pass_markers_are_not_finite_geometry(certified_saw):
    case = certified_saw
    case.detail["saw"] = {"model": "finite_disk_v1", "status": "pass"}
    assert credit(case)[0] == set()


@pytest.mark.parametrize(
    "field,value",
    [
        ("index", 7),
        ("index", True),
        ("index", -1),
        ("workpiece_id", "upper"),
        ("workpiece_id", "foreign"),
        ("canonical_ref", "#8"),
    ],
)
def test_foreign_or_stale_row_inventory_refuses_entire_certificate(certified_saw, field, value):
    case = certified_saw
    case.rows[0][field] = value
    assert credit(case)[0] == set()


def test_duplicate_certificate_index_refuses_entire_certificate(certified_saw):
    case = certified_saw
    case.rows.append(deepcopy(case.rows[0]))
    assert credit(case)[0] == set()


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("reasons", ["native full-footprint witness unresolved"]),
        ("registration", {}),
        ("input_partition_path", [{"split": "C0", "output": "old"}]),
        ("partition_path", [{"split": "C2:20", "output": "lower_blank"}]),
        ("output", "upper_blank"),
        ("side", "above"),
        ("output_registration", {}),
        ("output_proof", {}),
    ],
)
def test_each_row_requires_current_member_route_and_named_output(certified_saw, field, value):
    case = certified_saw
    case.rows[0][field] = value
    assert_lower_withheld(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("index", 42),
        ("workpiece_id", "upper"),
        ("canonical_ref", "#8"),
    ],
)
def test_certificate_cannot_borrow_an_unmatched_native_inventory_face(certified_saw, field, value):
    case = certified_saw
    case.facts["faces"][0][field] = value
    assert credit(case)[0] == {73}


def test_duplicate_native_inventory_index_is_not_a_unique_target(certified_saw):
    case = certified_saw
    case.facts["faces"].append(deepcopy(case.facts["faces"][0]))
    assert credit(case)[0] == {73}


@pytest.mark.parametrize("value", [True, -1, 73, "unknown"])
def test_global_member_mapping_must_be_numeric_and_unambiguous(certified_saw, value):
    case = certified_saw
    case.facts["workpiece_mapping"]["lower"]["#7"] = value
    assert credit(case)[0] == set()


@pytest.mark.parametrize(
    "field,value",
    [
        ("registration", {}),
        ("partition_path", [{"split": "C1", "output": "other"}]),
        ("status", "unknown"),
    ],
)
def test_declared_live_membership_cannot_replace_current_native_protection(
    certified_saw, field, value
):
    case = certified_saw
    case.protections["lower"][field] = value
    assert credit(case)[0] == set()


def test_containment_failure_remains_error_even_with_passing_face_certificate(certified_saw):
    case = certified_saw
    case.protections["lower"].update(status="error", reasons=["target absent from entering stock"])
    results = coverage.evaluate(case.bundle)
    assert results[0].status == "error"
    assert results[0].subject == "C2:lower"
    assert results[-1].numbers["claimed_face_count"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("side", "above"),
        ("partition", "C1:20"),
        ("partition_path", [{"split": "C2", "output": "upper_blank"}]),
        ("carries_workpieces", ["upper"]),
        ("whole_targets", []),
        ("volume_mm3", 0),
        ("volume_mm3", True),
        ("volume_mm3", float("nan")),
        ("volume_mm3", 9999),
        ("stock_volume_before_mm3", 21000),
        ("removed_kerf_volume_mm3", 0),
        ("children_volume_mm3", [10000]),
        ("children_volume_mm3", [10000, float("inf")]),
        ("conservation_error_mm3", 1e-5),
        ("conservation_error_mm3", -1e-6),
        ("conservation_error_mm3", True),
        ("bbox_mm", [0, 0, 0, -1, 1, 1]),
        ("bbox_mm", [False, 0, 0, 1, 1, 1]),
    ],
)
def test_even_identical_output_proof_requires_a_complete_accepted_conservation_ledger(
    certified_saw,
    field,
    value,
):
    case = certified_saw
    case.outputs["lower_blank"][field] = value
    case.rows[0]["output_proof"] = deepcopy(case.outputs["lower_blank"])
    assert_lower_withheld(case)


def test_row_cannot_replay_output_proof_after_actual_output_changes(certified_saw):
    case = certified_saw
    case.outputs["lower_blank"]["bbox_mm"][0] += 0.1
    assert_lower_withheld(case)


def test_native_six_decimal_conservation_rounding_is_accepted(certified_saw):
    case = certified_saw
    output = case.outputs["lower_blank"]
    output["children_volume_mm3"][0] += 1e-6
    output["conservation_error_mm3"] = 1e-6
    case.rows[0]["output_proof"] = deepcopy(output)
    assert credit(case)[0] == {41, 73}


@pytest.mark.parametrize("field", NUMERIC_WITNESSES)
@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), "unknown"])
def test_all_native_face_measurements_must_be_finite_numbers_not_booleans(
    certified_saw,
    field,
    value,
):
    case = certified_saw
    case.rows[0][field] = value
    assert_lower_withheld(case)


@pytest.mark.parametrize("field", NUMERIC_WITNESSES)
def test_partial_native_face_witnesses_withhold_only_the_uncertified_face(certified_saw, field):
    case = certified_saw
    case.rows[0].pop(field)
    assert_lower_withheld(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("surface", "cylinder"),
        ("normal", [0, 0, -1]),
        ("normal", [0, 0, True]),
        ("normal", [0, float("nan"), 1]),
        ("normal", [0, 1]),
        ("cutting_band_mm", [3.4125, 6.5]),
        ("cutting_band_mm", [3.4125, float("nan")]),
        ("plane_z_mm", 6.5875),
        ("plane_error_mm", 1.1e-6),
        ("plane_error_mm", -1e-6),
        ("area_mm2", 0),
        ("area_mm2", -40),
        ("area_tolerance_mm2", 1),
        ("volume_tolerance_mm3", 1),
        ("boundary_uncovered_area_mm2", 0.01),
        ("boundary_uncovered_area_mm2", -0.01),
        ("preexisting_boundary_area_mm2", 40),
        ("outward_column_volume_mm3", 0),
        ("outward_column_volume_mm3", 126),
        ("outward_missing_before_mm3", 0.01),
        ("outward_missing_before_mm3", -0.01),
        ("outward_missing_removed_mm3", 0.01),
        ("inward_column_volume_mm3", 0),
        ("inward_column_volume_mm3", 0.08),
        ("inward_missing_child_mm3", 0.01),
    ],
)
def test_preexisting_partial_wrong_side_or_unproved_material_columns_never_credit(
    certified_saw,
    field,
    value,
):
    case = certified_saw
    case.rows[0][field] = value
    assert_lower_withheld(case)


def test_witness_bounds_are_inclusive_without_relaxing_new_face_requirement(certified_saw):
    case = certified_saw
    row = case.rows[0]
    for key in ("boundary_uncovered_area_mm2", "preexisting_boundary_area_mm2"):
        row[key] = row["area_tolerance_mm2"]
    for key in (
        "outward_missing_before_mm3",
        "outward_missing_removed_mm3",
        "inward_missing_child_mm3",
    ):
        row[key] = row["volume_tolerance_mm3"]
    row["plane_error_mm"] = 1e-6
    assert credit(case)[0] == {41, 73}


def test_omitted_or_unknown_rows_do_not_turn_partial_face_coverage_into_a_pass(certified_saw):
    case = certified_saw
    case.proof["faces"] = case.rows[1:]
    indices, evidence = credit(case)
    assert indices == {73}
    assert evidence["status"] == "unknown"
    assert finding(case).status == "error"
    assert finding(case).numbers["unclaimed_indices"] == [41]


def test_ordinary_saw_claims_cannot_smuggle_an_additional_unlisted_face(certified_saw):
    case = certified_saw
    case.facts["faces"].append(
        {"index": 91, "ref": "#8", "canonical_ref": "#8", "workpiece_id": "lower"}
    )
    case.facts["workpiece_mapping"]["lower"]["#8"] = 91
    case.detail["claimed_indices"].append(91)
    result = finding(case)
    assert result.status == "error"
    assert result.numbers["claimed_face_count"] == 2
    assert result.numbers["unclaimed_indices"] == [91]


def test_face_row_cannot_borrow_a_member_omitted_from_explicit_operation_claims(certified_saw):
    case = certified_saw
    for claims in (
        case.op["workpiece_faces"],
        case.request["workpiece_faces"],
        case.proof["request"]["workpiece_faces"],
    ):
        claims.pop("lower")
    assert credit(case)[0] == set()


def test_explicit_unknown_native_row_preserves_other_certified_face_credit(certified_saw):
    case = certified_saw
    case.rows[0].update(status="unknown", reasons=["full target footprint is preexisting"])
    for field in NUMERIC_WITNESSES:
        case.rows[0].pop(field)
    assert_lower_withheld(case)
    result = finding(case)
    assert "face-creation proof refused for lower:#7" in result.sentence
    assert "full target footprint is preexisting" in result.sentence
    assert "faces have no cutting op or as-stock claim" not in result.sentence


def test_global_native_certificate_refusal_explains_the_uncovered_faces(certified_saw):
    case = certified_saw
    case.proof["reasons"] = ["accepted registered finite-saw partition evidence is incomplete"]
    result = finding(case)
    assert result.status == "error"
    assert result.numbers["unclaimed_indices"] == [41, 73]
    assert "face-creation proof refused for lower:#7" in result.sentence
    assert "face-creation proof refused for upper:#7" in result.sentence
    assert "accepted registered finite-saw partition evidence is incomplete" in result.sentence
    assert "faces have no cutting op or as-stock claim" not in result.sentence


def test_current_registration_change_refuses_replayed_member_and_face_proofs(certified_saw):
    case = certified_saw
    case.bundle.plan["workpieces"]["lower"]["pose"]["origin"][0] += 1
    assert credit(case)[0] == set()


def test_equal_boolean_in_both_native_registration_proofs_is_not_current_pose(certified_saw):
    case = certified_saw
    case.protections["lower"]["registration"]["pose"]["x"][0] = True
    case.rows[0]["registration"]["pose"]["x"][0] = True
    assert credit(case)[0] == set()


def test_actual_named_output_must_exist_not_just_the_certificate_copy(certified_saw):
    case = certified_saw
    case.outputs.pop("lower_blank")
    assert_lower_withheld(case)


def test_member_cannot_have_two_declared_output_carriers(certified_saw):
    case = certified_saw
    assert credit(case)[0] == {41, 73}
    for outputs in (
        case.op["outputs"],
        case.request["outputs"],
        case.proof["request"]["outputs"],
    ):
        outputs["upper_blank"]["carries_workpieces"].append("lower")
    # The duplicated lower carrier is refused. The upper face also loses credit:
    # its changed declared membership no longer matches the accepted native output.
    indices, evidence = credit(case)
    assert indices == set()
    assert [row["status"] for row in evidence["faces"]] == ["unknown", "unknown"]


def test_sub_micron_kerf_uses_bandwidth_for_both_material_columns(certified_saw):
    case = certified_saw
    band = [4.99975, 5.00025]
    width = band[1] - band[0]
    case.request["kerf_mm"] = width
    case.proof["request"] = deepcopy(case.request)
    case.saw["cutting_band_mm"] = band
    case.saw["body_band_mm"] = list(band)
    for position, row in enumerate(case.rows):
        row["cutting_band_mm"] = list(band)
        row["plane_z_mm"] = band[position]
        row["volume_tolerance_mm3"] = max(1e-6, row["area_mm2"] * width * 1e-6)
        row["outward_column_volume_mm3"] = row["area_mm2"] * width
        row["inward_column_volume_mm3"] = row["area_mm2"] * width
    assert credit(case)[0] == {41, 73}
    case.rows[0]["inward_column_volume_mm3"] = case.rows[0]["area_mm2"] * 1e-3
    assert_lower_withheld(case)
