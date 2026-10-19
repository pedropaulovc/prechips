"""Retained-piece route identity, shop arrival wording and independent native proof."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.material_routes import MaterialGraph, setup_lineage, stock_ancestry
from prechips.sheet import _Traveler

VALIDATOR = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/validate_examples.py"))


@pytest.fixture
def retained_plan():
    return {
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
    sheet = _Traveler.__new__(_Traveler)
    sheet.plan = plan
    return sheet


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


def test_magic_sibling_routes_keep_one_original_bar_and_actual_producer_history(retained_plan):
    graph = MaterialGraph(retained_plan, validate=True)
    assert graph.roots("A1") == frozenset({"stock"})
    assert stock_ancestry(retained_plan)["stock_out.cone"] == frozenset({"stock"})
    assert setup_lineage(retained_plan, "C1") == {"P1", "P3", "C1"}
    assert setup_lineage(retained_plan, "A1") == {"P1", "P3", "C1", "T2", "A1"}
    assert {(atom.split, atom.output) for atom in graph.nodes["A1"]} == {
        ("P3", "cone"),
        ("P3", "tube"),
    }
    assert VALIDATOR["carry_route"](retained_plan, retained_plan["setups"][-1]) == retained_plan["setups"]


@pytest.mark.parametrize("sid,piece", [("C1", "cone"), ("T2", "tube")])
def test_arrival_names_the_selected_piece_and_the_original_bar(retained_plan, sid, piece):
    setup = next(setup for setup in retained_plan["setups"] if setup["id"] == sid)
    arrival = sheet_for(retained_plan).arrival(setup)
    assert arrival == f"the {piece} retained piece (parted in Setup P3), from the original round bar"
    assert "stock_out." not in arrival


def test_assembly_arrival_never_invents_two_independent_supplies(retained_plan):
    arrival = sheet_for(retained_plan).arrival(retained_plan["setups"][-1])
    assert "cone retained piece from Setup C1" in arrival
    assert "tube retained piece from Setup T2" in arrival
    assert "both from the same original round bar" in arrival
    assert arrival.count("original round bar") == 1
    assert "stock_out." not in arrival
    assert "independent" not in arrival


@pytest.mark.parametrize("refs", [["C1", "C1"], ["C1", "stock_out.cone"], ["C1", "stock"], ["C1", "P3"]])
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
    sheet.setup_findings = lambda setup: [{"status": "unknown"}]
    dependency = sheet.stock_dependency(receiver)
    assert dependency["source"] is retained_plan["setups"][1]
    assert dependency["op"] is retained_plan["setups"][1]["ops"][0]


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
        "before": {
            "origin": [0, 0, 0], "z": [0, 0, 1], "x": [1, 0, 0], "y": [0, 1, 0]
        },
        "after": {
            "origin": [0, 0, 0], "z": [0, 0, -1], "x": [-1, 0, 0], "y": [0, -1, 0]
        },
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
        "before": {
            "origin": [0, 0, 0], "z": [0, 0, 1], "x": [1, 0, 0], "y": [0, 1, 0]
        },
        "after": {
            "origin": [0, 0, 0], "z": [0, 0, -1], "x": [1, 0, 0], "y": [0, -1, 0]
        },
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


@pytest.mark.parametrize("debt", ["missing", "reason", "descriptor", "zero-volume", "nonfinite-box"])
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
    status, numbers = VALIDATOR["kernel_join"](lambda: facts, retained_plan["setups"][-1], retained_plan)
    assert status == "pass"
    assert numbers["stock_in"] == ["C1", "T2"]
    facts["setups"]["A1"]["assembly_error"] = "posed pieces overlap"
    status, _ = VALIDATOR["kernel_join"](lambda: facts, retained_plan["setups"][-1], retained_plan)
    assert status == "error"


@pytest.mark.parametrize("proven", [False, True])
def test_blank_cut_reads_only_the_selected_native_output_not_the_parent_compound(retained_plan, proven):
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
    sheet.setup_findings = lambda setup: [{"status": "unknown"}]
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
