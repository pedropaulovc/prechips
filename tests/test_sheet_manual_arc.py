"""Manual arc travelers tell the operator how to rough, lay out and file the arc."""

import re

import pytest
from test_manual_arc import (
    JOIN_DRILL,
    joined_chain_finding,
    joined_chain_plan,
    synthetic_join_clip,
)
from test_sheet_ops import Markup, content
from test_sheet_precision import VisibleText, table_rows, tagged

from prechips.findings import Finding
from prechips.inputs import Bundle, load_bundle
from prechips.rules.coordinates import row_id
from prechips.rules.resolution import LENGTH_TOLERANCE_MM
from prechips.sheet import _Traveler


def text(html):
    visible = "".join(" " if part == "|" else part for part in VisibleText(html).parts)
    return " ".join(visible.split())


def coordinate_tables(html):
    markup = Markup(html)
    (owner,) = markup.find("contour")
    assert owner["attrs"]["data-page-context"].startswith("S1 op 20 —")
    return markup, owner, markup.find("coords", owner)


def chain_captions(markup, owner, table):
    """Read the screen introduction and its continuation-header mirror separately."""
    (intro,) = markup.find("table-intro", owner)
    (context,) = markup.find("table-context", table)
    siblings = [node for node in markup.nodes if node["parent"] is table["parent"]]
    assert intro["tag"] == "p" and siblings[siblings.index(table) - 1] is intro
    assert context["tag"] == "tr" and context["parent"]["tag"] == "thead"
    assert context["parent"]["parent"] is table
    captions = [" ".join(content(node).split()) for node in (intro, context)]
    assert captions[0] == captions[1], "the continuation header must mirror the introduction"
    assert all(not re.search(r"\.\s*[.;]", caption) for caption in captions)
    # Account for both legitimate copies without hiding any extra end instruction.
    for phrase in ("starts at ", "stops at ", "not for this breakout"):
        assert content(owner).count(phrase) == sum(caption.count(phrase) for caption in captions)
    return captions


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


