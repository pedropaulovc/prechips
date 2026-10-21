"""Retained-piece route identity, shop arrival wording and independent native proof."""

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_batch_material_routes import batch

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.material_routes import MaterialGraph, setup_lineage, stock_ancestry
from prechips.sheet import _Traveler

VALIDATOR = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/validate_examples.py")
)


@pytest.fixture
def retained_plan():
    return {
        "part": "retained-route-fixture",
        "features": "features.toml",
        "stock": {"form": "round_bar"},
        "setups": [
            {"id": "P1", "stock_in": "stock", "ops": []},
            {
                "id": "P3",
                "stock_in": "P1",
                "ops": [
                    {
                        "op": 30,
                        "do": "part_off",
                        "outputs": {
                            "cone": {"carries": "cone-body"},
                            "tube": {"carries": "tube-body"},
                        },
                    }
                ],
            },
            {"id": "C1", "stock_in": "stock_out.cone", "ops": []},
            {"id": "T2", "stock_in": "stock_out.tube", "ops": []},
            {
                "id": "A1",
                "stock_in": ["C1", "T2"],
                "joint": {"kind": "cylindrical"},
                "ops": [],
            },
        ],
    }


def sheet_for(plan):
    bundle = Bundle(
        plan=plan,
        features={},
        inventory={},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path(__file__).resolve().parent,
    )
    return _Traveler(bundle, [], {}, None)


def native_facts():
    return {
        "status": "ok",
        "setups": {
            "P3": {
                "outputs": {
                    "cone": {
                        "carries": "cone-body",
                        "finished_solid": "cone-solid",
                        "partition": "P3:30",
                        "bbox_mm": [0, 0, 0, 10, 2, 3],
                        "volume_mm3": 60,
                    },
                    "tube": {
                        "carries": "tube-body",
                        "finished_solid": "tube-solid",
                        "partition": "P3:30",
                        "bbox_mm": [10, 0, 0, 20, 2, 3],
                        "volume_mm3": 60,
                    },
                }
            },
            "A1": {
                "stock_bbox_mm": [0, 0, 0, 20, 2, 3],
                "completed_joint_features": [],
            },
        },
    }


def stock_stop_sheet(plan, sid, reason):
    sheet = sheet_for(plan)
    sheet.bundle = SimpleNamespace(kernel={"setups": {sid: {"stock_reason": reason}}})
    sheet.features = {}
    sheet.findings = [
        Finding("consistency", sid, "unknown", {}, [], "Incoming stock is unresolved.")
    ]
    sheet.setup_findings = lambda setup: sheet.findings
    sheet.bench = lambda value: value
    setup = next(setup for setup in plan["setups"] if setup["id"] == sid)
    return sheet, setup


def test_magic_sibling_routes_keep_one_original_bar_and_actual_producer_history(retained_plan):
    graph = MaterialGraph(retained_plan, validate=True)
    assert graph.roots("A1") == frozenset({"stock"})
    assert stock_ancestry(retained_plan)["stock_out.cone"] == frozenset({"stock"})
    assert setup_lineage(retained_plan, "C1") == {"P1", "P3", "C1"}
    assert setup_lineage(retained_plan, "A1") == {"P1", "P3", "C1", "T2", "A1"}
    assert (
        VALIDATOR["carry_route"](retained_plan, retained_plan["setups"][-1])
        == retained_plan["setups"]
    )


@pytest.mark.parametrize("sid,piece", [("C1", "cone"), ("T2", "tube")])
def test_arrival_names_the_selected_piece_and_the_original_bar(retained_plan, sid, piece):
    setup = next(setup for setup in retained_plan["setups"] if setup["id"] == sid)
    arrival = sheet_for(retained_plan).arrival(setup)
    assert (
        arrival == f"the {piece} retained piece (parted in Setup P3), from the original round bar"
    )
    assert "stock_out." not in arrival


def test_assembly_arrival_never_invents_two_independent_supplies(retained_plan):
    arrival = sheet_for(retained_plan).arrival(retained_plan["setups"][-1])
    assert "cone retained piece from Setup C1" in arrival
    assert "tube retained piece from Setup T2" in arrival
    assert "both from the same original round bar" in arrival
    assert arrival.count("original round bar") == 1
    assert "stock_out." not in arrival
    assert "independent" not in arrival


