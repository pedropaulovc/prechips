"""Physical mill stack arithmetic, independent of authored reference outputs."""

from types import SimpleNamespace

import pytest

from prechips.rules.headroom import evaluate


def bundle():
    return SimpleNamespace(
        plan={"stock": {"length_mm": 100, "section_mm": [30, 16]}, "setups": [{
            "id": "S1", "machine": "mill", "frame": "A",
            "stock_state": {"top_z": 4, "bottom_z": -12},
            "hold": {"fixture": "vise", "parallels": "parallel", "supports": "blocks", "support_orientation": "1 in height"},
            "ops": [{"op": 10, "do": "face", "feature": "top", "tool": "cutter", "holder": "holder", "to_z": 0}]}]},
        inventory={"machines": {"mill": {"kind": "mill", "spindle_to_table_max_mm": 200, "travel_mm": {"x": 400, "y": 200}}},
                   "fixtures": {"vise": {"kind": "vise", "bed_height_mm": 20, "jaw_height_mm": 40, "length_mm": 150, "width_mm": 80},
                                "parallel": {"kind": "parallels", "height_mm": 10}, "blocks": {"kind": "blocks_123", "size_in": [1, 2, 3]}},
                   "tools": {"cutter": {"kind": "endmill", "oal_mm": 80}},
                   "holders": {"holder": {"kind": "collet", "gauge_len_mm": 30, "grip_mm": 25}}},
        features={"frames": {"A": {"x": [1, 0, 0], "y": [0, 1, 0]}}, "features": {}}, policy={})


def test_stack_uses_physical_height_not_coordinate_or_jaw_height():
    finding = evaluate(bundle())[0]
    assert finding.status == "pass"
    assert finding.numbers["stock_height_mm"] == 16
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["stacks"][0]["tool_projection_mm"] == 55
    assert finding.numbers["stacks"][0]["margin_mm"] == pytest.approx(18.6)
    assert finding.numbers["stock_top_above_jaws_mm"] == pytest.approx(11.4)
    assert finding.numbers["cut_tip_above_jaws_mm"]["10"] == pytest.approx(7.4)


def test_coordinate_translation_does_not_change_spindle_stack():
    data = bundle()
    state = data.plan["setups"][0]["stock_state"]
    state.update(top_z=104, bottom_z=88)
    data.plan["setups"][0]["ops"][0]["to_z"] = 100
    finding = evaluate(data)[0]
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["cut_tip_above_jaws_mm"]["10"] == pytest.approx(7.4)


def test_retained_rail_bottom_is_supported_stock_bottom():
    data = bundle()
    data.plan["setups"][0]["stock_state"].update(bottom_z=-7, retained_rail_bottom_z=-12)
    finding = evaluate(data)[0]
    assert finding.numbers["stock_height_mm"] == 16
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)


def test_worst_stack_is_per_operation_not_sum_of_independent_maxima():
    data = bundle()
    data.inventory["tools"]["long"] = {"kind": "endmill", "projection_mm": 70}
    data.inventory["holders"]["short"] = {"kind": "collet", "gauge_len_mm": 10}
    data.plan["setups"][0]["ops"].append({"op": 20, "do": "face", "tool": "long", "holder": "short"})
    finding = evaluate(data)[0]
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["stacks"][1]["sum_mm"] == pytest.approx(176.4)


def test_measured_stack_over_limit_is_error_and_equality_passes():
    data = bundle()
    data.inventory["machines"]["mill"]["spindle_to_table_max_mm"] = 181.4
    assert evaluate(data)[0].status == "pass"
    data.inventory["machines"]["mill"]["spindle_to_table_max_mm"] = 180
    assert evaluate(data)[0].status == "error"


def test_vendor_verified_geometry_preserves_nominal_numbers_not_pass():
    data = bundle()
    data.inventory["machines"]["mill"]["verify"] = True
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)


def test_unknown_projection_does_not_invent_stack():
    data = bundle()
    del data.inventory["holders"]["holder"]["grip_mm"]
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"


def test_below_jaw_target_is_separate_unresolved_path_check():
    data = bundle()
    data.plan["setups"][0]["ops"][0]["to_z"] = -10
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["jaw_obstruction"]["requires_path_check"] is True
    assert finding.numbers["cut_tip_above_jaws_mm"]["10"] == pytest.approx(-2.6)


def test_part_and_fixture_envelope_must_fit_travel():
    data = bundle()
    data.inventory["machines"]["mill"]["travel_mm"]["x"] = 140
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 150


def test_block_orientation_unknown_does_not_guess_shortest_dimension():
    data = bundle()
    del data.plan["setups"][0]["hold"]["support_orientation"]
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["support_blocks_mm"] == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"


def test_inch_envelope_and_holder_dimensions_convert_once():
    data = bundle()
    machine = data.inventory["machines"]["mill"]
    del machine["spindle_to_table_max_mm"]
    machine["spindle_to_table_max_in"] = 8
    data.inventory["holders"]["holder"] = {
        "kind": "collet", "gauge_len_in": 1, "grip_mm": 25,
    }
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["spindle_to_table_max_mm"] == pytest.approx(203.2)
    assert finding.numbers["sum_mm"] == pytest.approx(176.8)
