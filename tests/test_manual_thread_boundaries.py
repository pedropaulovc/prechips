"""Manual thread-only setups owe holding and tool facts, not invented machine zeros."""

from copy import deepcopy

import pytest
from test_thread_preparation import prepared_hole as prepared_hole
from test_validate_examples import VALIDATOR

from prechips.inputs import Bundle
from prechips.rules import coordinates
from prechips.rules._bench import (
    BENCH_ACTIONS,
    manual_bench,
    manual_thread_setup,
    unfixtured_handling,
)
from prechips.rules.tip_endpoints import evaluate as endpoint_findings
from prechips.rules.zero_recipe import rule as zero_rule
from prechips.sheet import _TOPICS


@pytest.fixture
def manual_bundle(tmp_path):
    return Bundle(
        features={
            "units": "mm",
            "features": {
                "thread": {
                    "kind": "threaded_hole",
                    "depth": [8.0, 8.0],
                    "thread": "1/4-20 UNC",
                    "thread_hand": "right",
                    "thread_class": "2B",
                }
            },
        },
        plan={
            "setups": [
                {
                    "id": "S",
                    "machine": "station",
                    "stock_in": "stock",
                    "stock_state": {"top_z": 0.0},
                    "ops": [
                        {
                            "op": 10,
                            "do": "hand_tap",
                            "feature": "thread",
                            "tool": "tap",
                            "depth_mm": 8.0,
                        }
                    ],
                }
            ]
        },
        inventory={
            "machines": {"station": {"kind": "mill", "verify": False}},
            "tools": {"tap": {"kind": "tap", "flute_len_mm": 12.0, "verify": False}},
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def setup(bundle):
    return bundle.plan["setups"][0]


@pytest.mark.parametrize("machine", ["bench", "manual", "lathe", "mill", "drill_press"])
@pytest.mark.parametrize("action", ["hand_tap", "die_thread"])
def test_known_manual_thread_only_setup_needs_no_dro_frame_or_zero(manual_bundle, machine, action):
    manual_bundle.inventory["machines"]["station"]["kind"] = machine
    setup(manual_bundle)["ops"][0]["do"] = action
    setup(manual_bundle)["ops"].append({"op": 20, "do": "inspect", "feature": "thread"})
    guard = manual_thread_setup(manual_bundle, setup(manual_bundle))
    assert guard["manual_thread"] is True
    assert action in BENCH_ACTIONS
    assert not unfixtured_handling(guard, {"note": "handled by hand"})
    [zero] = zero_rule.evaluate(manual_bundle)
    [position] = coordinates.evaluate(manual_bundle)
    assert zero.status == position.status == "not_applicable"
    assert "dro" not in manual_bundle.plan
    assert "frame" not in setup(manual_bundle)
    assert "zero" not in setup(manual_bundle)


@pytest.mark.parametrize("machine", ["bench", "manual"])
def test_bench_hand_threading_still_requires_mechanical_holding(manual_bundle, machine):
    manual_bundle.inventory["machines"]["station"]["kind"] = machine
    bench = manual_bench(manual_bundle, setup(manual_bundle))
    assert bench is not None
    assert not unfixtured_handling(bench, {})
    assert not unfixtured_handling(bench, {"note": "held in the hand"})


@pytest.mark.parametrize("action", ["drill", "tap", "finish_turn", "unknown"])
def test_mixed_powered_or_unknown_operations_do_not_waive_machine_zero(manual_bundle, action):
    setup(manual_bundle)["ops"].append({"op": 20, "do": action, "feature": "thread"})
    assert manual_thread_setup(manual_bundle, setup(manual_bundle)) is None
    assert manual_bench(manual_bundle, setup(manual_bundle)) is None


@pytest.mark.parametrize("machine", ["unknown", "bandsaw", "unlisted-kind"])
def test_unknown_or_unsupported_machine_kind_does_not_waive_zero(manual_bundle, machine):
    manual_bundle.inventory["machines"]["station"]["kind"] = machine
    assert manual_thread_setup(manual_bundle, setup(manual_bundle)) is None
    assert manual_bench(manual_bundle, setup(manual_bundle)) is None


@pytest.mark.parametrize("operations", [[], [{"op": 10, "do": "inspect"}]])
def test_manual_thread_guard_requires_a_thread_operation(manual_bundle, operations):
    setup(manual_bundle)["ops"] = operations
    assert manual_thread_setup(manual_bundle, setup(manual_bundle)) is None


def endpoint_report(bundle):
    return {(row.rule, row.subject): row.to_dict() for row in endpoint_findings(bundle)}


def validate_endpoints(bundle, findings):
    return VALIDATOR["check_endpoints"](
        bundle.plan,
        bundle.features,
        findings,
        VALIDATOR["Entries"](bundle.inventory),
    )


def test_manual_tap_endpoint_is_relative_depth_not_a_dro_claim(manual_bundle):
    findings = endpoint_report(manual_bundle)
    finding = findings["blind_depth", "thread"]
    assert finding["status"] == "pass"
    assert finding["numbers"]["endpoints"] == [
        {
            "setup": "S",
            "op": 10,
            "feature": "thread",
            "entry_z": 0.0,
            "entry_from": "S stock_state.top_z",
            "depth_mm": 8.0,
            "depth_floor_mm": 8.0,
            "flute_len_mm": 12.0,
            "tip_z": -8.0,
            "exit_face": "not_applicable",
            "depth_scale": "manual",
        }
    ]
    assert validate_endpoints(manual_bundle, findings) == {("S", 10): 8.0}


@pytest.mark.parametrize(
    "field,value",
    [
        ("depth_mm", 9.0),
        ("flute_len_mm", 13.0),
        ("depth_floor_mm", 7.0),
        ("depth_scale", "quill"),
        ("tip_z", -9.0),
        ("dro_tip_z", -8.0),
        ("dro_depth_mm", 8.0),
        ("dro_entry_z", 0.0),
    ],
)
def test_manual_endpoint_oracle_rejects_corrupt_facts_or_dro_claims(manual_bundle, field, value):
    findings = endpoint_report(manual_bundle)
    validate_endpoints(manual_bundle, findings)
    findings["blind_depth", "thread"]["numbers"]["endpoints"][0][field] = value
    with pytest.raises(ValueError):
        validate_endpoints(manual_bundle, findings)


def test_manual_endpoint_oracle_rejects_missing_endpoint_row(manual_bundle):
    findings = endpoint_report(manual_bundle)
    findings["blind_depth", "thread"]["numbers"]["endpoints"].clear()
    with pytest.raises(ValueError):
        validate_endpoints(manual_bundle, findings)


@pytest.mark.parametrize("depth", [-1.0, 0.0])
def test_manual_tap_nonpositive_relative_depth_is_error(manual_bundle, depth):
    setup(manual_bundle)["ops"][0]["depth_mm"] = depth
    findings = endpoint_report(manual_bundle)
    assert findings["blind_depth", "thread"]["status"] == "error"
    validate_endpoints(manual_bundle, findings)


@pytest.mark.parametrize("unknown", ["depth", "flute", "tool"])
def test_manual_tap_unknown_endpoint_facts_cannot_be_forged_pass(manual_bundle, unknown):
    if unknown == "depth":
        setup(manual_bundle)["ops"][0]["depth_mm"] = "unknown"
    elif unknown == "flute":
        manual_bundle.inventory["tools"]["tap"]["flute_len_mm"] = "unknown"
    else:
        manual_bundle.inventory["tools"]["tap"]["verify"] = True
    findings = endpoint_report(manual_bundle)
    assert findings["blind_depth", "thread"]["status"] == "unknown"
    validate_endpoints(manual_bundle, findings)
    forged = deepcopy(findings)
    forged["blind_depth", "thread"]["status"] = "pass"
    with pytest.raises(ValueError):
        validate_endpoints(manual_bundle, forged)


def test_joint_debt_topics_are_operator_labels_not_rule_identifiers():
    assert _TOPICS["joint_fit"] == "joint fit"
    assert _TOPICS["joint_assembly"] == "assembly geometry"
    assert _TOPICS["joint_thread"] == "threaded joint"


@pytest.mark.parametrize("action", ["spot", "center_drill"])
def test_canonical_centre_endpoint_is_placed_and_checked_by_the_oracle(prepared_hole, action):
    source = prepared_hole.plan["setups"][0]
    source["ops"][0]["do"] = action
    prepared_hole.plan["setups"] = [source]
    findings = endpoint_report(prepared_hole)
    centre = findings["blind_depth", "tube_centre"]
    assert centre["status"] == "pass"
    (row,) = centre["numbers"]["endpoints"]
    assert row["op"] == 20
    assert row["depth_scale"] == "quill"
    validate_endpoints(prepared_hole, {("blind_depth", "tube_centre"): centre})
    forged = deepcopy(centre)
    forged["numbers"]["endpoints"].clear()
    with pytest.raises(ValueError):
        validate_endpoints(prepared_hole, {("blind_depth", "tube_centre"): forged})