@pytest.mark.parametrize(
    "sid,piece,split",
    [
        ("E1", "nut1 b", "C1a"),
        ("E2", "nut2 b", "C1b"),
        ("E3", "nut3 b", "C2"),
        ("E4", "nut4 b", "C2"),
    ],
)
def test_nested_arrival_selects_each_final_child_not_an_ancestor_remainder(sid, piece, split):
    plan = batch()
    setup = next(setup for setup in plan["setups"] if setup["id"] == sid)
    arrival = sheet_for(plan).arrival(setup)
    assert piece in arrival
    assert f"Setup {split}" in arrival
    assert "lower1" not in arrival and "lower2" not in arrival
    assert all(f"nut{index} b" not in arrival for index in range(1, 5) if sid != f"E{index}")


@pytest.mark.parametrize(
    "sid,pieces",
    [
        ("C1", ["bar remnant"]),
        ("T2", ["tube blank"]),
        ("A1", ["bar remnant", "tube blank"]),
    ],
)
def test_retained_arrival_humanizes_output_labels_without_changing_route_identity(
    retained_plan, sid, pieces
):
    outputs = retained_plan["setups"][1]["ops"][0]["outputs"]
    retained_plan["setups"][1]["ops"][0]["outputs"] = {
        "bar_remnant": outputs["cone"],
        "tube_blank": outputs["tube"],
    }
    retained_plan["setups"][2]["stock_in"] = "stock_out.bar_remnant"
    retained_plan["setups"][3]["stock_in"] = "stock_out.tube_blank"
    before = json.dumps(retained_plan, sort_keys=True)
    setup = next(setup for setup in retained_plan["setups"] if setup["id"] == sid)

    arrival = sheet_for(retained_plan).arrival(setup)

    for piece in pieces:
        assert f"the {piece} retained piece" in arrival
    assert "bar_remnant" not in arrival
    assert "tube_blank" not in arrival
    assert json.dumps(retained_plan, sort_keys=True) == before


@pytest.mark.parametrize(
    "refs", [["C1", "C1"], ["C1", "stock_out.cone"], ["C1", "stock"], ["C1", "P3"]]
)
def test_validator_rejects_overlapping_or_reused_material_not_sibling_roots(retained_plan, refs):
    retained_plan["setups"][-1]["stock_in"] = refs
    assert VALIDATOR["carry_route"](retained_plan, retained_plan["setups"][-1]) is None


def test_named_output_keeps_the_actual_upstream_stock_stopper(retained_plan):
    sheet = sheet_for(retained_plan)
    receiver = retained_plan["setups"][2]
    reason = "P3:30 retained output geometry is unresolved"
    sheet.bundle = SimpleNamespace(
        kernel={
            "setups": {
                "C1": {"stock_reason": reason},
                "P3": {"stock_out_reason": reason},
            }
        }
    )
    sheet.setup_findings = lambda setup: [
        Finding("consistency", setup["id"], "unknown", {}, [], reason)
    ]
    dependency = sheet.stock_dependency(receiver)
    assert dependency["source"] is retained_plan["setups"][1]
    assert dependency["op"] is retained_plan["setups"][1]["ops"][0]


