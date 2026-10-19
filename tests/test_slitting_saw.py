"""A mill slitting saw is a rotating disk, never a bandsaw or an axial endmill."""

import re
from copy import deepcopy
from pathlib import Path

import pytest
from test_envelope_m5 import bundle as measured_envelope_bundle
from test_geometry_rules import rules_bundle
from test_procedure_boxes import mill_bundle as mill_zero_bundle
from test_procedure_boxes import table_rows

from prechips import kernel
from prechips.findings import exit_code
from prechips.rules import (
    accessibility,
    envelope,
    headroom,
    hold_fields,
    reach,
    saw_cut,
    speeds_feeds,
    tool_resolves,
    travel,
)
from prechips.rules.resolution import saw_setup, saw_station, saw_tool, spindle_saw
from prechips.rules.zero_recipe import rule as zero_recipe
from prechips.sheet import _Traveler

CUT = {
    "op": 20,
    "do": "cut_off",
    "tool": "blade",
    "holder": "holder",
    "cut_plane": {"axis": "x", "value": 60.5, "keep": "below"},
}
ROW = {
    "material_class": "aluminum",
    "tool_material": "hss",
    "operation": "slitting_saw",
    "diameter_range": [50.0, 51.0],
    "sfm": 100.0,
    "chip_load_mm_per_tooth": 0.01,
    "cite": "synthetic slitting-saw chart",
}


def slitting_bundle(*, mixed=False):
    data = rules_bundle(Path("."))
    setup = data.plan["setups"][0]
    setup["ops"] = [*setup["ops"], deepcopy(CUT)] if mixed else [deepcopy(CUT)]
    setup["stock_state"] = {"top_z": 10, "bottom_z": 0}
    data.plan["stock"].update(material="6061", form="flat_bar", length_mm=100, section_mm=[20, 10])
    data.inventory["machines"]["mill"]["spindle"] = {
        "taper": "R8",
        "rpm_min": 100,
        "rpm_max": 2000,
    }
    data.inventory["tools"]["blade"] = {
        "kind": "slitting_saw",
        "material": "hss",
        "dia_mm": 50.8,
        "kerf_mm": 1.0,
        "flutes": 40,
        "verify": False,
    }
    data.inventory["holders"]["holder"].update(kind="saw_arbor", taper="R8")
    data.cutting_data.update(aliases={"6061": "aluminum"}, cut=[deepcopy(ROW)])
    # These are ideal slab-removal facts, not observations of a disk/arbor sweep.
    # Passing axial clearance facts must not certify this different cutter model.
    data.kernel["ops"]["S1:20"] = {
        **deepcopy(data.kernel["ops"]["S1:10"]),
        "cut_plane": deepcopy(CUT["cut_plane"]),
        "kerf_mm": 1.0,
        "retained_boundary_mm": 60.0,
        "kerf_volume_mm3": 200.0,
        "offcut_volume_mm3": 7800.0,
        "removed_volume_mm3": 8000.0,
        "stock_volume_before_mm3": 20000.0,
        "stock_volume_after_mm3": 12000.0,
        "cut_thickness_mm": 10.0,
        "cut_thickness_axis": "z",
    }
    return data


def op_row(rule, data):
    return next(row for row in rule.evaluate(data) if row.subject == "S1:20")


@pytest.mark.parametrize("action", ["saw_cut", "cut_off"])
def test_a_real_slitting_saw_is_recognized_on_a_mill_without_claiming_assembly_fit(action):
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op["do"] = action
    assert saw_tool(data, op) == "slitting_saw"
    assert saw_station(data, setup, op) == "fits"
    assert not saw_setup(data, setup)
    assembly = op_row(tool_resolves, data)
    assert assembly.status == "unknown"
    assert assembly.numbers["holder"] == "holder"
    assert assembly.numbers["arbor_fit"] == "unknown"
    inputs = kernel.op_inputs(data, setup, op)
    assert inputs["saw_tool"] == "slitting_saw"
    assert inputs["kerf_mm"] == 1.0


@pytest.mark.parametrize("kind", ["bench", "manual", "lathe", "bandsaw"])
def test_a_slitting_saw_cannot_gain_a_station_or_assembly_pass_off_a_mill(kind):
    data = slitting_bundle()
    data.inventory["machines"]["mill"]["kind"] = kind
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    assert saw_tool(data, op) == "slitting_saw"
    assert saw_station(data, setup, op) == "wrong_station"
    assembly = op_row(tool_resolves, data)
    assert assembly.status == "error"
    assert op_row(saw_cut, data).status == "error"
    assert op_row(speeds_feeds, data).status == "unknown"
    assert kernel.op_inputs(data, setup, op)["saw_tool"] == "refused"


