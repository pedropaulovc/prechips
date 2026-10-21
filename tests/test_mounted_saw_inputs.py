"""Mounted disks use measured pair-specific assemblies, never axial-cutter fallbacks.

These are host/schema contracts. Complete inputs are not native contact or safety proof.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_geometry_rules import rules_bundle

from prechips import kernel
from prechips.model import AxisZero, Inventory, MountedSawTouch, Operation, SawTrajectory, ToolTouch

MEASURED = {
    "status": "measured",
    "by": "synthetic saw operator",
    "date": "2026-10-19",
    "instrument": "synthetic micrometer and height gauge",
}
POSE = {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]}


def measured(value, status="measured"):
    return {"value": value, "measured": {**MEASURED, "status": status}}


def cylinder(name, diameter, low, high):
    return {
        "id": name,
        "dia_mm": measured(diameter),
        "z_min_mm": measured(low),
        "z_max_mm": measured(high),
    }


def solid(name="pad"):
    return {
        "name": name,
        "shape": "box",
        "at_mm": [0, 0, 10],
        "size_mm": [10, 10, 1],
        "measured": dict(MEASURED),
    }


def saw_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    data.inventory["tools"]["saw"] = {
        "kind": "slitting_saw",
        "dia_mm": measured(100),
        "root_dia_mm": measured(90),
        "bore_dia_limits_mm": measured([12.7, 12.71]),
        "thickness_mm": measured(3.05),
        "kerf_mm": measured(3.175),
        "kerf_offset_mm": measured(0),
        "flutes": 36,
        "tooth_spacing": "uniform",
        "projection_mm": {"holders.arbor": measured(20)},
    }
    data.inventory["holders"]["arbor"] = {
        "kind": "saw_arbor",
        "taper": "R8",
        "gauge_len_mm": measured(40),
        "mounted_saw_arbor": {
            "pilot_dia_limits_mm": measured([12.69, 12.7]),
            "bore_clearance_max_mm": {"value": 0.03, "cite": "synthetic arbor drawing"},
            "blade_thickness_limits_mm": measured([3.0, 3.2]),
            "envelope_state": "complete",
            "components": [
                cylinder("lower_flange", 20, -24, -21.525),
                cylinder("upper_flange", 20, -18.475, -16),
                cylinder("stem", 12, -16, 40),
            ],
            "cutting_rotation": measured("cw"),
            "retaining_side": "minus_z",
            "retaining_thread_hand": "right",
        },
    }
    data.inventory["machines"]["mill"]["spindle"] = {
        "taper": "R8",
        "rotation": measured("cw"),
    }
    for name in ("setting", "capture", "clamp"):
        data.inventory["fixtures"][name] = {"kind": "custom", "solids": [solid()]}
    setup = data.plan["setups"][0]
    setup["hold"] = {"fixture": "setting", "pose": deepcopy(POSE)}
    setup["ops"] = [
        {
            "op": 10,
            "do": "cut_off",
            "tool": "tools.saw",
            "holder": "arbor",
            "direction": "conventional",
            "cut_plane": {"axis": "z", "value": 10, "keep": "below"},
            "saw_trajectory": {
                "start_mm": [-60, -10, 10],
                "moves": [
                    {"to_mm": [90, -10, 10], "mode": "cut"},
                    {"to_mm": [90, -60, 10], "mode": "clear"},
                ],
            },
            "saw_capture": {
                "fixture": "fixtures.capture",
                "pose": deepcopy(POSE),
                "moving_clamp": "clamp",
                "moving_clamp_pose": deepcopy(POSE),
                "state": "clamped",
            },
        }
    ]
    setup["zero"] = {
        "z": {
            "method": "mounted_saw_side",
            "tool": "saw",
            "holder": "holders.arbor",
            "face": "fixture:fixtures.setting/pad:+z",
            "edge_mm": 11,
            "paper_mm": 0.05,
            "check_jog_mm": 5,
            "mounted_saw": {
                "blade_side": "minus_z",
                "axis_xy_mm": [30, 5],
                "point_mm": [5, 5, 11],
                "spindle_state": "stopped",
            },
        }
    }
    return data


def inputs(data):
    setup = data.plan["setups"][0]
    return kernel.mounted_saw_inputs(data, setup, setup["ops"][-1])


def test_complete_host_recipe_is_deterministic_and_uses_existing_fixture_primitives(tmp_path):
    data = saw_bundle(tmp_path)
    before = deepcopy((data.plan, data.inventory))
    recipe = inputs(data)
    assert recipe == inputs(data)
    assert recipe["status"] == "pass"
    assert recipe["reasons"] == recipe["errors"] == {}
    assert recipe["measurement_debts"] == recipe["refused_fields"] == []
    assert recipe["tool"] == "tools.saw"
    assert recipe["holder"] == "holders.arbor"
    assert recipe["arbor"]["projection_mm"] == 20
    assert recipe["arbor"]["components"][0]["z_min_mm"] == -24
    assert recipe["capture"]["components"][0]["role"] == "fixture"
    assert recipe["capture"]["components"][1]["role"] == "moving_clamp"
    assert recipe["zero"]["selected"] == 0
    touch = recipe["zero"]["touches"][0]
    assert touch["tool"] == "tools.saw" and touch["holder"] == "holders.arbor"
    assert touch["surface"] == {"kind": "fixture", "name": "setting:pad", "side": "+z"}
    assert (data.plan, data.inventory) == before
    setup = data.plan["setups"][0]
    op = kernel.op_inputs(data, setup, setup["ops"][0])
    assert op["mounted_saw"] == {
        key: value
        for key, value in recipe.items()
        if key not in {"measurement_debts", "refused_fields"}
    }
    assert kernel._engine_op(op)["mounted_saw"] == op["mounted_saw"]


@pytest.mark.parametrize("unit,allowance", [("mm", 0.01), ("in", 0.01 / 25.4)])
@pytest.mark.parametrize("qualified", [False, True])
def test_bore_clearance_uses_only_the_qualified_normalized_allowance(
    tmp_path, unit, allowance, qualified
):
    data = saw_bundle(tmp_path)
    arbor = data.inventory["holders"]["arbor"]["mounted_saw_arbor"]
    del arbor["bore_clearance_max_mm"]
    arbor[f"bore_clearance_max_{unit}"] = {
        "value": allowance,
        "cite": "synthetic arbor drawing",
        "verify": not qualified,
    }
    recipe = inputs(data)
    if qualified:
        assert recipe["arbor"]["bore_clearance_max_mm"] == pytest.approx(0.01)
        assert recipe["status"] == "error"
        assert "blade bore clearance exceeds arbor qualified maximum" in recipe["assembly_errors"]
    else:
        assert recipe["arbor"]["bore_clearance_max_mm"] == "unknown"
        assert recipe["status"] == "unknown"
        assert recipe["assembly_errors"] == []
        assert (
            "bore_clearance_max needs one fact-local cited or measured allowance"
            in (recipe["assembly_reasons"])
        )
        assert recipe["measurement_debts"]


@pytest.mark.parametrize("diameter", [12.69, 12.7, 12.71])
def test_bore_sized_components_at_body_faces_are_not_flanges(tmp_path, diameter):
    data = saw_bundle(tmp_path)
    components = data.inventory["holders"]["arbor"]["mounted_saw_arbor"]["components"]
    components.extend(
        [
            cylinder("pilot", 12.69, -21.525, -18.475),
            cylinder("bore_sized_stem", diameter, -18.475, 40),
        ]
    )
    recipe = inputs(data)
    assert recipe["status"] == "pass"
    assert recipe["assembly_reasons"] == []
    assert recipe["assembly_errors"] == []
    assert {component["id"] for component in recipe["arbor"]["components"]} >= {
        "pilot",
        "bore_sized_stem",
    }


@pytest.mark.parametrize("side", ["lower", "upper"])
def test_bore_sized_component_cannot_supply_missing_flange_contact(tmp_path, side):
    data = saw_bundle(tmp_path)
    components = data.inventory["holders"]["arbor"]["mounted_saw_arbor"]["components"]
    flange = next(component for component in components if component["id"] == f"{side}_flange")
    flange["dia_mm"] = measured(12.7)
    recipe = inputs(data)
    assert recipe["status"] == "unknown"
    assert (
        "arbor flange contact with both flat blade-body sides is not established"
        in recipe["assembly_reasons"]
    )


@pytest.mark.parametrize("diameter", [90, 91])
def test_body_face_flange_still_must_remain_inside_tooth_root(tmp_path, diameter):
    data = saw_bundle(tmp_path)
    components = data.inventory["holders"]["arbor"]["mounted_saw_arbor"]["components"]
    components[0]["dia_mm"] = measured(diameter)
    recipe = inputs(data)
    assert recipe["status"] == "error"
    assert (
        "arbor flange must overlap the flat body annulus inside the tooth root"
        in recipe["assembly_errors"]
    )


def test_signed_offset_and_component_bounds_convert_without_positive_length_clamping(tmp_path):
    data = saw_bundle(tmp_path)
    blade = data.inventory["tools"]["saw"]
    del blade["kerf_offset_mm"]
    blade["kerf_offset_in"] = measured(-0.001)
    recipe = inputs(data)
    assert recipe["blade"]["kerf_offset_mm"] == pytest.approx(-0.0254)
    assert recipe["arbor"]["components"][0]["z_max_mm"] == -21.525
    assert recipe["status"] == "pass"


@pytest.mark.parametrize("state", ["assumed", "illustrative"])
def test_pair_measurement_and_individual_cylinder_measurements_keep_local_debt(tmp_path, state):
    data = saw_bundle(tmp_path)
    data.inventory["tools"]["saw"]["projection_mm"]["holders.arbor"] = measured(20, state)
    arbor = data.inventory["holders"]["arbor"]["mounted_saw_arbor"]
    arbor["components"][0]["z_min_mm"] = measured(-24, state)
    recipe = inputs(data)
    debts = {entry["id"]: entry for entry in recipe["measurement_debts"]}
    assert debts["tools.saw.projection.holders.arbor"]["status"] == state
    assert debts["holders.arbor.mounted_saw_arbor.components.lower_flange.z_min"]["status"] == state
    assert recipe["arbor"]["projection_mm"] == "unknown"
    assert recipe["arbor"]["components"][0]["z_min_mm"] == "unknown"
    assert recipe["status"] == "unknown"


def test_disk_never_borrows_axial_oal_minus_grip_fallback(tmp_path):
    data = saw_bundle(tmp_path)
    blade = data.inventory["tools"]["saw"]
    del blade["projection_mm"]
    blade["oal_mm"] = measured(60)
    data.inventory["holders"]["arbor"]["grip_mm"] = measured(40)
    recipe = inputs(data)
    assert recipe["arbor"]["projection_mm"] == "unknown"
    assert any("exact tool-holder pair" in reason for reason in recipe["assembly_reasons"])
    assert any(entry["field"][0] == "projection" for entry in recipe["measurement_debts"])


def test_ambiguous_qualified_projection_is_debt_not_dictionary_order(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["tools"]["saw"]["projection_mm"]["arbor"] = measured(21)
    recipe = inputs(data)
    assert recipe["arbor"]["projection_mm"] == "unknown"
    assert any("each state the projection" in reason for reason in recipe["assembly_reasons"])
    assert recipe["measurement_debts"]


@pytest.mark.parametrize(
    "mutation,fragment",
    [
        ("pilot", "pilot maximum"),
        ("body_band", "body band"),
        ("body_limits", "mounting limits"),
        ("root", "tooth root"),
        ("component_interval", "z_min < z_max"),
        ("rotation", "cutting rotation"),
        ("retainer", "loosen"),
        ("taper", "spindle interface"),
    ],
)
def test_known_assembly_incompatibility_outranks_unrelated_missing_measurement(
    tmp_path, mutation, fragment
):
    data = saw_bundle(tmp_path)
    blade = data.inventory["tools"]["saw"]
    holder = data.inventory["holders"]["arbor"]
    arbor = holder["mounted_saw_arbor"]
    del blade["dia_mm"]
    if mutation == "pilot":
        arbor["pilot_dia_limits_mm"] = measured([13, 13.01])
    elif mutation == "body_band":
        blade["kerf_offset_mm"] = measured(0.2)
    elif mutation == "body_limits":
        arbor["blade_thickness_limits_mm"] = measured([1, 2])
    elif mutation == "root":
        blade["dia_mm"] = measured(80)
    elif mutation == "component_interval":
        arbor["components"][0]["z_min_mm"] = measured(-20)
    elif mutation == "rotation":
        arbor["cutting_rotation"] = measured("ccw")
    elif mutation == "retainer":
        arbor["retaining_thread_hand"] = "left"
    elif mutation == "taper":
        holder["taper"] = "MT3"
    recipe = inputs(data)
    assert recipe["status"] == "error"
    assert any(fragment in error for error in recipe["assembly_errors"])
    if mutation != "root":
        assert recipe["measurement_debts"]


def test_missing_teeth_spacing_is_engagement_debt_not_assembly_debt(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["tools"]["saw"].pop("tooth_spacing")
    recipe = inputs(data)
    assert recipe["assembly_reasons"] == []
    assert any(path.startswith("engagement.") for path in recipe["reasons"])
    assert recipe["status"] == "unknown"


@pytest.mark.parametrize("field", ["saw_trajectory", "saw_capture"])
def test_planar_legacy_inputs_cannot_become_a_complete_finite_saw_recipe(tmp_path, field):
    data = saw_bundle(tmp_path)
    data.plan["setups"][0]["ops"][0].pop(field)
    recipe = inputs(data)
    assert recipe["status"] == "unknown"
    assert recipe["assembly_reasons"] == []


@pytest.mark.parametrize(
    "moves",
    [
        [{"to_mm": [90, -9, 10], "mode": "cut"}],
        [{"to_mm": [-60, -10, 11], "mode": "cut"}],
        [{"to_mm": [90, -10, 10], "mode": "cut"}, {"to_mm": [-60, -10, 10], "mode": "cut"}],
    ],
)
def test_unsupported_diagonal_axial_or_reversing_multicut_paths_keep_debt(tmp_path, moves):
    data = saw_bundle(tmp_path)
    data.plan["setups"][0]["ops"][0]["saw_trajectory"]["moves"] = moves
    assert inputs(data)["trajectory"]["reasons"]


def test_released_capture_and_running_unselected_touch_are_errors_beside_debt(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup["ops"][0]["saw_capture"]["state"] = "released"
    setup["zero"]["z"]["mounted_saw"]["spindle_state"] = "running"
    setup["zero"]["z"]["holder"] = "unknown"
    recipe = inputs(data)
    assert recipe["zero"]["selected"] == "unknown"
    assert recipe["zero"]["errors"]
    assert recipe["capture"]["errors"]
    assert recipe["status"] == "error"


def test_reinstalled_pair_needs_a_new_setting_and_qualified_touch_can_supply_it(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    first = deepcopy(setup["ops"][0])
    returning = deepcopy(first)
    returning["op"] = 30
    setup["ops"] = [first, {"op": 20, "do": "face", "tool": "em", "holder": "holder"}, returning]
    assert inputs(data)["zero"]["selected"] == "unknown"
    touch = deepcopy(setup["zero"]["z"])
    touch["z_face"] = touch.pop("face")
    touch.update(before_ops=[30], after_op=20)
    setup["zero"]["tool_touches"] = [touch]
    zero = inputs(data)["zero"]
    assert zero["selected"] == 1
    assert zero["touches"][1]["position"] == 2
    assert zero["touches"][1]["method"] == "mounted_saw_side"


def test_unknown_intervening_spindle_pair_invalidates_setting(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    returning = deepcopy(setup["ops"][0])
    returning["op"] = 30
    setup["ops"].extend([{"op": 20, "do": "face", "tool": "unknown"}, returning])
    assert inputs(data)["zero"]["selected"] == "unknown"


@pytest.mark.parametrize("setter", ["endmill", "other_saw", "other_holder"])
@pytest.mark.parametrize("later_boundary", [False, True])
def test_another_pairs_z_touch_invalidates_mounted_zero_without_a_cut(
    tmp_path, setter, later_boundary
):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    if later_boundary:
        setup["ops"].insert(0, {"op": 5, "do": "inspect"})
    touch = deepcopy(setup["zero"]["z"])
    touch.update(before_ops=[10])
    if setter == "endmill":
        touch.update(method="paper", tool="em", holder="holder", z_face="top")
        touch.pop("mounted_saw")
    elif setter == "other_saw":
        data.inventory["tools"]["other_saw"] = deepcopy(data.inventory["tools"]["saw"])
        touch["tool"] = "other_saw"
    else:
        data.inventory["holders"]["other_arbor"] = deepcopy(data.inventory["holders"]["arbor"])
        touch["holder"] = "other_arbor"
    setup["zero"]["tool_touches"] = [touch]
    zero = inputs(data)["zero"]
    assert zero["selected"] == "unknown"
    assert zero["errors"] == []
    assert zero["reasons"] == [
        "no current mounted_saw_side touch matches the installed tool-holder pair"
    ]


@pytest.mark.parametrize("fresh_last", [False, True])
def test_same_boundary_touch_order_can_restore_or_replace_a_mounted_setting(tmp_path, fresh_last):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    fresh = {**deepcopy(setup["zero"]["z"]), "before_ops": [10]}
    ordinary = {
        "method": "paper",
        "tool": "em",
        "holder": "holder",
        "z_face": "top",
        "edge_mm": 11,
        "paper_mm": 0.05,
        "before_ops": [10],
    }
    setup["zero"]["tool_touches"] = [ordinary, fresh] if fresh_last else [fresh, ordinary]
    recipe = inputs(data)
    assert recipe["zero"]["selected"] == (1 if fresh_last else "unknown")
    assert recipe["status"] == ("pass" if fresh_last else "unknown")
    if fresh_last:
        assert recipe["zero"]["touches"][1]["position"] == 0
        assert recipe["zero"]["reasons"] == []


def test_metadata_keeps_authored_touch_ordinal_and_same_pair_setting(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    saw = setup["ops"][0]
    setup["ops"] = [
        {"op": 1, "do": "inspect"},
        {"op": 2, "do": "cut_off", "tool": "saw", "holder": "arbor"},
        {"op": 3, "do": "scribe"},
        saw,
    ]
    assert inputs(data)["zero"]["selected"] == 0
    setup["zero"]["tool_touches"] = [{**deepcopy(setup["zero"]["z"]), "before_ops": [3, 10]}]
    zero = inputs(data)["zero"]
    assert zero["selected"] == 1
    assert zero["touches"][1]["position"] == 2


def test_unresolved_touch_boundary_cannot_preserve_an_earlier_mounted_zero(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup["zero"]["tool_touches"] = [
        {**deepcopy(setup["zero"]["z"]), "before_ops": [10, "missing"]}
    ]
    zero = inputs(data)["zero"]
    assert zero["touches"][1]["position"] == "unknown"
    assert zero["selected"] == "unknown"


def test_legacy_touch_lengths_convert_but_explicit_setup_mm_coordinates_do_not(tmp_path):
    data = saw_bundle(tmp_path)
    data.features["units"] = "in"
    setup = data.plan["setups"][0]
    setup["ops"][0]["cut_plane"]["value"] /= 25.4
    source = setup["zero"]["z"]
    for field in ("edge_mm", "paper_mm", "check_jog_mm"):
        source[field] /= 25.4
    touch = inputs(data)["zero"]["touches"][0]
    assert touch["edge_mm"] == pytest.approx(11)
    assert touch["paper_mm"] == pytest.approx(0.05)
    assert touch["check_jog_mm"] == pytest.approx(5)
    assert touch["mounted_saw"]["point_mm"] == [5, 5, 11]


@pytest.mark.parametrize(
    "model,value",
    [
        (SawTrajectory, {"start_mm": [0, 0, 0], "moves": []}),
        (SawTrajectory, {"start_mm": [0, 0], "moves": [{"to_mm": [1, 0, 0], "mode": "cut"}]}),
        (SawTrajectory, {"start_mm": [0, 0, 0], "moves": [{"to_mm": [1, 0, 0], "mode": "rapid"}]}),
        (MountedSawTouch, {"blade_side": "bottom"}),
        (MountedSawTouch, {"spindle_state": "off"}),
        (MountedSawTouch, {"axis_xy_mm": [0, 0, 0]}),
        (MountedSawTouch, {"point_mm": [False, 0, 0]}),
    ],
)
def test_mounted_saw_structures_are_strict(model, value):
    with pytest.raises(ValidationError):
        model.model_validate(value)


@pytest.mark.parametrize("model", [AxisZero, ToolTouch])
@pytest.mark.parametrize("coordinates", [[], [0], [0, 0, 0], [0, 0, 0, 0]])
def test_touch_pose_rejects_any_coordinate_count_other_than_two(model, coordinates):
    with pytest.raises(ValidationError):
        model.model_validate({"at_mm": coordinates})


@pytest.mark.parametrize("model", [AxisZero, ToolTouch])
def test_touch_pose_preserves_two_coordinates_unknown_and_omission(model):
    assert model.model_validate({"at_mm": [1.25, -2]}).at_mm == [1.25, -2]
    assert model.model_validate({"at_mm": "unknown"}).at_mm == "unknown"
    assert "at_mm" not in model.model_validate({}).model_dump(exclude_unset=True)


def test_optional_saw_fields_preserve_authored_unknown_and_omission():
    for model in (AxisZero, ToolTouch):
        assert "mounted_saw" not in model.model_validate({}).model_dump(exclude_unset=True)
        assert (
            model.model_validate({"mounted_saw": "unknown"}).model_dump(exclude_unset=True)[
                "mounted_saw"
            ]
            == "unknown"
        )
    assert ToolTouch.model_validate({"holder": "holders.arbor"}).holder == "holders.arbor"
    assert Operation.model_validate({"saw_capture": "unknown"}).saw_capture == "unknown"


@pytest.mark.parametrize("stem", ["root_dia", "kerf_offset", "bore_dia_limits", "thickness"])
def test_inventory_rejects_duplicate_blade_units_even_when_one_value_is_unknown(stem):
    value = [12, 13] if stem.endswith("limits") else 1
    with pytest.raises(ValidationError, match="author one length twice"):
        Inventory.model_validate({"tools": {"saw": {stem + "_mm": value, stem + "_in": "unknown"}}})


@pytest.mark.parametrize(
    "stem", ["pilot_dia_limits", "blade_thickness_limits", "bore_clearance_max"]
)
def test_inventory_rejects_duplicate_nested_arbor_units(stem):
    value = [1, 2] if stem.endswith("limits") else {"value": 0.1, "cite": "spec"}
    with pytest.raises(ValidationError, match="author one length twice"):
        Inventory.model_validate(
            {
                "holders": {
                    "arbor": {"mounted_saw_arbor": {stem + "_mm": value, stem + "_in": "unknown"}}
                }
            }
        )


def test_arbor_component_ids_are_unique_and_evidence_never_inherits():
    with pytest.raises(ValidationError, match="unique"):
        Inventory.model_validate(
            {
                "holders": {
                    "arbor": {
                        "mounted_saw_arbor": {
                            "components": [
                                cylinder("same", 20, -4, -2),
                                cylinder("same", 20, -2, 0),
                            ]
                        }
                    }
                }
            }
        )
    with pytest.raises(ValidationError):
        Inventory.model_validate(
            {"holders": {"arbor": {"mounted_saw_arbor": {"measured": MEASURED}}}}
        )
    with pytest.raises(ValidationError):
        Inventory.model_validate({"tools": {"saw": {"tooth_spacing": "variable"}}})


def test_saw_operative_inputs_reach_engine_identity_without_presentation_fields(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = kernel.op_inputs(data, setup, setup["ops"][0])
    recipe = kernel._engine_op(op)
    assert "mounted_saw" in recipe
    assert "measurement_debts" not in recipe
    changed = deepcopy(op)
    changed["mounted_saw"]["trajectory"]["moves"][0]["to_mm"][0] += 1
    assert kernel._engine_op(changed) != recipe
    changed = deepcopy(op)
    changed["detail"] = "pro"
    assert kernel._engine_op(changed) == recipe
    assert "saw_engagement.py" in kernel.ENGINE_SOURCES


def test_missing_kerf_never_uses_body_thickness_as_its_substitute(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["tools"]["saw"].pop("kerf_mm")
    recipe = inputs(data)
    assert recipe["blade"]["thickness_mm"] == 3.05
    assert recipe["blade"]["kerf_mm"] == "unknown"
    assert "assembly.blade.kerf_mm" in recipe["reasons"]
    assert any(entry["id"] == "tools.saw.kerf" for entry in recipe["measurement_debts"])


def test_declared_complete_envelope_cannot_have_a_known_gap_before_spindle_nose(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["holders"]["arbor"]["mounted_saw_arbor"]["components"][-1]["z_max_mm"] = (
        measured(30)
    )
    recipe = inputs(data)
    assert recipe["status"] == "error"
    assert any("axial gap" in error for error in recipe["assembly_errors"])


def test_arbor_envelope_cannot_solidly_overlap_the_blade_body(tmp_path):
    data = saw_bundle(tmp_path)
    components = data.inventory["holders"]["arbor"]["mounted_saw_arbor"]["components"]
    components[0]["z_max_mm"] = measured(-20)
    recipe = inputs(data)
    assert recipe["status"] == "error"
    assert any("intersects the blade flat body" in error for error in recipe["assembly_errors"])


def test_known_wrong_rotation_is_an_error_even_with_assumed_rotation_evidence(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["holders"]["arbor"]["mounted_saw_arbor"]["cutting_rotation"] = measured(
        "ccw", "assumed"
    )
    recipe = inputs(data)
    assert recipe["arbor"]["cutting_rotation"] == "unknown"
    assert recipe["status"] == "error"
    assert any("cutting rotation" in error for error in recipe["assembly_errors"])
    assert any(entry["id"].endswith("cutting_rotation") for entry in recipe["measurement_debts"])


def test_unknown_capture_solid_retains_existing_fact_local_debt(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["fixtures"]["capture"]["solids"][0]["measured"]["status"] = "assumed"
    recipe = inputs(data)
    assert recipe["capture"]["components"][0]["solids"] == []
    assert recipe["capture"]["reasons"]
    assert recipe["status"] == "unknown"
    assert any(
        entry["id"] == "fixtures.capture.solids.pad" for entry in recipe["measurement_debts"]
    )


def test_unsupported_scribed_disk_still_transports_its_operative_finite_inputs(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    source = setup["ops"][0]
    source.pop("cut_plane")
    source.update(follows="S1:1", allowance_mm=1)
    op = kernel.op_inputs(data, setup, source)
    assert op["mounted_saw"]["trajectory"]["reasons"]
    assert kernel._engine_op(op)["mounted_saw"]["capture"]["state"] == "clamped"


def test_legacy_kerf_diagnostic_does_not_replace_nested_measured_finite_input(tmp_path):
    data = saw_bundle(tmp_path)
    data.inventory["tools"]["saw"]["kerf_mm"] = 1.0
    setup = data.plan["setups"][0]
    recipe = kernel.op_inputs(data, setup, setup["ops"][0])
    assert recipe["kerf_mm"] == 1.0
    assert recipe["mounted_saw"]["blade"]["kerf_mm"] == "unknown"
    assert any(entry["id"] == "tools.saw.kerf" for entry in recipe["measurement_debts"])


@pytest.mark.parametrize("owner", ["holder", "machine"])
@pytest.mark.parametrize("verification", [True, "unknown"])
def test_unverified_interface_cannot_prove_a_known_taper_mismatch(tmp_path, owner, verification):
    data = saw_bundle(tmp_path)
    holder = data.inventory["holders"]["arbor"]
    holder["taper"] = "MT3"
    item = holder if owner == "holder" else data.inventory["machines"]["mill"]
    item["verify"] = verification
    recipe = inputs(data)
    assert recipe["status"] == "unknown"
    assert recipe["assembly_errors"] == []
    assert any("interface requires verification" in reason for reason in recipe["assembly_reasons"])
    assert recipe["blade"]["dia_mm"] == 100


@pytest.mark.parametrize("diameter", [0, -50.8])
def test_invalid_nominal_diameter_is_diagnostic_only_not_native_geometry(tmp_path, diameter):
    data = saw_bundle(tmp_path)
    data.inventory["tools"]["saw"]["dia_mm"] = diameter
    recipe = inputs(data)
    assert recipe["status"] == "error"
    assert recipe["diagnostics"]["blade_diameter_mm"] == diameter
    assert recipe["blade"]["dia_mm"] == "unknown"
    assert any(entry["id"] == "tools.saw.dia" for entry in recipe["measurement_debts"])
