"""Adjustable internal finishing commands, settings, and causal gauge capability."""

import pytest
from test_provenance_machining_debt import bundle, fact

from prechips.rules import sizing


def data():
    value = bundle()
    value.inventory["tools"]["cutter"]["dia_mm"] = fact(6.0)
    value.inventory["tools"].update(
        bar={"kind": "boring_bar", "dia_mm": fact(6.35), "shank_mm": fact(12)},
        hone={"kind": "hone", "dia_mm": fact(6.35), "range_mm": [5, 8]},
    )
    value.inventory["gauges"] = {
        "bore": {"kind": "bore_gauge", "range_mm": [5, 8], "resolution_mm": fact(0.001)}
    }
    value.plan["setups"][0]["ops"] += [
        {"op": 20, "do": "bore", "feature": "target", "tool": "bar", "to_dia": 6.2},
        {"op": 30, "do": "hone", "feature": "target", "tool": "hone", "to_dia": 6.35},
        {"op": 40, "do": "inspect", "feature": "target", "checks": {"dia": "bore"}},
    ]
    return value


def row(value):
    [finding] = sizing.evaluate(value)
    return finding


def test_last_actual_hone_not_pilot_or_bar_shank_sets_final_size():
    finding = row(data())
    assert finding.status == "pass"
    assert finding.numbers["finishing_op"] == "S1:30"
    assert finding.numbers["commanded_dia_mm"] == 6.35
    assert finding.numbers["finishing_inspection"]["part_result"] == "not_recorded"


@pytest.mark.parametrize("action", ["drill", "ream"])
def test_fixed_cutter_after_adjustable_finish_is_the_actual_last_finisher(action):
    value = data()
    value.plan["setups"][0]["ops"].append(
        {"op": 50, "do": action, "feature": "target", "tool": "cutter"}
    )
    assert row(value).status == "error"
    assert row(value).numbers["finishing_action"] == action


@pytest.mark.parametrize("field", ["target", "setting", "inspection", "resolution"])
def test_unknown_command_setting_or_inspection_never_passes(field):
    value = data()
    if field == "target":
        del value.plan["setups"][0]["ops"][2]["to_dia"]
    elif field == "setting":
        del value.inventory["tools"]["hone"]["dia_mm"]
    elif field == "inspection":
        value.plan["setups"][0]["ops"].pop()
    else:
        value.inventory["gauges"]["bore"]["resolution_mm"] = "unknown"
    assert row(value).status == "unknown"


@pytest.mark.parametrize("target", [6.29, 6.41])
def test_final_target_outside_unchanged_acceptance_band_errors(target):
    value = data()
    value.plan["setups"][0]["ops"][2]["to_dia"] = target
    value.inventory["tools"]["hone"]["dia_mm"] = fact(target)
    assert row(value).status == "error"
    assert value.feature_definitions["target"]["dia"] == [6.3, 6.4]


def test_intermediate_undersize_is_valid_but_oversize_cannot_be_repaired():
    value = data()
    assert row(value).status == "pass"
    value.plan["setups"][0]["ops"][1]["to_dia"] = 6.38
    assert row(value).status == "error"


def test_final_configured_setting_must_match_command_not_nominal_range():
    value = data()
    value.inventory["tools"]["hone"]["dia_mm"] = fact(6.36)
    assert row(value).status == "error"


@pytest.mark.parametrize("change", ["range", "resolution", "early", "stock", "unverified"])
def test_instrument_limits_and_final_stage_order_are_binding(change):
    value = data()
    ops = value.plan["setups"][0]["ops"]
    gauge = value.inventory["gauges"]["bore"]
    if change == "range":
        gauge["range_mm"] = [7, 8]
    elif change == "resolution":
        gauge["resolution_mm"] = fact(0.2)
    elif change == "early":
        ops.insert(2, ops.pop())
    elif change == "stock":
        ops[2]["stock_to_leave_mm"] = 0.01
    else:
        value.inventory["tools"]["hone"]["dia_mm"] = fact(6.35, "assumed")
    assert row(value).status == ("unknown" if change in {"early", "unverified"} else "error")


def test_setting_outside_band_is_not_excused_by_numerical_command_equality():
    value = data()
    value.plan["setups"][0]["ops"][2]["to_dia"] = 6.4
    value.inventory["tools"]["hone"]["dia_mm"] = fact(6.40000001)
    assert row(value).status == "error"


def test_plain_drill_and_reamer_size_checks_stay_strict():
    value = data()
    value.plan["setups"][0]["ops"] = value.plan["setups"][0]["ops"][:1]
    assert row(value).status == "error"
    value.plan["setups"][0]["ops"][0]["do"] = "ream"
    assert row(value).status == "error"