@pytest.mark.parametrize(
    "cap_name,body_name,piece_labels",
    [
        ("cap_return", "body_blank", "body blank and cap return"),
        ("bar_remnant", "tube_blank", "bar remnant and tube blank"),
    ],
)
@pytest.mark.parametrize("sid", ["A1", "A2", "A3"])
@pytest.mark.parametrize(
    "reason",
    [
        "stock_in sibling partition geometry is unproven",
        "A diagnostic with no source name or operation number",
    ],
)
def test_unproven_sibling_stock_stop_identifies_actual_cut_and_pieces(
    retained_plan, sid, reason, cap_name, body_name, piece_labels
):
    producer = retained_plan["setups"][1]
    producer["id"] = "S9"
    parting = producer["ops"][0]
    parting["op"] = 70
    outputs = parting["outputs"]
    parting["outputs"] = {
        cap_name: outputs["cone"],
        body_name: outputs["tube"],
    }
    retained_plan["setups"][2]["stock_in"] = f"stock_out.{cap_name}"
    retained_plan["setups"][3]["stock_in"] = f"stock_out.{body_name}"
    retained_plan["setups"].extend(
        [
            {"id": "A2", "stock_in": "A1", "ops": []},
            {"id": "A3", "stock_in": "A2", "ops": []},
        ]
    )
    sheet, setup = stock_stop_sheet(retained_plan, sid, reason)
    sheet.bundle.kernel["setups"]["S9"] = {
        "outputs": {
            cap_name: {"reason": "Output registration is unresolved"},
            body_name: {"reason": "Output registration is unresolved"},
        }
    }
    before = json.dumps([retained_plan, sheet.bundle.kernel], sort_keys=True)

    stop = sheet.upstream_stock_stop(setup)

    assert "stock not established" in stop
    assert "part-off in Setup S9 op 70" in stop
    assert f"both required pieces ({piece_labels})" in stop
    assert "assembled workpiece before cutting" in stop
    assert "reissue this traveler" in stop
    assert reason not in stop
    assert cap_name not in stop
    assert body_name not in stop
    assert json.dumps([retained_plan, sheet.bundle.kernel], sort_keys=True) == before


@pytest.mark.parametrize("proof", ["missing", "partial", "wrong_partition", "reason"])
def test_sibling_stock_stop_requires_both_matching_native_partition_records(retained_plan, proof):
    reason = "Entry geometry is unresolved"
    sheet, setup = stock_stop_sheet(retained_plan, "A1", reason)
    records = native_facts()["setups"]["P3"]["outputs"]
    if proof == "missing":
        records = {}
    elif proof == "partial":
        del records["tube"]
    elif proof == "wrong_partition":
        records["tube"]["partition"] = "P3:99"
    else:
        records["tube"]["reason"] = "This output is unresolved"
    sheet.bundle.kernel["setups"]["P3"] = {"outputs": records}

    stop = sheet.upstream_stock_stop(setup)

    assert "part-off in Setup P3 op 30" in stop
    assert "both required pieces (cone and tube)" in stop
    assert "before cutting" in stop
    assert "reissue" in stop
    assert reason not in stop


def test_proved_sibling_partition_preserves_independent_join_failure(retained_plan):
    reason = "Prepared shoulders cannot be seated in the declared joining pose"
    sheet, setup = stock_stop_sheet(retained_plan, "A1", reason)
    sheet.bundle.kernel["setups"]["P3"] = native_facts()["setups"]["P3"]

    assert sheet.upstream_stock_stop(setup) == (
        "Setup-entry stock not established — "
        + reason
        + "; resolve the upstream stock prerequisite and reissue this traveler."
    )


@pytest.mark.parametrize("route", ["single_child", "independent_supply"])
def test_stock_stop_does_not_invent_sibling_cut_context(retained_plan, route):
    reason = "The input workpiece has no established geometry"
    if route == "single_child":
        sid = "C1"
    else:
        sid = "A1"
        retained_plan["stock"]["components"] = [{"id": "extra"}]
        retained_plan["setups"][-1]["stock_in"] = ["C1", "stock.extra"]
    sheet, setup = stock_stop_sheet(retained_plan, sid, reason)

    assert sheet.upstream_stock_stop(setup) == (
        "Setup-entry stock not established — "
        + reason
        + "; resolve the upstream stock prerequisite and reissue this traveler."
    )


def test_sibling_stock_stop_preserves_an_exported_source_operation(retained_plan):
    reason = "P3:30 actual retained output geometry is unresolved"
    sheet, setup = stock_stop_sheet(retained_plan, "A1", reason)
    sheet.bundle.kernel["setups"]["P3"] = {"stock_out_reason": reason}

    stop = sheet.upstream_stock_stop(setup)

    assert "Depends on Setup P3 op 30" in stop
    assert reason in stop
    assert "both required pieces" not in stop


