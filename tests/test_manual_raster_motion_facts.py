"""Finite raster facts never masquerade as axial sample or reach evidence."""

import pytest

from prechips.findings import Finding
from prechips.rules import accessibility, reach
from prechips.rules.manual_raster import METHOD, motion_finding, normalize


def inputs():
    return {
        "manual_raster": {
            "start_mm": [-3.0, 0.0, 10.0],
            "safe_z_mm": 10.0,
            "moves": [
                {"to_mm": [-3.0, 0.0, 0.0], "mode": "clear"},
                {"to_mm": [3.0, 0.0, 0.0], "mode": "cut"},
                {"to_mm": [3.0, 0.0, 10.0], "mode": "clear"},
            ],
        },
        "measurement_debts": [],
    }


def facts():
    return {
        "approach": METHOD,
        "manual_raster_status": "pass",
        "manual_raster_moves": 3,
        "manual_raster_checked_moves": 3,
        "manual_raster_errors": [],
        "tool_hits": 0,
        "shank_hits": 0,
        "holder_hits": 0,
    }


@pytest.mark.parametrize("rule", ["accessibility", "reach"])
def test_complete_finite_cycle_needs_no_axial_sample_count_or_depth(rule):
    result = motion_finding(rule, "S:1", facts(), inputs(), [], None)
    assert result.status == "pass"
    assert "sample_count" not in result.numbers
    assert "reach_depth_mm" not in result.numbers


@pytest.mark.parametrize(
    "changed",
    [
        {"approach": "axial"},
        {"manual_raster_checked_moves": 2},
        {"manual_raster_checked_moves": True},
        {"manual_raster_moves": 4},
        {"manual_raster_errors": "unknown"},
        {"shank_hits": "unknown"},
        {"holder_hits": float("nan")},
        {"manual_raster_status": "unknown"},
    ],
)
def test_incomplete_or_mismatched_evidence_never_passes(changed):
    result = motion_finding("accessibility", "S:1", facts() | changed, inputs(), [], None)
    assert result.status == "unknown"


@pytest.mark.parametrize("part", ["tool", "shank", "holder"])
def test_certain_collision_survives_unrelated_unknown(part):
    detail = facts() | {
        "manual_raster_status": "unknown",
        "tool_hits": "unknown",
        "shank_hits": "unknown",
        "holder_hits": "unknown",
        "min_hits": {part: 1},
    }
    blocked = Finding("reach", "S:1", "unknown", {}, [], "measurement unresolved")
    assert motion_finding("reach", "S:1", detail, inputs(), [], blocked).status == "error"


def test_missing_measurement_block_cannot_be_erased_by_geometric_pass():
    blocked = Finding("reach", "S:1", "unknown", {}, [], "holder measurement unresolved")
    assert motion_finding("reach", "S:1", facts(), inputs(), [], blocked) is blocked


def test_invalid_current_path_does_not_reuse_complete_motion_facts():
    request = inputs()
    request["manual_raster"]["moves"][1]["to_mm"] = [3.0, 1.0, 0.0]
    assert motion_finding("reach", "S:1", facts(), request, [], None).status == "unknown"


def test_huge_integer_coordinate_is_unresolved_not_an_exception():
    path = inputs()["manual_raster"]
    path["start_mm"][0] = 10**1000
    assert "reason" in normalize(path)


@pytest.mark.parametrize("module", [accessibility, reach])
def test_public_rule_consumes_finite_motion_before_axial_fallback(monkeypatch, module):
    context = (
        {"id": "S"},
        {"op": 1, "contour": {"method": METHOD}},
        {},
        facts(),
        inputs(),
        [],
        None,
    )
    monkeypatch.setattr(module, "op_contexts", lambda *args, **kwargs: iter([context]))
    result = module.evaluate(object())
    assert len(result) == 1
    assert result[0].status == "pass"
    assert result[0].numbers["manual_raster_checked_moves"] == 3