def traveler(tmp_path, operations, numbers=None, manual=None, machine="mill", units="mm"):
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
            "units": units,
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
    scale = 25.4 if units == "in" else 1.0
    findings = []
    waypoints = []
    if numbers is not None:
        findings.append(Finding("coordinates", "S1", "pass", numbers, [], ""))
        for table_name in ("arc_table", "line_table"):
            for table in numbers.get(table_name, []):
                rows = table.get("rows", []) if table_name == "arc_table" else table["dro_xy"]
                for index, row in enumerate(rows):
                    point = row.get("dro_xy") if table_name == "arc_table" else row
                    waypoints.append(
                        {
                            "op": str(table["op"]),
                            "label": f"P{len(waypoints) + 1}",
                            "xy": [value * scale for value in point],
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
    assert "leaves at most 0.420 mm for the file" in rough_context and "cap 0.5 mm" in rough_context
    # The stock clause has a subject, and the caption keeps exactly one terminal period.
    assert (
        "one handwheel axis per row; this leaves at most 0.420 mm for the file (cap 0.5 mm)"
        in rough_context
    )
    assert ", leaves at most" not in rough_context
    for caption in (rough_context, join_context):
        assert caption.endswith(".") and not re.search(r"\.\s*[.;]", caption)
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
    sentence = content(breakout)
    assert "; this leaves at most 0.420 mm for the file (cap 0.5 mm)." in sentence
    assert sentence.count("leaves at most") == 1 and sentence.endswith(" mm).")
    assert not re.search(r"\.\s*[.;]", sentence), "one terminal period"


@pytest.mark.parametrize("kind", ["arc_table", "line_table"])
@pytest.mark.parametrize(
    "dropped_ends", [[True, False], [False, True], [True, True], [False, False]]
)
@pytest.mark.parametrize("labelled", [False, True])
def test_excluded_end_holes_dispose_uncleared_stock_without_synthetic_clip_points(
    tmp_path, kind, dropped_ends, labelled
):
    table = arc_record("chain_drill")
    table.update(
        drill_dia_mm=1,
        pitch_mm=1.5,
        break_out="chisel the webs out along the hole centres",
        dropped_ends=dropped_ends,
    )
    if kind == "arc_table":
        table["dropped_rows"] = 2
    else:
        points = [row["dro_xy"] for row in table.pop("rows")]
        table.update(setup_xy=points, dro_xy=points, side="west", dropped_points=2)
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        {kind: [table]},
    )
    if not labelled:
        sheet.report["renders"]["S1"]["scene"]["waypoints"] = []

    html = sheet.contours(setup, {("tools", "cutter"): "1 mm drill"})
    printed = text(html)
    markup, owner, tables = coordinate_tables(html)
    (coordinate_table,) = tables
    rows = table_rows(markup, coordinate_table)

    assert len(rows) == 3, "dropped endpoints must not add interpolated drill positions"
    for caption in chain_captions(markup, owner, coordinate_table):
        assert caption.count("starts at ") == int(dropped_ends[0])
        assert caption.count("stops at ") == int(dropped_ends[1])
        if dropped_ends[0]:
            assert f"starts at {'P1' if labelled else 'hole #1'}" in caption
        if dropped_ends[1]:
            assert f"stops at {'P3' if labelled else 'hole #3'}" in caption
        assert ("outside this op's area" in caption) is any(dropped_ends)
        assert caption.count("not for this breakout") == int(any(dropped_ends))
    assert "leaves at most 0.420 mm for the file" in printed
    assert "clipped" not in printed, "whole excluded holes are not newly clipped hole centres"


@pytest.mark.parametrize("kind", ["arc_table", "line_table"])
@pytest.mark.parametrize("units", ["mm", "in"])
def test_single_retained_chain_hole_has_no_pitch_or_web_breakout(tmp_path, kind, units):
    scale = 25.4 if units == "in" else 1.0
    point = [0.25, -0.5]
    table = arc_record("chain_drill")
    table.update(
        kernel_clip=True,
        regeneration="true_curve",
        dropped_ends=[True, True],
        drill_dia_mm=1,
        pitch_mm=1.5,
        break_out="chisel the webs out along the hole centres",
    )
    if kind == "arc_table":
        table["rows"] = [{"dro_xy": point, "clipped_at": "stock_removal_bounds"}]
    else:
        table.pop("rows")
        table.update(
            setup_xy=[point],
            dro_xy=[point],
            clipped_at=["stock_removal_bounds"],
            side="west",
        )
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        {kind: [table]},
        units=units,
    )
    sheet.report["renders"]["S1"]["scene"]["waypoints"] = [
        {
            "op": "20",
            "label": "P5",
            "xy": [value * scale for value in point],
            "rows": [row_id("S1:20", kind, table, 4)],
        }
    ]

    html = sheet.contours(setup, {("tools", "cutter"): "1 mm drill"})
    printed = text(html)
    markup, _, tables = coordinate_tables(html)
    (coordinate_table,) = tables
    (row,) = table_rows(markup, coordinate_table)

    assert row[:2] == ["1", "P5"]
    assert [float(value) for value in row[-2:]] == pytest.approx(point)
    assert "Single retained hole" in printed and "drill Ø1 mm" in printed
    # The stock sentence names what leaves it and closes with exactly one period.
    assert "Drilling leaves at most 0.420 mm for the file (cap 0.5 mm)." in printed
    assert "Leaves at most" not in printed and ".." not in printed
    assert printed.count("leaves at most") == 1
    assert (
        "retained hole P5: stock beyond its bounded ends is outside this op's area "
        "and not cleared by drilling."
    ) in printed
    assert not re.search(r"\b(?:pitch|chisel|webs?|breakout)\b|break-out", printed, re.I)
    assert "starts at " not in printed and "stops at " not in printed


@pytest.mark.parametrize("flags", [[True, False], [False, True], [True, True], [False, False]])
def test_singleton_bound_disposition_never_implies_a_web_breakout(flags):
    table = {"method": "chain_drill", "dropped_ends": flags}

    note = _Traveler.clip(table, [], [["P5"]])

    assert ("retained hole P5" in note) is any(flags)
    assert ("not cleared by drilling" in note) is any(flags)
    assert not note.endswith("."), "the containing caption supplies its terminal period"
    assert "starts at " not in note and "stops at " not in note
    assert "breakout" not in note
    if any(flags):
        end = "end" if sum(flags) == 1 else "ends"
        assert f"stock beyond its bounded {end} is outside this op's area" in note