@pytest.mark.parametrize("has_unknown", [False, True])
def test_sibling_stock_presentation_never_downgrades_or_hides_known_error(
    retained_plan, has_unknown
):
    reason = "Missing native split geometry"
    sheet, setup = stock_stop_sheet(retained_plan, "A1", reason)
    if not has_unknown:
        sheet.findings.clear()
    failure = "Known thread size mismatch prevents the declared assembly"
    sheet.findings.append(Finding("joint_thread", "A1", "error", {}, [], failure))
    before = json.dumps([finding.to_dict() for finding in sheet.findings], sort_keys=True)

    prerequisite = sheet.upstream_stock_stop(setup)
    stops, cautions, topics = sheet.status_lines(sheet.findings, setup)
    if prerequisite:
        stops.append(prerequisite)
    html = sheet.status_boxes(stops, cautions, topics)

    assert failure in stops
    assert "STOP" in html
    assert failure in html
    assert json.dumps([finding.to_dict() for finding in sheet.findings], sort_keys=True) == before
    if has_unknown:
        assert topics
        assert "both required pieces (cone and tube)" in html
    else:
        assert prerequisite is None
        assert topics == []


@pytest.mark.parametrize("identity", [None, "", "unknown"])
def test_sibling_stock_stop_preserves_unresolved_rendering_identity(retained_plan, identity):
    retained_plan["setups"][-1]["id"] = identity
    reason = "Incoming material has not been established"
    sheet, setup = stock_stop_sheet(retained_plan, identity, reason)

    assert sheet.upstream_stock_stop(setup) == (
        "Setup-entry stock not established — "
        + reason
        + "; resolve the upstream stock prerequisite and reissue this traveler."
    )


def test_named_output_flip_uses_the_splitting_setup_frame(retained_plan):
    retained_plan["setups"][1]["ops"][0]["outputs"]["cone"]["pose"] = {
        "origin": [0, 0, 0],
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
        "binding": "Declared retained-piece registration",
        "cite": "Source registration",
    }
    retained_plan["frames"] = {
        "before": {"origin": [0, 0, 0], "z": [0, 0, 1], "x": [1, 0, 0], "y": [0, 1, 0]},
        "after": {"origin": [0, 0, 0], "z": [0, 0, -1], "x": [-1, 0, 0], "y": [0, -1, 0]},
    }
    retained_plan["setups"][1]["frame"] = "before"
    receiver = retained_plan["setups"][2]
    receiver["frame"] = "after"
    sheet = sheet_for(retained_plan)
    sheet.bundle = SimpleNamespace(plan=retained_plan, features={})
    sheet.lathe = lambda setup: True
    assert sheet.flip(receiver) == "Turn the part end for end. "


@pytest.mark.parametrize(
    "pose,expected",
    [
        ("unknown", ""),
        (
            {
                "origin": [5, 0, 0],
                "x": [-1, 0, 0],
                "y": [0, 1, 0],
                "z": [0, 0, -1],
                "binding": "Declared retained-piece registration",
                "cite": "Source registration",
            },
            "",
        ),
        (
            {
                "origin": [5, 0, 0],
                "x": [0, 1, 0],
                "y": [-1, 0, 0],
                "z": [0, 0, 1],
                "binding": "Declared retained-piece registration",
                "cite": "Source registration",
            },
            "Turn the part over: the other face up, the +X end moves to −Y. ",
        ),
        (
            {
                "origin": [0, 0, 0],
                "x": [1, 0, 0],
                "y": [0, 1, 0],
                "z": [0, 0, 1],
                "binding": "unknown",
            },
            "",
        ),
    ],
)
def test_named_output_flip_requires_and_applies_registered_pose(retained_plan, pose, expected):
    retained_plan["setups"][1]["ops"][0]["outputs"]["cone"]["pose"] = pose
    retained_plan["frames"] = {
        "before": {"origin": [0, 0, 0], "z": [0, 0, 1], "x": [1, 0, 0], "y": [0, 1, 0]},
        "after": {"origin": [0, 0, 0], "z": [0, 0, -1], "x": [1, 0, 0], "y": [0, -1, 0]},
    }
    retained_plan["setups"][1]["frame"] = "before"
    receiver = retained_plan["setups"][2]
    receiver["frame"] = "after"
    sheet = sheet_for(retained_plan)
    sheet.bundle = SimpleNamespace(plan=retained_plan, features={})
    sheet.lathe = lambda setup: False
    assert sheet.flip(receiver) == expected


