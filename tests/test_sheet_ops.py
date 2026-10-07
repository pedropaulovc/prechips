"""Operation-sheet wording a machinist acts on: printed bands and index directions."""

import functools
import random
import json
import os
import re
import subprocess
import threading
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.sheet import _Traveler

ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"


def bare(precision):
    sheet = _Traveler.__new__(_Traveler)
    sheet.precision = lambda feature, dimension: precision
    return sheet


class Markup(HTMLParser):
    """Read generated record associations without pinning its incidental markup."""

    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = {
            "tag": tag,
            "attrs": dict(attrs),
            "text": [],
            "parent": self.stack[-1] if self.stack else None,
        }
        self.nodes.append(node)
        if tag not in {"br", "col", "img", "meta", "input", "hr", "link"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()["tag"] == tag:
                break

    def handle_data(self, text):
        for node in self.stack:
            node["text"].append(text)

    def find(self, css, within=None):
        result = []
        for node in self.nodes:
            if css not in node["attrs"].get("class", "").split():
                continue
            parent = node
            while parent is not None and parent is not within:
                parent = parent["parent"]
            if within is None or parent is within:
                result.append(node)
        return result


def content(node):
    return "".join(node["text"])


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
    sheet.plan = sheet.bundle.plan
    sheet.units = "mm"
    sheet.bench = lambda text, setup=None: text
    sheet.machine = lambda setup: {"kind": kind}
    sheet.operative = lambda v: (
        f"{v:.3f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "?"
    )
    return sheet


SPOT = {"id": "S1", "ops": [{"op": 60, "do": "spot", "feature": "hole", "tool": "c"}]}
# The setup's T-numbers by tool + holder identity, and its tool names by tool identity.
T4 = {(("tools", "c"), ("holders", None)): "T4"}
T1 = {("tools", "c"): "T1"}


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
    rows = clearance_sheet(records).clearance_rows(SPOT, numbers, T4)
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
    rows = clearance_sheet(records).clearance_rows(setup, numbers, T4)
    assert [row[0] for row in rows] == ["60, 70"]


def near_holding(mm, tag="clamp 2 diamond-pin:collar"):
    """A clearance sheet whose kernel picture measured op 60's cut ``mm`` from ``tag``; the
    hold's second clamp entry is a locator (LOC2)."""
    sheet = clearance_sheet(reach_records(top=4.47))
    scene = {"cut_clearances": [{"op": 60, "mm": mm, "tag": tag}]}
    sheet.report = {"renders": {"S1": {"scene": scene}}}
    clamps = [{"ref": "strap"}, {"ref": "diamond-pin", "restraint": "locate"}]
    return sheet, {**SPOT, "hold": {"clamps": clamps}}


def test_the_holding_nearest_the_cut_is_a_clearance_row_and_a_hand_feed_check_on_the_op():
    # Holder face 22.03 over the stock; the locator's collar 1.57 from the cut is closer.
    sheet, setup = near_holding(1.57)
    ((ops, _, obstacle, value, action),) = sheet.clearance_rows(setup, headroom(40.0), {})
    assert (obstacle, value) == ("LOC2 collar beside the cut", "1.570")
    assert action == "hand feed past the LOC2 collar; check the cutter clears it"
    (box,) = sheet.crash_boxes(setup, setup["ops"][0])
    assert box == "LOC2 COLLAR 1.570 mm FROM THE CUT — hand feed past it"
    # Jaw tops 1.2 below the tip are closer still: the collar stays named, with its gap.
    numbers = headroom(40.0, tip_above_jaws=1.2, jaw_top_z=-1.7)
    ((_, _, obstacle, _, action),) = sheet.clearance_rows(setup, numbers, {})
    assert "jaw" in obstacle and "hand feed past the LOC2 collar (1.570 mm)" in action


def test_a_file_near_the_holding_is_a_clearance_row_and_a_check_on_its_own_op():
    # Filing the last of the profile brings the work 2.817 from the locator: the picture's
    # dimension, so a row of the table and a box on the file's op, never a machine op's.
    sheet, setup = near_holding(2.817, "clamp 2 diamond-pin:rodlocator")
    scene = sheet.report["renders"]["S1"]["scene"]
    scene["cut_clearances"][0]["op"] = 30
    filed = {"op": 30, "do": "file_to_line", "feature": "hole"}
    setup = {**setup, "ops": [filed]}
    ((ops, tool, obstacle, value, action),) = sheet.clearance_rows(setup, {}, {})
    assert (ops, tool, obstacle, value) == ("30", "", "LOC2 rodlocator beside the cut", "2.817")
    assert action == "keep the file clear of the LOC2 rodlocator"
    (box,) = sheet.crash_boxes(setup, filed)
    assert box == "LOC2 RODLOCATOR 2.817 mm FROM THE CUT — keep the file clear of it"


@pytest.mark.parametrize(
    ("mm", "tag", "obstacle", "action"),
    [
        # Past the crash zone: a clearance like any other, no check.
        (12.0, "profile-fixture:pad-r1", None, ""),
        (3.5, "profile-fixture:pad-r1", "pad r1 beside the cut", ""),
        # A vise jaw's kernel tag reads as the jaw, never as an identifier.
        (3.5, "fixed_jaw", "fixed jaw beside the cut", ""),
        # The kernel could not derive the op's cut: never a pass.
        ("unknown", "unknown", None, "holding beside the cut: not computed — check at"),
    ],
)
def test_a_far_or_unknown_holding_clearance_is_no_hand_feed_check(mm, tag, obstacle, action):
    sheet, setup = near_holding(mm, tag)
    ((_, _, printed, _, actions),) = sheet.clearance_rows(setup, headroom(40.0), {})
    assert obstacle is None or printed == obstacle
    assert action in actions and "hand feed" not in actions
    assert sheet.crash_boxes(setup, setup["ops"][0]) == []


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
    markup = Markup(shop(contour_records([-0.25, -0.5, -0.6])).contours(POCKET, {"c": "T1"}))
    heading = next(node for node in markup.nodes if node["tag"] == "h3")
    assert "S1 op 10 — ear · T1 · Z -0.250, -0.500, -0.600" in content(heading)
    assert content(heading).count("-0.250") == content(heading).count("-0.500") == 1


def test_a_single_level_contour_heading_keeps_its_one_z():
    for levels in (None, [-0.6]):
        markup = Markup(shop(contour_records(levels)).contours(POCKET, {"c": "T1"}))
        heading = next(node for node in markup.nodes if node["tag"] == "h3")
        html = content(heading)
        assert "S1 op 10 — ear · T1 · Z -0.600" in html
        assert "depth levels" not in html


@pytest.mark.parametrize(
    ("start", "levels", "target"),
    [
        # Stepped down from where its surface stands: the start, the count and the step.
        (0.0, [-0.25, -0.5, -0.6], "Z 0.000 → -0.600 in 3 levels of 0.250 max"),
        # Its surface already stands at the depth (an earlier op left the floor): one pass
        # at the depth, not a level from a Z to itself.
        (-0.6, [-0.6], "Z → -0.600"),
    ],
)
def test_an_op_whose_levels_start_at_its_depth_prints_one_pass_at_that_depth(start, levels, target):
    records = contour_records(levels)
    records[("coordinates", "S1")]["operations"][0]["z_levels"]["dro_start_z"] = start
    assert shop(records).z_target(POCKET, POCKET["ops"][0]) == target


@pytest.mark.parametrize(
    ("doc", "established"),
    [
        # No step, or one under the 0.001 DRO grid: the producer establishes no levels.
        ("unknown", False),
        (0.0001, False),
        (0.25, True),
    ],
)
def test_a_floor_already_at_depth_is_one_pass_only_when_its_levels_are_established(
    doc, established
):
    from prechips.rules.coordinates import _z_levels, dro_z

    op = {**POCKET["ops"][0], "to_z": -0.6, "doc_mm": doc}
    records = contour_records([-0.6])
    grid = (0.001, 3)
    records[("coordinates", "S1")]["operations"][0]["z_levels"] = _z_levels(
        op, {"top_z": -0.6}, {}, [], {}, grid, "mm", lambda: dro_z(-0.6, grid)
    )
    parts = [str(part) for part in shop(records).tip(POCKET, op)]
    assert any("STOP" in part for part in parts) is not established, parts


def test_each_depth_level_has_a_place_to_mark_it_done():
    markup = Markup(shop(contour_records([-0.25, -0.5, -0.6])).contours(POCKET, {"c": "T1"}))
    marks = markup.find("tick")
    assert len(marks) == 3
    parents = {id(mark["parent"]): mark["parent"] for mark in marks}
    assert [
        number
        for parent in parents.values()
        for number in re.findall(r"level (\d) of 3", content(parent))
    ] == ["1", "2", "3"]
    # One level: the op row is the only mark it needs.
    single = Markup(shop(contour_records([-0.6])).contours(POCKET, {"c": "T1"}))
    assert not single.find("tick")


def test_a_raster_block_says_how_to_lift_not_what_its_table_already_shows():
    markup = Markup(shop(contour_records(None)).contours(POCKET, {"c": "T1"}))
    table = markup.find("coords")[0]
    block = content(markup.find("table-context", table)[0])
    assert "Lift to Z 5.000 after each pass." in block, block
    for narration in ("passes", "stepover", "stage", "cutting order", "pass ends", "13.765"):
        assert narration not in block, (narration, block)
    # The passes are numbered: the table is where their count and ends are read.
    rows = [
        node
        for node in markup.nodes
        if node["tag"] == "tr"
        and node["parent"]["tag"] == "tbody"
        and node["parent"]["parent"] is table
    ]
    assert [
        content(
            next(node for node in markup.nodes if node["tag"] == "td" and node["parent"] is row)
        )
        for row in rows
    ] == ["1", "2"]


def kernel_stock(box_mm, status="ok"):
    """A bundle whose kernel modelled S1's entry stock as setup-frame box ``box_mm``."""
    return SimpleNamespace(kernel={"status": status, "setups": {"S1": {"stock_bbox_mm": box_mm}}})


def raster_notes(html):
    """Each raster table's note: how its passes lift, and what of their ends is proven."""
    markup = Markup(html)
    return [
        content(node) for node in markup.find("table-context") if "after each pass" in content(node)
    ]


def raster_note(bundle, units="mm", removal=None, records=None):
    """The raster note op 10 prints: its passes at Y 1 and 2 run X -13.765 to 13.765 with a
    4.76 cutter radius over the area X -9..9, entering from the open -Y side."""
    sheet = shop(records or contour_records(None))
    sheet.bundle, sheet.units = bundle, units
    op = {**POCKET["ops"][0]}
    if removal is not None:
        op["stock_removal_bounds"] = removal
    (note,) = raster_notes(sheet.contours({"id": "S1", "ops": [op]}, T1))
    # The table prints the pass ends: the note names an end by its side only.
    assert "13.765" not in note
    return note


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
    assert not MATERIAL.search(note)
    claimed = [
        end
        for end, side in (("-13.765", "-X"), ("13.765", "+X"))
        if re.search(rf"both in air|{re.escape(side)} pass end is in air", note)
    ]
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
    html = sheet.contours(POCKET, T1)
    return raster_notes(html)


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
    # The split finish stage states its own outer ends without the rough stage's every-pass
    # claim, and each table names its stage.
    assert "outer pass ends both in air" in notes[1] and not EVERY.search(notes[1])
    assert notes[0].startswith("Rough: lift") and notes[1].startswith("Finish: lift")


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
    markup = Markup(html)
    (note,) = [
        content(node)
        for node in markup.find("table-context")
        if "Cutter-centre checkpoints" in content(node)
    ]
    return note.split("Cutter-centre checkpoints", 1)[1]


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


def test_a_contour_table_repeats_its_operation_context_and_coordinate_values():
    markup = Markup(shop(contour_records(None)).contours(POCKET, {"c": "T1"}))
    table = markup.find("coords")[0]
    repeat = markup.find("repeat", table)[0]
    assert "op 10" in content(repeat) and "T1" in content(repeat)
    assert "-13.765" in [content(node) for node in markup.find("num", table)]


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
    markup = Markup(sheet.feature_map({"id": "S1", "ops": turned}))
    head = next(
        node["parent"] for node in markup.nodes if node["tag"] == "td" and content(node) == "head"
    )
    assert "Ø42.000–43.600" in content(head) and "Ø42.750" in content(head)
    # A process size (a joint spigot) has no drawing limits to print.
    spigot = next(
        node["parent"] for node in markup.nodes if node["tag"] == "td" and content(node) == "spigot"
    )
    assert "—" in content(spigot) and "Ø17.200" in content(spigot)


@pytest.mark.parametrize(
    ("display", "x", "heading", "cell", "note"),
    [
        ("diameter", 42.75, "turn to Ø", "Ø42.750", "X reads diameter."),
        # A radius display reads half the Ø42.75 head: never printed as a Ø.
        ("radius", 21.375, "turn to X (radius)", "21.375", "X reads radius."),
        # Not knowing the display, no X is printed and the map says why it stops.
        ("unknown", "unknown", "turn to X", "?", "STOP"),
    ],
)
def test_a_lathe_feature_map_prints_the_x_turned_to_in_the_dro_display(
    display, x, heading, cell, note
):
    rows = [
        {"feature": "head", "setup": [21.375, 0.0, z], "dia_nominal": 42.75, "x_target_mm": x}
        for z in (0, -95)
    ]
    sheet = mapped(
        {("coordinates", "S1"): {"x_display": display, "rows": rows}},
        {"head": {"kind": "cylinder"}},
        drawing={"head": {"kind": "cylinder", "dia": [42.0, 43.6]}},
        kind="lathe",
    )
    html = sheet.feature_map({"id": "S1", "ops": [{"op": 10, "do": "turn", "feature": "head"}]})
    markup = Markup(html)
    table = markup.find("feature-map")[0]
    head = next(
        node["parent"] for node in markup.nodes if node["tag"] == "td" and content(node) == "head"
    )
    cells = [node for node in markup.nodes if node["tag"] == "td" and node["parent"] is head]
    assert len(cells) == 5
    assert content(cells[1]) == "Ø42.000–43.600" and content(cells[2]) == cell
    assert heading in [
        content(node)
        for node in markup.nodes
        if node["tag"] == "th" and not node["attrs"].get("colspan")
    ]
    if display == "unknown":
        assert markup.find("stop")
    else:
        assert note in content(markup.find("table-context", table)[0])
    if display != "diameter":
        assert "Ø21.375" not in content(head)


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
    markup = Markup(sheet.feature_map(setup))
    table = markup.find("feature-map")[0]
    body_rows = [
        node
        for node in markup.nodes
        if node["tag"] == "tr"
        and node["parent"]["tag"] == "tbody"
        and node["parent"]["parent"] is table
    ]
    cells = [
        [content(node) for node in markup.nodes if node["tag"] == "td" and node["parent"] is row]
        for row in body_rows
    ]
    expected = [
        ("hold down", ("hole axis", "Z0 surface"), ["0.000", "-8.200", "0.000"]),
        ("ear arch", ("arc centre", "Z0 surface"), ["0.000", "-25.200", "0.000"]),
        ("crank bore", ("hole axis", "exit face"), ["-72.885", "0.000", "-21.375"]),
    ]
    for row, (feature, reference, coordinates) in zip(cells, expected, strict=True):
        assert row[0] == feature
        assert all(term in row[1] for term in reference)
        assert row[2:] == coordinates


@pytest.mark.parametrize(
    ("normal", "kept"),
    [([0.0, 0.0, 1.0], False), ([0.0, 0.0, -1.0], False), ([1.0, 0.0, 0.0], True)],
)
def test_a_mill_feature_map_leaves_off_a_face_square_to_the_spindle(normal, kept):
    # A face square to setup Z is located only by its centre: no X / Y the DRO stops at,
    # and its Z is the op row's. A face standing across the table keeps its row: its X
    # places it. A map left with no row prints nothing.
    identity = {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
    frames = {"model": identity, "T": {**identity, "origin": [0.0, 0.0, 0.0]}}
    face = {"feature": "blank_end", "dro": [17.1, 13.1, 0.0]}
    hole = {"feature": "hold_down", "dro": [0.0, -8.2, 0.0]}
    features = {"blank_end": {"kind": "end_face", "axis": normal}, "hold_down": {"kind": "hole"}}
    setup = {"id": "S1", "frame": "T", "ops": [{"op": 10, "do": "face", "feature": "blank_end"}]}
    maps = []
    for rows in ([face, hole], [face]):
        sheet = mapped({("coordinates", "S1"): {"rows": rows}}, features)
        sheet.bundle = SimpleNamespace(features={"features": {}, "frames": frames}, plan={})
        maps.append(rows_of(sheet.feature_map(setup)))
    both, alone = maps
    assert "hold down||hole axis on the Z0 surface||" in both
    assert ("blank end||" in both) is kept
    assert ("blank end||" in alone) is kept and bool(alone) is kept


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
    """The run-outs a breakthrough note claims. The op row's Z column prints the DRO tip and
    the exit face; the note repeats neither (no Z, no tip or face number)."""
    if note is None:
        return []
    numbers = re.findall(r"-?\d+\.\d+", note)
    printed = {f"{endpoint['dro_tip_z']:.3f}", f"{endpoint['dro_exit_face']:.3f}"}
    assert "Z" not in note and not printed & set(numbers), note
    return [float(v) for v in numbers]


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
    # The sheet names an item by its reference and the slot that selects it.
    sheet.reference = lambda gauge, slot=None: "dial test indicator"
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
    markup = Markup(html)
    assert len([node for node in markup.nodes if node["tag"] == "li"]) == 3
    fields = markup.find("field")
    assert [content(markup.find("field-label", field)[0]) for field in fields] == [
        "X1",
        "Y1",
        "result",
    ]
    assert all(len(markup.find("writing-blank", field)) == 1 for field in fields)
    calculation = content(markup.find("calc")[0])
    assert "133.067" in calculation and "8.456" in calculation and "−" in calculation
    assert shop({}).note("S1 op 10 Ra", "Compare.") == "S1 op 10 Ra: Compare."


ANGULARITY = [
    "Orientation 1, position A then B. Journal rod rise: {rJ1}",
    "Orientation 1. Crank rod rise: {rC1}",
    "Orientation 2. Journal rod rise: {rJ2}",
    "Orientation 2. Crank rod rise: {rC2}",
    "Calculate: 0.945 × rC1 − 1.384 × rJ1 = {e1}",
    "Calculate: √(e1² + e2²) = {result}; accept 0.10 or less.",
]


def worksheet_readings(markup):
    """Source step, named reading and sole value-field label in each READINGS row."""
    table = markup.find("readings")[0]
    result = []
    for row in markup.nodes:
        if row["tag"] != "tr" or row["parent"]["parent"] is not table:
            continue
        cells = [node for node in markup.nodes if node["tag"] == "td" and node["parent"] is row]
        if not cells:
            continue
        assert len(cells) == 3 and len(markup.find("writing-blank", cells[2])) == 1
        label = content(markup.find("field-label", cells[2])[0])
        result.append((content(cells[0]), content(cells[1]), label))
    return result


@pytest.mark.parametrize(
    ("procedure", "worksheet"),
    [
        (ANGULARITY, True),  # readings worked through two calculation lines
        (ANGULARITY[:5], False),  # one calculation line: a note
        (["Seat it.", "Read it.", "Calculate: a = b", "Calculate: c = d"], False),  # no reading
    ],
)
def test_readings_worked_through_several_calculations_get_a_worksheet_of_their_own(
    procedure, worksheet
):
    from prechips.sheet import _worksheet

    sheet = shop({})
    notes, worksheets = ["an earlier note"], []
    op = {"op": 110, "feature": "bore", "inspection_note": procedure}
    sheets = {"notes": 2, "worksheets": 4}
    cell = sheet.inspection({"id": "S11"}, op, notes, worksheets, sheets)
    if not worksheet:
        assert cell == ["see S11 sheet 2 note 2"] and not worksheets
        return
    assert cell == ["see S11 sheet 4 worksheet"] and notes == ["an earlier note"]
    html = _worksheet(worksheets[0])
    markup = Markup(html)
    steps = markup.find("steps")[0]
    assert not markup.find("field", steps)  # steps refer to readings, not extra value boxes
    assert [
        content(node)
        for node in markup.find("reading", steps)
        if re.fullmatch(r"\[[^\[\]]+\]", content(node))
    ] == ["[rJ1]", "[rC1]", "[rJ2]", "[rC2]"]
    assert worksheet_readings(markup) == [
        ("1", "[rJ1]", "rJ1"),
        ("2", "[rC1]", "rC1"),
        ("3", "[rJ2]", "rJ2"),
        ("4", "[rC2]", "rC2"),
    ]
    calculations = markup.find("calc")
    assert [content(markup.find("field-label", line)[0]) for line in calculations] == [
        "e1",
        "result",
    ]
    assert all(len(markup.find("writing-blank", line)) == 1 for line in calculations)
    assert "0.945 × rC1 − 1.384 × rJ1 =" in content(calculations[0])
    assert "√(e1² + e2²) =" in content(calculations[1])


def test_underscore_prompts_never_classify_as_named_worksheet_readings():
    from prechips.sheet import _list, _readings

    procedure = ["Read the dial: _____", "Calculate: a = _____", "Calculate: b = _____"]
    sheet = shop({})
    notes, worksheets = [], []
    rows = sheet.inspection(
        {"id": "S1"},
        {"op": 10, "inspection_note": procedure},
        notes,
        worksheets,
        {"notes": 2, "worksheets": 3},
    )
    assert rows == ["see S1 sheet 2 note 1"] and not worksheets
    assert _readings(procedure) == []
    assert len(Markup(_list(notes)).find("writing-blank")) == 3


@pytest.mark.parametrize("details", [False, True])
def test_real_cone_worksheet_keeps_source_steps_equations_and_attachment_order(details):
    from prechips.inputs import load_bundle

    bundle = load_bundle(
        Path(__file__).resolve().parents[1] / "examples/cone-pivot-post/built-up.toml"
    )
    setup = next(item for item in bundle.plan["setups"] if item["id"] == "S11")
    authored = next(op for op in setup["ops"] if op["op"] == 110)["inspection_methods"][
        "angularity_dia"
    ]
    sheet = _Traveler(bundle, [], {}, None)
    # Exercise both routing branches without invoking a native renderer.
    sheet.fixture_render = lambda setup: ""
    sheet.shop_made_tables = lambda setup: ""
    sheet.clearance = lambda setup, tools: ""
    sheet.feature_map = lambda setup: "<h2>FEATURE MAP</h2>" if details else ""
    sheet.blank_checks = lambda setup: ""
    sheet.contours = lambda setup, tools: "<h2>CONTOURS</h2>"
    original_operations = sheet.operations

    def operations(setup, tools, sheets):
        table, notes, worksheets, stops = original_operations(setup, tools, sheets)
        return table, notes if details else "", worksheets, stops

    sheet.operations = operations
    sections = sheet.setup_section(setup)
    assert len(sections) == (4 if details else 3)
    front = Markup("<div>" + "".join(sections[0]) + "</div>")
    assert f"S11 sheet {len(sections)} worksheet" in content(front.nodes[0])
    assert "CONTOURS" in "".join(sections[-2])
    worksheet = "".join(sections[-1])
    assert "worksheet, S11 op 110 angularity Ø" in worksheet
    markup = Markup(worksheet)
    assert worksheet_readings(markup) == [
        ("5", "[rJ1]", "rJ1"),
        ("6", "[rC1]", "rC1"),
        ("7", "[rJ2]", "rJ2"),
        ("8", "[rC2]", "rC2"),
    ]
    assert not markup.find("field", markup.find("steps")[0])
    calculations = markup.find("calc")
    assert [content(markup.find("field-label", row)[0]) for row in calculations] == [
        "e1",
        "e2",
        "result",
    ]
    assert len(markup.find("writing-blank")) == 7
    for row, source in zip(calculations, authored[-3:], strict=True):
        assert content(row) == re.sub(r"\{([^{}]+)\}", r"\1", source)


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
    html, _, _, _ = sheet.operations(data.plan["setups"][0], {}, {"notes": 2})
    return html


def test_a_bench_finishing_setup_prints_a_finishing_table_not_empty_machining_columns():
    paint = {"op": 10, "do": "coating", "feature": "body", "process": "ral-6005"}
    html = _bench_sheet(
        [{**paint, "note": PAINT_NOTE}, {"op": 20, "do": "deburr", "feature": "body"}]
    )
    markup = Markup(html)
    assert "<h2>ASSEMBLY / FINISHING</h2>" in html and "<h2>OPERATIONS</h2>" not in html
    painted, deburred = markup.find("operation")
    assert [node["attrs"]["data-op"] for node in (painted, deburred)] == ["10", "20"]
    assert content(markup.find("op-feature", painted)[0]).endswith("body")
    assert "RAL 6005 alkyd (in-house)" in content(markup.find("op-consumable", painted)[0])
    assert PAINT_NOTE in content(markup.find("op-action", painted)[0])
    assert content(painted).count("brush RAL 6005") == 1
    assert "deburr" in content(markup.find("op-action", deburred)[0])
    for operation in (painted, deburred):
        assert len(markup.find("performed-mark", operation)) == 1
        assert markup.find("inspection-message", operation)
        for css in ("op-speed", "op-feed", "op-target", "op-direction", "op-tool"):
            assert not markup.find(css, operation)


def test_a_setup_with_any_cutting_op_keeps_the_machining_table():
    paint = {"op": 10, "do": "coating", "feature": "body", "process": "ral-6005"}
    html = _bench_sheet([paint, {"op": 20, "do": "drill", "feature": "body"}])
    assert "<h2>OPERATIONS</h2>" in html and "FINISHING" not in html
    assert "rpm" in content(Markup(html).find("op-speed")[0])


def _lathe_sheet(ops, hands):
    from prechips.inputs import Bundle

    tools = {name: {"kind": "lathe_tool_bit", "name": name} for name in hands}
    for name, hand in hands.items():
        if hand is not None:
            tools[name]["hand"] = hand
    data = Bundle(
        plan={"setups": [{"id": "S1", "machine": "lathe", "ops": ops}]},
        inventory={"machines": {"lathe": {"kind": "lathe"}}, "tools": tools},
        features={"features": {"body": {"kind": "cylinder"}}},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )
    sheet = _Traveler(data, [], {}, None)
    html, _, _, stops = sheet.operations(data.plan["setups"][0], {}, {"notes": 2})
    rows = {}
    markup = Markup(html)
    for operation in markup.find("operation"):
        speed = markup.find("op-speed", operation)[0]
        value = next(
            node for node in markup.nodes if node["tag"] == "dd" and node["parent"] is speed
        )
        rows[operation["attrs"]["data-op"]] = " ".join(value["text"]).split()
    return html, rows, stops


@pytest.mark.parametrize(
    ("tool", "shank"),
    [
        ({"dia_mm": 21.8, "shank_in": 0.5}, "shank Ø12.700"),  # a reduced-shank drill
        ({"dia_mm": 9.525, "shank_in": 0.375}, None),  # shank and cut the same size
        ({"dia_mm": 21.8}, None),  # no shank declared: nothing claimed
    ],
)
def test_a_tool_row_prints_the_shank_where_it_differs_from_the_cutting_diameter(tool, shank):
    sheet = shop({})
    sheet.bundle.inventory = {"tools": {"drill": {"kind": "drill", **tool}}}
    detail = sheet.tool_detail("drill")
    assert [d for d in detail if d.startswith("shank")] == ([shank] if shank else [])


JOINT = {
    "kind": "cylindrical",
    "socket": "socket",
    "spigot": "spigot",
    "fit": "clearance",
    "clearance_mm": [0.044, 0.076],
    "method": "retaining_compound",
    "process": "retaining compound",
    "cure_time_min": 1440,
    "surface_prep": "solvent-degreased and dry",
}


@pytest.mark.parametrize("fit_op", [True, False])
def test_a_joint_prep_and_cure_print_once_on_the_op_that_fits_it_not_in_the_arrival(fit_op):
    sheet = shop({})
    sheet.features = {"socket": {"thru": True}}
    ops = [{"op": 10, "do": "inspect"}] + ([{"op": 20, "do": "fit"}] if fit_op else [])
    setup = {"id": "S6", "joint": JOINT, "ops": ops}
    arrival = sheet.joint_text(setup)
    at_ops = [sheet.compound_note(setup, op) for op in ops]
    # What goes into what, and the band, always arrive with the parts.
    assert "spigot into through-socket socket, clearance 0.044 to 0.076 mm diametral." in arrival
    # Prep and the undisturbed cure print exactly once: on the fit op, else on arrival.
    cure = (
        "Surface prep: solvent-degreased and dry. Do not disturb until cured: cure time 1440 min."
    )
    printed = [text for text in [arrival, *at_ops] if text and "Surface prep" in text]
    assert len(printed) == 1 and ("cure time 1440 min" in printed[0])
    assert at_ops == ([None, cure] if fit_op else [None])


def test_each_lathe_op_that_turns_the_spindle_names_which_way_from_its_tool_hand():
    ops = [
        {"op": 10, "do": "face", "feature": "body", "tool": "rh"},
        {"op": 20, "do": "rough_turn", "feature": "body", "tool": "lh"},
        {"op": 30, "do": "drill", "feature": "body", "tool": "lh"},  # a left-hand cut drill
        {"op": 40, "do": "inspect", "feature": "body"},
    ]
    html, rows, stops = _lathe_sheet(ops, {"rh": "right", "lh": "left"})
    # An edge-up turning tool of either hand: the work turns down onto it.
    assert rows["10"][-1] == rows["20"][-1] == "FORWARD"
    assert rows["30"][-1] == "REVERSE" and rows["40"] == ["—"]
    assert (
        "<h2>OPERATIONS — spindle FORWARD: the top of the work turns toward you; "
        "spindle REVERSE: the top of the work turns away from you</h2>"
    ) in html
    assert "spindle direction not known" not in stops


def test_a_lathe_setup_turning_one_way_says_so_once_and_its_rpm_cells_carry_only_the_rpm():
    ops = [
        {"op": 10, "do": "face", "feature": "body", "tool": "rh"},
        {"op": 20, "do": "rough_turn", "feature": "body", "tool": "lh"},
        {"op": 30, "do": "inspect", "feature": "body"},
    ]
    html, rows, stops = _lathe_sheet(ops, {"rh": "right", "lh": "left"})
    assert "FORWARD" not in rows["10"] + rows["20"]
    assert (
        "<h2>OPERATIONS — spindle FORWARD whenever it runs: the top of the work turns toward "
        "you</h2>"
    ) in html
    assert "spindle direction not known" not in stops


def test_a_lathe_op_whose_turn_is_unknown_leaves_the_known_turns_in_their_cells():
    # One STOP among FORWARD ops: the heading cannot say one turn for every op.
    ops = [
        {"op": 10, "do": "face", "feature": "body", "tool": "rh"},
        {"op": 20, "do": "rough_turn", "feature": "body", "tool": "bit"},
    ]
    html, rows, stops = _lathe_sheet(ops, {"rh": "right", "bit": None})
    assert rows["10"][-1] == "FORWARD"
    assert "whenever it runs" not in html
    assert stops["spindle direction not known"] == ["20"]


def test_a_lathe_tool_without_a_declared_hand_is_a_stop_not_a_guessed_direction():
    ops = [{"op": 10, "do": "face", "feature": "body", "tool": "bit"}]
    html, rows, stops = _lathe_sheet(ops, {"bit": None})
    assert "STOP: spindle direction not known" in " ".join(rows["10"])
    assert stops["spindle direction not known"] == ["10"]
    assert "FORWARD" not in html


@pytest.mark.parametrize("checked", [True, False])
def test_a_lathe_op_table_says_to_stop_the_spindle_before_any_gauge_touches_the_work(checked):
    # A lathe op inspected in the chuck is measured stopped, the tool withdrawn: said once
    # over the op rows; a table with nothing measured says nothing about measuring.
    finish = {"op": 10, "do": "finish_turn", "feature": "body", "tool": "rh"}
    if checked:
        finish["checks"] = {"dia": "mic"}
    html, _, _ = _lathe_sheet([finish], {"rh": "right"})
    (heading,) = re.findall(r"<h2>OPERATIONS.*?</h2>", html)
    stopped = "measure only with the spindle stopped and the tool withdrawn" in heading
    assert stopped is checked, heading


@pytest.mark.parametrize(
    ("x_after", "ends"),
    [
        ([1, 0, 0], "the +X end stays at +X"),
        ([-1, 0, 0], "the +X end moves to −X"),
        # Turned over about X and a quarter turn: the old +X end now lies along Y.
        ([0, 1, 0], "the +X end moves to +Y"),
        ([0, -1, 0], "the +X end moves to −Y"),
    ],
)
def test_a_turn_over_names_where_the_old_plus_x_end_goes(x_after, ends):
    from prechips.inputs import Bundle

    frames = {
        "first": {"origin": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
        "turned": {"origin": [0, 0, 0], "x": x_after, "z": [0, 0, -1]},
    }
    setups = [
        {"id": "S1", "machine": "mill", "frame": "first", "ops": []},
        {"id": "S2", "machine": "mill", "frame": "turned", "stock_in": "S1", "ops": []},
    ]
    data = Bundle(
        plan={"setups": setups},
        inventory={"machines": {"mill": {"kind": "mill"}}},
        features={"features": {}, "frames": frames},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )
    assert _Traveler(data, [], {}, None).flip(setups[1]) == (
        f"Turn the part over: the other face up, {ends}. "
    )


_MEASURED = {"by": "test", "date": "2026-10-05", "instrument": "caliper"}


@pytest.mark.parametrize("unmeasured", [None, "spigot_length_mm", "thickness_mm"])
def test_the_hold_prints_the_jaw_buttons_measured_sizes(unmeasured):
    from prechips.inputs import Bundle

    sizes = {"dia_mm": 16.0, "thickness_mm": 3.0, "spigot_dia_mm": 12.2, "spigot_length_mm": 2.0}
    buttons = {"kind": "jaw_buttons", "name": "two jaw buttons with spigots"}
    for key, value in sizes.items():
        # An unmeasured size is a bare nominal: the kernel will not place the jaws on it.
        buttons[key] = value if key == unmeasured else {"value": value, "measured": _MEASURED}
    setup = {
        "id": "S1",
        "machine": "lathe",
        "hold": {"kind": "chuck", "fixture": "chuck", "jaw_buttons": "buttons"},
        "ops": [],
    }
    data = Bundle(
        plan={"setups": [setup]},
        inventory={
            "machines": {"lathe": {"kind": "lathe"}},
            "fixtures": {"chuck": {"kind": "chuck", "name": "3-jaw chuck"}, "buttons": buttons},
        },
        features={"features": {}, "frames": {}, "units": "mm"},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )
    hold, _ = _Traveler(data, [], {}, None).hold(setup)
    (step,) = [s for s in re.findall(r"<li>(.*?)</li>", unescape(hold)) if "Jaw buttons" in s]
    printed = {
        "dia_mm": "face Ø16.000 mm",
        "thickness_mm": "thickness 3.000 mm",
        "spigot_dia_mm": "spigot Ø12.200 mm",
        "spigot_length_mm": "spigot length 2.000 mm",
    }
    for key, text in printed.items():
        assert (text in step) is (key != unmeasured), (key, step)
    if unmeasured:
        name = unmeasured.removesuffix("_mm").replace("_", " ")
        assert f"{name} ? not measured" in step, step


def _requirement_rows(features, **manifest):
    """The job page's DRAWING REQUIREMENTS rows as ``(feature, limits)`` texts."""
    from prechips.inputs import Bundle

    data = Bundle(
        plan={"setups": []},
        inventory={},
        features={"features": features, "frames": {}, "units": "mm", **manifest},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )
    html = _Traveler(data, [], {}, None).requirements()
    rows = [
        tuple(unescape(re.sub(r"<[^>]+>", "", cell)) for cell in re.findall(r"<td>(.*?)</td>", row))
        for row in re.findall(r"<tr>(.*?)</tr>", html)
    ]
    return [row for row in rows if row]


def _strap(band=(1.99, 3.01), faces=("#410/ADVANCED_FACE[9]/STRAP",), nominal=2.5):
    face = {
        "kind": "face",
        "requirements": ["thickness"],
        "thickness": list(band) if isinstance(band, tuple) else band,
        "precision": {"thickness": 2},
        # One cited drawing source: a sheet carries many dimensions, so it proves nothing.
        "cite": {"thickness": ["drawing.pdf page 1"]},
    }
    if nominal is not None:
        face["thickness_nominal"] = nominal
    return face if faces is None else {**face, "faces": list(faces)}


@pytest.mark.parametrize(
    ("first", "second", "merged"),
    [
        # The same model faces carrying the same known limits: one dimension, printed once.
        (_strap(), _strap(), True),
        # Other faces, equal limits and the same cited sheet (two bores alike): apart.
        (_strap(), _strap(faces=["#118/ADVANCED_FACE[5]/DATUM_B"]), False),
        # No faces declared: nothing shows the two are one dimension.
        (_strap(faces=None), _strap(faces=None), False),
        # The same faces with other limits.
        (_strap(), _strap(band=(2.0, 3.0)), False),
        # A limit or nominal not known is never taken for another feature's.
        (_strap(band="unknown"), _strap(band="unknown"), False),
        (_strap(band=(1.99, "unknown")), _strap(band=(1.99, "unknown")), False),
        (_strap(nominal="unknown"), _strap(nominal="unknown"), False),
        # An omitted nominal is no more known than one declared unknown.
        (_strap(nominal=None), _strap(nominal=None), False),
    ],
)
def test_two_features_share_a_requirement_row_only_on_the_same_faces_and_known_limits(
    first, second, merged
):
    rows = _requirement_rows({"strap_faces": first, "strap_datum_b": second})
    rows = [row for row in rows if "strap" in row[0]]
    if merged:
        assert rows == [("strap faces / strap (datum B)", "thickness 1.99–3.01")]
    else:
        assert [name for name, _ in rows] == ["strap faces", "strap (datum B)"], rows


@pytest.mark.parametrize(
    ("requirement", "limit", "precision"),
    [
        # Half a step past the drawing's decimals: rounded up it would pass a 0.048 error.
        ("position_dia", 0.045, 2),
        ("finish_ra", 0.85, 1),
        # Under one step at that precision: never printed as nothing, rejecting every part.
        ("coaxiality_dia", 0.004, 2),
    ],
)
def test_a_drawing_maximum_never_prints_looser_than_declared(requirement, limit, precision):
    hole = {"kind": "hole", "requirements": [requirement], requirement: limit}
    hole["precision"] = {requirement: precision}
    ((_, limits),) = [row for row in _requirement_rows({"pin_bore": hole}) if row[0] == "pin bore"]
    printed = float(re.findall(r"\d+(?:\.\d+)?", limits)[-1])
    assert 0 < printed <= limit, limits


@pytest.mark.parametrize(
    ("band", "precision"),
    [
        ([5.904, "unknown"], 2),
        (["unknown", 6.096], 2),
        ([6.0, 6.004], 2),
        # Rail-length magnitudes, where significant digits and decimal places differ.
        ([1234.564, "unknown"], 3),
        (["unknown", 1234.567], 3),
        ([1234.5671, 1234.5674], 3),
    ],
)
def test_a_band_not_printable_inward_keeps_each_declared_limit(band, precision):
    # One limit unknown, or too narrow for the drawing's decimals: no known limit prints
    # looser than declared, and the unknown one stays unknown.
    bore = {"kind": "hole", "requirements": ["dia"], "dia": band, "precision": {"dia": precision}}
    ((_, limits),) = [row for row in _requirement_rows({"bore": bore}) if row[0] == "bore"]
    low, high = limits.removeprefix("Ø ").split("–")
    assert low == "?" if band[0] == "unknown" else float(low) >= band[0], limits
    assert high == "?" if band[1] == "unknown" else float(high) <= band[1], limits


def test_a_printed_limit_never_lies_outside_its_declared_band():
    # Known, half-known, too-narrow and maximum limits at any magnitude, any decimals and
    # any drawing precision (or none): what prints lies inside or on the declared band.
    rng = random.Random(140)
    for _ in range(3000):
        scale = rng.choice([1e-3, 0.1, 1.0, 10.0, 1000.0, 5000.0])
        low = round(rng.uniform(-scale, scale), rng.randint(0, 6))
        width = rng.choice([0.0, 1e-4, 4e-3, 0.03, 1.0, 50.0]) * rng.random()
        high = max(low, round(low + width, rng.randint(0, 6)))
        kind = rng.choice(["known", "low", "high", "max"])
        declared = {
            "known": [low, high],
            "low": [low, "unknown"],
            "high": ["unknown", high],
            "max": abs(high) or 0.001,
        }[kind]
        precision = rng.choice([0, 1, 2, 3, 4, None, "unknown"])
        dimension = "position_dia" if kind == "max" else "dia"
        printed = bare(precision).band(declared, None, dimension)
        case = (declared, precision, printed)
        if kind == "max":
            assert 0 < float(printed) <= declared, case
            continue
        ends = printed.split("–")
        assert len(ends) == 2, case
        texts = dict(zip(("low", "high"), ends, strict=True))
        limits = dict(zip(("low", "high"), declared, strict=True))
        for end, limit in limits.items():
            if limit == "unknown":
                assert texts[end] == "?", case
        if limits["low"] != "unknown":
            assert float(texts["low"]) >= limits["low"], case
        if limits["high"] != "unknown":
            assert float(texts["high"]) <= limits["high"], case
        if kind == "known":
            assert float(texts["low"]) <= float(texts["high"]), case


def test_the_drawing_edge_break_never_prints_looser_than_declared():
    rows = _requirement_rows(
        {}, precision=1, general_tolerances={"edge_break_r": 0.25, "chamfer_max": 0.35}
    )
    ((_, limits),) = [row for row in rows if row[0] == "all edges"]
    radius, chamfer = map(float, re.findall(r"\d+\.\d+", limits))
    assert 0 < radius <= 0.25 and 0 < chamfer <= 0.35, limits


@pytest.mark.parametrize(("low", "high"), [(-6.0, -5.9), (-1234.5675, -1234.5671)])
def test_an_authored_z_band_prints_its_limits_as_declared(low, high):
    sheet = bare(2)
    sheet.coordinates_entry = lambda setup, op: {}
    printed = re.findall(r"-?\d+(?:\.\d+)?", sheet.allowed({}, {"to_z_band": [low, high]}))
    assert list(map(float, printed)) == [low, high], printed


@pytest.mark.parametrize("limit", [0.0254, 0.0000125])
def test_a_runout_limit_prints_as_declared(limit):
    sheet, transfer = transfer_sheet(["bore"], "mill")
    line = sheet.transfer_line({"id": "S2"}, {**transfer, "runout_limit_mm": limit})
    printed = re.search(r"(\d+(?:\.\d+)?) mm total indicator reading", line)
    assert printed and float(printed.group(1)) == limit, line
def ledger(features, ops):
    """Exercise the actual operation assembly with already-computed machining fields."""
    from prechips.sheet import _Box

    sheet = shop({})
    sheet.features = features
    sheet.units = "mm"
    sheet.findings = []
    sheet.bundle = SimpleNamespace(features={"units": "mm"}, inventory={"tools": {"c": {}}})
    sheet.setup = {"id": "S1", "ops": ops}
    sheet.feature_name = lambda feature: feature.replace("_", " ")
    sheet.feature_label = lambda feature, marked=True: sheet.feature_name(feature)
    sheet.short_reference = lambda reference, category: f"Gauge {reference}"
    sheet.contour_ops = set()
    sheet.lathe = lambda setup: False
    sheet.cut_depths = lambda setup, op, lathe: op.get("action", [op["do"]])
    sheet.coating = lambda op: op.get("process", "unknown")
    sheet.speeds = lambda setup, op, saw: ("1234", ["0.025 mm/rev", "(31 mm/min)"], False)
    sheet.hole_xy = lambda setup, op: ["tool axis X -25.000, Y +1.250"]
    sheet.tip = lambda setup, op: ["Z -3.125 mm"]
    sheet.relief_plunges = lambda setup, op: []
    sheet.rest_engagement = lambda setup, op: []
    sheet.unset_z = lambda setup, op, target: target
    sheet.crash_boxes = lambda setup, op: [_Box(op["safety"])] if op.get("safety") else []
    sheet.manual_arc_lines = lambda setup, op, stops: []
    sheet.tip_note = lambda setup, op: None
    sheet.direction = lambda direction: direction
    html, notes, worksheets, stops = sheet.operations(
        sheet.setup, {("c", None): "T4"}, {"notes": 2, "contours": 3}
    )
    assert not worksheets
    return Markup(html), notes, stops


def test_task_ledger_preserves_authored_operation_order_fields_and_attached_safety():
    ops = [
        {
            "op": 30,
            "do": "finish_turn",
            "feature": "bore",
            "tool": "c",
            "action": ["Inspect at -3.125 mm", "retain +0.025 mm"],
            "direction": "toward −Z",
            "checks": {"dia": "mic", "position_dia": "dti"},
            "inspection_methods": {"position_dia": "Seat datum A; read at -25.000 mm."},
            "safety": "STOP: unresolved clamp clearance",
            "note": "Keep the part seated until this operation is complete.",
        },
        {"op": 10, "do": "inspect", "feature": "bore", "tool": "c", "direction": "not_applicable"},
    ]
    markup, notes, _ = ledger(
        {"bore": {"dia": [6.33, 6.35], "position_dia": [0.0, 0.025], "position_datums": ["A"]}},
        ops,
    )
    operations = markup.find("operation")
    assert [node["attrs"]["data-op"] for node in operations] == ["30", "10"]
    for node, op in zip(operations, ops, strict=True):
        assert len(markup.find("performed-mark", node)) == 1
        action_text = content(markup.find("op-action", node)[0])
        assert all(action in action_text for action in op.get("action", [op["do"]]))
        for css, values in {
            "op-feature": ["bore"],
            "op-tool": ["T4"],
            "op-speed": ["1234"],
            "op-feed": ["0.025 mm/rev", "(31 mm/min)"],
            "op-target": ["X -25.000, Y +1.250", "Z -3.125 mm"],
            "op-direction": [op["direction"]],
        }.items():
            assert all(value in content(markup.find(css, node)[0]) for value in values)
    first = operations[0]
    assert ops[0]["safety"] in content(first)
    assert ops[0]["note"] in content(markup.find("op-note", first)[0])
    assert ops[0]["safety"] not in content(operations[1])
    records = markup.find("inspection-record", first)
    assert [node["attrs"]["data-requirement"] for node in records] == ["dia", "position_dia"]
    assert all(json.loads(node["attrs"]["data-features"]) == ["bore"] for node in records)
    assert all(len(markup.find("result-field", node)) == 1 for node in records)
    assert "6.330–6.350" in content(records[0])
    assert "0.000–0.025" in content(records[1]) and "A" in content(records[1])
    note_markup = Markup(notes)
    note_entries = [node for node in note_markup.nodes if node["tag"] == "li"]
    assert len(note_entries) == 1
    note = note_entries[0]
    context = note_markup.find("page-context", note)[0]
    assert note["attrs"]["data-page-context"] == content(context)
    assert "S1 op 30" in content(context) and "position" in content(context)
    assert ops[0]["inspection_methods"]["position_dia"] in content(note)
    assert "S1 sheet 2 note 1" in content(records[1])


def test_shared_owner_limit_is_read_once_with_one_associated_result():
    markup, notes, _ = ledger(
        {"left": {"dia": [6.33, 6.35]}, "right": {"dia": [6.33, 6.35]}},
        [
            {
                "op": 50,
                "do": "inspect",
                "feature": ["left", "right"],
                "checks": {"dia": "mic"},
                "inspection_methods": {"dia": "Use the micrometer."},
            }
        ],
    )
    records = markup.find("inspection-record")
    assert len(records) == 1
    assert json.loads(records[0]["attrs"]["data-features"]) == ["left", "right"]
    assert content(records[0]).count("6.330–6.350") == 1
    assert len(markup.find("result-field", records[0])) == 1
    assert notes.count("Use the micrometer.") == 1


def test_distinct_owner_bands_keep_their_result_and_method_associations():
    markup, notes, _ = ledger(
        {"left": {"dia": [6.33, 6.35]}, "right": {"dia": [8.01, 8.03]}},
        [
            {
                "op": 50,
                "do": "inspect",
                "feature": ["left", "right"],
                "checks": {"dia": "mic"},
                "inspection_methods": {"dia": "Use the micrometer."},
            }
        ],
    )
    records = markup.find("inspection-record")
    assert [json.loads(node["attrs"]["data-features"]) for node in records] == [["left"], ["right"]]
    for node, expected, other in (
        (records[0], "6.330–6.350", "8.010–8.030"),
        (records[1], "8.010–8.030", "6.330–6.350"),
    ):
        assert expected in content(node) and other not in content(node)
        assert "S1 sheet 2 note 1" in content(node)
        assert len(markup.find("writing-blank", node)) == 1
    assert notes.count("Use the micrometer.") == 1


def test_missing_requirements_identities_and_process_holds_do_not_get_fake_results():
    markup, notes, _ = ledger(
        {"bore": {"dia": [6.33, 6.35], "position_dia": "unknown"}},
        [
            {
                "op": 50,
                "do": "inspect",
                "feature": "bore",
                "checks": {"dia": "mic", "position_dia": "dti", "unknown": "unknown"},
                "missing_requirements": {"depth": "unknown"},
                "inspection_methods": {"position_dia": "Seat datum A; method remains required."},
                "process_holds": [
                    {
                        "feature": "bore",
                        "requirement": "dia",
                        "band": [6.335, 6.345],
                        "gauge": "mic",
                        "reason": "Retain material for the next operation.",
                    }
                ],
                "inspection_note": "Keep the drawing at the bench.",
            },
            {"op": 60, "do": "inspect", "checks": {"dia": "mic"}},
            {"op": 70, "do": "inspect", "feature": "bore", "checks": "unknown"},
        ],
    )
    assert [node["attrs"]["data-requirement"] for node in markup.find("inspection-record")] == [
        "dia"
    ]
    messages = markup.find("inspection-message")
    assert any(
        "depth" in content(node) and "no drawing limit" in content(node) for node in messages
    )
    assert any(
        "PROCESS HOLD" in content(node) and "6.335–6.345" in content(node) for node in messages
    )
    assert any("position Ø ?" in content(node) for node in messages)
    assert any("inspection checks not set" in content(node) for node in messages)
    assert all(not markup.find("writing-blank", node) for node in messages)
    assert "Seat datum A; method remains required." in notes
    assert "Keep the drawing at the bench." in notes


def test_long_authored_method_and_qualitative_limit_check_keep_their_association():
    method = "Compare the GO and NO-GO sizes without forcing the gauge. " * 400
    markup, notes, _ = ledger(
        {"edge": {"kind": "shaft", "dia": [6.33, 6.35]}},
        [
            {
                "op": 80,
                "do": "inspect",
                "feature": "edge",
                "checks": {"dia": "ring"},
                "go_no_go": {"dia": {"go": 6.33, "no_go": 6.35}},
                "inspection_methods": {"dia": method},
            }
        ],
    )
    record = markup.find("inspection-record")[0]
    assert method.strip() in notes
    assert json.loads(record["attrs"]["data-features"]) == ["edge"]
    assert record["attrs"]["data-requirement"] == "dia"
    assert "GO 6.330 passes over" in content(record)
    assert "NO-GO 6.350 does not" in content(record)
    assert "S1 sheet 2 note 1" in content(record)
    assert len(markup.find("writing-blank", record)) == 1
    label = content(markup.find("field-label", record)[0])
    assert "mm" not in label and "°" not in label


def test_one_shared_shoulder_dimension_keeps_both_faces_and_one_recording_area():
    note = "Shoulder length: caliper across the Ø10 shoulder, north face to thrust face."
    owners = ["shoulder_north_face", "shoulder_thrust"]
    markup, _, _ = ledger(
        {owner: {"kind": "face", "length": [0.99, 2.01]} for owner in owners},
        [
            {
                "op": 71,
                "do": "inspect",
                "feature": owners,
                "note": note,
                "checks": {"length": "calipers"},
            }
        ],
    )
    records = markup.find("inspection-record")
    assert len(records) == 1
    assert json.loads(records[0]["attrs"]["data-features"]) == owners
    assert records[0]["attrs"]["data-requirement"] == "length"
    assert len(markup.find("result-field", records[0])) == 1
    assert len(markup.find("writing-blank", records[0])) == 1
    assert note in content(markup.find("op-action")[0])


def test_authored_multi_location_note_stays_with_one_freeform_requirement_record():
    note = "Mic at both ends and the middle for taper before moving on."
    markup, _, _ = ledger(
        {"pivot_bearing": {"dia": [6.33, 6.35]}},
        [
            {
                "op": 30,
                "do": "finish_turn",
                "feature": "pivot_bearing",
                "tool": "c",
                "note": note,
                "checks": {"dia": "mic"},
            }
        ],
    )
    operation = markup.find("operation")[0]
    assert note in content(markup.find("op-note", operation)[0])
    records = markup.find("inspection-record", operation)
    assert len(records) == 1
    assert json.loads(records[0]["attrs"]["data-features"]) == ["pivot_bearing"]
    assert len(markup.find("result-field", records[0])) == 1
    assert len(markup.find("writing-blank", records[0])) == 1


def picture_sheet(panels):
    sheet = shop({})
    sheet.plan = {"part": "Bracket"}
    sheet.arrival = lambda setup: "stock blank"
    sheet.reference = lambda reference, category: "vise"
    sheet.drawing_revision = lambda: "B"
    sheet.report = {
        "renders": {
            "S1": {
                "path": "renders/S1.png",
                "fixture": "modeled",
                "scene": {
                    "width_px": 1600,
                    "height_px": 2200,
                    "print_panels": panels,
                    "debts": ["not drawn: rear clamp"],
                    "render_debts": ["graphic exaggeration: leader clearance"],
                },
            }
        }
    }
    return sheet


def test_printable_picture_windows_cover_the_canonical_image_once_at_one_scale():
    panels = [
        {"top_px": 0, "height_px": 1400, "role": "setup", "label": "Main setup"},
        {"top_px": 1400, "height_px": 800, "role": "holding_detail", "label": "Rear clamp"},
    ]
    html = picture_sheet(panels).fixture_render({"id": "S1", "hold": {"fixture": "vise"}})
    markup = Markup(html)
    figures = markup.find("fixture-render")
    assert len(figures) == len(panels)
    windows = [node for node in markup.nodes if node["tag"] == "svg"]
    assert [node["attrs"]["viewbox"] for node in windows] == ["0 0 1600 1400", "0 1400 1600 800"]
    images = [node for node in markup.nodes if node["tag"] == "image"]
    assert all(
        node["attrs"]["href"] == "renders/S1.png"
        and node["attrs"]["width"] == "1600"
        and node["attrs"]["height"] == "2200"
        for node in images
    )
    captions = [content(node) for node in markup.nodes if node["tag"] == "figcaption"]
    assert all(
        "Bracket" in caption and "Setup S1" in caption and "rev B" in caption
        for caption in captions
    )
    assert "Main setup" in captions[0] and "Rear clamp" in captions[1]
    assert "NOT SHOWN: rear clamp" in html
    assert "graphic exaggeration: leader clearance" in html


@pytest.mark.parametrize(
    "panels",
    [
        [{"top_px": 0, "height_px": 1400, "role": "setup", "label": "Incomplete"}],
        [
            {"top_px": 0, "height_px": 1400, "role": "setup", "label": "Main"},
            {
                "top_px": 1300,
                "height_px": 900,
                "role": "holding_detail",
                "label": "Repeated pixels",
            },
        ],
    ],
)
def test_printable_picture_windows_never_silently_omit_or_duplicate_source_content(panels):
    with pytest.raises(ValueError):
        picture_sheet(panels).fixture_render({"id": "S1", "hold": {"fixture": "vise"}})


def example_sheet(relative):
    from prechips.inputs import load_bundle

    bundle = load_bundle(Path(__file__).resolve().parents[1] / "examples" / relative)
    return _Traveler(bundle, [], {}, None)


def test_explicit_before_hold_measurement_has_one_field_in_its_original_hold_step():
    sheet = example_sheet("pivot-shaft/plan.toml")
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == "S2")
    sheet.setup = setup
    touch = setup["zero"]["z"]
    assert touch["measure_before_hold"] is True
    markup = Markup(sheet.hold(setup)[0])
    (reading,) = [
        node
        for node in markup.nodes
        if node["tag"] == "li" and sheet.bench(touch["measure"], setup) in content(node)
    ]
    assert sheet.short_reference(touch["gauge"], "gauges") in content(reading)
    assert [content(label) for label in markup.find("field-label", reading)] == ["Z M"]
    assert len(markup.find("writing-blank")) == 1
    assert content(markup.find("writing-blank", reading)[0]) == ""
    for flag in ({}, {"measure_before_hold": False}):
        at_machine = {key: value for key, value in touch.items() if key != "measure_before_hold"}
        at_machine.update(flag)
        held = {**setup, "zero": {**setup["zero"], "z": at_machine}}
        holding = Markup(sheet.hold(held)[0])
        assert not holding.find("writing-blank")
        assert not any(
            sheet.bench(touch["measure"], held) in content(node)
            for node in holding.nodes
            if node["tag"] == "li"
        )


@pytest.mark.parametrize(
    ("relative", "setup_id"),
    [
        ("pivot-shaft/plan.toml", "S3"),
        ("cone-pivot-post/built-up.toml", "S4"),
        ("cone-pivot-post/built-up.toml", "S5"),
    ],
)
def test_datum_transfer_prerequisite_precedes_axis_setting_for_lathe_and_mill(
    monkeypatch, relative, setup_id
):
    monkeypatch.setattr("prechips.sheet.stock_states", lambda bundle, setup: [])
    sheet = example_sheet(relative)
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == setup_id)
    sheet.setup = setup
    transfer_spec = setup["zero"].get("transfer")
    assert isinstance(transfer_spec, dict) and transfer_spec.get("indicate")
    _, tools, _ = sheet.tool_table(setup)
    markup = Markup(sheet.dro(setup, tools))
    transfer = markup.find("zero-transfer")[0]
    axes = markup.find("zero")[0]
    assert markup.nodes.index(transfer) < markup.nodes.index(axes)
    limit = transfer_spec["runout_limit_mm"]
    assert f"{limit} mm total indicator reading" in content(transfer)
    assert len(markup.find("zero-transfer")) == 1
    settings = {}
    for row in markup.nodes:
        if (
            row["tag"] != "tr"
            or row["parent"]["tag"] != "tbody"
            or row["parent"]["parent"] is not axes
        ):
            continue
        cells = [node for node in markup.nodes if node["tag"] == "td" and node["parent"] is row]
        settings[content(cells[0])] = (row, cells[1])
    assert settings
    assert set(settings) == {axis.upper() for axis in ("x", "y", "z") if axis in setup["zero"]}
    if sheet.lathe(setup):
        assert set(settings) == {"X", "Z"}
        assert all(setup["zero"][axis.lower()].get("tool") for axis in settings)
    for axis, (row, contact) in settings.items():
        assert markup.nodes.index(transfer) < markup.nodes.index(row)
        tool = setup["zero"][axis.lower()].get("tool")
        if tool not in (None, "unknown"):
            assert (tools.get(tool) or sheet.short_reference(tool)) in content(contact)
    assert not markup.find("writing-blank", axes)


def test_measured_zero_record_remains_associated_with_its_axis_set_arithmetic(monkeypatch):
    monkeypatch.setattr("prechips.sheet.stock_states", lambda bundle, setup: [])
    sheet = example_sheet("pivot-shaft/plan.toml")
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == "S2")
    sheet.setup = setup
    sheet.records[("zero_check", "S2")] = {
        "axes": {
            "z": {
                "axis_set": "M - 9.0",
                "check_reading": "M - 8.0",
                "mirrored_reading": "M - 10.0",
                "jog_mm": 1.0,
            }
        }
    }
    _, tools, _ = sheet.tool_table(setup)
    markup = Markup(sheet.dro(setup, tools))
    rows = [node for node in markup.nodes if node["tag"] == "tr"]
    row = next(
        row
        for row in rows
        if any(
            node["tag"] == "td" and node["parent"] is row and content(node) == "Z"
            for node in markup.nodes
        )
    )
    assert all(sheet.reading(value) in content(row) for value in ("M - 9.0", "M - 8.0", "M - 10.0"))
    assert sheet.bench(setup["zero"]["z"]["measure"], setup) not in content(row)
    assert "M" in content(row)


