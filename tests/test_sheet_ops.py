"""Operation-sheet wording a machinist acts on: printed bands and index directions."""

import functools
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.sheet import _Traveler

ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"


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


def _hold_facts(hold):
    sheet = bare(2)
    sheet.operative = lambda value: f"{value:.2f}"
    sheet.jaw_front_z = lambda setup: None
    sheet.bench = lambda text, setup=None: text
    return dict(sheet.hold_facts({"id": "S3"}, hold, True))


def test_a_stickout_from_a_measured_fit_up_prints_as_nominal_with_its_setting():
    fit = {"measure": "trial-fit scribe to the plain end", "nominal_mm": 16.83, "add_mm": 8.0}
    facts = _hold_facts({"stickout_mm": 24.83, "stickout_fit": fit})
    assert "stickout mm" not in facts
    assert facts["nominal stickout mm"] == "24.83"
    assert facts["set stickout"] == "measured trial-fit scribe to the plain end + 8.00"


@pytest.mark.parametrize("fit", [None, {}])
def test_a_plain_stickout_prints_as_the_setting(fit):
    hold = {"stickout_mm": 24.83} | ({"stickout_fit": fit} if fit is not None else {})
    facts = _hold_facts(hold)
    assert facts["stickout mm"] == "24.83" and "set stickout" not in facts


def test_a_fit_up_stickout_with_an_unstated_reading_is_not_printed_as_a_setting():
    fit = {"measure": "unknown", "nominal_mm": 16.83, "add_mm": 8.0}
    facts = _hold_facts({"stickout_mm": 24.83, "stickout_fit": fit})
    assert facts["set stickout"].startswith("?")


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
    """A bare sheet over ``records`` printing millimetres at three decimals, with no kernel
    result."""
    sheet = bare(3)
    sheet.records = records
    sheet.report = {}
    sheet.bundle = SimpleNamespace(features={"units": "mm"}, inventory={}, plan={"setups": []})
    sheet.units = "mm"
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


def kernel_stock(box_mm, status="ok"):
    """A bundle whose kernel modelled S1's entry stock as setup-frame box ``box_mm``."""
    return SimpleNamespace(kernel={"status": status, "setups": {"S1": {"stock_bbox_mm": box_mm}}})


def raster_note(bundle, units="mm", removal=None, records=None):
    """The raster note op 10 prints: its passes at Y 1 and 2 run X -13.765 to 13.765 with a
    4.76 cutter radius over the area X -9..9, entering from the open -Y side."""
    sheet = shop(records or contour_records(None))
    sheet.bundle, sheet.units = bundle, units
    op = {**POCKET["ops"][0]}
    if removal is not None:
        op["stock_removal_bounds"] = removal
    html = sheet.contours({"id": "S1", "ops": [op]}, {"c": "T1"})
    return html.split("Raster, ", 1)[1].split("</p>", 1)[0]


# What the sheet may say only on proof: a pass end or pass 1 in air, or a pass in material.
AIR, MATERIAL = re.compile(r"\bair\b|\bclear\b"), re.compile(r"wall|material|plunge")


@pytest.mark.parametrize(
    "removal",
    [
        {"x": [-9.0, 9.0], "y": [5.77, 30.0]},  # the ends stand a radius past what it removes
        {"x": [-160.0, 160.0], "y": [-20.0, 30.0]},  # the ends lie inside what it removes
    ],
)
@pytest.mark.parametrize("bundle", [SimpleNamespace(), kernel_stock(None)])
def test_an_op_removal_box_alone_never_puts_a_raster_end_in_air_or_in_material(removal, bundle):
    # stock_removal_bounds is what the op may remove; stock past it may stand or not.
    note = raster_note(bundle, removal=removal)
    assert "pass ends X -13.765 / 13.765" in note
    assert not AIR.search(note) and not MATERIAL.search(note)