@pytest.mark.parametrize("kind", ["arc_table", "line_table"])
@pytest.mark.parametrize("units", ["mm", "in"])
def test_bounded_65_hole_chain_names_only_its_actual_first_and_last_holes(tmp_path, kind, units):
    scale = 25.4 if units == "in" else 1.0
    points_mm = [[float(index), index * (64 - index) / 100] for index in range(65)]
    points = [[value / scale for value in point] for point in points_mm]
    table = arc_record("chain_drill")
    table.update(
        kernel_clip=True,
        regeneration="true_curve",
        dropped_ends=[True, True],
        drill_dia_mm=1,
        pitch_mm=1.5,
        break_out="chisel the webs out along the hole centres",
    )
    markers = ["stock_removal_bounds"] * 65
    if kind == "arc_table":
        table["rows"] = [
            {"dro_xy": point, "clipped_at": marker}
            for point, marker in zip(points, markers, strict=True)
        ]
    else:
        table.pop("rows")
        table.update(setup_xy=points, dro_xy=points, clipped_at=markers, side="west")
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        {kind: [table]},
        units=units,
    )
    sheet.report["renders"]["S1"]["scene"]["waypoints"] = [
        {
            "op": "20",
            "label": label,
            "xy": points_mm[index],
            "rows": [row_id("S1:20", kind, table, index + 1)],
        }
        for index, label in ((0, "P4"), (32, "P5"), (64, "P6"))
    ]

    html = sheet.contours(setup, {("tools", "cutter"): "1 mm drill"})
    markup, owner, tables = coordinate_tables(html)
    (coordinate_table,) = tables
    rows = table_rows(markup, coordinate_table)

    assert len(rows) == 65
    assert [rows[index][1] for index in (0, 32, 64)] == ["P4", "P5", "P6"]
    for caption in chain_captions(markup, owner, coordinate_table):
        assert caption.count("starts at ") == 1
        assert caption.count("stops at ") == 1
        assert "starts at P4 and stops at P6" in caption
        assert "stock beyond them is outside this op's area, not for this breakout." in caption
        assert "stops at row" not in caption and "starts at row" not in caption
        assert "P5" not in caption, "an interior hole must not become a fragment breakpoint"


def test_fully_retained_regenerated_chain_prints_no_end_stops_at_its_junctions(tmp_path):
    # A bounded op whose box covers the whole chain: the kernel regenerates every arc and
    # join hole (each carrying the clip marker as provenance) and drops none. The arc and
    # both joins continue through their shared holes, so no caption may say the chain
    # starts or stops at a bound, or that stock beyond a hole is outside this op.
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    clipped = synthetic_join_clip(
        bundle, requested, lambda table: range(len(table["rows"])), regenerated=True
    )
    marker = clipped.kernel["ops"]["S1:20"]["checkpoint_clips"]["clipped_at"]
    row = joined_chain_finding(clipped)
    assert row.status == "pass", row.sentence
    tables = [
        (kind, table)
        for kind in ("arc_table", "line_table")
        for table in row.numbers[kind]
        if table["op"] == 20
    ]
    arc_ends, line_ends = set(), set()
    for kind, table in tables:
        assert table["regeneration"] == "true_curve" and "fragment" not in table
        assert table["dropped_ends"] == [False, False]
        if kind == "arc_table":
            points = [item["dro_xy"] for item in table["rows"]]
            markers = [item["clipped_at"] for item in table["rows"]]
        else:
            points, markers = table["dro_xy"], table["clipped_at"]
        assert len(markers) == len(points) > 1 and all(item == marker for item in markers)
        (arc_ends if kind == "arc_table" else line_ends).update(
            tuple(points[index]) for index in (0, -1)
        )
    assert arc_ends and arc_ends <= line_ends, "the arc continues into a join at each end"

    setup = clipped.plan["setups"][0]
    html = _Traveler(clipped, [row], {}, None).contours(
        setup, {("tools", "drill"): f"{JOIN_DRILL} mm drill"}
    )
    printed = text(html)
    markup, _, printed_tables = coordinate_tables(html)
    assert len(printed_tables) == len(tables) >= 2
    assert "STOP" not in printed
    for coordinate_table in printed_tables:
        (context,) = markup.find("table-context", coordinate_table)
        caption = " ".join(content(context).split())
        assert caption.startswith("Chain ") and "drill Ø0.5 mm" in caption
        assert "every hole outside the finished outline" in caption
        assert caption.endswith(".") and not re.search(r"\.\s*[.;]", caption)
        for phrase in (
            "starts at ",
            "stops at ",
            "outside this op's area",
            "not for this breakout",
            "retained hole",
            "stock beyond",
            "piece ",
        ):
            assert phrase not in caption, caption
    assert "outside this op's area" not in printed and "not cleared by drilling" not in printed
    assert printed.count("After drilling, ") == len(tables)
    assert "; this leaves at most " in printed and ".." not in printed


