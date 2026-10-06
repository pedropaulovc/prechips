"""Physical mill stack arithmetic, independent of authored reference outputs."""

import math
import re
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_cli import traveler

from prechips.inputs import load_bundle
from prechips.rules import coordinates
from prechips.rules.headroom import evaluate

MEASURED = {"by": "test", "date": "2026-10-03", "instrument": "steel rule"}


def measured(value):
    return {"value": value, "measured": dict(MEASURED)}


def bundle():
    data = SimpleNamespace(
        plan={
            "stock": {"length_mm": 100, "section_mm": [30, 16]},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "stock_state": {"top_z": 4, "bottom_z": -12},
                    "hold": {
                        "fixture": "vise",
                        "parallels": "parallel",
                        "supports": "blocks",
                        "support_orientation": "1 in height",
                    },
                    "ops": [
                        {
                            "op": 10,
                            "do": "face",
                            "feature": "top",
                            "tool": "cutter",
                            "holder": "holder",
                            "to_z": 0,
                        }
                    ],
                }
            ],
        },
        inventory={
            "machines": {
                "mill": {
                    "kind": "mill",
                    "envelope": {
                        "spindle_to_table_max_mm": measured(200),
                        "travel_mm": {"x": measured(400), "y": measured(200)},
                    },
                }
            },
            "fixtures": {
                "vise": {
                    "kind": "vise",
                    "bed_height_mm": 20,
                    "jaw_height_mm": 40,
                    "length_mm": 150,
                    "width_mm": 80,
                },
                "parallel": {"kind": "parallels", "height_mm": 10},
                "blocks": {"kind": "blocks_123", "size_in": [1, 2, 3]},
            },
            "tools": {"cutter": {"kind": "endmill", "oal_mm": 80}},
            "holders": {"holder": {"kind": "collet", "gauge_len_mm": 30, "grip_mm": 25}},
        },
        features={"frames": {"A": {"x": [1, 0, 0], "y": [0, 1, 0]}}, "features": {}},
        policy={},
    )
    data.feature_definitions = data.features["features"]
    return data


def test_stack_uses_physical_height_not_coordinate_or_jaw_height():
    finding = evaluate(bundle())[0]
    assert finding.status == "pass"
    assert finding.numbers["stock_height_mm"] == 16
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["stacks"][0]["tool_projection_mm"] == 55
    assert finding.numbers["stacks"][0]["margin_mm"] == pytest.approx(18.6)
    assert finding.numbers["stock_top_above_jaws_mm"] == pytest.approx(11.4)
    assert finding.numbers["cut_tip_above_jaws_mm"]["10"] == pytest.approx(7.4)


def test_tip_above_jaw_top_is_reported_only_for_a_sweep_within_the_crash_zone_of_a_jaw():
    # Jaws run along X and grip the kernel's setup-entry stock faces at Y -15 / +15.
    data = bundle()
    setup = data.plan["setups"][0]
    setup["hold"]["jaws_along"] = "x"
    data.inventory["tools"]["cutter"]["dia_mm"] = 6
    data.kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": [-50, -15, -12, 50, 15, 4]}}}
    op = setup["ops"][0]
    # A Ø6 cutter over Y -8..8 keeps its edge 4 mm inside both jaw faces: no bite point.
    op["stock_removal_bounds"] = {"x": [-50, 50], "y": [-8, 8], "z": [0, 4]}
    assert "10" not in evaluate(data)[0].numbers["cut_tip_above_jaws_mm"]
    # Over Y -8..10 its edge comes within 2 mm of the +Y jaw face: still boxed.
    op["stock_removal_bounds"]["y"] = [-8, 10]
    assert evaluate(data)[0].numbers["cut_tip_above_jaws_mm"]["10"] == pytest.approx(7.4)


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
    data.inventory["tools"]["long"] = {"kind": "endmill", "projection_mm": {"short": 70}}
    data.inventory["holders"]["short"] = {"kind": "collet", "gauge_len_mm": 10}
    data.plan["setups"][0]["ops"].append(
        {"op": 20, "do": "face", "tool": "long", "holder": "short"}
    )
    finding = evaluate(data)[0]
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["stacks"][1]["sum_mm"] == pytest.approx(176.4)


