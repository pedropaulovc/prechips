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
from test_sheet_inspection_targets import inspection_job
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
    return [
        owner
        for owner in owners
        if isinstance(owner, dict) and owner.get("op_id") is not None
    ]


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


def settings_text(markup, row):
    """Separate table cells as the browser does, rather than joining drill500."""
    cells = [
        node
        for node in markup.nodes
        if node["parent"] is row and node["tag"] in ("td", "th")
    ]
    assert cells
    return " ".join(content(cell) for cell in cells)


def assert_displayed_block(markup, owner, message):
    """Check the notice, not the ledger wrapper that aggregates its evidence."""
    if "data-decision" in owner["attrs"]:
        assert owner["attrs"]["data-decision"] == "block"
        assert "stop" in owner["attrs"]["class"].split()
        assert "caution" not in owner["attrs"]["class"].split()
    else:
        assert "operation" in owner["attrs"]["class"].split()
        (notice,) = [
            node for node in markup.find("box", owner) if message in content(node)
        ]
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
        for record in markup.nodes
        if "data-inspection-ids" in record["attrs"]
        for identity in json.loads(record["attrs"]["data-inspection-ids"])
    ]
    assert missing.subject not in identities
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
    findings = zero_recipe.evaluate(data)
    assert findings[0].status == "pass"
    finder = findings[0].numbers["axes"]["x"]["finder"]
    radius_in = finder["radius_mm"] / 25.4
    assert radius_in == pytest.approx(tip_in / 2)
    for detail in ("hobby", "pedantic"):
        markup = Markup(rendered(data, findings, detail=detail))
        (guide,) = [node for node in markup.nodes if node["attrs"].get("id") == "dro-first-use"]
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
    assert not any(node["attrs"].get("id") == "dro-first-use" for node in pro.nodes)


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
                assert_number(settings_text(markup, settings), value)
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
        settings = [
            node for node in settings_markup.nodes
            if "data-physical-ops" in node["attrs"]
        ]
        owned = [
            node
            for node in settings
            if json.loads(node["attrs"]["data-physical-ops"]) == [f"{last['id']}:10"]
        ]
        assert len(owned) == 1
        assert_number(settings_text(settings_markup, owned[0]), findings[-1].numbers["rpm"])
        unchanged = [
            node
            for node in settings
            if set(json.loads(node["attrs"]["data-physical-ops"]))
            == {f"{setup['id']}:10" for setup in finals[:-1]}
        ]
        assert len(unchanged) == 1
        assert_number(settings_text(settings_markup, unchanged[0]), findings[0].numbers["rpm"])
    elif changed_field == "feature":
        expected = sheet.feature_label(last["ops"][0]["feature"], marked=False)
        assert any(expected in content(variant) for variant in variants)
        assert not any(
            expected in content(common) for common in markup.find("family-common")
        )
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
    (heading,) = [node for node in markup.nodes if node["tag"] == "h1"]
    assert " ".join(content(heading).split()).casefold() == data.plan["part"].replace("-", " ")
    assert data.plan["drawing"]["number"] not in content(heading)
    assert data.plan["drawing"]["revision"] not in content(heading)
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
def test_selected_numeric_acceptance_prints_once_at_its_physical_inspection_not_in_a_global_table(
    detail,
):
    data = bench_job()
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
    assert {
        (owner["setup_id"], str(owner["op_id"]))
        for owner in operation_owners(operation)
    } == {(data.plan["setups"][0]["id"], str(data.plan["setups"][0]["ops"][0]["op"]))}
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
            sheet.records[("headroom", "S1")] = headroom(
                tip_above_jaws=gap, jaw_top_z=-0.5 - gap
            )

    (box,) = sheet.crash_boxes(setup, setup["ops"][0])
    assert box.kind == kind
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
    (notice,) = [
        node for node in decision_nodes(markup) if evidence in decision_evidence(node)
    ]
    assert notice["attrs"]["data-decision"] == kind
    assert ("stop" in notice["attrs"]["class"].split()) == (kind == "block")
    assert ("caution" in notice["attrs"]["class"].split()) == (kind == "caution")


@pytest.mark.parametrize("detail", TRAVELER_DETAILS)
def test_tnut_final_family_keeps_every_size_method_and_typed_fit_clause(detail):
    data = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"
    )
    finals = [
        setup for setup in data.plan["setups"] if setup["id"] in ("F1a", "F1b", "F1c", "F1d")
    ]
    assert [setup["id"] for setup in finals] == ["F1a", "F1b", "F1c", "F1d"]
    _, _, markup = collected_family(data, finals, detail=detail)
    expected_owners = {
        ("F1a", "nut1"),
        ("F1b", "nut2"),
        ("F1c", "nut3"),
        ("F1d", "nut4"),
    }
    records = markup.find("checkpoint-result")
    assert len(records) == 4
    assert {
        (record["attrs"]["data-setup-id"], record["attrs"]["data-workpiece"])
        for record in records
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
        for clause in (
            "Slides freely by hand in the actual intended slot "
            "without binding or objectionable rocking.",
            "Both shoulder shelves bear under the lips without bottoming or wedging.",
            "Pulled-up top remains below the table top.",
            "The intended 3/8-16 right-hand stud enters from the top by hand.",
            "Bottom-thread deformation stops the stud before it exits onto the table; "
            "do not force it through.",
            "The nut does not rotate or pass through the intended slot "
            "during the functional check.",
        ):
            assert clause in criteria_text
