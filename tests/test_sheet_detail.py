"""Audience projection changes the paper, never the checked facts or their owners.

These host-only tests exercise the public renderer with real Bundle instances and
existing deterministic rule/asset fixtures. Native geometry and physical pagination
remain in their dedicated suites; no planning specimen is a runtime answer fixture.
"""

import base64
import json
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_batch_material_routes import batch
from test_bench_hold_fields import handling_bundle
from test_geometry_rules import rules_bundle
from test_kernel_outputs import _png
from test_procedure_boxes import mill_bundle
from test_sheet_inspection_targets import inspection_job, plan_finding
from test_sheet_measurement_debt import stopped_setup
from test_sheet_ops import Markup, content

from prechips.findings import Finding, exit_code
from prechips.inputs import Bundle, load_bundle
from prechips.model import TRAVELER_DETAILS
from prechips.report import build_report, canonical_bytes, render_assets
from prechips.rules import consistency, fixture_interference, hold_fields, inspection
from prechips.rules.resolution import op_check_targets, operation_members
from prechips.rules.zero_recipe import rule as zero_recipe
from prechips.sheet import _Traveler, finding_decision, render_traveler

EXAMPLE_WARNING = "EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT"
DETAIL_ERROR = "detail must be pro, hobby, or pedantic"


def bench_job():
    """A real, note-held inspection Bundle, without a native/browser dependency."""
    data = handling_bundle()
    data.plan.update(
        part="detail-boundary specimen",
        quantity=1,
        drawing={"number": "DETAIL-1", "revision": "A"},
        stock={
            "material": "steel",
            "form": "round_bar",
            "dia_mm": 12.7,
            "length_mm": 25.4,
            "on_hand": True,
        },
    )
    data.plan["setups"][0]["ops"] = [
        {"op": 10, "do": "inspect", "feature": "body", "checks": {"dia": "mic"}}
    ]
    data.inventory["gauges"] = {
        "mic": {
            "kind": "micrometer",
            "name": "Inspection micrometer",
            "range_mm": [0.0, 25.4],
            "resolution_mm": 0.001,
            "verify": False,
        }
    }
    return replace(
        data,
        features={
            "units": "mm",
            "precision": 3,
            "step_sha256": "a" * 64,
            "features": {"body": {"kind": "shaft", "requirements": ["dia"], "dia": [6.33, 6.35]}},
        },
        policy={"required": {"hold_fields": "*"}},
        root=Path("."),
        kernel={"status": "ok", "setups": {}, "ops": {}, "mapping": {}},
    )


def mill_job(tip_in=0.2, *, setups=2):
    """Use the existing finder rule fixture, but render an actual Bundle end to end."""
    source = mill_bundle(setups=setups)
    source.inventory["tools"]["finder"]["tip_in"] = tip_in
    source.plan["dro"].update(
        kind="digital",
        units="in",
        mode="abs",
        radius_mode=False,
        direction={"x": "right", "y": "away", "z": "up"},
    )
    source.plan.update(
        part="finder detail specimen",
        quantity=1,
        drawing={"number": "FINDER-1", "revision": "A"},
        stock={"material": "steel", "section_mm": [25.4, 12.7], "length_mm": 50.8},
    )
    for setup in source.plan["setups"]:
        for axis in ("x", "y", "z"):
            setup["zero"][axis]["check_jog_mm"] = 6.35
    return Bundle(
        plan=source.plan,
        features={**source.features, "precision": 3, "step_sha256": "b" * 64},
        inventory=source.inventory,
        policy={"required": {"zero_check": "*"}},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "setups": {}, "ops": {}, "mapping": {}},
    )


def rendered(data, findings=(), *, detail="hobby", approval=None):
    findings = list(findings)
    return render_traveler(data, findings, build_report(data, findings), approval, detail=detail)


def visible_text(html):
    markup = Markup(html)
    (body,) = [node for node in markup.nodes if node["tag"] == "body"]
    return " ".join(content(body).split())


def decision_evidence(node):
    """Read every original binding even when several facts share one visible notice."""
    attrs = node["attrs"]
    encoded = attrs.get("data-decision-evidence")
    if encoded is not None:
        return json.loads(encoded)
    return [
        {
            "source": attrs["data-source"],
            "status": attrs.get("data-status", ""),
            "scope": attrs["data-scope"],
            "kind": attrs["data-decision"],
        }
    ]


def decision_nodes(markup):
    return [
        node
        for node in markup.nodes
        if "decision" in node["attrs"].get("class", "").split()
        or "data-decision-evidence" in node["attrs"]
    ]


def decision_snapshot(html):
    """Compare complete typed evidence, not presentation-level notice duplication."""
    return sorted(
        {
            (entry["kind"], entry["source"], entry["status"], entry["scope"])
            for node in decision_nodes(Markup(html))
            for entry in decision_evidence(node)
        }
    )


def finding_nodes(markup, finding):
    return [
        node
        for node in decision_nodes(markup)
        if any(
            entry["source"] == finding.rule
            and entry["scope"] == finding.subject
            and entry["status"] in ("", str(finding.status))
            for entry in decision_evidence(node)
        )
    ]


def finding_has_kind(node, finding, kind):
    return any(
        entry["source"] == finding.rule
        and entry["scope"] == finding.subject
        and entry["status"] in ("", str(finding.status))
        and entry["kind"] == kind
        for entry in decision_evidence(node)
    )


def job_page(markup):
    (page,) = [node for node in markup.find("page") if node["attrs"].get("data-sheet") == "job"]
    return page


def approval_for(report):
    return {
        "approved": True,
        "hash": report["hash"],
        "first_article": "Synthetic approval fixture; not a physical inspection result",
    }


def release_banner(html):
    return " ".join(content(Markup(html).find("banner")[0]).split())


def numeric_values(text):
    return [
        float(value.replace("−", "-"))
        for value in re.findall(r"(?<![\w.])([+−-]?(?:\d+(?:\.\d+)?|\.\d+))", text)
    ]


def assert_number(text, expected):
    assert any(abs(value - expected) <= 0.0001 for value in numeric_values(text)), (
        expected,
        text,
    )


def assert_coordinate(text, axis, expected):
    # A sentence-ending period is punctuation, not a partial decimal or identifier.
    values = [
        float(value.replace("−", "-"))
        for value in re.findall(
            rf"(?<!\w){re.escape(axis)}\s*([+−-]?(?:\d+(?:\.\d+)?|\.\d+))(?!\w|\.[\w.])",
            text,
            re.IGNORECASE,
        )
    ]
    assert any(abs(value - expected) <= 0.0001 for value in values), (axis, expected, text)


def parallel_grip_values(text):
    """Read separately labelled physical lengths, independently of table/paragraph layout."""
    return [
        tuple(map(float, match))
        for match in re.findall(
            r"\bParallels\s+(\d+(?:\.\d+)?)\s+mm\b.*?"
            r"\bgrip\s+(\d+(?:\.\d+)?)\s+mm\b",
            " ".join(text.split()),
            re.IGNORECASE,
        )
    ]


def operation_owners(node):
    """Read physical operation identity without depending on its visual layout."""
    attrs = node["attrs"]
    if (
        "operation" in attrs.get("class", "").split()
        and "data-op" in attrs
        and "data-setup-id" in attrs
    ):
        return [
            {
                "setup_id": attrs["data-setup-id"],
                "op_id": attrs["data-op"],
                "workpiece": attrs.get("data-workpiece", ""),
            }
        ]
    owners = json.loads(attrs.get("data-physical-ops", "[]"))
    return [owner for owner in owners if isinstance(owner, dict) and owner.get("op_id") is not None]


def operation_nodes(markup, within=None):
    return [
        node
        for node in (markup.nodes if within is None else descendants(markup, within))
        if operation_owners(node)
    ]


def descendants(markup, owner):
    for node in markup.nodes:
        parent = node["parent"]
        while parent is not None:
            if parent is owner:
                yield node
                break
            parent = parent["parent"]


def operation_owner(node):
    while node is not None:
        if operation_owners(node):
            return node
        node = node["parent"]
    return None


def assert_displayed_block(markup, owner, message):
    """Check the notice, not the ledger wrapper that aggregates its evidence."""
    if "data-decision" in owner["attrs"]:
        assert owner["attrs"]["data-decision"] == "block"
        assert "stop" in owner["attrs"]["class"].split()
        assert "caution" not in owner["attrs"]["class"].split()
    else:
        assert "operation" in owner["attrs"]["class"].split()
        (notice,) = [node for node in markup.find("box", owner) if message in content(node)]
        assert content(notice).strip() == f"STOP: {message}"


def test_public_default_is_hobby_while_private_composer_stays_pedantic():
    data = bench_job()
    exhaustive = "Explain the retained reference during training."
    data.plan["setups"][0]["note"] = [{"text": exhaustive, "detail": "pedantic"}]
    findings = hold_fields.evaluate(data)
    report = build_report(data, findings)
    default = render_traveler(data, findings, report)
    assert default == render_traveler(data, findings, report, detail="hobby")
    private = _Traveler(data, findings, report, None)
    assert private.detail == "pedantic"
    pedantic = private.render()
    assert pedantic == render_traveler(data, findings, report, detail="pedantic")
    assert exhaustive not in visible_text(default)
    assert exhaustive in visible_text(pedantic)
    assert TRAVELER_DETAILS == ("pro", "hobby", "pedantic")
    markup = Markup(default)
    assert [node["attrs"].get("data-detail") for node in markup.nodes if node["tag"] == "body"] == [
        "hobby"
    ]
    assert [
        node["attrs"].get("content")
        for node in markup.nodes
        if node["tag"] == "meta" and node["attrs"].get("name") == "prechips-detail"
    ] == ["hobby"]


@pytest.mark.parametrize("invalid", [None, "", "professional", "Hobby", "hobby ", True, 0, [], {}])
def test_both_renderer_boundaries_refuse_invalid_detail_exactly(invalid):
    data = bench_job()
    with pytest.raises(ValueError, match=f"^{DETAIL_ERROR}$"):
        render_traveler(data, [], {}, detail=invalid)
    with pytest.raises(ValueError, match=f"^{DETAIL_ERROR}$"):
        _Traveler(data, [], {}, None, detail=invalid)
    with pytest.raises(TypeError):
        render_traveler(data, [], {}, None, "pro")


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_each_detail_is_byte_deterministic(detail):
    data = bench_job()
    data.plan["setups"][0]["note"] = [
        {"text": "Retain this reference for final inspection.", "detail": "pro"},
        {"text": "Clean seating surfaces before repeating the setup.", "detail": "hobby"},
    ]
    findings = hold_fields.evaluate(data)
    first = rendered(data, findings, detail=detail).encode("utf-8")
    second = rendered(data, findings, detail=detail).encode("utf-8")
    assert first == second
    markup = Markup(first.decode("utf-8"))
    assert len(markup.find("page")) == 1
    assert job_page(markup)["attrs"]["data-sheet"] == "job"


@pytest.mark.parametrize("approval_state", ["absent", "current", "stale", "unresolved"])
def test_levels_preserve_reports_findings_assets_exit_and_release(approval_state):
    data = bench_job()
    sid = data.plan["setups"][0]["id"]
    png = _png((80, 100, 120))
    data.kernel["setups"][sid] = {
        "render_png_base64": base64.b64encode(png).decode("ascii"),
        "fixture_rendered": True,
        "render_scene": {
            "width_px": 1,
            "height_px": 1,
            "print_panels": [
                {
                    "id": "setup",
                    "selection_group": "setup",
                    "annotations": [],
                    "role": "setup",
                    "label": "Synthetic asset-binding fixture",
                    "top_px": 0,
                    "height_px": 1,
                }
            ],
        },
    }
    if approval_state == "unresolved":
        data.plan["setups"][0]["hold"]["note"] = "unknown"
    findings = hold_fields.evaluate(data)
    assets = render_assets(data)
    assert assets and png in assets.values()
    report = build_report(data, findings, assets=assets)
    approval = None if approval_state == "absent" else approval_for(report)
    if approval_state == "stale":
        approval["hash"] = "f" * 64
    before = deepcopy(
        (data.plan, data.features, data.inventory, data.kernel, findings, report, approval)
    )
    expected_report = canonical_bytes(report)
    expected_findings = [finding.to_dict() for finding in findings]
    outputs = {}
    for detail in TRAVELER_DETAILS:
        html = render_traveler(data, findings, report, approval, detail=detail)
        outputs[detail] = html
        assert canonical_bytes(build_report(data, findings)) == expected_report
        assert render_assets(data) == assets
        assert [finding.to_dict() for finding in findings] == expected_findings
        assert exit_code(findings, data.policy, data) == report["expected_exit"]
        assert ("CHECKED" in release_banner(html)) is (approval_state == "current")
        if approval_state != "current":
            assert "PLANNED" in release_banner(html)
        report_meta = [
            node["attrs"].get("content")
            for node in Markup(html).nodes
            if node["tag"] == "meta" and node["attrs"].get("name") == "prechips-report"
        ]
        assert report_meta == [report["hash"]]
    assert len(set(outputs.values())) == len(TRAVELER_DETAILS)
    assert (
        data.plan,
        data.features,
        data.inventory,
        data.kernel,
        findings,
        report,
        approval,
    ) == before


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_note_audiences_apply_at_setup_hold_and_operation_without_changing_source(detail):
    data = bench_job()
    setup = data.plan["setups"][0]
    notes = {}
    for owner, target in (
        ("setup", setup),
        ("hold", setup["hold"]),
        ("operation", setup["ops"][0]),
    ):
        notes[owner] = [
            {"text": f"Keep the {owner} reference identified.", "detail": "pro"},
            {"text": f"Clean the {owner} reference before seating.", "detail": "hobby"},
            {"text": f"Explain the {owner} reference during training.", "detail": "pedantic"},
        ]
        target["note"] = deepcopy(notes[owner])
    original = deepcopy(data.plan)
    text = visible_text(rendered(data, detail=detail))
    rank = TRAVELER_DETAILS.index(detail)
    for segments in notes.values():
        for segment in segments:
            assert (segment["text"] in text) is (TRAVELER_DETAILS.index(segment["detail"]) <= rank)
    assert data.plan == original


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_existing_string_notes_remain_core_at_all_three_owners(detail):
    data = bench_job()
    setup = data.plan["setups"][0]
    notes = [
        (setup, "Keep the setup reference visibly labelled."),
        (setup["hold"], "Support on the clean pad and turn by hand for inspection."),
        (setup["ops"][0], "Keep the original drawing beside the inspection gauge."),
    ]
    for target, text in notes:
        target["note"] = text
    text = visible_text(rendered(data, detail=detail))
    assert all(note in text for _, note in notes)


@pytest.mark.parametrize("with_instruction_note", [False, True])
def test_segmented_bench_handling_is_validated_from_full_input_not_the_audience_projection(
    with_instruction_note,
):
    data = bench_job()
    setup = data.plan["setups"][0]
    concise = "Support the part on the clean pad for inspection."
    exhaustive = "Turn the part by hand while retaining support under the finished surface."
    setup["hold"] = {"note": [{"text": exhaustive, "detail": "pedantic"}]}
    if with_instruction_note:
        setup["ops"][0]["note"] = [{"text": concise, "detail": "pro"}]
    findings = hold_fields.evaluate(data)
    assert len(findings) == 1 and findings[0].status == "pass"
    assert findings[0].numbers["hold"]["note"] == setup["hold"]["note"]
    decisions = []
    for detail in TRAVELER_DETAILS:
        html = rendered(data, findings, detail=detail)
        text = visible_text(html)
        expected = concise if with_instruction_note else setup["ops"][0]["do"]
        assert any(
            expected.casefold() in content(action).casefold()
            for action in operation_nodes(Markup(html))
        )
        assert (exhaustive in text) is (detail == "pedantic")
        decisions.append(decision_snapshot(html))
    assert decisions[0] == decisions[1] == decisions[2]


def test_hidden_contradictory_note_still_reaches_consistency_and_blocks_every_level():
    data = bench_job()
    setup = data.plan["setups"][0]
    contradiction = "Use the same chucking as S0; do not loosen the jaws."
    setup["note"] = [
        {"text": "Retain the labelled reference through inspection.", "detail": "pro"},
        {"text": contradiction, "detail": "pedantic"},
    ]
    assert contradiction not in visible_text(rendered(data, detail="pro"))
    findings = consistency.evaluate(data)
    (adverse,) = [finding for finding in findings if finding.subject == setup["id"]]
    assert adverse.status == "error"
    assert "keep_clamped" in adverse.sentence
    assert build_report(data, findings)["expected_exit"] == 2
    for detail in TRAVELER_DETAILS:
        markup = Markup(rendered(data, findings, detail=detail))
        nodes = finding_nodes(markup, adverse)
        assert nodes and all(finding_has_kind(node, adverse, "block") for node in nodes)


def test_instruction_text_does_not_manufacture_a_typed_stop():
    data = bench_job()
    findings = hold_fields.evaluate(data)
    before = {
        detail: decision_snapshot(rendered(data, findings, detail=detail))
        for detail in TRAVELER_DETAILS
    }
    instruction = "STOP: stop the spindle before placing the inspection gauge against the work."
    data.plan["setups"][0]["ops"][0]["note"] = [{"text": instruction, "detail": "pedantic"}]
    for detail in TRAVELER_DETAILS:
        html = rendered(data, findings, detail=detail)
        assert (instruction in visible_text(html)) is (detail == "pedantic")
        assert decision_snapshot(html) == before[detail]


@pytest.mark.parametrize(
    ("status", "required", "numbers", "expected"),
    [
        ("error", False, {}, "block"),
        ("unknown", False, {"kernel_unavailable": True}, "block"),
        ("warn", True, {}, "block"),
        ("unknown", True, {}, "block"),
        ("unsupported", True, {}, "block"),
        ("warn", False, {}, "caution"),
        ("unknown", False, {}, "caution"),
        ("unsupported", False, {}, "caution"),
        ("pass", True, {}, "none"),
        ("not_applicable", True, {}, "none"),
        ("info", False, {}, "none"),
    ],
)
def test_finding_decisions_follow_status_requiredness_and_evidence_not_words(
    status, required, numbers, expected
):
    data = bench_job()
    data.policy["required"] = {"reach": "*"} if required else {}
    finding = Finding("reach", "B1:10", status, numbers, [], "STOP is merely a quoted instruction")
    assert finding_decision(finding, data) == expected
    assert finding_decision(replace(finding, sentence="Neutral description"), data) == expected


@pytest.mark.parametrize("status", ["warn", "unknown", "unsupported"])
def test_required_and_optional_adverse_findings_keep_their_decisions_and_owner_across_levels(
    status,
):
    data = bench_job()
    sid = data.plan["setups"][0]["id"]
    data.policy["required"] = {"reach": "*"}
    required = Finding("reach", f"{sid}:10", status, {}, [], "Required clearance is unresolved")
    optional = Finding("thin_wall_under_clamp", sid, status, {}, [], "Review optional wall margin")
    error = Finding("tool_resolves", f"{sid}:10", "error", {}, [], "Selected gauge is unavailable")
    findings = [required, optional, error]
    snapshots = []
    for detail in TRAVELER_DETAILS:
        html = rendered(data, findings, detail=detail)
        markup = Markup(html)
        for finding, expected in ((required, "block"), (optional, "caution"), (error, "block")):
            nodes = finding_nodes(markup, finding)
            assert nodes and all(finding_has_kind(node, finding, expected) for node in nodes)
            assert all(content(node).strip() for node in nodes)
        snapshots.append(decision_snapshot(html))
    assert snapshots[0] == snapshots[1] == snapshots[2]


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_missing_drawing_requirements_stay_visible_without_acquiring_a_result(detail):
    data = bench_job()
    setup = data.plan["setups"][0]
    setup["ops"][0]["missing_requirements"] = {"depth": "mic"}
    data.policy["required"] = {"inspection": "*"}
    findings = inspection.evaluate(data)
    (missing,) = [finding for finding in findings if finding.numbers.get("missing_requirement")]
    assert missing.status == "unknown" and missing.numbers["limits"] == "unknown"
    report = build_report(data, findings)
    assert report["expected_exit"] == 4
    markup = Markup(render_traveler(data, findings, report, detail=detail))
    nodes = finding_nodes(markup, missing)
    assert nodes and all(finding_has_kind(node, missing, "block") for node in nodes)
    assert "depth" in content(job_page(markup)).lower()
    identities = [
        identity
        for record in [*markup.find("inspection-record"), *markup.find("checkpoint-result")]
        for identity in json.loads(record["attrs"]["data-inspection-ids"])
    ]
    assert missing.subject not in identities
    (criterion,) = [
        node
        for node in markup.find("inspection-criterion")
        if missing.subject in json.loads(node["attrs"]["data-inspection-ids"])
    ]
    text = content(criterion).casefold()
    assert all(word in text for word in ("body", "depth", "?"))
    assert not markup.find("writing-blank", criterion)
    assert any("body:dia" == identity for identity in identities)
    text = visible_text(render_traveler(data, findings, report, detail=detail))
    assert_number(text, data.features["features"]["body"]["dia"][0])
    assert_number(text, data.features["features"]["body"]["dia"][1])


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_levels_keep_authored_execution_readings_but_not_generated_operation_paperwork(
    detail,
):
    data = bench_job()
    setup = data.plan["setups"][0]
    setup["ops"][0]["inspection_methods"] = {
        "dia": [
            "Read at the north station {north_reading} and south station {south_reading}.",
            "Calculate: mean = (north_reading + south_reading) / 2 = {mean}",
        ]
    }
    markup = Markup(rendered(data, detail=detail))
    methods = markup.find("inspection-method")
    assert methods
    fields = [field for method in methods for field in markup.find("field", method)]
    assert len(fields) == 3
    for field in fields:
        (blank,) = markup.find("writing-blank", field)
        assert content(blank) == ""
        owner = operation_owner(field)
        assert owner is not None
        owners = operation_owners(owner)
        assert len(owners) == 1
        assert owners[0]["setup_id"] == setup["id"]
        assert str(owners[0]["op_id"]) == str(setup["ops"][0]["op"])
    assert len(markup.find("writing-blank")) == len(fields)
    assert not markup.find("checkpoint-result")
    assert any("Calculate:" in content(method) and "mean" in content(method) for method in methods)
    records = [node for node in markup.nodes if "data-inspection-ids" in node["attrs"]]
    assert any(
        "body:dia" in json.loads(record["attrs"]["data-inspection-ids"]) for record in records
    )
    assert not markup.find("performed-mark")
    assert not markup.find("signoff")
    assert not re.search(r"\?M\d+\b", content(job_page(markup)))


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_demonstration_disclosure_is_first_and_retained_for_continuations_independent_of_approval(
    approved, detail
):
    data = bench_job()
    findings = hold_fields.evaluate(data)
    shop_report = build_report(data, findings)
    shop_approval = approval_for(shop_report) if approved else None
    shop_html = render_traveler(data, findings, shop_report, shop_approval, detail=detail)
    data.plan["purpose"] = "demonstration"
    report = build_report(data, findings)
    assert report["purpose"] == "demonstration"
    assert {key: value for key, value in report.items() if key not in {"hash", "purpose"}} == {
        key: value for key, value in shop_report.items() if key != "hash"
    }
    html = render_traveler(
        data, findings, report, approval_for(report) if approved else None, detail=detail
    )
    markup = Markup(html)
    assert content(markup.find("banner")[0]).strip().startswith(EXAMPLE_WARNING)
    page = job_page(markup)
    assert page["attrs"].get("data-example-only") == "true"
    assert page["attrs"].get("data-continuation-label") == "EXAMPLE ONLY"
    assert ("CHECKED" in release_banner(html)) is approved
    assert ("CHECKED" in release_banner(shop_html)) is approved
    assert decision_snapshot(html) == decision_snapshot(shop_html)
    if not approved:
        assert "PLANNED" in release_banner(html)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_demonstration_does_not_waive_a_missing_finder_fact_or_geometric_collision(
    tmp_path, detail
):
    data = mill_job(setups=1)
    data.plan["purpose"] = "demonstration"
    del data.inventory["tools"]["finder"]["tip_in"]
    findings = zero_recipe.evaluate(data)
    assert findings[0].status == "unknown"
    report = build_report(data, findings)
    assert report["expected_exit"] == 4 and report["verification"] == "planned"
    html = render_traveler(data, findings, report, approval_for(report), detail=detail)
    assert "PLANNED" in release_banner(html) and "CHECKED" not in release_banner(html)
    assert finding_nodes(Markup(html), findings[0])

    collision = rules_bundle(tmp_path)
    collision.plan["purpose"] = "demonstration"
    collision.kernel["setups"]["S1"]["fixture_clashes"] = ["vise jaw intersects stock"]
    findings = fixture_interference.evaluate(collision)
    assert any(finding.status == "error" for finding in findings)
    report = build_report(collision, findings)
    assert report["expected_exit"] == 2
    html = render_traveler(collision, findings, report, approval_for(report), detail=detail)
    assert "PLANNED" in release_banner(html) and "CHECKED" not in release_banner(html)
    for finding in findings:
        if finding.status == "error":
            nodes = finding_nodes(Markup(html), finding)
            assert nodes and all(finding_has_kind(node, finding, "block") for node in nodes)


