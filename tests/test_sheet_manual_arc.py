"""Manual arc travelers tell the operator how to rough, lay out and file the arc."""

import re
from html import unescape

import pytest

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.rules.coordinates import row_id
from prechips.sheet import _Traveler


def text(html):
    return unescape(re.sub(r"<[^>]+>", " ", html))


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


def contour_sheet(tmp_path, arc, line=None):
    method = arc["method"]
    numbers = {
        "arc_table": [arc],
        "profiles": [{"op": 20, "contour": {"method": method}, "cutter_centre": [[99, 88]]}],
        "line_table": [line] if line else [],
    }
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        numbers,
    )
    html = sheet.contours(setup, {"cutter": "6 mm endmill"})
    no_programming(html)
    assert "99.000" not in html, "the generic arc profile must not print a second table"
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
    html, printed = contour_sheet(tmp_path, arc, line)
    assert "rough stairs" in printed.lower() and "outside the scribed line" in printed
    assert "one handwheel axis per row" in printed
    assert "at most 0.420 mm for the file" in printed and "cap 0.5 mm" in printed
    assert re.search(r"P1\s+15\.200\s+-3\.000\s+-2\.125\s+X", printed)
    assert re.search(r"P2.*corner.*15\.200\s+1\.500\s+-2\.125\s+Y", printed)
    assert re.search(r"P3\s+12\.800\s+1\.500\s+-2\.125\s+X", printed)
    assert re.search(r"P5\s+12\.800\s+4\.000\s+-2\.125\s+Y", printed)
    assert "<th>handwheel axis</th>" in html


def test_chain_drill_prints_holes_then_breakout_and_filing_stock(tmp_path):
    arc = arc_record("chain_drill")
    arc.update(
        drill_dia_mm=3.5,
        pitch_mm=3.2,
        hole_clear_mm=0.1,
        break_out="chisel the webs out along the hole line",
    )
    html, printed = contour_sheet(tmp_path, arc)
    assert "<th>hole #</th>" in html
    assert "drill Ø3.5 mm" in printed and "pitch 3.2 mm" in printed
    assert "every hole outside the scribed line" in printed
    assert re.search(r"1\s+P1\s+15\.200\s+-3\.000", printed)
    assert re.search(r"3\s+P3\s+12\.800\s+1\.500", printed)
    assert "chisel the webs out along the hole line" in printed
    assert html.index("</table>") < html.index("chisel the webs")
    assert "at most 0.420 mm for the file" in printed


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
    for heading in (
        "chord #",
        "from X",
        "from Y",
        "to X",
        "to Y",
        "length mm",
        "sagitta mm",
        "index °",
    ):
        assert f"<th>{heading}</th>" in html
    assert re.search(r"P1\s+15\.200\s+-3\.000\s+P2\s+15\.200\s+1\.500\s+4\.5\s+0\.025", printed)
    assert "15.25" in printed and "0.007" in printed
    assert "lock X at 15.200" in printed and "feed Y -3.000 → 1.500" in printed
    assert "lock Y at -1.125" in printed and "feed X 4.750 → 7.150" in printed
    assert "chord ends sit on R 100.1 mm" in printed
    assert "every chord stays inside R 99.8–100.2 mm" in printed


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
    _, printed = contour_sheet(tmp_path, arc)
    assert "STOP: chord handwheel cut not established" in printed
    assert "feed X" not in printed


@pytest.mark.parametrize("centre_by", ["pin", "indicate"])
@pytest.mark.parametrize(("convex", "offset", "formula"), [(True, 13, "plus"), (False, 7, "minus")])
def test_rotary_recipe_prints_centring_offset_dial_and_conventional_direction(
    tmp_path, centre_by, convex, offset, formula
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
        "rotation": "counterclockwise",
    }
    html, printed = contour_sheet(tmp_path, arc)
    assert "<ol>" in html and "<table" not in html
    assert "indicating its centre bore" in printed and "DRO X0 Y0" in printed
    if centre_by == "pin":
        # The pin, the table bore it fits and the centre's play are all on the sheet.
        assert "Ø4 mm through centre bore" in printed and "Ø4.01 mm" in printed
        assert "0.015 mm" in printed
    else:
        assert "indicate centre bore" in printed
    # The printed X is explained by the radius it cuts (the DRO grid moved it off R9.99).
    assert f"offset the table to X {offset}.000 " in printed
    assert f"R 10 mm {formula} cutter radius 3 mm" in printed
    assert ("convex" if convex else "concave") in printed
    assert "lock x and y" in printed.lower() and "set Z -2.125" in printed
    assert "counterclockwise from 12.5° to 102.5°" in printed
    assert "sweep 90°" in printed and "dial to 0.25°" in printed
    assert "conventional-cut direction" in printed
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
    printed = text(html)
    assert "blue the part" in printed and "scribe R10 mm" in printed
    assert "X 2.000, Y -3.000" in printed and "on the axis of centre bore" in printed
    assert ("arc template" if layout == "template" else layout) in printed
    assert (
        "arc ends" in printed and "X 12.000, Y -3.000" in printed and "X 2.000, Y 7.000" in printed
    )
    assert "file down to the hardened button rims" in printed
    assert "R10 filing buttons" in printed
    # Every stack element's receipt limits print...
    for value in ("19.99", "4.01", "3.99", "0.004", "4.01842"):
        assert value in printed
    # ...and the worst case rounds outward, never narrower than the band it was proven in.
    assert "R9.968 to R10.027 mm" in printed
    assert "check with radius gauge" in printed
    assert "file off the stock left by S1:20 (at most 0.5 mm)" in printed
    assert "STOP" not in printed


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
    printed = text(html)
    no_programming(html)
    assert "guide: arc template" in printed
    assert f"STOP: {stop}" in printed
    assert "at most" not in printed


@pytest.mark.parametrize("missing", ["pin_dia_mm", "button_runout_mm", "files_to_mm"])
def test_buttons_without_a_worst_case_band_print_a_stop(tmp_path, missing):
    filing = manual_record(30, "file_to_line")
    guide = filing["guide"]
    guide.pop("files_to_mm")
    guide[missing] = "unknown"
    sheet, setup = traveler(
        tmp_path,
        [{"op": 30, "do": "file_to_line", "feature": "arc"}],
        manual=[filing],
        machine="bench",
    )
    printed = text("".join(sum(sheet.setup_section(setup), [])))
    assert "STOP" in printed
    assert not re.search(r"R\d+(\.\d+)? to R\d", printed)
