"""Explicit guided-profile intent reaches native inputs without a geometry claim."""

from copy import deepcopy

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel


@pytest.mark.parametrize("action", ["profile", "rough_profile", "finish_profile"])
@pytest.mark.parametrize("guide", ["unknown", {}, {"x": [0, 20], "y": [0, 10]}, []])
def test_explicit_sweep_bounds_always_select_guided_profile_model(tmp_path, action, guide):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(do=action, contour={"sweep_bounds": deepcopy(guide)})
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert prepared["profile_model"] == "guided_sweep"
    assert kernel._engine_op(prepared)["profile_model"] == "guided_sweep"
    # This is intent, not proof of a path or validity of the authored guide.
    assert "checkpoints" not in prepared
    assert op["contour"]["sweep_bounds"] == guide


def test_guided_marker_preserves_broad_box_precedence_inputs(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(
        contour={"sweep_bounds": "unknown"},
        stock_removal_bounds={"x": [0, 20], "y": [0, 10], "z": [0, 6]},
    )
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    native = kernel._engine_op(prepared)
    assert native["profile_model"] == "guided_sweep"
    assert native["stock_removal_bounds"] == {"x": [0, 20], "y": [0, 10], "z": [0, 6]}


@pytest.mark.parametrize("action", ["finish_face", "rough_face", "drill"])
def test_explicit_guide_does_not_select_profile_model_for_other_actions(tmp_path, action):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(do=action, contour={"sweep_bounds": "unknown"})
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert "profile_model" not in prepared
    assert "profile_model" not in kernel._engine_op(prepared)


def test_guided_model_changes_operative_identity_but_presentation_does_not(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    ordinary = kernel._engine_op(kernel.op_inputs(data, setup, op, finishing=set(), complete=set()))
    assert "profile_model" not in ordinary
    op["contour"] = {"sweep_bounds": "unknown"}
    guided = kernel._engine_op(kernel.op_inputs(data, setup, op, finishing=set(), complete=set()))
    assert kernel._json(kernel._cache_recipe({"stock": {}, "ops": [guided]})) != kernel._json(
        kernel._cache_recipe({"stock": {}, "ops": [ordinary]})
    )
    op["note"] = "Additional hobby explanation; no change to the cut."
    annotated = kernel._engine_op(
        kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    )
    assert annotated == guided
