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
        and "parallels/grip" in content(node).casefold()
    ]
    (parallel_reference,) = holding
    assert json.loads(parallel_reference["attrs"]["data-setup-members"]) == ["S1", "S2", "S3"]
    for value in (12.7, 7.62):
        assert_number(content(parallel_reference), value)
    assert content(job_page(markup)).casefold().count("parallels/grip") == 1
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
        return
    (reference,) = references
    assert reference["attrs"]["data-reference-only"] == "true"
    assert json.loads(reference["attrs"]["data-execute-after"]) == ["B2a", "B2b", "B2c", "B2d"]
    assert any(
        re.search(r"\bcomplete\s+only\s+after\s+B2\b", content(node), re.IGNORECASE)
        for node in descendants(markup, reference)
        if node["tag"] in ("p", "h1", "h2", "h3", "h4", "h5", "h6")
    )
    reference_nodes = list(descendants(markup, reference))
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


@pytest.mark.parametrize("display_units", ["mm", "in"])
def test_hobby_facing_table_keeps_all_native_pass_centres_and_clear_return(display_units):
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
                        {"xy": segment[0], "pass": True, "air": False, "contact": "tangent"}
                        for segment in profile["cutter_centre"]
                    ],
                }
            ],
        }
        findings.append(Finding("coordinates", sid, "pass", numbers, [], "Native facing path"))
    markup = Markup(rendered(data, findings, detail="hobby"))
    (table,) = markup.find("facing-paths")
    rows = [
        node
        for node in descendants(markup, table)
        if node["tag"] == "tr" and node["attrs"].get("data-setup-id") in native
    ]
    assert [row["attrs"]["data-setup-id"] for row in rows] == list(native)
    formatter = _Traveler(data, [], {}, None, detail="hobby")
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
        (cycle,) = markup.find("facing-cycle", table["parent"])
        context = content(cycle)
        assert_coordinate(context, "Z", float(formatter.readout(profile["raster"]["lift_z"])))
        assert re.search(r"\bone.way\b", context, re.IGNORECASE)
        assert re.search(r"\b(?:lift|raise)\b.*\breturn\b", context, re.IGNORECASE)
