"""Measured setup boundaries, provenance debt, and shop-owned M5 gating."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.findings import exit_code
from prechips.rules import envelope, holder_stack

MEASURED = {"by": "synthetic operator", "date": "2026-10-03", "instrument": "synthetic steel rule"}


def measured(value):
    return {"value": value, "measured": deepcopy(MEASURED)}


def bundle():
    return SimpleNamespace(
        plan={
            "stock": {"form": "flat_bar", "length_mm": 100, "section_mm": [30, 16]},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "stock_state": {"top_z": 4, "bottom_z": -12},
                    "hold": {"fixture": "vise", "parallels": "parallel"},
                    "ops": [
                        {
                            "op": 10,
                            "do": "face",
                            "feature": "top",
                            "tool": "cutter",
                            "holder": "holder",
                            "to_z": 4,
                            "approach_mm": 5,
                        }
                    ],
                }
            ],
        },
        features={
            "units": "mm",
            "frames": {
                "model": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
                "A": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
            },
            "features": {"top": {"kind": "face", "requirements": []}},
        },
        inventory={
            "machines": {
                "mill": {
                    "kind": "mill",
                    "envelope": {
                        "spindle_to_table_max_mm": measured(200),
                        "spindle_to_table_min_mm": measured(30),
                        "travel_mm": {"x": measured(400), "y": measured(200), "z": measured(100)},
                    },
                }
            },
            "fixtures": {
                "vise": {"kind": "vise", "jaw_height_mm": 40},
                "parallel": {"kind": "parallels", "height_mm": 10},
            },
            "tools": {"cutter": {"kind": "endmill", "dia_mm": 10, "oal_mm": 80}},
            "holders": {
                "holder": {
                    "kind": "collet",
                    "gauge_len_mm": measured(30),
                    "projection_mm": measured(55),
                }
            },
        },
        policy={"required": {"envelope": "*", "travel": "*"}},
    )


def test_measured_setup_passes_and_stack_is_physical_not_z_coordinate():
    data = bundle()
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["stack_mm"] == 151
    data.plan["setups"][0]["stock_state"].update(top_z=104, bottom_z=88)
    assert envelope.evaluate(data)[0].numbers["stacks"][0]["stack_mm"] == 151
    assert holder_stack.evaluate(data)[0].status == "pass"


def test_maximum_boundary_passes_and_overtall_stack_stops_with_sheet_sentence():
    data = bundle()
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_max_mm"] = measured(151)
    assert envelope.evaluate(data)[0].status == "pass"
    limits["spindle_to_table_max_mm"] = measured(150)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["upper_margin_mm"] == -1
    assert "exceeds spindle-to-table maximum" in row.sentence
    assert "by 1 mm" in row.sentence
    assert exit_code([row], {"required": {}}) == 2


def test_minimum_boundary_passes_then_unreachable_low_stack_stops():
    data = bundle()
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_min_mm"] = measured(151)
    assert envelope.evaluate(data)[0].status == "pass"
    limits["spindle_to_table_min_mm"] = measured(152)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert "below spindle-to-table minimum" in row.sentence


@pytest.mark.parametrize("limit", ["spindle_to_table_max_mm", "spindle_to_table_min_mm"])
def test_vendor_limit_retains_nominal_but_cannot_pass_or_fail(limit):
    data = bundle()
    nominal = 1 if "max" in limit else 999
    data.inventory["machines"]["mill"]["envelope"][limit] = {"value": nominal, "verify": True}
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers[limit] == nominal
    assert exit_code([row], {"required": {"envelope": "*"}}) == 4
    assert exit_code([row], {"required": {}}) == 0


def test_gauge_metadata_is_required_and_missing_holder_stays_unknown():
    data = bundle()
    data.inventory["holders"]["holder"]["gauge_len_mm"] = 30
    row = holder_stack.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["holder_gauge_len_mm"] == 30
    data.plan["setups"][0]["ops"][0]["holder"] = "absent"
    assert holder_stack.evaluate(data)[0].numbers["holder_gauge_len_mm"] == "unknown"


def test_measured_oal_minus_measured_grip_is_projection_not_flute_length():
    data = bundle()
    holder = data.inventory["holders"]["holder"]
    del holder["projection_mm"]
    holder["grip_mm"] = measured(25)
    data.inventory["tools"]["cutter"].update(oal_mm=measured(80), flute_len_mm=5)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["tool_projection_mm"] == 55
    holder["grip_mm"] = 25
    assert envelope.evaluate(data)[0].status == "unknown"


def test_kernel_bbox_consumed_only_if_already_successful_and_transformed():
    data = bundle()
    data.kernel = {"status": "ok", "bbox_mm": [-1, -2, -3, 2, 5, 8]}
    data.features["frames"]["A"].update(x=[0, 0, 1], z=[-1, 0, 0])
    row = envelope.evaluate(data)[0]
    assert row.numbers["part_extents_mm"] == {"x": 11, "y": 7, "z": 16}
    assert row.numbers["stacks"][0]["stack_mm"] == 151
    data.kernel["status"] = "unknown"
    assert envelope.evaluate(data)[0].numbers["part_extents_mm"]["z"] == 16


def test_each_operation_uses_its_own_gauge_and_projection_pair():
    data = bundle()
    data.inventory["holders"]["short"] = {
        "gauge_len_mm": measured(10),
        "projection_mm": measured(70),
    }
    data.plan["setups"][0]["ops"].append(
        {"op": 20, "do": "face", "holder": "short", "tool": "cutter"}
    )
    rows = envelope.evaluate(data)[0].numbers["stacks"]
    assert [row["stack_mm"] for row in rows] == [151, 146]


def test_lathes_and_manual_operations_do_not_gain_fake_mill_measurements():
    data = bundle()
    data.inventory["machines"]["mill"]["kind"] = "lathe"
    assert envelope.evaluate(data)[0].status == "not_applicable"
    data.plan["setups"][0]["ops"][0]["do"] = "inspect"
    assert holder_stack.evaluate(data)[0].status == "not_applicable"


def test_complete_feature_extents_are_available_when_no_stock_box_is_authored():
    data = bundle()
    data.plan["stock"] = "unknown"
    data.features["features"]["top"]["bounds"] = {"x": [-1, 3], "y": [-2, 4], "z": [-3, 5]}
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["part_extents_mm"] == {"x": 4, "y": 6, "z": 16}
    data.features["features"]["top"]["bounds"]["z"] = "unknown"
    # A supported setup height remains known, but does not invent XY extents.
    assert envelope.evaluate(data)[0].numbers["part_extents_mm"]["x"] == "unknown"


def test_finished_bbox_cannot_clear_an_overtall_received_blank():
    data = bundle()
    data.kernel = {"status": "ok", "bbox_mm": [0, 0, 0, 100, 30, 3]}
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(145)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["stack_mm"] == 151


def test_stack_decimal_residue_at_limit_is_not_a_real_clearance_error():
    data = bundle()
    data.plan["setups"][0]["stock_state"].update(top_z=0.4, bottom_z=0)
    data.plan["setups"][0]["hold"].pop("parallels")
    data.inventory["fixtures"]["vise"]["jaw_height_mm"] = 0.3
    data.inventory["holders"]["holder"].update(
        gauge_len_mm=measured(0.1), projection_mm=measured(0.2)
    )
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits.update(spindle_to_table_max_mm=measured(1), spindle_to_table_min_mm=measured(1))
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["upper_margin_mm"] == 0
    limits["spindle_to_table_max_mm"] = measured(0.999)
    assert envelope.evaluate(data)[0].status == "error"


def test_sibling_projection_debt_cannot_hide_an_independently_measured_gauge():
    data = bundle()
    data.inventory["holders"]["holder"].update(
        measured=deepcopy(MEASURED),
        gauge_len_mm=30,
        projection_mm={"value": 55, "verify": True},
    )
    gauge = holder_stack.evaluate(data)[0]
    assert gauge.status == "pass"
    assert gauge.numbers["holder_gauge_len_mm"] == 30
    assert envelope.evaluate(data)[0].status == "unknown"


def test_unknown_holder_availability_cannot_be_cleared_by_dimensional_measurement():
    data = bundle()
    data.inventory["holders"]["holder"]["present"] = "unknown"
    assert holder_stack.evaluate(data)[0].status == "unknown"
    assert envelope.evaluate(data)[0].status == "unknown"