def test_feature_map_qualification_is_part_of_its_repeatable_table_header():
    sheet = mapped(
        {
            ("coordinates", "S1"): {
                "x_display": "diameter",
                "rows": [
                    {"feature": "body", "setup": [5.0, 0.0, z], "x_target_mm": 10.0}
                    for z in (0.0, -20.0)
                ],
            }
        },
        {"body": {"kind": "cylinder"}},
        drawing={"body": {"kind": "cylinder", "dia": [9.9, 10.1]}},
        kind="lathe",
    )
    markup = Markup(
        sheet.feature_map({"id": "S1", "ops": [{"op": 10, "do": "turn", "feature": "body"}]})
    )
    table = markup.find("feature-map")[0]
    qualification = markup.find("table-context", table)[0]
    assert qualification["parent"]["tag"] == "thead"
    assert "X reads diameter" in content(qualification)
    assert "not the finished extent" in content(qualification)
    assert "later cut" in content(qualification)
    body = next(node for node in markup.nodes if node["tag"] == "tbody")
    assert markup.nodes.index(qualification) < markup.nodes.index(body)
    assert all(value in content(body) for value in ("Ø9.900–10.100", "Ø10.000", "-20.000"))


@pytest.mark.parametrize("list_only", [False, True])
def test_contour_intros_share_operation_tool_and_all_depth_levels(list_only):
    records = contour_records([-0.25, -0.5, -0.6])
    if list_only:
        numbers = records[("coordinates", "S1")]
        numbers["profiles"] = []
        numbers["arc_table"] = [
            {
                "op": 10,
                "method": "rotary_table",
                "dro_tip_z": -0.6,
                "rotary": {
                    "centre_feature": "ear",
                    "centre_by": "indicate",
                    "convex": True,
                    "table_name": "rotary table",
                    "radius_mm": 10.0,
                    "cutter_radius_mm": 2.0,
                    "offset_mm": 12.0,
                    "rotation": "clockwise",
                    "start_deg": 0.0,
                    "stop_deg": 90.0,
                    "sweep_deg": 90.0,
                    "resolution_deg": 0.5,
                },
            }
        ]
    markup = Markup(shop(records).contours(POCKET, {"c": "T1"}))
    owner = markup.find("contour")[0]
    heading = next(node for node in markup.nodes if node["tag"] == "h3" and node["parent"] is owner)
    context = owner["attrs"]["data-page-context"]
    assert context == content(heading)
    assert all(value in context for value in ("S1 op 10", "T1", "-0.250", "-0.500", "-0.600"))
    content_blocks = (
        [node for node in markup.nodes if node["tag"] == "ol" and node["parent"] is owner]
        if list_only
        else markup.find("coords", owner)
    )
    assert content_blocks
    for block in content_blocks:
        ancestor = block
        while ancestor is not owner:
            ancestor = ancestor["parent"]
        assert ancestor["attrs"]["data-page-context"] == context


