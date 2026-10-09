"""Manual arc travelers tell the operator how to rough, lay out and file the arc."""

import re

import pytest
from test_sheet_ops import Markup, content
from test_sheet_precision import VisibleText, table_rows, tagged

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.rules.coordinates import row_id
from prechips.sheet import _Traveler


def text(html):
    visible = "".join(" " if part == "|" else part for part in VisibleText(html).parts)
    return " ".join(visible.split())


def coordinate_tables(html):
    markup = Markup(html)
    (owner,) = markup.find("contour")
    assert owner["attrs"]["data-page-context"].startswith("S1 op 20 —")
    return markup, owner, markup.find("coords", owner)


def headers(markup, table):
    (head,) = tagged(markup, "thead", table)
    rows = tagged(markup, "tr", head)
    return [content(cell).strip() for cell in tagged(markup, "th", rows[-1])]


def operation_text(html, op):
    markup = Markup(html)
    (owner,) = [
        node for node in markup.find("operation") if node["attrs"].get("data-op") == str(op)
    ]
    instructions = markup.find("see", owner)
    assert instructions, f"Missing manual instructions for op {op}"
    return " ".join(" ".join(content(node).split()) for node in instructions)


def no_programming(html):
    assert not re.search(
        r"\b(?:MDI|G[123]|G-code|continuous circle|interpolation)\b", text(html), re.I
    )