@pytest.mark.parametrize(
    ("units", "box_mm", "air"),
    [
        # A cutter radius 4.76 past the entry stock at both ends and on the open -Y side.
        ("mm", [-9.0, 5.77, -5.0, 9.0, 30.0, 5.0], ["-13.765", "13.765", "pass 1"]),
        # The +X end 0.005 inside the stock, then grazing it exactly: only the -X end.
        ("mm", [-9.0, 5.77, -5.0, 9.01, 30.0, 5.0], ["-13.765", "pass 1"]),
        ("mm", [-9.0, 5.77, -5.0, 9.005, 30.0, 5.0], ["-13.765", "pass 1"]),
        # Pass 1 at Y 1 grazes stock from Y 5.76: it does not enter from air.
        ("mm", [-9.0, 5.76, -5.0, 9.0, 30.0, 5.0], ["-13.765", "13.765"]),
        # Inch plan values against the millimetre kernel box: X ±13.765 in is ±349.631 mm
        # and pass 1 at Y 1 in is Y 25.4 mm, clear of stock from Y 30.2 only that way.
        ("in", [-340.0, 30.2, -5.0, 340.0, 400.0, 5.0], ["-13.765", "13.765", "pass 1"]),
        ("mm", [-340.0, 30.2, -5.0, 340.0, 400.0, 5.0], ["pass 1"]),
        ("in", [-9.0, 5.77, -5.0, 9.0, 30.0, 5.0], ["-13.765", "13.765"]),
        # Unknown plan units prove nothing.
        ("unknown", [-9.0, 5.77, -5.0, 9.0, 30.0, 5.0], []),
    ],
)
def test_raster_ends_are_in_air_only_a_cutter_radius_past_the_kernel_entry_stock(
    units, box_mm, air
):
    note = raster_note(kernel_stock(box_mm), units, removal={"x": [-9.0, 9.0]})
    assert "pass ends X -13.765 / 13.765" in note and not MATERIAL.search(note)
    claimed = [end for end in ("-13.765", "13.765") if re.search(rf"X {end} end|both", note)]
    if "pass 1" in note:
        claimed.append("pass 1")
    assert claimed == air and bool(AIR.search(note)) is bool(air)


@pytest.mark.parametrize(("entry", "air"), [(40.0, True), (34.0, False)])
def test_pass_one_enters_from_air_only_a_cutter_radius_outside_its_open_side(entry, air):
    # Open +Y: pass 1 at Y 40 stands 5.24 above stock ending at Y 30; at Y 34, 0.76 short.
    records = contour_records(None)
    raster = records[("coordinates", "S1")]["profiles"][0]["raster"]
    raster.update(open_side="+y", entry_pass=entry)
    note = raster_note(kernel_stock([-9.0, -30.0, -5.0, 9.0, 30.0, 5.0]), records=records)
    assert ("pass 1" in note) is air


def face_raster(keep_out, stage="finish"):
    """Op 10's face raster as the coordinates producer emits it: a Ø6 cutter over X 0..20,
    Y 0..10 at a 2 stepover from the open -Y side, its passes split around a Ø2 keep-out at
    (10, 5) when ``keep_out``."""
    from prechips.rules.coordinates import _raster

    contour = {"step_mm": 2.0, "open_side": "-y"}
    if keep_out:
        contour["keep_out"] = [{"at": [10.0, 5.0], "dia_mm": 2.0}]
    op = {"op": 10, "do": "face", "contour": contour}
    op["stock_removal_bounds"] = {"x": [0.0, 20.0], "y": [0.0, 10.0]}
    frame = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]}
    frame["z"] = [0.0, 0.0, 1.0]
    order = {"cut_order": "conventional"}
    profile, why = _raster(
        {"frame": "model"}, op, 3.0, 3.0, frame, {"model": frame}, 1, order, 5.0, (0.001, 3), 1.0
    )
    assert profile is not None, why
    return {"op": 10, "stage": stage, "dro_to_z": -0.6, **profile}


def face_notes(box_mm, *profiles):
    records = {("coordinates", "S1"): {"operations": [{"op": 10}], "profiles": list(profiles)}}
    sheet = shop(records)
    sheet.bundle = kernel_stock(box_mm)
    html = sheet.contours(POCKET, {"c": "T1"})
    return [part.split("</p>", 1)[0] for part in html.split("Raster, ")[1:]]


# The universal claim over a raster's passes, and the stock the face op receives.
EVERY, FACE_STOCK = re.compile(r"every pass"), [0.005, 0.0, -1.0, 19.995, 10.0, 1.0]


def wholly_in_stock(point, box, radius=3.0):
    return all(box[i] < point[i] - radius and point[i] + radius < box[i + 3] for i in range(2))


