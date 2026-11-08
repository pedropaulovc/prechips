"""A known custom pose mismatch is stack uncertainty, not measured clearance."""

from copy import deepcopy

import pytest
from test_envelope_m5 import bundle, measured

from prechips.rules import envelope, headroom
from prechips.rules._envelope import supported_height_datum


def custom_bundle(*, top=4, bottom=-12, origin=-12):
    data = bundle()
    # The envelope-only base omits XY placement/cut bounds. Headroom also checks
    # travel, so this positive control must supply those independent facts.
    data.plan["stock"].update(origin_mm=[0, 0, bottom], axis=[1, 0, 0], section_axis=[0, 1, 0])
    data.feature_definitions["top"].update(
        frame="A", bounds={"x": [0, 100], "y": [0, 30], "z": [top, top]}
    )
    setup = data.plan["setups"][0]
    setup["stock_state"].update(top_z=top, bottom_z=bottom)
    setup["hold"] = {
        "fixture": "custom",
        "parallels": "none",
        "riser": "base",
        "pose": {"origin_mm": [0, 0, origin], "x": [1, 0, 0], "z": [0, 0, 1]},
    }
    data.inventory["fixtures"]["custom"] = {
        "kind": "custom",
        "height_mm": measured(22),
        "bed_height_mm": measured(22),
    }
    data.inventory["fixtures"]["base"] = {"kind": "parallels", "height_mm": measured(16)}
    return data


@pytest.mark.parametrize("rule", [headroom, envelope])
def test_matched_custom_datum_keeps_single_bearing_height_computable(rule):
    row = rule.evaluate(custom_bundle())[0]
    assert row.status == "pass"
    assert "supported_height_datum" not in row.numbers
    stack = row.numbers["stacks"][0]
    # 22 primary + 16 single bearing + 16 stock + 55 projection + 30 gauge.
    key = "sum_mm" if rule is headroom else "stack_mm"
    assert stack[key] == 139 + (25 if rule is headroom else 0)


@pytest.mark.parametrize("rule", [headroom, envelope])
@pytest.mark.parametrize("minimum,maximum", [(30, 200), (180, 181), (0, 1)])
@pytest.mark.parametrize(
    "top,bottom,origin",
    [(0.72175, -7.77825, -4.77285), (2.28365, -4.79635, -2.4892), (4, -12, -20)],
)
def test_straddling_and_offset_datums_do_not_prove_either_vertical_margin(
    rule, top, bottom, origin, minimum, maximum
):
    data = custom_bundle(top=top, bottom=bottom, origin=origin)
    # Neither generous limits nor either spindle-stop violation proves the assumed stack.
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_min_mm"] = measured(minimum)
    limits["spindle_to_table_max_mm"] = measured(maximum)
    row = rule.evaluate(data)[0]
    assert row.status == "unknown"
    evidence = row.numbers["supported_height_datum"]
    assert evidence["stock_bottom_setup_mm"] == bottom
    assert evidence["fixture_origin_setup_mm"][2] == origin
    assert "do not establish stock bottom" in row.sentence
    stack = row.numbers["stacks"][0]
    if rule is headroom:
        assert stack["sum_mm"] == stack["margin_mm"] == "unknown"
        assert stack["verify"] is True
    else:
        assert stack["spindle_nose_table_band_mm"] == "unknown"
        assert stack["upper_margin_mm"] == stack["lower_margin_mm"] == "unknown"
        assert stack["verified"] is False
        assert any("supported_height_datum" in debt["id"] for debt in row.numbers["measurements"])


@pytest.mark.parametrize("rule", [headroom, envelope])
def test_datum_uncertainty_preserves_independent_nonpositive_stock_error(rule):
    data = custom_bundle(top=-13, bottom=-12, origin=0)
    row = rule.evaluate(data)[0]
    assert row.status == "error"
    assert "supported stock height is not positive" in row.sentence
    assert row.numbers["supported_height_datum"]


def test_guard_compares_setup_units_to_explicit_pose_millimetres():
    data = custom_bundle(bottom=-1, origin=-25.4)
    data.features["units"] = "in"
    assert supported_height_datum(data, data.plan["setups"][0]) == {}
    data.plan["setups"][0]["hold"]["pose"]["origin_mm"][2] = -1
    evidence = supported_height_datum(data, data.plan["setups"][0])
    assert evidence["stock_bottom_setup_mm"] == -25.4


def test_known_tilt_refuses_scalar_stack_but_missing_pose_keeps_existing_policy():
    data = custom_bundle()
    setup = data.plan["setups"][0]
    original = deepcopy(setup["hold"]["pose"])
    setup["hold"]["pose"].update(x=[0, 0, -1], z=[1, 0, 0])
    assert supported_height_datum(data, setup)["fixture_z"] == [1, 0, 0]
    for rule in (headroom, envelope):
        row = rule.evaluate(data)[0]
        assert row.status == "unknown"
        assert row.numbers["supported_height_datum"]["fixture_z"] == [1, 0, 0]
    setup["hold"]["pose"] = original
    del setup["hold"]["pose"]
    assert supported_height_datum(data, setup) == {}
    assert envelope.evaluate(data)[0].status == "pass"


def test_retained_bottom_controls_the_datum_guard_without_changing_authored_stock():
    data = custom_bundle()
    setup = data.plan["setups"][0]
    setup["stock_state"]["retained_rail_bottom_z"] = -15
    before = deepcopy(data.plan)
    evidence = supported_height_datum(data, setup)
    assert evidence["stock_bottom_field"] == "retained_rail_bottom_z"
    assert evidence["stock_bottom_setup_mm"] == -15
    assert data.plan == before
