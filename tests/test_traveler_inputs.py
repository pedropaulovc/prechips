"""Traveler presentation inputs never replace authored facts or readiness evidence."""

import hashlib
import tomllib
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from test_input_contracts import PLAN, bundle_files

import prechips.cli as cli
import prechips.kernel as kernel
from prechips.findings import Finding
from prechips.inputs import BadInput, load_bundle
from prechips.model import (
    TRAVELER_DETAILS,
    Feature,
    Frame,
    Hold,
    NoteSegment,
    Operation,
    Plan,
    Setup,
    Source,
    note_text,
)
from prechips.report import build_report, report_hash

SEGMENTS = [
    {"text": "Pedantic first.", "detail": "pedantic"},
    {"text": "  Core instruction.  ", "detail": "pro"},
    {"text": "Hobby explanation.", "detail": "hobby"},
    {"text": "Core conclusion.", "detail": "pro"},
]


def plan_data():
    return tomllib.loads(PLAN)


def grouped_plan():
    data = plan_data()
    first = data["setups"][0]
    first["presentation_group"] = "Repeat inspection"
    first["ops"].append({"op": 20, "do": "inspect", "feature": "subject"})
    second = deepcopy(first)
    second["id"] = "S2"
    data["setups"].append(second)
    return data


@pytest.fixture
def tracing():
    return SimpleNamespace(
        span=lambda *args, **kwargs: nullcontext(),
        log=Mock(),
        flush=Mock(),
    )


@pytest.mark.parametrize("owner", [Setup, Hold, Operation])
@pytest.mark.parametrize("value", ["", "  ", "unknown", "An unchanged plain note.", SEGMENTS])
def test_authored_notes_preserve_strings_and_segment_records(owner, value):
    parsed = owner.model_validate({"note": deepcopy(value)})
    assert parsed.model_dump(exclude_unset=True)["note"] == value


@pytest.mark.parametrize("owner", [Setup, Hold, Operation])
def test_absent_note_stays_sparse_and_unresolved(owner):
    parsed = owner.model_validate({})
    assert parsed.note == "unknown"
    assert "note" not in parsed.model_dump(exclude_unset=True)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"text": "Read it."},
        {"detail": "pro"},
        {"text": "", "detail": "pro"},
        {"text": " \t ", "detail": "pro"},
        {"text": "unknown", "detail": "pro"},
        {"text": " unknown ", "detail": "pro"},
        {"text": 12, "detail": "pro"},
        {"text": True, "detail": "pro"},
        {"text": None, "detail": "pro"},
        {"text": "Read it.", "detail": "expert"},
        {"text": "Read it.", "detail": "unknown"},
        {"text": "Read it.", "detail": None},
        {"text": "Read it.", "detail": "pro", "extra": True},
    ],
)
def test_note_segments_require_strict_known_text_and_explicit_detail(value):
    with pytest.raises(ValidationError):
        NoteSegment.model_validate(value)


@pytest.mark.parametrize("owner", [Setup, Hold, Operation])
@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        True,
        [],
        ["plain"],
        [None],
        [{}],
        [SEGMENTS[0], {"text": "missing detail"}],
        {"text": "Not a list.", "detail": "pro"},
    ],
)
def test_malformed_authored_notes_are_not_coerced_or_silently_dropped(owner, value):
    with pytest.raises(ValidationError):
        owner.model_validate({"note": value})


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("pro", "  Core instruction.   Core conclusion."),
        ("hobby", "  Core instruction.   Hobby explanation. Core conclusion."),
        ("pedantic", "Pedantic first.   Core instruction.   Hobby explanation. Core conclusion."),
    ],
)
@pytest.mark.parametrize("representation", ["dict", "model", "mixed"])
def test_note_text_filters_by_minimum_detail_without_sorting_or_mutating(
    detail, expected, representation
):
    values = deepcopy(SEGMENTS)
    if representation == "model":
        values = [NoteSegment.model_validate(value) for value in values]
    elif representation == "mixed":
        values[1] = NoteSegment.model_validate(values[1])
    before = deepcopy(values)
    assert note_text(values, detail=detail) == expected
    assert values == before
    assert note_text(values) == note_text(values, detail="pedantic")