@pytest.mark.parametrize(
    ("keep_out", "box_mm", "every"),
    [
        (False, FACE_STOCK, True),  # every pass starts and ends at X -3 / 23, in air
        (True, FACE_STOCK, False),  # split pieces start and stop inside the stock box
        (True, [0.005, 0.0, -1.0, 2.0, 10.0, 1.0], True),  # every piece's ends past the stock
    ],
)
def test_every_pass_runs_in_and_out_clear_only_when_every_emitted_piece_end_is_proven(
    keep_out, box_mm, every
):
    profile = face_raster(keep_out)
    ends = [point for piece in profile["cutter_centre"] for point in piece]
    inner = sorted({point[0] for point in ends} - {-3.0, 23.0})
    # The keep-out's pieces start and stop between the outer ends; on the full stock some
    # (pass 5 starts at X 13.873, Y 4) stand with the whole cutter inside the stock box.
    assert bool(inner) is keep_out
    assert any(wholly_in_stock(point, box_mm) for point in ends) is (not every)
    (note,) = face_notes(box_mm, profile)
    assert bool(EVERY.search(note)) is every
    # The outer X -3 / 23 ends stay proven in air, and no inner end is named as such.
    assert "both in air" in note and not MATERIAL.search(note)
    assert not any(f"{value:.3f}" in note for value in inner)


def test_a_stage_whose_pieces_prove_less_does_not_share_the_op_raster_claim():
    rough, finish = face_raster(False, "rough"), face_raster(True, "finish")
    notes = face_notes(FACE_STOCK, rough, finish)
    assert len(notes) == 2 and EVERY.search(notes[0])
    # The split finish stage states its own ends without the rough stage's every-pass claim.
    assert "-3.000 / 23.000" in notes[1] and not EVERY.search(notes[1])


@pytest.mark.parametrize(
    "bundle",
    [
        kernel_stock([-9.0, 5.77, -5.0, 9.0, 30.0, 5.0], status="unavailable"),
        kernel_stock([-9.0, 5.77, -5.0, "unknown", 30.0, 5.0]),
        SimpleNamespace(kernel={"status": "ok", "setups": {"S2": {"stock_bbox_mm": [0.0] * 6}}}),
    ],
)
def test_raster_ends_claim_nothing_without_a_modelled_entry_stock(bundle):
    note = raster_note(bundle, removal={"x": [-9.0, 9.0]})
    assert "pass ends X -13.765 / 13.765" in note
    assert not AIR.search(note) and not MATERIAL.search(note)


def outline_note(bundle):
    """Op 10's outline note: rows X -20, 0 and 20 at Y 0 for a 4.76 cutter radius, inside
    its removal box X -9..9 grown by the radius only at X 0."""
    profile = {
        "op": 10,
        "stage": "finish",
        "dro_to_z": -0.6,
        "cutter_radius_mm": 4.76,
        "cutter_centre": [[-20.0, 0.0], [0.0, 0.0], [20.0, 0.0]],
    }
    records = {("coordinates", "S1"): {"operations": [{"op": 10}], "profiles": [profile]}}
    sheet = shop(records)
    sheet.bundle = bundle
    op = {**POCKET["ops"][0], "stock_removal_bounds": {"x": [-9.0, 9.0], "y": [-9.0, 9.0]}}
    html = sheet.contours({"id": "S1", "ops": [op]}, {"c": "T1"})
    return html.split("Cutter-centre checkpoints", 1)[1].split("</p>", 1)[0]


@pytest.mark.parametrize(
    ("bundle", "clear"),
    [
        (SimpleNamespace(), []),  # the removal box alone proves no row outside the stock
        (kernel_stock([-9.0, -9.0, -5.0, 9.0, 9.0, 5.0]), ["row 1", "row 3"]),
        (kernel_stock([-16.0, -9.0, -5.0, 16.0, 9.0, 5.0]), []),  # rows 1 and 3 cut stock
        (kernel_stock([-16.0, -9.0, -5.0, 15.0, 9.0, 5.0]), ["row 3"]),
    ],
)
def test_outline_rows_are_cutter_clearance_only_wholly_outside_the_kernel_entry_stock(
    bundle, clear
):
    note = outline_note(bundle)
    named = re.search(r";\s*([^;]*) stand wholly clear of the stock", note)
    assert (named.group(1).split(", ") if named else []) == clear


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
    turned = [
        {"op": 10, "do": "turn", "feature": "head"},
        {"op": 20, "do": "turn", "feature": "spigot"},
    ]
    html = sheet.feature_map({"id": "S1", "ops": turned})
    head = html.split("<td>head</td>", 1)[1].split("</tr>", 1)[0]
    assert "Ø42.000–43.600" in head and "Ø42.750" in head
    # A process size (a joint spigot) has no drawing limits to print.
    spigot = html.split("<td>spigot</td>", 1)[1].split("</tr>", 1)[0]
    assert "<td>—</td>" in spigot and "Ø17.200" in spigot


