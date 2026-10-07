"""Deep-hole drilling derates the starting sfm by the hole's depth over its diameter."""

from types import SimpleNamespace

import pytest

from prechips.rules import speeds_feeds

DEEP = {"operation": "drill", "depth_over_dia": 3.0, "sfm_factor": 0.5, "cite": "deep row"}


def drill_bundle(*, depth_mm=None, thickness=None, deep=(DEEP,), action="drill"):
    """A 1/4 in (6.35 mm) HSS drill at 100 sfm: 12*100/(pi*0.25) = 1528 -> 1550 rpm."""
    through = thickness is not None
    op = {"op": 10, "do": action, "feature": "hole", "tool": "drill"}
    if through:
        op["exit_mm"] = 1.0
    elif depth_mm is not None:
        op["depth_mm"] = depth_mm
    stock_state = {"top_z": 0.0}
    if through:
        stock_state["local_thickness"] = {"hole": thickness}
    data = SimpleNamespace(
        plan={
            "stock": {"material": "1018"},
            "setups": [{"id": "S1", "machine": "mill", "stock_state": stock_state, "ops": [op]}],
        },
        features={
            "units": "mm",
            "features": {
                "hole": {
                    "kind": "hole",
                    "dia_nominal": 6.35,
                    "thru": through,
                    "at": [0.0, 0.0, 0.0],
                    "axis": [0.0, 0.0, 1.0],
                }
            },
        },
        inventory={
            "machines": {"mill": {"kind": "mill", "spindle": {"rpm_min": 50, "rpm_max": 3000}}},
            "tools": {
                "drill": {
                    "kind": "drill",
                    "material": "HSS",
                    "dia_mm": 6.35,
                    "flutes": 2,
                    "point_angle": 118.0,
                }
            },
        },
        cutting_data={
            "aliases": {"1018": "low_carbon_steel"},
            "cut": [
                {
                    "material_class": "low_carbon_steel",
                    "tool_material": "HSS",
                    "operation": operation,
                    "diameter_range": [3.0, 13.0],
                    "sfm": 100.0,
                    "chip_load_mm_per_tooth": 0.05,
                    "cite": f"test {operation} row",
                }
                for operation in ("drill", "ream")
            ],
            "deep_hole": [dict(row) for row in deep],
        },
        policy={},
        kernel=None,
    )
    data.feature_definitions = data.features["features"]
    return data


def speeds(data):
    [row] = speeds_feeds.evaluate(data)
    return row


def test_hole_deeper_than_threshold_halves_rpm_and_feed_and_cites_the_row():
    row = speeds(drill_bundle(depth_mm=40.0))  # 40 / 6.35 = 6.3 x D
    # 12 * 50 / (pi * 0.25) = 764 -> 750 rpm; feed per tooth is kept.
    assert row.status == "pass"
    assert row.numbers["rpm"] == 750
    assert row.numbers["feed_mm_min"] == pytest.approx(750 * 2 * 0.05)
    assert row.numbers["sfm"] == 100.0
    assert row.numbers["deep_hole_sfm_factor"] == 0.5
    assert row.numbers["depth_over_dia"] == pytest.approx(40.0 / 6.35)
    assert "deep row" in row.cite


@pytest.mark.parametrize(
    "depth_mm, rpm",
    [(3.0 * 6.35, 1550), (3.0 * 6.35 + 0.01, 750)],
)
def test_threshold_is_strictly_deeper_than_its_diameters(depth_mm, rpm):
    row = speeds(drill_bundle(depth_mm=depth_mm))
    assert row.status == "pass"
    assert row.numbers["rpm"] == rpm


def test_through_hole_depth_is_local_thickness_not_point_or_exit_lead():
    # 18 mm is 2.83 x D; the 1 mm exit and 1.9 mm point would carry the tip past 3 x D.
    row = speeds(drill_bundle(thickness=18.0))
    assert row.status == "pass"
    assert row.numbers["rpm"] == 1550
    assert row.numbers["deep_hole_row"] == "not_applicable"
    row = speeds(drill_bundle(thickness=20.0))
    assert row.numbers["rpm"] == 750


def test_deepest_exceeded_threshold_governs():
    tiers = (DEEP, {**DEEP, "depth_over_dia": 8.0, "sfm_factor": 0.3, "cite": "deeper row"})
    assert speeds(drill_bundle(depth_mm=40.0, deep=tiers)).numbers["rpm"] == 750
    # 60 mm = 9.4 x D: 12 * 30 / (pi * 0.25) = 458 -> 450 rpm.
    row = speeds(drill_bundle(depth_mm=60.0, deep=tiers))
    assert row.numbers["rpm"] == 450
    assert row.numbers["deep_hole_row"] == "deeper row"


def test_operation_no_deep_row_names_keeps_its_speed():
    row = speeds(drill_bundle(depth_mm=40.0, action="ream"))
    assert row.status == "pass"
    assert row.numbers["rpm"] == 1550
    assert "deep_hole_row" not in row.numbers


@pytest.mark.parametrize(
    "depth_mm, deep",
    [
        (None, (DEEP,)),
        (40.0, ({**DEEP, "cite": "unknown"},)),
        (40.0, ({**DEEP, "sfm_factor": 1.5},)),
        (40.0, (DEEP, {**DEEP, "cite": "same threshold"})),
    ],
    ids=["unknown-depth", "uncited", "factor-above-one", "tied-rows"],
)
def test_unresolved_depth_or_deep_row_leaves_rpm_unknown(depth_mm, deep):
    row = speeds(drill_bundle(depth_mm=depth_mm, deep=deep))
    assert row.status == "unknown"
    assert row.numbers["rpm"] == "unknown"
    assert row.numbers["feed_mm_min"] == "unknown"