def test_projection_is_selected_per_tool_and_holder_pair_else_oal_minus_grip():
    data = bundle()
    cutter = data.inventory["tools"]["cutter"]
    cutter["projection_mm"] = {"other": 40}
    finding = evaluate(data)[0]
    assert finding.numbers["stacks"][0]["tool_projection_mm"] == 55
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    cutter["projection_mm"]["holder"] = 40
    finding = evaluate(data)[0]
    assert finding.numbers["stacks"][0]["tool_projection_mm"] == 40
    assert finding.numbers["sum_mm"] == pytest.approx(166.4)


@pytest.mark.parametrize("field", ["projection_mm", "projection_in"])
@pytest.mark.parametrize("limit", [200, 180])
def test_explicit_unknown_projection_never_falls_back_to_oal_minus_grip(field, limit):
    data = bundle()
    data.inventory["tools"]["cutter"][field] = {"holder": "unknown"}
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(limit)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["stacks"][0]["tool_projection_mm"] == "unknown"
    assert finding.numbers["stacks"][0]["sum_mm"] == "unknown"
    assert finding.numbers["stacks"][0]["margin_mm"] == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"


def test_measured_stack_over_limit_is_error_and_equality_passes():
    data = bundle()
    envelope = data.inventory["machines"]["mill"]["envelope"]
    envelope["spindle_to_table_max_mm"] = measured(181.4)
    assert evaluate(data)[0].status == "pass"
    envelope["spindle_to_table_max_mm"] = measured(180)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["stacks"][0]["margin_mm"] == pytest.approx(-1.4)


@pytest.mark.parametrize(
    "limit,nominal,margin",
    [
        (180, 180, -1.4),
        ({"value": 180, "verify": False}, 180, -1.4),
        ({"value": 200, "verify": True}, 200, 18.6),
    ],
)
def test_uncertified_machine_limit_keeps_nominal_numbers_but_neither_passes_nor_errors(
    limit, nominal, margin
):
    data = bundle()
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = limit
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["spindle_to_table_max_mm"] == nominal
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)
    assert finding.numbers["stacks"][0]["margin_mm"] == pytest.approx(margin)
    assert [entry["id"] for entry in finding.numbers["measurements"]] == [
        "machines.mill.envelope.spindle_to_table_max"
    ]


def test_measured_envelope_limits_govern_over_conflicting_legacy_machine_fields():
    data = bundle()
    machine = data.inventory["machines"]["mill"]
    machine["spindle_to_table_max_mm"] = 1000
    machine["travel_mm"] = {"x": 400, "y": 200}
    machine["envelope"]["spindle_to_table_max_mm"] = measured(180)
    machine["envelope"]["travel_mm"]["x"] = measured(140)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["spindle_to_table_max_mm"] == 180
    assert finding.numbers["stacks"][0]["margin_mm"] == pytest.approx(-1.4)
    assert finding.numbers["travel_checks"]["x"]["travel_mm"] == 140
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 150
    assert finding.numbers["measurements"] == []


def test_legacy_machine_fields_alone_cannot_certify_headroom():
    data = bundle()
    machine = data.inventory["machines"]["mill"]
    del machine["envelope"]
    machine["spindle_to_table_max_mm"] = 1000
    machine["travel_mm"] = {"x": 400, "y": 200}
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["spindle_to_table_max_mm"] == "unknown"
    assert finding.numbers["stacks"][0]["margin_mm"] == "unknown"
    assert finding.numbers["travel_checks"]["x"]["travel_mm"] == "unknown"
    assert [entry["id"] for entry in finding.numbers["measurements"]] == [
        "machines.mill.envelope.spindle_to_table_max",
        "machines.mill.envelope.travel.x",
        "machines.mill.envelope.travel.y",
    ]


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


LEVEL_HEAD_POSE = {"origin_mm": [0, 0, 0], "x": [0, 1, 0], "z": [1, 0, 0]}