@pytest.mark.parametrize("tip_in", [0.2, 0.24, 0.312])
def test_hobby_first_use_dro_guide_uses_the_evaluated_finder_not_example_answers(tip_in):
    data = mill_job(tip_in)
    data.inventory["tools"]["finder"]["name"] = "Selected mechanical finder"
    findings = zero_recipe.evaluate(data)
    assert findings[0].status == "pass"
    finder = findings[0].numbers["axes"]["x"]["finder"]
    radius_in = finder["radius_mm"] / 25.4
    assert radius_in == pytest.approx(tip_in / 2)
    for detail in ("hobby", "pedantic"):
        markup = Markup(rendered(data, findings, detail=detail))
        (guide,) = markup.find("dro-guide")
        text = " ".join(content(guide).split())
        assert all(
            concept.casefold() in text.casefold()
            for concept in ("ABS", "Axis Set", "Preset", "midpoint")
        )
        for value in (tip_in, radius_in, -radius_in, 1000, 6.35 / 25.4):
            assert_number(text, value)
        paper_in = data.plan["setups"][0]["zero"]["z"]["paper_mm"] / 25.4
        assert_number(text, paper_in)
    pro = Markup(rendered(data, findings, detail="pro"))
    assert not pro.find("dro-guide")
    (identity,) = pro.find("finder-identity")
    assert "Selected mechanical finder" in content(identity)
    assert_coordinate(content(identity), "Ø", tip_in)
    assert "Preset" not in content(identity) and "midpoint" not in content(identity)


def datum_sharing_job():
    """Three authored stages with equal physical references, not a layout-family fixture."""
    from test_envelope_m5 import measured

    data = mill_job(setups=3)
    data.features["frames"]["F"].update(
        origin=[0.0, 0.0, 0.0],
        x=[1.0, 0.0, 0.0],
        y=[0.0, 1.0, 0.0],
        z=[0.0, 0.0, 1.0],
    )
    data.inventory["fixtures"] = {
        "vise": {"kind": "vise", "name": "Datum vise"},
        "parallel-pair": {"kind": "parallels", "height_mm": measured(12.7)},
    }
    data.inventory["tools"]["finder"]["name"] = "Qualified finder"
    for index, setup in enumerate(data.plan["setups"]):
        setup["presentation_group"] = f"stage-{index + 1}"
        setup["note"] = "Keep the marked face uppermost"
        setup["hold"] = {
            "fixture": "vise",
            "parallels": "parallel-pair",
            "grip_mm": 7.62,
            "clamp": "Seat stock firmly against the stop",
        }
        setup["zero"]["x"].update(
            edge="Primer left reference" if index == 0 else "Shared left reference",
            edge_mm=19.05,
        )
    return data


def datum_sharing_output(data, findings, detail):
    markup = Markup(rendered(data, findings, detail=detail))
    shared = [
        node
        for node in markup.nodes
        if node["attrs"].get("data-reference-kind") == "datum"
        and "shared left reference" in content(node).casefold()
    ]
    flows = {
        member: node
        for node in markup.nodes
        if node["tag"] == "section"
        and {"setup-flow", "setup-family"} & set(node["attrs"].get("class", "").split())
        for member in json.loads(node["attrs"]["data-setup-members"])
    }
    assert flows.keys() == {"S1", "S2", "S3"}
    return markup, shared, flows


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_equal_proved_references_print_once_with_exact_physical_setup_owners(detail):
    data = datum_sharing_job()
    findings = zero_recipe.evaluate(data)
    assert [(finding.subject, finding.status) for finding in findings] == [
        ("S1", "pass"),
        ("S2", "pass"),
        ("S3", "pass"),
    ]
    # 0.750-inch edge minus the independently specified 0.100-inch finder radius.
    assert all(
        finding.numbers["axes"]["x"]["axis_set"] == pytest.approx(16.51) for finding in findings
    )
    markup, shared, flows = datum_sharing_output(data, findings, detail)
    (reference,) = shared
    assert json.loads(reference["attrs"]["data-setup-members"]) == ["S2", "S3"]
    assert_coordinate(content(reference), "x", 0.75)
    assert content(job_page(markup)).casefold().count("shared left reference") == 1
    assert all(
        "shared left reference" not in content(flows[sid]).casefold() for sid in ("S2", "S3")
    )
    holding = [
        node
        for node in markup.nodes
        if node["attrs"].get("data-reference-kind") == "holding"
        and parallel_grip_values(content(node))
    ]
    (parallel_reference,) = holding
    assert json.loads(parallel_reference["attrs"]["data-setup-members"]) == ["S1", "S2", "S3"]
    assert parallel_grip_values(content(parallel_reference)) == [(12.7, 7.62)]
    assert parallel_grip_values(content(job_page(markup))) == [(12.7, 7.62)]
    clamps = [
        node
        for node in markup.nodes
        if node["attrs"].get("data-reference-kind") == "holding"
        and "seat stock firmly against the stop" in content(node).casefold()
    ]
    (clamp_reference,) = clamps
    assert json.loads(clamp_reference["attrs"]["data-setup-members"]) == ["S1", "S2", "S3"]
    assert content(job_page(markup)).casefold().count("seat stock firmly against the stop") == 1
    orientations = [
        node
        for node in markup.nodes
        if node["attrs"].get("data-reference-kind") == "orientation"
        and "keep the marked face uppermost" in content(node).casefold()
    ]
    (orientation,) = orientations
    assert json.loads(orientation["attrs"]["data-setup-members"]) == ["S1", "S2", "S3"]
    assert content(job_page(markup)).casefold().count("keep the marked face uppermost") == 1
    assert {
        (owner["setup_id"], str(owner["op_id"]))
        for node in markup.nodes
        for owner in operation_owners(node)
    } == {("S1", "10"), ("S2", "10"), ("S3", "10")}


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize(
    "difference", ["frame", "incomplete_frame", "reference", "mount", "status"]
)
def test_equal_numbers_do_not_share_references_with_different_physical_evidence(detail, difference):
    data = datum_sharing_job()
    third = data.plan["setups"][2]
    if difference == "frame":
        data.features["frames"]["other-frame"] = deepcopy(data.features["frames"]["F"])
        third["frame"] = "other-frame"
    elif difference == "incomplete_frame":
        data.features["frames"]["other-frame"] = {"binding": "nominal"}
        third["frame"] = "other-frame"
    elif difference == "reference":
        data.inventory["tools"]["other-finder"] = deepcopy(data.inventory["tools"]["finder"])
        third["zero"]["x"]["tool"] = "other-finder"
    elif difference == "mount":
        data.inventory["fixtures"]["other-vise"] = deepcopy(data.inventory["fixtures"]["vise"])
        third["hold"]["fixture"] = "other-vise"
    findings = zero_recipe.evaluate(data)
    assert all(finding.status == "pass" for finding in findings)
    assert all(
        finding.numbers["axes"]["x"]["axis_set"] == pytest.approx(16.51) for finding in findings
    )
    if difference == "status":
        findings = [
            replace(finding, status="unknown") if finding.subject == "S3" else finding
            for finding in findings
        ]
    markup, shared, flows = datum_sharing_output(data, findings, detail)
    assert not shared
    for sid in ("S2", "S3"):
        text = content(flows[sid])
        assert "shared left reference" in text.casefold()
        assert_coordinate(text, "x", 0.75)
    if difference in ("frame", "incomplete_frame", "mount"):
        orientations = [
            node
            for node in markup.nodes
            if node["attrs"].get("data-reference-kind") == "orientation"
            and "keep the marked face uppermost" in content(node).casefold()
        ]
        (orientation,) = orientations
        assert json.loads(orientation["attrs"]["data-setup-members"]) == ["S1", "S2"]
        assert "keep the marked face uppermost" in content(flows["S3"]).casefold()
        assert content(job_page(markup)).casefold().count("keep the marked face uppermost") == 2
    if difference == "status":
        (unresolved,) = [finding for finding in findings if finding.subject == "S3"]
        notices = finding_nodes(markup, unresolved)
        assert notices and all(finding_has_kind(node, unresolved, "block") for node in notices)


@pytest.mark.parametrize("reading_location", ["axis", "note"])
@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_authored_contact_readings_stay_at_each_physical_setup(detail, reading_location):
    data = datum_sharing_job()
    for setup in data.plan["setups"][1:]:
        if reading_location == "axis":
            setup["zero"]["x"]["procedure"] = "Record {contact} before zeroing."
        else:
            setup["note"] = "Record {contact} before zeroing."
    findings = zero_recipe.evaluate(data)
    assert all(finding.status == "pass" for finding in findings)
    markup, shared, flows = datum_sharing_output(data, findings, detail)
    assert not shared
    fields = [
        node
        for node in markup.find("field")
        if [content(label) for label in markup.find("field-label", node)] == ["contact"]
    ]
    assert len(fields) == 2
    for sid in ("S2", "S3"):
        local = markup.find("field", flows[sid])
        assert len(local) == 1 and local[0] in fields
        (blank,) = markup.find("writing-blank", local[0])
        assert content(blank) == ""
        assert "shared left reference" in content(flows[sid]).casefold()


@pytest.mark.parametrize("problem", ["missing_tip", "out_of_range"])
@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_finder_safety_facts_remain_visible_when_the_tutorial_is_omitted(problem, detail):
    data = mill_job(setups=1)
    if problem == "missing_tip":
        del data.inventory["tools"]["finder"]["tip_in"]
    else:
        data.inventory["machines"]["mill"]["spindle"] = {"rpm_min": 50, "rpm_max": 900}
    findings = zero_recipe.evaluate(data)
    finding = findings[0]
    assert finding.status == ("unknown" if problem == "missing_tip" else "error")
    markup = Markup(rendered(data, findings, detail=detail))
    decisions = finding_nodes(markup, finding)
    assert decisions and all(finding_has_kind(node, finding, "block") for node in decisions)
    text = content(job_page(markup)).lower()
    assert "finder" in text
    assert ("tip" in text) if problem == "missing_tip" else ("rpm" in text)
    if problem == "out_of_range":
        assert_number(text, data.inventory["machines"]["mill"]["spindle"]["rpm_max"])


def test_compact_projection_hides_acquisition_paperwork_not_consumed_unknowns_or_operating_values():
    data, findings, cutter, lead = stopped_setup()
    data.policy["required"] = {"coordinates": "*", "blind_depth": "*", "speeds_feeds": "*"}
    original = deepcopy([finding.to_dict() for finding in findings])
    snapshots = []
    for detail in TRAVELER_DETAILS:
        html = rendered(data, findings, detail=detail)
        markup = Markup(html)
        snapshots.append(decision_snapshot(html))
        acquisition = [
            node["attrs"]["data-measurement-id"]
            for node in markup.nodes
            if "data-measurement-id" in node["attrs"]
        ]
        if detail == "pedantic":
            assert acquisition.count(cutter["id"]) == 1
            assert acquisition.count(lead["id"]) == 1
        else:
            assert not acquisition
            assert not re.search(r"\?M\d+\b", content(job_page(markup)))
        for finding in findings:
            if finding.status == "unknown":
                nodes = finding_nodes(markup, finding)
                assert nodes and all(finding_has_kind(node, finding, "block") for node in nodes)
        operations = {}
        for node in operation_nodes(markup):
            for op_id in {str(owner["op_id"]) for owner in operation_owners(node)}:
                operations.setdefault(op_id, []).append(node)
        assert {"10", "20", "30", "40", "50"} <= operations.keys()
        assert any("?" in content(node) for node in operations["10"])
        assert_number(" ".join(content(node) for node in operations["50"]), -1.5)
        if detail == "pedantic":
            for name, value in (("speed", 500), ("feed", 25)):
                fields = {
                    id(field): field
                    for node in operations["50"]
                    for field in markup.find(f"op-{name}", node)
                }
                (field,) = fields.values()
                (cell,) = [
                    node for node in markup.nodes if node["tag"] == "dd" and node["parent"] is field
                ]
                assert_number(content(cell), value)
        else:
            owner = f"{data.plan['setups'][0]['id']}:50"
            (settings,) = [
                node
                for node in markup.nodes
                if owner in json.loads(node["attrs"].get("data-physical-ops", "[]"))
            ]
            for value in (500, 25):
                assert_number(content(settings), value)
    assert [finding.to_dict() for finding in findings] == original
    assert snapshots[0] == snapshots[1] == snapshots[2]


def inspection_family_job():
    """Keep the real partition graph while composing the final inspection family."""
    original, section, finals = inspection_job()
    data = original.bundle
    data.inventory["machines"] = {"inspection-bench": {"kind": "bench", "name": "Inspection bench"}}
    for setup in [section, *finals]:
        setup["machine"] = "inspection-bench"
        setup["hold"] = {"note": "Support the part on the clean pad and turn it by hand."}
    for setup in finals:
        setup["presentation_group"] = "Final acceptance"
    return data, section, finals


def milling_family_job():
    """Physical descendants share a real tool/fixture, not a prototype setup."""
    source = rules_bundle(Path("."))
    template = deepcopy(source.plan["setups"][0])
    plan = batch()
    plan["dro"] = {
        "kind": "digital",
        "units": "mm",
        "mode": "abs",
        "direction": {"x": "right", "y": "away", "z": "up"},
    }
    finals = plan["setups"][-4:]
    findings = []
    kernel = deepcopy(source.kernel)
    kernel["setups"] = {}
    kernel["ops"] = {}
    for setup in finals:
        setup.update(
            machine=template["machine"],
            frame=template["frame"],
            presentation_group="Finish the four members",
            stock_state={"top_z": 0.0, "bottom_z": -8.0},
            hold=deepcopy(template["hold"]),
            coolant="none",
            ops=[
                {
                    **deepcopy(template["ops"][0]),
                    "to_z": -2.375,
                    "direction": "conventional",
                    "note": "Retain the stop while machining this face.",
                }
            ],
        )
        findings.append(
            Finding(
                "speeds_feeds",
                f"{setup['id']}:10",
                "pass",
                {"rpm": 1320.0, "feed_mm_min": 42.5},
                [],
                "Synthetic evaluated settings for the family projection regression",
            )
        )
        kernel["setups"][setup["id"]] = {"stock_bbox_mm": [-10, -5, -8, 10, 5, 0]}
    return replace(source, plan=plan, kernel=kernel), finals, findings


def collected_family(data, setups, findings=(), *, detail="hobby"):
    sheet = _Traveler(data, list(findings), build_report(data, list(findings)), None, detail=detail)
    blocks = {setup["id"]: sheet.setup_blocks(setup) for setup in setups}
    return sheet, blocks, Markup(sheet.family_html(setups, blocks))


def ancestor_with_class(node, css):
    while node is not None:
        if css in node["attrs"].get("class", "").split():
            return node
        node = node["parent"]
    return None


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_family_union_preserves_a_later_only_fact_and_member_caution(detail):
    data, _, finals = inspection_family_job()
    last = finals[-1]
    member = operation_members(data, last, last["ops"][0])[0]
    fact = "Retain 2.875 mm axial clearance at this member's inspection stop."
    last["note"] = [{"text": fact, "detail": "pro"}]
    caution = Finding(
        "reach",
        last["id"],
        "warn",
        {"clearance_mm": 2.875},
        [],
        "Review the clearance at this member's inspection stop",
    )
    data.policy["required"] = {}
    _, blocks, markup = collected_family(data, finals, [caution], detail=detail)
    assert "note" not in {block.key for block in blocks[finals[0]["id"]]}
    assert "note" in {block.key for block in blocks[last["id"]]}
    variants = [
        node
        for node in markup.find("setup-variant")
        if node["attrs"]["data-setup-id"] == last["id"]
    ]
    assert any(fact in content(node) for node in variants)
    assert all(node["attrs"]["data-workpiece"] == member for node in variants)
    nodes = finding_nodes(markup, caution)
    assert nodes and all(finding_has_kind(node, caution, "caution") for node in nodes)
    assert all(
        ancestor_with_class(node, "setup-variant")["attrs"]["data-setup-id"] == last["id"]
        for node in nodes
    )
    assert not any(fact in content(node) for node in markup.find("family-common"))


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_family_shares_identical_instructions_but_keeps_every_physical_checkpoint(detail):
    data, _, finals = inspection_family_job()
    _, _, markup = collected_family(data, finals, detail=detail)
    expected_owners = {
        (setup["id"], operation_members(data, setup, setup["ops"][0])[0]) for setup in finals
    }
    common = [
        node
        for node in markup.find("family-common")
        if {
            (owner["setup_id"], owner["workpiece"])
            for owner in json.loads(node["attrs"]["data-physical-ops"])
        }
        == expected_owners
        and operation_owners(node)
    ]
    assert len(common) == 1
    methods = markup.find("inspection-method", common[0])
    assert len(methods) == len(finals[0]["ops"][0]["inspection_methods"])
    assert all(content(method).strip() for method in methods)
    assert len(markup.find("checkpoint-result", common[0])) == len(expected_owners)
    criteria = markup.find("inspection-criterion", common[0])
    targets = [
        target for setup in finals for target in op_check_targets(data, setup, setup["ops"][0])
    ]
    expected_ids = {
        frozenset(
            target["subject"]
            for target in targets
            if target["identity"]["requirement"] == requirement
        )
        for requirement in {target["identity"]["requirement"] for target in targets}
    }
    assert {
        frozenset(json.loads(criterion["attrs"]["data-inspection-ids"])) for criterion in criteria
    } == expected_ids
    assert len(criteria) == len(expected_ids)
    for node in markup.find("checkpoint-result", common[0]):
        assert (node["attrs"]["data-setup-id"], node["attrs"]["data-workpiece"]) in expected_owners
        assert node["attrs"]["data-op-id"] == str(finals[0]["ops"][0]["op"])


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("changed_field", ["rpm", "feature", "fixture"])
def test_family_operative_differences_remain_named_member_variants(detail, changed_field):
    data, finals, findings = milling_family_job()
    last = finals[-1]
    member = operation_members(data, last, last["ops"][0])[0]
    if changed_field == "rpm":
        findings[-1] = replace(findings[-1], numbers={"rpm": 1740.0, "feed_mm_min": 42.5})
    elif changed_field == "feature":
        data.features["features"]["alternate_pocket"] = deepcopy(
            data.features["features"]["pocket"]
        )
        last["ops"][0]["feature"] = "alternate_pocket"
    else:
        data.inventory["fixtures"]["offset-vise"] = {
            **deepcopy(data.inventory["fixtures"]["vise"]),
            "name": "Offset soft-jaw vise",
        }
        last["hold"]["fixture"] = "offset-vise"
    sheet, blocks, markup = collected_family(data, finals, findings, detail=detail)
    key = "holding" if changed_field == "fixture" else "operation:10"
    first_block = next(block for block in blocks[finals[0]["id"]] if block.key == key)
    changed_block = next(block for block in blocks[last["id"]] if block.key == key)
    assert first_block.comparison != changed_block.comparison
    variants = [
        node
        for node in markup.find("setup-variant")
        if node["attrs"]["data-setup-id"] == last["id"]
        and node["attrs"]["data-workpiece"] == member
    ]
    assert variants
    if changed_field == "rpm":
        assert any(operation_nodes(markup, node) for node in variants)
        # The partition fixture's upstream nodes are graph placeholders, not
        # renderable setups. This private key covers the composed final family.
        sheet.plan = {**sheet.plan, "setups": finals}
        settings_markup = Markup(sheet.settings_key())
        settings = [node for node in settings_markup.nodes if "data-physical-ops" in node["attrs"]]
        owned = [
            node
            for node in settings
            if json.loads(node["attrs"]["data-physical-ops"]) == [f"{last['id']}:10"]
        ]
        assert len(owned) == 1
        assert_number(content(owned[0]), findings[-1].numbers["rpm"])
        unchanged = [
            node
            for node in settings
            if set(json.loads(node["attrs"]["data-physical-ops"]))
            == {f"{setup['id']}:10" for setup in finals[:-1]}
        ]
        assert len(unchanged) == 1
        assert_number(content(unchanged[0]), findings[0].numbers["rpm"])
    elif changed_field == "feature":
        expected = sheet.feature_label(last["ops"][0]["feature"], marked=False)
        assert any(expected in content(variant) for variant in variants)
        assert not any(expected in content(common) for common in markup.find("family-common"))
    else:
        fixture_name = data.inventory["fixtures"]["offset-vise"]["name"]
        assert any(fixture_name in content(variant) for variant in variants)
        assert not any(fixture_name in content(common) for common in markup.find("family-common"))


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_identical_authored_reading_prompts_are_never_shared_between_distinct_members(detail):
    data, _, finals = inspection_family_job()
    for setup in finals:
        setup["ops"][0]["inspection_methods"]["length"] = (
            "Measure this member's finished length: {finished_length}."
        )
    _, _, markup = collected_family(data, finals, detail=detail)
    fields = [
        blank
        for method in markup.find("inspection-method")
        for blank in markup.find("writing-blank", method)
    ]
    assert len(fields) == len(finals)
    observed = set()
    for blank in fields:
        variant = ancestor_with_class(blank, "setup-variant")
        assert variant is not None
        observed.add((variant["attrs"]["data-setup-id"], variant["attrs"]["data-workpiece"]))
        assert content(blank) == ""
        assert ancestor_with_class(blank, "family-common") is None
    assert observed == {
        (setup["id"], operation_members(data, setup, setup["ops"][0])[0]) for setup in finals
    }
    assert not any(
        markup.find("writing-blank", method)
        for common in markup.find("family-common")
        for method in markup.find("inspection-method", common)
    )


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_family_result_grid_keeps_one_batch_owner_and_four_distinct_final_owners(detail):
    data, section, finals = inspection_family_job()
    sheet = _Traveler(data, [], build_report(data, []), None, detail=detail)
    all_setups = [section, *finals]
    blocks = {setup["id"]: sheet.setup_blocks(setup) for setup in all_setups}
    markup = Markup(sheet.family_html([section], blocks) + sheet.family_html(finals, blocks))
    cells = markup.find("checkpoint-result")
    assert len(cells) == 1 + len(finals)
    batch_cells = [node for node in cells if node["attrs"]["data-shared-check"]]
    assert len(batch_cells) == 1
    batch_cell = batch_cells[0]
    batch_op = section["ops"][-1]
    assert batch_cell["attrs"]["data-workpiece"] == ""
    assert batch_cell["attrs"]["data-shared-check"] == f"{section['id']}:{batch_op['op']}"
    assert (
        json.loads(batch_cell["attrs"]["data-covered-workpieces"]) == batch_op["inspect_workpieces"]
    )
    assert set(json.loads(batch_cell["attrs"]["data-inspection-ids"])) == {
        target["subject"] for target in op_check_targets(data, section, batch_op)
    }
    final_cells = [node for node in cells if not node["attrs"]["data-shared-check"]]
    assert {
        (node["attrs"]["data-setup-id"], node["attrs"]["data-workpiece"]) for node in final_cells
    } == {(setup["id"], operation_members(data, setup, setup["ops"][0])[0]) for setup in finals}
    final_grid = final_cells[0]["parent"]
    assert final_grid in markup.find("checkpoint-results")
    assert all(node["parent"] is final_grid for node in final_cells)
    for setup in finals:
        (cell,) = [node for node in final_cells if node["attrs"]["data-setup-id"] == setup["id"]]
        assert set(json.loads(cell["attrs"]["data-inspection-ids"])) == {
            target["subject"] for target in op_check_targets(data, setup, setup["ops"][0])
        }
        assert json.loads(cell["attrs"]["data-covered-workpieces"]) == []
    for cell in cells:
        (blank,) = markup.find("writing-blank", cell)
        assert content(blank) == ""


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_human_heading_omits_drawing_identifiers_without_changing_raw_bindings(detail):
    data = bench_job()
    data.plan["part"] = "fixture-stop-plate"
    data.plan["drawing"] = {"number": "BOUND-DRAWING-731", "revision": "BOUND-REVISION-C"}
    markup = Markup(rendered(data, detail=detail))
    page = job_page(markup)
    (identity,) = markup.find("job-identity", page)
    (heading,) = [
        node
        for node in markup.nodes
        if node["parent"] is identity
        and " ".join(content(node).split()).casefold() == data.plan["part"].replace("-", " ")
    ]
    assert " ".join(content(heading).split()).casefold() == data.plan["part"].replace("-", " ")
    assert data.plan["drawing"]["number"] not in content(heading)
    assert data.plan["drawing"]["revision"] not in content(heading)
    assert data.plan["drawing"]["number"] in content(identity)
    assert data.plan["drawing"]["revision"] in content(identity)
    assert not re.search(r"(?:^|·)\s*(?:Pro|Hobby)\s*(?:·|$)", content(identity))
    assert page["attrs"]["data-part"] == data.plan["part"]
    assert page["attrs"]["data-drawing"] == data.plan["drawing"]["number"]
    assert page["attrs"]["data-revision"] == data.plan["drawing"]["revision"]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("manifest_units", ["mm", "in"])