def traveler(tmp_path, operations, numbers=None, manual=None, machine="mill"):
    setup = {
        "id": "S1",
        "machine": machine,
        "frame": "A",
        "hold": {"fixture": "none"},
        "ops": operations,
    }
    data = Bundle(
        plan={"setups": [setup]},
        features={
            "units": "mm",
            "features": {
                "arc": {"kind": "profile", "name": "outer arc", "requirements": []},
                "centre_bore": {"kind": "hole", "name": "centre bore", "requirements": []},
            },
        },
        inventory={
            "machines": {machine: {"kind": machine, "resolution_mm": 0.001}},
            "fixtures": {"buttons": {"kind": "filing_buttons", "name": "R10 filing buttons"}},
            "tools": {"cutter": {"kind": "endmill", "name": "6 mm endmill"}},
            "gauges": {
                "template": {"name": "arc template"},
                "gauge": {"name": "radius gauge"},
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
        kernel={"status": "ok", "ops": {}},
    )
    findings = []
    waypoints = []
    if numbers is not None:
        findings.append(Finding("coordinates", "S1", "pass", numbers, [], ""))
        for table_name in ("arc_table", "line_table"):
            for table in numbers.get(table_name, []):
                rows = table.get("rows", []) if table_name == "arc_table" else table["dro_xy"]
                for index, _ in enumerate(rows):
                    waypoints.append(
                        {
                            "op": str(table["op"]),
                            "label": f"P{len(waypoints) + 1}",
                            "rows": [row_id(f"S1:{table['op']}", table_name, table, index)],
                        }
                    )
    for record in manual or []:
        findings.append(
            Finding(
                "manual_arc",
                f"S1:{record['op']}",
                "unknown"
                if record.get("do") == "file_to_line"
                and (record.get("rough_op") is None or record.get("stock_cap_mm") == "unknown")
                else "pass",
                record,
                [],
                "",
            )
        )

    report = {"renders": {"S1": {"scene": {"waypoints": waypoints}}}} if numbers else {}
    sheet = _Traveler(data, findings, report, None)
    sheet.setup = setup
    return sheet, setup


def arc_record(method):
    return {
        "method": method,
        "op": 20,
        "feature": "arc",
        "stage": "rough" if method in {"stairs", "chain_drill"} else "finish",
        "allowance_mm": 0.2,
        "centre_setup_xy": [2, -3],
        "cutter_centre_radius_mm": 13.2,
        "dro_tip_z": -2.125,
        "rows": [
            {"dro_xy": [15.2, -3], "jog": "X", "angle_deg": 0},
            {"dro_xy": [15.2, 1.5], "jog": "Y", "corner": True},
            {"dro_xy": [12.8, 1.5], "jog": "X", "angle_deg": 20},
        ],
        "stock_left_mm": 0.42,
        "stock_cap_mm": 0.5,
        "cut_order": "conventional",
        "spindle_rotation": "cw",
    }


def contour_sheet(tmp_path, arc, line=None, scribed=False):
    method = arc["method"]
    numbers = {
        "arc_table": [arc],
        "profiles": [{"op": 20, "contour": {"method": method}, "cutter_centre": [[99, 88]]}],
        "line_table": [line] if line else [],
    }
    # Laying the arc out is optional: a scribe op before the rough names its line.
    scribe = [{"op": 10, "do": "scribe", "feature": "arc"}] if scribed else []
    sheet, setup = traveler(
        tmp_path,
        [*scribe, {"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        numbers,
    )
    html = sheet.contours(setup, {("tools", "cutter"): "6 mm endmill"})
    no_programming(html)
    assert "99.000" not in text(html), "the generic arc profile must not print a second table"
    return html, text(html)


def test_stairs_print_every_corner_and_single_handwheel_axis(tmp_path):
    arc = arc_record("stairs")
    arc.update(step_deg=20, stair_cusp_mm=0.22)
    line = {
        "op": 20,
        "stage": "rough",
        "side": "west",
        "setup_xy": [[12.8, 1.5], [12.8, 4]],
        "dro_xy": [[12.8, 1.5], [12.8, 4]],
        "dro_tip_z": -2.125,
        "jog": [None, "Y"],
    }
    line["stair_cusp_mm"] = 0.1272
    html, printed = contour_sheet(tmp_path, arc, line)
    markup, owner, tables = coordinate_tables(html)
    assert len(tables) == 2
    rough_context, join_context = [
        content(markup.find("table-context", table)[0]) for table in tables
    ]
    # The cusp bound belongs to the join table and rounds up to the 0.001 DRO grid.
    assert "the stair leaves ≤ 0.128" in join_context and "0.1272" not in printed
    assert "rough stairs" in rough_context.lower()
    assert "outside the finished outline" in rough_context and "scribed" not in printed
    assert all("one handwheel axis per row" in value for value in (rough_context, join_context))
    assert "at most 0.420 mm for the file" in rough_context and "cap 0.5 mm" in rough_context
    # Every move is at one Z: it heads the block and each table's continued-page heading
    # (one per table), and no row repeats it.
    (heading,) = tagged(markup, "h3", owner)
    assert "S1 op 20" in content(heading) and "6 mm endmill" in content(heading)
    assert "Z -2.125" in content(heading)
    for table in tables:
        (repeat,) = markup.find("repeat", table)
        assert "S1 op 20" in content(repeat) and "Z -2.125" in content(repeat)
    assert "Z" not in [heading for table in tables for heading in headers(markup, table)]
    assert printed.count("-2.125") == 3, printed
    # Each row owns its picture index, coordinates and one handwheel axis.
    assert headers(markup, tables[0]) == ["#", "P", "X", "Y", "handwheel axis"]
    assert table_rows(markup, tables[0]) == [
        ["1", "P1", "15.200", "-3.000", "X"],
        ["2", "P2 (corner)", "15.200", "1.500", "Y"],
        ["3", "P3", "12.800", "1.500", "X"],
    ]
    assert table_rows(markup, tables[1]) == [
        ["4", "P4", "12.800", "1.500", ""],
        ["5", "P5", "12.800", "4.000", "Y"],
    ]


def test_chain_drill_prints_holes_then_breakout_and_filing_stock(tmp_path):
    arc = arc_record("chain_drill")
    arc.update(
        drill_dia_mm=3.5,
        pitch_mm=3.2,
        hole_clear_mm=0.1,
        break_out="chisel the webs out along the hole line",
    )
    html, printed = contour_sheet(tmp_path, arc, scribed=True)
    markup, owner, tables = coordinate_tables(html)
    (table,) = tables
    assert headers(markup, table) == ["hole #", "P", "X", "Y"]
    assert table_rows(markup, table) == [
        ["1", "P1", "15.200", "-3.000"],
        ["2", "P2", "15.200", "1.500"],
        ["3", "P3", "12.800", "1.500"],
    ]
    context = content(markup.find("table-context", table)[0])
    assert "drill Ø3.5 mm" in context and "pitch 3.2 mm" in context
    assert "every hole outside the scribed line" in context
    (breakout,) = [
        node
        for node in tagged(markup, "p", owner)
        if "chisel the webs out along the hole line" in content(node)
    ]
    assert markup.nodes.index(table) < markup.nodes.index(breakout)
    assert "at most 0.420 mm for the file" in content(breakout)
    assert "cap 0.5 mm" in content(breakout)


def test_chords_print_endpoints_length_sagitta_index_and_radius_band(tmp_path):
    arc = arc_record("chords")
    arc.update(
        edge_radius_mm=100.1,
        band_mm=[99.8, 100.2],
        chords=[
            {
                "from": 0,
                "to": 1,
                "length_mm": 4.5,
                "sagitta_mm": 0.025,
                "cut": {"index_deg": None, "along": "Y", "at": 15.2, "from": -3, "to": 1.5},
            },
            {
                "from": 1,
                "to": 2,
                "length_mm": 2.4,
                "sagitta_mm": 0.007,
                "cut": {"index_deg": 15.25, "along": "X", "at": -1.125, "from": 4.75, "to": 7.15},
            },
        ],
    )
    html, printed = contour_sheet(tmp_path, arc)
    markup, owner, tables = coordinate_tables(html)
    (table,) = tables
    assert headers(markup, table) == [
        "chord #",
        "from P",
        "from X",
        "from Y",
        "to P",
        "to X",
        "to Y",
        "length mm",
        "sagitta mm",
        "index °",
        "handwheel cut",
    ]
    rows = table_rows(markup, table)
    assert [row[:-1] for row in rows] == [
        ["1", "P1", "15.200", "-3.000", "P2", "15.200", "1.500", "4.5", "0.025", ""],
        ["2", "P2", "15.200", "1.500", "P3", "12.800", "1.500", "2.4", "0.007", "15.25"],
    ]
    assert "lock X at 15.200" in rows[0][-1] and "feed Y -3.000 → 1.500" in rows[0][-1]
    assert "lock Y at -1.125" in rows[1][-1] and "feed X 4.750 → 7.150" in rows[1][-1]
    context = content(markup.find("table-context", table)[0])
    assert "chord ends sit on R 100.1 mm" in context
    assert "every chord stays inside R 99.8–100.2 mm" in context


def test_unknown_chord_cut_does_not_print_a_handwheel_motion(tmp_path):
    arc = arc_record("chords")
    arc.update(
        edge_radius_mm=100.1,
        band_mm=[99.8, 100.2],
        chords=[
            {
                "from": 0,
                "to": 1,
                "length_mm": 4.5,
                "sagitta_mm": 0.025,
                "cut": {"index_deg": None, "along": "X", "at": "unknown", "from": 1, "to": 2},
            }
        ],
    )
    html, printed = contour_sheet(tmp_path, arc)
    markup, owner, tables = coordinate_tables(html)
    (table,) = tables
    (row,) = table_rows(markup, table)
    assert "STOP: chord handwheel cut not established" in row[-1]
    assert "feed X" not in printed


@pytest.mark.parametrize("rotation", ["clockwise", "counterclockwise"])
@pytest.mark.parametrize("centre_by", ["pin", "indicate"])
@pytest.mark.parametrize(("convex", "offset", "formula"), [(True, 13, "plus"), (False, 7, "minus")])
def test_rotary_recipe_prints_centring_offset_dial_and_conventional_direction(
    tmp_path, centre_by, convex, offset, formula, rotation
):
    arc = arc_record("rotary_table")
    arc["rotary"] = {
        "table": "rotary",
        "table_name": "6 inch rotary table",
        "centre_by": centre_by,
        "centre_feature": "centre_bore",
        "pin_dia_mm": 4,
        "table_bore_dia_mm": 4.01,
        "centre_play_mm": 0.015,
        "convex": convex,
        "radius_mm": 9.99,
        "cut_radius_mm": 10,
        "cutter_radius_mm": 3,
        "offset_axis": "X",
        "offset_x": offset,
        "start_deg": 12.5,
        "stop_deg": 102.5,
        "sweep_deg": 90,
        "resolution_deg": 0.25,
        "rotation": rotation,
    }
    html, printed = contour_sheet(tmp_path, arc)
    markup, owner, tables = coordinate_tables(html)
    assert not tables
    (steps,) = tagged(markup, "ol", owner)
    instructions = [content(node) for node in tagged(markup, "li", steps)]
    assert len(instructions) == 4
    centring, locating, offsetting, cutting = instructions
    assert "indicating its centre bore" in centring and "DRO X0 Y0" in centring
    if centre_by == "pin":
        assert "Ø4 mm through centre bore" in locating and "Ø4.01 mm" in locating
        assert "0.015 mm" in locating
    else:
        assert "indicate centre bore" in locating
    # The formula and the resulting offset must be on the same step, not elsewhere.
    assert f"offset the table to X {offset}.000 " in offsetting
    assert f"R 10 mm {formula} cutter radius 3 mm" in offsetting
    assert ("convex" if convex else "concave") in offsetting
    assert "lock x and y" in cutting.lower() and "set Z -2.125" in cutting
    assert re.search(rf"\b{rotation} from 12\.5° to 102\.5°", cutting)
    assert "sweep 90°" in cutting and "dial to 0.25°" in cutting
    assert "conventional-cut direction" in cutting
    assert "15.200" not in printed, "rotary samples belong only to the picture"


def manual_record(op, action):
    return {
        "op": op,
        "do": action,
        "feature": "arc",
        "radius_mm": 10,
        "centre_setup_xy": [2, -3],
        "centre_on": "centre_bore",
        "ends_setup_xy": [[12, -3], [2, 7]],
        "layout": "dividers",
        "guide": {
            "kind": "buttons",
            "kit": "buttons",
            "bore": "centre_bore",
            "button_dia_mm": [19.99, 20.0],
            "button_bore_mm": [4.0, 4.01],
            "pin_dia_mm": [3.99, 4.0],
            "button_runout_mm": 0.004,
            "bore_dia_mm": [4.0, 4.01842],
            "centre_shift_mm": {"pin_in_bore": 0.01421, "button_on_pin": 0.01, "runout": 0.002},
            "files_to_mm": [9.96879, 10.02621],
        },
        "gauge": {"ref": "gauge", "range_mm": [9, 11]},
        "rough_op": "S1:20",
        "stock_cap_mm": 0.5,
    }


@pytest.mark.parametrize("machine", ["mill", "bench"])
@pytest.mark.parametrize("layout", ["dividers", "trammel", "template"])
def test_manual_layout_and_filing_attach_to_their_operation_even_at_the_bench(
    tmp_path, machine, layout
):
    scribe = manual_record(10, "scribe")
    scribe.update(layout=layout, template="template")
    filing = manual_record(30, "file_to_line")
    sheet, setup = traveler(
        tmp_path,
        [
            {"op": 10, "do": "scribe", "feature": "arc"},
            {"op": 30, "do": "file_to_line", "feature": "arc"},
        ],
        manual=[scribe, filing],
        machine=machine,
    )
    html = "".join(sum(sheet.setup_section(setup), []))
    no_programming(html)
    layout_text = operation_text(html, 10)
    filing_text = operation_text(html, 30)
    assert "blue the part" in layout_text and "scribe R10 mm" in layout_text
    assert "X 2.000, Y -3.000" in layout_text and "on the axis of centre bore" in layout_text
    assert ("arc template" if layout == "template" else layout) in layout_text
    assert "arc ends" in layout_text
    assert "X 12.000, Y -3.000" in layout_text and "X 2.000, Y 7.000" in layout_text
    assert "file down to the hardened button rims" in filing_text
    assert "R10 filing buttons" in filing_text
    # Receipt limits and the outward-rounded proven band belong to the filing operation.
    for value in ("19.99", "4.01", "3.99", "0.004", "4.01842"):
        assert value in filing_text
    assert "R9.968 to R10.027 mm" in filing_text
    assert "check with radius gauge" in filing_text
    assert "file off the stock left by S1:20 (at most 0.5 mm)" in filing_text
    assert "Bench filing:" not in layout_text and "Layout:" not in filing_text
    assert "STOP" not in text(html)


@pytest.mark.parametrize(
    ("rough_op", "cap", "stop"),
    [
        ("S1:20", "unknown", "filing stock limit not established"),
        (None, 0.5, "roughing operation not established"),
    ],
)
def test_template_guide_and_unknown_stock_do_not_claim_a_filing_allowance(
    tmp_path, rough_op, cap, stop
):
    filing = manual_record(30, "file_to_line")
    filing.update(
        guide={"kind": "template", "kit": "template"}, rough_op=rough_op, stock_cap_mm=cap
    )
    sheet, setup = traveler(
        tmp_path,
        [{"op": 30, "do": "file_to_line", "feature": "arc"}],
        manual=[filing],
        machine="bench",
    )
    html = "".join(sum(sheet.setup_section(setup), []))
    printed = operation_text(html, 30)
    no_programming(html)
    assert "guide: arc template" in printed
    assert f"STOP: {stop}" in printed
    assert "at most" not in printed


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("pin_dia_mm", "pin limits unknown; worst-case filing radius not established"),
        (
            "button_runout_mm",
            "button runout limits unknown; worst-case filing radius not established",
        ),
        ("files_to_mm", "worst-case filing radius not established"),
    ],
)
def test_buttons_without_a_worst_case_band_print_a_stop(tmp_path, missing, reason):
    filing = manual_record(30, "file_to_line")
    operations = [{"op": 30, "do": "file_to_line", "feature": "arc"}]
    control, control_setup = traveler(tmp_path, operations, manual=[filing], machine="bench")
    valid = operation_text("".join(sum(control.setup_section(control_setup), [])), 30)
    assert "R9.968 to R10.027 mm" in valid
    assert "STOP" not in valid
    filing["guide"][missing] = "unknown"
    sheet, setup = traveler(
        tmp_path,
        operations,
        manual=[filing],
        machine="bench",
    )
    printed = operation_text("".join(sum(sheet.setup_section(setup), [])), 30)
    assert f"STOP: {reason}" in printed
    assert not re.search(r"R\d+(\.\d+)? to R\d", printed)
