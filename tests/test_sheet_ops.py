"""Operation-sheet wording a machinist acts on: printed bands and index directions."""

import re

import pytest

from prechips.sheet import _Traveler


def bare(precision):
    sheet = _Traveler.__new__(_Traveler)
    sheet.precision = lambda feature, dimension: precision
    return sheet


@pytest.mark.parametrize(
    ("band", "precision", "printed"),
    [
        ([1.994, 2.094], 2, "2.00–2.09"),
        ([12.2555, 12.2855], 3, "12.256–12.285"),
        ([7.0565, 7.1065], 3, "7.057–7.106"),
        ([6.33, 6.35], 3, "6.330–6.350"),
    ],
)
def test_printed_band_never_wider_than_the_drawing(band, precision, printed):
    assert bare(precision).band(band, None, None) == printed


def test_band_narrower_than_its_precision_prints_declared_limits():
    assert bare(2).band([3.001, 3.004], None, None) == "3.001–3.004"


@pytest.mark.parametrize(
    ("clock", "z", "words"),
    [
        (12.5, [1.0, 0.0, 0.0], "counterclockwise viewed from the free end of the work"),
        (-12.5, [1.0, 0.0, 0.0], "clockwise viewed from the free end of the work"),
    ],
)
def test_index_direction_follows_jaw_clock_sign(clock, z, words):
    sense = _Traveler.index_sense({"jaw_clock_deg": clock, "pose": {"z": z}})
    assert sense.startswith(words)
    assert "from setup +X" in sense


def test_index_direction_names_the_viewing_end_from_the_chuck_axis():
    sense = _Traveler.index_sense({"jaw_clock_deg": 5.0, "pose": {"z": [0.0, 0.0, -1.0]}})
    assert "from setup −Z" in sense


def test_index_direction_unknown_without_a_clock_angle():
    assert _Traveler.index_sense({"pose": {"z": [1.0, 0.0, 0.0]}}).startswith("?")


def test_blank_line_paragraphs_print_as_numbered_steps():
    sheet = bare(2)
    sheet.bench = lambda text, setup=None: text
    method = "Seat datum B.\nClamp lightly.\n\nPin bore A.\n\n  Read the rod pin.  "
    assert sheet.steps(method) == (
        "(1) Seat datum B. Clamp lightly. (2) Pin bore A. (3) Read the rod pin."
    )
    assert sheet.steps("One paragraph.") == "One paragraph."


def shop(records, kind="mill"):
    """A bare sheet over ``records`` printing millimetres at three decimals."""
    sheet = bare(3)
    sheet.records = records
    sheet.report = {}
    sheet.bench = lambda text, setup=None: text
    sheet.machine = lambda setup: {"kind": kind}
    sheet.operative = lambda v: (
        f"{v:.3f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "?"
    )
    return sheet


SPOT = {"id": "S1", "ops": [{"op": 60, "do": "spot", "feature": "hole", "tool": "c"}]}


def reach_records(top="unset", projection=27.0, hits=0):
    record = {
        "reach_depth_mm": 4.97175,  # the kernel's own, from its unrounded tip and lift
        "flute_len_mm": 1.9,
        "oal_mm": 47.6,
        "projection_mm": projection,
        "holder_wall_hits": hits,
    }
    if top != "unset":
        record["reach_top_z_mm"] = top
    endpoint = {"setup": "S1", "op": 60, "dro_entry_z": 0.0, "dro_tip_z": -0.5}
    return {("reach", "S1:60"): record, ("blind_depth", "hole"): {"endpoints": [endpoint]}}


def clearance_sheet(records):
    # Op 60's DRO tip as the coordinates rule checked it.
    records = {("coordinates", "S1"): {"operations": [{"op": 60, "dro_to_z": -0.5}]}, **records}
    sheet = shop(records)
    # The stock top prints as its own DRO surface Z; here the grid leaves it unchanged.
    sheet.surface_z = lambda setup, value, *args, **kwargs: value
    return sheet