def head_bundle():
    """S1 held in a dividing head whose axis origin lies on setup z = 0."""
    data = bundle()
    data.plan["setups"][0]["hold"] = {"fixture": "head", "pose": deepcopy(LEVEL_HEAD_POSE)}
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(250)
    data.inventory["machines"]["head"] = {
        "kind": "dividing_head",
        "centre_height_mm": 100,
        # Neither is the work's height on a head: bed 20 + supported stock 16 would
        # give 36, jaw 40 would give 40, against the true 104 mm work top.
        "bed_height_mm": 20,
        "jaw_height_mm": 40,
        "length_mm": 150,
        "width_mm": 80,
    }
    return data


def test_dividing_head_work_top_is_centre_height_plus_top_above_axis():
    finding = evaluate(head_bundle())[0]
    assert finding.status == "pass"
    # 100 centre height + (top 4 - axis 0) + projection 55 + gauge 30 + insertion 25.
    assert finding.numbers["work_top_above_table_mm"] == 104
    assert finding.numbers["sum_mm"] == pytest.approx(214)
    assert finding.numbers["bed_height_mm"] == "not_applicable"
    assert finding.numbers["jaw_obstruction"]["jaw_top_z"] == "not_applicable"
    assert finding.numbers["cut_tip_above_jaws_mm"] == {}


def test_dividing_head_exact_clearance_passes_and_excess_errors():
    data = head_bundle()
    envelope = data.inventory["machines"]["mill"]["envelope"]
    envelope["spindle_to_table_max_mm"] = measured(214)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["stacks"][0]["margin_mm"] == 0
    envelope["spindle_to_table_max_mm"] = measured(213)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["stacks"][0]["margin_mm"] == -1


def test_dividing_head_translated_pose_and_stock_keep_the_same_stack():
    data = head_bundle()
    setup = data.plan["setups"][0]
    setup["hold"]["pose"]["origin_mm"] = [7, -3, 50]
    setup["stock_state"].update(top_z=54, bottom_z=38)
    setup["ops"][0]["to_z"] = 50
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["head_axis_z"] == 50
    assert finding.numbers["sum_mm"] == pytest.approx(214)


def test_dividing_head_needs_no_supported_stock_bottom():
    data = head_bundle()
    del data.plan["setups"][0]["stock_state"]["bottom_z"]
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["sum_mm"] == pytest.approx(214)


def test_inclined_head_keeps_centre_plus_pose_offset_and_blocks_lift_it():
    data = head_bundle()
    tilt = math.radians(3.33)
    hold = data.plan["setups"][0]["hold"]
    cos, sin = math.cos(tilt), math.sin(tilt)
    hold["pose"].update(z=[cos, 0, sin], x=[-sin, 0, cos])
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["work_top_above_table_mm"] == 104
    assert finding.numbers["sum_mm"] == pytest.approx(214)
    hold.update(supports="blocks", support_orientation="1 in height")
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["work_top_above_table_mm"] == pytest.approx(129.4)
    assert finding.numbers["sum_mm"] == pytest.approx(239.4)


@pytest.mark.parametrize(
    "gap",
    ["no pose", "pose origin unknown", "no centre height", "head verify", "support verify"],
)
@pytest.mark.parametrize("limit", [1000, 100])
def test_dividing_head_unresolved_work_top_neither_passes_nor_errors(gap, limit):
    data = head_bundle()
    hold = data.plan["setups"][0]["hold"]
    head = data.inventory["machines"]["head"]
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(limit)
    if gap == "no pose":
        del hold["pose"]
    elif gap == "pose origin unknown":
        hold["pose"]["origin_mm"] = "unknown"
    elif gap == "no centre height":
        del head["centre_height_mm"]
    elif gap == "head verify":
        head["verify"] = True
    else:
        hold.update(supports="blocks", support_orientation="1 in height")
        data.inventory["fixtures"]["blocks"]["verify"] = True
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    if gap not in {"head verify", "support verify"}:
        assert finding.numbers["work_top_above_table_mm"] == "unknown"
        assert finding.numbers["sum_mm"] == "unknown"