@pytest.mark.parametrize(
    ("ops", "listed"),
    [
        # Mic'd as supplied, never cut: no size to turn to, no Z to cut from.
        ([{"op": 5, "do": "inspect", "feature": "shoulder_od"}], False),
        ([], False),
        ([{"op": 10, "do": "turn", "feature": "shoulder_od"}], True),
    ],
)
def test_a_lathe_feature_map_lists_only_surfaces_this_setup_cuts(ops, listed):
    rows = [
        {"feature": "shoulder_od", "setup": [5.0, 0.0, z], "x_target_mm": 10.0} for z in (0, -1.5)
    ]
    rows += [{"feature": "bearing", "setup": [3.2, 0.0, z], "x_target_mm": 6.35} for z in (0, -9)]
    sheet = mapped(
        {("coordinates", "S1"): {"x_display": "diameter", "rows": rows}},
        {"shoulder_od": {"kind": "cylinder"}, "bearing": {"kind": "cylinder"}},
        kind="lathe",
    )
    setup = {"id": "S1", "ops": [*ops, {"op": 20, "do": "finish_turn", "feature": "bearing"}]}
    html = sheet.feature_map(setup)
    assert "<td>bearing</td>" in html
    assert ("<td>shoulder od</td>" in html) is listed


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


@functools.cache
def rocker():
    from prechips.inputs import load_bundle

    return load_bundle(ROCKER)


def through(**row):
    """(a sheet over a through op 60's endpoint as tip_endpoints derives it on the rocker's
    S1 0.005 mm DRO grid, the endpoint, the setup)."""
    from prechips.rules.tip_endpoints import _operative

    bundle = rocker()
    setup = bundle.plan["setups"][0]
    endpoint = {"setup": setup["id"], "op": 60, "entry_z": 0.0, "entry_from": "stock", **row}
    _operative(endpoint, bundle, setup, "top")
    sheet = mapped({("blind_depth", "hole"): {"endpoints": [endpoint]}}, {})
    sheet.bundle = bundle
    return sheet, endpoint, setup


def run_outs(note, endpoint):
    """The run-outs a breakthrough note claims: every number it prints besides the DRO tip
    and exit face, so the off-grid exact tip or the point arithmetic would count too."""
    printed = {f"{endpoint['dro_tip_z']:.3f}", f"{endpoint['dro_exit_face']:.3f}"}
    numbers = re.findall(r"-?\d+\.\d+", note)
    assert printed <= set(numbers)
    return [float(v) for v in numbers if v not in printed]


@pytest.mark.parametrize(
    ("row", "lead", "claimed"),
    [
        # The off-grid exit face rounds up to -10.000 and the tip to -11.335: the full
        # diameter runs 0.494 past the face (0.496 past the printed one), not the 0.5 asked.
        ({"exit_face": -10.002, "point_mm": 0.839, "exit_mm": 0.5}, "point_mm", [0.494]),
        # A reamer's lead: 0.4987 achieved prints 0.498, never rounded up to 0.499.
        ({"exit_face": -10.0013, "lead_mm": 0.3, "exit_mm": 0.5}, "lead_mm", [0.498]),
        # Nothing left past the face: no run-out is claimed.
        ({"exit_face": -10.0, "point_mm": 0.84, "exit_mm": 0.0}, "point_mm", []),
        # The rounded-up tip leaves the full diameter short (the op's STOP): none claimed.
        ({"exit_face": -10.002, "point_mm": 0.839, "exit_mm": 0.003}, "point_mm", []),
    ],
)
def test_a_breakthrough_note_claims_only_the_run_out_the_printed_tip_achieves(row, lead, claimed):
    tip = row["exit_face"] - row[lead] - row["exit_mm"]
    sheet, endpoint, setup = through(**row, tip_z=tip)
    note = sheet.tip_note(setup, SPOT["ops"][0])
    full = endpoint["dro_tip_z"] + row[lead]  # where the full diameter ends
    achieved = min(row["exit_face"], endpoint["dro_exit_face"]) - full
    assert run_outs(note, endpoint) == claimed
    # 0.494 and 0.4987 can only print as 0.494 and 0.498: never more than the tip achieves.
    assert all(achieved - 0.001 < value <= achieved + 1e-9 for value in claimed)