def test_operation_readings_keep_authored_sign_precision_and_unit_in_one_inline_token():
    markup, _, _ = ledger(
        {"surface": {"kind": "face", "length": [3.0, 3.2]}},
        [{"op": 10, "do": "face", "feature": "surface", "tool": "c"}],
    )
    operation = markup.find("operation")[0]
    target = content(markup.find("op-target", operation)[0])
    assert all(value in target for value in ("X -25.000", "Y +1.250", "Z -3.125 mm"))
    readings = [content(node) for node in markup.find("reading", operation)]
    assert "X -25.000" in readings and "Y +1.250" in readings
    assert "Z -3.125 mm" in readings and "0.025 mm/rev" in readings


def test_authored_underlines_and_braces_keep_scope_labels_punctuation_and_prompts():
    from prechips.sheet import _list

    source = "Record +X ______ and -X ______; X1 = {X1}. Literal part_id___code."
    markup = Markup(_list([source]))
    assert content(markup.nodes[0]) == ("Record +X  and -X ; X1 = X1. Literal part_id___code.")
    blanks = markup.find("authored-blank")
    assert len(blanks) == 2
    assert all(
        len(markup.find("writing-blank", blank)) == 1
        and len(markup.find("field-label", blank)) == 1
        for blank in blanks
    )
    assert [content(label) for label in markup.find("field-label")] == [
        "Record +X ",
        " and -X ",
        "X1",
    ]


