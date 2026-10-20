"""Policy consumers select actual structured inspection owners, not display prefixes."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_practical_inspection import (
    MEMBERS,
    final_op,
    install_preservation,
    practical_bundle,
)

from prechips.findings import Finding, exit_code, is_required, selector_match
from prechips.report import build_report
from prechips.rules import inspection, required_coverage


@pytest.fixture
def planned_checks():
    bundle = practical_bundle()
    install_preservation(bundle)
    return bundle, inspection.evaluate(bundle)


def selected_subjects(bundle, findings, selector):
    policy = {"required": {"inspection": selector}}
    return {row.subject for row in findings if is_required(row, policy, bundle)}


def consumer_report(bundle, findings, selector):
    selected = replace(bundle, policy={"required": {"inspection": selector}})
    missing = required_coverage(selected, findings)
    all_findings = [*findings, *missing]
    report = build_report(selected, all_findings, assets={})
    assert report["expected_exit"] == exit_code(all_findings, selected.policy, selected)
    return report, missing


@pytest.mark.parametrize(
    "selector,expected",
    [
        (
            "base",
            {"S1:30/base:width", "S1:30/base:height"}
            | {f"{member}/part:actual_slot_fit" for member in MEMBERS},
        ),
        (
            "end",
            {f"{member}/end:length" for member in MEMBERS}
            | {f"{member}/part:actual_slot_fit" for member in MEMBERS},
        ),
        (
            "thread",
            {f"{member}/thread" for member in MEMBERS}
            | {f"{member}/part:stud_retention" for member in MEMBERS},
        ),
        ("stud_retention", {f"{member}/part:stud_retention" for member in MEMBERS}),
        ("actual_slot_fit", {f"{member}/part:actual_slot_fit" for member in MEMBERS}),
        (
            "holes",
            {f"{member}/thread" for member in MEMBERS}
            | {f"{member}/part:stud_retention" for member in MEMBERS},
        ),
        (
            "toleranced_features",
            {
                "S1:30/base:width",
                "S1:30/base:height",
                "S1:30/shoulders:thickness",
                "S1:30/shoulders:width",
            }
            | {f"{member}/end:length" for member in MEMBERS}
            | {f"{member}/part:actual_slot_fit" for member in MEMBERS},
        ),
    ],
)
def test_owner_selectors_cover_shared_member_and_part_relationship_findings(
    planned_checks, selector, expected
):
    bundle, findings = planned_checks
    assert selected_subjects(bundle, findings, selector) == expected
    report, missing = consumer_report(bundle, findings, selector)
    assert missing == []
    assert report["expected_exit"] == 0
    assert report["verification"] == "checked"
    # Policy passes certify an inspection plan, never recorded physical results.
    selected = [row for row in report["findings"] if row["subject"] in expected]
    assert selected
    assert all(row["numbers"]["evaluation"] == "inspection_plan" for row in selected)
    assert all(row["numbers"]["part_result"] == "not_recorded" for row in selected)


@pytest.mark.parametrize(
    "selector,expected_exit",
    [
        ("end", 4),
        ("toleranced_features", 4),
        ("base", 0),
        ("holes", 0),
        ("stud_retention", 0),
        (["nut1/end:length"], 4),
        (["nut2/end:length"], 0),
    ],
)
def test_one_unknown_member_dimension_blocks_only_its_required_consumers(selector, expected_exit):
    bundle = practical_bundle()
    install_preservation(bundle)
    final_op(bundle, "nut1")["checks"]["length"] = "unknown"
    findings = inspection.evaluate(bundle)
    by_subject = {row.subject: row for row in findings}
    assert by_subject["nut1/end:length"].status == "unknown"
    assert by_subject["nut2/end:length"].status == "pass"
    report, missing = consumer_report(bundle, findings, selector)
    assert missing == []
    assert report["expected_exit"] == expected_exit
    assert report["verification"] == ("planned" if expected_exit else "checked")


@pytest.mark.parametrize(
    "selector,expected_exit",
    [
        ("holes", 4),
        ("thread", 4),
        ("stud_retention", 4),
        ("toleranced_features", 0),
        ("base", 0),
        ("actual_slot_fit", 0),
    ],
)
def test_unresolved_thread_comparator_is_required_by_threaded_hole_ownership(
    selector, expected_exit
):
    bundle = practical_bundle()
    install_preservation(bundle)
    bundle.inventory["gauges"]["stud"]["thread"] = "unknown"
    findings = inspection.evaluate(bundle)
    stud = [row for row in findings if row.numbers.get("requirement") == "stud_retention"]
    assert len(stud) == 4
    assert {row.status for row in stud} == {"unknown"}
    report, missing = consumer_report(bundle, findings, selector)
    assert missing == []
    assert report["expected_exit"] == expected_exit


@pytest.mark.parametrize("selector", ["base", "end", "actual_slot_fit", "toleranced_features"])
def test_unknown_manual_contract_still_selects_its_known_participants(selector):
    bundle = practical_bundle()
    install_preservation(bundle)
    bundle.features["acceptance"]["actual_slot_fit"]["contract"] = "unknown"
    findings = inspection.evaluate(bundle)
    manual = next(row for row in findings if row.subject == "nut1/part:actual_slot_fit")
    assert manual.status == "unknown"
    assert is_required(manual, {"required": {"inspection": selector}}, bundle)
    report, missing = consumer_report(bundle, findings, selector)
    assert missing == []
    assert report["expected_exit"] == 4


def test_manual_contract_does_not_create_numeric_tolerance_selection(planned_checks):
    bundle, findings = planned_checks
    stud = next(row for row in findings if row.subject == "nut1/part:stud_retention")
    assert bundle.feature_definitions["thread"]["requirements"] == []
    assert selector_match(stud, "toleranced_features", bundle) == "no_match"
    assert selector_match(stud, "holes", bundle) == "match"
    assert selector_match(stud, "thread", bundle) == "match"
    assert (
        required_coverage(replace(bundle, policy={"required": {"inspection": "holes"}}), [stud])
        == []
    )


def test_unknown_participant_requirements_retain_existing_tolerance_debt():
    bundle = practical_bundle()
    install_preservation(bundle)
    bundle.features["features"]["thread"]["requirements"] = "unknown"
    findings = inspection.evaluate(bundle)
    stud = next(row for row in findings if row.subject == "nut1/part:stud_retention")
    assert selector_match(stud, "toleranced_features", bundle) == "match"
    report, missing = consumer_report(bundle, findings, "toleranced_features")
    assert missing == []
    assert report["expected_exit"] == 4


def test_display_subject_and_copied_participants_cannot_override_authoritative_identity(
    planned_checks,
):
    bundle, findings = planned_checks
    original = next(row for row in findings if row.subject == "nut1/part:stud_retention")
    numbers = deepcopy(original.numbers)
    numbers["participants"] = ["base"]
    misleading = replace(original, subject="nut1/part:actual_slot_fit", numbers=numbers)
    assert selector_match(misleading, "thread", bundle) == "match"
    assert selector_match(misleading, "holes", bundle) == "match"
    assert selector_match(misleading, "base", bundle) == "no_match"
    assert selector_match(misleading, "actual_slot_fit", bundle) == "no_match"
    assert selector_match(misleading, "stud_retention", bundle) == "match"
    assert (
        required_coverage(
            replace(bundle, policy={"required": {"inspection": "thread"}}), [misleading]
        )
        == []
    )


def test_dimensional_owner_does_not_come_from_member_or_shared_subject_text(planned_checks):
    bundle, findings = planned_checks
    original = next(row for row in findings if row.subject == "S1:30/base:width")
    misleading = replace(original, subject="nut9/end:length")
    assert selector_match(misleading, "base", bundle) == "match"
    assert selector_match(misleading, "end", bundle) == "no_match"
    assert (
        required_coverage(
            replace(bundle, policy={"required": {"inspection": "base"}}), [misleading]
        )
        == []
    )


@pytest.mark.parametrize("selector", [["end"], ["base"], ["stud_retention"]])
def test_subject_lists_never_expand_to_owner_or_relationship_selectors(planned_checks, selector):
    bundle, findings = planned_checks
    assert selected_subjects(bundle, findings, selector) == set()
    report, missing = consumer_report(bundle, findings, selector)
    assert [row.subject for row in missing] == selector
    assert report["expected_exit"] == 4


def test_complete_qualified_subject_list_selects_only_the_named_member(planned_checks):
    bundle, findings = planned_checks
    selector = ["nut2/part:stud_retention", "S1:30/base:width"]
    assert selected_subjects(bundle, findings, selector) == set(selector)
    report, missing = consumer_report(bundle, findings, selector)
    assert missing == []
    assert report["expected_exit"] == 0


@pytest.mark.parametrize(
    "identity",
    [
        None,
        "unknown",
        {},
        {"workpiece": "nut1", "feature_owner": "unknown", "requirement": "length"},
        {"workpiece": "nut1", "feature_owner": "missing", "requirement": "length"},
    ],
)
def test_unknown_owner_cannot_establish_nonselection_or_claim_coverage(planned_checks, identity):
    bundle, findings = planned_checks
    original = next(row for row in findings if row.subject == "nut1/end:length")
    numbers = deepcopy(original.numbers)
    if identity is None:
        numbers.pop("identity")
    else:
        numbers["identity"] = identity
    unknown_owner = replace(original, status="unknown", numbers=numbers)
    assert selector_match(unknown_owner, "end", bundle) == "unknown"
    assert is_required(unknown_owner, {"required": {"inspection": "end"}}, bundle)
    report, missing = consumer_report(bundle, [unknown_owner], "end")
    assert [row.subject for row in missing] == ["end"]
    assert report["expected_exit"] == 4
    # Even an inconsistent PASS marker cannot turn absent ownership into coverage.
    report, missing = consumer_report(bundle, [replace(unknown_owner, status="pass")], "end")
    assert [row.subject for row in missing] == ["end"]
    assert report["expected_exit"] == 4


@pytest.mark.parametrize("participants", [None, "unknown", [], ["missing"]])
def test_unknown_relationship_participants_remain_conservative_debt(planned_checks, participants):
    bundle, findings = planned_checks
    manual = next(row for row in findings if row.subject == "nut1/part:stud_retention")
    relationship = bundle.features["acceptance"]["stud_retention"]
    if participants is None:
        relationship.pop("features")
    else:
        relationship["features"] = participants
    unresolved = replace(manual, status="unknown")
    assert selector_match(unresolved, "thread", bundle) == "unknown"
    assert selector_match(unresolved, "holes", bundle) == "unknown"
    assert selector_match(unresolved, "stud_retention", bundle) == "unknown"
    report, missing = consumer_report(bundle, [unresolved], "holes")
    assert [row.subject for row in missing] == ["thread"]
    assert report["expected_exit"] == 4


def test_legacy_unqualified_feature_rows_keep_their_original_selection(planned_checks):
    bundle, _ = planned_checks
    row = Finding("inspection", "end:length", "unknown", {}, [], "Legacy dimensional debt.")
    assert selector_match(row, "end", bundle) == "match"
    assert selector_match(row, "holes", bundle) == "no_match"
    assert selector_match(row, "toleranced_features", bundle) == "match"
    report, missing = consumer_report(bundle, [row], "end")
    assert missing == []
    assert report["expected_exit"] == 4


def test_setups_selects_only_bare_ids_not_operations_or_inspection_subjects(planned_checks):
    bundle, findings = planned_checks
    bare = Finding("inspection", "S1", "unknown", {}, [], "Bare setup debt.")
    operation = replace(bare, subject="S1:20")
    policy = {"required": {"inspection": "setups"}}
    assert is_required(bare, policy, bundle)
    assert not is_required(operation, policy, bundle)
    assert not any(is_required(row, policy, bundle) for row in findings)
    report, missing = consumer_report(bundle, [*findings, operation], "setups")
    assert {row.subject for row in missing} == {setup["id"] for setup in bundle.plan["setups"]}
    assert report["expected_exit"] == 4


def test_arbitrary_unmatched_selector_keeps_missing_coverage_debt(planned_checks):
    bundle, findings = planned_checks
    selector = "not-a-feature-or-relationship"
    assert selected_subjects(bundle, findings, selector) == set()
    report, missing = consumer_report(bundle, findings, selector)
    assert [row.subject for row in missing] == [selector]
    assert report["expected_exit"] == 4


@pytest.mark.parametrize("identity", [None, "unknown", {}])
def test_missing_manual_owner_metadata_cannot_waive_an_exact_relationship(planned_checks, identity):
    bundle, findings = planned_checks
    original = next(row for row in findings if row.subject == "nut1/part:stud_retention")
    numbers = deepcopy(original.numbers)
    if identity is None:
        numbers.pop("identity")
    else:
        numbers["identity"] = identity
    unresolved = replace(original, status="unknown", numbers=numbers)
    policy = {"required": {"inspection": "stud_retention"}}
    assert selector_match(unresolved, "stud_retention", bundle) == "unknown"
    assert is_required(unresolved, policy, bundle)
    assert exit_code([unresolved], policy, bundle) == 4
    report, missing = consumer_report(bundle, [unresolved], "stud_retention")
    assert [row.subject for row in missing] == ["stud_retention"]
    assert report["expected_exit"] == 4


def test_known_manual_comparator_error_still_precedes_policy_nonselection():
    bundle = practical_bundle()
    install_preservation(bundle)
    bundle.inventory["gauges"]["actual-slot"]["kind"] = "mating_hardware"
    findings = inspection.evaluate(bundle)
    slot = next(row for row in findings if row.subject == "nut1/part:actual_slot_fit")
    assert slot.status == "error"
    assert selector_match(slot, "holes", bundle) == "no_match"
    report, missing = consumer_report(bundle, findings, "holes")
    assert missing == []
    assert report["expected_exit"] == 2
    assert report["verification"] == "planned"