@pytest.mark.parametrize("flags", [[True, False], [False, True], [True, True], [False, False]])
def test_legacy_chain_clip_markers_name_only_the_corresponding_end_not_interior_holes(flags):
    # A chain the kernel clipped from named rows (no regeneration) still reads its end
    # markers; an interior marker never turns a hole into a break point.
    table = {"method": "chain_drill", "dropped_ends": [False, False]}
    rows = [["P4"], ["P5"], ["P6"]]
    marker = "stock_removal_bounds"
    markers = [marker if flags[0] else None, marker, marker if flags[1] else None]

    note = _Traveler.clip(table, markers, rows)

    assert note.count("starts at ") == int(flags[0])
    assert note.count("stops at ") == int(flags[1])
    assert ("starts at P4" in note) is flags[0]
    assert ("stops at P6" in note) is flags[1]
    assert "P5" not in note
    assert note.count("not for this breakout") == int(any(flags))


@pytest.mark.parametrize(
    "dropped_ends", [[True, False], [False, True], [True, True], [False, False]]
)
def test_regenerated_chain_end_clauses_follow_dropped_ends_not_row_markers(dropped_ends):
    # Every regenerated true-curve hole carries the clip marker as provenance; only the
    # explicit dropped_ends say whether an actual end stops at the bound.
    table = {
        "method": "chain_drill",
        "kernel_clip": True,
        "regeneration": "true_curve",
        "dropped_ends": dropped_ends,
    }
    rows = [["P4"], ["P5"], ["P6"]]

    note = _Traveler.clip(table, ["stock_removal_bounds"] * 3, rows)

    assert note.count("starts at ") == int(dropped_ends[0])
    assert note.count("stops at ") == int(dropped_ends[1])
    assert ("starts at P4" in note) is dropped_ends[0]
    assert ("stops at P6" in note) is dropped_ends[1]
    assert "P5" not in note
    assert ("outside this op's area" in note) is any(dropped_ends)
    assert note.count("not for this breakout") == int(any(dropped_ends))
    if not any(dropped_ends):
        assert note == "", "a fully retained chain adds no end clause"


@pytest.mark.parametrize(
    ("fragment", "dropped_ends", "start", "stop"),
    [
        ([1, 3], [False, False], False, True),
        ([2, 3], [False, False], True, True),
        ([3, 3], [False, False], True, False),
        ([1, 3], [True, False], True, True),
        ([3, 3], [False, True], True, True),
    ],
)
def test_split_chain_names_only_real_fragment_break_ends(fragment, dropped_ends, start, stop):
    table = {
        "method": "chain_drill",
        "fragment": fragment,
        "dropped_ends": dropped_ends,
    }
    rows = [["P4"], ["P5"], ["P6"]]

    note = _Traveler.clip(table, [True, True, True], rows)

    assert note.count("starts at ") == int(start)
    assert note.count("stops at ") == int(stop)
    assert ("starts at P4" in note) is start
    assert ("stops at P6" in note) is stop
    assert "P5" not in note
    assert f"piece {fragment[0]} of {fragment[1]}: no cut links the pieces" in note
    assert "stock between them is not cleared by this op" in note