def test_existing_gap_series_keeps_one_authored_area_and_note_continuation_identity():
    from prechips.sheet import _list

    sheet = example_sheet("rocker-arm/plan.toml")
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == "S4")
    op = next(op for op in setup["ops"] if op["op"] == 30)
    source = op["inspection_methods"]["height_above_pivot"]
    note = sheet.note("S4 op 30 top edge height", source)
    markup = Markup(_list([note]))
    owner = next(node for node in markup.nodes if node["tag"] == "li")
    context = markup.find("page-context", owner)[0]
    assert owner["attrs"]["data-page-context"] == content(context)
    steps = markup.find("steps", owner)[0]
    entries = [node for node in markup.nodes if node["tag"] == "li" and node["parent"] is steps]
    assert [content(entry) for entry in entries] == [
        re.sub(r"\{([^{}]+)\}", r"\1", line) for line in note[1]
    ]
    names = [match.group(1) for line in source for match in re.finditer(r"\{([^{}]+)\}", line)]
    assert names
    assert [content(label) for label in markup.find("field-label", owner)] == names
    assert len(markup.find("writing-blank", owner)) == len(names)
    assert not markup.find("inspection-record", owner)


def test_authored_step_fields_keep_numbered_order_and_existing_note_heading():
    from prechips.sheet import _list

    source = ["Read {X1}.", "Record the gaps ______.", "Calculate: result = {result}."]
    note = shop({}).note("S4 op 50 position", source)
    markup = Markup(_list([note]))
    owner = next(node for node in markup.nodes if node["tag"] == "li")
    assert owner["attrs"]["data-page-context"] == "S4 op 50 position:"
    steps = markup.find("steps", owner)[0]
    entries = [node for node in markup.nodes if node["tag"] == "li" and node["parent"] is steps]
    assert [content(entry) for entry in entries] == ["Read X1.", "Record the gaps ."]
    assert content(markup.find("calc", owner)[0]) == "Calculate: result = result."
    assert len(markup.find("authored-blank", owner)) == 1
    assert [content(label) for label in markup.find("field-label", owner)] == [
        "X1",
        "Record the gaps ",
        "result",
    ]