def test_a_breakthrough_note_claims_no_run_out_the_endpoint_leaves_unknown():
    sheet, endpoint, setup = through(exit_face=-10.002, point_mm=0.839, exit_mm=0.5, tip_z=-11.341)
    endpoint["dro_exit_mm"] = "unknown"
    assert run_outs(sheet.tip_note(setup, SPOT["ops"][0]), endpoint) == []


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


@pytest.mark.parametrize("kind", ["mill", "lathe"])
def test_a_hold_that_must_stay_clamped_prints_its_recovery_never_the_loosen_advice(kind):
    sheet, transfer = transfer_sheet(["face_a", "bore"], kind)
    sheet.machine = lambda setup: {"kind": kind}
    recovery = "index back to 0 and indicate the reamed socket; re-tram the head if it holds"
    line = sheet.transfer_line(
        {"id": "S5"}, {**transfer, "keep_clamped": True, "recovery": recovery}
    )
    assert recovery in line and "0.0254" in line
    assert not re.search(r"loosen the clamping|tap the|tap true|re-clamp", line)
    assert "do not loosen" in line.lower()


@pytest.mark.parametrize("recovery", [None, "unknown", "  "])
def test_a_hold_that_must_stay_clamped_without_a_recovery_is_a_stop(recovery):
    sheet, transfer = transfer_sheet(["face_a", "bore"], "mill")
    transfer = {**transfer, "keep_clamped": True}
    if recovery is not None:
        transfer["recovery"] = recovery
    line = sheet.transfer_line({"id": "S5"}, transfer)
    assert line.startswith("STOP") and "recovery" in line
    assert not re.search(r"loosen the clamping|tap the|re-clamp", line)


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


PAINT_NOTE = "Mask the bores; brush RAL 6005 to 50-75 um dry film."


def _bench_sheet(ops):
    from prechips.inputs import Bundle

    data = Bundle(
        plan={"setups": [{"id": "S12", "machine": "bench", "ops": ops}]},
        inventory={
            "machines": {"bench": {"kind": "bench"}},
            "consumables": {"ral-6005": {"name": "RAL 6005 alkyd"}},
        },
        features={"features": {"body": {"kind": "cylinder"}}},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )
    sheet = _Traveler(data, [], {}, None)
    html, _, _ = sheet.operations(data.plan["setups"][0], {}, {"notes": 2})
    return html


def test_a_bench_finishing_setup_prints_a_finishing_table_not_empty_machining_columns():
    paint = {"op": 10, "do": "coating", "feature": "body", "process": "ral-6005"}
    html = _bench_sheet(
        [{**paint, "note": PAINT_NOTE}, {"op": 20, "do": "deburr", "feature": "body"}]
    )
    headings = re.findall(r"<th>([^<]*)</th>", html)
    assert "<h2>ASSEMBLY / FINISHING</h2>" in html and "<h2>OPERATIONS</h2>" not in html
    assert headings == [
        "step",
        "feature",
        "material / consumable",
        "action",
        "inspection: limit, gauge",
    ]
    painted = html.split("<td>10</td>", 1)[1].split("</tr>", 1)[0]
    # The consumable sits in its own column and the op's instruction is its action, once.
    cells = re.findall(r"<td>(.*?)</td>", painted, re.DOTALL)
    assert cells[1] == "RAL 6005 alkyd (in-house)"
    assert PAINT_NOTE in cells[2]
    assert html.count("brush RAL 6005") == 1
    deburred = html.split("<td>20</td>", 1)[1].split("</tr>", 1)[0]
    assert "deburr" in deburred


def test_a_setup_with_any_cutting_op_keeps_the_machining_table():
    paint = {"op": 10, "do": "coating", "feature": "body", "process": "ral-6005"}
    html = _bench_sheet([paint, {"op": 20, "do": "drill", "feature": "body"}])
    assert "<h2>OPERATIONS</h2>" in html and "FINISHING" not in html
    assert "rpm" in re.findall(r"<th>([^<]*)</th>", html)