@pytest.mark.parametrize("display_units", ["mm", "in", "unknown"])
def test_declared_mm_stock_dimensions_use_explicit_display_units_not_manifest_units(
    detail,
    manifest_units,
    display_units,
):
    data = mill_job(setups=1)
    data.features["units"] = manifest_units
    data.plan["dro"]["units"] = display_units
    data.plan["stock"] = {
        "material": "steel",
        "form": "flat_bar",
        "section_mm": [25.4, 15.875],
        "length_mm": 127.0,
        "on_hand": True,
    }
    markup = Markup(rendered(data, detail=detail))
    stock_lines = [
        node
        for node in markup.nodes
        if node["tag"] == "p" and "×" in content(node) and "stock" in content(node).casefold()
    ]
    assert len(stock_lines) == 1
    text = content(stock_lines[0])
    unit = "in" if display_units == "in" else "mm"
    scale = 25.4 if unit == "in" else 1.0
    declared = [*data.plan["stock"]["section_mm"], data.plan["stock"]["length_mm"]]
    assert numeric_values(text)[:3] == pytest.approx([value / scale for value in declared])
    assert re.search(rf"\b{unit}\b", text)
    assert data.plan["stock"]["section_mm"] == [25.4, 15.875]
    assert data.plan["stock"]["length_mm"] == 127.0


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("action", ["inspect", "finish_turn", "profile"])
def test_selected_numeric_acceptance_prints_once_at_its_physical_inspection_not_in_a_global_table(
    detail,
    action,
):
    data = bench_job()
    data.plan["setups"][0]["ops"][0]["do"] = action
    markup = Markup(rendered(data, detail=detail))
    band = data.features["features"]["body"]["dia"]

    def has_band(node):
        return all(
            any(abs(value - limit) <= 0.000001 for value in numeric_values(content(node)))
            for limit in band
        )

    criteria = [
        node
        for node in markup.nodes
        if operation_owner(node) is not None
        and has_band(node)
        and not any(has_band(child) for child in descendants(markup, node))
    ]
    assert len(criteria) == 1
    operation = operation_owner(criteria[0])
    assert operation is not None
    assert {(owner["setup_id"], str(owner["op_id"])) for owner in operation_owners(operation)} == {
        (data.plan["setups"][0]["id"], str(data.plan["setups"][0]["ops"][0]["op"]))
    }
    page_values = numeric_values(visible_text(rendered(data, detail=detail)))
    for limit in band:
        assert sum(abs(value - limit) <= 0.000001 for value in page_values) == 1


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_requirements_omit_empty_but_keep_debt_unassigned_limits_and_edges(
    detail,
):
    data = bench_job()
    data.features["features"].update(
        unusedsurface={"kind": "face", "requirements": []},
        unresolvedsurface={"kind": "face", "requirements": "unknown"},
        omittedsurface={"kind": "face"},
        unassignedshaft={"kind": "shaft", "requirements": ["dia"], "dia": [7.101, 7.109]},
    )
    edge_instruction = "Break every exposed edge to R0.187 mm maximum; retain bearing corners."
    data.features["notes"] = {"edge_break": edge_instruction}
    data.policy["required"] = {"inspection": "*"}
    findings = inspection.evaluate(data)
    markup = Markup(rendered(data, findings, detail=detail))
    text = content(job_page(markup))
    assert "unusedsurface" not in text
    assert all(name in text for name in ("unresolvedsurface", "omittedsurface", "unassignedshaft"))
    for limit in data.features["features"]["unassignedshaft"]["dia"]:
        assert_number(text, limit)
    assert text.count(edge_instruction) == 1
    for name in ("unresolvedsurface", "omittedsurface"):
        adverse = [
            finding
            for finding in findings
            if finding.subject == name or finding.subject.startswith(name + ":")
        ]
        assert adverse and any(finding.status == "unknown" for finding in adverse)
        for finding in adverse:
            if finding.status == "unknown":
                nodes = finding_nodes(markup, finding)
                assert nodes and all(finding_has_kind(node, finding, "block") for node in nodes)
    ids = [
        identity
        for node in markup.nodes
        if "data-inspection-ids" in node["attrs"]
        for identity in json.loads(node["attrs"]["data-inspection-ids"])
    ]
    assert not any(identity.startswith("unassignedshaft:") for identity in ids)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("status", ["warn", "unknown", "error"])
def test_identical_decisions_share_a_notice_per_owner_without_losing_source_status_or_scope(
    detail, status
):
    data = bench_job()
    first = data.plan["setups"][0]
    second = deepcopy(first)
    second["id"] = "B2"
    second["stock_in"] = first["id"]
    data.plan["setups"].append(second)
    data.policy["required"] = {} if status == "warn" else {"reach": "*", "accessibility": "*"}
    message = "Review the indicated clearance before proceeding."
    findings = [
        Finding(rule, f"{setup['id']}:{setup['ops'][0]['op']}", status, {}, [], message)
        for setup in (first, second)
        for rule in ("reach", "accessibility")
    ]
    markup = Markup(rendered(data, findings, detail=detail))
    for setup in (first, second):
        subject = f"{setup['id']}:{setup['ops'][0]['op']}"
        scoped = [finding for finding in findings if finding.subject == subject]
        owned = [
            node
            for node in decision_nodes(markup)
            if node["attrs"].get("data-op") == str(setup["ops"][0]["op"])
            and node["attrs"].get("data-setup-id") == setup["id"]
        ]
        assert len(owned) == 1
        notice = owned[0]
        expected_kind = "caution" if status == "warn" else "block"
        assert all(finding_has_kind(notice, finding, expected_kind) for finding in scoped)
        assert decision_evidence(notice) == [
            {
                "source": finding.rule,
                "status": status,
                "scope": subject,
                "kind": expected_kind,
            }
            for finding in sorted(scoped, key=lambda finding: (finding.rule, finding.subject))
        ]
        assert content(notice).count(message) == 1
    assert len(decision_snapshot(rendered(data, findings, detail=detail))) >= len(findings)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_same_text_different_statuses_keep_evidence_and_highest_operator_severity(detail):
    data = bench_job()
    sid = f"{data.plan['setups'][0]['id']}:{data.plan['setups'][0]['ops'][0]['op']}"
    data.policy["required"] = {"reach": "*", "accessibility": "*"}
    message = "Resolve this clearance before proceeding."
    unresolved = Finding("reach", sid, "unknown", {}, [], message)
    failed = Finding("accessibility", sid, "error", {}, [], message)
    markup = Markup(rendered(data, [unresolved, failed], detail=detail))
    operation = next(
        node
        for node in decision_nodes(markup)
        if finding_has_kind(node, unresolved, "block") and finding_has_kind(node, failed, "block")
    )
    assert content(operation).count(message) == 1
    assert_displayed_block(markup, operation, message)
    assert {
        (entry["source"], entry["status"], entry["scope"], entry["kind"])
        for entry in decision_evidence(operation)
    } >= {
        (unresolved.rule, str(unresolved.status), unresolved.subject, "block"),
        (failed.rule, str(failed.status), failed.subject, "block"),
    }


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_optional_warning_and_error_share_one_highest_severity_notice_with_both_bindings(detail):
    data = bench_job()
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    sid = f"{setup['id']}:{op['op']}"
    data.policy["required"] = {}
    message = "Resolve the selected assembly clearance before proceeding."
    optional = Finding("reach", sid, "warn", {}, [], message)
    failed = Finding("accessibility", sid, "error", {}, [], message)
    report = build_report(data, [optional, failed])
    assert report["expected_exit"] == 2
    markup = Markup(render_traveler(data, [optional, failed], report, detail=detail))
    notices = {
        id(node): node for finding in (optional, failed) for node in finding_nodes(markup, finding)
    }
    assert len(notices) == 1
    (notice,) = notices.values()
    assert notice["attrs"]["data-setup-id"] == setup["id"]
    assert notice["attrs"]["data-op"] == str(op["op"])
    assert_displayed_block(markup, notice, message)
    assert finding_has_kind(notice, optional, "caution")
    assert finding_has_kind(notice, failed, "block")
    assert {
        (entry["source"], entry["status"], entry["scope"], entry["kind"])
        for entry in decision_evidence(notice)
    } == {
        (optional.rule, str(optional.status), optional.subject, "caution"),
        (failed.rule, str(failed.status), failed.subject, "block"),
    }
    owner = ancestor_with_class(notice, "setup-variant")
    assert owner is not None and owner["attrs"]["data-setup-id"] == setup["id"]
    assert content(notice).count(message) == 1


@pytest.mark.parametrize(
    ("obstacle", "gap", "kind"),
    [
        ("jaw", 0.5, "caution"),
        ("jaw", -0.5, "block"),
        ("jaw", "unknown", "block"),
        ("tip", 0.5, "caution"),
        ("tip", -0.5, "block"),
        ("cut", 0.5, "caution"),
        ("cut", -0.5, "block"),
    ],
)
def test_clearance_decisions_render_known_gaps_as_cautions_and_collision_or_unknown_as_blocks(
    monkeypatch, obstacle, gap, kind
):
    from test_sheet_ops import SPOT, headroom, near_holding, shop

    from prechips.sheet import _typed_values

    if obstacle == "jaw":
        sheet = shop({}, kind="lathe")
        setup = SPOT
        sheet.jaw_front_z = lambda setup: 0.0
        sheet.lathe_approaches = lambda setup: {"60": gap}
        sheet.path_zs = lambda setup, op: []
        sheet.posed_start = lambda setup, op: None
    else:
        sheet, setup = near_holding(gap if obstacle == "cut" else 12.0)
        if obstacle == "tip":
            sheet.records[("headroom", "S1")] = headroom(tip_above_jaws=gap, jaw_top_z=-0.5 - gap)

    (box,) = sheet.crash_boxes(setup, setup["ops"][0])
    assert box.kind == kind
    if kind == "block":
        assert not box.notice_group
    if kind == "caution":
        assert box.status == "warn"

    data = bench_job()
    owner = data.plan["setups"][0]
    scope = f"{owner['id']}:{owner['ops'][0]['op']}"
    (decision,) = _typed_values([box], scope)
    operation_rows = _Traveler.operation_rows

    def with_clearance(self, setup, tools):
        rows = operation_rows(self, setup, tools)
        rows[0].decisions = (*rows[0].decisions, decision)
        return rows

    monkeypatch.setattr(_Traveler, "operation_rows", with_clearance)
    markup = Markup(rendered(data))
    evidence = {
        "source": decision.source,
        "status": decision.status,
        "scope": scope,
        "kind": kind,
    }
    (notice,) = [node for node in decision_nodes(markup) if evidence in decision_evidence(node)]
    assert notice["attrs"]["data-decision"] == kind
    assert ("stop" in notice["attrs"]["class"].split()) == (kind == "block")
    assert ("caution" in notice["attrs"]["class"].split()) == (kind == "caution")


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_tnut_final_family_keeps_every_size_method_and_typed_fit_clause(detail):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    finals = [setup for setup in data.plan["setups"] if setup["id"] in ("F1a", "F1b", "F1c", "F1d")]
    assert [setup["id"] for setup in finals] == ["F1a", "F1b", "F1c", "F1d"]
    sheet, _, markup = collected_family(data, finals, detail=detail)
    expected_owners = {
        ("F1a", "nut1"),
        ("F1b", "nut2"),
        ("F1c", "nut3"),
        ("F1d", "nut4"),
    }
    records = markup.find("checkpoint-result")
    assert len(records) == 4
    assert {
        (record["attrs"]["data-setup-id"], record["attrs"]["data-workpiece"]) for record in records
    } == expected_owners
    for record in records:
        assert record["attrs"]["data-op-id"] == "10"
        assert record["attrs"]["data-shared-check"] == ""
        assert json.loads(record["attrs"]["data-covered-workpieces"]) == []
        (blank,) = markup.find("writing-blank", record)
        assert content(blank) == ""
        member = record["attrs"]["data-workpiece"]
        assert set(json.loads(record["attrs"]["data-inspection-ids"])) == {
            f"{member}/base-envelope:width",
            f"{member}/base-envelope:height",
            f"{member}/shoulders:width",
            f"{member}/shoulders:thickness",
            f"{member}/end-length:length",
            f"{member}/part:actual_slot_fit",
            f"{member}/part:stud_retention",
        }
    for setup_id, member in expected_owners:
        setup = next(setup for setup in finals if setup["id"] == setup_id)
        (check,) = sheet.inspection(setup, setup["ops"][0])
        assert len(check.compact_criteria) == 7
        assert set(check.subjects) == {
            f"{member}/base-envelope:width",
            f"{member}/base-envelope:height",
            f"{member}/shoulders:width",
            f"{member}/shoulders:thickness",
            f"{member}/end-length:length",
            f"{member}/part:actual_slot_fit",
            f"{member}/part:stud_retention",
        }
        if detail != "pedantic":
            headings = [criterion.heading for _, _, criterion in check.compact_criteria]
            assert "end-length" in headings
            assert "end-length length" not in headings
        owned = [
            node
            for node in operation_nodes(markup)
            if any(
                owner["setup_id"] == setup_id
                and owner["workpiece"] == member
                and str(owner["op_id"]) == "10"
                for owner in operation_owners(node)
            )
        ]
        assert owned
        text = " ".join(" ".join(content(node).split()) for node in owned)
        # Method prose repeats sizes, so it cannot stand in for a dropped criterion.
        criteria_text = text
        for node in owned:
            for method in markup.find("inspection-method", node):
                criteria_text = criteria_text.replace(" ".join(content(method).split()), "")
        # Pedantic criteria use manifest millimetres; compact uses readout inches.
        # Keep independent inch limits, not values recovered from the checkpoint.
        scale = 25.4 if detail == "pedantic" else 1.0
        limits_text = re.sub(r"(?<=\d)[-–—…](?=[\d.])", " ", criteria_text)
        for band in (
            (0.873, 0.877),
            (0.498, 0.502),
            (0.248, 0.252),
            (0.493, 0.497),
            (0.998, 1.002),
        ):
            for limit in band:
                assert_number(limits_text, limit * scale)
        if detail != "pedantic":
            flange_methods = {
                id(method): method
                for node in owned
                for method in markup.find("inspection-method", node)
                if re.search(r"\bboth\b.*?\bflanges\b", content(method), re.IGNORECASE)
            }
            (method,) = flange_methods.values()
            paragraph = method["parent"]
            while paragraph is not None and paragraph["tag"] != "p":
                paragraph = paragraph["parent"]
            assert paragraph is not None
            local = " ".join(content(paragraph).split())
            band, _ = sheet.inspection_band("shoulders", "thickness")
            gauge = setup["ops"][0]["checks"]["shoulders"]["thickness"]
            assert band in local
            assert sheet.short_reference(gauge, "gauges") in local
            assert re.search(r"\bshoulders\b.*?\bthickness\b", local, re.IGNORECASE)
        # Method and criterion jointly express the physical fit procedure.
        # Numeric acceptance bands above must still survive without method prose.
        for relationship in (
            (
                r"(?:\bslides?\b.*?\bby hand\b|\bhand[- ]slides?\b)",
                r"\b(?:no|without) binding\b.*?\brocking\b.*?\bintended slot\b",
            ),
            (
                r"\bboth\b.*?\b(?:flange|shoulder) shelves\b.*?\bbear under\b.*?\blips\b",
                r"\b(?:no|without) bottoming\b.*?\bwedging\b",
            ),
            (r"\bpull(?:ed)?[ -]up\b", r"\btop\b.*?\bbelow\b.*?\btable\b"),
            (
                r"\bintended 3/8-16\b.*?\b(?:RH|right.hand) stud\b",
                r"(?:\b(?:insert stud|stud enters)\b.*?\bfrom\b.*?\btop by hand\b|"
                r"\bhand[- ]insert\b.*?\bstud\b.*?\bfrom\b.*?\btop\b)",
            ),
            (
                r"\bbottom.thread deformation\b.*?\bstops\b.*?\bstud\b.*?"
                r"\bbefore\b.*?\b(?:exit|exits)\b.*?\btable\b",
                r"\bdo not force\b.*?\bthrough\b",
            ),
            (
                r"\bnut\b.*?\b(?:does not|neither) rotates?\b.*?"
                r"\b(?:or|nor) pass(?:es)? through\b.*?\bintended slot\b",
            ),
        ):
            assert all(re.search(clause, text, re.IGNORECASE) for clause in relationship), (
                relationship,
                text,
            )


def terminal_inspection_job():
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    finals = data.plan["setups"][-4:]
    assert [setup["id"] for setup in finals] == ["F1a", "F1b", "F1c", "F1d"]
    return data, finals


def assert_terminal_inspection_route(markup, data, *, deferred):
    """Compare authored physical setup/op order, not paragraph or table layout."""
    flows = [
        node
        for node in markup.nodes
        if node["tag"] == "section"
        and {"setup-flow", "setup-family"} & set(node["attrs"].get("class", "").split())
    ]
    owners = {
        sid: flow for flow in flows for sid in json.loads(flow["attrs"]["data-setup-members"])
    }
    authored = [setup["id"] for setup in data.plan["setups"]]
    displayed = [sid for flow in flows for sid in json.loads(flow["attrs"]["data-setup-members"])]
    assert displayed == (authored[-4:] + authored[:-4] if deferred else authored)
    for setup in data.plan["setups"]:
        sid = setup["id"]
        physical_ops = list(
            dict.fromkeys(
                str(owner["op_id"])
                for node in operation_nodes(markup, owners[sid])
                for owner in operation_owners(node)
                if owner["setup_id"] == sid
            )
        )
        assert physical_ops == [str(op["op"]) for op in setup["ops"]], sid
    return owners