@pytest.mark.parametrize("value", [None, "", "unknown", " Exact spacing. \n"])
def test_note_text_plain_values_are_unchanged_at_every_detail(value):
    for detail in TRAVELER_DETAILS:
        assert note_text(value, detail=detail) == ("" if value is None else value)


def test_note_text_all_hidden_is_empty_not_unknown():
    assert note_text([{"text": "Explanation only.", "detail": "pedantic"}], detail="pro") == ""


@pytest.mark.parametrize("detail", [None, "", "expert", "PRO", 1, [], {}])
@pytest.mark.parametrize("value", [None, "plain", SEGMENTS])
def test_note_text_rejects_invalid_detail_before_any_passthrough(detail, value):
    with pytest.raises(ValueError, match="^detail must be pro, hobby, or pedantic$"):
        note_text(value, detail=detail)


@pytest.mark.parametrize(
    "value",
    [
        [],
        (),
        {},
        3,
        True,
        ["text"],
        [None],
        [{}],
        [{"text": "unknown", "detail": "pedantic"}],
        [SEGMENTS[1], {"text": "Hidden malformed entry.", "detail": "invalid"}],
    ],
)
def test_note_text_validates_even_hidden_segments(value):
    with pytest.raises(ValueError):
        note_text(value, detail="pro")


@pytest.mark.parametrize("purpose", ["shop", "demonstration"])
def test_plan_purpose_is_explicit_and_sparse_default_stays_shop(purpose):
    data = plan_data()
    omitted = Plan.model_validate(data)
    assert omitted.purpose == "shop"
    assert "purpose" not in omitted.model_dump(exclude_unset=True)
    data["purpose"] = purpose
    parsed = Plan.model_validate(data)
    assert parsed.purpose == purpose
    assert parsed.model_dump(exclude_unset=True)["purpose"] == purpose


@pytest.mark.parametrize("purpose", [None, "unknown", "demo", "", True, []])
def test_plan_purpose_rejects_non_contract_values(purpose):
    with pytest.raises(ValidationError):
        Plan.model_validate(plan_data() | {"purpose": purpose})


def test_grouped_setups_preserve_distinct_physical_members_and_notes():
    data = grouped_plan()
    data["setups"][0]["note"] = SEGMENTS
    data["setups"][1]["note"] = "Second physical setup, not an alias."
    parsed = Plan.model_validate(data).model_dump(exclude_unset=True)
    assert parsed["setups"] == data["setups"]
    assert [setup["id"] for setup in parsed["setups"]] == ["S1", "S2"]


@pytest.mark.parametrize("group", ["", " \t ", "unknown", " unknown ", "S1", "S2", None, []])
def test_presentation_group_must_be_known_and_distinct_from_all_setup_ids(group):
    data = grouped_plan()
    for setup in data["setups"]:
        setup["presentation_group"] = group
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        "singleton",
        "noncontiguous",
        "machine",
        "unknown-machine",
        "blank-machine",
        "omitted-machine",
        "op-number",
        "action",
        "order",
        "shorter",
        "unknown-ops",
        "unknown-number",
        "unknown-action",
        "blank-action",
    ],
)
def test_presentation_group_rejects_incomplete_or_different_ladders(mutation):
    data = grouped_plan()
    first, second = data["setups"]
    if mutation == "singleton":
        second.pop("presentation_group")
    elif mutation == "noncontiguous":
        middle = deepcopy(first)
        middle["id"] = "Middle"
        middle.pop("presentation_group")
        data["setups"].insert(1, middle)
    elif mutation == "machine":
        second["machine"] = "another-mill"
    elif mutation in {"unknown-machine", "blank-machine", "omitted-machine"}:
        for setup in data["setups"]:
            if mutation == "omitted-machine":
                setup.pop("machine")
            else:
                setup["machine"] = "unknown" if mutation == "unknown-machine" else " "
    elif mutation == "op-number":
        second["ops"][0]["op"] = 11
    elif mutation == "action":
        second["ops"][0]["do"] = "drill"
    elif mutation == "order":
        second["ops"].reverse()
    elif mutation == "shorter":
        second["ops"].pop()
    elif mutation == "unknown-ops":
        second["ops"] = "unknown"
    else:
        for setup in data["setups"]:
            if mutation == "unknown-number":
                setup["ops"][0]["op"] = "unknown"
            else:
                setup["ops"][0]["do"] = "unknown" if mutation == "unknown-action" else " "
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


