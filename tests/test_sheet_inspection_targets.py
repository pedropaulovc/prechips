"""Inspection criteria retain their explicit physical recording owner on the sheet."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from test_batch_material_routes import batch
from test_sheet_ops import Markup, content, shop

from prechips.findings import Finding
from prechips.inputs import load_bundle
from prechips.rules.resolution import op_check_targets, resolve
from prechips.sheet import _Inspection, _ledger_row, _readings, _Row, _Steps, _Traveler

MEMBERS = ["nut1", "nut2", "nut3", "nut4"]
SECTION_SUBJECTS = {
    "S1:30/base-envelope:width",
    "S1:30/base-envelope:height",
    "S1:30/shoulders:thickness",
    "S1:30/shoulders:width",
}
SLOT_CRITERIA = [
    "Slide freely by hand without objectionable rocking.",
    "Shoulders bear without bottoming or wedging; top remains below the table.",
]
STUD_CRITERIA = ["The intended stud enters by hand and stops before exiting at the bottom."]


def inspection_job():
    """Use real nested member routing, without claiming measured or native results."""
    plan = batch()
    plan["dro"] = {"kind": "digital", "units": "mm"}
    section = plan["setups"][0]
    section["id"] = "S1"
    section["ops"] = [
        {"op": 20, "do": "mill_profile", "feature": "shoulders"},
        {
            "op": 30,
            "do": "inspect",
            "feature": ["base-envelope", "shoulders"],
            "inspect_workpieces": MEMBERS.copy(),
            "inspection_scope": {"after": "S1:20", "before": "C1a:10"},
            "checks": {
                "width": "gauges.calipers",
                "height": "gauges.calipers",
                "thickness": "gauges.calipers",
            },
            "inspection_methods": {
                "width": "Measure the section at every future blank station.",
                "height": "Measure the overall bar height.",
                "thickness": "Measure the shoulder thickness at each station.",
            },
        },
    ]
    plan["setups"][1]["stock_in"] = "S1"
    finals = plan["setups"][-4:]
    for index, setup in enumerate(finals, 1):
        setup["id"] = f"F1{chr(96 + index)}"
        setup["ops"] = [
            {
                "op": 10,
                "do": "inspect",
                "feature": "end-length",
                "checks": {
                    "length": "gauges.calipers",
                    "actual_slot_fit": "gauges.actual-slot",
                    "stud_retention": "gauges.mating-hardware",
                },
                "inspection_methods": {
                    "length": "Measure the two finished end faces with calipers.",
                    "actual_slot_fit": "Try this nut in the actual mating slot.",
                    "stud_retention": "Try the intended stud in this nut by hand.",
                },
            }
        ]
    features = {
        "units": "mm",
        "precision": 3,
        "features": {
            "base-envelope": {
                "kind": "prism",
                "requirements": ["width", "height"],
                "width": [22.1742, 22.2758],
                "height": [12.6492, 12.7508],
            },
            "shoulders": {
                "kind": "prism",
                "requirements": ["thickness", "width"],
                "thickness": [6.2992, 6.4008],
                "width": [12.5222, 12.6238],
            },
            "end-length": {
                "kind": "end_face",
                "requirements": ["length"],
                "length": [25.3492, 25.4508],
            },
            "threaded-hole": {
                "kind": "threaded_hole",
                "requirements": [],
                "dia_nominal": 9.525,
            },
        },
        "acceptance": {
            "actual_slot_fit": {
                "features": ["base-envelope", "shoulders", "end-length"],
                "contract": {
                    "kind": "manual",
                    "gauge_kind": "mating_part",
                    "accept": SLOT_CRITERIA.copy(),
                    "cite": "Authored functional slot acceptance",
                },
            },
            "stud_retention": {
                "features": ["threaded-hole"],
                "contract": {
                    "kind": "manual",
                    "gauge_kind": "mating_hardware",
                    "accept": STUD_CRITERIA.copy(),
                    "cite": "Authored functional stud acceptance",
                },
            },
        },
    }
    bundle = replace(
        shop({}).bundle,
        plan=plan,
        features=features,
        inventory={
            "gauges": {
                "calipers": {"kind": "caliper", "name": "Calipers"},
                "actual-slot": {"kind": "mating_part", "name": "Actual slot comparator"},
                "mating-hardware": {"kind": "mating_hardware", "name": "Intended stud comparator"},
            }
        },
    )
    return _Traveler(bundle, [], {}, None), section, finals


def plan_finding(
    subject, *, setup_id, op_id, feature, requirement, member=None, covered=(), status="pass"
):
    return Finding(
        rule="inspection",
        subject=subject,
        status=status,
        sentence="Comparator is unavailable" if status == "error" else "Inspection plan complete",
        cite=["Synthetic inspection-plan routing evidence; no physical result"],
        numbers={
            "identity": {"workpiece": member, "feature_owner": feature, "requirement": requirement},
            "setup_id": setup_id,
            "op_id": op_id,
            "shared_check_id": "S1:30" if covered else None,
            "covered_workpieces": list(covered),
            "evaluation": "inspection_plan",
            "part_result": "not_recorded",
        },
    )


def inspection_markup(sheet, setup, op=None):
    op = op or setup["ops"][-1]
    checks = sheet.inspection(setup, op)
    row = _Row(
        (str(op["op"]), "Part", "—", "Inspect", checks),
        setup_id=setup["id"],
        op_id=op["op"],
    )
    return Markup(_ledger_row(row, ["step", "feature", "gauge", "action", "inspect"])), checks


def subject_ids(record):
    import json

    return set(json.loads(record["attrs"]["data-inspection-ids"]))


def test_one_batch_checkpoint_and_four_individual_final_records_remain_blank():
    import json

    sheet, section, finals = inspection_job()
    batch_markup, batch_checks = inspection_markup(sheet, section)
    (batch_record,) = batch_markup.find("inspection-record")
    assert subject_ids(batch_record) == SECTION_SUBJECTS
    assert json.loads(batch_record["attrs"]["data-covered-workpieces"]) == MEMBERS
    assert batch_record["attrs"]["data-shared-check"] == "S1:30"
    assert batch_record["attrs"]["data-workpiece"] == ""
    assert len(batch_markup.find("result-field", batch_record)) == 1
    assert batch_checks[0].subjects and len(batch_checks[0].subjects) == 4

    final_records = []
    for index, setup in enumerate(finals, 1):
        markup, _ = inspection_markup(sheet, setup)
        (record,) = markup.find("inspection-record")
        final_records.append((markup, record))
        assert subject_ids(record) == {
            f"nut{index}/end-length:length",
            f"nut{index}/part:actual_slot_fit",
            f"nut{index}/part:stud_retention",
        }
        assert record["attrs"]["data-workpiece"] == f"nut{index}"
        assert record["attrs"]["data-shared-check"] == ""
        assert json.loads(record["attrs"]["data-covered-workpieces"]) == []
        assert all(criterion in content(record) for criterion in SLOT_CRITERIA + STUD_CRITERIA)
        assert "25.350–25.450 mm" in content(record)
        methods = markup.find("inspection-method", record)
        assert len(methods) == 3
        assert len(markup.find("result-field", record)) == 1
    assert len({record["attrs"]["data-record-title"] for _, record in final_records}) == 4
    for markup, record in [(batch_markup, batch_record), *final_records]:
        (blank,) = markup.find("writing-blank", record)
        assert content(blank) == ""


def test_manual_relationships_have_part_ownership_not_participant_feature_copies():
    import json

    sheet, _, finals = inspection_job()
    setup = finals[0]
    op = setup["ops"][0]
    del op["feature"]
    del op["checks"]["length"]
    del op["inspection_methods"]["length"]
    markup, checks = inspection_markup(sheet, setup)
    (record,) = markup.find("inspection-record")
    assert subject_ids(record) == {"nut1/part:actual_slot_fit", "nut1/part:stud_retention"}
    assert json.loads(record["attrs"]["data-features"]) == []
    assert checks[0].qualitative and checks[0].unit == ""
    for clause in SLOT_CRITERIA + STUD_CRITERIA:
        assert content(record).count(clause) == 1
    assert "Actual slot comparator" in content(record)
    assert "Intended stud comparator" in content(record)
    assert len(markup.find("writing-blank")) == 1
    assert len(checks[0].methods) == len(markup.find("inspection-method", record)) == 2


def test_missing_numeric_manual_and_authored_requirements_stay_visible_without_fake_results():
    sheet, section, finals = inspection_job()
    sheet.features["shoulders"]["thickness"] = "unknown"
    shared, _ = inspection_markup(sheet, section)
    (record,) = shared.find("inspection-record")
    assert subject_ids(record) == SECTION_SUBJECTS - {"S1:30/shoulders:thickness"}
    assert any(
        "thickness" in content(node) and "?" in content(node)
        for node in shared.find("inspection-message")
    )

    sheet.bundle.features["acceptance"]["actual_slot_fit"]["contract"] = "unknown"
    op = finals[0]["ops"][0]
    op["checks"]["stud_retention"] = "unknown"
    op["inspection_methods"]["stud_retention"] = "unknown"
    op["missing_requirements"] = {"below_table_top": "unknown"}
    op["process_holds"] = [
        {
            "feature": "end-length",
            "requirement": "length",
            "band": [25.37, 25.43],
            "gauge": "gauges.calipers",
            "reason": "Retain the authored process margin.",
        }
    ]
    markup, checks = inspection_markup(sheet, finals[0])
    (record,) = markup.find("inspection-record")
    assert subject_ids(record) == {"nut1/end-length:length", "nut1/part:stud_retention"}
    messages = markup.find("inspection-message")
    assert any("actual slot fit" in content(node) and "?" in content(node) for node in messages)
    assert any(
        "below table top" in content(node) and "no drawing limit" in content(node)
        for node in messages
    )
    assert any(
        "PROCESS HOLD" in content(node) and "25.370–25.430" in content(node) for node in messages
    )
    assert all(not markup.find("writing-blank", node) for node in messages)
    assert "?" in content(record)
    assert all(
        not isinstance(check, _Inspection) or "nut1/part:actual_slot_fit" not in check.subjects
        for check in checks
    )


def test_authored_method_readings_stay_inline_at_the_explicit_physical_checkpoint():
    sheet, section, finals = inspection_job()
    section["ops"][-1]["inspection_methods"]["height"] = [
        "Read the bar at the first station: {first}",
        "Read the bar at the last station: {last}",
        "Calculate: station difference = first - last = {difference}",
        "Calculate: final station result = difference = {station_result}",
    ]
    markup, checks = inspection_markup(sheet, section)
    (checkpoint,) = [check for check in checks if isinstance(check, _Inspection)]
    (record,) = markup.find("inspection-record")
    assert checkpoint.shared_check_id == "S1:30"
    assert checkpoint.covered_workpieces == tuple(MEMBERS)
    assert subject_ids(record) == set(checkpoint.subjects) == SECTION_SUBJECTS
    (steps,) = [method for method in checkpoint.methods if isinstance(method, _Steps)]
    assert _readings(steps[1]) == [(1, "first"), (2, "last")]
    (worksheet,) = markup.find("worksheet", record)
    assert len(markup.find("writing-blank", worksheet)) == 4
    # The height readings do not also record the other three section criteria.
    assert not checkpoint.reading_owned
    assert len(markup.find("result-field", record)) == 1
    assert len(markup.find("writing-blank", record)) == 5
    assert all(content(blank) == "" for blank in markup.find("writing-blank", record))

    finals[0]["ops"][0]["inspection_methods"]["length"] = (
        "Measure the finished ends; record {finished_length}."
    )
    final, checks = inspection_markup(sheet, finals[0])
    (checkpoint,) = [check for check in checks if isinstance(check, _Inspection)]
    (record,) = final.find("inspection-record")
    assert checkpoint.workpiece == "nut1"
    assert subject_ids(record) == {
        "nut1/end-length:length",
        "nut1/part:actual_slot_fit",
        "nut1/part:stud_retention",
    }
    assert len(checkpoint.methods) == len(final.find("inspection-method", record)) == 3
    assert not checkpoint.reading_owned
    assert len(final.find("result-field", record)) == 1
    assert len(final.find("writing-blank", record)) == 2
    assert all(content(blank) == "" for blank in final.find("writing-blank", record))


def test_a_reading_owned_checkpoint_has_no_second_overall_result_blank():
    sheet, _, finals = inspection_job()
    op = finals[0]["ops"][0]
    op["checks"] = {"length": "gauges.calipers"}
    op["inspection_methods"] = {"length": "Measure the ends; record {finished_length}."}
    markup, checks = inspection_markup(sheet, finals[0])
    (checkpoint,) = checks
    (record,) = markup.find("inspection-record")
    assert checkpoint.reading_owned
    assert subject_ids(record) == {"nut1/end-length:length"}
    assert not markup.find("result-field", record)
    (blank,) = markup.find("writing-blank", record)
    assert content(blank) == ""


def test_legacy_distinct_bands_keep_independent_results_and_one_inline_reading():
    sheet = shop({})
    features = {
        "left": {"requirements": ["length"], "length": [6.33, 6.35]},
        "right": {"requirements": ["length"], "length": [8.01, 8.03]},
    }
    sheet.bundle = replace(
        sheet.bundle,
        features={"units": "mm", "precision": 3, "features": features},
        inventory={"gauges": {"calipers": {"kind": "caliper", "name": "Calipers"}}},
    )
    sheet.features = features
    setup = {
        "id": "L1",
        "ops": [
            {
                "op": 10,
                "do": "inspect",
                "feature": ["left", "right"],
                "checks": {"length": "gauges.calipers"},
                "inspection_methods": {"length": "Use the calipers; record {observed}."},
            }
        ],
    }
    sheet.plan["setups"] = [setup]
    markup, checks = inspection_markup(sheet, setup)
    records = markup.find("inspection-record")
    assert len(records) == len(checks) == 2
    assert [check.features for check in checks] == [("left",), ("right",)]
    assert all(not check.workpiece and not check.shared_check_id for check in checks)
    assert all(not check.reading_owned for check in checks)
    for record, check, band, other in zip(
        records,
        checks,
        ("6.330–6.350", "8.010–8.030"),
        ("8.010–8.030", "6.330–6.350"),
        strict=True,
    ):
        assert subject_ids(record) == set(check.subjects)
        assert band in content(record) and other not in content(record)
        assert len(markup.find("result-field", record)) == 1
    (method,) = markup.find("inspection-method")
    assert [content(label) for label in markup.find("field-label", method)] == ["observed"]
    assert len(markup.find("writing-blank", method)) == 1
    assert len(markup.find("writing-blank")) == 3
    assert all(content(blank) == "" for blank in markup.find("writing-blank"))


def test_structured_findings_route_and_match_without_decoding_diagnostic_subjects():
    sheet, section, finals = inspection_job()
    finding = plan_finding(
        "opaque diagnostic identity / not a qualified feature",
        setup_id="F1a",
        op_id=10,
        feature=None,
        requirement="actual_slot_fit",
        member="nut1",
        status="error",
    )
    sheet.findings = [finding]
    assert sheet.setup_findings(finals[0]) == [finding]
    assert sheet.setup_findings(finals[1]) == []
    assert sheet.setup_findings(section) == []
    stops, _, _ = sheet.status_lines([finding], finals[0])
    assert len(stops) == 1 and "10" in stops[0] and finding.sentence in stops[0]
    own_html, _ = sheet.operations(finals[0], {})
    sibling_html, _ = sheet.operations(finals[1], {})
    assert finding.sentence in own_html
    assert finding.sentence not in sibling_html

    # A capability-plan pass is associated by explicit identity, not by subject parsing,
    # and cannot become a recorded physical result or another nut's evidence.
    op = finals[0]["ops"][0]
    op["checks"] = {"actual_slot_fit": "gauges.actual-slot"}
    sheet.findings = [replace(finding, status="pass")]
    markup, _ = inspection_markup(sheet, finals[0])
    (record,) = markup.find("inspection-record")
    assert "?" not in content(record)
    assert subject_ids(record) == {"nut1/part:actual_slot_fit"}
    assert content(markup.find("writing-blank", record)[0]) == ""
    sibling_op = finals[1]["ops"][0]
    sibling_op["checks"] = {"actual_slot_fit": "gauges.actual-slot"}
    sibling, _ = inspection_markup(sheet, finals[1])
    assert "?" in content(sibling.find("inspection-record")[0])


def test_shared_plan_evidence_stays_at_its_batch_checkpoint_with_a_blank_result():
    sheet, section, finals = inspection_job()
    sheet.findings = [
        plan_finding(
            f"opaque batch diagnostic {index}",
            setup_id="S1",
            op_id=30,
            feature=feature,
            requirement=requirement,
            covered=MEMBERS,
        )
        for index, (feature, requirement) in enumerate(
            [
                ("base-envelope", "width"),
                ("base-envelope", "height"),
                ("shoulders", "thickness"),
                ("shoulders", "width"),
            ]
        )
    ]
    markup, _ = inspection_markup(sheet, section)
    (record,) = markup.find("inspection-record")
    assert subject_ids(record) == SECTION_SUBJECTS
    assert "?" not in content(record)
    assert content(markup.find("writing-blank", record)[0]) == ""
    assert sheet.setup_findings(section) == sheet.findings
    assert all(sheet.setup_findings(setup) == [] for setup in finals)
    sheet.findings[0].numbers["covered_workpieces"] = ["nut1", "nut2", "nut3"]
    unresolved, _ = inspection_markup(sheet, section)
    assert "?" in content(unresolved.find("inspection-record")[0])


def test_member_owned_missing_check_does_not_spread_to_another_final_nut():
    sheet, _, finals = inspection_job()
    finding = plan_finding(
        "uninterpreted missing-check diagnostic",
        setup_id=None,
        op_id=None,
        feature="end-length",
        requirement="length",
        member="nut2",
        status="error",
    )
    sheet.findings = [finding]
    assert sheet.setup_findings(finals[1]) == [finding]
    assert all(sheet.setup_findings(setup) == [] for setup in [finals[0], finals[2], finals[3]])


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_tnut_final_only_checkpoints_keep_all_sizes_and_four_physical_results(detail):
    bundle = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    sheet = _Traveler(bundle, [], {}, None, detail=detail)
    inspections = [
        (setup, op)
        for setup in bundle.plan["setups"]
        for op in setup.get("ops", [])
        if op.get("do") == "inspect"
    ]
    assert [(setup["id"], op["op"]) for setup, op in inspections] == [
        ("F1a", 10),
        ("F1b", 10),
        ("F1c", 10),
        ("F1d", 10),
    ]
    dimensions = {
        ("base-envelope", "width"),
        ("base-envelope", "height"),
        ("shoulders", "width"),
        ("shoulders", "thickness"),
        ("end-length", "length"),
    }
    criteria = dimensions | {(None, "actual_slot_fit"), (None, "stud_retention")}
    # Criteria, not routine procedure paragraphs, carry the seven acceptance duties.
    # Keep independent numeric oracles in both printed unit systems.
    expected_bands = {
        ("base-envelope", "width"): ("0.873–0.877 in", "22.1742–22.2758 mm"),
        ("base-envelope", "height"): ("0.498–0.502 in", "12.6492–12.7508 mm"),
        ("shoulders", "width"): ("0.493–0.497 in", "12.5222–12.6238 mm"),
        ("shoulders", "thickness"): ("0.248–0.252 in", "6.2992–6.4008 mm"),
        ("end-length", "length"): ("0.998–1.002 in", "25.3492–25.4508 mm"),
    }
    band_index = int(detail == "pedantic")
    # These are physical acceptance duties, not sentence punctuation. In the compact
    # sheet an inline method can follow the last clause with a dash instead of a stop.
    functional_patterns = {
        "actual_slot_fit": (
            r"no binding or objectionable rocking in intended slot\b",
            r"both flange shelves bear under lips:\s*no bottoming or wedging\b",
            r"\btop (?:stays|remains) below (?:the )?table\b",
        ),
        "stud_retention": (
            r"intended 3/8-16 RH stud:\s*free top entry\b",
            r"bottom-thread deformation stops stud before exit onto table\b",
            r"nut neither rotates nor passes through intended slot\b",
        ),
    }
    expected_subjects = {}
    for member, (setup, op) in zip(MEMBERS, inspections, strict=True):
        targets = op_check_targets(bundle, setup, op)
        assert {
            (target["identity"]["feature_owner"], target["identity"]["requirement"])
            for target in targets
        } == criteria
        assert all(
            target["identity"]["workpiece"] == member
            and target["selection_status"] == "pass"
            and target["shared_check_id"] is None
            and target["covered_workpieces"] == []
            for target in targets
        )
        assert all(
            target["kind"] == "dimensional"
            and (resolve(bundle, "gauges", target["gauge"]) or {}).get("kind") == "caliper"
            for target in targets
            if target["identity"]["feature_owner"] is not None
        )
        expected_subjects[member] = {
            f"{member}/{feature if feature is not None else 'part'}:{requirement}"
            for feature, requirement in criteria
        }
        markup, checks = inspection_markup(sheet, setup, op)
        (checkpoint,) = [check for check in checks if isinstance(check, _Inspection)]
        assert checkpoint.workpiece == member
        assert checkpoint.shared_check_id is None and checkpoint.covered_workpieces == ()
        assert set(checkpoint.subjects) == expected_subjects[member]
        assert set(checkpoint.features) == {feature for feature, _ in dimensions}
        assert len(checkpoint.compact_criteria) == len(criteria) == 7
        by_heading = {
            criterion.heading: (gauge_id, gauge, criterion)
            for gauge_id, gauge, criterion in checkpoint.compact_criteria
        }
        assert len(by_heading) == 7
        for (feature, requirement), bands in expected_bands.items():
            ((gauge_id, gauge, criterion),) = [
                entry
                for entry in checkpoint.compact_criteria
                if feature in entry[2].heading
                and requirement in entry[2].heading.replace("-", " ").split()
            ]
            assert gauge_id == ("gauges", "calipers") and gauge == "Calipers"
            assert bands[band_index] in criterion, (feature, requirement, criterion)
        for requirement, gauge_key in (
            ("actual_slot_fit", "actual-slot"),
            ("stud_retention", "mating-hardware"),
        ):
            gauge_id, gauge, criterion = by_heading[requirement.replace("_", " ")]
            assert gauge_id == ("gauges", gauge_key)
            assert gauge == bundle.inventory["gauges"][gauge_key]["name"]
            for pattern in functional_patterns[requirement]:
                assert re.search(pattern, criterion, re.IGNORECASE), (requirement, criterion)
            method = op["inspection_methods"][requirement]
            assert any(method in str(note) for note in criterion.methods)
        flange = by_heading["shoulders thickness"][2]
        flange_method = op["inspection_methods"]["shoulders"]["thickness"]
        assert any(flange_method in str(note) for note in flange.methods)
        for method in (
            flange_method,
            op["inspection_methods"]["actual_slot_fit"],
            op["inspection_methods"]["stud_retention"],
        ):
            assert sum(method in str(note) for note in checkpoint.methods) == 1
        assert not checkpoint.reading_owned
        (record,) = markup.find("inspection-record")
        assert subject_ids(record) == expected_subjects[member]
        assert len(markup.find("result-field", record)) == 1
        (blank,) = markup.find("writing-blank")
        assert content(blank) == ""

    finals = [setup for setup, _ in inspections]
    blocks = {setup["id"]: sheet.setup_blocks(setup) for setup in finals}
    family = Markup(sheet.family_html(finals, blocks))
    (grid,) = family.find("checkpoint-results")
    results = family.find("checkpoint-result", grid)
    assert [record["attrs"]["data-workpiece"] for record in results] == MEMBERS
    assert len(family.find("result-field")) == len(family.find("writing-blank")) == 4
    for bands in expected_bands.values():
        assert bands[band_index] in content(grid["parent"])
    for requirement in ("actual_slot_fit", "stud_retention"):
        for pattern in functional_patterns[requirement]:
            assert re.search(pattern, content(grid["parent"]), re.IGNORECASE), requirement
        assert inspections[0][1]["inspection_methods"][requirement] in content(grid["parent"])
    assert inspections[0][1]["inspection_methods"]["shoulders"]["thickness"] in content(
        grid["parent"]
    )
    for (setup, op), member, record in zip(inspections, MEMBERS, results, strict=True):
        assert record["attrs"]["data-setup-id"] == setup["id"]
        assert record["attrs"]["data-op-id"] == str(op["op"])
        assert record["attrs"]["data-shared-check"] == ""
        assert json.loads(record["attrs"]["data-covered-workpieces"]) == []
        assert subject_ids(record) == expected_subjects[member]
        (blank,) = family.find("writing-blank", record)
        assert content(blank) == ""
    # Finish remains an authored obligation, not a fabricated gauge or a fifth result.
    finish = bundle.plan["setups"][-4]["ops"][0]["note"]
    finish = finish[0]["text"] if isinstance(finish, list) else finish
    assert finish in content(grid["parent"])