@pytest.mark.parametrize("source", ["P3", "stock_out.cone"])
def test_prepared_blank_checks_remain_on_actual_handoff_setup(retained_plan, source):
    retained_plan["setups"][2]["stock_in"] = source
    retained_plan["stock"]["prepared"] = {
        "setup": "C1",
        "methods": {"flat": "Check the retained face on the surface plate"},
    }
    sheet = sheet_for(retained_plan)
    sheet.bench = lambda value, setup: value
    checks = sheet.blank_checks(retained_plan["setups"][1])
    assert "CHECK THE BLANK — before SETUP C1" in checks
    assert "File the edge burrs off and wipe the blank first." in checks
    assert "Check the retained face on the surface plate" in checks
    assert sheet.blank_checks(retained_plan["setups"][0]) == ""


def test_legacy_flip_wording_does_not_require_an_output_pose(retained_plan):
    retained_plan["frames"] = {
        "before": {"z": [0, 0, 1], "x": [1, 0, 0]},
        "after": {"z": [0, 0, -1], "x": [-1, 0, 0]},
    }
    retained_plan["setups"][1]["frame"] = "before"
    receiver = retained_plan["setups"][2]
    receiver.update(stock_in="P3", frame="after")
    sheet = sheet_for(retained_plan)
    sheet.bundle = SimpleNamespace(plan=retained_plan, features={})
    sheet.lathe = lambda setup: True
    assert sheet.flip(receiver) == "Turn the part end for end. "


@pytest.mark.parametrize(
    "debt", ["missing", "reason", "descriptor", "zero-volume", "nonfinite-box"]
)
def test_join_never_passes_on_partition_identity_without_native_proof(retained_plan, debt):
    facts = native_facts()
    outputs = facts["setups"]["P3"]["outputs"]
    if debt == "missing":
        outputs.pop("cone")
    elif debt == "reason":
        outputs["cone"]["reason"] = "whole-solid containment unknown"
    elif debt == "descriptor":
        outputs["cone"] = {"roots": ["stock"], "partitions": [{"split": "P3", "output": "cone"}]}
    elif debt == "zero-volume":
        outputs["cone"]["volume_mm3"] = 0
    else:
        outputs["cone"]["bbox_mm"][0] = float("nan")
    status, _ = VALIDATOR["kernel_join"](lambda: facts, retained_plan["setups"][-1], retained_plan)
    assert status == "unknown"


def test_join_can_use_both_native_proven_sibling_outputs(retained_plan):
    facts = native_facts()
    status, numbers = VALIDATOR["kernel_join"](
        lambda: facts, retained_plan["setups"][-1], retained_plan
    )
    assert status == "pass"
    assert numbers["stock_in"] == ["C1", "T2"]
    facts["setups"]["A1"]["assembly_error"] = "posed pieces overlap"
    status, _ = VALIDATOR["kernel_join"](lambda: facts, retained_plan["setups"][-1], retained_plan)
    assert status == "error"


@pytest.mark.parametrize("proven", [False, True])
def test_blank_cut_reads_only_the_selected_native_output_not_the_parent_compound(
    retained_plan, proven
):
    facts = native_facts()
    facts["setups"]["P3"].update(stock_out_bbox_mm=[0, 0, 0, 20, 2, 3], stock_out_volume_mm3=120)
    if not proven:
        facts["setups"]["P3"]["outputs"]["cone"] = {"reason": "unresolved partition"}
    numbers = {}
    status = VALIDATOR["blank_cut"](
        retained_plan,
        lambda: facts,
        "C1",
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[0, 10], [0, 2], [0, 3]],
        [0, 0, 0],
        numbers,
    )
    assert status == ("pass" if proven else "unknown")
    if proven:
        assert numbers["cut_box_mm"] == [[0, 10], [0, 2], [0, 3]]
        assert numbers["cut_volume_mm3"] == 60
    else:
        assert "cut_box_mm" not in numbers


def test_a_transient_parent_end_face_is_not_credited_to_each_child(retained_plan):
    retained_plan["process_features"] = {
        "entry-face": {
            "kind": "end_face",
            "at": [0, 0, 0],
            "axis": [1, 0, 0],
            "cite": "test preparation face",
        }
    }
    retained_plan["setups"][0]["ops"] = [{"op": 10, "do": "face", "feature": "entry-face"}]
    status, numbers, missing = VALIDATOR["derive_prepared_blank"](
        retained_plan, {"units": "mm", "features": {}}, {}, {"setup": "C1"}, native_facts
    )
    assert status == "unknown"
    assert numbers["made_by"] == []
    assert numbers["made_material_unknown"]
    assert not missing


