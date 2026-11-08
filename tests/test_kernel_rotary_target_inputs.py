"""Rotary target intent survives host serialization without claiming native validity."""

from copy import deepcopy

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel


@pytest.fixture
def rotary_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    # Forwarding target intent must not depend on native cylinder or head validation.
    data.plan["setups"][0]["ops"][0]["approach"] = "rotary"
    return data


@pytest.fixture(params=["op_inputs", "_engine_op"])
def prepared_inputs(request):
    def prepare(data):
        setup = data.plan["setups"][0]
        inputs = kernel.op_inputs(data, setup, setup["ops"][0], finishing=set(), complete=set())
        return kernel._engine_op(inputs) if request.param == "_engine_op" else inputs

    return prepare


@pytest.mark.parametrize("action", ["rough_profile", "finish_profile"])
@pytest.mark.parametrize("units, scale", [("mm", 1.0), ("in", 25.4)])
def test_explicit_rotary_target_scales_once_without_mutating_source(
    rotary_bundle, prepared_inputs, action, units, scale
):
    rotary_bundle.features["units"] = units
    op = rotary_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=2.5)
    source = deepcopy(op)

    inputs = prepared_inputs(rotary_bundle)

    assert inputs["approach"] == "rotary"
    assert inputs["to_dia_mm"] == pytest.approx(2.5 * scale)
    assert "rough_allowance_mm" not in inputs
    assert op == source


@pytest.mark.parametrize("action", ["rough_profile", "finish_profile"])
@pytest.mark.parametrize(
    "target",
    ["unknown", "2.5", None, True, False, 0.0, -1.0, float("nan"), float("inf"), -float("inf")],
)
def test_invalid_explicit_rotary_target_stays_present_unknown(
    rotary_bundle, prepared_inputs, action, target
):
    op = rotary_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=target)

    inputs = prepared_inputs(rotary_bundle)

    assert inputs["to_dia_mm"] == "unknown"
    assert "rough_allowance_mm" not in inputs


@pytest.mark.parametrize("action", ["rough_profile", "finish_profile"])
@pytest.mark.parametrize("units", ["unknown", "cm", None])
def test_explicit_rotary_target_with_unknown_units_stays_present_unknown(
    rotary_bundle, prepared_inputs, action, units
):
    rotary_bundle.features["units"] = units
    op = rotary_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=2.5)

    inputs = prepared_inputs(rotary_bundle)

    assert inputs["to_dia_mm"] == "unknown"
    assert "rough_allowance_mm" not in inputs


@pytest.mark.parametrize("action", ["rough_profile", "finish_profile"])
def test_rotary_target_overflow_after_scaling_stays_present_unknown(
    rotary_bundle, prepared_inputs, action
):
    rotary_bundle.features["units"] = "in"
    rotary_bundle.plan["setups"][0]["ops"][0].update(do=action, to_dia=1e308)

    assert prepared_inputs(rotary_bundle)["to_dia_mm"] == "unknown"


@pytest.mark.parametrize("action", ["rough_profile", "finish_profile"])
@pytest.mark.parametrize("units", ["mm", "in", "unknown"])
def test_omitted_rotary_target_remains_absent(rotary_bundle, prepared_inputs, action, units):
    rotary_bundle.features["units"] = units
    rotary_bundle.plan["setups"][0]["ops"][0]["do"] = action

    inputs = prepared_inputs(rotary_bundle)

    assert "to_dia_mm" not in inputs
    if action == "rough_profile":
        assert inputs["rough_allowance_mm"] == "unknown"
    else:
        assert "rough_allowance_mm" not in inputs


@pytest.mark.parametrize("units, scale", [("mm", 1.0), ("in", 25.4)])
@pytest.mark.parametrize("with_target", [False, True])
@pytest.mark.parametrize(
    "leave_fields, expected",
    [
        ({"rough_allowance_mm": 0.3}, 0.3),
        ({"stock_to_leave_mm": 0.4}, 0.4),
        ({"rough_allowance_mm": 0.3, "stock_to_leave_mm": 0.4}, 0.3),
        ({"rough_allowance_mm": 0.0, "stock_to_leave_mm": 0.4}, 0.0),
        ({"stock_to_leave_mm": 0.0}, 0.0),
        ({"rough_allowance_mm": "unknown", "stock_to_leave_mm": 0.4}, "unknown"),
        ({"rough_allowance_mm": None}, "unknown"),
        ({"stock_to_leave_mm": "unknown"}, "unknown"),
        ({"stock_to_leave_mm": -0.1}, "unknown"),
    ],
)
def test_authored_rotary_rough_leave_keeps_machine_mm_and_precedence(
    rotary_bundle, prepared_inputs, units, scale, with_target, leave_fields, expected
):
    rotary_bundle.features["units"] = units
    op = rotary_bundle.plan["setups"][0]["ops"][0]
    op.update(do="rough_profile", **leave_fields)
    if with_target:
        op["to_dia"] = 2.5
    source = deepcopy(op)

    inputs = prepared_inputs(rotary_bundle)

    assert inputs["rough_allowance_mm"] == expected
    if with_target:
        assert inputs["to_dia_mm"] == pytest.approx(2.5 * scale)
    else:
        assert "to_dia_mm" not in inputs
    assert op == source


@pytest.mark.parametrize("units", ["mm", "in", "unknown"])
@pytest.mark.parametrize("leave_key", ["rough_allowance_mm", "stock_to_leave_mm"])
def test_rotary_rough_leave_does_not_require_known_feature_units(
    rotary_bundle, prepared_inputs, units, leave_key
):
    rotary_bundle.features["units"] = units
    op = rotary_bundle.plan["setups"][0]["ops"][0]
    op.update(do="rough_profile", to_dia=2.5, **{leave_key: 0.3})

    assert prepared_inputs(rotary_bundle)["rough_allowance_mm"] == 0.3


@pytest.mark.parametrize("units, scale", [("mm", 1.0), ("in", 25.4)])
@pytest.mark.parametrize("with_target", [False, True])
@pytest.mark.parametrize(
    "leave_fields",
    [
        {"rough_allowance_mm": 0.3},
        {"stock_to_leave_mm": 0.4},
        {"rough_allowance_mm": 0.3, "stock_to_leave_mm": 0.4},
        {"rough_allowance_mm": "unknown"},
    ],
)
def test_rotary_finish_incoming_leave_is_not_forwarded_as_target_offset(
    rotary_bundle, prepared_inputs, units, scale, with_target, leave_fields
):
    rotary_bundle.features["units"] = units
    op = rotary_bundle.plan["setups"][0]["ops"][0]
    op.update(do="finish_profile", **leave_fields)
    if with_target:
        op["to_dia"] = 2.5
    source = deepcopy(op)

    inputs = prepared_inputs(rotary_bundle)

    assert "rough_allowance_mm" not in inputs
    assert "stock_to_leave_mm" not in inputs
    if with_target:
        assert inputs["to_dia_mm"] == pytest.approx(2.5 * scale)
    else:
        assert "to_dia_mm" not in inputs
    assert op == source