def test_numeric_prose_table_cells_preserve_whole_signed_decimals_and_source_bytes():
    from prechips.sheet import _table

    source = "Limit −1.9875/1.9850, ±0.0050 mm. R799.49 / .0020 in/rev."
    markup = Markup(_table(["fastener"], [[source]]))
    cell = next(node for node in markup.nodes if node["tag"] == "td")
    assert content(cell) == source
    readings = [content(node) for node in markup.find("reading", cell)]
    assert all(
        value in readings
        for value in ("−1.9875", "1.9850", "±0.0050 mm", "R799.49", ".0020 in/rev")
    )


def test_coating_optional_space_is_not_a_dimensional_inspection_record():
    note = "Existing five-place dry-film check; keep its gauge and limits as authored."
    markup, _, _ = ledger(
        {},
        [
            {
                "op": 10,
                "do": "coating",
                "process": "paint",
                "note": note,
                "checks": "unknown",
            }
        ],
    )
    operation = markup.find("operation")[0]
    area = markup.find("process-observations", operation)[0]
    assert "optional" in content(area).casefold()
    assert area["attrs"]["data-process"] == "coating"
    assert not any(
        name in area["attrs"] for name in ("data-feature", "data-features", "data-requirement")
    )
    assert len(markup.find("writing-blank", area)) == 1
    assert not markup.find("inspection-record", operation)
    assert markup.find("inspection-message", operation)
    assert content(markup.find("op-action", operation)[0]) == note
    assert not any(
        unit in content(label)
        for label in markup.find("field-label", area)
        for unit in ("mm", "µm", "inches")
    )