def assert_terminal_results(markup, *, reading_owned=False):
    finals = {"F1a": "nut1", "F1b": "nut2", "F1c": "nut3", "F1d": "nut4"}
    records = [
        node
        for node in markup.find("checkpoint-result")
        if node["attrs"]["data-setup-id"] in finals
    ]
    expected = (
        finals if not reading_owned else {sid: nut for sid, nut in finals.items() if sid != "F1a"}
    )
    assert {
        (record["attrs"]["data-setup-id"], record["attrs"]["data-workpiece"]) for record in records
    } == set(expected.items())
    assert len(records) == len(expected)
    for record in records:
        member = record["attrs"]["data-workpiece"]
        assert record["attrs"]["data-op-id"] == "10"
        assert record["attrs"]["data-shared-check"] == ""
        assert json.loads(record["attrs"]["data-covered-workpieces"]) == []
        assert set(json.loads(record["attrs"]["data-inspection-ids"])) == {
            f"{member}/base-envelope:width",
            f"{member}/base-envelope:height",
            f"{member}/shoulders:width",
            f"{member}/shoulders:thickness",
            f"{member}/end-length:length",
            f"{member}/part:actual_slot_fit",
            f"{member}/part:stud_retention",
        }
        (blank,) = markup.find("writing-blank", record)
        assert content(blank) == ""
    return records


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_terminal_inspection_reference_preserves_deferred_execution_and_physical_results(detail):
    data, _ = terminal_inspection_job()
    markup = Markup(rendered(data, detail=detail))
    references = [
        node for node in markup.nodes if node["attrs"].get("id") == "final-inspection-reference"
    ]
    deferred = detail == "hobby"
    owners = assert_terminal_inspection_route(markup, data, deferred=deferred)
    records = assert_terminal_results(markup)
    links = [
        node
        for node in markup.nodes
        if node["tag"] == "a" and node["attrs"].get("href") == "#final-inspection-reference"
    ]
    if not deferred:
        assert not references and not links
        assert not any(
            node["attrs"].get("data-page-reference") == "final-inspection" for node in markup.nodes
        )
        return
    (reference,) = references
    assert reference["attrs"]["data-reference-only"] == "true"
    assert reference["attrs"]["data-page-reference"] == "final-inspection"
    assert [
        node
        for node in markup.nodes
        if node["attrs"].get("data-page-reference") == "final-inspection"
    ] == [reference]
    assert json.loads(reference["attrs"]["data-execute-after"]) == ["B2a", "B2b", "B2c", "B2d"]
    assert any(
        re.search(r"\bcomplete\s+only\s+after\s+B2\b", content(node), re.IGNORECASE)
        for node in descendants(markup, reference)
        if node["tag"] in ("p", "h1", "h2", "h3", "h4", "h5", "h6")
    )
    reference_nodes = list(descendants(markup, reference))
    continuation_titles = [
        node["attrs"]["data-setup-title"]
        for node in reference_nodes
        if node["attrs"].get("data-setup-title")
    ]
    assert continuation_titles
    assert all(
        re.search(r"\bcomplete\s+only\s+after\s+B2\b", title, re.IGNORECASE)
        for title in continuation_titles
    )
    assert all(record in reference_nodes for record in records)
    assert all(owners[sid] in reference_nodes for sid in ("F1a", "F1b", "F1c", "F1d"))
    route = [
        node
        for node in markup.nodes
        if node["tag"] == "p" and content(node).startswith("Execution order:")
    ]
    (route,) = route
    assert re.search(r"\bB2\b.*\bF1\b", content(route))
    (link,) = links
    assert re.search(r"\bF1\b.*\bfinal inspection", content(link), re.IGNORECASE)
    assert re.search(r"\bafter\s+B2\b", content(link["parent"]), re.IGNORECASE)
    assert link not in reference_nodes
    remaining_ops = [
        node
        for node in operation_nodes(markup)
        if any(
            owner["setup_id"] not in ("F1a", "F1b", "F1c", "F1d")
            for owner in operation_owners(node)
        )
    ]
    assert remaining_ops
    positions = {id(node): index for index, node in enumerate(markup.nodes)}
    assert positions[id(link)] > max(positions[id(node)] for node in remaining_ops)
    text = " ".join(content(reference).split())
    assert re.search(r"\bhand[- ]slide\b.*?\bpull up\b", text, re.IGNORECASE)
    assert re.search(r"\bhand[- ]insert\b.*?\bstud\b.*?\btop\b", text, re.IGNORECASE)
    assert re.search(r"\bdo not force through\b", text, re.IGNORECASE)


@pytest.mark.parametrize(
    "unsafe",
    [
        "reading_owned",
        "method_field",
        "note_field",
        "indexing",
        "picture",
        "blocking",
    ],
)
def test_terminal_inspection_with_local_work_stays_at_its_execution_position(unsafe):
    data, finals = terminal_inspection_job()
    first = finals[0]
    findings = []
    if unsafe == "reading_owned":
        first["ops"][0]["checks"] = {"length": "calipers"}
        first["ops"][0]["inspection_methods"] = {
            "length": "Measure the ends; record {finished_length}."
        }
    elif unsafe == "method_field":
        first["ops"][0]["inspection_methods"]["end-length"] = {
            "length": "Measure the ends; record {finished_length}."
        }
    elif unsafe == "note_field":
        first["note"] = "Before inspecting, record {terminal_temperature}."
    elif unsafe == "indexing":
        first["hold"]["index"] = {"angle_deg": 0}
    elif unsafe == "picture":
        first["picture_panels"] = ["setup"]
        kernel = deepcopy(data.kernel or {})
        kernel.setdefault("status", "ok")
        kernel.setdefault("setups", {})["F1a"] = {
            "render_png_base64": base64.b64encode(_png((80, 100, 120))).decode("ascii"),
            "fixture_rendered": True,
            "render_scene": {
                "width_px": 1,
                "height_px": 1,
                "print_panels": [
                    {
                        "id": "setup",
                        "selection_group": "setup",
                        "annotations": [],
                        "role": "setup",
                        "label": "Terminal inspection fixture",
                        "top_px": 0,
                        "height_px": 1,
                    }
                ],
            },
        }
        data = replace(data, kernel=kernel)
    elif unsafe == "blocking":
        findings = [
            Finding(
                "reach",
                "F1a:10",
                "error",
                {},
                [],
                "Resolve terminal inspection clearance before proceeding.",
            )
        ]
    assets = render_assets(data)
    report = build_report(data, findings, assets=assets)
    markup = Markup(render_traveler(data, findings, report, None, detail="hobby"))
    assert not any(node["attrs"].get("id") == "final-inspection-reference" for node in markup.nodes)
    assert not any(
        node["attrs"].get("href") == "#final-inspection-reference" for node in markup.nodes
    )
    owners = assert_terminal_inspection_route(markup, data, deferred=False)
    assert_terminal_results(markup, reading_owned=unsafe == "reading_owned")
    local = owners["F1a"]
    if unsafe in ("reading_owned", "method_field", "note_field"):
        label = "terminal temperature" if unsafe == "note_field" else "finished length"
        fields = [
            node
            for node in markup.find("field")
            if any(content(caption) == label for caption in markup.find("field-label", node))
        ]
        (field,) = fields
        assert field in list(descendants(markup, local))
        scope = field
        while scope is not None and "data-setup-id" not in scope["attrs"]:
            scope = scope["parent"]
        assert scope is not None and scope["attrs"]["data-setup-id"] == "F1a"
        if unsafe != "note_field":
            operation = operation_owner(field)
            assert operation is not None
            assert {
                (owner["setup_id"], str(owner["op_id"]), owner["workpiece"])
                for owner in operation_owners(operation)
            } == {("F1a", "10", "nut1")}
        (blank,) = markup.find("writing-blank", field)
        assert content(blank) == ""
    elif unsafe == "indexing":
        assert re.search(
            r"\bindex\b.*\bplate arithmetic not computed\b", content(local), re.IGNORECASE
        )
    elif unsafe == "picture":
        (picture,) = markup.find("fixture-render")
        assert picture in list(descendants(markup, local))
        assert "Terminal inspection fixture" in content(picture)
        (image,) = [
            node for node in descendants(markup, picture) if node["tag"] in ("img", "image")
        ]
        path = report["renders"]["F1a"]["path"]
        assert image["attrs"].get("src", image["attrs"].get("href")) == path
        assert assets[path] == _png((80, 100, 120))
    elif unsafe == "blocking":
        (finding,) = findings
        notices = finding_nodes(markup, finding)
        assert notices and all(finding_has_kind(node, finding, "block") for node in notices)
        assert any(node in list(descendants(markup, local)) for node in notices)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("with_reading", [False, True], ids=["plain-note", "owned-reading"])
def test_selected_detail_note_keeps_plain_manual_work_inline_but_readings_local(
    detail, with_reading
):
    data, _ = terminal_inspection_job()
    setup = next(setup for setup in data.plan["setups"] if setup["id"] == "B2a")
    operation = next(op for op in setup["ops"] if op["op"] == 40)
    text = (
        "Record the oil-film check: {customreading}."
        if with_reading
        else "Keep the witness face upright."
    )
    operation["note"] = [{"text": text, "detail": "pro"}]
    markup = Markup(rendered(data, detail=detail))
    instructions = []
    for node in markup.find("route-operation"):
        owner = operation_owner(node)
        if owner is not None and any(
            item["setup_id"] == "B2a" and str(item["op_id"]) == "40"
            for item in operation_owners(owner)
        ):
            instructions.append((node, owner))
    ((instruction, owner),) = instructions
    assert {
        (item["setup_id"], str(item["op_id"]), item["workpiece"])
        for item in operation_owners(owner)
    } == {("B2a", "40", "nut1")}
    assert instruction["tag"] == ("p" if with_reading else "span")
    fields = [
        node
        for node in markup.find("field")
        if any(content(label) == "customreading" for label in markup.find("field-label", node))
    ]
    if with_reading:
        assert "Record the oil-film check:" in content(owner)
        (field,) = fields
        assert field in list(descendants(markup, owner))
        assert operation_owner(field) is owner
        (blank,) = markup.find("writing-blank", field)
        assert content(blank) == ""
    else:
        assert not fields
        assert "Keep the witness face upright." in content(owner)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_saw_stops_before_first_withdrawal_and_holds_capture_through_calibration(detail):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    cycles = [
        (setup, op)
        for setup in data.plan["setups"]
        for op in setup.get("ops", [])
        if "saw_trajectory" in op
    ]
    assert len(cycles) == 3

    def position(sheet, scale, text, setup_id, axis, value, start):
        target = re.escape(sheet.readout(value / scale)).replace(r"\-", "[−-]")
        match = re.search(rf"\b{'XYZ'[axis]}\s*{target}(?!\d|\.\d)", text[start:])
        assert match is not None, (setup_id, axis, value, text)
        return start + match.end()

    for setup, op in cycles:
        # A fresh composer makes this physical cycle the reference rather than a repeat.
        sheet = _Traveler(data, [], {}, None, detail=detail)
        sheet.setup = setup
        text = content(Markup(sheet.saw_cycle(setup, op)).find("route-cycle")[0])
        moves = op["saw_trajectory"]["moves"]
        last_cut = max(index for index, move in enumerate(moves) if move["mode"] == "cut")
        previous = moves[last_cut - 1]["to_mm"] if last_cut else op["saw_trajectory"]["start_mm"]
        cut_point = moves[last_cut]["to_mm"]
        axis = next(index for index in range(3) if previous[index] != cut_point[index])
        scale = {"mm": 1.0, "in": 25.4}[sheet.units]

        cut_word = re.search(r"\bcut\s+", text, re.IGNORECASE)
        assert cut_word is not None
        cut_end = position(sheet, scale, text, setup["id"], axis, cut_point[axis], cut_word.end())
        stop = re.search(r"\bSTOP\s+fully\b", text[cut_end:], re.IGNORECASE)
        assert stop is not None
        stop_end = cut_end + stop.end()
        held = re.search(r"\bcapture\b[^.;]*\b(?:clamped|held)\b", text[stop_end:], re.IGNORECASE)
        assert held is not None
        held_end = stop_end + held.end()
        cursor = cut_end
        previous = cut_point
        for move in moves[last_cut + 1 :]:
            assert move["mode"] == "clear"
            point = move["to_mm"]
            axis = next(index for index in range(3) if previous[index] != point[index])
            cursor = position(sheet, scale, text, setup["id"], axis, point[axis], cursor)
            assert stop_end < cursor, (setup["id"], text)
            assert held_end < cursor, (setup["id"], text)
            previous = point
        # Include the final paper-gap calibration, not just the raised return pose.
        assert previous == op["saw_trajectory"]["start_mm"]
        assert not re.search(r"\b(?:release|retrieve)\b", text[:cursor], re.IGNORECASE)
        capture_return = re.search(
            r"\bcapture\b[^.;]*\b(?:clamped|held)\b[^.;]*\b(?:full|whole|complete)\s+return\b",
            text,
            re.IGNORECASE,
        )
        assert capture_return is not None
        release = re.search(r"\b(?:release|retrieve)\b", text[cursor:], re.IGNORECASE)
        assert release is not None
        assert cursor + release.start() > capture_return.end()


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("display_units", ["mm", "in"])
@pytest.mark.parametrize("entry_mode", ["legacy_tangent", "air", "mixed_family"])
def test_compact_facing_table_keeps_all_native_pass_centres_and_clear_return(
    detail, display_units, entry_mode
):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    data.plan["dro"]["units"] = display_units
    # Native Q1-Q4 coordinate findings, report findings 154-157: retain the actual
    # snapped middle Y, not an interpolated or reviewer-invented two-pass recipe.
    native = {
        "Q1": (-22.225, 110.49, [-12.7, 0.0, 12.7]),
        "Q2": (-110.49, 22.225, [-14.2875, -7.14248, 0.0]),
        "Q3": (-22.225, 110.49, [-14.2875, -7.14248, 0.0]),
        "Q4": (-22.225, 110.49, [-11.1125, 0.0, 11.1125]),
    }
    air_starts = {"Q1": -24.765, "Q2": -113.03, "Q3": -24.765, "Q4": -24.765}
    air_owners = (
        set(native)
        if entry_mode == "air"
        else {"Q1", "Q2"}
        if entry_mode == "mixed_family"
        else set()
    )
    for sid in air_owners:
        _, end, ys = native[sid]
        native[sid] = (air_starts[sid], end, ys)
    findings = []
    for sid, (start, end, ys) in native.items():
        profile = {
            "op": 10,
            "stage": "finish",
            "to_z": 0.0,
            "dro_to_z": 0.0,
            "cut_order": "conventional",
            "spindle_rotation": "cw",
            "cutter_centre": [[[start, y], [end, y]] for y in ys],
            "raster": {
                "cycle": "one_way",
                "run_axis": "x",
                "passes": len(ys),
                "step_mm": 12.7,
                "lift_z": 4.1275,
            },
        }
        numbers = {
            "operations": [{"op": 10, "dro_to_z": 0.0, "z_levels": {"levels": [0.0]}}],
            "profiles": [profile],
            "level_paths": [
                {
                    "op": 10,
                    "raster": True,
                    "closed": False,
                    "from_z": 1.5875,
                    "levels": [0.0],
                    "raise_z": profile["raster"]["lift_z"],
                    "raise_clear": True,
                    "entries": [
                        {
                            "xy": segment[0],
                            "pass": True,
                            "air": sid in air_owners,
                            **({} if sid in air_owners else {"contact": "tangent"}),
                        }
                        for segment in profile["cutter_centre"]
                    ],
                }
            ],
        }
        findings.append(Finding("coordinates", sid, "pass", numbers, [], "Native facing path"))
    # Source heights: Q1 .625 - .0625 in over 10-mm jaws; Q4 .500 in over 10-mm jaws.
    headroom_findings = [
        Finding(
            "headroom",
            sid,
            "pass",
            {"cut_tip_above_jaws_mm": {"10": gap}, "jaw_obstruction": {"jaw_top_z": -gap}},
            [],
            "Evaluated vertical jaw height",
        )
        for sid, gap in (("Q1", 4.2875), ("Q4", 2.7))
    ]
    shown_findings = [*findings, *headroom_findings]
    report = build_report(data, shown_findings)
    report["renders"] = {
        "Q2": {
            "path": "renders/Q2.png",
            "fixture": "modeled",
            "scene": {
                "width_px": 1600,
                "height_px": 1400,
                "print_panels": [
                    {
                        "top_px": 0,
                        "height_px": 1400,
                        "role": "setup",
                        "label": "Facing setup",
                        "id": "setup",
                        "selection_group": "setup",
                        "annotations": [],
                    }
                ],
            },
        }
    }
    markup = Markup(render_traveler(data, shown_findings, report, detail=detail))
    (table,) = markup.find("facing-paths")
    rows = [
        node
        for node in descendants(markup, table)
        if node["tag"] == "tr" and node["attrs"].get("data-setup-id") in native
    ]
    assert [row["attrs"]["data-setup-id"] for row in rows] == list(native)
    formatter = _Traveler(data, [], {}, None, detail=detail)
    cycles = markup.find("facing-cycle", table["parent"])
    assert len(cycles) == (2 if entry_mode == "mixed_family" else 1)
    air_endpoints = (
        {
            "Q1": [-24.765, 110.49],
            "Q2": [-113.03, 22.225],
            "Q3": [-24.765, 110.49],
            "Q4": [-24.765, 110.49],
        }
        if display_units == "mm"
        else {
            "Q1": [-0.975, 4.35],
            "Q2": [-4.45, 0.875],
            "Q3": [-0.975, 4.35],
            "Q4": [-0.975, 4.35],
        }
    )
    for row, finding in zip(rows, findings, strict=True):
        (path,) = markup.find("facing-path", row)
        assert path["attrs"]["data-op-id"] == "10"
        formatter.setup = next(
            setup for setup in data.plan["setups"] if setup["id"] == finding.subject
        )
        profile = finding.numbers["profiles"][0]
        first, *_, last = profile["cutter_centre"]
        expected = [
            formatter.readout(first[0][0]),
            formatter.readout(last[1][0]),
            *(formatter.readout(segment[0][1]) for segment in profile["cutter_centre"]),
        ]
        # Numeric order preserves both feed endpoints and every actual Y centre.
        assert numeric_values(content(path)) == [float(value) for value in expected]
        if finding.subject in air_owners:
            assert numeric_values(content(path))[:2] == pytest.approx(
                air_endpoints[finding.subject]
            )
        (cycle,) = [
            cycle
            for cycle in cycles
            if len(cycles) == 1 or f"{finding.subject}:10" in content(cycle)
        ]
        context = content(cycle)
        assert_coordinate(context, "Z", float(formatter.readout(profile["dro_to_z"])))
        assert_coordinate(context, "Z", float(formatter.readout(profile["raster"]["lift_z"])))
        assert re.search(r"\b(?:lift|raise)\b.*\breturn\b", context, re.IGNORECASE)
        assert ("tangent" in context.casefold()) is (finding.subject not in air_owners)
        assert bool(re.search(r"\blower\b.*\bin air\b", context, re.IGNORECASE)) is (
            finding.subject in air_owners
        )
    q1, _, _, q4 = rows
    q4_notices = [
        node
        for node in decision_nodes(markup)
        if any(
            fact["source"] == "headroom" and fact["scope"] == "Q4:10"
            for fact in decision_evidence(node)
        )
    ]
    assert q4_notices and all(node in list(descendants(markup, q4)) for node in q4_notices)
    if detail == "hobby":
        assert re.search(r"both jaw tops.*4\.3\s*mm", content(q1), re.IGNORECASE)
        references = markup.find("setup-view-reference", table)
        (reference,) = references
        reference_text = content(reference)
        assert "Q2" in reference_text
        assert re.search(r"\bfollows\b.*\bfacing\s+cycle\b", reference_text, re.IGNORECASE)
        assert not re.search(r"\bpage\b|\bE1\w*\b", reference_text, re.IGNORECASE)
        assert reference in list(descendants(markup, rows[1]))
        (picture,) = markup.find("fixture-render", table["parent"])
        (instruction,) = [
            node
            for node in markup.find("route-operation", table["parent"])
            if {str(owner["setup_id"]) for owner in operation_owners(operation_owner(node))}
            == set(native)
            and all(
                str(owner["op_id"]) == "10" for owner in operation_owners(operation_owner(node))
            )
        ]
        positions = [
            next(index for index, node in enumerate(markup.nodes) if node is target)
            for target in (table, instruction, picture)
        ]
        assert positions == sorted(positions)


@pytest.mark.parametrize(
    "selected_picture", [False, True, None], ids=["absent", "explicit", "default"]
)
@pytest.mark.parametrize("final_op", [40, 87])
def test_hobby_source_order_view_reference_uses_actual_single_cycle_end_not_e1_family(
    selected_picture, final_op
):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    shoulder = next(setup for setup in data.plan["setups"] if setup["id"] == "S1")
    shoulder["id"] = "shoulder-view-owner"
    shoulder["ops"][-1]["op"] = final_op
    if selected_picture is None:
        shoulder.pop("picture_panels", None)
    for setup in data.plan["setups"]:
        if setup.get("stock_in") == "S1":
            setup["stock_in"] = shoulder["id"]
    report = build_report(data, [])
    report["renders"] = {}
    for sid in ("shoulder-view-owner", "E1a"):
        if sid == "shoulder-view-owner" and selected_picture is False:
            continue
        report["renders"][sid] = {
            "path": f"renders/{sid}.png",
            "fixture": "modeled",
            "scene": {
                "width_px": 1600,
                "height_px": 1400,
                "print_panels": [
                    {
                        "top_px": 0,
                        "height_px": 1400,
                        "role": "setup",
                        "label": "Selected setup",
                        "id": "setup",
                        "selection_group": "setup",
                        "annotations": [],
                    }
                ],
            },
        }
    markup = Markup(render_traveler(data, [], report, detail="hobby"))
    references = markup.find("setup-view-reference")
    assert not any(re.search(r"\bE1\w*\b", content(node)) for node in references)
    shoulder_references = [node for node in references if "shoulder-view-owner" in content(node)]
    assert len(shoulder_references) == int(selected_picture is True)
    if selected_picture is True:
        text = content(shoulder_references[0])
        assert re.search(rf"\bfollows\b.*\bop\s+{final_op}\b", text, re.IGNORECASE)
        assert not re.search(r"\bpage\b|\bS1\b", text, re.IGNORECASE)
        assert any(
            node["attrs"].get("href") == "renders/shoulder-view-owner.png"
            for node in markup.nodes
            if node["tag"] == "image"
        )


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_hand_tap_warning_omits_model_cause_without_changing_typed_evidence(detail):
    data = bench_job()
    setup = data.plan["setups"][0]
    setup["ops"][0]["do"] = "hand_tap"
    scope = f"{setup['id']}:{setup['ops'][0]['op']}"
    finding = Finding(
        "accessibility",
        scope,
        "unknown",
        {},
        [],
        "claimed face references are unknown or unmapped.",
    )
    data.policy["required"]["accessibility"] = "*"
    original = deepcopy(finding.to_dict())
    markup = Markup(rendered(data, [finding], detail=detail))
    notices = finding_nodes(markup, finding)
    assert notices and all(finding_has_kind(node, finding, "block") for node in notices)
    text = " ".join(content(node) for node in notices).casefold()
    assert re.search(r"hand.tap movement.*?not checked", text)
    assert "inside surface" not in text and "model" not in text
    assert "unknown or unmapped" not in text
    assert finding.to_dict() == original
    pedantic = rendered(data, [finding], detail="pedantic")
    assert finding.sentence in visible_text(pedantic)
    assert decision_snapshot(pedantic) == decision_snapshot(
        rendered(data, [finding], detail=detail)
    )