def test_machine_hosted_dividing_head_is_the_fixture_in_stack_and_travel():
    data = head_bundle()
    data.inventory["machines"]["head"]["length_mm"] = 450
    finding = evaluate(data)[0]
    assert finding.numbers["fixture_verify"] is False
    assert finding.numbers["sum_mm"] == pytest.approx(214)
    assert finding.numbers["travel_checks"]["x"]["fixture_mm"] == 450
    assert finding.status == "error"


def test_part_and_fixture_envelope_must_fit_travel():
    data = bundle()
    data.inventory["machines"]["mill"]["envelope"]["travel_mm"]["x"] = measured(140)
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
    envelope = data.inventory["machines"]["mill"]["envelope"]
    del envelope["spindle_to_table_max_mm"]
    envelope["spindle_to_table_max_in"] = measured(8)
    data.inventory["holders"]["holder"] = {
        "kind": "collet",
        "gauge_len_in": 1,
        "grip_mm": 25,
    }
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["spindle_to_table_max_mm"] == pytest.approx(203.2)
    assert finding.numbers["sum_mm"] == pytest.approx(176.8)


@pytest.mark.parametrize(
    "section",
    ["stock", "hold", "stock_state", "machines", "fixtures", "envelope", "travel_mm"],
)
def test_structural_unknown_cannot_certify_physical_envelope(section):
    data = bundle()
    if section == "stock":
        data.plan["stock"] = "unknown"
    elif section in {"hold", "stock_state"}:
        data.plan["setups"][0][section] = "unknown"
    elif section == "envelope":
        data.inventory["machines"]["mill"]["envelope"] = "unknown"
    elif section == "travel_mm":
        data.inventory["machines"]["mill"]["envelope"]["travel_mm"] = "unknown"
    else:
        data.inventory[section] = "unknown"
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    if section in {"hold", "stock_state", "fixtures"}:
        assert finding.numbers["sum_mm"] == "unknown"
    if section == "stock":
        assert finding.numbers["travel_checks"]["x"]["required_mm"] == "unknown"


def coordinate_bundle(tmp_path, feature, operations):
    """A scratch bundle with coordinates as its sole required rule."""
    root = tmp_path / "coordinate-bundle"
    root.mkdir()
    plan = root / "plan.toml"
    plan.write_text(
        'part = "coordinate-control"\nfeatures = "features.toml"\n'
        "[paths]\ninventory = 'inventory.toml'\npolicy = 'policy.toml'\n"
        "cutting_data = 'cutting.toml'\n"
        "[[setups]]\nid = 'S1'\nmachine = 'mill'\nframe = 'A'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        "[setups.hold]\nfixture = 'unknown'\nstop = 'unknown'\ngrip_mm = 'unknown'\n"
        "clamp = 'unknown'\nfixed_jaw = 'unknown'\n"
        "[setups.stock_state]\ntop_z = 0.0\nbottom_z = -10.0\n"
        "local_thickness = { target = 10.0 }\n"
        + operations.replace("feature = 'target'\n", "feature = 'target'\nholder = 'unknown'\n"),
        encoding="utf-8",
    )
    (root / "features.toml").write_text(
        'part = "coordinate-control"\nunits = "mm"\nprecision = 2\n'
        "[frames.A]\norigin = [5.0, 2.0, 1.0]\n"
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n"
        'binding = "measured"\n'
        "[frames.model]\norigin = [0.0, 0.0, 0.0]\n"
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n"
        "[features.target]\nframe = 'model'\nrequirements = []\n" + feature,
        encoding="utf-8",
    )
    (root / "inventory.toml").write_text(
        "[machines.mill]\nkind = 'mill'\nverify = false\n[machines.mill.spindle]\nrotation = 'cw'\n"
        "[tools.cutter]\nkind = 'endmill'\ndia_mm = 6.0\nverify = false\n"
        "[tools.spot]\nkind = 'center_drill'\ndia_mm = 6.0\npoint_angle = 90.0\n"
        "verify = false\n"
        "[tools.drill]\nkind = 'drill'\ndia_mm = 6.0\npoint_angle = 118.0\n"
        "verify = false\n",
        encoding="utf-8",
    )
    (root / "policy.toml").write_text('[required]\ncoordinates = "*"\n', encoding="utf-8")
    (root / "cutting.toml").write_text("revision = 1\n", encoding="utf-8")
    return plan