def headroom(margin=None, tip_above_jaws=None, jaw_top_z=None):
    numbers = {"stacks": [{"op": 60, "margin_mm": margin}] if margin is not None else []}
    if tip_above_jaws is not None:
        numbers["cut_tip_above_jaws_mm"] = {"60": tip_above_jaws}
        numbers["jaw_obstruction"] = {"jaw_top_z": jaw_top_z}
    return numbers


def clearance_row(records, numbers):
    rows = clearance_sheet(records).clearance_rows(SPOT, numbers, {("c", None): "T4"})
    assert len(rows) == 1, rows
    return rows[0]


def test_the_clearance_row_names_the_smallest_clearance_of_the_op():
    # Headroom 40 spare, holder face 22.03 above the stock top: the holder face is closest.
    ops, tool, obstacle, value, action = clearance_row(reach_records(top=4.47), headroom(40.0))
    assert (ops, tool, value, action) == ("60", "T4", "22.030", "")
    assert "holder face" in obstacle and "4.470" in obstacle
    # Jaw tops 1.2 below the tip win over both, and ask for a hand-fed approach.
    numbers = headroom(40.0, tip_above_jaws=1.2, jaw_top_z=-1.7)
    _, _, obstacle, value, action = clearance_row(reach_records(top=4.47), numbers)
    assert "jaw" in obstacle and value == "1.200" and action.startswith("hand feed")


def test_a_declared_reach_clearance_competes_for_the_closest_obstacle():
    records = reach_records(top=4.47)
    records[("reach", "S1:60")]["clearances"] = [
        {"part": "holder", "obstacle": "crown", "mm": -11.2}
    ]
    _, _, obstacle, value, action = clearance_row(records, headroom(40.0))
    assert obstacle == "holder to crown" and value == "-11.200"
    assert action.startswith("STOP")


def test_a_tip_below_the_jaw_tops_is_a_stop():
    numbers = headroom(40.0, tip_above_jaws=-0.4, jaw_top_z=0.0)
    _, _, obstacle, value, action = clearance_row(reach_records(top="not_applicable"), numbers)
    assert "jaw" in obstacle and value == "-0.500" and action.startswith("STOP")


@pytest.mark.parametrize(
    ("records", "check"),
    [
        (reach_records(top=4.47, projection="unknown"), "holder face"),
        (reach_records(top=4.47, hits="unknown"), "holder clearance of the walls not proven"),
    ],
)
def test_an_unknown_clearance_is_an_action_to_check_at_the_machine(records, check):
    _, _, _, _, action = clearance_row(records, headroom(40.0))
    assert check in action and "check at the machine" in action


def test_a_holder_below_the_stock_top_with_walls_proven_clear_is_not_a_clearance():
    _, _, obstacle, value, action = clearance_row(reach_records(top=4.47, projection=3.0), {})
    assert value == "—" and "1.970 below" in obstacle and "clear of the walls" in obstacle
    assert action == ""


def test_ops_with_one_tool_obstacle_clearance_and_action_share_a_row():
    records = reach_records(top="not_applicable")
    setup = {"id": "S1", "ops": [{**SPOT["ops"][0]}, {**SPOT["ops"][0], "op": 70}]}
    numbers = {"stacks": [{"op": 60, "margin_mm": 5.0}, {"op": 70, "margin_mm": 5.0}]}
    rows = clearance_sheet(records).clearance_rows(setup, numbers, {("c", None): "T4"})
    assert [row[0] for row in rows] == ["60, 70"]