@pytest.mark.parametrize(
    ("detail", "operation", "rule", "message"),
    [
        (
            "pedantic",
            "hand_tap",
            "accessibility",
            "claimed face references are unknown or unmapped.",
        ),
        ("hobby", "drill", "accessibility", "claimed face references are unknown or unmapped."),
        ("pro", "hand_tap", "reach", "claimed face references are unknown or unmapped."),
        ("hobby", "hand_tap", "accessibility", "The bore approach remains unresolved."),
    ],
)
def test_hand_tap_mapping_projection_leaves_other_messages_unchanged(
    detail, operation, rule, message
):
    data = bench_job()
    setup = data.plan["setups"][0]
    setup["ops"][0]["do"] = operation
    scope = f"{setup['id']}:{setup['ops'][0]['op']}"
    sheet = _Traveler(data, [], {}, None, detail=detail)
    assert sheet.plain_error(rule, message, scope) == sheet.bench(message)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize(("cut_gap", "tip_gap"), [(0.5, 0.5), (1.57, 0.8)])
def test_paired_positive_milling_cautions_share_only_compact_notice_with_all_facts(
    monkeypatch, detail, cut_gap, tip_gap
):
    from test_sheet_ops import headroom, near_holding

    from prechips.sheet import _typed_values

    producer, setup = near_holding(cut_gap)
    producer.detail = detail
    numbers = headroom(tip_above_jaws=tip_gap, jaw_top_z=-0.5 - tip_gap)
    producer.records[("headroom", setup["id"])] = numbers
    boxes = producer.crash_boxes(setup, setup["ops"][0])
    assert {box.source for box in boxes} == {"cut_clearance", "headroom"}
    assert all(
        (box.status, box.kind, box.notice_group) == ("warn", "caution", "milling-clearance")
        for box in boxes
    )
    by_source = {box.source: box for box in boxes}
    assert_number(str(by_source["cut_clearance"]), cut_gap)
    assert_number(str(by_source["headroom"]), tip_gap)
    if detail != "pro":
        assert re.search(r"\bhand feed\b", str(by_source["cut_clearance"]), re.IGNORECASE)
        assert re.search(r"\bcheck before plunging\b", str(by_source["headroom"]), re.IGNORECASE)

    # The table producer must opt into the same presentation grouping as op boxes.
    producer.clearance_rows(setup, numbers, {})
    table_decisions = producer.producer_decisions[setup["id"]]
    assert {
        decision.source
        for decision in table_decisions
        if decision.notice_group == "milling-clearance" and decision.kind == "caution"
    } == {"cut_clearance", "headroom"}

    data = bench_job()
    owner = data.plan["setups"][0]
    scope = f"{owner['id']}:{owner['ops'][0]['op']}"
    decisions = tuple(_typed_values(boxes, scope))
    assert all(decision.notice_group == "milling-clearance" for decision in decisions)
    operation_rows = _Traveler.operation_rows

    def with_clearances(self, setup, tools):
        rows = operation_rows(self, setup, tools)
        rows[0].decisions = (*rows[0].decisions, *decisions)
        rows[0].warnings = (*rows[0].warnings, *boxes)
        return rows

    monkeypatch.setattr(_Traveler, "operation_rows", with_clearances)
    markup = Markup(rendered(data, detail=detail))
    expected = {
        (decision.source, decision.status, decision.scope, decision.kind) for decision in decisions
    }
    notices = [
        node
        for node in decision_nodes(markup)
        if any(
            (entry["source"], entry["status"], entry["scope"], entry["kind"]) in expected
            for entry in decision_evidence(node)
        )
    ]
    assert notices
    assert {
        (entry["source"], entry["status"], entry["scope"], entry["kind"])
        for node in notices
        for entry in decision_evidence(node)
    } == expected
    displays = [
        node
        for node in markup.nodes
        if {"decision", "box"} & set(node["attrs"].get("class", "").split())
        and any(str(box) in content(node) for box in boxes)
    ]
    for box in boxes:
        assert sum(content(node).count(str(box)) for node in displays) == 1
    for display in displays:
        physical = operation_owner(display)
        assert physical is not None
        assert {
            (identity["setup_id"], str(identity["op_id"]))
            for identity in operation_owners(physical)
        } == {(owner["id"], str(owner["ops"][0]["op"]))}
    if detail != "pedantic":
        assert any(all(str(box) in content(node) for box in boxes) for node in displays)


def test_milling_notice_group_does_not_merge_other_owners_unrelated_cautions_or_blocks():
    from prechips.sheet import _Box, _Decision, _decision_groups, _typed_values

    first = _Box(
        "Locator gap 0.75 mm; hand feed past it",
        source="cut_clearance",
        status="warn",
        kind="caution",
        notice_group="milling-clearance",
    )
    second = _Box(
        "Tip gap 1.25 mm; check before plunging",
        source="headroom",
        status="warn",
        kind="caution",
        notice_group="milling-clearance",
    )
    paired = tuple(_typed_values([first, second], "S1:60"))
    other_op = replace(paired[0], scope="S1:70")
    other_setup = replace(paired[1], scope="S2:60")
    unrelated = _Decision("reach", "warn", "S1:60", "caution", "Review the holder projection")
    unknown = _Decision("reach", "unknown", "S1:60", "block", "Holder clearance not computed")
    collision = _Decision("cut_clearance", "error", "S1:60", "block", "STOP: 0.4 mm collision")
    decisions = (*paired, other_op, other_setup, unrelated, unknown, collision)
    compact = _decision_groups(decisions, combine_notices=True)
    assert _decision_groups(paired) == [[paired[0]], [paired[1]]]
    assert [group for group in compact if len(group) > 1] == [list(paired)]
    assert all(
        [decision] in compact for decision in (other_op, other_setup, unrelated, unknown, collision)
    )
    assert {
        (decision.source, decision.status, decision.scope, decision.kind, decision.text)
        for group in compact
        for decision in group
    } == {
        (decision.source, decision.status, decision.scope, decision.kind, decision.text)
        for decision in decisions
    }


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("display_units", ["mm", "in"])
def test_local_parallel_and_grip_rows_name_each_source_mm_quantity(detail, display_units):
    from test_envelope_m5 import measured

    data = datum_sharing_job()
    data.plan["dro"]["units"] = display_units
    expected = {}
    for index, setup in enumerate(data.plan["setups"]):
        height = (12.7, 9.525, 6.35)[index]
        grip = (7.62, 5.08, 3.81)[index]
        reference = f"local-parallels-{index}"
        data.inventory["fixtures"][reference] = {
            "kind": "parallels",
            "height_mm": measured(height),
        }
        setup["hold"].update(parallels=reference, grip_mm=grip)
        setup["presentation_group"] = "Local holding choices"
        expected[setup["id"]] = (height, grip)
    markup = Markup(rendered(data, zero_recipe.evaluate(data), detail=detail))
    owned = {sid: set() for sid in expected}
    for node in markup.nodes:
        sid = node["attrs"].get("data-setup-id")
        if sid in owned:
            owned[sid].update(parallel_grip_values(content(node)))
    assert owned == {sid: {quantities} for sid, quantities in expected.items()}
    assert not any(
        "parallels/grip" in content(node).casefold() for node in markup.nodes if node["tag"] == "h2"
    )


def mounted_jog_job(axis, jog, jog_key):
    """Two real setups sharing complete, signed mounted-saw pickup records."""
    from test_zero_pickup_rule_consumers import native_proof, normalized_request

    data = mill_job(setups=2)
    data.plan["dro"]["units"] = "mm"
    data.inventory["tools"]["blade"] = {
        "kind": "slitting_saw",
        "dia_mm": 50.8,
        "kerf_mm": 1.0,
        "thickness_mm": 0.8,
        "kerf_offset_mm": 0.0,
    }
    data.inventory["holders"] = {
        "collet": {"kind": "collet"},
        "arbor": {"kind": "saw_arbor"},
    }
    findings = []
    for setup in data.plan["setups"]:
        setup["stock_in"] = "stock"
        setup["ops"] = [
            {
                "op": 20,
                "do": "cut_off",
                "tool": "blade",
                "holder": "arbor",
                "cut_plane": {"axis": "z", "value": 8.5, "keep": "below"},
            }
        ]
        axes = {}
        for letter in "xyz":
            signed = jog if letter == axis else 1.25
            setting = {"x": -2.54, "y": 13.375, "z": 20.6}[letter]
            touch = {
                "face": f"stock:-{letter}" if letter != "z" else "top",
                "from": f"-{letter}" if letter != "z" else "+z",
                "method": "edge finder" if letter != "z" else "mounted_saw_side",
                "tool": "finder" if letter != "z" else "blade",
                "holder": "collet" if letter != "z" else "arbor",
                "at_mm": [5.0, 8.0],
            }
            setup["zero"][letter] = touch
            record = {
                **deepcopy(touch),
                "edge_mm": {"x": 0.0, "y": 15.915, "z": 20.15}[letter],
                "axis_set_status": "computed",
                "axis_set": setting,
                jog_key: signed,
                "check_reading": setting + signed,
                "mirrored_reading": setting - signed,
            }
            if jog_key == "check_jog_mm":
                record["jog_mm"] = 8.25  # The explicit signed check jog wins.
            if letter != "z":
                request = normalized_request(letter)
                request["check_jog_mm"] = signed
                request["edge_mm"] = record["edge_mm"]
                proof = native_proof(request)
                proof["setup_id"] = setup["id"]
                if letter == "y":

                    def in_y(point, edge_mm=record["edge_mm"]):
                        return [point[1], point[0] + edge_mm, point[2]]

                    def box_in_y(box):
                        return in_y(box[:3]) + in_y(box[3:])

                    for key in ("start_mm", "contact_mm"):
                        proof["path"][key] = in_y(proof["path"][key])
                    for leg in proof["path"]["legs"]:
                        for key in ("from_mm", "to_mm"):
                            leg[key] = in_y(leg[key])
                        for component in leg["components"]:
                            component["bbox_mm"] = box_in_y(component["bbox_mm"])
                    for obstacle in proof["obstacles"]:
                        obstacle["bbox_mm"] = box_in_y(obstacle["bbox_mm"])
                    for key in ("axis_mm", "point_mm"):
                        proof["resolved_contact"][key] = in_y(proof["resolved_contact"][key])
                    normal = proof["resolved_contact"]["normal"]
                    proof["resolved_contact"]["normal"] = [normal[1], normal[0], normal[2]]
                    proof["resolved_contact"]["plane_mm"] = record["edge_mm"]
                    proof["window"]["transverse_axis"] = "x"
                last = proof["path"]["legs"][-1]
                last["to_mm"] = list(last["from_mm"])
                last["to_mm"]["xyz".index(letter)] += signed
                proof["path"]["jog_mm"] = signed
                record["pickup_proof"] = proof
            else:
                record["mounted_saw_setting"] = {
                    "blade_side": "minus_z",
                    "body_thickness_mm": 0.8,
                    "kerf_offset_mm": 0.0,
                    "paper_mm": 0.05,
                }
            axes[letter] = record
        findings.append(Finding("zero_check", setup["id"], "pass", {"axes": axes}, [], ""))
    return data, findings


@pytest.mark.parametrize("jog_key", ["check_jog_mm", "jog_mm"], ids=["explicit", "fallback"])
@pytest.mark.parametrize("jog", [2.75, -2.75], ids=["positive", "negative"])
@pytest.mark.parametrize("axis", ["x", "y", "z"], ids=["X", "Y", "Z"])
def test_mounted_saw_check_jog_prints_signed_direction_and_one_magnitude(axis, jog, jog_key):
    data, findings = mounted_jog_job(axis, jog, jog_key)
    sheet = _Traveler(data, findings, build_report(data, findings), None, detail="hobby")
    first, second = data.plan["setups"]
    assert set(sheet.mounted_datum_groups) == {first["id"], second["id"]}
    if axis in ("x", "y"):
        proof = findings[0].numbers["axes"][axis]["pickup_proof"]
        last = proof["path"]["legs"][-1]
        assert proof["status"] == "pass"
        index = "xyz".index(axis)
        assert last["to_mm"][index] - last["from_mm"][index] == pytest.approx(jog)
    markup = Markup(sheet.mounted_datum_table(first))
    text = " ".join(content(node) for node in markup.nodes if node["tag"] == "p")
    match = re.search(
        rf"([+−-]){axis.upper()}\s*(\d+(?:\.\d+)?)\s+check\s*"
        r"([+−-]?\d+(?:\.\d+)?);\s*([+−-]?\d+(?:\.\d+)?)\s+reversed:\s*STOP",
        text,
    )
    assert match, text
    assert match[1] == ("−" if jog < 0 else "+")
    assert float(match[2]) == abs(jog)
    setting = {"x": -2.54, "y": 13.375, "z": 20.6}[axis]
    assert [float(value.replace("−", "-")) for value in match.groups()[2:]] == pytest.approx(
        [setting + jog, setting - jog]
    )
    assert sheet.mounted_datum_table(second) == ""


def straight_saw_lineage_job(route):
    """A translated proved saw plane, with actual direct or inherited supply lineage."""
    data = rules_bundle(Path("."))
    data.plan["stock"] = {
        "components": [
            {"id": name, "material": "steel", "section_mm": [20.0, 10.0], "length_mm": 130.0}
            for name in ("a", "b")
        ]
    }
    setup = data.plan["setups"][0]
    setup["machine"] = "saw"
    setup["stock_in"] = ["stock.a", "stock.b"] if route == "multiple" else "stock.a"
    if route.startswith("inherited-"):
        arrival = {"id": "ARRIVAL", "ops": []}
        if route == "inherited-multiple":
            arrival["stock_in"] = ["stock.a", "stock.b"]
        elif route == "inherited-unknown":
            arrival["stock_in"] = "unknown"
        elif route == "inherited-single":
            arrival["stock_in"] = "stock.a"
        data.plan["setups"].insert(0, arrival)
        setup["stock_in"] = "ARRIVAL"
    if route == "aggregate":
        setup["stock_in"] = "stock"
    if route == "unknown":
        setup["stock_in"] = "unknown"
    if route == "missing":
        setup.pop("stock_in")
    plane = {"axis": "x", "value": 100.0, "keep": "below"}
    op = {"op": 10, "do": "cut_off", "tool": "blade", "cut_plane": deepcopy(plane)}
    setup["ops"] = [op]
    data.inventory["machines"]["saw"] = {"kind": "bandsaw"}
    data.inventory["tools"]["blade"] = {"kind": "bandsaw", "kerf_mm": 1.5}
    numbers = {"cut_plane": plane, "retained_boundary_mm": 99.25}
    native = {**deepcopy(numbers), "stock_bbox_before_mm": [0.0, 0.0, 0.0, 130.0, 20.0, 10.0]}
    data = replace(data, kernel={"status": "ok", "ops": {"S1:10": native}, "setups": {}})
    finding = Finding("saw_cut", "S1:10", "pass", numbers, [], "Straight cut proved")
    return data, setup, op, finding


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize(
    "route",
    [
        "single",
        "inherited-single",
        "multiple",
        "inherited-multiple",
        "unknown",
        "missing",
        "inherited-unknown",
        "inherited-missing",
        "aggregate",
    ],
)
def test_straight_saw_stock_end_projection_requires_one_known_arriving_atom(detail, route):
    from prechips.material_routes import MaterialGraph

    data, setup, op, finding = straight_saw_lineage_job(route)
    sheet = _Traveler(data, [finding], build_report(data, [finding]), None, detail=detail)
    before = canonical_bytes(build_report(data, [finding]))
    graph = MaterialGraph(data.plan)
    material = graph.nodes[setup["id"]]
    if route in ("inherited-unknown", "inherited-missing", "aggregate"):
        assert len(material) == 1
        assert (
            material[0].root
            == {
                "inherited-unknown": "unknown",
                "inherited-missing": "ARRIVAL",
                "aggregate": "stock",
            }[route]
        )
    target = sheet.straight_saw_target(setup, op, finding.numbers)
    if route in ("single", "inherited-single"):
        assert len(material) == 1 and material[0].root == "stock.a"
        assert target is not None
        assert "lower-X stock end" in target[0]
        assert_number(target[0], 99.25)
        assert_number(target[0], 100.0)
    else:
        if route in ("multiple", "inherited-multiple"):
            assert len(material) == 2
        assert target is None
        numbers, _, _ = sheet.tool_table(setup)
        (row,) = sheet.operation_rows(setup, numbers)
        text = " ".join(str(cell) for cell in row)
        assert re.search(r"\bretained X edge 99\.25 mm\b", text)
        assert "stock end" not in text
    assert canonical_bytes(build_report(data, [finding])) == before


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_missing_contour_tool_retains_distinct_profile_stop_reason_and_evidence(detail):
    from prechips.rules import coordinates

    data = rules_bundle(Path("."))
    setup = data.plan["setups"][0]
    setup["stock_in"] = "stock"
    setup["ops"][0]["tool"] = "unknown"
    setup["ops"][0]["contour"] = {
        "method": "linear_table",
        "step_mm": "unknown",
        "open_side": "-x",
    }
    (finding,) = coordinates.evaluate(data)
    (profile,) = finding.numbers["profiles"]
    reason = profile["raster_reason"]
    assert "contour.step_mm" in reason and re.search(r"\bpositive\b", reason)
    assert profile["cutter_centre"] == "unknown"
    assert reason not in finding.sentence
    assert finding.status == "unknown"
    paper_reason = reason.replace("_", " ")
    data.policy["required"] = {"coordinates": "*"}
    markup = Markup(rendered(data, [finding], detail=detail))
    notices = decision_nodes(markup)
    distinct = [node for node in notices if paper_reason in content(node)]
    assert len(distinct) == 1
    assert content(distinct[0]).count(paper_reason) == 1
    assert any(
        entry["source"] == "coordinates"
        and entry["status"] == "unknown"
        and entry["kind"] == "block"
        and entry["scope"] == "S1:10"
        for entry in decision_evidence(distinct[0])
    )
    assert any(
        entry["source"] == "tool_resolves"
        and entry["kind"] == "block"
        and entry["scope"] == "S1:10"
        for node in notices
        for entry in decision_evidence(node)
    )
    assert finding_nodes(markup, finding)
    assert not markup.find("coords")


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize(
    "gap", [0.5, -0.5, 0.0, "unknown"], ids=["positive", "collision", "zero", "unknown"]
)
def test_swept_clearance_advice_never_feeds_through_collision_or_unproved_gap(detail, gap):
    from prechips.sheet import _typed_values

    data = rules_bundle(Path("."))
    setup = data.plan["setups"][0]
    report = build_report(data, [])
    report["renders"] = {
        setup["id"]: {"scene": {"cut_clearances": [{"op": 10, "mm": gap, "tag": "fixture"}]}}
    }
    sheet = _Traveler(data, [], report, None, detail=detail)
    boxes = sheet.crash_boxes(setup, setup["ops"][0])
    rows = sheet.clearance_rows(setup, {}, {})
    facts = [
        *_typed_values(boxes, "S1:10"),
        *sheet.producer_decisions.get(setup["id"], []),
    ]
    assert rows and facts
    assert all(fact.source == "cut_clearance" and fact.scope == "S1:10" for fact in facts)
    texts = [*(str(box) for box in boxes), *(str(row[-1]) for row in rows)]
    if gap == 0.5:
        assert all((fact.status, fact.kind) == ("warn", "caution") for fact in facts)
        assert any("hand feed past it" in text for text in texts)
    else:
        assert not any("hand feed past it" in text for text in texts)
        assert any(
            re.search(r"\b(?:STOP|not computed|does not clear|do not run|no clearance)\b", text)
            for text in texts
        )
        if gap in (-0.5, 0.0):
            assert all((fact.status, fact.kind) == ("error", "block") for fact in facts)
            assert not any(fact.notice_group for fact in facts)
        elif gap == "unknown":
            assert all((fact.status, fact.kind) == ("unknown", "block") for fact in facts)
    if isinstance(gap, float):
        assert any(abs(value - gap) < 0.0001 for text in texts for value in numeric_values(text))


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_zero_swept_gap_keeps_owned_stop_separate_from_positive_tip_caution(monkeypatch, detail):
    source = rules_bundle(Path("."))
    source_setup = source.plan["setups"][0]
    report = build_report(source, [])
    report["renders"] = {
        source_setup["id"]: {"scene": {"cut_clearances": [{"op": 10, "mm": 0.0, "tag": "fixture"}]}}
    }
    producer = _Traveler(source, [], report, None, detail=detail)
    producer.records[("headroom", source_setup["id"])] = {"cut_tip_above_jaws_mm": {"10": 0.5}}
    boxes = producer.crash_boxes(source_setup, source_setup["ops"][0])
    by_source = {box.source: box for box in boxes}
    assert set(by_source) == {"cut_clearance", "headroom"}
    assert (
        by_source["cut_clearance"].status,
        by_source["cut_clearance"].kind,
        by_source["cut_clearance"].notice_group,
    ) == ("error", "block", "")
    assert (
        by_source["headroom"].status,
        by_source["headroom"].kind,
        by_source["headroom"].notice_group,
    ) == ("warn", "caution", "milling-clearance")

    data = bench_job()
    owner = data.plan["setups"][0]
    scope = f"{owner['id']}:{owner['ops'][0]['op']}"
    crash_boxes = _Traveler.crash_boxes

    def with_measured_clearances(self, setup, op):
        measured = crash_boxes(self, setup, op)
        if self.bundle is data and setup["id"] == owner["id"] and op["op"] == owner["ops"][0]["op"]:
            return [*measured, *boxes]
        return measured

    monkeypatch.setattr(_Traveler, "crash_boxes", with_measured_clearances)
    sheet = _Traveler(data, [], build_report(data, []), None, detail=detail)
    blocks = sheet.setup_blocks(owner)
    assert sheet.setup_stops[owner["id"]] == 1
    markup = Markup("".join(sheet.block_html(block) for block in blocks))
    notices = {}
    for source_name, status, kind, notice_group in (
        ("cut_clearance", "error", "block", ""),
        ("headroom", "warn", "caution", "milling-clearance"),
    ):
        (fact,) = [
            fact
            for fact in sheet.setup_decisions[owner["id"]]
            if fact.source == source_name and fact.scope == scope
        ]
        assert (fact.status, fact.kind, fact.notice_group) == (status, kind, notice_group)
        (notice,) = [
            node
            for node in decision_nodes(markup)
            if any(
                entry["source"] == source_name and entry["scope"] == scope
                for entry in decision_evidence(node)
            )
        ]
        notices[source_name] = notice
        assert notice["attrs"]["data-setup-id"] == owner["id"]
        assert notice["attrs"]["data-op"] == str(owner["ops"][0]["op"])
        assert [
            entry
            for entry in decision_evidence(notice)
            if entry["source"] == source_name and entry["scope"] == scope
        ] == [{"source": source_name, "status": status, "scope": scope, "kind": kind}]
    assert_number(content(notices["cut_clearance"]), 0.0)
    assert_number(content(notices["headroom"]), 0.5)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_hand_thread_holder_survives_same_tool_spindle_label_without_lead(detail):
    data = mill_job(setups=2)
    data.inventory["tools"]["m6"] = {
        "kind": "tap",
        "name": "M6 hand and machine tap",
        "dia_mm": 6.0,
        "flute_len_mm": 15.0,
    }
    data.inventory["holders"] = {
        "machine-holder": {"kind": "collet", "name": "Spindle tap chuck"},
        "hand-holder": {"kind": "tap_wrench", "name": "Selected crossbar tap wrench"},
    }
    first, second = data.plan["setups"]
    for setup, action, holder in (
        (first, "tap", "machine-holder"),
        (second, "hand_tap", "hand-holder"),
    ):
        setup["stock_in"] = "stock" if setup is first else first["id"]
        setup["ops"] = [{"op": 10, "do": action, "tool": "m6", "holder": holder, "depth_mm": 8.0}]
    sheet = _Traveler(data, [], build_report(data, []), None, detail=detail)
    assert sheet.route_tool_label("m6") == "T1"
    blocks = {setup["id"]: sheet.setup_blocks(setup) for setup in (first, second)}
    key = Markup(sheet.settings_key())
    hand_key = [
        node
        for node in key.nodes
        if f"{second['id']}:10" in json.loads(node["attrs"].get("data-physical-ops", "[]"))
        and "Selected crossbar tap wrench" in content(node)
    ]
    local = Markup(
        next(block.html for block in blocks[second["id"]] if block.key == "operation:10")
    )
    assert hand_key or "Selected crossbar tap wrench" in " ".join(
        content(node) for node in local.nodes if node["tag"] in ("p", "span")
    )
    assert not any(
        "Spindle tap chuck" in content(node) for node in local.nodes if node["tag"] in ("p", "span")
    )


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize(
    ("numeric_authority", "local", "local_printed"),
    [(True, 0.05, False), (True, 0.04, True), (False, 0.05, True)],
)
def test_deburr_citation_prefixes_preserve_reasons_and_only_numeric_equality_shares_limits(
    detail, numeric_authority, local, local_printed
):
    data = bench_job()
    setup = data.plan["setups"][0]
    reason = "The small edge break keeps the bonded length."
    setup.update(deburr_mm=local, deburr_cite="private-provenance.md#edge: " + reason)
    global_note = "Raised burrs only; incidental edge break ≤0.05 mm."
    protection = "Preserve this reference shoulder and usable threads."
    data.features["notes"] = {"edge_break": global_note}
    if numeric_authority:
        data.features["general_tolerances"] = {"edge_break_r": 0.05, "chamfer_max": 0.05}
    setup["ops"].append({"op": 40, "do": "deburr", "feature": "body", "note": protection})
    sheet = _Traveler(data, [], {}, None, detail=detail)
    local_text = sheet.setup_edge_break(setup)
    assert bool(local_text) is local_printed
    if local_printed:
        assert_number(visible_text("<body>" + local_text + "</body>"), local)
    text = visible_text(rendered(data, detail=detail))
    assert text.count(global_note) == 1
    assert text.count(protection) == 1
    assert "private-provenance" not in text
    assert (reason in text) is local_printed


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("qualification", ["measured", "bare", "conflict", "missing"])
def test_compact_settings_keep_exact_selected_holder_projection_and_qualification(
    detail, qualification
):
    from test_envelope_m5 import measured

    data = mill_job(setups=2)
    data.inventory["holders"] = {
        "short": {"kind": "collet", "name": "Short installed collet"},
        "long": {"kind": "collet", "name": "Long installed collet"},
    }
    short = measured(31.75) if qualification != "bare" else 31.75
    projections = {"holders.short": short, "long": measured(45.72)}
    if qualification == "conflict":
        projections["short"] = measured(99.0)
    elif qualification == "missing":
        projections.pop("holders.short")
    data.inventory["tools"]["pair-drill"] = {
        "kind": "drill",
        "name": "Selected drill",
        "dia_mm": measured(5.0),
        "flute_len_mm": measured(25.0),
        "projection_mm": projections,
    }
    findings = []
    for setup, holder in zip(data.plan["setups"], ("short", "holders.long"), strict=True):
        setup["ops"] = [{"op": 70, "do": "drill", "tool": "pair-drill", "holder": holder}]
        findings.append(
            Finding(
                "speeds_feeds",
                setup["id"] + ":70",
                "pass",
                {"rpm": 850.0, "feed_mm_min": 19.05},
                [],
                "Controlled settings fixture",
            )
        )
    markup = Markup(rendered(data, findings, detail=detail))
    entries = markup.find("tool-setting-entry")
    selected = {
        json.loads(entry["attrs"]["data-physical-ops"])[0].split(":")[0]: content(entry)
        for entry in entries
    }
    first, second = (setup["id"] for setup in data.plan["setups"])
    assert "Short installed collet" in selected[first]
    assert "Long installed collet" in selected[second]
    assert re.search(r"\bprojection\s+45\.72\s+mm\b", selected[second])
    assert {"holder", "face"} <= set(re.findall(r"\b\w+\b", selected[second].casefold()))
    assert "Short installed collet" not in selected[second]
    assert "Long installed collet" not in selected[first]
    if qualification in ("conflict", "missing"):
        assert "projection ?" in selected[first]
        assert not re.search(r"projection\s+(?:31\.75|45\.72)\s+mm\b", selected[first])
        if qualification == "missing":
            assert "not recorded for the selected holder" in selected[first]
    else:
        projection = re.search(r"\bprojection\s+(\d+(?:\.\d+)?)\s+mm\b(.*)$", selected[first])
        assert projection, selected[first]
        assert float(projection[1]) == pytest.approx(31.75)
        assert {"holder", "face"} <= set(re.findall(r"\b\w+\b", projection[2].casefold()))
        if qualification == "bare":
            assert re.search(r"\?M\d+|\?\s+not verified", projection[2])
        else:
            assert "?" not in projection[2]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_saw_projection_uses_body_midplane_to_selected_holder_gauge(detail):
    from test_envelope_m5 import measured

    data = mill_job(setups=1)
    data.inventory["holders"] = {
        "arbor": {"kind": "arbor", "name": "Selected saw arbor"},
        "other": {"kind": "arbor", "name": "Unselected spare arbor"},
    }
    data.inventory["tools"]["blade"] = {
        "kind": "slitting_saw",
        "name": "Selected slitting saw",
        "dia_mm": measured(50.8),
        "kerf_mm": measured(1.0),
        "thickness_mm": measured(0.8),
        "projection_mm": {"arbor": measured(45.0), "other": measured(82.0)},
    }
    (setup,) = data.plan["setups"]
    setup["ops"] = [{"op": 75, "do": "rough_profile", "tool": "blade", "holder": "arbor"}]
    markup = Markup(rendered(data, detail=detail))
    (entry,) = [
        entry
        for entry in markup.find("tool-setting-entry")
        if f"{setup['id']}:75" in json.loads(entry["attrs"].get("data-physical-ops", "[]"))
    ]
    text = content(entry)
    assert "Selected saw arbor" in text and "Unselected spare arbor" not in text
    projection = re.search(r"\bprojection\s+45(?:\.0+)?\s+mm\b([^;.]*)", text, re.IGNORECASE)
    assert projection, text
    datum = projection[1]
    assert re.search(r"\bbody\s+midplane\b", datum, re.IGNORECASE)
    assert re.search(r"\bholder\s+gauge\s+plane\b", datum, re.IGNORECASE)
    assert not re.search(r"\b(?:face|nose|tip)\b", datum, re.IGNORECASE)
    assert not re.search(r"\bprojection\s+82(?:\.0+)?\b", text)