@pytest.mark.parametrize(
    "source,expected",
    [
        ("stock", "the stock blank"),
        ("stock.body", "the body blank"),
        ("S1", "part as it arrives from Setup S1"),
        ("unknown", "? unknown stock"),
    ],
)
def test_legacy_monolithic_arrival_wording_is_unchanged(source, expected):
    plan = {"setups": [{"id": "S1", "stock_in": "stock", "ops": []}]}
    assert sheet_for(plan).arrival({"id": "S2", "stock_in": source}) == expected


def test_legacy_sequential_component_assembly_wording_is_unchanged():
    plan = {
        "stock": {"components": [{"id": "body"}, {"id": "boss"}, {"id": "cap"}]},
        "setups": [
            {"id": "S1", "stock_in": "stock.body"},
            {"id": "S2", "stock_in": "stock.boss"},
            {"id": "S3", "stock_in": ["S1", "S2"]},
            {"id": "S4", "stock_in": "stock.cap"},
            {"id": "S5", "stock_in": ["S3", "S4"]},
        ],
    }
    sheet = sheet_for(plan)
    assert sheet.arrival(plan["setups"][2]) == "parts from Setup S1 and Setup S2 joined"
    assert sheet.arrival(plan["setups"][-1]) == (
        "the body + boss assembly (joined in Setup S3) and the cap from Setup S4, "
        "joined here (adds the cap to that assembly)"
    )


@pytest.mark.parametrize("selected", [False, True])
def test_retained_output_stock_stopper_must_belong_to_the_selected_branch(retained_plan, selected):
    sheet = sheet_for(retained_plan)
    receiver = retained_plan["setups"][2]
    reason = "P3:30 retained output cannot be established"
    output = "cone" if selected else "tube"
    sheet.bundle = SimpleNamespace(
        kernel={
            "setups": {
                "C1": {"stock_reason": reason},
                "P3": {"outputs": {output: {"reason": reason}}},
            }
        }
    )
    sheet.setup_findings = lambda setup: [
        Finding("consistency", setup["id"], "unknown", {}, [], reason)
    ]
    dependency = sheet.stock_dependency(receiver)
    assert (dependency["source"] is retained_plan["setups"][1]) is selected
    if not selected:
        assert dependency["source"] is None
        assert dependency["op"] is None


@pytest.mark.parametrize("proven", [False, True])
def test_prepared_retained_blank_never_uses_the_original_bar_box(retained_plan, proven):
    retained_plan["stock"].update(
        form="rectangular_blank",
        axis=[1, 0, 0],
        section_axis=[0, 1, 0],
        origin_mm=[0, 0, 0],
        section_mm=[2, 3],
        length_mm=20,
    )
    prepared = {
        "setup": "C1",
        "origin_mm": [0, 0, 0],
        "section_mm": [2, 3],
        "length_mm": 10,
        "tolerance_mm": [0, 0, 0],
    }
    facts = native_facts()
    if not proven:
        facts["setups"]["P3"]["outputs"]["cone"] = {"reason": "native split unresolved"}
    status, numbers, missing = VALIDATOR["derive_prepared_blank"](
        retained_plan, {"units": "mm", "features": {}}, {}, prepared, lambda: facts
    )
    # Undeclared gauges stay unknown even after a proven geometric split.
    assert status == "unknown"
    assert not missing
    assert "received_box_mm" not in numbers
    if proven:
        assert numbers["cut_box_mm"] == [[0, 10], [0, 2], [0, 3]]
    else:
        assert "cut_box_mm" not in numbers


@pytest.fixture(params=["die_thread", "hand_tap"])
def manual_thread_validator_inputs(request):
    action = request.param
    plan = {
        "part": "hand-thread-fixture",
        "features": "features.toml",
        "setups": [
            {
                "id": "S1",
                "machine": "bench",
                "hold": {},
                "ops": [
                    {
                        "op": 10,
                        "do": action,
                        "feature": "thread",
                        "tool": "hand-cutter",
                        "holder": "hand-holder",
                    },
                    {"op": 20, "do": "inspect", "feature": "thread"},
                ],
            }
        ],
    }
    features = {
        "frames": {},
        "features": {
            "thread": {
                "kind": "external_thread" if action == "die_thread" else "thread",
                "faces": "unknown",
                "requirements": [],
            }
        },
    }
    inventory = {"machines": {"bench": {"kind": "bench"}}}
    return plan, features, inventory