def test_coating_does_not_duplicate_existing_requirement_or_authored_prompt_areas():
    checked, _, _ = ledger(
        {"body": {"kind": "cylinder", "dia": [10.0, 10.2]}},
        [
            {
                "op": 10,
                "do": "coating",
                "feature": "body",
                "process": "paint",
                "checks": {"dia": "mic"},
            }
        ],
    )
    assert len(checked.find("inspection-record")) == 1
    assert not checked.find("process-observations")
    prompted, _, _ = ledger(
        {},
        [{"op": 10, "do": "coating", "process": "paint", "note": "Record the batch ______."}],
    )
    assert len(prompted.find("authored-blank")) == 1
    assert not prompted.find("process-observations")
    other, _, _ = ledger(
        {}, [{"op": 10, "do": "deburr", "note": "Existing five-place dry-film check."}]
    )
    assert not other.find("process-observations")


def test_grouped_clearance_actions_keep_the_supplied_check_in_full_width_rows():
    operations = [
        {"op": op, "do": "pocket", "feature": "surface", "tool": "c"}
        for op in (10, 20, 40, 45, 50, 55)
    ]
    tips = {str(op["op"]): 2.63 if op["op"] in (10, 40, 45) else 2.33 for op in operations}
    numbers = {
        "stacks": [{"op": op["op"], "margin_mm": 5.0} for op in operations],
        "jaw_obstruction": {"jaw_top_z": -2.33},
        "cut_tip_above_jaws_mm": tips,
    }
    reach = reach_records(top="not_applicable", projection=37.0)[("reach", "S1:60")]
    records = {
        ("coordinates", "S1"): {
            "operations": [
                {"op": op["op"], "dro_to_z": 0.3 if op["op"] in (10, 40, 45) else 0.0}
                for op in operations
            ]
        },
        ("headroom", "S1"): numbers,
        **{("reach", f"S1:{op['op']}"): dict(reach) for op in operations},
    }
    sheet = clearance_sheet(records)
    setup = {"id": "S1", "ops": operations}
    supplied = sheet.clearance_rows(setup, numbers, {("c", None): "T1"})
    markup = Markup(sheet.clearance(setup, {("c", None): "T1"}))
    bodies = [node for node in markup.nodes if node["tag"] == "tbody"]
    assert len(bodies) == len(supplied) == 2
    assert [row[0] for row in supplied] == ["10, 40, 45", "20, 50, 55"]
    for body, row in zip(bodies, supplied, strict=True):
        summary = next(
            node for node in markup.nodes if node["tag"] == "tr" and node["parent"] is body
        )
        cells = [node for node in markup.nodes if node["tag"] == "td" and node["parent"] is summary]
        assert [content(cell) for cell in cells] == list(row[:4])
        action = markup.find("see", body)[0]
        assert row[4] in content(action)
        assert "check the tip clears the jaws before plunging" in content(action)
        assert int(action["parent"]["attrs"]["colspan"]) == len(cells)


def test_shaft_fit_up_prose_fields_keep_their_source_and_sole_boxes():
    from prechips.sheet import _list

    sheet = example_sheet("pivot-shaft/plan.toml")
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == "S3")
    sheet.setup = setup
    op = next(op for op in setup["ops"] if op["op"] == 20)
    procedure = op["inspection_note"]
    expected = [sheet.bench(line, setup) for line in procedure]
    names = [match.group(1) for line in expected for match in re.finditer(r"\{([^{}]+)\}", line)]
    markup = Markup(_list([sheet.note("S3 op 20 fit-up", procedure)]))
    steps = markup.find("steps")[0]
    entries = [node for node in markup.nodes if node["tag"] == "li" and node["parent"] is steps]
    assert [content(entry) for entry in entries] == [
        re.sub(r"\{([^{}]+)\}", r"\1", line)
        for line in expected
        if not line.startswith("Calculate:")
    ]
    assert [
        content(markup.find("field-label", field)[0]) for field in markup.find("prose-field")
    ] == (names[:2])
    assert [content(label) for label in markup.find("field-label")] == names
    assert len(markup.find("writing-blank")) == 3
    assert all(len(markup.find("writing-blank", field)) == 1 for field in markup.find("field"))
    calculation = markup.find("calc")[0]
    assert content(calculation) == next(
        re.sub(r"\{([^{}]+)\}", r"\1", line) for line in expected if line.startswith("Calculate:")
    )
    assert not markup.find("prose-field", calculation)


def test_printed_shaft_fit_up_field_has_its_own_line_before_the_next_sentence(printed_sheet):
    from prechips.sheet import _list

    sheet = example_sheet("pivot-shaft/plan.toml")
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == "S3")
    sheet.setup = setup
    op = next(op for op in setup["ops"] if op["op"] == 20)
    source = _list([sheet.note("S3 op 20 fit-up", op["inspection_note"])])
    original = Markup(source)
    printed, layout = printed_sheet(
        source,
        """pageOf => {
          const field = [...document.querySelectorAll('.prose-field')].find(el =>
            el.querySelector('.field-label')?.textContent === 'Z scribe');
          const label = field.querySelector('.field-label'),
            box = field.querySelector('.writing-blank');
          const item = field.closest('li');
          const walker = document.createTreeWalker(item, NodeFilter.SHOW_TEXT);
          let next, node;
          while (node = walker.nextNode()) {
            const index = node.textContent.indexOf('It must read');
            if (index >= 0) {
              next = document.createRange();
              next.setStart(node, index); next.setEnd(node, index + 'It must read'.length);
              break;
            }
          }
          const preceding = document.createRange();
          preceding.setStart(item, 0); preceding.setEndBefore(field);
          const rect = el => {
            const r = el.getBoundingClientRect();
            return {top:r.top, bottom:r.bottom, left:r.left, right:r.right, width:r.width};
          };
          return {
            field:rect(field), label:rect(label), box:rect(box), next:rect(next),
            precedingBottom: Math.max(...[...preceding.getClientRects()].map(r => r.bottom)),
            owner:rect(item), fieldPage:pageOf(field), labelPage:pageOf(label), boxPage:pageOf(box),
            display:getComputedStyle(field).display,
            direction:getComputedStyle(field).flexDirection,
            boxes:item.querySelectorAll('.writing-blank').length
          };
        }""",
    )
    assert [content(node) for node in printed.find("steps")] == [
        content(node) for node in original.find("steps")
    ]
    assert len(printed.find("writing-blank")) == len(original.find("writing-blank")) == 3
    assert layout["display"] == "flex" and layout["direction"] == "column"
    assert layout["boxes"] == 1
    assert layout["fieldPage"] == layout["labelPage"] == layout["boxPage"]
    assert layout["field"]["top"] >= layout["precedingBottom"] - 0.5
    assert layout["next"]["top"] >= layout["field"]["bottom"] - 0.5
    assert layout["label"]["bottom"] <= layout["box"]["top"] + 0.5
    assert layout["box"]["left"] >= layout["field"]["left"] - 0.5
    assert layout["box"]["right"] <= layout["field"]["right"] + 0.5
    assert layout["box"]["bottom"] <= layout["field"]["bottom"] + 0.5
    assert layout["field"]["width"] < layout["owner"]["width"]


@pytest.mark.parametrize(
    "callout", ["Ø6.475–6.495 mm", "#10-32 x 5/8 in", "M5x0.8", "3/8-16", "3/8 in"]
)
def test_printed_compound_callouts_stay_whole_without_losing_source_text(printed_sheet, callout):
    from prechips.sheet import _table

    text = f"Use {callout}; retain the original callout."
    source = _table(["Component", "Size"], [["Authored component", text]], css="fixture")
    original = Markup(source)
    cell = next(node for node in original.nodes if node["tag"] == "td" and content(node) == text)
    assert callout in [content(node) for node in original.find("reading", cell)]
    printed, readings = printed_sheet(
        source,
        """pageOf => [...document.querySelectorAll('.reading')].map(el => {
          const range = document.createRange(); range.selectNodeContents(el);
          const rects = [...range.getClientRects()].filter(r => r.width > 0);
          const cell = el.closest('td').getBoundingClientRect();
          return {text:el.textContent, lines:[...new Set(rects.map(r => r.top))].length,
            fits:rects.every(r => r.left >= cell.left - .5 && r.right <= cell.right + .5)};
        })""",
        prepare="""() => {
          const table = document.querySelector('table');
          table.style.width = '300px';
        }""",
    )
    assert [content(node) for node in printed.nodes if node["tag"] == "td"] == [
        content(node) for node in original.nodes if node["tag"] == "td"
    ]
    whole = [reading for reading in readings if reading["text"] == callout]
    assert len(whole) == 1
    assert whole[0]["lines"] == 1 and whole[0]["fits"]


def test_decimal_before_into_does_not_consume_a_unit_prefix():
    from prechips.sheet import _table

    sentence = "Advance 0.8 into the bore, then withdraw."
    markup = Markup(_table(["Action"], [[sentence]]))
    owner = next(node for node in markup.nodes if node["tag"] == "td")
    assert content(owner) == sentence
    assert [content(node) for node in markup.find("reading", owner)] == ["0.8"]


def test_printed_manual_finishing_action_is_working_body_below_its_step(printed_sheet):
    note = (
        PAINT_NOTE
        + " Keep the masked edges clean and inspect the entire surface under good light."
        + " Allow the coating to dry before removing the masking."
    )
    source = _bench_sheet(
        [{"op": 10, "do": "coating", "feature": "body", "process": "ral-6005", "note": note}]
    )
    original = Markup(source)
    operation = original.find("operation")[0]
    action = original.find("op-action", operation)
    assert len(action) == 1
    assert content(action[0]) == note
    head = original.find("op-head", operation)[0]
    assert not original.find("op-action", head)
    assert len(original.find("performed-mark", operation)) == 1
    assert not any(original.find(css, operation) for css in ("op-speed", "op-feed", "op-target"))
    printed, layout = printed_sheet(
        source,
        """pageOf => {
          const op = document.querySelector('.operation'), head = op.querySelector('.op-head');
          const action = op.querySelector('.op-action');
          const paragraphs = [...action.querySelectorAll('p')];
          return {heading:head.textContent, top:action.getBoundingClientRect().top,
            headingBottom:head.getBoundingClientRect().bottom,
            headingPage:pageOf(head), actionPage:pageOf(action),
            paragraphs:paragraphs.map(p => p.textContent),
            weight:getComputedStyle(paragraphs[0] || action).fontWeight};
        }""",
    )
    assert [content(node) for node in printed.find("op-action")] == [note]
    assert len(printed.find("performed-mark")) == 1
    assert not any(printed.find(css) for css in ("op-speed", "op-feed", "op-target"))
    assert "Step" in layout["heading"] and "10" in layout["heading"]
    assert note not in layout["heading"]
    assert layout["top"] >= layout["headingBottom"] - 0.5
    assert layout["headingPage"] == layout["actionPage"]
    assert layout["paragraphs"] and "".join(layout["paragraphs"]) == note
    assert int(layout["weight"]) < 600