@pytest.mark.parametrize("levels_owner", ["operation", "path", "none"])
def test_compact_straight_paths_keep_each_evaluated_depth_in_order(levels_owner):
    data = mill_job(setups=1)
    setup = data.plan["setups"][0]
    setup["ops"] = [{"op": 75, "do": "rough_profile", "tool": "cutter", "to_z": -6.35}]
    data.inventory["tools"]["cutter"] = {"kind": "endmill", "dia_mm": 12.7}
    depths = [-3.175, -6.35]
    path = {"op": 75, "entries": [{"air": True}]}
    operation = {"op": 75}
    if levels_owner == "operation":
        operation["z_levels"] = {"levels": depths}
    elif levels_owner == "path":
        path["levels"] = depths
    finding = Finding(
        "coordinates",
        setup["id"],
        "pass",
        {"operations": [operation], "level_paths": [path]},
        [],
        "Evaluated depth fixture",
    )
    sheet = _Traveler(data, [finding], {}, None, detail="hobby")
    entry = {
        "parts": [
            (
                (0, 0, 0),
                "Ordered straight cuts",
                ["pass", "X from", "Y from", "X to", "Y to", "Z"],
                [["1", "-.75", "-.5075", "4.225", "-.5075", "-.25"]],
                "",
            )
        ],
        "stops": [],
    }
    text, html = sheet.route_contour_parts(setup, {("tools", "cutter"): "T1"}, {"75": entry}, {})[
        "75"
    ]
    assert not html
    shown_depths = [
        float(value.replace("−", "-"))
        for value in re.findall(r"\bZ([−+-]?(?:\d+(?:\.\d+)?|\.\d+))", text)
    ]
    assert shown_depths == ([-0.25] if levels_owner == "none" else [-0.125, -0.25]), text
    assert "-.5075" in text and "4.225" in text


def test_hobby_selected_figure_keeps_native_identity_without_repeated_job_slug():
    from test_sheet_ops import picture_sheet

    panel = {
        "top_px": 0,
        "height_px": 2200,
        "role": "setup",
        "label": "Main setup",
        "id": "setup",
        "selection_group": "setup",
        "annotations": [],
    }
    sheet = picture_sheet([panel])
    sheet.detail = "hobby"
    sheet.plan["part"] = "private-job-slug"
    markup = Markup(sheet.fixture_render({"id": "S1", "picture_panels": ["setup"]}))
    (figure,) = markup.find("fixture-render")
    assert figure["attrs"]["data-panel-id"] == "setup"
    assert figure["attrs"]["data-selection-group"] == "setup"
    assert not [node for node in markup.nodes if node["tag"] == "figcaption"]
    (image,) = [node for node in markup.nodes if node["tag"] == "image"]
    assert image["attrs"]["href"] == "renders/S1.png"
    (svg,) = [node for node in markup.nodes if node["tag"] == "svg"]
    assert svg["attrs"]["viewbox"] == "0 0 1600 2200"
    assert "Setup S1" in svg["attrs"]["aria-label"]
    assert "private-job-slug" not in svg["attrs"]["aria-label"]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_vertical_both_jaw_headroom_does_not_relabel_native_fixed_jaw_swept_gap(detail):
    from test_sheet_ops import headroom, near_holding

    sheet, setup = near_holding(0.91, tag="fixed jaw")
    sheet.detail = detail
    sheet.bundle.inventory["fixtures"] = {"vise": {"kind": "vise"}}
    setup["hold"]["fixture"] = "vise"
    sheet.records[("headroom", setup["id"])] = headroom(tip_above_jaws=1.35, jaw_top_z=-1.85)
    boxes = {box.source: str(box) for box in sheet.crash_boxes(setup, setup["ops"][0])}
    assert "BOTH JAW TOPS" in boxes["headroom"] and "VERTICAL" in boxes["headroom"]
    assert_number(boxes["headroom"], 1.35)
    assert "FIXED JAW" in boxes["cut_clearance"] and "SWEPT GAP" in boxes["cut_clearance"]
    assert "BOTH" not in boxes["cut_clearance"]
    assert_number(boxes["cut_clearance"], 0.91)

    data = mill_job(setups=1)
    (owner,) = data.plan["setups"]
    owner.setdefault("hold", {})["fixture"] = "vise"
    data.inventory["fixtures"] = {"vise": {"kind": "vise"}}
    owner["ops"] = [{"op": 60, "do": "rough_profile", "tool": "cutter", "to_z": -0.5}]
    data.inventory["tools"]["cutter"] = {"kind": "endmill", "dia_mm": 5.0}
    findings = [
        Finding(
            "headroom",
            owner["id"],
            "pass",
            headroom(tip_above_jaws=1.35, jaw_top_z=-1.85),
            [],
            "Evaluated vertical jaw height",
        ),
        Finding(
            "coordinates",
            owner["id"],
            "pass",
            {"operations": [{"op": 60, "dro_to_z": -0.5}]},
            [],
            "Evaluated tip position",
        ),
    ]
    report = build_report(data, findings)
    report["renders"] = {
        owner["id"]: {
            "path": f"renders/{owner['id']}.png",
            "fixture": "modeled",
            "scene": {
                "width_px": 1600,
                "height_px": 1400,
                "print_panels": [
                    {
                        "top_px": 0,
                        "height_px": 1400,
                        "role": "setup",
                        "label": "Synthetic clearance ownership fixture",
                        "id": "setup",
                        "selection_group": "setup",
                        "annotations": [],
                    }
                ],
                "cut_clearances": [{"op": 60, "mm": 0.91, "tag": "fixed jaw"}],
            },
        }
    }
    markup = Markup(render_traveler(data, findings, report, detail=detail))
    scope = f"{owner['id']}:60"
    notices = [
        node
        for node in decision_nodes(markup)
        if any(
            fact["source"] in ("headroom", "cut_clearance") and fact["scope"] == scope
            for fact in decision_evidence(node)
        )
    ]
    assert notices
    text = " ".join(content(node) for node in notices)
    assert "BOTH JAW TOPS" in text and "VERTICAL" in text
    assert "FIXED JAW" in text and "SWEPT GAP" in text
    assert_number(text, 1.35)
    assert_number(text, 0.91)
    for notice in notices:
        physical = operation_owner(notice)
        assert physical is not None
        assert {
            (identity["setup_id"], str(identity["op_id"]))
            for identity in operation_owners(physical)
        } == {(owner["id"], "60")}


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_example_dro_resolution_labels_numeric_mill_even_with_only_one_target_machine(detail):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    data.inventory["machines"]["pm-25mv-bd"]["name"] = "Milling machine"
    data.inventory["machines"]["bench-bandsaw"]["name"] = "Cutoff saw"
    setups = [setup for setup in data.plan["setups"] if setup["id"] in ("B0", "Q1")]
    findings = [
        Finding("coordinates", sid, "pass", {"dro_grid": grid}, [], "Evaluated readout fixture")
        for sid, grid in (
            ("B0", {"step": "not used", "decimals": "not used"}),
            ("Q1", {"step": 0.0001, "decimals": 4}),
        )
    ]
    sheet = _Traveler(data, findings, {}, None, detail=detail)
    text = sheet.dro_resolution(setups)
    assert text.startswith("Example DRO resolution:")
    assert "Cutoff saw" in text and "no coordinate targets" in text
    assert re.search(r"\bMilling machine\s+0\.0001\s+in\b", text), text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_machining_operations_keep_source_ids_and_separate_scannable_instructions(detail):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    sheet = _Traveler(data, [], {}, None, detail=detail)
    setups = [setup for setup in data.plan["setups"] if setup["id"] in ("S1", "E1a", "D1a")]
    assert {setup["id"] for setup in setups} == {"S1", "E1a", "D1a"}
    for setup in setups:
        blocks = sheet.setup_blocks(setup)
        for op in setup["ops"]:
            block = next(block for block in blocks if block.key == f"operation:{op['op']}")
            markup = Markup(block.html)
            (instruction,) = markup.find("route-operation")
            assert re.match(rf"\s*{op['op']}\.", content(instruction))
            if op["do"] in ("rough_profile", "profile", "spot", "drill"):
                assert block.layout == "block" and instruction["tag"] == "p"


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("citation_prefix", ["", "https://example.invalid/edges#thin: "])
def test_different_local_edge_limit_keeps_human_reason_after_optional_url(detail, citation_prefix):
    data = bench_job()
    data.features["general_tolerances"] = {"edge_break_r": 0.25}
    reason = "Small socket edge break keeps the bonded length."
    setup = data.plan["setups"][0]
    setup.update(deburr_mm=0.1, deburr_cite=citation_prefix + reason)
    sheet = _Traveler(data, [], {}, None, detail=detail)
    markup = Markup("<div>" + sheet.setup_edge_break(setup) + "</div>")
    text = content(markup.nodes[0])
    assert reason in text and "https://" not in text
    assert_number(text, 0.1)
    assert_number(text, 0.25)


@pytest.mark.parametrize("jog_key", ["check_jog_mm", "jog_mm"], ids=["explicit", "fallback"])
@pytest.mark.parametrize("jog", [2.75, -2.75], ids=["positive", "negative"])
@pytest.mark.parametrize("selected_axis", ["x", "y"], ids=["X", "Y"])
def test_unshared_mounted_saw_keeps_evaluated_xy_settings_and_signed_jog_readings(
    selected_axis, jog, jog_key
):
    data, findings = mounted_jog_job(selected_axis, jog, jog_key)
    data.plan["setups"] = data.plan["setups"][:1]
    findings = findings[:1]
    (setup,) = data.plan["setups"]
    sheet = _Traveler(data, findings, build_report(data, findings), None, detail="hobby")
    assert not sheet.mounted_datum_groups
    sheet.dro(setup, {}, procedure="separate")
    for axis in ("x", "y"):
        record = findings[0].numbers["axes"][axis]
        text = sheet._route_datum_axes[setup["id"]][axis]
        assert_coordinate(text, axis, record["axis_set"])
        check = re.search(
            rf"([+−-]){axis.upper()}\s*(\d+(?:\.\d+)?)\s+jog\s+reads\s*"
            r"([+−-]?\d+(?:\.\d+)?);\s*([+−-]?\d+(?:\.\d+)?)\s+reversed",
            text,
        )
        assert check, text
        distance = record.get("check_jog_mm", record.get("jog_mm"))
        assert check[1] == ("−" if distance < 0 else "+")
        assert float(check[2]) == pytest.approx(abs(distance))
        assert [float(value.replace("−", "-")) for value in check.groups()[2:]] == pytest.approx(
            [record["check_reading"], record["mirrored_reading"]]
        )


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("reason", ["", "Keeps the bonded length intact."])
def test_deburr_citation_line_lists_do_not_become_operator_instructions(detail, reason):
    data = bench_job()
    data.features["general_tolerances"] = {"edge_break_r": 0.25}
    setup = data.plan["setups"][0]
    cite = "harmonic-analyzer/cad/scripts/cone_gear_shaft_spec.py:79-97,111-113"
    setup.update(deburr_mm=0.1, deburr_cite=cite + (": " + reason if reason else ""))
    sheet = _Traveler(data, [], {}, None, detail=detail)
    text = visible_text("<body>" + sheet.setup_edge_break(setup) + "</body>")
    assert_number(text, 0.1)
    assert_number(text, 0.25)
    assert "harmonic-analyzer" not in text and "cone_gear_shaft_spec" not in text
    assert "79-97" not in text and "111-113" not in text
    if reason:
        assert reason in text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_tool_without_projection_map_does_not_invent_projection_requirement(detail):
    data = mill_job(setups=1)
    data.inventory["holders"] = {
        "installed": {"kind": "collet", "name": "Selected ordinary collet"}
    }
    data.inventory["tools"]["plain-drill"] = {
        "kind": "drill",
        "name": "Ordinary drill",
        "dia_mm": 5.0,
        "flute_len_mm": 25.0,
    }
    (setup,) = data.plan["setups"]
    setup["ops"] = [{"op": 70, "do": "drill", "tool": "plain-drill", "holder": "installed"}]
    findings = [
        Finding(
            "speeds_feeds",
            setup["id"] + ":70",
            "pass",
            {"rpm": 850.0, "feed_mm_min": 19.05},
            [],
            "Controlled settings fixture",
        )
    ]
    markup = Markup(rendered(data, findings, detail=detail))
    entries = [
        entry
        for entry in markup.find("tool-setting-entry")
        if f"{setup['id']}:70" in json.loads(entry["attrs"].get("data-physical-ops", "[]"))
    ]
    (entry,) = entries
    text = content(entry)
    assert "Selected ordinary collet" in text
    assert "850" in text
    assert not re.search(r"\bprojection\b", text)


def physical_flow(markup, setup_id):
    (flow,) = [
        node
        for node in markup.nodes
        if node["tag"] == "section"
        and setup_id in json.loads(node["attrs"].get("data-setup-members", "[]"))
    ]
    return flow


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("reverse", [False, True], ids=["male-first", "female-first"])
@pytest.mark.parametrize("methods_kind", ["scoped", "flat", "override"])
@pytest.mark.parametrize("requirement", ["thread", "dia"], ids=["unselected", "selected"])
def test_inspection_methods_keep_scoped_owners_and_only_share_actual_flat_entries(
    detail, reverse, methods_kind, requirement
):
    data = bench_job()
    owners = ["male", "female"]
    if reverse:
        owners.reverse()
    data.features["features"] = {
        owner: (
            {"kind": "thread", "thread": "1/2-20", "thread_class": "unknown"}
            if requirement == "thread"
            else {"kind": "shaft", "requirements": ["dia"], "dia": [6.33, 6.35]}
        )
        for owner in owners
    }
    procedures = {
        "male": "Try the actual cap by hand; record shoulder seating; thread gauging is unknown.",
        "female": "Confirm female full threads without tip bottoming and continuous mouth contact.",
    }
    shared = "Compare both actual members by hand; this does not establish thread class."
    methods = (
        {owner: {requirement: procedures[owner]} for owner in owners}
        if methods_kind == "scoped"
        else {requirement: shared}
    )
    if methods_kind == "override":
        methods["female"] = {requirement: procedures["female"]}
    setup = data.plan["setups"][0]
    setup["ops"] = [
        {
            "op": 10,
            "do": "inspect",
            "feature": owners,
            "checks": {owner: {requirement: "unknown"} for owner in owners},
            "inspection_methods": methods,
        }
    ]
    markup = Markup(rendered(data, detail=detail))
    flow = physical_flow(markup, setup["id"])
    text = content(flow)
    expected = (
        list(procedures.values())
        if methods_kind == "scoped"
        else [shared, procedures["female"]]
        if methods_kind == "override"
        else [shared]
    )
    for procedure in expected:
        assert text.count(procedure) == 1
        (method,) = [
            node for node in markup.find("inspection-method", flow) if procedure in content(node)
        ]
        owner = operation_owner(method)
        assert owner is not None
        assert {(entry["setup_id"], str(entry["op_id"])) for entry in operation_owners(owner)} == {
            (setup["id"], "10")
        }
        if requirement == "thread" and procedure != shared:
            feature_owner = next(key for key, value in procedures.items() if value == procedure)
            assert feature_owner in content(method)
    assert "no gauge chosen" in text
    if requirement == "thread":
        assert not markup.find("checkpoint-result", flow)
        assert not markup.find("writing-blank", flow)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("unknown_gauge", [False, True], ids=["resolved", "unknown-gauge"])
