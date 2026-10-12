"""Exact consumed machining facts become checklist debt without tainting other facts."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel
from prechips.measurements import length_debt, measurement_checklist, measurement_entry
from prechips.rules import (
    accessibility,
    headroom,
    level_entry,
    op_chain,
    saw_cut,
    sizing,
    speeds_feeds,
)
from prechips.rules.geometry_common import kernel_measurement_debts

REFUSALS = [
    pytest.param("assumed", "assumed", id="assumed"),
    pytest.param("illustrative", "illustrative", id="illustrative"),
    pytest.param("legacy", "assumed", id="status-less-record"),
    pytest.param("incomplete", "measured", id="incomplete-measured-record"),
    pytest.param("verify_true", "measured", id="verify-true"),
    pytest.param("verify_unknown", "measured", id="verify-unknown"),
    pytest.param("missing", "missing", id="missing-length"),
]


def fact(value, case="measured"):
    if case == "missing":
        return "unknown"
    measured = {
        "status": case if case in {"assumed", "illustrative"} else "measured",
        "by": "synthetic test operator",
        "date": "2026-10-03",
        "instrument": "test calipers",
    }
    if case == "legacy":
        del measured["status"]
    elif case == "incomplete":
        del measured["instrument"]
    record = {"value": value, "measured": measured}
    if case in {"verify_true", "verify_unknown"}:
        record["verify"] = True if case == "verify_true" else "unknown"
    return record


def bundle():
    features = {
        "units": "mm",
        "frames": {
            "A": {
                "origin": [0, 0, 0],
                "x": [1, 0, 0],
                "y": [0, 1, 0],
                "z": [0, 0, 1],
                "binding": "measured",
            }
        },
        "features": {"target": {"kind": "hole", "dia": [6.3, 6.4]}},
    }
    return SimpleNamespace(
        plan={
            "stock": {"material": "steel", "length_mm": 100, "section_mm": [30, 20]},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "stock_state": {"top_z": 20, "bottom_z": 0},
                    "hold": {"fixture": "vise"},
                    "ops": [
                        {
                            "op": 10,
                            "do": "drill",
                            "feature": "target",
                            "tool": "cutter",
                            "holder": "holder",
                            "to_z": 15,
                        }
                    ],
                }
            ],
        },
        inventory={
            "machines": {
                "mill": {
                    "kind": "mill",
                    "spindle": {"rpm_min": 50, "rpm_max": 3000},
                    "envelope": {
                        "spindle_to_table_max_mm": fact(200),
                        "travel_mm": {"x": fact(400), "y": fact(200)},
                    },
                }
            },
            "fixtures": {
                "vise": {
                    "kind": "vise",
                    "bed_height_mm": fact(20),
                    "jaw_height_mm": fact(10),
                    "length_mm": fact(150),
                    "width_mm": fact(80),
                }
            },
            "tools": {
                "cutter": {
                    "kind": "drill",
                    "dia_mm": fact(6.35),
                    "oal_mm": fact(80),
                    "material": "HSS",
                    "flutes": 2,
                    "chart": "synthetic cutting chart",
                    "sfm": 100,
                    "chip_load_mm_per_tooth": 0.05,
                    "center_cutting": True,
                }
            },
            "holders": {
                "holder": {"kind": "collet", "gauge_len_mm": fact(30), "grip_mm": fact(25)}
            },
        },
        features=features,
        feature_definitions=features["features"],
        cutting_data={
            "aliases": {"steel": "steel"},
            "plunge": [
                {
                    "material_class": "steel",
                    "tool_material": "HSS",
                    "diameter_range": [3, 8],
                    "feed_mm_rev": 0.05,
                    "cite": "synthetic plunge row",
                }
            ],
        },
        policy={},
        kernel={"status": "ok", "ops": {}, "setups": {}},
    )


@pytest.fixture(autouse=True)
def synthetic_geometry_only(monkeypatch):
    def refuse_native(*args, **kwargs):
        raise AssertionError("these host-only regressions must never discover or run FreeCAD")

    monkeypatch.setattr(kernel, "discover_kernel", refuse_native)
    monkeypatch.setattr(kernel, "run_geometry", lambda data: data.kernel)


def assert_debts(row, expected):
    assert row.status == "unknown"
    entries = row.numbers.get("measurements", [])
    assert [entry["id"] for entry in entries] == sorted(expected)
    assert len({entry["id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert entry["status"] == expected[entry["id"]]
        assert entry["instruction"].startswith("measure:")
        assert entry["units"] == "mm"
        assert f"inventory.{entry['id']}" in entry["cite"]
        assert entry["reason"]
        if entry["status"] in {"assumed", "illustrative"}:
            assert "by: synthetic test operator" in entry["reason"]
    assert [entry["id"] for entry in measurement_checklist([row])] == sorted(expected)


@pytest.mark.parametrize(("case", "status"), REFUSALS)
def test_sizing_names_only_the_finishing_diameter_and_restores_its_numbers(case, status):
    data = bundle()
    [baseline] = sizing.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["tool_dia_mm"] == 6.35
    assert (baseline.numbers["under_low_mm"], baseline.numbers["over_high_mm"]) == (0, 0)
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, case)
    data.inventory["tools"]["cutter"]["oal_mm"] = fact(80, "illustrative")
    [row] = sizing.evaluate(data)
    assert_debts(row, {"tools.cutter.dia": status})
    assert row.numbers["tool_dia_mm"] == "unknown"
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35)
    assert sizing.evaluate(data) == [baseline]


@pytest.mark.parametrize("fields", [("nose_radius",), ("reach",), ("nose_radius", "reach")])
def test_groove_sizing_names_the_consumed_nose_and_radial_reach(fields):
    data = bundle()
    data.plan["stock"]["dia_mm"] = 20
    data.feature_definitions["target"] = {
        "kind": "groove",
        "width": [1, 2],
        "dia": [10, 10.1],
        "corner_radius_max_design": 0.5,
    }
    tool = data.inventory["tools"]["cutter"]
    tool.update(nose_radius_mm=fact(0.4), reach_mm=fact(10), dia_mm=fact(6.35, "assumed"))
    [baseline] = sizing.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["required_radial_reach_mm"] == 5
    assert baseline.numbers["tool_nose_radius_mm"] == 0.4
    assert baseline.numbers["tool_reach_mm"] == 10
    for field in fields:
        tool[f"{field}_mm"]["measured"]["status"] = "illustrative"
    [row] = sizing.evaluate(data)
    assert_debts(row, {f"tools.cutter.{field}": "illustrative" for field in fields})
    for field in fields:
        tool[f"{field}_mm"]["measured"]["status"] = "measured"
    assert sizing.evaluate(data) == [baseline]


@pytest.mark.parametrize(("case", "status"), REFUSALS)
def test_speeds_name_the_rpm_diameter_without_tool_stack_or_kernel_taint(case, status):
    data = bundle()
    [baseline] = speeds_feeds.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["rpm"] == 1550
    assert baseline.numbers["feed_mm_min"] == pytest.approx(155)
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, case)
    data.inventory["tools"]["cutter"]["oal_mm"] = fact(80, "assumed")
    irrelevant = length_debt({"oal_mm": fact(60, "illustrative")}, "oal", "tools", "other")
    data.kernel["measurement_debts"] = {"ops": {"S1:10": [irrelevant]}, "setups": {}}
    [row] = speeds_feeds.evaluate(data)
    assert_debts(row, {"tools.cutter.dia": status})
    assert (row.numbers["rpm"], row.numbers["feed_mm_min"]) == ("unknown", "unknown")
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35)
    assert speeds_feeds.evaluate(data) == [baseline]


def test_turning_speed_and_noncutting_identity_do_not_consume_a_cutter_diameter():
    data = bundle()
    machine = data.inventory["machines"]["mill"]
    machine["kind"] = "lathe"
    op = data.plan["setups"][0]["ops"][0]
    op.update(do="face", feed_mm_rev=0.1)
    data.feature_definitions["target"].update(kind="boss", dia_nominal=20)
    [baseline] = speeds_feeds.evaluate(data)
    assert baseline.status == "pass"
    assert (baseline.numbers["rpm"], baseline.numbers["feed_mm_min"]) == (500, 50)
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, "assumed")
    assert speeds_feeds.evaluate(data) == [baseline]
    op["do"] = "inspect"
    [identity] = speeds_feeds.evaluate(data)
    assert identity.status == "not_applicable"
    assert identity.numbers == {"operation": "inspect"}


@pytest.mark.parametrize(("case", "status"), REFUSALS)
def test_tap_chain_names_only_the_selected_drill_diameter(case, status):
    data = bundle()
    data.feature_definitions["target"] = {
        "kind": "threaded_hole",
        "thread": {"tap_drill_mm": 6.35},
    }
    data.plan["setups"][0]["ops"] = [
        {"op": 5, "do": "spot", "feature": "target"},
        {"op": 10, "do": "drill", "feature": "target", "tool": "tools.cutter"},
        {"op": 20, "do": "tap", "feature": "target"},
    ]
    [baseline] = op_chain.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["selected_drill_mm"] == 6.35
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, case)
    data.inventory["tools"]["cutter"]["oal_mm"] = fact(80, "illustrative")
    [row] = op_chain.evaluate(data)
    assert_debts(row, {"tools.cutter.dia": status})
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35)
    assert op_chain.evaluate(data) == [baseline]


def test_untapped_hole_prerequisites_and_path_sizing_are_pure_identity_checks():
    data = bundle()
    data.plan["setups"][0]["ops"].insert(0, {"op": 5, "do": "spot", "feature": "target"})
    [baseline] = op_chain.evaluate(data)
    assert baseline.status == "pass"
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, "illustrative")
    assert op_chain.evaluate(data) == [baseline]
    data.feature_definitions["target"]["kind"] = "plane"
    [path_size] = sizing.evaluate(data)
    assert path_size.status == "not_applicable"
    assert "measurements" not in path_size.numbers


@pytest.mark.parametrize("case", ["assumed", "illustrative"])
@pytest.mark.parametrize(
    ("category", "identity", "field", "value"),
    [
        ("fixtures", "vise", "bed_height", 20),
        ("fixtures", "vise", "jaw_height", 10),
        ("fixtures", "vise", "length", 150),
        ("fixtures", "vise", "width", 80),
        ("tools", "cutter", "oal", 80),
        ("holders", "holder", "gauge_len", 30),
        ("holders", "holder", "grip", 25),
    ],
)
def test_headroom_names_each_consumed_stack_or_travel_fact(category, identity, field, value, case):
    data = bundle()
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["sum_mm"] == 150
    assert baseline.numbers["stacks"][0]["tool_projection_mm"] == 55
    assert baseline.numbers["stacks"][0]["margin_mm"] == 50
    assert baseline.numbers["travel_checks"]["x"]["required_mm"] == 150
    data.inventory[category][identity][f"{field}_mm"] = fact(value, case)
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, "illustrative")
    [row] = headroom.evaluate(data)
    assert_debts(row, {f"{category}.{identity}.{field}": case})
    data.inventory[category][identity][f"{field}_mm"] = fact(value)
    assert headroom.evaluate(data) == [baseline]


def test_headroom_names_selected_projection_not_the_unused_grip_and_keeps_m5_debt():
    data = bundle()
    tool = data.inventory["tools"]["cutter"]
    tool["projection_mm"] = {"holders.holder": fact(55)}
    data.inventory["holders"]["holder"]["grip_mm"] = fact(25, "illustrative")
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass" and baseline.numbers["sum_mm"] == 150
    tool["projection_mm"]["holders.holder"] = fact(55, "assumed")
    [row] = headroom.evaluate(data)
    assert_debts(row, {"tools.cutter.projection.holders.holder": "assumed"})
    envelope = data.inventory["machines"]["mill"]["envelope"]
    envelope["spindle_to_table_max_mm"] = fact(200, "illustrative")
    [row] = headroom.evaluate(data)
    entries = {entry["id"]: entry for entry in row.numbers["measurements"]}
    expected = measurement_entry(
        "machines", "mill", "envelope.spindle_to_table_max", status="illustrative"
    )
    assert entries[expected["id"]] == expected
    assert set(entries) == {expected["id"], "tools.cutter.projection.holders.holder"}


def test_dividing_head_uses_its_centre_height_not_its_bed_or_jaws():
    data = bundle()
    fixture = data.inventory["fixtures"]["vise"]
    fixture.update(
        kind="dividing_head",
        centre_height_mm=fact(30),
        bed_height_mm=fact(20, "assumed"),
        jaw_height_mm=fact(10, "illustrative"),
    )
    data.plan["setups"][0]["hold"]["pose"] = {"origin_mm": [0, 0, 0]}
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["work_top_above_table_mm"] == 50
    assert baseline.numbers["sum_mm"] == 160
    fixture["centre_height_mm"] = fact(30, "assumed")
    [row] = headroom.evaluate(data)
    assert_debts(row, {"fixtures.vise.centre_height": "assumed"})
    fixture["centre_height_mm"] = fact(30)
    assert headroom.evaluate(data) == [baseline]


@pytest.mark.parametrize("support_slot", ["parallels", "supports"])
def test_headroom_names_a_refused_selected_support_height(support_slot):
    data = bundle()
    data.plan["setups"][0]["hold"][support_slot] = "support"
    data.inventory["fixtures"]["support"] = {"kind": "parallels", "height_mm": fact(5)}
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass" and baseline.numbers["sum_mm"] == 155
    data.inventory["fixtures"]["support"]["height_mm"] = fact(5, "illustrative")
    [row] = headroom.evaluate(data)
    assert_debts(row, {"fixtures.support.height": "illustrative"})


def jaw_bundle(monkeypatch, *, inside=False):
    data = bundle()
    setup = data.plan["setups"][0]
    setup["hold"].update(jaws_along="x", jaw_center_along_mm=0)
    setup["ops"][0]["to_z"] = 0
    data.inventory["fixtures"]["vise"]["jaw_width_mm"] = fact(80)
    data.kernel["setups"]["S1"] = {"stock_bbox_mm": [-60, -15, 0, 60, 15, 20]}
    points = [[0, -5], [0, 5]] if inside else [[47, -25], [50, 25]]
    printed = {"line_table": [{"op": 10, "dro_xy": points}]}
    monkeypatch.setattr(headroom, "_setup_coordinates", lambda *args: printed)
    return data


@pytest.mark.parametrize(
    ("category", "identity", "field", "value"),
    [("tools", "cutter", "dia", 6.35), ("fixtures", "vise", "jaw_width", 80)],
)
def test_headroom_jaw_clearance_names_the_radius_or_jaw_end_fact(
    monkeypatch, category, identity, field, value
):
    data = jaw_bundle(monkeypatch)
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass" and baseline.numbers["cut_tip_above_jaws_mm"] == {}
    data.inventory[category][identity][f"{field}_mm"] = fact(value, "assumed")
    [row] = headroom.evaluate(data)
    assert_debts(row, {f"{category}.{identity}.{field}": "assumed"})
    assert row.numbers["cut_tip_above_jaws_mm"] == {"10": -10}
    data.inventory[category][identity][f"{field}_mm"] = fact(value)
    assert headroom.evaluate(data) == [baseline]


def test_headroom_jaw_width_is_not_consumed_when_the_cutter_is_inside_the_faces(monkeypatch):
    data = jaw_bundle(monkeypatch, inside=True)
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass"
    data.inventory["fixtures"]["vise"]["jaw_width_mm"] = fact(80, "illustrative")
    assert headroom.evaluate(data) == [baseline]


@pytest.mark.parametrize("field,value", [("body_dia", 120), ("body_length", 50)])
def test_lathe_headroom_names_only_its_consumed_chuck_body_dimensions(field, value):
    data = bundle()
    machine = data.inventory["machines"]["mill"]
    machine.update(
        kind="lathe",
        envelope={
            "swing_over_bed_mm": fact(300),
            "swing_over_cross_slide_mm": fact(200),
            "between_centres_mm": fact(500),
        },
    )
    data.inventory["fixtures"]["vise"] = {
        "kind": "chuck",
        "body_dia_mm": fact(120),
        "body_length_mm": fact(50),
    }
    setup = data.plan["setups"][0]
    setup["stock_state"].update(od_mm=20, north_end_z=50, south_end_z=0)
    setup["hold"]["stickout_mm"] = 40
    [baseline] = headroom.evaluate(data)
    assert baseline.status == "pass" and baseline.numbers["required_length_mm"] == 90
    data.inventory["fixtures"]["vise"][f"{field}_mm"] = fact(value, "illustrative")
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, "assumed")
    data.inventory["tools"]["cutter"]["oal_mm"] = fact(80, "assumed")
    [row] = headroom.evaluate(data)
    assert_debts(row, {f"fixtures.vise.{field}": "illustrative"})
    data.inventory["fixtures"]["vise"][f"{field}_mm"] = fact(value)
    assert headroom.evaluate(data) == [baseline]


def saw_bundle():
    data = bundle()
    data.inventory["machines"]["mill"]["kind"] = "bandsaw"
    data.inventory["tools"]["cutter"] = {"kind": "bandsaw", "kerf_mm": fact(1.5)}
    data.plan["setups"][0]["ops"][0].update(
        do="saw_cut", cut_plane={"axis": "y", "value": 87.75, "keep": "below"}
    )
    data.kernel["ops"]["S1:10"] = {
        "kerf_mm": 1.5,
        "retained_boundary_mm": 87,
        "kerf_volume_mm3": 15,
        "offcut_volume_mm3": 25,
        "removed_volume_mm3": 40,
        "stock_volume_before_mm3": 140,
        "stock_volume_after_mm3": 100,
    }
    return data


@pytest.mark.parametrize(("case", "status"), REFUSALS)
def test_saw_names_actual_kerf_even_with_complete_synthetic_native_volumes(case, status):
    data = saw_bundle()
    [baseline] = saw_cut.evaluate(data)
    assert baseline.status == "pass"
    assert baseline.numbers["retained_boundary_mm"] == 87
    assert baseline.numbers["removed_volume_mm3"] == 40
    data.inventory["tools"]["cutter"]["kerf_mm"] = fact(1.5, case)
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, "illustrative")
    [row] = saw_cut.evaluate(data)
    assert_debts(row, {"tools.cutter.kerf": status})
    assert "tools.cutter.kerf" in row.sentence
    data.inventory["tools"]["cutter"]["kerf_mm"] = fact(1.5)
    assert saw_cut.evaluate(data) == [baseline]


def test_unavailable_saw_names_kerf_and_relevant_stock_ancestry_not_other_contexts(monkeypatch):
    data = saw_bundle()
    data.inventory["tools"]["cutter"]["kerf_mm"] = fact(1.5, "illustrative")
    kerf = length_debt(data.inventory["tools"]["cutter"], "kerf", "tools", "cutter")
    prior = length_debt({"dia_mm": fact(6, "assumed")}, "dia", "tools", "prior")
    unused = length_debt({"oal_mm": fact(60, "assumed")}, "oal", "tools", "unused")
    attachment = {
        "setups": {"S1": [unused], "S9": [unused]},
        "ops": {"S0:10": [prior], "S1:10": [kerf], "S9:10": [unused]},
    }
    job = {
        "measurement_debts": attachment,
        "setups": [
            {"id": "S0", "stock_in": "stock", "ops": [{"subject": "S0:10"}]},
            {"id": "S1", "stock_in": "S0", "ops": [{"subject": "S1:10"}]},
            {"id": "S9", "stock_in": "stock", "ops": [{"subject": "S9:10"}]},
        ],
    }
    monkeypatch.setattr(kernel, "build_job", lambda _: job)
    data.kernel = {
        "status": "unknown",
        "kernel_unavailable": True,
        "reason": "synthetic unavailable kernel",
        "measurement_debts": attachment,
    }
    [row] = saw_cut.evaluate(data)
    assert row.numbers["kernel_unavailable"] is True
    assert_debts(row, {"tools.cutter.kerf": "illustrative", "tools.prior.dia": "assumed"})
    assert "tools.cutter.kerf" in row.sentence
    assert "tools.unused.oal" not in row.sentence


def paths(data, *, lowered=False, outside=False):
    data.kernel["setups"]["S1"] = {"stock_bbox_mm": [-10, -10, -10, 10, 10, 0]}
    point = [-20, 0] if outside else [0, 0]
    numbers = {
        "operations": [
            {"op": 10, "z_levels": {"levels": [0] if lowered else [-1, -2], "dro_start_z": 0}}
        ],
        "line_table": [{"op": 10, "dro_xy": [point, point]}],
    }
    op = data.plan["setups"][0]["ops"][0]
    states = [(op, {"top_z": 0}, {})]
    return level_entry.level_paths(
        data,
        data.plan["setups"][0],
        numbers,
        states,
        (0.001, 3),
        "mm",
        lambda value, grid: value,
        lambda value, *, done: value,
    )


@pytest.mark.parametrize(("case", "status"), REFUSALS)
@pytest.mark.parametrize("outside", [False, True], ids=["plunge-row-diameter", "air-entry-radius"])
def test_level_path_records_carry_refused_diameter_through_string_plunge_debt(
    case, status, outside
):
    data = bundle()
    baseline = paths(data, outside=outside)
    [record], debts = baseline
    assert debts == []
    assert record["levels"] == [-1, -2]
    assert record["entries"][0]["air"] is outside
    if not outside:
        assert record["plunge_mm_rev"] == 0.05
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, case)
    data.inventory["tools"]["cutter"]["oal_mm"] = fact(80, "illustrative")
    [record], debts = paths(data, outside=outside)
    assert record["plunge_mm_rev"] == "unknown"
    assert [(entry["id"], entry["status"]) for entry in record["measurements"]] == [
        ("tools.cutter.dia", status)
    ]
    assert any("tools.cutter.dia" in debt and status in debt for debt in debts)
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35)
    assert paths(data, outside=outside) == baseline


def test_lowering_at_the_stock_top_does_not_acquire_unused_diameter_debt():
    data = bundle()
    baseline = paths(data, lowered=True)
    [record], debts = baseline
    assert record["lowered"] == "top" and debts == []
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(6.35, "illustrative")
    assert paths(data, lowered=True) == baseline


def test_plunge_lookup_collects_only_facts_it_reaches_and_preserves_its_tuple_api():
    data = bundle()
    op = data.plan["setups"][0]["ops"][0]
    measurements = []
    assert speeds_feeds.plunge_row(data, op, measurements=measurements) == (
        0.05,
        "synthetic plunge row",
        None,
    )
    assert measurements == []
    tool = data.inventory["tools"]["cutter"]
    tool["dia_mm"] = fact(6.35, "assumed")
    feed, cite, why = speeds_feeds.plunge_row(data, op, measurements=measurements)
    assert (feed, cite) == ("unknown", "unknown")
    assert [entry["id"] for entry in measurements] == ["tools.cutter.dia"]
    assert "tools.cutter.dia" in why and "assumed" in why
    tool["center_cutting"] = False
    measurements.clear()
    feed, cite, why = speeds_feeds.plunge_row(data, op, measurements=measurements)
    assert (feed, cite) == ("unknown", "unknown")
    assert "not centre-cutting" in why and measurements == []


@pytest.mark.parametrize("rule", [sizing, speeds_feeds, headroom])
def test_bare_nominal_policy_is_unchanged_and_unrelated_records_do_not_taint_passes(rule):
    data = bundle()
    [baseline] = rule.evaluate(data)
    assert baseline.status == "pass"
    nominal = deepcopy(data)
    for category in ("fixtures", "tools", "holders"):
        for item in nominal.inventory[category].values():
            for key, value in list(item.items()):
                if isinstance(value, dict) and "value" in value:
                    item[key] = value["value"]
    nominal.inventory["tools"]["unused"] = {"kind": "endmill", "dia_mm": fact(9, "assumed")}
    nominal.inventory["tools"]["cutter"]["nose_radius_mm"] = fact(0.4, "illustrative")
    assert rule.evaluate(nominal) == [baseline]


@pytest.mark.parametrize("reference", [None, "none", "not_applicable", "unknown", "missing"])
def test_headroom_unselected_or_unresolved_support_is_not_a_physical_height_debt(reference):
    data = bundle()
    data.plan["setups"][0]["hold"]["supports"] = reference
    [row] = headroom.evaluate(data)
    assert row.status == ("unknown" if reference in {"unknown", "missing"} else "pass")
    assert row.numbers["measurements"] == []
    # An unselected/stale local record cannot manufacture a checklist identity either.
    debts = {}
    assert (
        headroom._length(data, {"kind": "parallels"}, "height", "fixtures", reference, debts)
        == "unknown"
    )
    assert debts == {}


def test_headroom_selected_real_support_with_missing_height_keeps_its_measurement_debt():
    data = bundle()
    data.plan["setups"][0]["hold"]["supports"] = "support"
    data.inventory["fixtures"]["support"] = {"kind": "parallels"}
    [row] = headroom.evaluate(data)
    assert_debts(row, {"fixtures.support.height": "missing"})
    assert row.numbers["support_blocks_mm"] == "unknown"
    assert row.numbers["sum_mm"] == "unknown"


def turning_setting_bundle(tmp_path, projection=10.0):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup["machine"] = "lathe"
    setup["ops"][0].update(tool="turn", holder="post")
    data.inventory["machines"] = {"lathe": {"kind": "lathe", "resolution_mm": fact(0.001)}}
    data.inventory["tools"] = {
        "turn": {
            "kind": "turning",
            "hand": "right",
            "nose_radius_mm": fact(0.4),
            "insert_angle_deg": fact(80.0),
            "entering_angle_deg": fact(85.0),
            "edge_len_mm": fact(6.0),
            "head_len_mm": fact(12.0),
            "shank_width_mm": fact(10.0),
            "functional_width_mm": fact(12.0),
            "projection_mm": {"post": fact(projection)},
            "reach_mm": fact(5.0),
        }
    }
    data.inventory["holders"] = {
        "post": {
            "kind": "qctp",
            "body_width_mm": fact(30.0),
            "body_depth_mm": fact(20.0),
        }
    }
    data.inventory["fixtures"]["parallels"].update(length_mm=fact(50.0), width_mm=fact(6.0))
    data.kernel["ops"]["S1:10"]["approach"] = "turning"
    return data


@pytest.mark.parametrize("case", ["missing", "assumed", "illustrative"])
def test_invalid_turning_setting_does_not_acquire_unconsumed_context_debts(tmp_path, case):
    data = turning_setting_bundle(tmp_path)
    data.inventory["fixtures"]["parallels"].update(
        length_mm=fact(50.0, case), width_mm=fact(6.0, case)
    )
    data.inventory["machines"]["lathe"]["resolution_mm"] = fact(0.001, case)
    data.inventory["tools"]["turn"]["reach_mm"] = fact(5.0, case)
    setup = data.plan["setups"][0]
    job = kernel.build_job(data)
    # Fixture/reach preparation retains real consumer debt; this op authors no DRO target.
    entries = kernel_measurement_debts(job, setup, setup["ops"][0], fixture=True)
    assert {entry["id"] for entry in entries} == {
        "fixtures.parallels.length",
        "fixtures.parallels.width",
        "tools.turn.reach",
    }
    [row] = accessibility.evaluate(data)
    assert row.status == "unknown"
    assert "projection_mm at least head_len_mm" in row.sentence
    assert "unmeasured" not in row.sentence
    assert row.numbers == {
        "projection_mm": 10.0,
        "head_len_mm": 12.0,
        "tool_z_mm": "unknown",
        "nose_z_mm": "unknown",
    }
    assert measurement_checklist([row]) == []


@pytest.mark.parametrize(("case", "status"), REFUSALS)
@pytest.mark.parametrize("field", ["projection", "head_len"])
@pytest.mark.parametrize("projection", [10.0, 25.0], ids=["invalid-setting", "clear-setting"])
def test_turning_setting_requires_trusted_comparison_inputs(
    tmp_path, case, status, field, projection
):
    data = turning_setting_bundle(tmp_path, projection)
    setup = data.plan["setups"][0]
    tool = data.inventory["tools"]["turn"]
    if field == "projection":
        tool["projection_mm"]["post"] = fact(projection, case)
        expected = {"tools.turn.projection.post": status}
    else:
        tool["head_len_mm"] = fact(12.0, case)
        expected = {"tools.turn.head_len": status}
    inputs = kernel.op_inputs(data, setup, setup["ops"][0])
    assert inputs.get(field + "_mm", "unknown") == "unknown"
    [row] = accessibility.evaluate(data)
    assert_debts(row, expected)
    assert "unmeasured" in row.sentence
    assert "projection_mm at least head_len_mm" not in row.sentence
    assert row.numbers["tool_z_mm"] == row.numbers["nose_z_mm"] == "unknown"


def engagement_claim_bundle():
    data = bundle()
    data.plan["setups"][0]["ops"][0].update(do="rough_pocket", doc_mm=2)
    data.inventory["tools"]["cutter"].update(
        kind="endmill",
        dia_mm=fact(10),
        oal_mm=fact(55),
        projection_mm={"holder": fact(30)},
    )
    return data


def engagement_claim_row(data):
    from prechips.rules import RULES

    registered = next(rule for rule in RULES if rule.name == "engagement")
    [row] = registered.evaluate(data)
    return row


@pytest.mark.parametrize(
    "case",
    [
        "measured",
        "assumed",
        "illustrative",
        "legacy",
        "incomplete",
        "verify_true",
        "verify_unknown",
        "missing",
        "nominal",
        "absent",
    ],
)
@pytest.mark.parametrize("field", ["oal", "grip"])
def test_explicit_engagement_labels_unused_stack_lengths_without_consuming_their_debt(case, field):
    data = engagement_claim_bundle()
    baseline = engagement_claim_row(data)
    assert baseline.status == "pass"
    assert baseline.numbers["tool_oal_mm"] == baseline.numbers["holder_grip_mm"] == "not used"
    assert baseline.numbers["projection_mm"] == 30
    assert baseline.numbers["projection_ld"] == 3
    assert baseline.numbers["projection_basis"] == "selected tool/holder projection"
    assert baseline.numbers["diameter_mm"] == 10
    assert baseline.numbers["doc_scale"] == 1
    assert baseline.numbers["recommended_doc_mm"] == 2
    assert not any("OAL" in cite or "grip" in cite for cite in baseline.cite)
    item, value = (
        (data.inventory["tools"]["cutter"], 55)
        if field == "oal"
        else (data.inventory["holders"]["holder"], 25)
    )
    if case == "absent":
        del item[field + "_mm"]
    else:
        item[field + "_mm"] = value if case == "nominal" else fact(value, case)
    authored = deepcopy(vars(data))
    row = engagement_claim_row(data)
    if case in {"verify_true", "verify_unknown"}:
        identity = "tools.cutter.verify" if field == "oal" else "holders.holder.verify"
        assert_debts(row, {identity: "unmeasured"})
        assert row.numbers["tool_oal_mm"] == row.numbers["holder_grip_mm"] == "not used"
        assert row.numbers["diameter_mm"] == baseline.numbers["diameter_mm"]
        assert row.numbers["projection_mm"] == baseline.numbers["projection_mm"]
        assert row.numbers["projection_basis"] == baseline.numbers["projection_basis"]
        assert row.numbers["projection_ld"] == row.numbers["recommended_doc_mm"] == "unknown"
        selected = "tool" if field == "oal" else "holder"
        assert row.numbers["missing_inputs"] == [f"resolved/verified selected {selected}"]
    else:
        assert row == baseline
        assert measurement_checklist([row]) == []
    assert engagement_claim_row(data) == row
    assert vars(data) == authored


def test_explicit_engagement_does_not_walk_unrelated_holder_or_tool_facts():
    data = engagement_claim_bundle()
    baseline = engagement_claim_row(data)
    data.inventory["holders"]["holder"].update(
        gauge_len_mm=fact(30, "assumed"),
        gauge_dia_mm=fact(40, "illustrative"),
    )
    data.inventory["tools"]["cutter"].update(
        flute_len_mm=fact(15, "assumed"),
        nose_radius_mm=fact(0.4, "illustrative"),
    )
    data.inventory["holders"]["unused"] = {"kind": "collet", "grip_mm": fact(25, "assumed")}
    row = engagement_claim_row(data)
    assert row == baseline
    assert row.status == "pass"
    assert measurement_checklist([row]) == []


@pytest.mark.parametrize(("case", "status"), REFUSALS)
@pytest.mark.parametrize("field", ["oal", "grip"])
def test_inferred_engagement_names_only_the_stack_length_it_actually_consumes(case, status, field):
    data = engagement_claim_bundle()
    tool = data.inventory["tools"]["cutter"]
    holder = data.inventory["holders"]["holder"]
    del tool["projection_mm"]
    baseline = engagement_claim_row(data)
    assert baseline.status == "pass"
    assert baseline.numbers["projection_mm"] == 30
    assert baseline.numbers["projection_ld"] == 3
    assert baseline.numbers["projection_basis"] == "tool OAL - selected holder grip"
    assert baseline.numbers["tool_oal_mm"] == 55
    assert baseline.numbers["holder_grip_mm"] == 25
    item, value, identity = (
        (tool, 55, "tools.cutter.oal") if field == "oal" else (holder, 25, "holders.holder.grip")
    )
    item[field + "_mm"] = fact(value, case)
    holder["gauge_len_mm"] = fact(30, "illustrative")
    row = engagement_claim_row(data)
    expected = {identity: status}
    if case in {"verify_true", "verify_unknown"}:
        verification = "tools.cutter.verify" if field == "oal" else "holders.holder.verify"
        expected[verification] = "unmeasured"
    assert_debts(row, expected)
    assert row.numbers[("tool_oal_mm" if field == "oal" else "holder_grip_mm")] == "unknown"
    assert row.numbers["projection_ld"] == row.numbers["recommended_doc_mm"] == "unknown"
    item[field + "_mm"] = fact(value)
    assert engagement_claim_row(data) == baseline


@pytest.mark.parametrize(("case", "status"), REFUSALS)
@pytest.mark.parametrize("field", ["dia", "projection"])
def test_explicit_engagement_still_refuses_its_actual_ratio_inputs(case, status, field):
    data = engagement_claim_bundle()
    tool = data.inventory["tools"]["cutter"]
    baseline = engagement_claim_row(data)
    if field == "projection":
        tool["projection_mm"]["holder"] = fact(30, case)
        expected = {"tools.cutter.projection.holder": status}
    else:
        tool["dia_mm"] = fact(10, case)
        expected = {"tools.cutter.dia": status}
    if case in {"verify_true", "verify_unknown"}:
        expected["tools.cutter.verify"] = "unmeasured"
    tool["oal_mm"] = fact(55, "assumed")
    data.inventory["holders"]["holder"]["grip_mm"] = fact(25, "illustrative")
    row = engagement_claim_row(data)
    assert_debts(row, expected)
    assert row.numbers["tool_oal_mm"] == row.numbers["holder_grip_mm"] == "not used"
    assert row.numbers["projection_ld"] == row.numbers["recommended_doc_mm"] == "unknown"
    if field == "projection":
        tool["projection_mm"]["holder"] = fact(30)
    else:
        tool["dia_mm"] = fact(10)
    assert engagement_claim_row(data) == baseline


@pytest.mark.parametrize("explicit", [True, False], ids=["installed", "inferred"])
def test_engagement_inherited_grip_debt_never_enumerates_unselected_collet_members(explicit):
    data = engagement_claim_bundle()
    holder = data.inventory["holders"].pop("holder")
    holder.update(
        kind="collet_set",
        grip_mm=fact(25, "assumed"),
        members={"3-8in": {}, **{f"unused-{index}": {} for index in range(12)}},
    )
    data.inventory["holders"]["collets"] = holder
    data.plan["setups"][0]["ops"][0]["holder"] = "holders.collets/3-8in"
    tool = data.inventory["tools"]["cutter"]
    if explicit:
        tool["projection_mm"] = {"collets/3-8in": fact(30)}
    else:
        del tool["projection_mm"]
    row = engagement_claim_row(data)
    if explicit:
        assert row.status == "pass"
        assert row.numbers["holder_grip_mm"] == "not used"
        assert measurement_checklist([row]) == []
    else:
        assert_debts(row, {"holders.collets/3-8in.grip": "assumed"})
    holder["grip_mm"]["measured"]["status"] = "measured"
    trusted = engagement_claim_row(data)
    assert trusted.status == "pass"
    assert trusted.numbers["projection_mm"] == 30
    assert trusted.numbers["projection_ld"] == 3
    assert measurement_checklist([trusted]) == []
    if explicit:
        assert trusted == row


def test_inferred_engagement_retains_bare_nominal_stack_length_admission():
    data = engagement_claim_bundle()
    tool = data.inventory["tools"]["cutter"]
    del tool["projection_mm"]
    baseline = engagement_claim_row(data)
    tool["oal_mm"] = 55
    data.inventory["holders"]["holder"]["grip_mm"] = 25
    assert baseline.status == "pass"
    assert engagement_claim_row(data) == baseline


@pytest.mark.parametrize("case", ["assumed", "illustrative", "legacy"])
@pytest.mark.parametrize("field", ["oal", "grip"])
def test_unused_engagement_stack_provenance_keeps_the_installed_native_job(tmp_path, case, field):
    data = rules_bundle(tmp_path)
    data.plan["setups"][0]["ops"][0]["doc_mm"] = 2
    data.inventory["tools"]["em"].update(
        dia_mm=fact(10),
        oal_mm=fact(55),
        projection_mm={"holder": fact(30)},
    )
    data.inventory["holders"]["holder"]["grip_mm"] = fact(25)
    baseline = engagement_claim_row(data)
    assert baseline.status == "pass"
    native = kernel.engine_job(kernel.build_job(data))
    item, value = (
        (data.inventory["tools"]["em"], 55)
        if field == "oal"
        else (data.inventory["holders"]["holder"], 25)
    )
    item[field + "_mm"] = fact(value, case)
    assert engagement_claim_row(data) == baseline
    assert kernel.engine_job(kernel.build_job(data)) == native