@pytest.fixture
def printed_sheet(tmp_path):
    """Read the real browser's final, reprinted DOM without an extra test dependency."""
    from test_machinist_review import mr

    from prechips.sheet import _CSS, _DUPLEX_JS

    variable = (
        "PRECHIPS_TEST_BROWSER" if "PRECHIPS_TEST_BROWSER" in os.environ else "PRECHIPS_CHROME"
    )
    requested = os.environ.get(variable)
    if requested is not None:
        executable = Path(requested)
        if not executable.is_file():
            pytest.fail(f"{variable} does not name a browser: {requested}")
    else:
        try:
            executable = mr.find_chrome()
        except FileNotFoundError:
            pytest.skip("Chromium-family browser not found; set PRECHIPS_TEST_BROWSER")

    requests = []

    class DenyProxy(BaseHTTPRequestHandler):
        def deny(self):
            requests.append((self.command, self.path))
            self.send_response(403)
            self.end_headers()

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_CONNECT = deny

        def log_message(self, format, *args):
            pass

    proxy = HTTPServer(("127.0.0.1", 0), DenyProxy)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    canary = f"http://127.0.0.1:{proxy.server_port}/browser-fixture-positive-control"

    def print_html(source, probe, prepare=None):
        document = tmp_path / "traveler.html"
        document.write_text(
            '<!doctype html><html><head><meta charset="utf-8">'
            f"<style>{_CSS}</style><script>{_DUPLEX_JS}</script></head><body>"
            '<section class="page" data-sheet="SETUP S1 sheet 1" data-part="boundary part" '
            'data-drawing="boundary drawing" data-revision="A">'
            + source
            + '</section><img style="position:absolute;width:0;height:0" '
            + f'src="{canary}" alt=""><script>'
            + (f"addEventListener('DOMContentLoaded', {prepare});" if prepare else "")
            + "addEventListener('load', () => {"
            + "const capture = () => {"
            + "document.documentElement.classList.add('print-measuring');"
            + "document.body.style.cssText = "
            + "'max-width:none;width:var(--page-content-width);margin:0;padding:0';"
            + "const section = document.querySelector('section.page');"
            + "const tops = [section.getBoundingClientRect().top, "
            + "...[...section.querySelectorAll('.cont-head')].map(el => "
            + "el.getBoundingClientRect().top)];"
            + "const pageOf = el => tops.findLastIndex(top => "
            + "top <= el.getBoundingClientRect().top + .01);"
            + "const overflows = [...section.querySelectorAll('table')].filter(el => "
            + "el.getBoundingClientRect().bottom + "
            + "parseFloat(getComputedStyle(el).marginBottom) - tops[pageOf(el)] > "
            + "Number(document.documentElement.dataset.pageCapacity) + .01).length;"
            + f"return {{html: section.innerHTML, details: ({probe})(pageOf), overflows, "
            + "pages: Number(section.dataset.pages), "
            + "blankBack: !!section.nextElementSibling?.classList.contains('blank-side'), "
            + "error: document.documentElement.dataset.paginationError || null}; };"
            + "const first = capture(); dispatchEvent(new Event('beforeprint'));"
            + "const result = capture(); result.idempotent = "
            + "JSON.stringify(first) === JSON.stringify(result);"
            + "const report = document.createElement('script');"
            + "report.type = 'application/json'; report.id = 'print-result';"
            + "report.textContent = JSON.stringify(result); document.body.append(report);"
            + "});</script></body></html>",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                executable,
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--disable-default-apps",
                "--disable-domain-reliability",
                "--disable-quic",
                "--no-pings",
                f"--proxy-server=http://127.0.0.1:{proxy.server_port}",
                "--proxy-bypass-list=<-loopback>",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
                f"--user-data-dir={tmp_path / 'browser-profile'}",
                "--virtual-time-budget=1000",
                "--dump-dom",
                document.as_uri(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert ("GET", canary) in requests, "The local positive control bypassed the deny proxy"
        rendered = Markup(result.stdout)
        report = next(
            (node for node in rendered.nodes if node["attrs"].get("id") == "print-result"), None
        )
        assert report is not None, result.stderr
        output = json.loads(content(report))
        assert output["error"] is None, output["error"]
        assert output["idempotent"]
        assert output["overflows"] == 0
        assert output["blankBack"] == (output["pages"] % 2 == 1)
        return Markup(output["html"]), output["details"]

    try:
        yield print_html
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join()


@pytest.mark.parametrize("column", [1, 2])
def test_printed_tool_fragments_keep_every_value_under_its_original_heading(printed_sheet, column):
    sheet = example_sheet("rocker-arm/plan.toml")
    words = " ".join(f"AuthoredWord{index:04}" for index in range(180))
    sheet.tool_name = lambda reference: words if column == 1 else "Authored cutter"
    sheet.tool_detail = lambda reference, holder: [words if column == 2 else "Authored detail"]
    sheet.short_reference = lambda reference, category: "Authored holder"
    setup = {
        "id": "S1",
        "machine": "mill",
        "ops": [{"op": 30, "do": "pocket", "tool": "c", "holder": "h"}],
    }
    _, _, source = sheet.tool_table(setup)
    original = Markup(source)
    expected = [content(node) for node in original.nodes if node["tag"] == "td"]
    printed, _ = printed_sheet(source, "() => null")
    tables = [node for node in printed.nodes if node["tag"] == "table"]
    assert len(tables) > 1
    values = [[] for _ in expected]
    for table in tables:
        body_rows = [
            node
            for node in printed.nodes
            if node["tag"] == "tr"
            and node["parent"]["tag"] == "tbody"
            and node["parent"]["parent"] is table
        ]
        for row in body_rows:
            cells = [
                node for node in printed.nodes if node["tag"] == "td" and node["parent"] is row
            ]
            assert len(cells) == len(expected)
            assert all(cell["attrs"].get("colspan", "1") == "1" for cell in cells)
            for target, cell in zip(values, cells, strict=True):
                target.append(content(cell))
    assert ["".join(parts) for parts in values] == expected


def test_printed_inspection_continuations_repeat_the_whole_operation_without_marks(printed_sheet):
    from prechips.sheet import _Inspection, _Note, _Row, _table

    headings = ["op", "action", "feature", "tool", "rpm", "feed", "Z", "direction", "inspect"]
    checks = [
        _Inspection(f"Existing requirement {index}", ("bore",), f"requirement {index}", "mm")
        for index in range(14)
    ]
    note = "Keep the original datum seated until all these existing checks are complete."
    row = _Row(
        (
            "30",
            "Inspect the bored face",
            "bore",
            "T4 cutter",
            "1234",
            "0.025 mm/rev",
            "Z -3.125 mm",
            "toward −Z",
            checks,
        ),
        [_Note(note)],
    )
    source = _table(headings, [row], css="operations")
    printed, _ = printed_sheet(source, "() => null")
    bodies = printed.find("operation")
    assert len(bodies) > 1
    assert len(printed.find("performed-mark")) == 1
    assert len(printed.find("inspection-record")) == len(checks)
    for body in bodies:
        assert "Inspect the bored face" in content(printed.find("op-action", body)[0])
        for css, expected in zip(
            ("feature", "tool", "speed", "feed", "target", "direction"), row[2:8], strict=True
        ):
            assert content(printed.find("op-" + css, body)[0]).endswith(expected)
        assert note in content(body)
        if printed.find("operation-continuation", body):
            assert "(continued)" in content(printed.find("op-number", body)[0])
            assert not printed.find("performed-mark", body)


def test_printed_contour_fragments_keep_their_exact_local_introduction(printed_sheet):
    records = contour_records([-0.25, -0.5, -0.6])
    numbers = records[("coordinates", "S1")]
    numbers["profiles"] = []
    numbers["line_table"] = [
        {
            "op": 10,
            "side": side,
            "sequence": sequence,
            "stage": "finish",
            "dro_tip_z": -0.6,
            "setup_xy": [[x, float(index)] for index in range(69)],
            "dro_xy": [[x, float(index)] for index in range(69)],
            "jog": ["Y"] * 69,
        }
        for side, x, sequence in (("-X", -1.0, 0), ("+X", 1.0, 2))
    ]
    numbers["arc_table"] = [
        {
            "op": 10,
            "method": "stairs",
            "sequence": 1,
            "stage": "finish",
            "dro_tip_z": -0.6,
            "centre_setup_xy": [0.0, 0.0],
            "cutter_centre_radius_mm": 10.0,
            "rows": [{"dro_xy": [0.0, float(index)], "jog": "X"} for index in range(69)],
        }
    ]
    source = shop(records).contours(POCKET, {"c": "T1"})
    original = Markup(source)
    introductions = {
        float(
            content(next(node for node in original.find("num", table) if content(node)))
        ): content(original.find("table-context", table)[0])
        for table in original.find("coords")
    }
    op_notes = [content(note) for note in original.find("contour-context")]
    assert op_notes
    printed, _ = printed_sheet(source, "() => null")
    tables = printed.find("coords")
    assert len(tables) > 2
    assert len([node for node in printed.nodes if node["tag"] == "tbody"]) == 207
    assert len(set(introductions.values())) == 3
    for table in tables:
        first = next(node for node in printed.find("num", table) if content(node))
        local = introductions[float(content(first))]
        contexts = [content(node) for node in printed.find("table-context", table)]
        assert contexts.count(local) == 1
        assert set(contexts).intersection(introductions.values()) == {local}
        if "data-duplex-split" in table["attrs"]:
            for note in op_notes:
                assert contexts.count(note) == 1
                assert contexts.index(note) < contexts.index(local)
        assert content(printed.find("repeat", table)[0]) == content(original.find("repeat")[0])


def test_printed_authored_calculations_and_boxes_never_separate(printed_sheet):
    from prechips.sheet import _list

    sheet = example_sheet("rocker-arm/plan.toml")
    setup = next(setup for setup in sheet.plan["setups"] if setup["id"] == "S4")
    op = next(op for op in setup["ops"] if op["op"] == 50)
    procedure = op["inspection_methods"]["position_dia"]
    note = sheet.note("S4 op 50 position Ø", procedure)
    source = _list([note]).replace("<ol>", '<ol start="8">', 1)
    original = Markup(source)
    expected = [content(node) for node in original.find("authored-blank")]
    printed, fields = printed_sheet(
        source,
        """pageOf => [...document.querySelectorAll('.authored-blank')].map(field => ({
          label: field.querySelector('.field-label')?.textContent,
          labelPage: pageOf(field.querySelector('.field-label')),
          blankPage: pageOf(field.querySelector('.writing-blank')),
          fits: field.getBoundingClientRect().bottom - tops[pageOf(field)] <=
            Number(document.documentElement.dataset.pageCapacity) + .01,
          height: field.querySelector('.writing-blank').getBoundingClientRect().height
        }))""",
    )
    assert len(printed.find("record-continuation")) > 0
    assert [content(node) for node in printed.find("authored-blank")] == expected
    assert all(
        field["label"].strip()
        and field["labelPage"] == field["blankPage"]
        and field["fits"]
        and field["height"] >= 20 * 96 / 25.4
        for field in fields
    )
    for item in (node for node in printed.nodes if node["tag"] == "li"):
        first = next((node for node in printed.nodes if node["parent"] is item), None)
        assert first is None or "authored-blank" not in first["attrs"].get("class", "").split()


def test_printed_procedure_lead_in_moves_with_its_numbered_steps(printed_sheet):
    sheet = example_sheet("rocker-arm/plan.toml")
    setup = sheet.plan["setups"][0]
    sheet.setup = setup
    _, tools, _ = sheet.tool_table(setup)
    source = '<div style="height:800px"></div>' + sheet.dro(setup, tools)
    _, groups = printed_sheet(
        source,
        """pageOf => [...document.querySelectorAll('p + ol')].map(list => ({
          intro: pageOf(list.previousElementSibling),
          steps: [...list.children].map(pageOf)
        }))""",
    )
    assert groups
    assert all(group["steps"] and set(group["steps"]) == {group["intro"]} for group in groups)


def test_printed_fixture_rows_repeat_their_own_title_not_the_following_fixture(printed_sheet):
    from test_sheet_fixture import TURNED, bundle

    data = bundle([{"fixture": "plate", "pose": TURNED}])
    fixture = data.inventory["fixtures"]["plate"]
    fixture["solids"] = [
        {**fixture["solids"][0], "name": f"component {index}", "size_mm": [10 + index, 20, 5]}
        for index in range(45)
    ]
    sheet = _Traveler(data, [], {}, None)
    setup = data.plan["setups"][0]
    source = sheet.shop_made_table(setup, "plate", [("C1", TURNED)]) + sheet.shop_made_table(
        setup, "plate", [("LOC2", TURNED)]
    )
    printed, _ = printed_sheet(source, "() => null")
    tables = [node for node in printed.nodes if node["tag"] == "table"]
    assert len(tables) > 2
    titles = [content(printed.find("repeat", table)[0]) for table in tables]
    assert any("C1" in title for title in titles) and any("LOC2" in title for title in titles)
    for title, table in zip(titles, tables, strict=True):
        assert "(continued)" in title and "SHOP-MADE FIXTURE" in title
        assert not ("C1" in title and "LOC2" in title)
        assert printed.find("repeat", table)[0]["parent"]["tag"] == "thead"


@pytest.mark.parametrize("column", range(8))
def test_printed_eight_column_row_fragments_preserve_all_slots(printed_sheet, column):
    from prechips.sheet import _table

    values = [f"Owned by column {index}" for index in range(8)]
    values[column] = " ".join(f"AuthoredWord{index:04}" for index in range(60))
    headings = [f"Column {index}" for index in range(8)]
    printed, _ = printed_sheet(_table(headings, [values]), "() => null")
    tables = [node for node in printed.nodes if node["tag"] == "table"]
    assert len(tables) > 1
    reconstructed = [[] for _ in values]
    for table in tables:
        header = [
            content(node)
            for node in printed.nodes
            if node["tag"] == "th" and node["parent"]["parent"]["parent"] is table
        ]
        assert header == headings
        rows = [
            node
            for node in printed.nodes
            if node["tag"] == "tr"
            and node["parent"]["tag"] == "tbody"
            and node["parent"]["parent"] is table
        ]
        for row in rows:
            cells = [
                node for node in printed.nodes if node["tag"] == "td" and node["parent"] is row
            ]
            assert len(cells) == 8
            assert all(cell["attrs"].get("colspan", "1") == "1" for cell in cells)
            for target, cell in zip(reconstructed, cells, strict=True):
                target.append(content(cell))
    assert ["".join(parts) for parts in reconstructed] == values


@pytest.mark.parametrize("case", ["note", "main", "tool", "direction", "intro", "label"])
def test_printed_unbounded_authored_context_makes_finite_original_progress(printed_sheet, case):
    from prechips.sheet import _Inspection, _list, _Note, _Row, _table

    words = (
        "Measure the existing datum with the original inspection gauge and keep the part fully "
        "seated before recording each reading".split()
        * 40
    )[:600]
    prose = " ".join(words)
    headings = ["op", "action", "feature", "tool", "rpm", "feed", "Z", "direction", "inspect"]
    check = _Inspection(
        "Bore diameter 6.330–6.350 mm: use the existing micrometer.",
        ("bore",),
        "diameter",
        "mm",
    )
    cells = (
        "30",
        "Inspect the bore",
        "bore",
        "T4 cutter",
        "1234",
        "0.025 mm/rev",
        "Z -3.125 mm",
        "toward −Z",
        [check],
    )
    if case == "note":
        source = _table(headings, [_Row(cells, [_Note(prose)])], css="operations")
    elif case == "main":
        source = _table(headings, [_Row((cells[0], prose, *cells[2:]))], css="operations")
    elif case in {"tool", "direction"}:
        values = list(cells)
        values[3 if case == "tool" else 7] = prose
        source = _table(headings, [_Row(values)], css="operations")
    elif case == "intro":
        source = _table(
            ["X", "Y", "Z"],
            [[str(index), "1.000", "-3.125"] for index in range(70)],
            css="coords",
            repeat="S1 op 30 — bore · T4 cutter · Z -3.125",
            context="Straight joins on the -X side; " + prose,
        )
    else:
        source = _list([_Note("S1 op 30 inspection: " + prose + " ______", "S1 op 30 inspection:")])
    printed, details = printed_sheet(
        source,
        """pageOf => {
          const section = document.querySelector('section.page');
          const authored = el => !el.closest('[data-duplex], thead, .record-continuation');
          const join = selector => [...section.querySelectorAll(selector)]
            .filter(authored).map(el => el.textContent).join('');
          const pages = new Set();
          for (const row of section.querySelectorAll('tbody > tr:not([data-duplex])')) {
            pages.add(pageOf(row));
          }
          for (const el of section.querySelectorAll('p.table-intro, li')) {
            if (!authored(el)) continue;
            const own = el.cloneNode(true);
            own.querySelectorAll('.record-continuation, .page-context')
              .forEach(context => context.remove());
            if (/[\\p{L}\\p{N}]/u.test(own.textContent) || own.querySelector('.writing-blank')) {
              pages.add(pageOf(el));
            }
          }
          return {
            pages: Number(section.dataset.pages), sourcePages: [...pages].sort((a, b) => a - b),
            notes: join('.op-note'), actions: join('.op-action'),
            tools: join('.op-tool dd'), directions: join('.op-direction dd'),
            fieldLabels: [...section.querySelectorAll('.op-details > div')].filter(authored)
              .every(field => !field.querySelector('dd') || !!field.querySelector('dt')),
            intros: join('p.table-intro'),
            labels: join('.authored-label, .authored-blank .field-label'),
            fields: [...section.querySelectorAll('.authored-blank')].map(field => ({
              label: field.querySelector('.field-label').textContent,
              labelPage: pageOf(field.querySelector('.field-label')),
              boxPage: pageOf(field.querySelector('.writing-blank')),
              fits: field.getBoundingClientRect().bottom - tops[pageOf(field)] <=
                Number(document.documentElement.dataset.pageCapacity) + .01
            }))
          };
        }""",
    )
    assert 1 < details["pages"] < 20
    assert details["sourcePages"] == list(range(details["pages"]))
    key = {
        "note": "notes",
        "main": "actions",
        "tool": "tools",
        "direction": "directions",
        "intro": "intros",
        "label": "labels",
    }[case]
    expected = "Straight joins on the -X side; " + prose if case == "intro" else prose
    if case == "label":
        expected = " " + expected
    assert details[key].rstrip() == expected
    assert len(printed.find("performed-mark")) == (case in {"note", "main", "tool", "direction"})
    assert len(printed.find("writing-blank")) == (case != "intro")
    assert details["fieldLabels"]
    if case == "label":
        (field,) = details["fields"]
        assert field["label"].strip()
        assert field["labelPage"] == field["boxPage"] and field["fits"]


def test_printed_running_header_retains_working_context_and_measured_final_count(printed_sheet):
    from prechips.sheet import _list, _Note

    context = "S4 op 50 — original face · T4 · Z -3.125 mm"
    source = _list(
        [
            _Note(
                context
                + ": "
                + "Keep the existing datum seated and record the authored measurement. " * 600,
                context,
            )
        ]
    )
    _, details = printed_sheet(
        source,
        """pageOf => {
          const section = document.querySelector('section.page');
          const pages = Number(section.dataset.pages);
          const source = section.querySelector('.page-context');
          return {
            pages, workingFont: getComputedStyle(source).fontSize,
            heads: [...section.querySelectorAll('.cont-head')].map(head => {
              const context = head.querySelector('.cont-context');
              const count = head.querySelector('.cont-count');
              const total = head.querySelector('.cont-page-total');
              const before = head.getBoundingClientRect().height;
              if (total) total.textContent = '?';
              const reserved = head.getBoundingClientRect().height;
              if (total) total.textContent = String(pages);
              const after = head.getBoundingClientRect().height;
              return {
                text: head.textContent, context: context?.textContent || null,
                font: context ? getComputedStyle(context).fontSize : null,
                readings: context ? [...context.querySelectorAll('.reading')].map(reading => {
                  const range = document.createRange(); range.selectNodeContents(reading);
                  return {text: reading.textContent, lines: range.getClientRects().length};
                }) : [],
                countFits: !!count && count.getBoundingClientRect().width
                  <= head.getBoundingClientRect().width,
                before, reserved, after
              };
            })
          };
        }""",
    )
    assert details["pages"] >= 10
    assert len(details["heads"]) == details["pages"] - 1
    for page, head in enumerate(details["heads"], 2):
        assert head["context"] == context
        assert head["font"] == details["workingFont"]
        assert f"(continued)\n · page {page} of {details['pages']}\n{context}" in head["text"]
        assert {"text": "Z -3.125 mm", "lines": 1} in head["readings"]
        assert head["countFits"]
        assert head["before"] == head["reserved"] == head["after"]


@pytest.mark.parametrize("kind", ["caption", "context"])
def test_printed_near_cap_atomic_source_uses_its_actual_continuation_body(printed_sheet, kind):
    from prechips.sheet import _list, _Note

    source = _list(
        [_Note("S4 op 50 inspection: Record the existing datum ______", "S4 op 50 inspection:")]
    )
    short_label = (
        "Keep this short authored caption atomic together with its existing recording box "
        "and preserve the original gauge, datum and instruction without alteration"
    )
    short_source = _list(
        [
            _Note(
                "S4 op 50 inspection: "
                + "Keep the existing datum seated and record the authored measurement. " * 70
                + short_label
                + " ______.",
                "S4 op 50 inspection:",
            )
        ]
    )
    _, short = printed_sheet(
        short_source,
        """pageOf => ({
          prose: document.querySelectorAll('.authored-label').length,
          fields: document.querySelectorAll('.authored-blank').length,
          boxes: document.querySelectorAll('.writing-blank').length,
          label: document.querySelector('.authored-blank .field-label').textContent.trim()
        })""",
    )
    assert short == {"prose": 0, "fields": 1, "boxes": 1, "label": short_label}
    prepare = """() => {
      const root = document.documentElement, body = document.body;
      const saved = body.getAttribute('style');
      root.classList.add('paged', 'print-measuring');
      body.style.cssText = 'max-width:none;width:var(--page-content-width);margin:0;padding:0';
      const measure = document.createElement('div');
      measure.style.height = 'var(--page-content-height)'; body.append(measure);
      const cap = measure.getBoundingClientRect().height
        - parseFloat(getComputedStyle(root).getPropertyValue('--page-rounding'));
      measure.remove();
      const kind = KIND;
      const field = document.querySelector(
        kind === 'caption' ? '.authored-blank' : '.page-context');
      const label = kind === 'caption' ? field.querySelector('.field-label') : field;
      const prefix = kind === 'context'
        ? [...label.childNodes].map(node => node.cloneNode(true)) : [];
      const words = ('Measure the original datum with the existing gauge '
        + 'before writing the reading ').repeat(250).trim().split(/\\s+/);
      const set = n => {
        const text = words.slice(0, n).join(' ') + ' final reading';
        label.replaceChildren(...prefix.map(node => node.cloneNode(true)),
          document.createTextNode((kind === 'context' ? ' ' : '') + text));
      };
      const height = () => {
        const box = field.getBoundingClientRect(), style = getComputedStyle(field);
        return box.height + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
      };
      let low = 1, high = words.length, best = 0;
      while (low <= high) {
        const middle = (low + high) >> 1; set(middle);
        if (height() <= cap) {best = middle; low = middle + 1;} else high = middle - 1;
      }
      set(best);
      if (kind === 'context') {
        field.closest('[data-page-context]').dataset.pageContext = label.textContent;
      }
      window.nearCapInput = {kind, cap, height: height(), text: label.textContent};
      root.classList.remove('paged', 'print-measuring');
      if (saved === null) body.removeAttribute('style'); else body.setAttribute('style', saved);
    }""".replace("KIND", json.dumps(kind))
    _, details = printed_sheet(
        source,
        """pageOf => {
          const section = document.querySelector('section.page');
          const heads = [...section.querySelectorAll('.cont-head')];
          const tops = [section.getBoundingClientRect().top,
            ...heads.map(head => head.getBoundingClientRect().top)];
          const original = el => !el.closest('[data-duplex], .record-continuation, .cont-head');
          const selector = window.nearCapInput.kind === 'caption'
            ? '.authored-label, .authored-blank .field-label' : '.page-context';
          const reconstructed = [...section.querySelectorAll(selector)].filter(original)
            .map(el => el.textContent).join('');
          const fields = [...section.querySelectorAll('.authored-blank')];
          const sourcePages = new Set();
          for (const item of section.querySelectorAll('li')) {
            if (!original(item)) continue;
            const own = item.cloneNode(true);
            own.querySelectorAll('[data-duplex], .record-continuation, .writing-blank')
              .forEach(el => el.remove());
            if (/[\\p{L}\\p{N}]/u.test(own.textContent)) sourcePages.add(pageOf(item));
          }
          return {
            input: window.nearCapInput, reconstructed, pages: Number(section.dataset.pages),
            sourcePages: [...sourcePages].sort((a, b) => a - b),
            contextFont: getComputedStyle(section.querySelector('.page-context')).fontSize,
            heads: heads.map(head => ({
              font: getComputedStyle(head.querySelector('.cont-context')).fontSize,
              readings: [...head.querySelectorAll('.cont-context .reading')]
                .map(node => node.textContent)
            })),
            fields: fields.map(field => {
              const label = field.querySelector('.field-label'),
                box = field.querySelector('.writing-blank');
              const rect = field.getBoundingClientRect(), style = getComputedStyle(field);
              return {
                label: label.textContent, boxes: field.querySelectorAll('.writing-blank').length,
                samePage: pageOf(label) === pageOf(box),
                fits: rect.bottom + parseFloat(style.marginBottom) - tops[pageOf(field)]
                  <= window.nearCapInput.cap + .01,
                available: window.nearCapInput.cap
                  - (rect.top - parseFloat(style.marginTop) - tops[pageOf(field)])
              };
            })
          };
        }""",
        prepare,
    )
    assert details["input"]["height"] <= details["input"]["cap"]
    assert details["pages"] > 1
    assert details["sourcePages"] == list(range(details["pages"]))
    assert details["reconstructed"] == details["input"]["text"]
    assert details["heads"]
    for head in details["heads"]:
        assert head["font"] == details["contextFont"]
        assert "50" in head["readings"]
    (field,) = details["fields"]
    assert details["input"]["height"] > field["available"]
    assert field["label"].strip()
    assert field["boxes"] == 1 and field["samePage"] and field["fits"]