@pytest.mark.parametrize("kind", ["arc_table", "line_table"])
@pytest.mark.parametrize("removed", [(0,), (0, 2), (0, 2, 8)])
@pytest.mark.parametrize("units", ["mm", "in"])
def test_clipped_hole_labels_follow_geometry_not_stale_original_row_ids(
    tmp_path, kind, removed, units
):
    scale = 25.4 if units == "in" else 1.0
    original_mm = [
        [-6, 0],
        [-5, 1],
        [-4, 2],
        [-2, 3],
        [0, 4],
        [2, 3],
        [4, 2],
        [5, 1],
        [6, 0],
    ]
    original = [[value / scale for value in point] for point in original_mm]
    kept = [index for index in range(len(original)) if index not in removed]
    table = {
        "op": 20,
        "method": "chain_drill",
        "stage": "rough",
        "side": "west",
        "dro_tip_z": -2,
        "drill_dia_mm": 1,
        "pitch_mm": 1.5,
        "break_out": "chisel the webs out along the hole centres",
        "stock_left_mm": 0.4,
        "stock_cap_mm": 0.5,
    }
    if kind == "arc_table":
        table.update(
            rows=[{"dro_xy": point} for point in original],
            centre_setup_xy=[0, 0],
            cutter_centre_radius_mm=6,
        )
        clipped = {**table, "rows": [table["rows"][index] for index in kept]}
    else:
        table.update(setup_xy=original, dro_xy=original)
        clipped = {
            **table,
            "setup_xy": [original[index] for index in kept],
            "dro_xy": [original[index] for index in kept],
        }
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        {kind: [clipped]},
        units=units,
    )
    # Native pictures keep original sparse row provenance after clipping changes both
    # the first hole and the row index of the actual arc midpoint.
    sheet.report["renders"]["S1"]["scene"]["waypoints"] = [
        {
            "op": "20",
            "label": label,
            "xy": original_mm[index],
            "rows": [row_id("S1:20", kind, table, index)],
        }
        for index, label in ((0, "P4"), (4, "P5"), (8, "P6"))
    ]

    html = sheet.contours(setup, {("tools", "cutter"): "1 mm drill"})
    markup, _, tables = coordinate_tables(html)
    (printed,) = tables
    rows = table_rows(markup, printed)

    assert len(rows) == len(kept), "labels must not introduce a replacement hole"
    labels = [row[1] for row in rows]
    assert labels == ["P5" if index == 4 else "P6" if index == 8 else "" for index in kept]
    assert "P4" not in text(html), "an excluded endpoint must not alias the first retained hole"
    assert labels[kept.index(4)] == "P5", "the centre label belongs on the actual centre hole"
    assert ("P6" in labels) is (8 in kept)


@pytest.mark.parametrize("units", ["mm", "in"])
def test_waypoint_matching_uses_nearest_geometry_and_physical_length_tolerance(tmp_path, units):
    sheet, _ = traveler(tmp_path, [], units=units)
    scale = 25.4 if units == "in" else 1.0
    target = [2.0, -3.0]
    point = [value / scale for value in target]
    row = "stale row 0"
    waypoints = [
        {"op": "30", "label": "other op", "xy": target, "rows": [row]},
        {"op": "20", "label": "index only", "rows": [row]},
        {"op": "20", "label": "wrong hole", "xy": [2.01, -3.0], "rows": [row]},
        {
            "op": "20",
            "label": "farther",
            "xy": [2 + LENGTH_TOLERANCE_MM * 0.75, -3],
            "rows": [row],
        },
        {
            "op": "20",
            "label": "nearest",
            "xy": [2 + LENGTH_TOLERANCE_MM * 0.25, -3],
            "rows": ["original row 4"],
        },
    ]

    assert sheet.waypoint(waypoints, 20, point, row) == "nearest"
    outside = [{**waypoints[-1], "xy": [2 + LENGTH_TOLERANCE_MM * 2, -3]}]
    assert sheet.waypoint(outside, 20, point, row) == ""
    assert sheet.waypoint(waypoints, 20, ["unknown", -3], row) == ""
    assert sheet.waypoint(waypoints, 20, None, row) == ""
    boundary = [{"op": "20", "label": "at tolerance", "xy": [LENGTH_TOLERANCE_MM, 0]}]
    assert sheet.waypoint(boundary, 20, [0, 0], row) == "at tolerance"


def test_common_points_keep_colocated_labels_and_legacy_geometry_lookup(tmp_path):
    sheet, _ = traveler(tmp_path, [])
    waypoints = [
        {"op": "20", "label": "P1", "xy": [2, -3], "rows": ["arc row"]},
        {"op": "20", "label": "P2", "xy": [2, -3], "rows": ["join row"]},
        {"op": "30", "label": "P3", "xz": [4, -5]},
    ]

    assert sheet.waypoint(waypoints, 20, [2, -3], "arc row") == "P1"
    assert sheet.waypoint(waypoints, 20, [2, -3], "join row") == "P2"
    assert sheet.waypoint(waypoints, 20, [2, -3]) == "P1"
    assert sheet.waypoint(waypoints, 30, [4, -5]) == "P3"


