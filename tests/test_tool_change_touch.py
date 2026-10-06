"""One DRO per setup: a tool that did not set it is touched off before it cuts."""

from types import SimpleNamespace

import pytest

from prechips.rules.zero_recipe import evaluate

DRO = {
    "controller": "el400",
    "mode": "abs",
    "radius_mode": False,
    "direction": {"x": "away_from_spindle_axis", "y": "away", "z": "toward_exposed_end"},
}


def bundle(machine, zero, ops, stock_state=None):
    data = SimpleNamespace(
        plan={
            "dro": DRO,
            "setups": [
                {
                    "id": "S1",
                    "machine": machine,
                    "frame": "F",
                    "zero": zero,
                    "stock_state": stock_state or {},
                    "ops": ops,
                }
            ],
        },
        features={"frames": {"F": {"binding": "nominal"}}, "features": {}},
        inventory={
            "machines": {"lathe": {"kind": "lathe"}, "mill": {"kind": "mill"}},
            "tools": {
                name: {"kind": kind, "tip_in": 0.2}
                for name, kind in (
                    ("turner", "insert_holder"),
                    ("parter", "parting_blade"),
                    ("finder", "edge_finder"),
                    ("centre", "center_drill"),
                    ("drill", "drill"),
                    ("mill", "endmill"),
                )
            },
            "gauges": {"mic": {"kind": "micrometer"}},
        },
    )
    data.feature_definitions = data.features["features"]
    return data


def op(number, do, feature, tool, **extra):
    return {"op": number, "do": do, "feature": feature, "tool": tool, **extra}


def lathe_zero(touches):
    return {
        "x": {
            "feature": "spindle_axis",
            "edge_mm": 0.0,
            "from": "+x",
            "method": "trial_cut_measure",
            "tool": "turner",
            "gauge": "mic",
            "check_jog_mm": 10.0,
        },
        "z": {
            "face": "stub end",
            "edge_mm": 5.0,
            "from": "+z",
            "method": "touch",
            "tool": "turner",
            "paper_mm": 0.0,
            "check_jog_mm": 10.0,
            "retouch_after": [],
        },
        "tool_touches": touches,
    }


BLADE = {
    "tool": "parter",
    "x_method": "touch the journal just measured",
    "gauge": "mic",
    "z_face": "shoulder",
    "edge_mm": -7.5,
    "paper_mm": 0.05,
    "method": "paper",
    "before_ops": [40],
}
LATHE_OPS = [
    op(10, "rough_turn", "journal", "turner"),
    op(20, "face", "shoulder", "turner", to_z=-7.5),
    op(30, "finish_turn", "journal", "turner"),
    op(40, "form_relief", "relief", "parter"),
]


def test_the_turning_tool_back_after_a_blade_touch_is_re_touched():
    ops = [*LATHE_OPS, op(50, "face", "dome", "turner", to_z=0.0)]
    finding = evaluate(bundle("lathe", lathe_zero([BLADE]), ops))[0]
    assert finding.status == "pass"
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    # Z repeats the blade's touch on the shoulder; X touches the last diameter turned.
    assert touch["before_ops"] == [50] and touch["tool"] == "turner"
    assert (touch["z_face"], touch["edge_mm"], touch["paper_mm"]) == ("shoulder", -7.5, 0.05)
    assert touch["z_axis_set"] == pytest.approx(-7.45)
    assert (touch["x_face"], touch["gauge"], touch["x_axis_set"]) == (
        "journal",
        "mic",
        "measured D",
    )


def test_a_blade_that_finishes_the_setup_needs_no_re_touch():
    finding = evaluate(bundle("lathe", lathe_zero([BLADE]), LATHE_OPS))[0]
    assert finding.status == "pass"
    assert finding.numbers["derived_touches"] == []


def test_a_lathe_tool_change_with_no_diameter_to_touch_is_an_error():
    # The blade's X came from its own trial cut: no measured diameter stands for the
    # turning tool to touch, so its X Axis Set cannot be derived.
    touch = {**BLADE, "x_method": "trial_cut_measure", "before_ops": [20]}
    ops = [
        op(10, "face", "shoulder", "turner", to_z=-7.5),
        op(20, "part_off", "relief", "parter"),
        op(30, "face", "dome", "turner", to_z=0.0),
    ]
    finding = evaluate(bundle("lathe", lathe_zero([touch]), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "turner", "axes": ["x"], "dro_set_by": "parter"}
    ]