def coordinate_finding(report):
    return next(
        row for row in report["findings"] if row["rule"] == "coordinates" and row["subject"] == "S1"
    )


@pytest.mark.parametrize("kind,action", [("hole", "drill"), ("boss", "face"), ("plane", "center")])
@pytest.mark.parametrize(
    "location",
    ['at = "unknown"\n', "", "at = [20.0, 10.0]\n", 'at = [20.0, "unknown", 0.0]\n'],
    ids=["unknown", "absent", "2d", "partial"],
)
def test_worked_located_feature_needs_complete_reference_point(
    tmp_path, freecad_kernel, kind, action, location
):
    operations = (
        "[[setups.ops]]\nop = 10\ndo = 'spot'\nfeature = 'target'\ntool = 'spot'\ndepth_mm = 0.5\n"
        if kind == "hole"
        else ""
    )
    operations += (
        f"[[setups.ops]]\nop = 20\ndo = '{action}'\nfeature = 'target'\n"
        f"tool = '{'drill' if action == 'drill' else 'cutter'}'\n"
        "exit_mm = 0.5\nto_z = -1.0\ndirection = 'conventional'\n"
    )
    plan = coordinate_bundle(
        tmp_path,
        f"kind = '{kind}'\nat = [20.0, 10.0, 0.0]\ndia = 6.0\nthru = true\n",
        operations,
    )
    result, known, _ = traveler(plan, tmp_path / "known")
    row = coordinate_finding(known)
    assert result.returncode == 0, result.stderr
    assert row["status"] == "pass"
    assert row["numbers"]["rows"][0]["model"] == [20.0, 10.0, 0.0]
    assert row["numbers"]["rows"][0]["setup"] == [15.0, 8.0, -1.0]
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8").replace("at = [20.0, 10.0, 0.0]\n", location),
        encoding="utf-8",
    )
    result, incomplete, html = traveler(plan, tmp_path / "incomplete")
    row = coordinate_finding(incomplete)
    assert row["status"] == "unknown"
    assert result.returncode == 4, result.stderr
    assert incomplete["verification"] != "checked"
    assert "PLANNED" in html


@pytest.mark.parametrize("method", ["arc_table", "linear_table"])
@pytest.mark.parametrize(
    "action,allowance_field,allowances",
    [
        ("profile", "rough_allowance_mm = 0.3\n", [0.3, 0.0]),
        ("rough_profile", "rough_allowance_mm = 0.3\n", [0.3]),
        ("rough_profile", "stock_to_leave_mm = 0.3\n", [0.3]),
        ("finish_profile", "", [0.0]),
    ],
    ids=["combined", "rough", "rough-stock-to-leave", "finish"],
)
def test_contour_allowances_produce_actual_rough_and_finish_targets(
    tmp_path, freecad_kernel, method, action, allowance_field, allowances
):
    feature = (
        "kind = 'boss'\nat = [20.0, 10.0, 0.0]\ndia = 20.0\n"
        if method == "arc_table"
        else "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }\n"
    )
    plan = coordinate_bundle(
        tmp_path,
        feature,
        f"[[setups.ops]]\nop = 20\ndo = '{action}'\nfeature = 'target'\n"
        "tool = 'cutter'\nto_z = -1.0\ndirection = 'conventional'\n"
        + allowance_field
        + f"contour = {{ method = '{method}', step_deg = 90.0 }}\n",
    )
    result, report, html = traveler(plan, tmp_path / "out")
    finding = coordinate_finding(report)
    assert result.returncode == 0, result.stderr
    assert finding["status"] == "pass"
    numbers = finding["numbers"]
    assert [p["offset_mm"] for p in numbers["profiles"]] == pytest.approx(
        [3.0 + allowance for allowance in allowances]
    )
    for profile, allowance in zip(numbers["profiles"], allowances, strict=True):
        assert profile["tool_nominal_dia_mm"] == 6.0
        assert profile["cutter_radius_mm"] == 3.0
        assert profile["rough_allowance_mm"] == (allowance if allowance else "not_applicable")
        if method == "arc_table":
            arc = next(arc for arc in numbers["arc_table"] if arc["allowance_mm"] == allowance)
            assert arc["cutter_centre_radius_mm"] == pytest.approx(13.0 + allowance)
            assert arc["rows"][0]["model_xy"] == pytest.approx([33.0 + allowance, 10.0])
            assert arc["rows"][0]["setup_xy"] == pytest.approx([28.0 + allowance, 8.0])
        else:
            assert profile["cutter_centre"][0] == pytest.approx(
                [-8.0 - allowance, -5.0 - allowance]
            )
            assert profile["cutter_centre"][2] == pytest.approx(
                [18.0 + allowance, 11.0 + allowance]
            )
    if action != "profile":
        return
    displayed = {
        "rough" if "stage: rough" in description else "finish": table
        for description, table in re.findall(
            r"<p>([^<]*stage: (?:rough|finish)[^<]*)</p>(<table.*?</table>)", html, re.DOTALL
        )
    }
    for stage, allowance in (("rough", 0.3), ("finish", 0.0)):
        table = displayed[stage]
        headings = re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", table)
        first_row = re.search(r"<tbody><tr>(.*?)</tr>", table, re.DOTALL).group(1)
        cells = dict(zip(headings, re.findall(r"<td[^>]*>(.*?)</td>", first_row), strict=True))
        assert [float(cells["X"]), float(cells["Y"])] == pytest.approx(
            [28.0 + allowance, 8.0]
            if method == "arc_table"
            else [-8.0 - allowance, -5.0 - allowance]
        )