def test_receipt_acceptance_survives_full_render_at_first_use_without_claiming_signoff(
    detail, unknown_gauge
):
    from test_procedure_boxes import KIT, printed_band, table_rows

    from prechips.rules import purchased_tooling

    data = mill_job(setups=2)
    item = deepcopy(KIT)
    item.update(
        name="Purchased boring head",
        purchase="R8 shank, 7/16-20 drawbar, 0.001 in dial",
        dial_limits_mm=[0.244, 0.264],
        note="UNRELATED_CATALOG_TUTORIAL_SENTINEL",
        acceptance=[
            {"check": "R8 shank fit", "gauge": "none", "accept": "seats with no rock"},
            {
                "check": "dial graduation",
                "gauge": "dti",
                "how": "DTI on slide end; move 10 graduations, three times",
                "limits": "dial_limits_mm",
            },
            {"check": "slide lock", "gauge": "none", "accept": "no movement felt at bar tip"},
        ],
    )
    data.inventory.setdefault("fixtures", {})["kit"] = item
    data.inventory.setdefault("gauges", {})["dti"] = {
        "kind": "dial_test_indicator",
        "name": "Receipt DTI",
    }
    if unknown_gauge:
        data.inventory["gauges"].pop("dti")
    for setup in data.plan["setups"]:
        setup["presentation_group"] = setup["id"]
        setup.setdefault("hold", {})["clamps"] = [{"ref": "kit"}]
    findings = purchased_tooling.evaluate(data)
    html = rendered(data, findings, detail=detail)
    markup = Markup(html)
    first, second = (physical_flow(markup, setup["id"]) for setup in data.plan["setups"])
    first_text, second_text = content(first), content(second)
    for check in ("R8 shank fit", "dial graduation", "slide lock"):
        assert check in first_text
    (dial_row,) = [row for row in table_rows(html) if row[0] == "dial graduation"]
    assert printed_band(dial_row[2], "mm") == [tuple(item["dial_limits_mm"])]
    assert "10 graduations" in first_text and "three times" in first_text
    assert "10 graduations" not in second_text and "three times" not in second_text
    assert "return the item if any check fails" in first_text
    assert data.plan["setups"][0]["id"] in second_text
    assert "receipt checks before first use" in second_text
    assert "accepted on receipt" not in content(job_page(markup))
    assert "UNRELATED_CATALOG_TUTORIAL_SENTINEL" not in content(job_page(markup))
    if unknown_gauge:
        unknowns = [finding for finding in findings if finding.status == "unknown"]
        assert unknowns
        for finding in unknowns:
            assert finding_nodes(markup, finding)


def lathe_operating_job(ops, hands=None):
    from test_lathe_review_rules import _lathe

    hands = hands or {"cutter": "right"}
    tools = {
        name: {
            "kind": "lathe_tool_bit",
            "name": name + " tool",
            **({"hand": hand} if hand else {}),
        }
        for name, hand in hands.items()
    }
    data = _lathe(ops, {"body": {"kind": "shaft", "dia": [6.33, 6.35]}}, tools)
    data.plan["dro"].update(kind="digital", mode="abs", units="mm")
    data.plan["drawing"] = {"number": "LATHE-FACTS", "revision": "A"}
    data.inventory.setdefault("fixtures", {})["chuck"] = {"kind": "chuck", "name": "Lathe chuck"}
    return data


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("mode", ["forward", "reverse", "mixed", "unknown"])
def test_compact_spindle_context_keeps_nondefault_sense_and_hobby_guidance_at_its_owner(
    detail, mode
):
    ops = [{"op": 10, "do": "finish_turn", "tool": "cutter", "feature": "body", "to_dia": 6.35}]
    hands = {"cutter": "right"}
    if mode in ("reverse", "mixed"):
        hands["axial"] = "left"
        drill = {"op": 20, "do": "drill", "tool": "axial", "feature": "body", "depth_mm": 2.0}
        ops = [*ops, drill] if mode == "mixed" else [drill]
    elif mode == "unknown":
        hands["cutter"] = None
    data = lathe_operating_job(ops, hands)
    markup = Markup(rendered(data, detail=detail))
    flow = physical_flow(markup, "S1")
    instructions = markup.find("route-operation", flow)
    text = " ".join(content(node) for node in instructions)
    if mode == "forward":
        assert ("Spindle FORWARD" in content(flow)) is (detail == "hobby")
        if detail == "pro":
            assert "FORWARD" not in content(job_page(markup))
        if detail == "hobby":
            assert content(flow).count("Spindle FORWARD") == 1
            assert "top of the work turns toward you" in content(flow)
    elif mode in ("reverse", "mixed"):
        reverse_nodes = [
            node
            for node in operation_nodes(markup, flow)
            if "spindle reverse" in content(node).casefold()
        ]
        assert reverse_nodes
        assert any(
            any(str(owner["op_id"]) == "20" for owner in operation_owners(node))
            for node in reverse_nodes
        )
        if mode == "mixed":
            assert "spindle FORWARD" in text and "spindle REVERSE" in text
    else:
        assert "STOP: spindle direction not known" in content(flow)
        assert "Spindle FORWARD" not in content(flow)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_dro_lessons_follow_machine_family_and_later_links_resolve_to_applicable_guide(detail):
    data = mill_job(setups=2)
    lathe = lathe_operating_job([], {"cutter": "right"})
    lathe_setup = deepcopy(lathe.plan["setups"][0])
    lathe_setup.update(
        id="L1",
        frame=data.plan["setups"][0]["frame"],
        zero={"x": {"edge_mm": 5.0}, "z": {"edge_mm": 0.0}},
    )
    data.inventory["machines"]["lathe"] = lathe.inventory["machines"]["lathe"]
    data.inventory.setdefault("fixtures", {})["chuck"] = lathe.inventory["fixtures"]["chuck"]
    data.plan["setups"].insert(0, lathe_setup)
    findings = zero_recipe.evaluate(data)
    markup = Markup(rendered(data, findings, detail=detail))
    guides = markup.find("dro-guide")
    if detail == "pro":
        assert not guides
        return
    assert len(guides) == 2
    assert len({guide["attrs"]["id"] for guide in guides}) == 2
    by_owner = {guide["attrs"]["data-setup-id"]: guide for guide in guides}
    assert set(by_owner) == {"L1", "S1"}
    assert "radius" in content(by_owner["L1"]) and "raise Z" not in content(by_owner["L1"])
    mill_guide = by_owner["S1"]
    mill_text = content(mill_guide)
    assert re.search(r"(?:clear vertically|raise Z only)", mill_text, re.IGNORECASE)
    assert re.search(
        r"return.*?before lowering.*?without another Axis Set", mill_text, re.IGNORECASE
    )
    if detail == "pedantic":
        later = physical_flow(markup, "S2")
        (pointer,) = markup.find("zero-guide", later)
        links = [node for node in descendants(markup, pointer) if node["tag"] == "a"]
        assert links
        for link in links:
            (target,) = [
                guide for guide in guides if "#" + guide["attrs"]["id"] == link["attrs"]["href"]
            ]
            assert target is mill_guide


def test_pedantic_missing_pickups_keep_owned_stops_without_guide_references():
    data = mill_job(setups=2)
    for setup in data.plan["setups"]:
        setup["presentation_group"] = setup["id"]
        setup.pop("zero")
    html = rendered(data, zero_recipe.evaluate(data), detail="pedantic")
    markup = Markup(html)
    assert not markup.find("dro-guide")
    assert not markup.find("zero-guide")
    evidence = decision_snapshot(html)
    for setup in data.plan["setups"]:
        assert ("block", "zero_check", "unknown", f"{setup['id']}:zero") in evidence


def test_pedantic_guide_starts_at_first_setup_with_an_actual_pickup():
    data = mill_job(setups=2)
    first, valid = data.plan["setups"]
    first.pop("zero")
    for setup in data.plan["setups"]:
        setup["presentation_group"] = setup["id"]
    html = rendered(data, zero_recipe.evaluate(data), detail="pedantic")
    markup = Markup(html)
    (guide,) = markup.find("dro-guide")
    assert guide["attrs"]["data-setup-id"] == valid["id"]
    assert "Axis Set" in content(guide) and "Preset" in content(guide)
    assert not markup.find("zero-guide", physical_flow(markup, first["id"]))
    assert markup.find("zero", physical_flow(markup, valid["id"]))
    assert ("block", "zero_check", "unknown", f"{first['id']}:zero") in decision_snapshot(html)


def test_pedantic_later_pickup_links_resolve_past_a_setup_without_pickups():
    data = mill_job(setups=3)
    first, empty, later = data.plan["setups"]
    empty.pop("zero")
    for setup in data.plan["setups"]:
        setup["presentation_group"] = setup["id"]
    html = rendered(data, zero_recipe.evaluate(data), detail="pedantic")
    markup = Markup(html)
    (guide,) = markup.find("dro-guide")
    assert guide["attrs"]["data-setup-id"] == first["id"]
    assert not markup.find("zero-guide", physical_flow(markup, empty["id"]))
    (pointer,) = markup.find("zero-guide", physical_flow(markup, later["id"]))
    links = [node for node in descendants(markup, pointer) if node["tag"] == "a"]
    assert links
    for link in links:
        href = link["attrs"]["href"]
        assert href.startswith("#")
        (target,) = [node for node in markup.nodes if node["attrs"].get("id") == href[1:]]
        assert target is guide
    assert ("block", "zero_check", "unknown", f"{empty['id']}:zero") in decision_snapshot(html)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("display_units", ["mm", "in"])
def test_authored_rough_turn_note_does_not_replace_canonical_numeric_operation_facts(
    detail, display_units
):
    note = "Rough the journal and stub together; retain the reference shoulder."
    op = {
        "op": 10,
        "do": "rough_turn",
        "feature": "body",
        "tool": "cutter",
        "z_from": 5.0,
        "z_to": -7.3,
        "rough_allowance_mm": 0.2,
        "doc_mm": 0.5,
        "passes": 4,
        "note": note,
    }
    data = lathe_operating_job([op])
    data.plan["dro"]["units"] = display_units
    finding = Finding(
        "speeds_feeds",
        "S1:10",
        "pass",
        {"rpm": 600.0, "feed_mm_rev": 0.05, "feed_mm_min": 30.0, "diameter_in": 6.55 / 25.4},
        [],
        "Evaluated turning settings",
    )
    markup = Markup(rendered(data, [finding], detail=detail))
    (instruction,) = markup.find("route-operation", physical_flow(markup, "S1"))
    text = content(instruction)
    assert note in text
    divisor = 25.4 if display_units == "in" else 1.0
    assert_coordinate(text, "Ø", 6.55 / divisor)
    for value in (0.2, 0.5):
        assert_number(text, value / divisor)
    assert "on Ø" in text and "radial per pass" in text and "4 passes" in text
    if display_units == "in":
        assert " mm" not in text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("allowance_key", ["rough_allowance_mm", "stock_to_leave_mm"])
@pytest.mark.parametrize("present", [False, True], ids=["absent", "explicit-zero"])
def test_compact_preparation_preserves_explicit_zero_allowance_without_inventing_one(
    detail, allowance_key, present
):
    data = mill_job(setups=1)
    setup = data.plan["setups"][0]
    op = {
        "op": 10,
        "do": "rough_profile",
        "feature": "hole",
        "tool": "cutter",
        "to_z": -6.35,
        "note": "Prepare the opposed reference faces before finishing.",
    }
    if present:
        op[allowance_key] = 0.0
    setup["ops"] = [op]
    data.inventory["tools"]["cutter"] = {"kind": "endmill", "dia_mm": 12.7}
    markup = Markup(rendered(data, detail=detail))
    (instruction,) = markup.find("route-operation", physical_flow(markup, setup["id"]))
    text = content(instruction)
    assert op["note"] in text
    assert bool(re.search(r"\bleave\s+0\b.*?\bper side\b", text)) is present


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("owner", ["path", "facing", "table"])
def test_compact_doc_qualifier_does_not_repeat_owned_paths_or_tables(detail, owner):
    data = mill_job(setups=1)
    setup = data.plan["setups"][0]
    op = {
        "op": 10,
        "do": "face" if owner == "facing" else "rough_profile",
        "feature": "hole",
        "tool": "cutter",
        "to_z": -6.35,
        "doc_mm": 3.175,
        "stock_to_leave_mm": 0.254,
        "note": "Retain the reference end.",
    }
    setup["ops"] = [op]
    data.inventory["tools"]["cutter"] = {"kind": "endmill", "dia_mm": 12.7}
    sheet = _Traveler(data, [], {}, None, detail=detail)
    rows = sheet.operation_rows(setup, {})
    sheet._rows_by_setup[setup["id"]] = rows
    if owner == "path":
        sheet._route_contours[setup["id"]] = {"10": ("Depths: Z-.125, then Z-.25.", "")}
    elif owner == "facing":
        sheet._route_facing_paths[(setup["id"], "10")] = ("0", "1", "0", "1", "0", "tangent")
        sheet._route_contours[setup["id"]] = {"10": ("Face Z-.25; maximum stepover 0.1.", "")}
    else:
        sheet._route_contours[setup["id"]] = {
            "10": (
                "",
                '<div class="route-path"><table><tr><td>Owned contour</td></tr></table></div>',
            )
        }
    markup = Markup(sheet.route_operation(setup, rows[0]))
    text = " ".join(content(node) for node in markup.find("route-operation"))
    assert "axial per pass" not in text
    assert "leave 0.01" in text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_doc_stays_with_its_setup_when_a_later_setup_reuses_the_op_id(detail):
    from test_sheet_ops import contour_records

    data = mill_job(setups=2)
    data.plan["dro"]["units"] = "mm"
    for setup in data.plan["setups"]:
        setup["note"] = "Keep the marked face uppermost."
        setup["ops"] = [
            {
                "op": 10,
                "do": "rough_profile",
                "feature": "hole",
                "tool": "cutter",
                "to_z": -0.6,
                "doc_mm": 0.25,
                "note": "Retain the reference end.",
            }
        ]
    data.inventory["tools"]["cutter"] = {"kind": "endmill", "dia_mm": 12.7}
    first, later = data.plan["setups"]
    coordinates = contour_records([-0.25, -0.5, -0.6])[("coordinates", "S1")]
    finding = Finding(
        "coordinates", later["id"], "pass", coordinates, [], "Evaluated cutter-centre path"
    )
    sheet = _Traveler(data, [finding], {}, None, detail=detail)
    blocks = {setup["id"]: sheet.setup_blocks(setup) for setup in data.plan["setups"]}
    family = Markup(sheet.family_html(data.plan["setups"], blocks))

    def assert_owned_path(instruction):
        text = content(instruction)
        assert "Centre:" in text
        for depth in coordinates["operations"][0]["z_levels"]["levels"]:
            assert_coordinate(text, "Z", depth)
        for stroke in coordinates["profiles"][0]["cutter_centre"]:
            for point in stroke:
                for value in point:
                    assert_number(text, value)

    (later_family_instruction,) = [
        node
        for node in family.find("route-operation")
        if any(
            owner["setup_id"] == later["id"] for owner in operation_owners(operation_owner(node))
        )
    ]
    assert_owned_path(later_family_instruction)
    (first_instruction,) = [
        node
        for node in family.find("route-operation")
        if any(
            owner["setup_id"] == first["id"] for owner in operation_owners(operation_owner(node))
        )
    ]
    assert "axial per pass" in content(first_instruction)
    assert_number(content(first_instruction), 0.25)
    (owner,) = operation_owners(operation_owner(first_instruction))
    assert owner["setup_id"] == first["id"] and str(owner["op_id"]) == "10"

    # Re-project the first row with the family-prelude entrypoint after the later
    # setup has materialized its contour. Do not invent an inspect operation with DOC.
    first_row = sheet._rows_by_setup[first["id"]][0]
    projected = Markup(
        sheet.route_operation(
            first,
            first_row,
            lead_in=f'<span class="route-prelude">{first["note"]} </span>',
        )
    )
    (instruction,) = projected.find("route-operation")
    assert "axial per pass" in content(instruction)
    assert_number(content(instruction), 0.25)

    later_row = sheet._rows_by_setup[later["id"]][0]
    later_markup = Markup(sheet.route_operation(later, later_row))
    (later_instruction,) = later_markup.find("route-operation")
    assert "axial per pass" not in content(later_instruction)
    assert_owned_path(later_instruction)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_alignment_is_due_owned_and_does_not_restore_model_pose_coordinates(detail):
    from test_hold_align import bundle as alignment_bundle
    from test_hold_align import setup as alignment_setup

    data = alignment_bundle(
        alignment_setup("V1", "vise", parallels_centres_mm=[[71.25, -9.5], [71.25, 9.5]]),
        alignment_setup("V2", "vise", parallels_centres_mm=[[71.25, -9.5], [71.25, 9.5]]),
    )
    for setup in data.plan["setups"]:
        setup["presentation_group"] = setup["id"]
    findings = hold_fields.evaluate(data)
    markup = Markup(rendered(data, findings, detail=detail))
    first, second = (physical_flow(markup, sid) for sid in ("V1", "V2"))
    text = content(first)
    assert "fixed jaw" in text and "X travel" in text and "test indicator" in text
    assert_number(text, 0.0254)
    assert_number(text, 100.0)
    assert "tighten and recheck" in text
    assert "Align the fixed jaw" not in content(second)
    assert "parallels at" not in content(job_page(markup))
    assert 71.25 not in numeric_values(content(job_page(markup)))


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_angle_plate_keeps_locating_base_and_face_placement(detail):
    from test_sheet_fixture import bundle as fixture_bundle

    data = fixture_bundle(
        [
            {
                "fixture": "angle",
                "pose": {"origin_mm": [10, 0, -5], "x": [0, 1, 0], "z": [0, 0, 1]},
            }
        ]
    )
    markup = Markup(rendered(data, detail=detail))
    text = content(physical_flow(markup, "S1"))
    assert re.search(r"underside at Z\s*[−-]95\b", text)
    assert re.search(r"working face at X\s*10\b.*?facing \+X", text)
    assert "two 1/2-13 T-bolts" in text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("kind", ["nest", "tapped-existing", "existing-only"])
def test_compact_construction_retains_only_actual_make_obligations_with_first_use_provenance(
    detail, kind
):
    from test_procedure_boxes import table_rows
    from test_sheet_fixture import IDENTITY, existing_tapped_fixture
    from test_sheet_fixture import bundle as fixture_bundle

    if kind == "tapped-existing":
        data = existing_tapped_fixture(2)
    else:
        data = fixture_bundle([{"fixture": "plate", "pose": IDENTITY}])
        if kind == "existing-only":
            data.inventory["fixtures"]["plate"]["shop_made"] = False
            for solid in data.inventory["fixtures"]["plate"]["solids"]:
                solid["supply"] = "existing"
    first = data.plan["setups"][0]
    first["presentation_group"] = first["id"]
    second = deepcopy(first)
    second.update(id="S2", presentation_group="S2")
    data.plan["setups"].append(second)
    html = rendered(data, detail=detail)
    markup = Markup(html)
    home = physical_flow(markup, "S1")
    later = physical_flow(markup, "S2")
    tables = markup.find("fixture", home)
    if kind == "existing-only":
        assert not tables
        assert "SHOP-MADE FIXTURE" not in content(home)
        return
    assert tables and not markup.find("fixture", later)
    home_text, table_text = content(home), " ".join(content(table) for table in tables)
    assert "Make before Setup S1" in home_text
    assert "not physical installed measurements" in home_text
    assert "SHOP-MADE FIXTURE table, Setup S1" in content(later)
    if kind == "nest":
        for value in (10.0, 20.0, 5.0):
            assert_number(table_text, value)
        (pin,) = [row for row in table_rows(html) if row[0] == "pin"]
        assert_coordinate(pin[1], "Ø", 6.0)
        assert_number(pin[1], 8.0)
        assert "M6 stud" in table_text
    else:
        assert "existing part: make the holes only" in table_text
        assert "Feature000" in table_text and "Feature001" in table_text
        assert_number(table_text, 100.0)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_saw_fallback_keeps_geometry_stop_typed_not_flattened_into_action(detail):
    data = mill_job(setups=1)
    setup = data.plan["setups"][0]
    data.inventory["tools"]["blade"] = {
        "kind": "slitting_saw",
        "name": "Finite saw",
        "dia_mm": 63.5,
        "kerf_mm": 1.0,
        "thickness_mm": 0.8,
    }
    setup["ops"] = [
        {
            "op": 20,
            "do": "cut_off",
            "tool": "blade",
            "cut_plane": {"axis": "z", "value": 8.5, "keep": "below"},
        }
    ]
    markup = Markup(rendered(data, detail=detail))
    (instruction,) = markup.find("route-operation", physical_flow(markup, setup["id"]))
    assert "STOP:" not in content(instruction)
    evidence = [
        entry
        for node in decision_nodes(markup)
        for entry in decision_evidence(node)
        if entry["source"] == "finite_saw" and entry["scope"] == f"{setup['id']}:20"
    ]
    assert evidence
    assert all(entry["status"] == "unknown" and entry["kind"] == "block" for entry in evidence)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("display_units", ["mm", "in"])
@pytest.mark.parametrize("shared", [True, False], ids=["shared", "local"])
def test_mounted_saw_positions_keep_contact_and_arbor_distinct_and_pro_axis_sets_numeric(
    detail, display_units, shared
):
    data, findings = mounted_jog_job("x", 2.75, "check_jog_mm")
    data.plan["dro"]["units"] = display_units
    mounted = {
        "point_mm": [-119.38, 7.62, 10.16],
        "axis_xy_mm": [-139.7, -2.54],
        "spindle_state": "stopped",
    }
    for setup, finding in zip(data.plan["setups"], findings, strict=True):
        setup["zero"]["z"]["mounted_saw"] = deepcopy(mounted)
        finding.numbers["axes"]["z"]["mounted_saw"] = deepcopy(mounted)
    if not shared:
        data.plan["setups"] = data.plan["setups"][:1]
        findings = findings[:1]
    setup = data.plan["setups"][0]
    sheet = _Traveler(data, findings, build_report(data, findings), None, detail=detail)
    if shared:
        markup = Markup(sheet.mounted_datum_table(setup))
        text = " ".join(content(node) for node in markup.nodes if node["tag"] == "p")
    else:
        sheet.dro(setup, {}, procedure="separate")
        text = "; ".join(sheet._route_datum_axes[setup["id"]].values())
    contact = re.search(r"Blade-body contact\s+(X[^\s;]+)", text)
    arbor = re.search(r"arbor axis\s+(X[^\s;]+)", text)
    assert contact and arbor, text
    divisor = 25.4 if display_units == "in" else 1.0
    for role, values in ((contact[1], mounted["point_mm"]), (arbor[1], mounted["axis_xy_mm"])):
        for axis, value in zip("XY", values[:2], strict=True):
            assert_coordinate(role, axis, value / divisor)
    for axis in ("x", "y"):
        (setting,) = re.findall(rf"Axis Set {axis.upper()}([+−-]?\d+(?:\.\d+)?)", text)
        assert float(setting.replace("−", "-")) == pytest.approx(
            findings[0].numbers["axes"][axis]["axis_set"] / divisor, abs=0.0001
        )
    if detail == "pro":
        assert "reversed" not in text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("field", ["point_mm", "axis_xy_mm"])