@pytest.mark.parametrize("panels", [[], ["holding"], ["cut", "holding"]])
def test_picture_panel_selection_preserves_authored_order_and_explicit_empty(panels):
    data = plan_data()
    data["setups"][0]["picture_panels"] = panels
    assert (
        Plan.model_validate(data).model_dump(exclude_unset=True)["setups"][0]["picture_panels"]
        == panels
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_picture_panels_absent_or_unknown_remains_unresolved(explicit):
    data = plan_data()
    if explicit:
        data["setups"][0]["picture_panels"] = "unknown"
    parsed = Plan.model_validate(data).setups[0]
    assert parsed.picture_panels == "unknown"
    assert ("picture_panels" in parsed.model_dump(exclude_unset=True)) is explicit
    assert "presentation_group" not in parsed.model_dump(exclude_unset=True)


@pytest.mark.parametrize(
    "panels",
    [
        None,
        "holding",
        [""],
        [" "],
        ["unknown"],
        [" unknown "],
        ["holding", "holding"],
        [1],
        [True],
        [None],
        {},
    ],
)
def test_picture_panels_rejects_malformed_or_duplicate_known_identities(panels):
    data = plan_data()
    data["setups"][0]["picture_panels"] = panels
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_loading_preserves_segmented_authorship_and_exact_source_digest(tmp_path):
    authored = (
        '[{text = "Core instruction.", detail = "pro"}, '
        '{text = "Hidden explanation.", detail = "pedantic"}]'
    )
    source = PLAN.replace('hold = "unknown"', f"hold = {{note = {authored}}}")
    source = source.replace("[[setups.ops]]", f"note = {authored}\n[[setups.ops]]")
    source += f"note = {authored}\n"
    path = bundle_files(tmp_path, source)
    bundle = load_bundle(path)
    expected = tomllib.loads(source)["setups"][0]
    setup = bundle.plan["setups"][0]
    assert setup["note"] == expected["note"]
    assert setup["hold"]["note"] == expected["hold"]["note"]
    assert setup["ops"][0]["note"] == expected["ops"][0]["note"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert bundle.hashes["plan"] == bundle.input_records["plan"]["sha256"] == digest
    report = build_report(bundle, [], assets={})
    for detail in TRAVELER_DETAILS:
        note_text(setup["note"], detail=detail)
        assert build_report(bundle, [], assets={}) == report
        assert setup["note"] == expected["note"]
    changed = source.replace("Hidden explanation.", "Changed hidden explanation.")
    path.write_text(changed, encoding="utf-8")
    other = load_bundle(path)
    assert note_text(other.plan["setups"][0]["note"], detail="pro") == note_text(
        setup["note"], detail="pro"
    )
    assert other.hashes["plan"] != digest
    assert build_report(other, [], assets={})["hash"] != report["hash"]


@pytest.mark.parametrize(("status", "expected_exit"), [("pass", 0), ("error", 2), ("unknown", 4)])
def test_report_purpose_disclosure_binds_hash_without_changing_readiness(
    tmp_path, status, expected_exit
):
    bundle = load_bundle(bundle_files(tmp_path))
    bundle = replace(bundle, policy={"required": {"inspection": "*"}})
    findings = [Finding("inspection", "subject", status, {}, [], "Synthetic gate evidence.")]
    before = deepcopy(bundle.plan)
    sparse = build_report(bundle, findings, assets={})
    shop = build_report(
        replace(bundle, plan=bundle.plan | {"purpose": "shop"}), findings, assets={}
    )
    demo = build_report(
        replace(bundle, plan=bundle.plan | {"purpose": "demonstration"}), findings, assets={}
    )
    assert "purpose" not in sparse
    assert shop == sparse
    assert demo["purpose"] == "demonstration"
    assert demo["expected_exit"] == sparse["expected_exit"] == expected_exit
    assert (
        demo["verification"]
        == sparse["verification"]
        == ("checked" if expected_exit == 0 else "planned")
    )
    assert demo["findings"] == sparse["findings"] == [findings[0].to_dict()]
    assert demo["inputs"] == sparse["inputs"]
    assert demo["hash"] == report_hash(demo)
    assert demo["hash"] != sparse["hash"]
    without_disclosure = {key: value for key, value in demo.items() if key != "purpose"}
    assert report_hash(without_disclosure) == sparse["hash"]
    assert {key: value for key, value in demo.items() if key not in {"purpose", "hash"}} == {
        key: value for key, value in sparse.items() if key != "hash"
    }
    assert bundle.plan == before


@pytest.mark.parametrize(
    "argv",
    [
        ["traveler", "plan.toml", "--detail", "expert"],
        ["traveler", "plan.toml", "--detail", "PRO"],
        ["traveler", "plan.toml", "--detail"],
        ["check", "plan.toml", "--detail", "pro"],
        ["compare", "plan.toml", "--detail", "hobby"],
        ["tools", "--detail", "pedantic"],
        ["explain", "report.json", "inspection", "--detail", "pro"],
        ["--detail", "pro", "traveler", "plan.toml"],
    ],
)
def test_cli_invalid_detail_boundaries_exit_three_before_loading_or_outputs(
    tmp_path, monkeypatch, capsys, tracing, argv
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.telemetry, "configure", lambda verb: tracing)
    run = Mock(side_effect=AssertionError("Invalid argparse input must not run a verb"))
    monkeypatch.setattr(cli, "_run", run)
    with pytest.raises(BadInput):
        cli.build_parser().parse_args(argv)
    assert cli.main(argv) == 3
    assert not tuple(tmp_path.iterdir())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage" in captured.err.lower()


@pytest.mark.parametrize("owner", [Feature, Frame, Source])
def test_other_note_fields_remain_plain_strings_not_authored_segments(owner):
    for value in ("", "unknown", "Unchanged source prose."):
        assert owner.model_validate({"note": value}).note == value
    with pytest.raises(ValidationError):
        owner.model_validate({"note": SEGMENTS})


@pytest.mark.parametrize("field", ["detail", "traveler_detail", "preference"])
def test_presentation_detail_is_not_a_plan_input_or_preference(field):
    with pytest.raises(ValidationError, match=field):
        Plan.model_validate(plan_data() | {field: "pro"})


@pytest.mark.parametrize(
    "authored",
    [
        "[]",
        '[{text = "unknown", detail = "pro"}]',
        '[{text = "Hidden malformed text.", detail = "expert"}]',
        '[{text = "Missing detail."}]',
    ],
)
def test_cli_malformed_note_schema_exits_three_before_native_or_output(
    tmp_path, monkeypatch, tracing, authored
):
    source = PLAN + f"note = {authored}\n"
    path = bundle_files(tmp_path, source)
    out = tmp_path / "out"
    monkeypatch.setattr(cli.telemetry, "configure", lambda verb: tracing)
    build = Mock(side_effect=AssertionError("Invalid schema must not build a native job"))
    native = Mock(side_effect=AssertionError("Invalid schema must not run native work"))
    monkeypatch.setattr(kernel, "build_job", build)
    monkeypatch.setattr(kernel, "run_geometries", native)
    assert cli.main(["traveler", str(path), "--out", str(out)]) == 3
    build.assert_not_called()
    native.assert_not_called()
    assert not out.exists()
    tracing.log.assert_called_once()