def _validator_domain_rows(domains):
    """Supply unrelated report rows; target subjects are asserted explicitly below."""
    return {
        (rule, subject): {"status": "unknown", "numbers": {}}
        for rule, subjects in domains.items()
        for subject in subjects
    }


def test_validator_manual_thread_tool_domain_excludes_plain_inspection(
    manual_thread_validator_inputs,
):
    plan, features, inventory = manual_thread_validator_inputs
    entries = VALIDATOR["Entries"](inventory)
    domains = VALIDATOR["rule_subjects"](plan, features, entries, lambda rule: {})
    assert "S1:10" in domains["tool_resolves"]
    assert "S1:20" not in domains["tool_resolves"]
    rows = _validator_domain_rows(domains)
    check = VALIDATOR["check_required_coverage"]
    check({"required": {}}, plan, features, rows, entries, lambda rule: {})
    del rows["tool_resolves", "S1:10"]
    with pytest.raises(ValueError, match="missing findings.*tool_resolves.*S1:10"):
        check({"required": {}}, plan, features, rows, entries, lambda rule: {})


def test_validator_inspection_cannot_borrow_a_manual_thread_tool_subject(
    manual_thread_validator_inputs,
):
    plan, features, inventory = manual_thread_validator_inputs
    entries = VALIDATOR["Entries"](inventory)
    domains = VALIDATOR["rule_subjects"](plan, features, entries, lambda rule: {})
    rows = _validator_domain_rows(domains)
    rows["tool_resolves", "S1:20"] = {"status": "pass", "numbers": {}}
    with pytest.raises(ValueError, match="tool_resolves:S1:20: no supported check"):
        VALIDATOR["check_required_coverage"](
            {"required": {}}, plan, features, rows, entries, lambda rule: {}
        )


def test_validator_subject_check_requires_hand_tool_row_and_holder(manual_thread_validator_inputs):
    plan, features, inventory = manual_thread_validator_inputs
    rows = {
        **{
            (rule, "thread"): {"status": "unknown", "numbers": {}}
            for rule in VALIDATOR["FEATURE_RULES"] | {"inspection"}
        },
        **{(rule, "S1"): {"status": "unknown", "numbers": {}} for rule in VALIDATOR["SETUP_RULES"]},
        **{
            (rule, f"S1:{op}"): {"status": "unknown", "numbers": {}}
            for rule in ("speeds_feeds", "turning_deflection", "engagement")
            for op in (10, 20)
        },
        ("tool_resolves", "S1:10"): {"status": "unknown", "numbers": {}},
    }
    bench = {
        "machine": "bench",
        "machine_kind": "bench",
        "operations": [
            {"op": 10, "do": plan["setups"][0]["ops"][0]["do"]},
            {"op": 20, "do": "inspect"},
        ],
        "joint_method": "not_applicable",
    }
    for rule in ("zero_check", "coordinates", "headroom"):
        rows[rule, "S1"] = {"status": "not_applicable", "numbers": bench}
    check = VALIDATOR["check_subjects"]
    check(plan, features, rows, inventory)
    missing = rows.pop(("tool_resolves", "S1:10"))
    with pytest.raises(ValueError, match="missing finding.*tool_resolves.*S1:10"):
        check(plan, features, rows, inventory)
    rows["tool_resolves", "S1:10"] = missing
    del plan["setups"][0]["ops"][0]["holder"]
    with pytest.raises(ValueError, match="omitted manual thread holder"):
        check(plan, features, rows, inventory)