@pytest.mark.parametrize("state", ["missing", "nonfinite"])
def test_mounted_saw_missing_position_does_not_borrow_generic_pickup_or_invent_zero(
    detail, field, state
):
    data, findings = mounted_jog_job("x", 2.75, "check_jog_mm")
    data.plan["setups"] = data.plan["setups"][:1]
    finding = replace(findings[0], status="unknown")
    mounted = {"point_mm": [-119.38, 7.62, 10.16], "axis_xy_mm": [-139.7, -2.54]}
    if state == "missing":
        mounted.pop(field)
    else:
        mounted[field][0] = float("inf")
    finding.numbers["axes"]["z"]["mounted_saw"] = mounted
    original = deepcopy(finding.to_dict())
    setup = data.plan["setups"][0]
    # Exercise the native-record display guard directly: nonfinite records are
    # deliberately not serializable as public report JSON.
    sheet = _Traveler(data, [finding], {}, None, detail=detail)
    sheet.dro(setup, {}, procedure="separate")
    text = sheet._route_datum_axes[setup["id"]]["z"]
    label = "Blade-body contact" if field == "point_mm" else "arbor axis"
    (position,) = re.findall(re.escape(label) + r"\s+(X[^\s;]+)", text)
    assert position.startswith("X?")
    if state == "missing":
        assert "/Y?" in position
    assert "inf" not in position.casefold()
    assert sheet.finding_fact(finding).status == "unknown"
    assert finding.to_dict() == original


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_different_mounted_arbor_positions_remain_local_recipes(detail):
    data, findings = mounted_jog_job("x", 2.75, "check_jog_mm")
    for index, (setup, finding) in enumerate(zip(data.plan["setups"], findings, strict=True)):
        mounted = {
            "point_mm": [-119.38, 7.62, 10.16],
            "axis_xy_mm": [-139.7 - 25.4 * index, -2.54],
        }
        setup["zero"]["z"]["mounted_saw"] = deepcopy(mounted)
        finding.numbers["axes"]["z"]["mounted_saw"] = deepcopy(mounted)
    sheet = _Traveler(data, findings, build_report(data, findings), None, detail=detail)
    for index, setup in enumerate(data.plan["setups"]):
        assert sheet.mounted_datum_table(setup) is None
        sheet.dro(setup, {}, procedure="separate")
        text = sheet._route_datum_axes[setup["id"]]["z"]
        (axis_position,) = re.findall(r"arbor axis\s+(X[^\s;]+)", text)
        assert_coordinate(axis_position, "X", -139.7 - 25.4 * index)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("local_first", [False, True], ids=["family-only", "after-local-context"])
def test_shared_operation_restores_visible_family_scope_after_a_local_instruction(
    detail, local_first
):
    data, setups, findings = milling_family_job()
    first = setups[0]
    first["zero"] = {"procedure": "Pick up only this member's marked reference."}
    sheet, blocks, _ = collected_family(data, setups, findings, detail=detail)
    selected = {
        setup["id"]: [
            block
            for block in blocks[setup["id"]]
            if block.key == "operation:10"
            or local_first
            and setup is first
            and block.key == "datum-procedure"
        ]
        for setup in setups
    }
    markup = Markup(sheet.family_html(setups, selected))
    (common,) = [node for node in markup.find("family-common") if operation_owners(node)]
    expected = {setup["id"] for setup in setups}
    assert {owner["setup_id"] for owner in operation_owners(common)} == expected
    assert {str(owner["op_id"]) for owner in operation_owners(common)} == {"10"}
    labels = markup.find("variant-label", common)
    assert bool(labels) is local_first
    if local_first:
        assert {part.strip().rstrip(":") for part in content(labels[0]).split(",")} == expected
        local = [
            node
            for node in markup.find("setup-variant")
            if node["attrs"]["data-setup-id"] == first["id"]
        ]
        assert any(markup.nodes.index(node) < markup.nodes.index(common) for node in local)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_tap_chamfer_and_threaded_cutting_labels_do_not_relabel_reamer_geometry(detail):
    data = mill_job(setups=2)
    for setup, kind, action in zip(
        data.plan["setups"], ("tap", "reamer"), ("hand_tap", "ream"), strict=True
    ):
        data.inventory["tools"][kind] = {
            "kind": kind,
            "name": f"Selected {kind}",
            "dia_mm": 9.525,
            "lead_mm": 12.7,
            "flute_len_mm": 31.75,
        }
        setup["ops"] = [{"op": 10, "do": action, "tool": kind, "depth_mm": 8.0}]
    sheet = _Traveler(data, [], build_report(data, []), None, detail=detail)
    for setup in data.plan["setups"]:
        sheet.setup_blocks(setup)
    markup = Markup(sheet.settings_key())
    entries = {
        json.loads(node["attrs"]["data-physical-ops"])[0].split(":")[0]: content(node)
        for node in markup.find("tool-setting-entry")
    }
    tap, reamer = (entries[setup["id"]] for setup in data.plan["setups"])
    assert re.search(r"chamfer/lead length\s+0\.5\b", tap)
    assert re.search(r"threaded cutting length\s+1\.25\b", tap)
    assert re.search(r"\blead\s+0\.5\b", reamer)
    assert re.search(r"\bcutting\s+1\.25\b", reamer)
    assert "threaded cutting length" not in reamer and "chamfer/lead length" not in reamer


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_plain_unknown_criteria_keep_visible_identity_without_creating_result_fields(detail):
    data = bench_job()
    setup = data.plan["setups"][0]
    data.features["features"]["body"]["dia"] = "unknown"
    findings = inspection.evaluate(data)
    (target,) = op_check_targets(data, setup, setup["ops"][0])
    _, _, markup = collected_family(data, [setup], findings, detail=detail)
    (criterion,) = [
        node
        for node in markup.find("inspection-criterion")
        if target["subject"] in json.loads(node["attrs"]["data-inspection-ids"])
    ]
    text = content(criterion).casefold()
    assert "body" in text and "?" in text
    assert "ø" in text or "diameter" in text or "dia" in text
    assert not markup.find("checkpoint-result")
    assert not markup.find("writing-blank", criterion)


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_unknown_manual_contract_uses_human_criterion_not_a_fake_part_feature(detail):
    data, _, finals = inspection_family_job()
    data.features["acceptance"]["actual_slot_fit"]["contract"] = "unknown"
    setup = finals[0]
    targets = op_check_targets(data, setup, setup["ops"][0])
    (target,) = [
        target for target in targets if target["identity"]["requirement"] == "actual_slot_fit"
    ]
    _, _, markup = collected_family(data, [setup], inspection.evaluate(data), detail=detail)
    (criterion,) = [
        node
        for node in markup.find("inspection-criterion")
        if target["subject"] in json.loads(node["attrs"]["data-inspection-ids"])
    ]
    text = content(criterion).casefold()
    assert all(word in text for word in ("actual", "slot", "fit", "?"))
    assert not re.search(r"\bpart\b", text)
    assert not markup.find("writing-blank", criterion)
    assert all(
        target["subject"] not in json.loads(record["attrs"]["data-inspection-ids"])
        for record in [*markup.find("inspection-record"), *markup.find("checkpoint-result")]
    )


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_one_members_unknown_criterion_does_not_lend_its_marker_to_known_siblings(detail):
    data, _, finals = inspection_family_job()
    findings, known_subjects = [], set()
    unknown_subject = None
    for setup in finals:
        for target in op_check_targets(data, setup, setup["ops"][0]):
            is_length = target["identity"]["requirement"] == "length"
            unresolved = setup is finals[-1] and is_length
            if unresolved:
                unknown_subject = target["subject"]
            elif is_length:
                known_subjects.add(target["subject"])
            findings.append(
                Finding(
                    "inspection",
                    target["subject"],
                    "unknown" if unresolved else "pass",
                    {
                        key: target[key]
                        for key in (
                            "identity",
                            "setup_id",
                            "op_id",
                            "shared_check_id",
                            "covered_workpieces",
                        )
                    },
                    ["Synthetic inspection-plan evidence; not physical results"],
                    "Inspection plan incomplete" if unresolved else "Inspection plan complete",
                )
            )
    original = deepcopy([finding.to_dict() for finding in findings])
    _, _, markup = collected_family(data, finals, findings, detail=detail)
    length_criteria = [
        node
        for node in markup.find("inspection-criterion")
        if set(json.loads(node["attrs"]["data-inspection-ids"]))
        & (known_subjects | {unknown_subject})
    ]
    assert len(length_criteria) == 2
    (unknown,) = [
        node
        for node in length_criteria
        if unknown_subject in json.loads(node["attrs"]["data-inspection-ids"])
    ]
    assert set(json.loads(unknown["attrs"]["data-inspection-ids"])) == {unknown_subject}
    assert "?" in content(unknown)
    assert ancestor_with_class(unknown, "family-common") is None
    owner = ancestor_with_class(unknown, "setup-variant")
    assert owner is not None and owner["attrs"]["data-setup-id"] == finals[-1]["id"]
    (known,) = [node for node in length_criteria if node is not unknown]
    assert set(json.loads(known["attrs"]["data-inspection-ids"])) == known_subjects
    assert "?" not in content(known)
    assert len(markup.find("checkpoint-result")) == len(finals)
    assert [finding.to_dict() for finding in findings] == original


@pytest.mark.parametrize(
    "defect", ["mixed", "unknown", "contradictory", "wrong_start", "unproved_return"]
)
def test_facing_compaction_requires_uniform_entry_truth_and_same_proved_return(defect):
    sheet = _Traveler(mill_job(setups=1), [], {}, None, detail="hobby")
    segments = [[[-24.765, y], [110.49, y]] for y in (-12.7, 0.0)]
    entry = {
        "raster_profiles": [
            {
                "dro_to_z": 0.0,
                "cutter_centre": segments,
                "raster": {"cycle": "one_way", "run_axis": "x", "passes": 2, "lift_z": 4.1275},
            }
        ]
    }
    path = {
        "raise_z": 4.1275,
        "raise_clear": True,
        "entries": [{"xy": segment[0].copy(), "pass": True, "air": True} for segment in segments],
    }
    assert sheet.compact_facing_path(entry, path, [0.0]) is not None
    if defect == "mixed":
        path["entries"][1].update(air=False, contact="tangent")
    elif defect == "unknown":
        path["entries"][1]["air"] = "unknown"
    elif defect == "contradictory":
        path["entries"][1]["contact"] = "tangent"
    elif defect == "wrong_start":
        path["entries"][1]["xy"][0] += 0.1
    else:
        path["raise_clear"] = "unknown"
    assert sheet.compact_facing_path(entry, path, [0.0]) is None


@pytest.mark.parametrize("area_ends", [[-15.24, 100.965], None, [-15.24, 110.49]])
def test_raster_area_allowance_does_not_claim_tangent_stock_exit_is_clear(area_ends):
    data = mill_job(setups=1)
    setup = data.plan["setups"][0]
    data.kernel["setups"] = {
        setup["id"]: {"stock_bbox_mm": [-12.7, -20.0, -5.0, 100.965, 20.0, 0.0]}
    }
    sheet = _Traveler(data, [], {}, None, detail="hobby")
    profile = {
        "cutter_centre": [[[-24.765, 0.0], [110.49, 0.0]]],
        "raster": {
            "run_axis": "x",
            "ends": [-24.765, 110.49],
            "area_ends": area_ends,
            "clearance_mm": 9.525,
        },
    }
    text = sheet.raster_clearance(setup, profile)
    assert "enters from air at -X" in text
    assert "leaves into air" not in text
    assert "every pass runs in and out clear" not in text
    assert ("planned cut area" in text) is (area_ends == [-15.24, 100.965])
    data.kernel["setups"][setup["id"]]["stock_bbox_mm"] = None
    assert sheet.raster_clearance(setup, profile) == ""


@pytest.mark.parametrize("model_units", ["mm", "in"])
@pytest.mark.parametrize("end_in, clear", [(1.25, False), (1.5, False), (1.6, True)])
def test_raster_air_proof_uses_physical_radius_for_both_model_unit_systems(
    model_units, end_in, clear
):
    data = mill_job(setups=1)
    data.features["units"] = model_units
    setup = data.plan["setups"][0]
    data.kernel["setups"] = {setup["id"]: {"stock_bbox_mm": [-25.4, -25.4, -5.0, 25.4, 25.4, 0.0]}}
    scale = 25.4 if model_units == "mm" else 1.0
    end = end_in * scale
    profile = {
        "cutter_centre": [[[-end, 0.0], [end, 0.0]]],
        "raster": {
            "run_axis": "x",
            "ends": [-end, end],
            "area_ends": [-0.75 * scale, 0.75 * scale],
            "clearance_mm": 0.5 * scale,
            "open_side": "+y",
            "entry_pass": end,
        },
    }
    sheet = _Traveler(data, [], {}, None, detail="hobby")
    text = sheet.raster_clearance(setup, profile)
    assert bool(re.search(r"\b(?:air|clear)\b", text)) is clear
    assert ("every pass runs in and out clear" in text) is clear
    assert ("pass 1 enters from air" in text) is clear


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_shared_empty_criterion_ids_do_not_move_a_later_debt_to_the_wrong_requirement(detail):
    data, _, finals = inspection_family_job()
    for setup in finals:
        setup["ops"][0]["missing_requirements"] = {
            "depth": "gauges.calipers",
            "width": "gauges.calipers",
        }
    (debt,) = [
        finding
        for finding in inspection.evaluate(data)
        if finding.numbers.get("missing_requirement")
        and finding.numbers.get("setup_id") == finals[-1]["id"]
        and finding.numbers["identity"]["requirement"] == "width"
    ]
    _, _, markup = collected_family(data, finals, [debt], detail=detail)
    (criterion,) = [
        node
        for node in markup.find("inspection-criterion")
        if debt.subject in json.loads(node["attrs"]["data-inspection-ids"])
    ]
    text = content(criterion).casefold()
    assert "width" in text and "depth" not in text and "?" in text
    if detail == "pedantic":
        owner = ancestor_with_class(criterion, "setup-variant")
        assert owner is not None and owner["attrs"]["data-setup-id"] == finals[-1]["id"]
    else:
        assert ancestor_with_class(criterion, "family-common") is not None
    depths = [
        node
        for node in markup.find("inspection-criterion")
        if re.search(r"\bdepth\b", content(node), re.IGNORECASE)
    ]
    if detail == "pedantic":
        shown_owners = []
        for depth in depths:
            owner = ancestor_with_class(depth, "family-common") or ancestor_with_class(
                depth, "setup-variant"
            )
            assert owner is not None
            if "data-physical-ops" in owner["attrs"]:
                shown_owners.extend(
                    (item["setup_id"], item["workpiece"])
                    for item in json.loads(owner["attrs"]["data-physical-ops"])
                )
            else:
                shown_owners.append(
                    (owner["attrs"]["data-setup-id"], owner["attrs"]["data-workpiece"])
                )
        assert shown_owners == [
            (setup["id"], operation_members(data, setup, setup["ops"][0])[0]) for setup in finals
        ]
    else:
        assert len(depths) == 1
    for depth in depths:
        assert json.loads(depth["attrs"]["data-inspection-ids"]) == []
        assert "?" in content(depth)
    assert len(markup.find("checkpoint-result")) == len(finals)


def test_pedantic_plain_criterion_preserves_authored_writing_field_and_identity():
    from prechips.sheet import _Criterion, _ledger_row, _Row

    criterion = _Criterion(
        "? Body diameter unknown; record {bore_reading}.",
        subjects=("body:dia",),
    )
    row = _Row(
        ("10", "Body", "Micrometer", "Inspect", [criterion]),
        setup_id="B1",
        op_id=10,
    )
    markup = Markup(
        _ledger_row(row, ["step", "feature", "gauge", "action", "inspect"], detail="pedantic")
    )
    (visible,) = markup.find("inspection-criterion")
    assert json.loads(visible["attrs"]["data-inspection-ids"]) == ["body:dia"]
    (field,) = markup.find("field", visible)
    (blank,) = markup.find("writing-blank", field)
    assert content(blank) == ""
    assert "bore" in content(field).casefold() and "reading" in content(field).casefold()
    assert "{bore_reading}" not in content(visible)
    assert not markup.find("result-field")


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
@pytest.mark.parametrize("one_unknown", [False, True])
def test_interleaved_gauges_keep_visible_criterion_ids_and_member_unknowns_together(
    detail, one_unknown
):
    data, _, finals = inspection_family_job()
    data.inventory["gauges"]["alternate-calipers"] = {
        "kind": "caliper",
        "name": "Alternate calipers",
    }
    for setup in finals:
        setup["ops"][0].update(
            feature=["base-envelope", "shoulders"],
            checks={
                "base-envelope": {
                    "height": "gauges.calipers",
                    "width": "gauges.alternate-calipers",
                },
                "shoulders": {"thickness": "gauges.calipers"},
            },
            inspection_methods={},
        )
    targets = [
        (setup, target)
        for setup in finals
        for target in op_check_targets(data, setup, setup["ops"][0])
    ]
    assert [target["gauge"] for setup, target in targets if setup is finals[0]] == [
        "gauges.calipers",
        "gauges.alternate-calipers",
        "gauges.calipers",
    ]
    expected, findings, statuses = {}, [], {}
    unknown_subject = None
    for setup, target in targets:
        identity = target["identity"]
        status = (
            "unknown"
            if one_unknown and setup is finals[-1] and identity["requirement"] == "height"
            else "pass"
        )
        subject = target["subject"]
        expected[subject] = identity
        statuses[subject] = status
        if status == "unknown":
            unknown_subject = subject
        findings.append(
            plan_finding(
                subject,
                setup_id=setup["id"],
                op_id=target["op_id"],
                feature=identity["feature_owner"],
                requirement=identity["requirement"],
                member=identity["workpiece"],
                status=status,
            )
        )
    sheet, _, markup = collected_family(data, finals, findings, detail=detail)
    observed = []
    criteria = markup.find("inspection-criterion")
    for criterion in criteria:
        subjects = json.loads(criterion["attrs"]["data-inspection-ids"])
        assert subjects and all(subject in expected for subject in subjects)
        owners = {
            (expected[subject]["feature_owner"], expected[subject]["requirement"])
            for subject in subjects
        }
        assert len(owners) == 1
        feature, requirement = next(iter(owners))
        text = content(criterion).casefold()
        assert sheet.feature_name(feature).casefold() in text
        assert requirement in text
        states = {statuses[subject] for subject in subjects}
        assert len(states) == 1
        assert ("?" in text) is (states == {"unknown"})
        observed.extend(subjects)
    assert sorted(observed) == sorted(expected)
    assert len(markup.find("checkpoint-result")) == len(finals)
    if one_unknown:
        (unknown,) = [
            criterion
            for criterion in criteria
            if unknown_subject in json.loads(criterion["attrs"]["data-inspection-ids"])
        ]
        assert json.loads(unknown["attrs"]["data-inspection-ids"]) == [unknown_subject]
        owner = ancestor_with_class(unknown, "setup-variant")
        assert owner is not None and owner["attrs"]["data-setup-id"] == finals[-1]["id"]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("qualification", ["measured", "bare", "verify", "unknown"])
def test_compact_fixture_summary_keeps_selected_jaw_height_and_qualification(detail, qualification):
    from test_envelope_m5 import measured

    data = mill_job(setups=2)
    height = {
        "measured": measured(37.5),
        "bare": 37.5,
        "verify": {"value": 37.5, "verify": True},
        "unknown": "unknown",
    }[qualification]
    data.inventory["fixtures"] = {
        "selected-vise": {
            "kind": "vise",
            "name": "Selected summary vise",
            "jaw_height_mm": height,
        },
        "unused-vise": {
            "kind": "vise",
            "name": "Unused summary vise",
            "jaw_height_mm": measured(62.25),
        },
        "parallel-pair": {"kind": "parallels", "height_mm": measured(12.7)},
    }
    data.inventory["tools"]["cutter"] = {"kind": "endmill", "dia_mm": 5.0}
    for setup in data.plan["setups"]:
        setup.setdefault("hold", {})["fixture"] = "selected-vise"
        setup["hold"]["parallels"] = "parallel-pair"
        setup["ops"] = [{"op": 70, "do": "rough_profile", "tool": "cutter", "to_z": -0.5}]
    markup = Markup(rendered(data, detail=detail))
    (summary,) = [
        node
        for node in markup.nodes
        if node["tag"] == "p"
        and content(node).lstrip().startswith("Fixtures")
        and "Selected summary vise" in content(node)
    ]
    text = content(summary)
    assert "Unused summary vise" not in text
    assert 62.25 not in numeric_values(text)
    assert 40.0 not in numeric_values(text)
    (jaw_fact,) = re.findall(r"\bjaw height\s+([^)]*)", text)
    if qualification == "unknown":
        assert "?" in jaw_fact
        assert 37.5 not in numeric_values(jaw_fact)
    else:
        assert_number(jaw_fact, 37.5)
        assert "mm" in jaw_fact
        assert ("?" in jaw_fact) is (qualification == "verify")


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("parallels", ["none", "not_applicable"])
def test_compact_powered_saw_fixture_without_parallels_has_no_jaw_height_basis(detail, parallels):
    data = mill_job(setups=2)
    data.inventory["fixtures"] = {
        "selected-vise": {
            "kind": "vise",
            "name": "Selected powered-saw vise",
            "jaw_height_mm": 37.5,
        }
    }
    data.inventory["machines"]["saw"] = {"kind": "bandsaw", "name": "Powered cutoff saw"}
    data.inventory["tools"]["blade"] = {"kind": "bandsaw", "kerf_mm": 1.5}
    for setup in data.plan["setups"]:
        setup["machine"] = "saw"
        setup["hold"] = {"fixture": "selected-vise", "parallels": parallels}
        setup["ops"] = [
            {
                "op": 10,
                "do": "cut_off",
                "tool": "blade",
                "cut_plane": {"axis": "x", "value": 20.0, "keep": "below"},
            }
        ]
    markup = Markup(rendered(data, detail=detail))
    (summary,) = [
        node
        for node in markup.nodes
        if node["tag"] == "p"
        and content(node).lstrip().startswith("Fixtures")
        and "Selected powered-saw vise" in content(node)
    ]
    assert "jaw height" not in content(summary).casefold()
    assert 37.5 not in numeric_values(content(summary))
