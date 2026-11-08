"""Explicit turning diameters survive host normalization without claiming native validity."""

from copy import deepcopy

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel


@pytest.fixture
def turning_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup["machine"] = "lathe"
    data.inventory["machines"]["lathe"] = {"kind": "lathe"}
    # Deliberately incomplete tool geometry: forwarding a requested target is not
    # permission to execute it. The native model must still validate the tool.
    return data


def prepared_inputs(data):
    setup = data.plan["setups"][0]
    prepared = kernel.op_inputs(data, setup, setup["ops"][0], finishing=set(), complete=set())
    return prepared, kernel._engine_op(prepared)


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn"])
@pytest.mark.parametrize("units, scale", [("mm", 1.0), ("in", 25.4)])
def test_explicit_turn_target_and_window_scale_once(turning_bundle, action, units, scale):
    data = turning_bundle
    data.features["units"] = units
    op = data.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=2.5, z_from=-1.0, z_to=3.0)
    source = deepcopy(op)
    for inputs in prepared_inputs(data):
        assert inputs["approach"] == "turning"
        assert inputs["to_dia_mm"] == pytest.approx(2.5 * scale)
        assert inputs["z_from"] == pytest.approx(-1.0 * scale)
        assert inputs["z_to"] == pytest.approx(3.0 * scale)
    assert op == source


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn"])
@pytest.mark.parametrize("target", ["unknown", -1.0, None, True])
def test_invalid_explicit_turn_target_remains_unknown_not_absent(turning_bundle, action, target):
    op = turning_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=target, z_from=0.0, z_to=3.0)
    for inputs in prepared_inputs(turning_bundle):
        assert inputs["to_dia_mm"] == "unknown"


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn"])
@pytest.mark.parametrize("window", [{}, {"z_from": "unknown", "z_to": 3.0}])
@pytest.mark.parametrize("tool_kind", ["turning_tool", "parting_blade"])
def test_explicit_turn_target_is_not_dropped_for_native_validation(
    turning_bundle, action, window, tool_kind
):
    op = turning_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=2.5, **window)
    turning_bundle.inventory["tools"]["em"]["kind"] = tool_kind
    for inputs in prepared_inputs(turning_bundle):
        assert inputs["to_dia_mm"] == 2.5
        if "z_from" in window:
            assert inputs["z_from"] == "unknown"
        else:
            assert "z_from" not in inputs
            assert "z_to" not in inputs


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn"])
def test_profile_turn_without_target_stays_without_target(turning_bundle, action):
    op = turning_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, z_from=0.0, z_to=3.0)
    for inputs in prepared_inputs(turning_bundle):
        assert "to_dia_mm" not in inputs


@pytest.mark.parametrize("action", ["face", "rough_face", "finish_face", "cut_to_fit", "part_off"])
@pytest.mark.parametrize("units, scale", [("mm", 1.0), ("in", 25.4)])
@pytest.mark.parametrize("target", [0.0, 2.5])
def test_existing_radial_target_zero_and_scaling_are_preserved(
    turning_bundle, action, units, scale, target
):
    turning_bundle.features["units"] = units
    op = turning_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=target)
    for inputs in prepared_inputs(turning_bundle):
        assert inputs["to_dia_mm"] == pytest.approx(target * scale)


@pytest.mark.parametrize("action", ["face", "rough_face", "finish_face", "cut_to_fit", "part_off"])
def test_only_partoff_keeps_legacy_axis_default(turning_bundle, action):
    op = turning_bundle.plan["setups"][0]["ops"][0]
    op["do"] = action
    for inputs in prepared_inputs(turning_bundle):
        if action == "part_off":
            assert inputs["to_dia_mm"] == 0.0
        else:
            assert "to_dia_mm" not in inputs


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn"])
def test_explicit_target_with_unknown_units_stays_unknown(turning_bundle, action):
    turning_bundle.features["units"] = "unknown"
    op = turning_bundle.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=2.5)
    for inputs in prepared_inputs(turning_bundle):
        assert inputs["to_dia_mm"] == "unknown"


@pytest.mark.parametrize(
    "action, target, refused",
    [
        ("finish_turn", 46.0, True),
        ("finish_turn", 41.899999, True),
        ("finish_turn", 41.920001, True),
        ("finish_turn", 41.90, False),
        ("finish_turn", 41.92, False),
        ("rough_turn", 46.0, False),
    ],
)
def test_final_turn_target_uses_exact_diameter_band_without_changing_cad(
    turning_bundle, action, target, refused
):
    data = turning_bundle
    feature = data.features["features"]["pocket"]
    feature.update(kind="cylinder", dia=[41.90, 41.92], dia_nominal=41.91)
    op = data.plan["setups"][0]["ops"][0]
    op.update(do=action, to_dia=target, z_from=0.0, z_to=3.0)
    source_features = deepcopy(data.features)
    source_plan = deepcopy(data.plan)
    source_kernel = deepcopy(data.kernel)
    for inputs in prepared_inputs(data):
        if refused:
            assert inputs["to_dia_mm"] == "unknown"
            assert f"to_dia target {target:g}" in inputs["to_dia_reason"]
            assert "41.9-41.92 mm" in inputs["to_dia_reason"]
        else:
            assert inputs["to_dia_mm"] == target
            assert "to_dia_reason" not in inputs
    assert data.features == source_features
    assert data.plan == source_plan
    assert data.kernel == source_kernel


def test_intermediate_turn_target_before_same_member_finish_is_not_a_final_conflict(
    turning_bundle,
):
    data = turning_bundle
    data.features["features"]["pocket"].update(
        kind="cylinder", dia=[41.90, 41.92], dia_nominal=41.91
    )
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(do="finish_turn", to_dia=46.0, z_from=0.0, z_to=3.0)
    setup["ops"].append({**op, "op": 20, "to_dia": 41.91})
    for inputs in prepared_inputs(data):
        assert inputs["to_dia_mm"] == 46.0
        assert "to_dia_reason" not in inputs
