"""Explicit turning cylinders credit only native whole-face attainment.

Synthetic native facts exercise host consumers; geometry itself remains native-owned.
"""

from copy import deepcopy

import pytest
from test_geometry_rules import bundle  # noqa: F401 (pytest fixture)

from prechips.rules import accessibility, coverage, finish_coverage
from prechips.rules.geometry_common import op_claims


def _turn(data, *, diameter=10.0, window=(0.0, 20.0), attained=(1,), action="finish_turn"):
    setup = data.plan["setups"][0]
    data.inventory["machines"]["mill"]["kind"] = "lathe"
    op = setup["ops"][0]
    op.update(do=action, to_dia=diameter, z_from=window[0], z_to=window[1])
    detail = data.kernel["ops"]["S1:10"]
    detail.update(
        approach="turning",
        turn_target={
            "diameter_mm": diameter,
            "z_mm": sorted(window),
            "status": "accepted",
            "attained_indices": list(attained),
        },
    )
    return setup, op, detail


def _status(rule, data):
    [row] = rule.evaluate(data)
    return row.status


@pytest.mark.parametrize("action", ["rough_turn", "finish_turn"])
def test_intermediate_diameter_does_not_credit_candidate_final_face(bundle, action):  # noqa: F811
    setup, op, _ = _turn(bundle, diameter=12.0, attained=(), action=action)
    assert op_claims(bundle, bundle.kernel, setup, op) == (set(), [], [])
    assert _status(coverage, bundle) == "error"
    assert _status(finish_coverage, bundle) == "error"


def test_partial_axial_window_does_not_credit_a_whole_face(bundle):  # noqa: F811
    setup, op, _ = _turn(bundle, window=(5.0, 10.0), attained=())
    assert op_claims(bundle, bundle.kernel, setup, op)[0] == set()
    for rule in (coverage, finish_coverage):
        assert _status(rule, bundle) == "error"


def test_actual_final_attainment_credits_coverage_and_finish(bundle):  # noqa: F811
    setup, op, detail = _turn(bundle)
    # Extra attained faces never expand the direction-valid candidate claim.
    detail["turn_target"]["attained_indices"] = [1, 2]
    assert op_claims(bundle, bundle.kernel, setup, op)[0] == {1}
    for rule in (coverage, finish_coverage):
        assert _status(rule, bundle) == "pass"


@pytest.mark.parametrize(
    "target",
    [
        None,
        "unknown",
        {},
        {"status": "unknown"},
        {"status": "stopped"},
        {"attained_indices": "unknown"},
        {"attained_indices": [True]},
        {"attained_indices": [-1]},
        {"attained_indices": [1.0]},
        {"attained_indices": [1, 1]},
        {"diameter_mm": 12.0},
        {"diameter_mm": True},
        {"diameter_mm": float("nan")},
        {"diameter_mm": float("inf")},
        {"z_mm": [0.0, 10.0]},
        {"z_mm": [20.0, 0.0]},
        {"z_mm": [0.0]},
        {"z_mm": [False, 20.0]},
        {"z_mm": [0.0, float("inf")]},
    ],
)
def test_missing_unknown_malformed_or_stale_evidence_is_debt(bundle, target):  # noqa: F811
    setup, op, detail = _turn(bundle)
    if isinstance(target, dict):
        detail["turn_target"].update(deepcopy(target))
        if not target:
            detail["turn_target"] = {}
    else:
        detail["turn_target"] = target
    assert op_claims(bundle, bundle.kernel, setup, op) == (None, [], [])
    for rule in (coverage, finish_coverage):
        assert _status(rule, bundle) == "unknown"


def test_target_identity_uses_scaled_current_commands_and_sorted_window(bundle):  # noqa: F811
    setup, op, detail = _turn(bundle, diameter=1.0, window=(2.0, 0.0))
    bundle.features["units"] = "in"
    detail["turn_target"].update(diameter_mm=25.4, z_mm=[0.0, 50.8])
    assert op_claims(bundle, bundle.kernel, setup, op)[0] == {1}
    # Changing either authored command invalidates previously accepted evidence.
    op["to_dia"] = 1.1
    assert op_claims(bundle, bundle.kernel, setup, op)[0] is None
    op["to_dia"] = 1.0
    op["z_from"] = 3.0
    assert op_claims(bundle, bundle.kernel, setup, op)[0] is None