def test_ideal_planar_cut_and_axial_hit_counts_do_not_certify_a_finite_disk():
    data = slitting_bundle()
    row = op_row(saw_cut, data)
    assert row.status == "unknown"
    assert row.numbers["retained_boundary_mm"] == 60.0
    assert row.numbers["removed_volume_mm3"] == 8000.0
    for rule in (accessibility, reach):
        clearance = op_row(rule, data)
        assert clearance.status == "unknown"
    assert exit_code([row], {"required": {"saw_cut": "*"}}, data) == 4


@pytest.mark.parametrize("missing", ["dia_mm", "kerf_mm", "holder"])
def test_missing_blade_dimensions_or_arbor_remain_debt(missing):
    data = slitting_bundle()
    if missing == "holder":
        del data.plan["setups"][0]["ops"][0]["holder"]
    else:
        del data.inventory["tools"]["blade"][missing]
    row = op_row(tool_resolves, data)
    assert row.status == "unknown"
    if missing == "holder":
        assert row.numbers["holder"] == "unknown"
        assert "ops.20.holder" in hold_fields.evaluate(data)[0].numbers["missing"]
    else:
        field = "blade_diameter_mm" if missing == "dia_mm" else "kerf_mm"
        assert row.numbers[field] == "unknown"


def test_blade_thickness_is_not_inferred_to_be_cutting_kerf():
    data = slitting_bundle()
    blade = data.inventory["tools"]["blade"]
    del blade["kerf_mm"]
    blade["thickness_mm"] = 1.0
    setup = data.plan["setups"][0]
    inputs = kernel.op_inputs(data, setup, setup["ops"][0])
    assert inputs["kerf_mm"] == "unknown"
    row = op_row(saw_cut, data)
    assert row.status == "unknown"


@pytest.mark.parametrize("kerf", [0, -1])
def test_a_known_invalid_kerf_is_still_an_error_not_hidden_by_the_disk_model_debt(kerf):
    data = slitting_bundle()
    data.inventory["tools"]["blade"]["kerf_mm"] = kerf
    row = op_row(saw_cut, data)
    assert row.status == "error"


@pytest.mark.parametrize("field", ["dia_mm", "kerf_mm"])
def test_unverified_dimensions_keep_identity_and_consumer_debt(field):
    data = slitting_bundle()
    blade = data.inventory["tools"]["blade"]
    blade[field] = {"value": blade[field], "verify": True}
    setup = data.plan["setups"][0]
    assert saw_tool(data, setup["ops"][0]) == "unverified"
    assert not saw_setup(data, setup)
    row = op_row(tool_resolves, data)
    assert row.status == "unknown"
    assert f"tools.blade.{field.removesuffix('_mm')}" in {
        entry["id"] for entry in row.numbers["measurements"]
    }
    assert op_row(saw_cut, data).status == "unknown"
    assert op_row(speeds_feeds, data).status == "unknown"


def test_scribed_region_removal_is_not_routed_as_a_finite_disk_cut():
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    del op["cut_plane"]
    op.update(
        follows="S0:10",
        allowance_mm=0.5,
        stock_removal_bounds={"x": [50, 70], "y": [0, 20], "z": [0, 10]},
    )
    inputs = kernel.op_inputs(data, setup, op)
    assert inputs["saw_tool"] == "slitting_saw"
    assert inputs["scribed_profile"].get("reason")
    assert "radius_mm" not in inputs["scribed_profile"]


def test_linear_tpi_and_stock_thickness_do_not_establish_disk_tooth_engagement():
    data = slitting_bundle()
    data.inventory["tools"]["blade"]["tpi"] = 200
    data.policy.update(
        numbers={"saw_min_teeth_in_work": 3},
        numbers_verify=False,
        numbers_cite={"saw_min_teeth_in_work": "synthetic shop policy"},
    )
    [row] = saw_cut.evaluate_teeth(data)
    assert row.status == "unknown"
    assert row.numbers["tooth_count"] == 40
    assert row.numbers["teeth_in_work"] == "unknown"
    assert row.numbers["engagement_arc_deg"] == "unknown"