def contour_records(levels):
    operation = {"op": 10, "dro_to_z": -0.6}
    if levels is not None:
        operation["z_levels"] = {
            "dro_start_z": 0.0,
            "dro_to_z": -0.6,
            "doc_mm": 0.25,
            "levels": levels,
            "count": len(levels),
        }
    profile = {
        "op": 10,
        "stage": "finish",
        "dro_to_z": -0.6,
        "cutter_centre": [[[-13.765, 1.0], [13.765, 1.0]], [[-13.765, 2.0], [13.765, 2.0]]],
        "raster": {
            "passes": 2,
            "step_mm": 1.0,
            "lift_z": 5.0,
            "open_side": "-y",
            "run_axis": "x",
            "area_ends": [-9.0, 9.0],
            "ends": [-13.765, 13.765],
            "clearance_mm": 4.76,
            "entry_pass": 1.0,
        },
    }
    return {("coordinates", "S1"): {"operations": [operation], "profiles": [profile]}}


POCKET = {"id": "S1", "ops": [{"op": 10, "do": "pocket", "feature": "ear", "tool": "c"}]}


def test_a_stepped_contour_lists_its_levels_once_in_the_heading():
    html = shop(contour_records([-0.25, -0.5, -0.6])).contours(POCKET, {"c": "T1"})
    assert "S1 op 10 — ear · T1 · Z -0.250, -0.500, -0.600" in html
    assert "3 depth levels" in html
    # The repeat row prints only on a continued page; the first page shows the levels once.
    first_page = re.sub(r'<tr class="repeat">.*?</tr>', "", html)
    assert first_page.count("-0.250") == first_page.count("-0.500") == 1


def test_a_single_level_contour_heading_keeps_its_one_z():
    for levels in (None, [-0.6]):
        html = shop(contour_records(levels)).contours(POCKET, {"c": "T1"})
        assert "S1 op 10 — ear · T1 · Z -0.600" in html
        assert "depth levels" not in html


@pytest.mark.parametrize(
    ("box", "claim"),
    [
        ([-9.0, 9.0], "clear air"),  # ends a cutter radius past the stock
        ([-160.0, 160.0], "walled"),  # ends inside the cleared field: plunge in material
    ],
)
def test_raster_pass_ends_are_classified_against_the_op_stock_box(box, claim):
    pocket = {"id": "S1", "ops": [{**POCKET["ops"][0], "stock_removal_bounds": {"x": box}}]}
    html = shop(contour_records(None)).contours(pocket, {"c": "T1"})
    assert "pass ends X -13.765 / 13.765: both " in html
    other = {"clear air": "walled", "walled": "clear air,"}[claim]
    assert claim in html and other not in html


def test_raster_pass_ends_without_a_stock_box_make_no_claim():
    html = shop(contour_records(None)).contours(POCKET, {"c": "T1"})
    assert "pass ends X -13.765 / 13.765" in html
    assert "clear air, a cutter" not in html and "walled" not in html


def test_a_contour_table_repeats_its_op_on_continued_pages_and_never_wraps_a_number():
    html = shop(contour_records(None)).contours(POCKET, {"c": "T1"})
    assert '<tr class="repeat"><th colspan=' in html
    repeat = html.split('<tr class="repeat">', 1)[1].split("</tr>", 1)[0]
    assert "op 10" in repeat and "T1" in repeat
    assert '<td class="read num">-13.765</td>' in html or '<td class="num">-13.765</td>' in html


def hole_records(points):
    rows = [{"feature": "rod_hole", "setup": [*p, 0.0], "dro_xy": p} for p in points]
    return {("coordinates", "S2"): {"rows": rows}}


DRILL = {"op": 33, "do": "drill", "feature": "rod_hole"}


def test_a_hole_op_prints_its_tool_axis_on_the_dro_grid():
    sheet = shop(hole_records([[133.065, -8.455]]))
    assert sheet.hole_xy({"id": "S2"}, DRILL) == ["tool axis X 133.065, Y -8.455"]
    # Not a hole op, or a feature at several places: the op row prints no single axis.
    assert sheet.hole_xy({"id": "S2"}, {**DRILL, "do": "pocket"}) == []
    two = shop(hole_records([[1.0, 2.0], [3.0, 4.0]]))
    assert two.hole_xy({"id": "S2"}, DRILL) == []
    unknown = shop(hole_records([["unknown", 2.0]]))
    assert unknown.hole_xy({"id": "S2"}, DRILL) == ["STOP: hole X/Y not set"]
    assert shop(hole_records([[1.0, 2.0]]), "lathe").hole_xy({"id": "S2"}, DRILL) == []


