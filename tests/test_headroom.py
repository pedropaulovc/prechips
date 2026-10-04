"""Physical mill stack arithmetic, independent of authored reference outputs."""

import re
from pathlib import Path
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
    return SimpleNamespace(
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
        "[machines.mill]\nkind = 'mill'\nverify = false\n"
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
        first_row = re.search(r"<tbody><tr>(.*?)</tr>", table, re.DOTALL).group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", first_row)
        assert [float(cell) for cell in cells[1:3]] == pytest.approx(
            [28.0 + allowance, 8.0]
            if method == "arc_table"
            else [-8.0 - allowance, -5.0 - allowance]
        )


@pytest.mark.parametrize(("setup_id", "op_id"), [("S1", 40), ("S2", 40), ("S3", 30)])
def test_exported_rocker_top_edge_keeps_cutter_table_with_all_linked_features(setup_id, op_id):
    data = load_bundle(Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml")
    finding = next(row for row in coordinates.evaluate(data) if row.subject == setup_id)
    arc = next(
        (
            arc
            for arc in finding.numbers["arc_table"]
            if arc["feature"] == "top_edge" and arc["op"] == op_id
        ),
        None,
    )
    assert arc is not None
    top = next(
        profile
        for profile in finding.numbers["profiles"]
        if profile["feature"] == "top_edge" and profile["op"] == op_id
    )
    assert arc["cutter_centre_radius_mm"] == pytest.approx(800.0 - top["offset_mm"])
    assert arc["rows"][0]["model_xy"][0] == pytest.approx(-arc["rows"][-1]["model_xy"][0])
    assert arc["rows"][0]["model_xy"][1] == pytest.approx(arc["rows"][-1]["model_xy"][1])


@pytest.mark.parametrize("corruption", ["missing", "inconsistent"])
@pytest.mark.parametrize("linked_feature", ["profile_outer", "tip_land_pos_x", "tip_land_neg_x"])
def test_top_edge_does_not_ignore_missing_or_conflicting_linked_geometry(
    linked_feature, corruption
):
    data = load_bundle(Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml")
    linked = data.features["features"][linked_feature]
    if corruption == "missing":
        linked["radial_tip_end"] = "unknown"
    else:
        linked["radial_tip_end"][1] += 1.0
    finding = coordinates.evaluate(data)[0]
    assert not any(arc["feature"] == "top_edge" for arc in finding.numbers["arc_table"])
    top = next(
        profile
        for profile in finding.numbers["profiles"]
        if profile["feature"] == "top_edge" and profile["op"] == 40
    )
    assert top["cutter_centre"] == "unknown"