@pytest.mark.parametrize("recut_by", [None, "S1:30"])
def test_chain_drill_straight_joins_keep_checkpoints_clips_and_stock(tmp_path, recut_by):
    line = {
        "method": "chain_drill",
        "op": 20,
        "stage": "rough",
        "side": "west",
        "setup_xy": [[12.8, 1.5], [12.8, 4]],
        "model_xy": [[12.8, 1.5], [12.8, 4]],
        "dro_xy": [[12.8, 1.5], [12.8, 4]],
        "dro_tip_z": -2.125,
        "drill_dia_mm": 2,
        "pitch_mm": 2.5,
        "hole_clear_mm": 0.2,
        "stock_left_mm": 1.2,
        "stock_cap_mm": 1.5,
        "break_out": "chisel the webs out along the hole line",
        "overshoot": [True, False],
        "clipped_at": [True, True],
        "fragment": [1, 2],
    }
    if recut_by:
        line["recut_by"] = recut_by
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        {
            "line_table": [line],
            "profiles": [
                {
                    "op": 20,
                    "contour": {"method": "chain_drill"},
                    "cutter_centre": [[99, 88]],
                }
            ],
        },
    )
    key = row_id("S1:20", "line_table", line, 0)
    sheet.records[("accessibility", "S1:20")] = {"checkpoint_overshoot_ok": [key]}
    html = sheet.contours(setup, {("tools", "cutter"): "2 mm drill"})
    markup, owner, tables = coordinate_tables(html)
    (table,) = tables
    assert headers(markup, table) == ["hole #", "P", "", "X", "Y"]
    rows = table_rows(markup, table)
    assert rows[0][:2] == ["1", "P1"]
    assert rows[0][-2:] == ["12.800", "1.500"]
    assert rows[0][2], "proven overshoot must retain its annotation"
    assert rows[1] == ["2", "P2", "", "12.800", "4.000"]
    printed = text(html)
    assert "99.000" not in printed, "join-only chain must not print a generic path too"
    assert "Chain drill straight joins" in printed
    assert "drill Ø2 mm" in printed and "pitch 2.5 mm" in printed
    assert "every hole outside the finished outline" in printed
    assert "starts at P1 and stops at P2" in printed
    assert "piece 1 of 2: no cut links the pieces" in printed
    assert "Z -2.125" in printed
    assert "handwheel" not in printed and "stair" not in printed
    assert "chisel the webs out along the hole line" in printed
    assert "leaves at most 1.200 mm for " + (recut_by or "the file") in printed
    assert ("cap 1.5 mm" in printed) is (recut_by is None)
    # An unproved coordinate flag alone must not label a reposition as safe overshoot.
    sheet.records[("accessibility", "S1:20")] = {"checkpoint_overshoot_ok": []}
    unproved = sheet.contours(setup, {("tools", "cutter"): "2 mm drill"})
    unproved_markup, _, unproved_tables = coordinate_tables(unproved)
    assert headers(unproved_markup, unproved_tables[0]) == ["hole #", "P", "X", "Y"]
    assert table_rows(unproved_markup, unproved_tables[0])[0] == ["1", "P1", "12.800", "1.500"]


@pytest.mark.parametrize("method", ["stairs", "chords"])
def test_join_only_milled_tables_never_reprint_the_unsnapped_generic_profile(tmp_path, method):
    raw = [[12.8004, 1.5004], [12.8004, 4.0004]]
    line = {
        "method": method,
        "op": 20,
        "stage": "rough",
        "side": "west",
        "setup_xy": raw,
        "dro_xy": [[12.8, 1.5], [12.8, 4]],
        "dro_tip_z": -2.125,
    }
    if method == "stairs":
        line.update(jog=[None, "Y"], stair_cusp_mm=0.1)
    sheet, setup = traveler(
        tmp_path,
        [{"op": 20, "do": "rough_profile", "feature": "arc", "tool": "cutter"}],
        {
            "line_table": [line],
            "profiles": [{"op": 20, "contour": {"method": method}, "cutter_centre": raw}],
        },
    )

    html = sheet.contours(setup, {("tools", "cutter"): "6 mm endmill"})
    markup, _, tables = coordinate_tables(html)
    (table,) = tables
    expected = [["1", "P1", "12.800", "1.500"], ["2", "P2", "12.800", "4.000"]]
    if method == "stairs":
        expected[0].append("")
        expected[1].append("Y")
    assert table_rows(markup, table) == expected
    printed = text(html)
    assert "Straight joins on the west side" in printed
    assert "Cutter-centre checkpoints" not in printed
    assert ("one handwheel axis per row" in printed) is (method == "stairs")
    no_programming(html)


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