def mapped(records, features, drawing=None, kind="mill"):
    from types import SimpleNamespace

    sheet = shop(records, kind)
    sheet.features = features
    sheet.bundle = SimpleNamespace(features={"features": drawing or {}})
    sheet.feature_name = lambda feature: feature.replace("_", " ")
    sheet.zero_name = lambda setup: f"Setup {setup['id']} zero"
    sheet.surface_z = lambda setup, value, *args, **kwargs: value
    sheet.ops_done = lambda setup, before=None: 0
    return sheet


def rows_of(html):
    from test_sheet_precision import text

    return text(html)


def test_a_lathe_feature_map_keeps_the_drawing_limits_apart_from_the_size_turned_to():
    rows = [
        {"feature": "head", "setup": [21.375, 0.0, z], "x_target_mm": 42.75} for z in (0.0, -95.0)
    ]
    rows.append({"feature": "spigot", "setup": [8.6, 0.0, -23.0], "x_target_mm": 17.2})
    sheet = mapped(
        {("coordinates", "S1"): {"x_display": "diameter", "rows": rows}},
        {"head": {"kind": "cylinder"}, "spigot": {"kind": "cylinder_spigot"}},
        drawing={"head": {"kind": "cylinder", "dia": [42.0, 43.6]}},
        kind="lathe",
    )
    html = sheet.feature_map({"id": "S1", "ops": []})
    head = html.split("<td>head</td>", 1)[1].split("</tr>", 1)[0]
    assert "Ø42.000–43.600" in head and "Ø42.750" in head
    # A process size (a joint spigot) has no drawing limits to print.
    spigot = html.split("<td>spigot</td>", 1)[1].split("</tr>", 1)[0]
    assert "<td>—</td>" in spigot and "Ø17.200" in spigot


def test_a_mill_feature_map_names_the_point_each_row_stands_on_from_the_feature_kind():
    rows = [
        {"feature": "hold_down", "dro": [0.0, -8.2, 0.0]},
        {"feature": "ear_arch", "dro": [0.0, -25.2, 0.0]},
        {"feature": "crank_bore", "dro": [-72.885, 0.0, -21.375]},
    ]
    endpoint = {"setup": "S1", "op": 30, "dro_entry_z": 0.0, "dro_exit_face": -21.375}
    sheet = mapped(
        {
            ("coordinates", "S1"): {"rows": rows},
            ("blind_depth", "crank_bore"): {"endpoints": [endpoint]},
        },
        {
            "hold_down": {"kind": "hole"},
            "ear_arch": {"kind": "pocket", "arc": "upper_semicircle"},
            "crank_bore": {"kind": "bore"},
        },
    )
    setup = {"id": "S1", "ops": [{"op": 30, "do": "ream", "feature": "crank_bore"}]}
    plain = rows_of(sheet.feature_map(setup))
    assert "hold down||hole axis on the Z0 surface||" in plain
    assert "ear arch||arc centre on the Z0 surface||" in plain
    assert "crank bore||hole axis at the exit face||" in plain


def test_an_aimed_target_names_its_offset_and_inspection_but_not_the_authored_reason():
    sheet = mapped({}, {})
    record = {
        "feature": "crank_bore",
        "dro": [-72.885, 0.0, -21.375],
        "nominal_setup": [-72.7, 0.0, -21.375],
        # The aim record coordinates emits: its owner and its value in manifest units.
        "aim": {
            "feature": "crank_bore",
            "shift_mm": -0.185,
            "source": "journal_bore",
            "requirement": "separation",
            "printed_band": [39.34, 39.7],
            "value_mm": 39.517,
            "value": 39.517,
            "reason": "centre the separation band; the gauge reads low",
        },
    }
    note = sheet.aim_note(record)
    assert "X -72.885" in note and "0.185 off the drawing nominal -72.700" in note
    assert "39.340–39.700" in note
    assert "gauge reads low" not in note


