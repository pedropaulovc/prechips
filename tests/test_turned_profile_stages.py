"""Accepted intermediate turning commands are stock stages, not final-face attainment."""

import dataclasses

import pytest
from test_lathe_m2 import bundle, setup

from prechips.rules import stickout, turned_profile


def _stage():
    data = bundle()
    data.features["features"] = {
        "body": {
            "kind": "shaft", "frame": "model", "dia_nominal": 8.0,
            "z_mm": [0.0, 20.0],
        }
    }
    setup(data)["ops"] = [
        {"op": 10, "do": "rough_turn", "feature": "body", "tool": "turner",
         "to_dia": 10.0, "z_from": 0.0, "z_to": 20.0}
    ]
    return dataclasses.replace(
        data,
        kernel={
            "status": "ok",
            "setups": {"S1": {"stock_profile": [[0.0, 20.0, 5.0, 6.0]]}},
            "ops": {
                "S1:10": {
                    "turn_target": {
                        "status": "accepted", "diameter_mm": 10.0,
                        "z_mm": [0.0, 20.0], "attained_indices": [],
                    }
                }
            },
        },
    )


def test_intermediate_target_uses_actual_native_stage_not_future_nominal():
    data = _stage()
    profile = turned_profile.evaluate(data)[0]
    assert profile.status == "pass"
    assert profile.numbers["intervals"][0]["diameter_mm"] == 10.0
    assert profile.numbers["intervals"][0]["source"] == "kernel_stock"
    assert stickout.evaluate(data)[0].numbers["diameter_mm"] == 10.0


@pytest.mark.parametrize("change", ["target", "window", "status", "stock"])
def test_explicit_stage_without_bound_native_proof_is_unknown(change):
    data = _stage()
    target = data.kernel["ops"]["S1:10"]["turn_target"]
    if change == "target":
        target["diameter_mm"] = 9.0
    elif change == "window":
        target["z_mm"] = [0.0, 19.0]
    elif change == "status":
        target["status"] = "unknown"
    else:
        data.kernel["setups"]["S1"].pop("stock_profile")
    assert turned_profile.evaluate(data)[0].status == "unknown"
    assert stickout.evaluate(data)[0].status == "unknown"