def test_slitting_speed_is_disk_rpm_and_feed_per_tooth_not_bandsaw_descent():
    data = slitting_bundle()
    data.inventory["machines"]["mill"]["blade_speed_sfm"] = [1, 2]
    data.cutting_data["cut"].append({**ROW, "operation": "saw_cut", "sfm": 200, "feed_mm_min": 900})
    row = op_row(speeds_feeds, data)
    assert row.status == "pass"
    assert row.numbers["operation"] == "slitting_saw"
    assert row.numbers["action"] == "cut_off"
    assert row.numbers["diameter_in"] == 2.0
    assert row.numbers["rpm"] == 200
    assert row.numbers["feed_mm_min"] == 80
    assert row.numbers["cutting_data_row"] == ROW["cite"]
    assert "blade_speed_sfm" not in row.numbers


def test_bandsaw_cutting_data_never_supplies_rotating_slitting_saw_numbers():
    data = slitting_bundle()
    data.cutting_data["cut"] = [{**ROW, "operation": "saw_cut", "feed_mm_min": 900}]
    row = op_row(speeds_feeds, data)
    assert row.status == "unknown"
    assert row.numbers["rpm"] == "unknown"
    assert row.numbers["feed_mm_min"] == "unknown"


@pytest.mark.parametrize("mixed", [False, True], ids=["dedicated", "mixed"])
@pytest.mark.parametrize("rule", [envelope, headroom, travel, zero_recipe])
def test_mounted_saw_keeps_required_setup_rows_instead_of_no_spindle_waivers(rule, mixed):
    data = slitting_bundle(mixed=mixed)
    [row] = rule.evaluate(data)
    assert row.status == "unknown", row.sentence
    assert row.numbers["spindle_saw_ops"] == [20]


def test_the_printed_slitting_saw_operation_keeps_geometry_debt_visible():
    data = slitting_bundle()
    findings = saw_cut.evaluate(data) + tool_resolves.evaluate(data) + speeds_feeds.evaluate(data)
    setup = data.plan["setups"][0]
    html, _, _, _ = _Traveler(data, findings, {}, None).operations(setup, {}, {"notes": 2})
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert "200 rpm" in text
    assert "80 mm/min" in text
    assert "sfm" not in text
    assert "STOP: blade reach, arbor fit and fixture clearance have not been checked." in text
    assert op_row(saw_cut, data).status == "unknown"


def test_a_passing_measured_mill_stack_cannot_hide_a_mixed_slitting_saw():
    data = measured_envelope_bundle()
    data.inventory["tools"]["blade"] = {
        "kind": "slitting_saw",
        "dia_mm": 50.8,
        "kerf_mm": 1.0,
    }
    data.plan["setups"][0]["ops"].append(deepcopy(CUT))
    [row] = envelope.evaluate(data)
    assert row.status == "unknown"
    assert row.numbers["spindle_saw_ops"] == [20]
    assert [stack["op"] for stack in row.numbers["stacks"]] == [10]
    assert row.numbers["stacks"][0]["verified"] is True
    assert row.numbers["stacks"][0]["stack_mm"] == 151
    assert row.numbers["part_extents_mm"]["z"] == 16
    assert "plan.setups.S1.supported_height" not in {
        debt["id"] for debt in row.numbers["measurements"]
    }


@pytest.mark.parametrize("machine_kind", ["mill", "unknown"])
@pytest.mark.parametrize("tool_state", ["missing-slot", "unlisted", "absent-kind", "unknown-kind"])
def test_unresolved_mill_saw_never_gains_nonspindle_waivers(machine_kind, tool_state):
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    del op["holder"]
    data.inventory["machines"]["mill"]["kind"] = machine_kind
    if tool_state == "missing-slot":
        del op["tool"]
    elif tool_state == "unlisted":
        del data.inventory["tools"]["blade"]
    elif tool_state == "absent-kind":
        del data.inventory["tools"]["blade"]["kind"]
    else:
        data.inventory["tools"]["blade"]["kind"] = "unknown"
    assert saw_tool(data, op) == "unknown"
    assert spindle_saw(data, setup, op)
    assert not saw_setup(data, setup)
    for rule in (envelope, headroom, travel, zero_recipe):
        [row] = rule.evaluate(data)
        assert row.status == "unknown"
        assert row.numbers["spindle_saw_ops"] == [20]
    for rule in (accessibility, reach, tool_resolves):
        assert op_row(rule, data).status == "unknown"
    speed = op_row(speeds_feeds, data)
    assert speed.status == "unknown"
    assert speed.numbers["rpm"] == speed.numbers["feed_mm_min"] == "unknown"
    assert "blade_speed_sfm" not in speed.numbers
    assert "ops.20.holder" in hold_fields.evaluate(data)[0].numbers["missing"]


