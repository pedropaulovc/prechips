"""Real preparation witnesses and internal/external thread chains, without native work."""

from copy import deepcopy

import pytest

from prechips import kernel
from prechips.inputs import Bundle
from prechips.model import PreparationWitness
from prechips.process_features import ACTIONS, process_operation
from prechips.rules import centre_support, op_chain, op_order, tip_endpoints

IDENTITY = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "synthetic test frame",
}


def rows(rule, bundle):
    return {row.subject: row for row in rule.evaluate(bundle)}


@pytest.fixture
def prepared_hole(tmp_path):
    return Bundle(
        plan={
            "stock": {"form": "round_bar", "dia_mm": 20.0},
            "process_features": {
                "tube_centre": {
                    "kind": "centre_hole",
                    "at": [0.0, 0.0, 10.0],
                    "axis": [0.0, 0.0, -1.0],
                    "size": "synthetic combined drill/countersink",
                    "drill_dia_mm": 1.98,
                    "drill_length_mm": 1.98,
                    "mouth_dia_mm": 3.0,
                    "countersink_angle_deg": 60.0,
                    "cite": "synthetic test geometry",
                }
            },
            "setups": [
                {
                    "id": "P1",
                    "machine": "lathe",
                    "frame": "model",
                    "stock_in": "stock",
                    "stock_state": {"top_z": 10.0},
                    "ops": [{"op": 20, "do": "spot", "feature": "tube_centre", "tool": "centre"}],
                },
                {
                    "id": "T2",
                    "machine": "lathe",
                    "frame": "model",
                    "stock_in": "P1",
                    "ops": [
                        {
                            "op": 10,
                            "do": "drill",
                            "feature": "socket",
                            "tool": "drill",
                            "prerequisites": {"spot": "P1:20"},
                        },
                        {"op": 20, "do": "tap", "feature": "socket", "tool": "tap"},
                    ],
                },
            ],
        },
        features={
            "units": "mm",
            "frames": {"model": deepcopy(IDENTITY)},
            "features": {
                "socket": {
                    "kind": "threaded_hole",
                    "frame": "model",
                    "at": [0.0, 0.0, 10.0],
                    "axis": [0.0, 0.0, -1.0],
                    "dia": [10.6, 10.8],
                    "depth": 6.0,
                    "thread": "1/2-20 UNF",
                    "thread_hand": "right",
                    "thread_class": "2B",
                    "tap_drill_mm": 10.7,
                },
                "other": {"kind": "boss"},
            },
        },
        inventory={
            "machines": {
                "lathe": {
                    "kind": "lathe",
                    "resolution_mm": {
                        "value": 0.001,
                        "measured": {
                            "status": "measured",
                            "by": "synthetic test operator",
                            "date": "2026-10-18",
                            "instrument": "synthetic DRO specification",
                        },
                    },
                }
            },
            "fixtures": {"centre_support": {"kind": "dead_centre"}},
            "tools": {
                "centre": {
                    "kind": "center_drill",
                    "dia_mm": 1.98,
                    "pilot_len_mm": 1.98,
                    "shank_mm": 4.7625,
                    "angle_deg": 60.0,
                    "point_angle": 118.0,
                    "oal_mm": 47.6,
                    "flute_len_mm": 1.9,
                },
                "drill": {"kind": "drill", "dia_mm": 10.7},
                "tap": {
                    "kind": "tap",
                    "thread": "1/2-20 UNF",
                    "thread_hand": "right",
                    "thread_class": "2B",
                },
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def hole_row(bundle):
    return rows(op_chain, bundle)["socket"]


def receiving_setup(bundle):
    return next(setup for setup in bundle.plan["setups"] if setup["id"] == "T2")


def use_centre_support(bundle):
    receiving_setup(bundle)["hold"] = {
        "support": "centre_support",
        "centre_hole": "tube_centre",
        "centre_hole_dia_mm": 3.0,
    }


def retained_output(feature):
    return {
        "carries": feature,
        "pose": {**deepcopy(IDENTITY), "cite": "synthetic retained registration"},
        "cite": "synthetic retained selector",
    }


def split_before_receiver(bundle, *, owner="tube", source_owned=False):
    source = bundle.plan["setups"][0]
    source["ops"].append(
        {
            "op": 90,
            "do": "part_off",
            "feature": "other",
            "outputs": {
                "tube": retained_output("socket"),
                "knob": retained_output("other"),
            },
        }
    )
    receiving_setup(bundle)["stock_in"] = f"stock_out.{owner}"
    # Synthetic STEP ownership is explicit test evidence, not inferred from feature names.
    bundle.__dict__["finished_feature_owners"] = {"socket": "tube", "other": "knob"}
    if source_owned:
        bundle.finished_feature_owners["tube_centre"] = "tube"


def test_prerequisite_is_a_typed_operation_reference_not_prose():
    assert PreparationWitness.model_validate({"spot": "P1:20"}).spot == "P1:20"
    assert PreparationWitness.model_validate({"spot": "unknown"}).spot == "unknown"
    with pytest.raises(ValueError, match="setup:op"):
        PreparationWitness.model_validate({"spot": "spot the end first"})


@pytest.mark.parametrize("action", ["spot", "center_drill"])
def test_real_centre_spot_uses_the_existing_centre_geometry_contract(prepared_hole, action):
    source = prepared_hole.plan["setups"][0]
    op = source["ops"][0]
    op["do"] = action
    assert action in ACTIONS["centre_hole"]
    assert "reason" not in process_operation(prepared_hole, op)
    assert tip_endpoints.centre_check(prepared_hole, source, op)[0] == "pass"
    endpoint = rows(tip_endpoints, prepared_hole)["tube_centre"]
    assert endpoint.status == "pass"
    assert endpoint.numbers["endpoints"][0]["depth_scale"] == "quill"
    assert kernel.op_inputs(prepared_hole, source, op)["process_cut"].get("reason") is None
    use_centre_support(prepared_hole)
    assert rows(centre_support, prepared_hole)["T2"].status == "pass"
    assert hole_row(prepared_hole).status == "pass"


@pytest.mark.parametrize("value,status", [(2.48, "error"), ("unknown", "unknown")])
def test_centre_spot_cannot_bypass_selected_tool_shape(prepared_hole, value, status):
    prepared_hole.inventory["tools"]["centre"]["pilot_len_mm"] = value
    source = prepared_hole.plan["setups"][0]
    op = source["ops"][0]
    assert rows(tip_endpoints, prepared_hole)["tube_centre"].status == status
    assert kernel.op_inputs(prepared_hole, source, op)["process_cut"]["reason"]
    use_centre_support(prepared_hole)
    assert rows(centre_support, prepared_hole)["T2"].status == status
    assert hole_row(prepared_hole).status == status


def test_valid_witness_credits_only_the_real_prior_spot(prepared_hole):
    row = hole_row(prepared_hole)
    assert row.status == "pass"
    assert row.numbers["chain"] == ["drill", "tap"]
    assert row.numbers["preparation_witnesses"] == [
        {
            "operation": "T2:10",
            "spot": "P1:20",
            "source_feature": "tube_centre",
            "source_kind": "centre_hole",
            "action": "spot",
            "preparation": "pass",
        }
    ]
    assert [op["do"] for op in receiving_setup(prepared_hole)["ops"]] == ["drill", "tap"]


@pytest.mark.parametrize(
    "reference,status",
    [("missing:20", "error"), ("P1:99", "error"), ("unknown", "unknown")],
)
def test_missing_or_unknown_witness_is_not_a_spot(prepared_hole, reference, status):
    receiving_setup(prepared_hole)["ops"][0]["prerequisites"]["spot"] = reference
    row = hole_row(prepared_hole)
    assert row.status == status
    if status == "unknown":
        assert "no earlier spot" not in row.sentence


def test_ambiguous_witness_cannot_choose_an_arbitrary_operation(prepared_hole):
    source = prepared_hole.plan["setups"][0]
    source["ops"].append(deepcopy(source["ops"][0]))
    assert hole_row(prepared_hole).status == "error"


def test_a_future_real_spot_is_not_prior_preparation(prepared_hole):
    prepared_hole.plan["setups"].reverse()
    assert hole_row(prepared_hole).status == "error"


@pytest.mark.parametrize("action", ["drill", "face", "inspect"])
def test_witness_must_name_the_real_spot_action(prepared_hole, action):
    prepared_hole.plan["setups"][0]["ops"][0]["do"] = action
    assert hole_row(prepared_hole).status == "error"


def test_a_spot_on_an_exported_unrelated_feature_is_not_a_process_witness(prepared_hole):
    prepared_hole.plan["setups"][0]["ops"][0]["feature"] = "other"
    assert hole_row(prepared_hole).status == "error"


def test_a_known_nonhole_process_feature_is_not_a_spot_witness(prepared_hole):
    prepared_hole.plan["process_features"]["tube_centre"]["kind"] = "end_face"
    assert hole_row(prepared_hole).status == "error"


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("at", [1.0, 0.0, 10.0], "error"),
        ("at", [0.0, 0.0, 11.0], "error"),
        ("axis", [0.0, 1.0, 0.0], "error"),
        ("axis", [0.0, 0.0, 1.0], "error"),
        ("at", "unknown", "unknown"),
        ("axis", "unknown", "unknown"),
    ],
)
def test_witness_entry_and_axis_match_target(prepared_hole, field, value, status):
    prepared_hole.features["features"]["socket"][field] = value
    assert hole_row(prepared_hole).status == status


@pytest.mark.parametrize("missing_frame", [False, True])
def test_witness_geometry_transforms_to_model(prepared_hole, missing_frame):
    feature = prepared_hole.features["features"]["socket"]
    feature.update(frame="translated", at=[0.0, 0.0, 0.0], axis=[0.0, 0.0, 1.0])
    if not missing_frame:
        prepared_hole.features["frames"]["translated"] = {
            "origin": [0.0, 0.0, 10.0],
            "x": [1.0, 0.0, 0.0],
            "y": [0.0, -1.0, 0.0],
            "z": [0.0, 0.0, -1.0],
        }
    assert hole_row(prepared_hole).status == ("unknown" if missing_frame else "pass")


def test_unrelated_stock_cannot_supply_an_explicit_spot(prepared_hole):
    prepared_hole.plan["stock"]["components"] = [{"id": "tube"}, {"id": "other"}]
    prepared_hole.plan["setups"][0]["stock_in"] = "stock.tube"
    receiving_setup(prepared_hole)["stock_in"] = "stock.other"
    assert hole_row(prepared_hole).status == "error"


def test_undeclared_route_is_unknown_not_a_known_different_blank(prepared_hole):
    receiving_setup(prepared_hole).pop("stock_in")
    assert hole_row(prepared_hole).status == "unknown"


@pytest.mark.parametrize("source_owned,status", [(False, "unknown"), (True, "pass")])
def test_spot_partition_survival(prepared_hole, source_owned, status):
    split_before_receiver(prepared_hole, source_owned=source_owned)
    assert hole_row(prepared_hole).status == status
    use_centre_support(prepared_hole)
    row = rows(centre_support, prepared_hole)["T2"]
    assert row.status == status
    if status == "unknown":
        assert row.numbers["made_by"] == []
        assert row.numbers["material_unknown"] == ["P1 op 20"]
        assert "no earlier setup" not in row.sentence


def test_known_wrong_partition_cannot_credit_a_spot_or_centre_maker(prepared_hole):
    split_before_receiver(prepared_hole, owner="knob", source_owned=True)
    assert hole_row(prepared_hole).status == "error"
    use_centre_support(prepared_hole)
    row = rows(centre_support, prepared_hole)["T2"]
    assert row.status == "error"
    assert row.numbers["made_by"] == []
    assert row.numbers["material_rejected"] == ["P1 op 20"]


@pytest.mark.parametrize("owner,status", [("tube", "unknown"), ("knob", "error")])
def test_unknown_output_pose_is_debt_without_hiding_a_wrong_branch(prepared_hole, owner, status):
    split_before_receiver(prepared_hole, owner=owner, source_owned=True)
    prepared_hole.plan["setups"][0]["ops"][-1]["outputs"][owner]["pose"] = "unknown"
    assert hole_row(prepared_hole).status == status


def test_a_spot_after_partition_prepares_only_that_same_piece(prepared_hole):
    split = {
        "id": "CUT",
        "stock_in": "stock",
        "ops": [
            {
                "op": 10,
                "do": "part_off",
                "feature": "other",
                "outputs": {
                    "tube": retained_output("socket"),
                    "knob": retained_output("other"),
                },
            }
        ],
    }
    prepared_hole.plan["setups"][0]["stock_in"] = "stock_out.tube"
    prepared_hole.plan["setups"].insert(0, split)
    prepared_hole.__dict__["finished_feature_owners"] = {"socket": "tube", "other": "knob"}
    assert hole_row(prepared_hole).status == "pass"


def test_each_drill_resolves_its_own_preparation_not_another_drills_witness(prepared_hole):
    setup = receiving_setup(prepared_hole)
    setup["ops"].insert(
        1,
        {
            **deepcopy(setup["ops"][0]),
            "op": 15,
            "prerequisites": {"spot": "unknown"},
        },
    )
    row = hole_row(prepared_hole)
    assert row.status == "unknown"
    assert len(row.numbers["preparation_witnesses"]) == 2


def test_tap_drill_check_uses_the_actual_prior_drill_not_a_correct_future_one(prepared_hole):
    setup = receiving_setup(prepared_hole)
    prepared_hole.inventory["tools"]["wrong_drill"] = {"kind": "drill", "dia_mm": 9.0}
    setup["ops"][0]["tool"] = "wrong_drill"
    setup["ops"].append({**deepcopy(setup["ops"][0]), "op": 30, "tool": "drill"})
    row = hole_row(prepared_hole)
    assert row.status == "error"
    assert row.numbers["selected_drill_mm"] == 9.0


def test_a_future_drill_does_not_prepare_an_earlier_tap(prepared_hole):
    receiving_setup(prepared_hole)["ops"].reverse()
    assert hole_row(prepared_hole).status == "error"


@pytest.mark.parametrize(
    "field,value",
    [
        ("thread", "1/2-13 UNC"),
        ("thread", "M12x1.25"),
        ("thread_hand", "left"),
        ("thread_class", "3B"),
    ],
)
@pytest.mark.parametrize("action", ["tap", "hand_tap"])
def test_known_wrong_tap_specification(prepared_hole, field, value, action):
    receiving_setup(prepared_hole)["ops"][-1]["do"] = action
    prepared_hole.inventory["tools"]["tap"][field] = value
    assert hole_row(prepared_hole).status == "error"


@pytest.mark.parametrize("owner", ["feature", "tool"])
@pytest.mark.parametrize("field", ["thread", "thread_hand", "thread_class"])
@pytest.mark.parametrize("omit", [False, True])
@pytest.mark.parametrize("action", ["tap", "hand_tap"])
def test_unknown_tap_metadata_is_debt(prepared_hole, owner, field, omit, action):
    receiving_setup(prepared_hole)["ops"][-1]["do"] = action
    item = (
        prepared_hole.features["features"]["socket"]
        if owner == "feature"
        else prepared_hole.inventory["tools"]["tap"]
    )
    if omit:
        item.pop(field)
    else:
        item[field] = "unknown"
    assert hole_row(prepared_hole).status == "unknown"


def test_tap_name_and_prose_do_not_supply_missing_thread_identity(prepared_hole):
    tool = prepared_hole.inventory["tools"]["tap"]
    tool.update(thread="unknown", name="1/2-20 UNF RH tap", note="correct half inch tap")
    assert hole_row(prepared_hole).status == "unknown"


@pytest.fixture
def external_thread(tmp_path):
    return Bundle(
        plan={
            "setups": [
                {
                    "id": "S1",
                    "machine": "lathe",
                    "frame": "model",
                    "stock_in": "stock",
                    "ops": [
                        {
                            "op": 10,
                            "do": "finish_turn",
                            "feature": "stud",
                            "to_dia": 12.7,
                            "z_from": 10.0,
                            "z_to": 4.0,
                        },
                        {"op": 20, "do": "die_thread", "feature": "stud", "tool": "die"},
                    ],
                }
            ]
        },
        features={
            "units": "mm",
            "frames": {"model": deepcopy(IDENTITY)},
            "features": {
                "stud": {
                    "kind": "external_thread",
                    "frame": "model",
                    "at": [0.0, 0.0, 10.0],
                    "axis": [0.0, 0.0, -1.0],
                    "dia": [12.6, 12.7],
                    "length": 6.0,
                    "thread": "1/2-20 UNF",
                    "thread_hand": "right",
                }
            },
        },
        inventory={
            "tools": {"die": {"kind": "die", "thread": "1/2-20 UNF", "thread_hand": "right"}}
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def external_row(bundle):
    return rows(op_chain, bundle)["stud"]


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn", "turn"])
def test_male_turn_and_die_need_no_hole_chain_or_spindle_settings(external_thread, action):
    setup = external_thread.plan["setups"][0]
    setup["ops"][0]["do"] = action
    row = external_row(external_thread)
    assert row.status == "pass"
    assert row.numbers["male_blank_preparation"] == {"S1:20": "S1:10"}
    assert not any("rpm" in op or "depth_mm" in op for op in setup["ops"])
    assert "tap_drill_mm" not in row.numbers


def test_known_external_thread_requires_the_die_operation(external_thread):
    external_thread.plan["setups"][0]["ops"].pop()
    assert external_row(external_thread).status == "error"


def test_unknown_external_thread_and_absent_die_remain_debt(external_thread):
    external_thread.features["features"]["stud"]["thread"] = "unknown"
    external_thread.plan["setups"][0]["ops"].pop()
    assert external_row(external_thread).status == "unknown"


@pytest.mark.parametrize("future", [False, True])
def test_missing_prior_male_blank_is_debt(external_thread, future):
    ops = external_thread.plan["setups"][0]["ops"]
    if future:
        ops.reverse()
    else:
        ops.pop(0)
    row = external_row(external_thread)
    assert row.status == "unknown"
    assert "no drill" not in row.sentence and "no spot" not in row.sentence


@pytest.mark.parametrize(
    "action", ["spot", "center_drill", "drill", "tap", "hand_tap", "ream", "counterbore"]
)
def test_internal_hole_actions_do_not_prepare_a_male_thread(external_thread, action):
    external_thread.plan["setups"][0]["ops"][0]["do"] = action
    assert external_row(external_thread).status == "error"


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("to_dia", 10.0, "error"),
        ("z_to", 8.0, "error"),
        ("to_dia", "unknown", "unknown"),
        ("z_to", "unknown", "unknown"),
    ],
)
def test_male_blank_geometry_is_real_or_unresolved(external_thread, field, value, status):
    external_thread.plan["setups"][0]["ops"][0][field] = value
    assert external_row(external_thread).status == status


def test_different_stock_does_not_supply_the_male_blank(external_thread):
    setup = external_thread.plan["setups"][0]
    turn = setup["ops"].pop(0)
    external_thread.plan["stock"] = {"components": [{"id": "male"}, {"id": "other"}]}
    setup["stock_in"] = "stock.other"
    external_thread.plan["setups"].insert(
        0,
        {"id": "PREP", "frame": "model", "stock_in": "stock.male", "ops": [turn]},
    )
    assert external_row(external_thread).status == "error"


@pytest.mark.parametrize("action", ["part_off", "release"])
def test_manual_die_is_still_a_real_cut_after_terminal_release(external_thread, action):
    ops = external_thread.plan["setups"][0]["ops"]
    ops.insert(1, {"op": 15, "do": action, "feature": "stud"})
    assert rows(op_order, external_thread)["S1"].status == "error"
    ops[-1]["do"] = "inspect"
    assert rows(op_order, external_thread)["S1"].status == "pass"


@pytest.mark.parametrize("field", ["do", "feature"])
def test_unknown_centre_maker_identity_is_not_a_false_missing_error(prepared_hole, field):
    prepared_hole.plan["setups"][0]["ops"][0][field] = "unknown"
    use_centre_support(prepared_hole)
    row = rows(centre_support, prepared_hole)["T2"]
    assert row.status == "unknown"
    assert row.numbers["made_by"] == []
    assert row.numbers["material_unknown"] == ["P1 op 20"]
    assert hole_row(prepared_hole).status == "unknown"


def test_unknown_action_does_not_hide_a_known_wrong_selected_tap(prepared_hole):
    setup = receiving_setup(prepared_hole)
    setup["ops"].append({"op": 30, "do": "unknown", "feature": "socket"})
    prepared_hole.inventory["tools"]["tap"]["thread_hand"] = "left"
    assert hole_row(prepared_hole).status == "error"


def test_an_unknown_prior_spot_action_is_debt_not_proven_absence(prepared_hole):
    setup = receiving_setup(prepared_hole)
    setup["ops"][0].pop("prerequisites")
    setup["ops"].insert(0, {"op": 5, "do": "unknown", "feature": "socket"})
    assert hole_row(prepared_hole).status == "unknown"


def test_uncertain_drill_survival_does_not_prove_a_wrong_target_tap_drill(prepared_hole):
    source = prepared_hole.plan["setups"][0]
    drill = receiving_setup(prepared_hole)["ops"].pop(0)
    drill["op"] = 30
    source["ops"].append(drill)
    prepared_hole.inventory["tools"]["drill"]["dia_mm"] = 9.0
    prepared_hole.features["features"]["tube_surface"] = {"kind": "boss"}
    split_before_receiver(prepared_hole, source_owned=True)
    source["ops"][-1]["outputs"]["tube"]["carries"] = "tube_surface"
    prepared_hole.__dict__["finished_feature_owners"] = {
        "tube_surface": "tube",
        "tube_centre": "tube",
        "other": "knob",
    }
    row = hole_row(prepared_hole)
    assert row.status == "unknown"
    assert "selected tap drill differs" not in row.sentence


@pytest.mark.parametrize(
    "selected,pose_known,status",
    [("male", True, "pass"), ("male", False, "unknown"), ("other", False, "error")],
)
def test_external_blank_partition_and_registration_are_preserved(
    external_thread, selected, pose_known, status
):
    source = external_thread.plan["setups"][0]
    die = source["ops"].pop()
    source["ops"].append(
        {
            "op": 15,
            "do": "part_off",
            "feature": "other",
            "outputs": {
                "male": retained_output("stud"),
                "other": retained_output("other"),
            },
        }
    )
    if not pose_known:
        source["ops"][-1]["outputs"][selected]["pose"] = "unknown"
    external_thread.plan["setups"].append(
        {"id": "DIE", "stock_in": f"stock_out.{selected}", "ops": [die]}
    )
    external_thread.features["features"]["other"] = {"kind": "boss"}
    external_thread.__dict__["finished_feature_owners"] = {"stud": "male", "other": "other"}
    assert external_row(external_thread).status == status


@pytest.mark.parametrize("field", ["at", "axis", "length", "dia"])
def test_unknown_male_blank_geometry_stays_debt(external_thread, field):
    external_thread.features["features"]["stud"][field] = "unknown"
    assert external_row(external_thread).status == "unknown"


def test_hand_tap_can_use_the_real_prior_process_spot(prepared_hole):
    setup = receiving_setup(prepared_hole)
    setup["ops"][-1]["do"] = "hand_tap"
    row = hole_row(prepared_hole)
    assert row.status == "pass"
    assert row.numbers["chain"] == ["drill", "hand_tap"]
    assert row.numbers["selected_drill_mm"] == 10.7
    assert "rpm" not in setup["ops"][-1] and "feed_mm_rev" not in setup["ops"][-1]


@pytest.mark.parametrize("flute,status", [(8.0, "pass"), (3.0, "error"), ("unknown", "unknown")])
def test_manual_tap_depth_needs_real_flute_length_not_a_dro_or_powered_setting(
    prepared_hole, monkeypatch, flute, status
):
    setup = receiving_setup(prepared_hole)
    setup["stock_in"] = "stock"
    setup["ops"] = [{**setup["ops"][-1], "do": "hand_tap"}]
    prepared_hole.plan["setups"][:] = [setup]
    prepared_hole.plan["dro"] = {"kind": "unknown"}
    prepared_hole.inventory["tools"]["tap"]["flute_len_mm"] = flute

    def no_powered_setting(*args, **kwargs):
        raise AssertionError("manual tapping must not resolve a DRO or carried axial tool setting")

    monkeypatch.setattr(tip_endpoints, "_operative", no_powered_setting)
    row = rows(tip_endpoints, prepared_hole)["socket"]
    assert row.status == status
    endpoint = row.numbers["endpoints"][0]
    assert endpoint["depth_scale"] == "manual"
    assert endpoint["depth_mm"] == 6.0
    assert "dro_tip_z" not in endpoint and "dro_grid_debt" not in endpoint


def test_explicit_unknown_manual_tap_depth_does_not_borrow_the_feature_depth(prepared_hole):
    setup = receiving_setup(prepared_hole)
    setup["ops"] = [{**setup["ops"][-1], "do": "hand_tap", "depth_mm": "unknown"}]
    prepared_hole.plan["setups"][:] = [setup]
    prepared_hole.inventory["tools"]["tap"]["flute_len_mm"] = 8.0
    assert rows(tip_endpoints, prepared_hole)["socket"].status == "unknown"


@pytest.mark.parametrize("action", ["part_off", "release"])
def test_hand_tap_is_not_an_after_release_manual_exemption(prepared_hole, action):
    setup = receiving_setup(prepared_hole)
    setup["ops"][-1]["do"] = "hand_tap"
    setup["ops"].insert(1, {"op": 15, "do": action, "feature": "socket"})
    assert rows(op_order, prepared_hole)["T2"].status == "error"


def test_hand_tap_still_requires_the_real_prior_drill(prepared_hole):
    setup = receiving_setup(prepared_hole)
    setup["ops"][-1]["do"] = "hand_tap"
    setup["ops"].reverse()
    assert hole_row(prepared_hole).status == "error"
    assert rows(op_order, prepared_hole)["T2"].status == "error"


@pytest.mark.parametrize("depth,status", [(-1.0, "error"), (0.0, "error"), ("unknown", "unknown")])
def test_manual_tap_nonpositive_depth_is_a_contradiction(prepared_hole, depth, status):
    setup = receiving_setup(prepared_hole)
    setup["ops"] = [{**setup["ops"][-1], "do": "hand_tap", "depth_mm": depth}]
    prepared_hole.plan["setups"][:] = [setup]
    prepared_hole.inventory["tools"]["tap"]["flute_len_mm"] = 8.0
    assert rows(tip_endpoints, prepared_hole)["socket"].status == status


@pytest.mark.parametrize(
    "change,status",
    [
        (None, "pass"),
        ("missing tool", "unknown"),
        ("unknown depth", "unknown"),
        ("zero depth", "error"),
        ("wrong entry", "error"),
    ],
)
def test_tooling_spot_requires_a_real_point_cut(prepared_hole, change, status):
    prepared_hole.plan["process_features"]["tube_centre"] = {
        "kind": "tooling_hole",
        "at": [0.0, 0.0, 10.0],
        "axis": [0.0, 0.0, -1.0],
        "dia": [1.9, 2.1],
        "depth": 3.0,
        "cite": "synthetic tooling-hole spot",
    }
    setup = prepared_hole.plan["setups"][0]
    op = setup["ops"][0]
    op["depth_mm"] = 0.5
    if change == "missing tool":
        op["tool"] = "missing"
    elif change == "unknown depth":
        op["depth_mm"] = "unknown"
    elif change == "zero depth":
        op["depth_mm"] = 0.0
    elif change == "wrong entry":
        setup["stock_state"]["top_z"] = 11.0
    assert hole_row(prepared_hole).status == status


@pytest.mark.parametrize("action", ["tap", "hand_tap"])
def test_tap_class_comparison_normalizes_case_and_outer_whitespace(prepared_hole, action):
    receiving_setup(prepared_hole)["ops"][-1]["do"] = action
    prepared_hole.features["features"]["socket"]["thread_class"] = " 2b "
    row = hole_row(prepared_hole)
    assert row.status == "pass"
    assert row.numbers["tap_tools"][0]["required_class"] == " 2b "
    assert row.numbers["tap_tools"][0]["selected_class"] == "2B"
    assert row.numbers["tap_tools"][0]["class_match"] is True


@pytest.mark.parametrize("action", ["tap", "hand_tap"])
def test_known_wrong_tap_class_is_not_hidden_by_other_missing_proof(prepared_hole, action):
    setup = receiving_setup(prepared_hole)
    setup["ops"][-1]["do"] = action
    setup["ops"][0]["prerequisites"]["spot"] = "unknown"
    prepared_hole.features["features"]["socket"]["thread_hand"] = "unknown"
    prepared_hole.inventory["tools"]["tap"]["thread_class"] = "3B"
    row = hole_row(prepared_hole)
    assert row.status == "error"
    assert "selected tap class differs" in row.sentence
    assert row.numbers["tap_tools"][0]["class_match"] is False


def add_same_hole_enlarger(bundle):
    setup = receiving_setup(bundle)
    pilot = setup["ops"][0]
    pilot["tool"] = "pilot"
    bundle.inventory["tools"]["pilot"] = {"kind": "drill", "dia_mm": 5.0}
    enlarger = {"op": 15, "do": "drill", "feature": "socket", "tool": "drill"}
    setup["ops"].insert(1, enlarger)
    return setup, pilot, enlarger


def test_later_same_hole_drill_inherits_the_real_pilots_spot(prepared_hole):
    setup, _, enlarger = add_same_hole_enlarger(prepared_hole)
    row = hole_row(prepared_hole)
    assert row.status == "pass"
    assert row.numbers["chain"] == ["drill", "drill", "tap"]
    assert row.numbers["selected_drill_mm"] == 10.7
    assert "prerequisites" not in enlarger
    assert [op["do"] for op in setup["ops"]] == ["drill", "drill", "tap"]
    assert row.numbers["preparation_witnesses"][1] == {
        "operation": "T2:15",
        "spot": "P1:20",
        "source_feature": "tube_centre",
        "source_kind": "centre_hole",
        "action": "spot",
        "preparation": "pass",
        "inherited_from": "T2:10",
    }


def test_multiple_enlargements_keep_the_original_witness_source(prepared_hole):
    setup, _, _ = add_same_hole_enlarger(prepared_hole)
    setup["ops"].insert(2, {"op": 17, "do": "drill", "feature": "socket", "tool": "drill"})
    row = hole_row(prepared_hole)
    assert row.status == "pass"
    proofs = row.numbers["preparation_witnesses"]
    assert [proof["spot"] for proof in proofs] == ["P1:20", "P1:20", "P1:20"]
    assert proofs[-1]["operation"] == "T2:17"
    assert proofs[-1]["inherited_from"] == "T2:15"


@pytest.mark.parametrize("missing", ["spot identity", "target axis", "source tool"])
def test_inherited_unknown_pilot_preparation_is_not_a_missing_spot_error(prepared_hole, missing):
    _, pilot, _ = add_same_hole_enlarger(prepared_hole)
    if missing == "spot identity":
        pilot["prerequisites"]["spot"] = "unknown"
    elif missing == "target axis":
        prepared_hole.features["features"]["socket"]["axis"] = "unknown"
    else:
        prepared_hole.inventory["tools"]["centre"]["pilot_len_mm"] = "unknown"
    row = hole_row(prepared_hole)
    assert row.status == "unknown"
    assert "no earlier spot" not in row.sentence
    assert row.numbers["preparation_witnesses"][1]["inherited_from"] == "T2:10"


@pytest.mark.parametrize(
    "reference,status",
    [("unknown", "unknown"), ("missing:20", "error"), ("T2:20", "error")],
)
def test_an_explicit_enlarger_witness_cannot_fall_back_to_the_pilot(
    prepared_hole, reference, status
):
    _, _, enlarger = add_same_hole_enlarger(prepared_hole)
    enlarger["prerequisites"] = {"spot": reference}
    row = hole_row(prepared_hole)
    assert row.status == status
    proof = row.numbers["preparation_witnesses"][1]
    assert proof["spot"] == reference
    assert "inherited_from" not in proof


def test_a_future_spot_at_the_pilot_is_not_repaired_by_later_inheritance(prepared_hole):
    setup, pilot, _ = add_same_hole_enlarger(prepared_hole)
    spot = prepared_hole.plan["setups"][0]["ops"].pop()
    spot["op"] = 12
    setup["stock_state"] = {"top_z": 10.0}
    setup["ops"].insert(1, spot)
    pilot["prerequisites"]["spot"] = "T2:12"
    row = hole_row(prepared_hole)
    assert row.status == "error"
    assert "not earlier" in row.sentence
    inherited = row.numbers["preparation_witnesses"][1]
    assert inherited["operation"] == "T2:15"
    assert inherited["inherited_from"] == "T2:10"
    assert inherited["preparation"] == "pass"


def move_enlarger_to_receiver(bundle):
    pilot_setup, _, enlarger = add_same_hole_enlarger(bundle)
    pilot_setup["ops"].remove(enlarger)
    tap = pilot_setup["ops"].pop()
    receiver = {"id": "T3", "stock_in": "T2", "ops": [enlarger, tap]}
    bundle.plan["setups"].append(receiver)
    return pilot_setup, receiver


@pytest.mark.parametrize("routed,status", [(True, "pass"), (False, "unknown")])
def test_an_enlarger_requires_a_known_route_from_the_actual_pilot(prepared_hole, routed, status):
    _, receiver = move_enlarger_to_receiver(prepared_hole)
    if not routed:
        receiver.pop("stock_in")
    row = hole_row(prepared_hole)
    assert row.status == status
    assert row.numbers["preparation_witnesses"][1]["inherited_from"] == "T2:10"
    if status == "unknown":
        assert "no earlier spot" not in row.sentence


def test_a_pilot_on_unrelated_stock_cannot_prepare_the_enlarger(prepared_hole):
    _, receiver = move_enlarger_to_receiver(prepared_hole)
    prepared_hole.plan["stock"]["components"] = [{"id": "tube"}, {"id": "other"}]
    prepared_hole.plan["setups"][0]["stock_in"] = "stock.tube"
    receiver["stock_in"] = "stock.other"
    row = hole_row(prepared_hole)
    assert row.status == "error"
    assert "T3:15 has no earlier spot" in row.sentence
    assert len(row.numbers["preparation_witnesses"]) == 1


@pytest.mark.parametrize(
    "selected,pose_known,source_owned,status",
    [
        ("tube", True, True, "pass"),
        ("tube", False, True, "unknown"),
        ("tube", True, False, "unknown"),
        ("knob", True, True, "error"),
        ("knob", False, True, "error"),
    ],
)
def test_pilot_inheritance_preserves_partition_pose_and_original_spot_ownership(
    prepared_hole, selected, pose_known, source_owned, status
):
    pilot_setup, receiver = move_enlarger_to_receiver(prepared_hole)
    outputs = {
        "tube": retained_output("socket"),
        "knob": retained_output("other"),
    }
    if not pose_known:
        outputs[selected]["pose"] = "unknown"
    pilot_setup["ops"].append({"op": 90, "do": "part_off", "feature": "other", "outputs": outputs})
    receiver["stock_in"] = f"stock_out.{selected}"
    prepared_hole.__dict__["finished_feature_owners"] = {
        "socket": "tube",
        "other": "knob",
    }
    if source_owned:
        prepared_hole.finished_feature_owners["tube_centre"] = "tube"
    row = hole_row(prepared_hole)
    assert row.status == status
    if status != "error":
        inherited = row.numbers["preparation_witnesses"][1]
        assert inherited["operation"] == "T3:15"
        assert inherited["spot"] == "P1:20"
        assert inherited["inherited_from"] == "T2:10"
    if status == "unknown":
        assert "no earlier spot" not in row.sentence


@pytest.mark.parametrize("unusable", ["future", "different feature"])
def test_only_an_actual_earlier_same_feature_pilot_can_supply_preparation(prepared_hole, unusable):
    setup, pilot, enlarger = add_same_hole_enlarger(prepared_hole)
    if unusable == "future":
        setup["ops"].remove(enlarger)
        setup["ops"].insert(0, enlarger)
    else:
        pilot["feature"] = "other"
    row = hole_row(prepared_hole)
    assert row.status == "error"
    assert "T2:15 has no earlier spot" in row.sentence