@pytest.mark.parametrize("corruption", ["missing", "inconsistent"])
@pytest.mark.parametrize("linked_feature", ["outer", "right_land", "left_land"])
def test_top_edge_does_not_ignore_missing_or_conflicting_linked_geometry(
    tmp_path, linked_feature, corruption
):
    plan = coordinate_bundle(
        tmp_path,
        """kind = "profile"
radius = 10.0
arc_centre = [0.0, 0.0, 0.0]
end = [6.0, -8.0, 0.0]
[features.outer]
kind = "profile"
top_edge_feature = "target"
radial_tip_end = [10.0, -8.0, 0.0]
[features.right_land]
kind = "profile"
top_edge_feature = "target"
radial_tip_end = [10.0, -8.0, 0.0]
[features.left_land]
kind = "profile"
top_edge_feature = "target"
radial_tip_end = [-10.0, -8.0, 0.0]
""",
        "[[setups.ops]]\nop = 20\ndo = 'finish_profile'\nfeature = 'target'\n"
        "tool = 'cutter'\nto_z = -1.0\ndirection = 'conventional'\n"
        "contour = { method = 'arc_table', step_deg = 5.0 }\n",
    )
    data = load_bundle(plan)
    known = coordinates.evaluate(data)[0]
    assert known.status == "pass"
    (arc,) = known.numbers["arc_table"]
    # The 6 mm cutter offsets the R10 arc to R7 and the horizontal lands to Y-5.
    assert arc["cutter_centre_radius_mm"] == pytest.approx(7.0)
    # Endpoints are the land intersections; which comes first is the cutting order.
    ends = sorted([arc["rows"][0], arc["rows"][-1]], key=lambda row: row["model_xy"][0])
    assert ends[0]["model_xy"] == pytest.approx([-(24.0**0.5), -5.0])
    assert ends[1]["model_xy"] == pytest.approx([24.0**0.5, -5.0])
    assert ends[0]["setup_xy"] == pytest.approx([-(24.0**0.5) - 5.0, -7.0])
    linked = data.features["features"][linked_feature]
    if corruption == "missing":
        linked["radial_tip_end"] = "unknown"
    else:
        linked["radial_tip_end"][1] += 1.0
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["arc_table"] == []
    (top,) = finding.numbers["profiles"]
    assert top["offset_mm"] == pytest.approx(3.0)
    assert top["cutter_centre"] == "unknown"