@pytest.mark.parametrize("machine_kind", ["mill", "unknown"])
@pytest.mark.parametrize("tool_kind", ["slitting-saw", "disk", "end_mill", ""])
def test_invalid_saw_kind_retains_spindle_checks_and_known_tool_errors(machine_kind, tool_kind):
    data = slitting_bundle()
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    del op["holder"]
    data.inventory["machines"]["mill"]["kind"] = machine_kind
    data.inventory["tools"]["blade"]["kind"] = tool_kind
    assert saw_tool(data, op) == "not_a_saw"
    assert saw_station(data, setup, op) == "wrong_station"
    assert spindle_saw(data, setup, op)
    assert not saw_setup(data, setup)
    for rule in (envelope, headroom, travel, zero_recipe):
        [row] = rule.evaluate(data)
        assert row.status == "unknown"
    for rule in (accessibility, reach):
        assert op_row(rule, data).status == "unknown"
    for rule in (tool_resolves, saw_cut):
        assert op_row(rule, data).status == "error"
    assert "ops.20.holder" in hold_fields.evaluate(data)[0].numbers["missing"]
    assert kernel.op_inputs(data, setup, op)["saw_tool"] == "refused"


@pytest.mark.parametrize("diameter", [0, -50.8])
def test_known_nonpositive_disk_diameter_is_an_assembly_error(diameter):
    data = slitting_bundle()
    data.inventory["tools"]["blade"]["dia_mm"] = diameter
    row = op_row(tool_resolves, data)
    assert row.status == "error"
    assert row.numbers["blade_diameter_mm"] == diameter


@pytest.mark.parametrize("debt", ["none", "holder", "machine"])
def test_arbor_taper_mismatch_is_an_error_only_when_its_interfaces_are_verified(debt):
    data = slitting_bundle()
    data.inventory["holders"]["holder"]["taper"] = "MT3"
    if debt == "holder":
        data.inventory["holders"]["holder"]["verify"] = True
    elif debt == "machine":
        data.inventory["machines"]["mill"]["verify"] = True
    row = op_row(tool_resolves, data)
    assert row.status == ("error" if debt == "none" else "unknown")
    assert row.numbers["spindle_interface"] == "R8"
    assert row.numbers["holder_interface"] == "MT3"


def mixed_zero_bundle():
    data = deepcopy(mill_zero_bundle())
    data.inventory["tools"]["blade"] = {"kind": "slitting_saw", "dia_mm": 50.8, "kerf_mm": 1.0}
    data.plan["setups"][0]["ops"].append(deepcopy(CUT))
    return data


@pytest.mark.parametrize("mode", ["abs", "incremental"])
def test_mixed_disk_setup_keeps_ordinary_zero_evidence_and_error_precedence(mode):
    data = mixed_zero_bundle()
    data.plan["dro"]["mode"] = mode
    [row] = zero_recipe.evaluate(data)
    assert row.status == ("unknown" if mode == "abs" else "error")
    assert row.numbers["spindle_saw_ops"] == [20]
    assert row.numbers["axes"]["z"]["axis_set"] == pytest.approx(10.05)
    assert row.numbers["axes"]["z"]["check_reading"] == pytest.approx(15.05)
    assert row.numbers["axes"]["z"].get("tool_setting_state") != "unsupported_spindle_saw"
    html = _Traveler(data, [row], {}, None).dro(data.plan["setups"][0], {})
    z_rows = [cells for cells in table_rows(html) if cells[0] == "Z"]
    assert z_rows
    readings = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", " ".join(z_rows[0]))]
    assert any(value == pytest.approx(10.05) for value in readings)
    assert "STOP" in html


def test_mounted_disk_touches_are_not_exposed_as_axial_settings_in_a_mixed_setup():
    data = mixed_zero_bundle()
    setup = data.plan["setups"][0]
    setup["zero"]["z"]["tool"] = "blade"
    setup["zero"]["tool_touches"] = [
        {
            "tool": "blade",
            "z_face": "deck",
            "edge_mm": 10.0,
            "paper_mm": 0.05,
            "method": "paper",
            "before_ops": [20],
        }
    ]
    [row] = zero_recipe.evaluate(data)
    assert row.numbers["axes"]["z"]["tool_setting_state"] == "unsupported_spindle_saw"
    assert row.numbers["axes"]["z"]["axis_set"] == "unknown"
    [touch] = row.numbers["tool_touches"]
    assert touch["tool_setting_state"] == "unsupported_spindle_saw"
    assert touch["z_axis_set"] == "unknown"
    assert isinstance(row.numbers["axes"]["x"]["axis_set"], (int, float))
    html = _Traveler(data, [row], {}, None).dro(setup, {})
    assert "STOP" in html
    assert any(cells[0] == "X" for cells in table_rows(html))
