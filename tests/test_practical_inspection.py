"""Shared dimensional plans and separately owned manual final checkpoints.

Synthetic native rows exercise host binding/refusal, not CAD survival. The native
owner's single real fixture supplies the independent native-to-host bridge.
"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_batch_material_routes import batch
from test_geometry_rules import rules_bundle

from prechips.inputs import Bundle
from prechips.rules import inspection, internal_corner_radius
from prechips.rules.resolution import (
    inspection_preservation_evidence,
    op_check_targets,
    operation_members,
    thread_class_acceptance,
)

MEMBERS = ("nut1", "nut2", "nut3", "nut4")
DIMENSIONS = (
    ("base", "width"),
    ("base", "height"),
    ("shoulders", "thickness"),
    ("shoulders", "width"),
)
NOMINALS = {
    ("base", "width"): 22.225,
    ("base", "height"): 12.7,
    ("shoulders", "thickness"): 6.35,
    ("shoulders", "width"): 12.573,
}
PATHS = {
    "nut1": [{"split": "C1a", "output": "nut1_b"}],
    "nut2": [
        {"split": "C1a", "output": "lower1"},
        {"split": "C1b", "output": "nut2_b"},
    ],
    "nut3": [
        {"split": "C1a", "output": "lower1"},
        {"split": "C1b", "output": "lower2"},
        {"split": "C2", "output": "nut3_b"},
    ],
    "nut4": [
        {"split": "C1a", "output": "lower1"},
        {"split": "C1b", "output": "lower2"},
        {"split": "C2", "output": "nut4_b"},
    ],
}
CUTS = {
    "nut1": ["S1:20", "C1a:10"],
    "nut2": ["S1:20", "C1a:10", "C1b:10"],
    "nut3": ["S1:20", "C1a:10", "C1b:10", "C2:10"],
    "nut4": ["S1:20", "C1a:10", "C1b:10", "C2:10"],
}


def practical_bundle():
    plan = batch()
    plan["setups"][0].update(
        id="S1",
        ops=[
            {"op": 20, "do": "finish_profile", "feature": "shoulders"},
            {
                "op": 30,
                "do": "inspect",
                "feature": ["base", "shoulders"],
                "inspect_workpieces": list(MEMBERS),
                "inspection_scope": {"after": "S1:20", "before": "C1a:10"},
                "checks": {"width": "calipers", "height": "calipers", "thickness": "calipers"},
                "inspection_methods": {
                    "width": "Read the future blank stations with calipers.",
                    "height": "Read the section with calipers.",
                    "thickness": "Read the shoulder thickness with calipers.",
                },
            },
        ],
    )
    plan["setups"][1]["stock_in"] = "S1"
    for setup in plan["setups"][-4:]:
        setup["ops"] = [
            {
                "op": 10,
                "do": "inspect",
                "feature": ["base", "shoulders", "end", "thread"],
                "checks": {
                    "length": "calipers",
                    "actual_slot_fit": "actual-slot",
                    "stud_retention": "stud",
                },
                "inspection_methods": {
                    "length": "Measure the finished length.",
                    "actual_slot_fit": "Compare the nut with the actual slot by hand.",
                    "stud_retention": "Try the intended stud by hand; verify bottom retention.",
                },
            }
        ]
    features = {
        "units": "mm",
        "features": {
            "base": {
                "kind": "profile",
                "faces": ["#1"],
                "requirements": ["width", "height"],
                "width": [22.1742, 22.2758],
                "height": [12.6492, 12.7508],
                "width_nominal": 22.225,
                "height_nominal": 12.7,
            },
            "shoulders": {
                "kind": "profile",
                "faces": ["#2"],
                "requirements": ["thickness", "width"],
                "thickness": [6.2992, 6.4008],
                "width": [12.5222, 12.6238],
                "thickness_nominal": 6.35,
                "width_nominal": 12.573,
            },
            "end": {
                "kind": "face",
                "faces": ["#3"],
                "requirements": ["length"],
                "length": [25.3492, 25.4508],
            },
            "thread": {
                "kind": "threaded_hole",
                "faces": ["#4"],
                "requirements": [],
                "thread": "3/8-16",
                "thread_hand": "right",
                "dia_nominal": 9.525,
            },
        },
        "acceptance": {
            "actual_slot_fit": {
                "features": ["base", "shoulders", "end"],
                "contract": {
                    "kind": "manual",
                    "gauge_kind": "mating_part",
                    "accept": [
                        "Slides freely without objectionable rocking.",
                        "Shoulders bear without bottoming or wedging; top stays below table.",
                    ],
                    "cite": "Synthetic practical slot acceptance",
                },
            },
            "stud_retention": {
                "features": ["thread"],
                "contract": {
                    "kind": "manual",
                    "gauge_kind": "mating_hardware",
                    "accept": [
                        "Stud enters by hand.",
                        "Bottom deformation prevents exit or table contact; "
                        "nut does not turn or pass through slot.",
                    ],
                    "cite": "Synthetic practical stud acceptance",
                },
            },
        },
    }
    return Bundle(
        plan=plan,
        features=features,
        inventory={
            "gauges": {
                "calipers": {"kind": "caliper", "range_mm": [0.0, 150.0], "resolution_mm": 0.01},
                "actual-slot": {"kind": "mating_part", "present": True},
                "stud": {
                    "kind": "mating_hardware",
                    "thread": "3/8-16 UNC",
                    "thread_hand": "right",
                    "present": True,
                },
            }
        },
        policy={},
        cutting_data={},
        hashes={},
        paths={},
        root=Path("."),
        kernel={"status": "ok", "setups": {}},
    )


def shared_op(bundle):
    return bundle.plan["setups"][0]["ops"][1]


def final_op(bundle, member="nut1"):
    return next(setup for setup in bundle.plan["setups"] if setup["id"] == f"E{member[-1]}")["ops"][
        0
    ]


def install_preservation(bundle):
    """Fixed synthetic contract, intentionally not derived from MaterialGraph."""
    for index, member in enumerate(MEMBERS, 1):
        pose = bundle.plan["workpieces"][member]["pose"]
        rows = []
        for feature, requirement in DIMENSIONS:
            rows.append(
                {
                    "model": "requirement_preservation_v1",
                    "check_id": "S1:30",
                    "feature": feature,
                    "requirement": requirement,
                    "workpiece_id": member,
                    "after": "S1:20",
                    "before": "C1a:10",
                    "producer": "S1:20",
                    "receiver": f"E{index}",
                    "registration": {
                        "pose": {key: deepcopy(pose[key]) for key in ("origin", "x", "y", "z")}
                    },
                    "partition_path": deepcopy(PATHS[member]),
                    "status": "pass",
                    "reasons": [],
                    "region": {
                        "model": "planar_support_v1",
                        "indices": [0, 1],
                        "axis": [0.0, 1.0, 0.0],
                        "planes_mm": [0.0, NOMINALS[feature, requirement]],
                        "nominal_mm": NOMINALS[feature, requirement],
                    },
                    "operations": list(CUTS[member]),
                }
            )
        bundle.kernel["setups"][f"E{index}"] = {"inspection_preservation": rows}


def shared_rows(bundle):
    return [row for row in inspection.evaluate(bundle) if row.numbers.get("shared_check_id")]


def test_selector_preserves_scoped_precedence_and_geometry_member_semantics():
    bundle = practical_bundle()
    setup = bundle.plan["setups"][0]
    op = shared_op(bundle)
    op["checks"]["base"] = {"width": "base-calipers"}
    targets = op_check_targets(bundle, setup, op)
    assert operation_members(bundle, setup, op) is None
    assert len(targets) == 4
    by_identity = {
        (row["identity"]["feature_owner"], row["identity"]["requirement"]): row for row in targets
    }
    assert by_identity["base", "width"]["gauge"] == "base-calipers"
    assert by_identity["shoulders", "width"]["gauge"] == "calipers"
    assert all(row["identity"]["workpiece"] is None for row in targets)
    assert all(row["covered_workpieces"] == list(MEMBERS) for row in targets)
    assert by_identity["base", "width"]["subject"] == "S1:30/base:width"


def test_shared_four_requirements_and_four_separate_final_checkpoints():
    bundle = practical_bundle()
    install_preservation(bundle)
    rows = inspection.evaluate(bundle)
    shared = [row for row in rows if row.numbers.get("shared_check_id")]
    assert len(shared) == 4
    assert {row.subject for row in shared} == {f"S1:30/{name}:{req}" for name, req in DIMENSIONS}
    assert all(row.status == "pass" for row in shared)
    assert all(row.numbers["covered_workpieces"] == list(MEMBERS) for row in shared)
    assert all(len(row.numbers["preservation"]) == 4 for row in shared)
    final = [
        row
        for row in rows
        if row.numbers.get("requirement") in {"length", "actual_slot_fit", "stud_retention"}
    ]
    assert len(final) == 12
    assert {row.subject for row in final} == {
        f"{member}/{owner}:{req}"
        for member in MEMBERS
        for owner, req in (
            ("end", "length"),
            ("part", "actual_slot_fit"),
            ("part", "stud_retention"),
        )
    }
    assert all(row.status == "pass" for row in final)
    assert all(
        row.numbers["evaluation"] == "inspection_plan"
        and row.numbers["part_result"] == "not_recorded"
        for row in [*shared, *final]
    )
    assert {row.numbers["op"] for row in final} == {"E1:10", "E2:10", "E3:10", "E4:10"}
    assert all(not row.numbers.get("covered_workpieces") for row in final)


def test_target_containment_alone_does_not_preserve_early_dimensions():
    bundle = practical_bundle()
    for index, member in enumerate(MEMBERS, 1):
        bundle.kernel["setups"][f"E{index}"] = {"workpieces": {member: {"status": "pass"}}}
    assert {row.status for row in shared_rows(bundle)} == {"unknown"}


@pytest.mark.parametrize(
    "mutation",
    [
        "member",
        "registration",
        "path",
        "producer",
        "receiver",
        "feature",
        "requirement",
        "check",
        "before",
        "model",
        "region",
        "nominal",
        "planes",
        "ledger",
        "duplicate",
    ],
)
def test_preservation_proof_requires_exact_identities_and_complete_region(mutation):
    bundle = practical_bundle()
    install_preservation(bundle)
    rows = bundle.kernel["setups"]["E1"]["inspection_preservation"]
    proof = rows[0]
    if mutation == "member":
        proof["workpiece_id"] = "nut2"
    elif mutation == "registration":
        proof["registration"]["pose"]["origin"][0] += 1.0
    elif mutation == "path":
        proof["partition_path"] = PATHS["nut2"]
    elif mutation == "producer":
        proof["producer"] = "S1:30"
    elif mutation == "receiver":
        proof["receiver"] = "E2"
    elif mutation == "feature":
        proof["feature"] = "shoulders"
    elif mutation == "requirement":
        proof["requirement"] = "height"
    elif mutation == "check":
        proof["check_id"] = "S1:20"
    elif mutation == "before":
        proof["before"] = "C1b:10"
    elif mutation == "model":
        proof["model"] = "contained_target"
    elif mutation == "region":
        proof["region"] = {"model": "planar_support_v1"}
    elif mutation == "nominal":
        proof["region"]["nominal_mm"] += 0.1
    elif mutation == "planes":
        proof["region"]["planes_mm"][1] += 0.1
    elif mutation == "ledger":
        proof["operations"] = ["S1:20"]
    else:
        rows.append(deepcopy(proof))
    row = next(row for row in shared_rows(bundle) if row.subject == "S1:30/base:width")
    assert row.status == "unknown"
    assert row.numbers["preservation"][0]["status"] == "unknown"


def test_later_cross_section_change_is_an_error_not_missing_proof():
    bundle = practical_bundle()
    install_preservation(bundle)
    proof = bundle.kernel["setups"]["E3"]["inspection_preservation"][0]
    proof.update(status="error", reasons=["later profile cut changes the supporting plane"])
    row = next(row for row in shared_rows(bundle) if row.subject == "S1:30/base:width")
    assert row.status == "error"
    assert row.numbers["preservation"][2]["reasons"] == [
        "later profile cut changes the supporting plane"
    ]


@pytest.mark.parametrize("action", ["fit", "deburr", "coating"])
def test_unmodeled_bench_step_cannot_borrow_early_dimensional_credit(action):
    bundle = practical_bundle()
    install_preservation(bundle)
    final = bundle.plan["setups"][-4]
    final["ops"].insert(0, {"op": 5, "do": action, "feature": "thread"})
    # Even a stale pass that merely lists the new subject is not bounded proof
    # of its material effect. A functional stud check is not a size measurement.
    for proof in bundle.kernel["setups"]["E1"]["inspection_preservation"]:
        proof["operations"].append("E1:5")
    evidence = inspection_preservation_evidence(
        bundle, final, shared_op(bundle), "base", "height", "nut1"
    )
    assert evidence["status"] == "unknown"
    assert evidence["reasons"] == ["material effects are unmodeled for E1:5"]
    row = next(row for row in shared_rows(bundle) if row.subject == "S1:30/base:height")
    assert row.status == "unknown"
    assert [proof["status"] for proof in row.numbers["preservation"]] == [
        "unknown",
        "pass",
        "pass",
        "pass",
    ]


def test_later_producer_does_not_erase_unmodeled_incoming_bench_effect():
    bundle = practical_bundle()
    install_preservation(bundle)
    check = shared_op(bundle)
    bundle.plan["setups"][0]["ops"].insert(0, {"op": 10, "do": "fit", "feature": "thread"})
    evidence = inspection_preservation_evidence(bundle, "E1", check, "base", "height", "nut1")
    assert evidence["status"] == "unknown"
    assert evidence["reasons"] == ["material effects are unmodeled for S1:10"]


@pytest.mark.parametrize("action", ["inspect", "release", "scribe"])
def test_nonmaterial_metadata_does_not_create_preservation_debt(action):
    bundle = practical_bundle()
    install_preservation(bundle)
    final = bundle.plan["setups"][-4]
    final["ops"].insert(0, {"op": 5, "do": action})
    assert (
        inspection_preservation_evidence(
            bundle, final, shared_op(bundle), "base", "height", "nut1"
        )["status"]
        == "pass"
    )


@pytest.mark.parametrize("mutation", ["extra", "repeated", "reordered"])
def test_native_operation_ledger_must_match_current_exact_order(mutation):
    bundle = practical_bundle()
    install_preservation(bundle)
    proof = bundle.kernel["setups"]["E1"]["inspection_preservation"][0]
    if mutation == "extra":
        proof["operations"].append("other-part:10")
    elif mutation == "repeated":
        proof["operations"].append("C1a:10")
    else:
        proof["operations"].reverse()
    assert (
        inspection_preservation_evidence(bundle, "E1", shared_op(bundle), "base", "width", "nut1")[
            "status"
        ]
        == "unknown"
    )


def final_multiowner_bundle():
    bundle = practical_bundle()
    bundle.plan["setups"][0]["ops"].pop()
    for member in MEMBERS:
        op = final_op(bundle, member)
        op["inspect_workpieces"] = [member]
        op["checks"] = {
            "base": {"width": "calipers", "height": "calipers"},
            "shoulders": {"width": "calipers", "thickness": "calipers"},
            "end": {"length": "calipers"},
            "actual_slot_fit": "actual-slot",
            "stud_retention": "stud",
        }
        op["inspection_methods"].update(
            base={"width": "Measure the base width.", "height": "Measure overall height."},
            shoulders={
                "width": "Measure the stem width.",
                "thickness": "Measure both flange thicknesses; each must meet the band.",
            },
            end={"length": "Measure the finished length."},
        )
        op["inspection_methods"].pop("length")
    return bundle


def test_four_final_checkpoints_keep_every_numeric_and_manual_owner_without_preservation():
    bundle = final_multiowner_bundle()
    numeric = [*DIMENSIONS, ("end", "length")]
    for index, member in enumerate(MEMBERS, 1):
        setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == f"E{index}")
        targets = op_check_targets(bundle, setup, final_op(bundle, member))
        assert len(targets) == 7
        assert {
            (target["identity"]["feature_owner"], target["identity"]["requirement"])
            for target in targets
        } == {*numeric, (None, "actual_slot_fit"), (None, "stud_retention")}
        assert all(target["identity"]["workpiece"] == member for target in targets)
        assert all(target["shared_check_id"] is None for target in targets)
        assert all(target["covered_workpieces"] == [] for target in targets)
    rows = [
        row
        for row in inspection.evaluate(bundle)
        if row.numbers.get("requirement")
        in {"width", "height", "thickness", "length", "actual_slot_fit", "stud_retention"}
    ]
    assert len(rows) == 28
    assert all(row.status == "pass" for row in rows)
    assert {row.subject for row in rows} == {
        f"{member}/{owner}:{requirement}"
        for member in MEMBERS
        for owner, requirement in [
            *numeric,
            ("part", "actual_slot_fit"),
            ("part", "stud_retention"),
        ]
    }
    assert {row.numbers["op"] for row in rows} == {"E1:10", "E2:10", "E3:10", "E4:10"}
    assert all(row.numbers["part_result"] == "not_recorded" for row in rows)
    assert all("preservation" not in row.numbers for row in rows)


def test_one_final_record_never_waives_missing_numeric_owner_or_borrows_a_sibling_check():
    bundle = final_multiowner_bundle()
    final_op(bundle, "nut2")["checks"]["base"].pop("height")
    rows = {
        row.subject: row
        for row in inspection.evaluate(bundle)
        if row.subject.endswith("/base:height")
    }
    assert set(rows) == {f"{member}/base:height" for member in MEMBERS}
    assert rows["nut2/base:height"].status == "error"
    assert all(
        rows[f"{member}/base:height"].status == "pass" for member in ("nut1", "nut3", "nut4")
    )


@pytest.mark.parametrize(
    "scope",
    ["unknown", {"after": "unknown", "before": "C1a:10"}, {"after": "S1:20", "before": "unknown"}],
)
def test_unknown_shared_scope_never_falls_back_to_final_check(scope):
    bundle = practical_bundle()
    install_preservation(bundle)
    shared_op(bundle)["inspection_scope"] = scope
    rows = shared_rows(bundle)
    assert len(rows) == 4 and all(row.status == "unknown" for row in rows)
    assert all(row.numbers["preservation"] == [] for row in rows)


def test_known_wrong_shared_timing_errors_even_with_unknown_native_proof():
    bundle = practical_bundle()
    shared_op(bundle)["inspection_scope"]["after"] = "C1a:10"
    assert {row.status for row in shared_rows(bundle)} == {"error"}


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("range_mm", [0.0, 25.4508], "pass"),
        ("range_mm", [0.0, 25.4507], "error"),
        ("resolution_mm", 25.4508 - 25.3492, "pass"),
        ("resolution_mm", 0.10161, "error"),
        ("resolution_mm", "unknown", "unknown"),
        ("verify", True, "unknown"),
    ],
)
def test_existing_caliper_range_resolution_and_trust_boundaries(field, value, status):
    bundle = practical_bundle()
    bundle.inventory["gauges"]["calipers"][field] = value
    setup = bundle.plan["setups"][-4]
    result, _, nums = inspection.requirement_check(
        bundle, "end", "length", setup["ops"][0], setup=setup, workpiece="nut1"
    )
    assert result == status
    assert nums["identity"] == {
        "workpiece": "nut1",
        "feature_owner": "end",
        "requirement": "length",
    }
    assert nums["evaluation"] == "inspection_plan" and nums["part_result"] == "not_recorded"


def test_four_positional_requirement_check_remains_supported():
    bundle = practical_bundle()
    status, message, nums = inspection.requirement_check(bundle, "end", "length", final_op(bundle))
    assert status == "pass" and message
    assert nums["gauge"] == "calipers"


@pytest.mark.parametrize(
    "mutation,status",
    [
        ("wrong-kind", "error"),
        ("missing", "error"),
        ("absent", "error"),
        ("unknown-ref", "unknown"),
        ("unknown-kind", "unknown"),
        ("verify", "unknown"),
        ("unknown-presence", "unknown"),
        ("unknown-method", "unknown"),
        ("unknown-contract", "unknown"),
        ("unknown-clauses", "unknown"),
        ("unknown-source", "unknown"),
    ],
)
def test_manual_comparator_contract_and_method_remain_fail_closed(mutation, status):
    bundle = practical_bundle()
    gauge = bundle.inventory["gauges"]["actual-slot"]
    op = final_op(bundle)
    contract = bundle.features["acceptance"]["actual_slot_fit"]["contract"]
    if mutation == "wrong-kind":
        gauge["kind"] = "caliper"
    elif mutation == "missing":
        del bundle.inventory["gauges"]["actual-slot"]
    elif mutation == "absent":
        gauge["present"] = False
    elif mutation == "unknown-ref":
        op["checks"]["actual_slot_fit"] = "unknown"
    elif mutation == "unknown-kind":
        gauge["kind"] = "unknown"
    elif mutation == "verify":
        gauge["verify"] = True
    elif mutation == "unknown-presence":
        gauge["present"] = "unknown"
    elif mutation == "unknown-method":
        op["inspection_methods"]["actual_slot_fit"] = "unknown"
    elif mutation == "unknown-contract":
        bundle.features["acceptance"]["actual_slot_fit"]["contract"] = "unknown"
    elif mutation == "unknown-clauses":
        contract["accept"] = "unknown"
    else:
        contract["cite"] = "unknown"
    row = next(
        row for row in inspection.evaluate(bundle) if row.subject == "nut1/part:actual_slot_fit"
    )
    assert row.status == status
    assert row.numbers["identity"]["feature_owner"] is None
    assert row.numbers["participants"] == ["base", "shoulders", "end"]


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("thread", "1/4-20", "error"),
        ("thread", "unknown", "unknown"),
        ("thread_hand", "left", "error"),
        ("thread_hand", "unknown", "unknown"),
        ("thread_class", "2A", "unknown"),
        ("thread_class", "unknown", "unknown"),
    ],
)
def test_hardware_identity_does_not_follow_name_or_prose(field, value, status):
    bundle = practical_bundle()
    bundle.inventory["gauges"]["stud"][field] = value
    result, _, _ = inspection.requirement_check(bundle, None, "stud_retention", final_op(bundle))
    assert result == status


def test_both_absent_unrequired_classes_under_manual_contract_are_not_invented():
    bundle = practical_bundle()
    assert thread_class_acceptance(bundle, "thread") == "manual_functional"
    status, _, nums = inspection.requirement_check(bundle, None, "stud_retention", final_op(bundle))
    assert status == "pass"
    assert "thread_class" not in bundle.features["features"]["thread"]
    assert "thread_class" not in bundle.inventory["gauges"]["stud"]
    assert nums["part_result"] == "not_recorded"


@pytest.mark.parametrize(
    "feature_class,gauge_class,status",
    [
        ("2B", "2A", "pass"),
        ("2B", "2B", "error"),
        ("2A", "2A", "error"),
        ("2B", None, "unknown"),
        ("unknown", "2A", "unknown"),
        (None, "2A", "unknown"),
    ],
)
def test_explicit_thread_classes_preserve_roles_and_one_sided_debt(
    feature_class, gauge_class, status
):
    bundle = practical_bundle()
    if feature_class is not None:
        bundle.features["features"]["thread"]["thread_class"] = feature_class
    if gauge_class is not None:
        bundle.inventory["gauges"]["stud"]["thread_class"] = gauge_class
    assert (
        inspection.requirement_check(bundle, None, "stud_retention", final_op(bundle))[0] == status
    )


def test_one_nut_final_check_never_covers_another_nut():
    bundle = practical_bundle()
    del final_op(bundle, "nut2")["checks"]["stud_retention"]
    rows = {row.subject: row for row in inspection.evaluate(bundle)}
    assert rows["nut1/part:stud_retention"].status == "pass"
    assert rows["nut2/part:stud_retention"].status == "error"
    assert rows["nut3/part:stud_retention"].status == "pass"
    assert rows["nut4/part:stud_retention"].status == "pass"


def test_later_member_work_requires_a_new_manual_final_check():
    bundle = practical_bundle()
    setup = bundle.plan["setups"][-4]
    setup["ops"].append({"op": 20, "do": "hand_tap", "feature": "thread"})
    row = next(
        row for row in inspection.evaluate(bundle) if row.subject == "nut1/part:stud_retention"
    )
    assert row.status == "error"
    assert "precedes later work" in row.sentence


def test_explicit_single_member_manual_selection_uses_inspection_not_face_ownership():
    bundle = practical_bundle()
    setup = bundle.plan["setups"][0]
    op = deepcopy(final_op(bundle))
    op.update(op=40, inspect_workpieces=["nut1"])
    setup["ops"].append(op)
    assert operation_members(bundle, setup, op) is None
    manual = [
        target for target in op_check_targets(bundle, setup, op) if target["kind"] == "manual"
    ]
    assert len(manual) == 2
    assert all(target["identity"]["workpiece"] == "nut1" for target in manual)
    assert all(
        target["shared_check_id"] is None and not target["covered_workpieces"] for target in manual
    )
    status, _, _ = inspection.requirement_check(
        bundle, None, "stud_retention", op, setup=setup, workpiece="nut1"
    )
    assert status == "pass"


def test_direct_requirement_check_refuses_wrong_workpiece_context():
    bundle = practical_bundle()
    setup = bundle.plan["setups"][-4]
    assert (
        inspection.requirement_check(
            bundle, "end", "length", setup["ops"][0], setup=setup, workpiece="nut2"
        )[0]
        == "error"
    )
    assert (
        inspection.requirement_check(
            bundle, None, "stud_retention", setup["ops"][0], setup=setup, workpiece="nut2"
        )[0]
        == "error"
    )


@pytest.mark.parametrize("action", ["hand_tap", "die_thread"])
def test_hand_thread_corner_rule_is_inapplicable_before_missing_corner_facts(tmp_path, action):
    bundle = rules_bundle(tmp_path)
    bundle.plan["setups"][0]["ops"][0]["do"] = action
    bundle = replace(bundle, kernel={"status": "unknown", "reason": "no helical kernel facts"})
    [row] = internal_corner_radius.evaluate(bundle)
    assert row.status == "not_applicable"
    assert row.numbers == {"action": action}


def test_genuine_rotary_corner_conflict_is_still_an_error(tmp_path):
    bundle = rules_bundle(tmp_path)
    bundle.kernel["ops"]["S1:10"]["corner_radii_mm"] = [0.1]
    [row] = internal_corner_radius.evaluate(bundle)
    assert row.status == "error"


def test_preservation_accessor_accepts_real_zero_based_face_domain():
    bundle = practical_bundle()
    install_preservation(bundle)
    row = inspection_preservation_evidence(bundle, "E1", shared_op(bundle), "base", "width", "nut1")
    assert row["status"] == "pass"
    assert row["proof"]["region"]["indices"] == [0, 1]


def test_unknown_selection_cannot_supply_a_siblings_missing_final_check():
    bundle = practical_bundle()
    final_op(bundle, "nut1")["inspect_workpieces"] = "unknown"
    del final_op(bundle, "nut2")["checks"]["length"]
    del final_op(bundle, "nut2")["checks"]["stud_retention"]
    rows = {row.subject: row for row in inspection.evaluate(bundle)}
    assert rows["nut1/end:length"].status == "unknown"
    assert rows["nut2/end:length"].status == "error"
    assert rows["nut2/part:stud_retention"].status == "error"


def test_known_wrong_comparator_kind_is_not_hidden_by_verification_debt():
    bundle = practical_bundle()
    bundle.inventory["gauges"]["actual-slot"].update(kind="caliper", verify=True)
    status, _, _ = inspection.requirement_check(bundle, None, "actual_slot_fit", final_op(bundle))
    assert status == "error"


def test_absent_manual_contract_remains_required_unresolved_input():
    bundle = practical_bundle()
    del bundle.features["acceptance"]["actual_slot_fit"]["contract"]
    rows = {row.subject: row for row in inspection.evaluate(bundle)}
    assert rows["nut1/part:actual_slot_fit"].status == "unknown"
    assert rows["nut1/part:actual_slot_fit"].numbers["contract"] == "unknown"


@pytest.mark.parametrize("requirements", ["unknown", ["unknown"], ["thread_class"]])
def test_absent_classes_do_not_waive_unknown_or_adopted_class_requirements(requirements):
    bundle = practical_bundle()
    bundle.features["features"]["thread"]["requirements"] = requirements
    assert (
        inspection.requirement_check(bundle, None, "stud_retention", final_op(bundle))[0]
        == "unknown"
    )


def test_class_policy_defaults_to_formal_without_feature_context():
    from types import SimpleNamespace

    assert thread_class_acceptance(SimpleNamespace(plan={}, inventory={}), "thread") == "formal"


@pytest.mark.parametrize("field", ["accept", "gauge_kind", "cite"])
def test_unknown_manual_contract_fact_cannot_authorize_class_omission(field):
    bundle = practical_bundle()
    bundle.features["acceptance"]["stud_retention"]["contract"][field] = "unknown"
    assert thread_class_acceptance(bundle, "thread") == "formal"


def test_unknown_registration_cannot_be_replayed_as_a_matching_native_proof():
    bundle = practical_bundle()
    install_preservation(bundle)
    bundle.plan["workpieces"]["nut1"]["pose"] = "unknown"
    for proof in bundle.kernel["setups"]["E1"]["inspection_preservation"]:
        proof["registration"] = {"pose": "unknown"}
    row = inspection_preservation_evidence(bundle, "E1", shared_op(bundle), "base", "width", "nut1")
    assert row["status"] == "unknown"