def mill_zero(z, retouch_after=()):
    return {
        "x": {"edge": "left", "edge_mm": 0.0, "from": "-x", "tool": "finder", "check_jog_mm": 5},
        "y": {"edge": "front", "edge_mm": 0.0, "from": "-y", "tool": "finder", "check_jog_mm": 5},
        "z": {
            "from": "+z",
            "check_jog_mm": 5.0,
            "paper_mm": 0.05,
            "retouch_after": list(retouch_after),
            **z,
        },
        "tool_touches": [],
    }


DECK = {"face": "deck", "edge_mm": 10.0, "method": "touch", "tool": "centre"}


def test_a_drill_after_the_centre_drill_that_set_z_is_re_touched_on_the_zero_face():
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", mill_zero(DECK), ops))[0]
    assert finding.status == "pass"
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [20] and touch["tool"] == "drill"
    assert (touch["z_face"], touch["edge_mm"], touch["paper_mm"]) == ("deck", 10.0, 0.05)
    assert touch["z_axis_set"] == pytest.approx(10.05)
    assert "x_axis_set" not in touch


def test_a_faced_away_top_is_not_touched_again_the_new_face_is():
    zero = mill_zero({"face": "top", "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", to_z=0.0), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 2.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["edge_mm"], touch["z_axis_set"]) == ("deck", 0.0, 0.05)


def test_a_listed_retouch_serves_only_the_next_tool():
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "spot", "hole", "centre"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 2.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [30] and touch["z_face"] in ("deck", "top")
    assert touch["z_axis_set"] == pytest.approx(0.05)


def test_a_top_picked_up_after_a_facing_op_is_re_touched_where_that_op_left_it():
    # The face runs before the zero (no tool has set Z yet); the centre drill then
    # touches the faced top, and the drill repeats that touch at -2, not the incoming 0.
    zero = mill_zero({"face": "top", "tool": "centre", "after_op": 10})
    ops = [
        op(10, "face", "deck", "mill", to_z=-2.0),
        op(20, "spot", "hole", "centre"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 0.0}))[0]
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [30] and touch["edge_mm"] == pytest.approx(-2.0)
    assert touch["z_axis_set"] == pytest.approx(-1.95)


def test_a_measured_zero_gives_no_plan_z_to_re_touch_so_the_change_is_an_error():
    z = {
        "face": "deck",
        "edge_mm": 10.0,
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "deck height above the vise floor",
        "offset_mm": -1.0,
        "tool": "centre",
    }
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", mill_zero(z), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 20, "tool": "drill", "axes": ["z"], "dro_set_by": "centre"}
    ]


@pytest.mark.parametrize(
    "change,axis_set,check,mirror",
    [
        ({}, "M -0.95", "M +4.05", "M -5.95"),
        ({"gauge": "unknown"}, "unknown", "unknown", "unknown"),
        ({"measure": ""}, "unknown", "unknown", "unknown"),
        ({"offset_mm": "unknown"}, "unknown", "unknown", "unknown"),
    ],
)
def test_a_measured_z_zero_sets_the_measurement_plus_offset_and_paper(
    change, axis_set, check, mirror
):
    z = {
        "face": "deck",
        "edge_mm": 10.0,
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "deck height above the vise floor",
        "offset_mm": -1.0,
        "tool": "centre",
        **change,
    }
    finding = evaluate(bundle("mill", mill_zero(z), [op(10, "spot", "hole", "centre")]))[0]
    row = finding.numbers["axes"]["z"]
    assert (row["axis_set"], row["check_reading"], row["mirrored_reading"]) == (
        axis_set,
        check,
        mirror,
    )
    assert finding.status == ("pass" if axis_set != "unknown" else "unknown")


def test_a_mill_tool_touch_is_z_only_and_may_be_measured():
    touch = {
        "tool": "drill",
        "z_face": "boss",
        "edge_mm": 3.0,
        "paper_mm": 0.05,
        "method": "measure_then_set",
        "z_gauge": "mic",
        "z_measure": "boss height above the deck",
        "z_offset_mm": 10.0,
        "before_ops": [20],
    }
    zero = {**mill_zero(DECK), "tool_touches": [touch]}
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops))[0]
    assert finding.status == "pass"
    [row] = finding.numbers["tool_touches"]
    assert (row["x_axis_set"], row["z_axis_set"]) == ("not_applicable", "M +10.05")
    assert finding.numbers["derived_touches"] == []