@pytest.mark.parametrize(
    "field,value", [("to_dia", "unknown"), ("z_from", "unknown"), ("z_to", 0.0)]
)
def test_unresolved_or_degenerate_current_command_cannot_reuse_evidence(bundle, field, value):  # noqa: F811
    setup, op, _ = _turn(bundle)
    op[field] = value
    assert op_claims(bundle, bundle.kernel, setup, op)[0] is None


def test_target_debt_keeps_direction_and_mapping_errors(bundle):  # noqa: F811
    setup, op, detail = _turn(bundle)
    detail["turn_target"]["status"] = "unknown"
    detail["claim_errors"] = ["#1"]
    assert op_claims(bundle, bundle.kernel, setup, op) == (None, ["#1"], [])
    assert _status(accessibility, bundle) == "error"
    bundle.kernel["mapping_errors"]["#1"] = "missing STEP face"
    assert op_claims(bundle, bundle.kernel, setup, op) == (None, [], ["#1"])


@pytest.mark.parametrize("legacy", ["no_target", "facing"])
def test_profile_and_facing_claims_do_not_require_turn_target(bundle, legacy):  # noqa: F811
    setup, op, detail = _turn(bundle)
    detail.pop("turn_target")
    if legacy == "no_target":
        op.pop("to_dia")
        op.pop("z_from")
        op.pop("z_to")
    else:
        op["to_z"] = 0.0
    assert op_claims(bundle, bundle.kernel, setup, op) == ({1}, [], [])


@pytest.mark.parametrize(
    "action",
    [
        "turn",
        "rough_turn",
        "finish_turn",
        "profile_turn",
        "profile",
        "form",
        "form_dome",
        "form_relief",
        "groove",
        "rough_groove",
        "finish_groove",
    ],
)
@pytest.mark.parametrize("attained", [[], [1]])
def test_bounded_legacy_profiles_credit_only_native_whole_face_attainment(
    bundle,  # noqa: F811
    action,
    attained,
):
    setup, op, detail = _turn(bundle, window=(5.0, 10.0), action=action)
    op.pop("to_dia")
    detail.pop("turn_target")
    detail["turn_window"] = {
        "status": "accepted",
        "z_mm": [5.0, 10.0],
        "attained_indices": attained,
    }
    assert op_claims(bundle, bundle.kernel, setup, op) == (set(attained), [], [])
    assert _status(coverage, bundle) == ("pass" if attained else "error")
    if not action.startswith("rough"):
        assert _status(finish_coverage, bundle) == ("pass" if attained else "error")


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        {"status": "unknown", "z_mm": [0.0, 20.0], "attained_indices": "unknown"},
        {"status": "accepted", "z_mm": [0.0, 10.0], "attained_indices": [1]},
        {"status": "accepted", "z_mm": [0.0, 20.0], "attained_indices": [True]},
    ],
)
def test_bounded_legacy_missing_unknown_or_mismatched_window_is_debt(bundle, evidence):  # noqa: F811
    setup, op, detail = _turn(bundle)
    op.pop("to_dia")
    detail.pop("turn_target")
    if evidence is not None:
        detail["turn_window"] = evidence
    assert op_claims(bundle, bundle.kernel, setup, op) == (None, [], [])
    for rule in (coverage, finish_coverage):
        assert _status(rule, bundle) == "unknown"


def test_window_evidence_cannot_replace_explicit_diameter_evidence(bundle):  # noqa: F811
    setup, op, detail = _turn(bundle)
    detail["turn_window"] = {
        "status": "accepted",
        "z_mm": [0.0, 20.0],
        "attained_indices": [1],
    }
    detail.pop("turn_target")
    assert op_claims(bundle, bundle.kernel, setup, op)[0] is None
