"""Measured setup boundaries, provenance debt, and shop-owned M5 gating."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.findings import exit_code
from prechips.rules import engagement, envelope, headroom

MEASURED = {"by": "synthetic operator", "date": "2026-10-03", "instrument": "synthetic steel rule"}


def measured(value):
    return {"value": value, "measured": deepcopy(MEASURED)}


def bundle():
    data = SimpleNamespace(
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
                "vise": {"kind": "vise", "jaw_height_mm": 40, "bed_height_mm": measured(40)},
                "parallel": {"kind": "parallels", "height_mm": measured(10)},
            },
            "tools": {
                "cutter": {
                    "kind": "endmill",
                    "dia_mm": measured(10),
                    "oal_mm": measured(80),
                    "projection_mm": {"holder": measured(55)},
                }
            },
            "holders": {
                "holder": {
                    "kind": "collet",
                    "gauge_len_mm": measured(30),
                    "grip_mm": measured(25),
                }
            },
        },
        policy={"required": {"envelope": "*", "travel": "*"}},
    )
    data.feature_definitions = data.features["features"]
    return data


def test_measured_setup_passes_and_stack_is_physical_not_z_coordinate():
    data = bundle()
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["stack_mm"] == 151
    data.plan["setups"][0]["stock_state"].update(top_z=104, bottom_z=88)
    assert envelope.evaluate(data)[0].numbers["stacks"][0]["stack_mm"] == 151


@pytest.mark.parametrize(
    "review_geometry,boundary,rejected_limit,margin",
    [(False, 156, 155, -1), (True, 141, 136, -5)],
)
def test_maximum_boundary_includes_safe_approach_and_overtall_stack_stops(
    review_geometry, boundary, rejected_limit, margin
):
    data = review_bundle() if review_geometry else bundle()
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = measured(40)
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_max_mm"] = measured(boundary)
    boundary_row = envelope.evaluate(data)[0]
    assert boundary_row.status == "pass"
    assert boundary_row.numbers["stacks"][0]["upper_margin_mm"] == 0
    limits["spindle_to_table_max_mm"] = measured(rejected_limit)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["upper_margin_mm"] == margin
    assert exit_code([row], {"required": {}}) == 2


def test_minimum_boundary_passes_then_unreachable_low_stack_stops():
    data = bundle()
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_min_mm"] = measured(151)
    assert envelope.evaluate(data)[0].status == "pass"
    limits["spindle_to_table_min_mm"] = measured(152)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["lower_margin_mm"] == -1


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


def test_gauge_metadata_is_required_by_envelope_consumer():
    data = bundle()
    data.inventory["holders"]["holder"]["gauge_len_mm"] = 30
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["stacks"][0]["holder_gauge_len_mm"] == 30
    assert row.numbers["stacks"][0]["verified"] is False
    assert "holders.holder.gauge_len" in {entry["id"] for entry in row.numbers["measurements"]}


def test_measured_oal_minus_measured_grip_is_projection_not_flute_length():
    data = bundle()
    holder = data.inventory["holders"]["holder"]
    del data.inventory["tools"]["cutter"]["projection_mm"]
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
    data.inventory["holders"]["short"] = {"kind": "collet", "gauge_len_mm": measured(10)}
    data.inventory["tools"]["cutter"]["projection_mm"]["short"] = measured(70)
    data.plan["setups"][0]["ops"].append(
        {"op": 20, "do": "face", "holder": "short", "tool": "cutter", "to_z": 4, "approach_mm": 5}
    )
    rows = envelope.evaluate(data)[0].numbers["stacks"]
    assert [row["stack_mm"] for row in rows] == [151, 146]


def test_lathes_and_manual_operations_do_not_gain_fake_mill_measurements():
    data = bundle()
    data.inventory["machines"]["mill"]["kind"] = "lathe"
    assert envelope.evaluate(data)[0].status == "not_applicable"
    data.plan["setups"][0]["ops"][0]["do"] = "inspect"
    data.inventory["machines"]["mill"]["kind"] = "mill"
    assert envelope.evaluate(data)[0].status == "not_applicable"


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
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = measured(0.3)
    data.inventory["holders"]["holder"]["gauge_len_mm"] = measured(0.1)
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = measured(0.2)
    data.plan["setups"][0]["ops"][0].update(to_z=0.4, approach_mm=0)
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits.update(spindle_to_table_max_mm=measured(1), spindle_to_table_min_mm=measured(1))
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["upper_margin_mm"] == 0
    limits["spindle_to_table_max_mm"] = measured(0.999)
    assert envelope.evaluate(data)[0].status == "error"


def test_selected_projection_debt_does_not_hide_independently_measured_gauge():
    data = bundle()
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = {"value": 55, "verify": True}
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["stacks"][0]["holder_gauge_len_mm"] == 30
    ids = {entry["id"] for entry in row.numbers["measurements"]}
    assert "tools.cutter.projection.holder" in ids
    assert "holders.holder.gauge_len" not in ids


def review_bundle():
    """Measured synthetic geometry from the reviewer probes, never shop inventory."""
    data = bundle()
    data.plan["setups"][0]["stock_state"].update(top_z=0, bottom_z=-16)
    data.plan["setups"][0]["ops"][0]["to_z"] = 0
    data.features["features"]["top"]["bounds"] = {"x": [0, 100], "y": [0, 30], "z": [0, 0]}
    data.inventory["fixtures"]["vise"].update(bed_height_mm=measured(90), jaw_height_mm=40)
    data.inventory["fixtures"]["parallel"]["height_mm"] = measured(10)
    data.inventory["tools"]["cutter"].update(
        oal_mm=measured(60), projection_mm={"holder": measured(40)}
    )
    data.inventory["holders"]["holder"]["grip_mm"] = measured(20)
    return data


def test_review_1_vise_bed_not_jaws_stops_overtall_stack():
    data = review_bundle()
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(140)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["fixture_height_mm"] == 100
    assert row.numbers["stacks"][0]["stack_mm"] == 186
    assert row.numbers["stacks"][0]["upper_margin_mm"] == -51


def test_review_2_holder_scalar_cannot_certify_another_tools_projection():
    data = review_bundle()
    data.inventory["holders"]["holder"]["projection_mm"] = measured(40)
    data.inventory["tools"]["longdrill"] = {
        "kind": "drill",
        "dia_mm": measured(6),
        "oal_mm": measured(150),
        "point_angle": measured(118),
    }
    data.features["features"]["hole"] = {
        "kind": "hole",
        "at": [10, 10, 0],
        "thru": False,
        "depth": 20,
    }
    data.plan["setups"][0]["ops"].append(
        {
            "op": 20,
            "do": "drill",
            "feature": "hole",
            "tool": "longdrill",
            "holder": "holder",
            "depth_mm": 5,
            "approach_mm": 5,
        }
    )
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(220)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert [op["tool_projection_mm"] for op in row.numbers["stacks"]] == [40, 130]


def test_review_3_minimum_must_reach_deepest_commanded_cut():
    data = review_bundle()
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = measured(40)
    data.plan["setups"][0]["ops"][0].update(do="pocket", to_z=-30)
    data.features["features"]["top"]["bounds"]["z"] = [-30, 0]
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_min_mm"] = measured(136)
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["lower_margin_mm"] == -30


def test_review_10_unresolved_holder_requests_resolution_not_measurement():
    data = review_bundle()
    data.plan["setups"][0]["ops"][0]["holder"] = "unowned-chuck"
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert not any(
        entry["id"] in {"holders.unowned-chuck.gauge_len", "holders.unowned-chuck.grip"}
        for entry in row.numbers["measurements"]
    )


@pytest.mark.parametrize("bed", [90, "unknown"])
def test_vise_bed_requires_its_own_measurement_not_jaw_geometry(bed):
    data = review_bundle()
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = bed
    data.inventory["fixtures"]["vise"]["jaw_height_mm"] = 500
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert "fixtures.vise.bed_height" in {entry["id"] for entry in row.numbers["measurements"]}


def test_missing_authored_approach_cannot_certify_envelope():
    data = review_bundle()
    data.plan["setups"][0]["ops"][0].pop("approach_mm")
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["stacks"][0]["verified"] is False
    debt = next(
        entry for entry in row.numbers["measurements"] if entry["id"].endswith(".z_geometry")
    )
    assert debt["instruction"].startswith("author:")
    assert "approach_mm" in debt["instruction"]
    assert debt["units"] == "mm"


def test_through_drill_entry_exit_and_measured_point_set_minimum_nose_floor():
    data = review_bundle()
    data.features["features"]["hole"] = {"kind": "hole", "at": [10, 10, 0], "thru": True}
    data.inventory["tools"]["cutter"].update(
        kind="drill", dia_mm=measured(6), point_angle=measured(90)
    )
    setup = data.plan["setups"][0]
    setup["stock_state"]["local_thickness"] = {"hole": 16}
    setup["ops"][0].update(do="drill", feature="hole", exit_mm=1)
    setup["ops"][0].pop("to_z")
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_min_mm"] = measured(166)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["tip_z_bounds_mm"] == pytest.approx([-20, 5])
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == pytest.approx([166, 191])
    limits["spindle_to_table_min_mm"] = measured(167)
    assert envelope.evaluate(data)[0].status == "error"


# A selected tool or holder is the same item spelled with its category: its projection,
# measurement debt and citation name the item's key.
@pytest.mark.parametrize("tool_spelling", ["", "tools."])
@pytest.mark.parametrize("holder_spelling", ["", "holders."])
def test_member_tool_projection_requires_exact_full_selected_holder_key(
    tool_spelling, holder_spelling
):
    data = review_bundle()
    data.inventory["holders"]["collets"] = {
        "kind": "collet_set",
        "members": {"3-8in": {"gauge_len_mm": measured(30), "grip_mm": measured(20)}},
    }
    data.inventory["tools"]["mills"] = {
        "kind": "endmill_set",
        "members": {
            "selected": {
                "kind": "endmill",
                "oal_mm": measured(80),
                "projection_mm": {"collets": measured(5), "collets/3-8in": measured(55)},
            }
        },
    }
    data.plan["setups"][0]["ops"][0].update(
        tool=tool_spelling + "mills/selected", holder=holder_spelling + "collets/3-8in"
    )
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["tool_projection_mm"] == 55
    data.inventory["tools"]["mills"]["members"]["selected"]["projection_mm"]["collets/3-8in"] = (
        "unknown"
    )
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    debt = next(entry for entry in row.numbers["measurements"] if ".projection." in entry["id"])
    assert debt["id"] == "tools.mills/selected.projection.collets/3-8in"
    assert debt["cite"] == ["inventory.tools.mills/selected.projection_mm.collets/3-8in"]


# Two spellings of one holder in a tool's projection map state its projection twice. The
# projection is unknown, with both keys named, never the entry dictionary order puts first:
# 5 mm alone passes and 55 mm alone errors (envelope) or halves the DOC (engagement).
@pytest.mark.parametrize("op_holder", ["holder", "holders.holder"])
@pytest.mark.parametrize("first", ["holder", "holders.holder"])
@pytest.mark.parametrize("values", [(5, 55), (55, 5), (5, "unknown"), ("unknown", 5)])
def test_two_spellings_of_one_holder_in_a_projection_map_leave_it_unknown(op_holder, first, values):
    data = review_bundle()
    second = "holders.holder" if first == "holder" else "holder"
    stated = [value if value == "unknown" else measured(value) for value in values]
    data.inventory["tools"]["cutter"]["projection_mm"] = {first: stated[0], second: stated[1]}
    data.plan["setups"][0]["ops"][0].update(holder=op_holder, doc_mm=1)
    keys = {"projection_mm.holder", "projection_mm.holders.holder"}
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["stacks"][0]["tool_projection_mm"] == "unknown"
    debt = next(e for e in row.numbers["measurements"] if e["id"] == "tools.cutter.projection")
    assert all(key in debt["instruction"] for key in keys), debt
    [use] = engagement.evaluate(data)
    assert use.status == "unknown" and use.numbers["projection_mm"] == "unknown"
    assert any(all(key in text for key in keys) for text in use.numbers["missing_inputs"])
    [room] = headroom.evaluate(data)
    assert room.status == "unknown"
    assert room.numbers["stacks"][0]["tool_projection_mm"] == "unknown"
    assert all(key in room.numbers["stacks"][0]["projection_conflict"] for key in keys)


def test_tool_wide_scalar_and_wrong_pair_cannot_replace_selected_oal_grip():
    data = review_bundle()
    tool = data.inventory["tools"]["cutter"]
    tool.update(oal_mm=measured(150), projection_mm=measured(5))
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["tool_projection_mm"] == 130
    tool["projection_mm"] = {"not-selected": measured(5)}
    row = envelope.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["stacks"][0]["tool_projection_mm"] == 130


def test_missing_approach_instruction_is_printed_once():
    data = review_bundle()
    data.plan["setups"][0]["ops"][0].pop("approach_mm")
    row = envelope.evaluate(data)[0]
    debt = next(
        entry for entry in row.numbers["measurements"] if entry["id"].endswith(".z_geometry")
    )
    assert row.sentence.count(debt["instruction"].removeprefix("author: ")) == 1


@pytest.mark.parametrize("field", ["fixture", "parallels", "supports", "riser"])
@pytest.mark.parametrize("identity", ["unowned", "unknown"])
def test_unresolved_fixture_requests_identity_not_height_measurement(field, identity):
    data = review_bundle()
    data.plan["setups"][0]["hold"][field] = identity
    if identity == "unknown":
        data.inventory["fixtures"][identity] = {"kind": "unknown"}
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    debts = {entry["id"]: entry for entry in row.numbers["measurements"]}
    assert f"fixtures.{identity}.height" not in debts
    assert debts[f"fixtures.{identity}.resolve"]["instruction"].startswith("resolve:")


def test_machine_hosted_dividing_head_supplies_the_fixture_height():
    data = bundle()
    data.plan["setups"][0]["hold"] = {"fixture": "head", "parallels": "none"}
    head = {"kind": "dividing_head", "height_mm": measured(50)}
    data.inventory["machines"]["head"] = head
    row = envelope.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["stacks"][0]["stack_mm"] == 151
    assert "inventory.machines.head.height" in row.cite
    head["height_mm"] = 50
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert "machines.head.height" in {entry["id"] for entry in row.numbers["measurements"]}


@pytest.mark.parametrize("action,field", [("drill", "point_angle"), ("ream", "lead")])
@pytest.mark.parametrize("identity", ["unowned", "unknown"])
def test_unresolved_hole_tool_does_not_request_unowned_measurement(action, field, identity):
    data = review_bundle()
    data.features["features"]["hole"] = {"kind": "hole", "at": [10, 10, 0], "thru": True}
    data.plan["setups"][0]["ops"][0].update(do=action, feature="hole", tool=identity, exit_mm=1)
    if identity == "unknown":
        data.inventory["tools"][identity] = {"kind": "unknown"}
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    debts = {entry["id"]: entry for entry in row.numbers["measurements"]}
    assert f"tools.{identity}.{field}" not in debts
    assert debts[f"tools.{identity}.resolve"]["instruction"].startswith("resolve:")