def tip_sheet():
    endpoint = {
        "setup": "S1",
        "op": 60,
        "dro_entry_z": 0.0,
        "tip_z": -25.214,
        "dro_tip_z": -25.210,
        "exit_face": "#1/ADVANCED_FACE[2]/NONE",
        "dro_exit_face": -21.375,
        "point_mm": 1.839,
        "exit_mm": 0.5,
    }
    return mapped({("blind_depth", "hole"): {"endpoints": [endpoint]}}, {})


def test_a_breakthrough_note_prints_only_dro_grid_values():
    note = tip_sheet().tip_note(SPOT, SPOT["ops"][0])
    assert "-25.210" in note and "-21.375" in note and "0.500" in note
    # The off-grid exact tip and the point allowance arithmetic stay in the report.
    assert "-25.214" not in note and "1.839" not in note


def transfer_sheet(indicate, kind):
    sheet = mapped({}, {"face_a": {"kind": "face"}, "bore": {"kind": "hole"}})
    sheet.reference = lambda gauge: "dial test indicator"
    return sheet, {"from": "S1", "indicate": indicate, "tool": "dti", "runout_limit_mm": 0.0254}


@pytest.mark.parametrize(
    ("indicate", "moves"),
    [(["face_a"], "work"), (["bore"], "table"), (["face_a", "bore"], "work")],
)
def test_an_alignment_sweep_moves_the_work_and_a_centring_sweep_moves_the_table(indicate, moves):
    sheet, transfer = transfer_sheet(indicate, "mill")
    line = sheet.transfer_line({"id": "S2"}, transfer)
    assert "0.0254" in line
    if moves == "work":
        assert "move the table" not in line and "tap the" in line and "re-clamp" in line
    else:
        assert "move the table" in line and "re-clamp" not in line


def test_a_procedure_authored_as_steps_prints_numbered_with_fields_and_its_calculation():
    from prechips.sheet import _list

    note = shop({}).note(
        "S4 op 50 position Ø",
        [
            "Pin the rod hole; read X at the pin: {X1}",
            "Read Y at the pin: {Y1}",
            "Calculate: position Ø = 2 × √((X1 − 133.067)² + (Y1 + 8.456)²) = {result}",
        ],
    )
    html = _list([note])
    assert html.count("<li>") == 3  # the note, then its two numbered steps
    assert '<ol class="steps"><li>Pin the rod hole; read X at the pin: ' in html
    assert '<span class="field">X1 ____________</span>' in html
    assert '<p class="calc">Calculate: position Ø = 2 × √((X1 − 133.067)² + (Y1 + 8.456)²) = ' in (
        html
    )
    # An authored string keeps printing as before.
    assert shop({}).note("S1 op 10 Ra", "Compare.") == "S1 op 10 Ra: Compare."


@pytest.mark.parametrize(
    ("method", "known"),
    [
        ("Read it.", True),
        (["Seat it.", "Read it."], True),
        (["Seat it.", "unknown"], False),
        (["Seat it.", "  "], False),
        ("unknown", False),
        (None, False),
    ],
)
def test_a_step_list_procedure_is_known_only_when_every_step_is(method, known):
    from prechips.rules.inspection import procedure_known

    assert procedure_known(method) is known


def test_plans_author_inspection_procedures_as_strings_or_step_lists():
    from pydantic import ValidationError

    from prechips.model import Operation

    steps = ["Seat it.", "Calculate: d = {X1}"]
    op = Operation.model_validate(
        {
            "op": 10,
            "do": "inspect",
            "inspection_methods": {"position_dia": steps},
            "inspection_note": steps,
        }
    )
    assert op.model_dump()["inspection_methods"]["position_dia"] == steps
    with pytest.raises(ValidationError):
        Operation.model_validate({"op": 10, "do": "inspect", "inspection_note": []})