def test_validator_threaded_joint_has_its_own_required_domain(retained_plan):
    retained_plan["setups"][-1]["joint"] = {
        "kind": "threaded",
        "socket": "tube-thread",
        "spigot": "cone-thread",
        "process": "Screw the two retained pieces together by hand",
        "cite": "Synthetic route fixture",
        "engagement_mm": "unknown",
        "seat": "unknown",
    }
    features = {"features": {}, "frames": {}}
    inventory = {
        "machines": {"fixture-lathe": {"kind": "lathe", "verify": True}},
        "tools": {"parting-cutter": {"kind": "unknown", "verify": True}},
        "holders": {"parting-holder": {"kind": "unknown", "verify": True}},
    }
    for setup in retained_plan["setups"]:
        setup["machine"] = "fixture-lathe"
    retained_plan["setups"][1]["ops"][0].update(tool="parting-cutter", holder="parting-holder")
    entries = VALIDATOR["Entries"](inventory)
    bundle = SimpleNamespace(plan=retained_plan, features=features, inventory=inventory)

    def checked(rule):
        if rule.name != "joint_thread":
            return {}
        return {row.subject: json.loads(json.dumps(row.to_dict())) for row in rule.evaluate(bundle)}

    rule = next(rule for rule in VALIDATOR["CHECKER_RULES"] if rule.name == "joint_thread")
    thread_row = checked(rule)["A1"]
    assert thread_row["status"] == "unknown"
    assert thread_row["numbers"]["unmodeled_geometry"] == [
        "helical flanks",
        "lead/runout",
        "prepared shoulder seating",
    ]
    domains = VALIDATOR["rule_subjects"](retained_plan, features, entries, checked)
    assert domains["joint_thread"] == {"A1"}
    assert domains["joint_fit"] == set()
    rows = _validator_domain_rows(domains)
    rows["joint_thread", "A1"] = thread_row
    check = VALIDATOR["check_required_coverage"]
    check({"required": {}}, retained_plan, features, rows, entries, checked)
    del rows["joint_thread", "A1"]
    with pytest.raises(ValueError, match="missing findings.*joint_thread.*A1"):
        check({"required": {}}, retained_plan, features, rows, entries, checked)
    rows["joint_thread", "A1"] = {**thread_row, "status": "pass"}
    with pytest.raises(ValueError, match="joint_thread:A1: not the checker's own row"):
        check({"required": {}}, retained_plan, features, rows, entries, checked)


def test_validator_threaded_join_cannot_pass_a_synthetic_native_bbox(retained_plan):
    retained_plan["setups"][-1]["joint"] = {
        "kind": "threaded",
        "socket": "tube-thread",
        "spigot": "cone-thread",
    }
    facts = native_facts()
    joined = retained_plan["setups"][-1]
    status, numbers = VALIDATOR["kernel_join"](lambda: facts, joined, retained_plan)
    assert status == "unknown"
    assert numbers["joint"] == "threaded"
    rows = {
        ("joint_assembly", "A1"): {"status": status, "numbers": numbers},
        ("joint_thread", "A1"): {
            "status": "unknown",
            "numbers": {
                "socket": "tube-thread",
                "spigot": "cone-thread",
                "violations": [],
                "unmodeled_geometry": [
                    "helical flanks",
                    "lead/runout",
                    "prepared shoulder seating",
                ],
            },
        },
    }
    check = VALIDATOR["check_joint_declarations"]
    # A threaded assembly owes no cylindrical joint_fit report row.
    check(retained_plan, {"features": {}}, rows, lambda: facts)
    rows["joint_thread", "A1"]["status"] = "pass"
    with pytest.raises(ValueError, match="unmodeled threaded geometry cannot approve"):
        check(retained_plan, {"features": {}}, rows, lambda: facts)


@pytest.mark.parametrize("identity", [None, "", "unknown"])
def test_incomplete_rendering_route_names_no_known_arrival_or_causal_owner(retained_plan, identity):
    target = retained_plan["setups"][-1]
    target["id"] = identity
    sheet = sheet_for(retained_plan)
    assert sheet.arrival(target) == "? unknown stock route; setup identity unresolved"
    reason = "P3:30 unresolved retained partition"
    sheet.bundle = SimpleNamespace(kernel={"setups": {identity: {"stock_reason": reason}}})
    sheet.setup_findings = lambda setup: [
        Finding("consistency", identity, "unknown", {}, [], "Setup-entry stock is unresolved.")
    ]
    assert sheet.stock_dependency(target) == {"reason": reason, "source": None, "op": None}
