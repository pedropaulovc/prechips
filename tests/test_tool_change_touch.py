"""One DRO per setup: a tool that did not set it is touched off before it cuts."""

import math
import re
import subprocess
from html import unescape
from types import SimpleNamespace

import pytest
from test_kernel_geometry import Engine

from prechips.rules.zero_recipe import evaluate
from prechips.sheet import _Traveler

DRO = {
    "controller": "el400",
    "mode": "abs",
    "radius_mode": False,
    "direction": {"x": "away_from_spindle_axis", "y": "away", "z": "toward_exposed_end"},
}


def bundle(machine, zero, ops, stock_state=None):
    data = SimpleNamespace(
        plan={
            "dro": DRO,
            "setups": [
                {
                    "id": "S1",
                    "machine": machine,
                    "frame": "F",
                    "zero": zero,
                    "stock_state": stock_state or {},
                    "ops": ops,
                }
            ],
        },
        features={"frames": {"F": {"binding": "nominal"}}, "features": {"journal": {}}},
        inventory={
            "machines": {"lathe": {"kind": "lathe"}, "mill": {"kind": "mill"}},
            "tools": {
                name: {"kind": kind, "tip_in": 0.2}
                for name, kind in (
                    ("turner", "insert_holder"),
                    ("parter", "parting_blade"),
                    ("finder", "edge_finder"),
                    ("centre", "center_drill"),
                    ("drill", "drill"),
                    ("mill", "endmill"),
                )
            },
            "gauges": {"mic": {"kind": "micrometer"}},
        },
        policy={},
    )
    data.feature_definitions = data.features["features"]
    return data


def op(number, do, feature, tool, **extra):
    return {"op": number, "do": do, "feature": feature, "tool": tool, **extra}


def lathe_zero(touches):
    return {
        "x": {
            "feature": "spindle_axis",
            "edge_mm": 0.0,
            "from": "+x",
            "method": "trial_cut_measure",
            "tool": "turner",
            "gauge": "mic",
            "check_jog_mm": 10.0,
        },
        "z": {
            "face": "stub end",
            "edge_mm": 5.0,
            "from": "+z",
            "method": "touch",
            "tool": "turner",
            "paper_mm": 0.0,
            "check_jog_mm": 10.0,
            "retouch_after": [],
        },
        "tool_touches": touches,
    }


# The shoulder faces the free end (the turner faced it from +Z): the blade meets it with
# its chuck-side corner, from +Z, so its paper stands it off toward the free end. Its X
# is on the journal the turner turned, through the same paper.
BLADE = {
    "tool": "parter",
    "x_method": "touch the journal just measured",
    "x_face": "journal",
    "x_paper_mm": 0.05,
    "gauge": "mic",
    "z_face": "shoulder",
    "edge_mm": -7.5,
    "paper_mm": 0.05,
    "method": "paper",
    "corner": "chuck_side",
    "before_ops": [40],
}
LATHE_OPS = [
    op(10, "rough_turn", "journal", "turner"),
    op(20, "face", "shoulder", "turner", to_z=-7.5),
    op(30, "finish_turn", "journal", "turner"),
    op(40, "form_relief", "relief", "parter"),
]


def test_the_turning_tool_back_after_a_blade_touch_is_re_touched():
    ops = [*LATHE_OPS, op(50, "face", "dome", "turner", to_z=0.0)]
    finding = evaluate(bundle("lathe", lathe_zero([BLADE]), ops))[0]
    assert finding.status == "pass"
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    # Z repeats the blade's touch on the shoulder; X touches the last diameter turned.
    assert touch["before_ops"] == [50] and touch["tool"] == "turner"
    assert (touch["z_face"], touch["edge_mm"], touch["paper_mm"]) == ("shoulder", -7.5, 0.05)
    assert touch["z_axis_set"] == pytest.approx(-7.45)
    # The blade's own recipe ("paper", its corner) is not the turning tool's.
    assert touch["method"] == "edge_then_set"
    assert (touch["x_face"], touch["gauge"], touch["x_axis_set"]) == (
        "journal",
        "mic",
        "measured D",
    )


def test_a_blade_that_finishes_the_setup_needs_no_re_touch():
    finding = evaluate(bundle("lathe", lathe_zero([BLADE]), LATHE_OPS))[0]
    assert finding.status == "pass"
    assert finding.numbers["derived_touches"] == []


def test_a_lathe_tool_change_with_no_diameter_to_touch_is_an_error():
    # The blade's X came from its own trial cut: no measured diameter stands for the
    # turning tool to touch, so its X Axis Set cannot be derived.
    touch = {**BLADE, "x_method": "trial_cut_measure", "before_ops": [20]}
    ops = [
        op(10, "face", "shoulder", "turner", to_z=-7.5),
        op(20, "part_off", "relief", "parter"),
        op(30, "face", "dome", "turner", to_z=0.0),
    ]
    finding = evaluate(bundle("lathe", lathe_zero([touch]), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "turner", "axes": ["x"], "dro_set_by": "parter"}
    ]


def test_a_turned_diameter_formed_away_is_no_longer_touched():
    # The nose turned in op 10 is formed into a dome in op 20: no cylinder is left to
    # touch the blade off on, so its X needs a planned touch.
    ops = [
        op(10, "turn", "nose", "turner"),
        op(20, "form_dome", "nose", "turner"),
        op(30, "part_off", "relief", "parter"),
    ]
    data = bundle("lathe", lathe_zero([]), ops)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "parter", "axes": ["x"], "dro_set_by": "turner"}
    ]
    # The sheet stops the operator at that op instead of printing a touch.
    html = _Traveler(data, [finding], {}, {}).dro(data.plan["setups"][0], {})
    assert "STOP: before op 30" in html and "no X touch" in html


def test_a_diameter_a_touch_names_only_in_words_is_not_tracked_for_the_next_tool():
    # Nothing was turned in the setup; the blade's touch surface is prose whose survival
    # past the blade's own cut the rule cannot follow, so the turner's X is planned.
    ops = [
        op(10, "face", "shoulder", "turner", to_z=-7.5),
        op(20, "form_relief", "relief", "parter"),
        op(30, "face", "dome", "turner", to_z=0.0),
    ]
    words = {key: value for key, value in BLADE.items() if key != "x_face"}
    finding = evaluate(bundle("lathe", lathe_zero([{**words, "before_ops": [20]}]), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "turner", "axes": ["x"], "dro_set_by": "parter"}
    ]


def mill_zero(z, retouch_after=()):
    return {
        "x": {"edge": "left", "edge_mm": 0.0, "from": "-x", "tool": "finder", "check_jog_mm": 5},
        "y": {"edge": "front", "edge_mm": 0.0, "from": "-y", "tool": "finder", "check_jog_mm": 5},
        "z": {
            "from": "+z",
            "check_jog_mm": 5.0,
            "paper_mm": 0.05,
            "retouch_after": list(retouch_after),
            **z,
        },
        "tool_touches": [],
    }


DECK = {"face": "deck", "edge_mm": 10.0, "method": "touch", "tool": "centre"}


def test_a_drill_after_the_centre_drill_that_set_z_is_re_touched_on_the_zero_face():
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", mill_zero(DECK), ops))[0]
    assert finding.status == "pass"
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [20] and touch["tool"] == "drill"
    assert (touch["z_face"], touch["edge_mm"], touch["paper_mm"]) == ("deck", 10.0, 0.05)
    assert touch["z_axis_set"] == pytest.approx(10.05)
    assert "x_axis_set" not in touch


def test_a_faced_away_top_is_not_touched_again_the_new_face_is():
    zero = mill_zero({"face": "top", "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", to_z=0.0), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 2.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["edge_mm"], touch["z_axis_set"]) == ("deck", 0.0, 0.05)


def test_a_listed_retouch_serves_only_the_next_tool():
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "spot", "hole", "centre"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 2.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [30] and touch["z_face"] in ("deck", "top")
    assert touch["z_axis_set"] == pytest.approx(0.05)


def test_a_listed_retouch_installs_the_incoming_tool_and_none_for_the_same_tool():
    # Ops 10 and 20 both run the end mill: the retouch after op 10 is no tool change. The
    # one after op 20 serves the drill, which goes in before its touch.
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "face", "deck", "mill", to_z=0.0),
        op(30, "drill", "hole", "drill"),
    ]
    data = bundle("mill", zero, ops, {"top_z": 2.0})
    finding = evaluate(data)[0]
    after = {row["op"]: row for row in finding.numbers["retouch"]}
    assert (after[10]["next_op"], after[10]["tool_change"]) == (20, False)
    assert (after[20]["next_op"], after[20]["next_tool"], after[20]["tool_change"]) == (
        30,
        "drill",
        True,
    )
    sheet, setup = sheet_of(data)
    html = sheet.dro(setup, {"mill": "T1 end mill", "drill": "T2 drill"})
    assert "before the next tool" not in html
    assert "After op 20, install T2 drill for op 30, then touch the top" in html
    assert "After op 10, T1 end mill stays in for op 20: re-touch the top" in html
    assert "install T1" not in html


def test_several_tool_changes_to_one_touch_name_their_ops_not_the_tools_again():
    # The op rows carry each op's T number and the TOOLS table names it: the touch
    # paragraph lists where the changes fall, not a second tool-by-tool itinerary.
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "spot", "hole", "centre"),
        op(30, "drill", "hole", "drill"),
    ]
    sheet, setup = sheet_of(bundle("mill", zero, ops, {"top_z": 2.0}))
    tools = {"mill": "T1 end mill", "centre": "T2 centre drill", "drill": "T3 drill"}
    text = unescape(re.sub(r"<[^>]+>", " ", sheet.dro(setup, tools)))
    (line,) = [part for part in re.split(r"\s{2,}", text) if "ops 20 and 30" in part]
    assert "touch the top" in line and "Axis Set Z" in line, line
    # The Z zero row names the tool that sets Z; the incoming tools are named nowhere.
    for name in ("T2 centre drill", "T3 drill"):
        assert name not in text, (name, text)


def test_a_mill_tool_touch_installs_its_tool_first():
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    sheet, setup = sheet_of(bundle("mill", mill_zero(DECK), ops))
    html = sheet.dro(setup, {"centre": "T1 centre drill", "drill": "T2 drill"})
    assert "Before op 20, install T2 drill, then re-touch it:" in html


def test_a_top_picked_up_after_a_facing_op_is_re_touched_where_that_op_left_it():
    # The face runs before the zero (no tool has set Z yet); the centre drill then
    # touches the faced top, and the drill repeats that touch at -2, not the incoming 0.
    zero = mill_zero({"face": "top", "tool": "centre", "after_op": 10})
    ops = [
        op(10, "face", "deck", "mill", to_z=-2.0),
        op(20, "spot", "hole", "centre"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 0.0}))[0]
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [30] and touch["edge_mm"] == pytest.approx(-2.0)
    assert touch["z_axis_set"] == pytest.approx(-1.95)


def test_a_face_cut_to_an_unknown_depth_leaves_no_known_z_to_re_touch():
    zero = mill_zero({**DECK, "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", to_z="unknown"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["z_axis_set"]) == ("deck", "unknown")


def test_a_floor_re_pocketed_to_an_unknown_depth_falls_back_to_a_face_still_standing():
    zero = mill_zero({**DECK, "tool": "mill"})
    ops = [
        op(10, "face", "deck", "mill", to_z=5.0),
        op(20, "pocket", "field", "mill", to_z=0.0),
        op(30, "pocket", "field", "mill", to_z="unknown"),
        op(40, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["edge_mm"]) == ("deck", 5.0)
    assert touch["z_axis_set"] == pytest.approx(5.05)


@pytest.mark.parametrize(
    "top_feature", [{"top_feature": "deck"}, {}, {"top_feature": "unknown"}], ids=str
)
@pytest.mark.parametrize(
    "depth, status, axis_set",
    [
        ({}, "unknown", "unknown"),
        ({"to_z": "unknown"}, "unknown", "unknown"),
        ({"to_z": 9.0}, "pass", 9.05),
    ],
    ids=["omitted", "unknown", "known"],
)
def test_a_top_faced_to_no_stated_depth_is_no_known_z_to_re_touch(
    depth, status, axis_set, top_feature
):
    # The zero touched the top. Facing the deck leaves the top wherever that op took it
    # when the deck is (or may be: no or an unknown top feature) the top: a depth left
    # out states it no more than an explicit "unknown" does.
    zero = mill_zero({"face": "top", "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", **depth), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0, **top_feature}))[0]
    assert finding.status == status
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_face"] == "deck"
    assert touch["z_axis_set"] == (axis_set if axis_set == "unknown" else pytest.approx(axis_set))


@pytest.mark.parametrize("depth", [{}, {"to_z": "unknown"}], ids=["omitted", "unknown"])
@pytest.mark.parametrize("producer", ["retouch_after", "after_op"])
def test_a_top_touched_after_a_face_to_no_stated_depth_is_unknown(producer, depth):
    # The top is touched again after op 10 faced it (a listed retouch), or first touched
    # then (a zero after op 10): no stated depth leaves that top's Z unknown, not the
    # incoming Z 10.
    z = {"face": "top", "tool": "mill"}
    zero = mill_zero(z, [10]) if producer == "retouch_after" else mill_zero({**z, "after_op": 10})
    ops = [
        op(10, "face", "deck", "mill", **depth),
        op(20, "spot", "hole", "centre"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0, "top_feature": "deck"}))[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    derived = [t["z_axis_set"] for t in finding.numbers["derived_touches"]]
    assert derived and set(derived) == {"unknown"}
    if producer == "retouch_after":
        assert [r["axis_set"] for r in finding.numbers["retouch"]] == ["unknown"]
    else:
        assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"


@pytest.mark.parametrize("cut", ["deck", "unknown"])
def test_a_cut_whose_feature_is_unnamed_leaves_the_datum_unproven(cut):
    # A profile on the deck cuts the touched surface away; a profile on a feature the plan
    # does not name may have, so the drill's touch on the deck is unknown, not 10.05.
    zero = mill_zero({**DECK, "tool": "mill"})
    ops = [op(10, "profile", cut, "mill"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    if cut == "deck":
        assert finding.status == "error"
        assert finding.numbers["missing_touches"] == [
            {"before_op": 20, "tool": "drill", "axes": ["z"], "dro_set_by": "mill"}
        ]
    else:
        assert finding.status == "unknown"
        assert finding.numbers["missing_touches"] == []
        [touch] = finding.numbers["derived_touches"]
        assert (touch["z_face"], touch["z_axis_set"]) == ("deck", "unknown")


@pytest.mark.parametrize("face", [{"face": "field"}, {}], ids=["named", "absent"])
def test_a_zero_on_an_unnamed_face_is_no_proven_surface(face):
    # The floor the zero touched is re-pocketed to an unknown depth. Named, the re-pocket
    # visibly ends it; unnamed, nothing can show it survived, so neither is a known Z.
    zero = mill_zero({"edge_mm": 0.0, "method": "touch", "tool": "mill", **face})
    ops = [
        op(10, "pocket", "field", "mill", to_z=0.0),
        op(20, "pocket", "field", "mill", to_z="unknown"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


def deck_bundle(face, cuts, footprint=True):
    """A deck X 0..20, Y 0..10 at Z 10 (its footprint unresolved unless ``footprint``, then
    the kernel's one plane face filling it), touched as ``face`` by the mill, faced to Z 5
    over each X span of ``cuts``, then drilled."""
    zero = mill_zero({"face": face, "edge_mm": 10.0, "method": "touch", "tool": "mill"})
    ops = [
        op(10 + 10 * i, "face", "deck", "mill", to_z=5.0, stock_removal_bounds=bounds)
        for i, bounds in enumerate({"x": x, "y": [0.0, 10.0], "z": [5.0, 10.0]} for x in cuts)
    ]
    ops.append(op(10 + 10 * len(cuts), "drill", "hole", "drill"))
    data = bundle("mill", zero, ops, {"top_z": 10.0, "top_feature": "deck"})
    identity = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]}
    identity["z"] = [0.0, 0.0, 1.0]
    data.features["frames"] = {"F": {**identity, "binding": "nominal"}, "model": identity}
    data.features["units"] = "mm"
    deck = {"frame": "model", "kind": "plane", "faces": ["#1/FACE"]}
    if footprint:
        deck["bounds"] = {"x": [0.0, 20.0], "y": [0.0, 10.0], "z": [10.0, 10.0]}
        box = [0.0, 0.0, 10.0, 20.0, 10.0, 10.0]
        plane = {"index": 0, "ref": "#1/FACE", "kind": "Plane", "area_mm2": 200.0, "bbox_mm": box}
        plane["fills_bbox"] = True
        data.kernel = {"status": "ok", "mapping": {"#1/FACE": 0}, "faces": [plane]}
    data.features["features"]["deck"] = deck
    return data


@pytest.mark.parametrize(
    "cuts, status, edge",
    [
        ([[0.0, 10.0]], "pass", 10.0),
        ([[0.0, 20.0]], "pass", 5.0),
        ([[0.0, 10.0], [10.0, 20.0]], "unknown", "unknown"),
        ([[0.0, 12.0], [8.0, 20.0]], "unknown", "unknown"),
        ([[0.0, 8.0], [12.0, 20.0]], "pass", 10.0),
    ],
    ids=["part", "whole", "halves", "overlapping", "strip-left"],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_datum_faced_in_parts_stands_only_where_every_cut_spared_it(face, cuts, status, edge):
    # Faces over part of the deck leave the rest of it at Z 10, where the drill is touched
    # off, as long as some of it is outside every cut; faces that together cover it leave
    # no Z 10 to touch, and no one of them made the Z 5 face. A whole face moves it to Z 5.
    finding = evaluate(deck_bundle(face, cuts))[0]
    assert finding.status == status
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    if status == "pass":
        assert touch["edge_mm"] == pytest.approx(edge)
        assert touch["z_axis_set"] == pytest.approx(edge + 0.05)
    else:
        assert (touch["edge_mm"], touch["z_axis_set"]) == ("unknown", "unknown")


@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_bounded_face_over_a_datum_of_unknown_extent_neither_spares_nor_makes_it(face):
    # Without the deck's footprint the bounded face may have cut all or part of it: the
    # drill's touch is neither the old Z 10 nor the cut's Z 5.
    finding = evaluate(deck_bundle(face, [[0.0, 10.0]], footprint=False))[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


ROUND = {"frame": "model", "kind": "plane", "at": [10.0, 5.0, 10.0], "dia": 10.0}
BOX = {"bounds": {"x": [5.0, 15.0], "y": [0.0, 10.0], "z": [10.0, 10.0]}}


@pytest.mark.parametrize(
    "deck",
    [ROUND, {**ROUND, **BOX}, {"frame": "model", "kind": "face", "faces": ["#1/FACE"], **BOX}],
    ids=["round", "round-with-bounds", "face-box"],
)
def test_a_datum_not_known_to_fill_its_box_is_not_spared_by_its_corners(deck):
    # The deck is a dia 10 disc at X 10, Y 5 (or a face known only by its box), faced in
    # two passes that between them cover all of such a disc but not the corners of its
    # box: nothing shows any Z 10 is left for the drill.
    data = deck_bundle("deck", [[5.0, 15.0], [6.4, 13.6]])
    ops = data.plan["setups"][0]["ops"]
    ops[0]["stock_removal_bounds"]["y"] = [1.5, 8.5]
    data.features["features"]["deck"] = deck
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


@pytest.mark.parametrize("kernel", ["L-shaped", "none"])
def test_a_plane_face_not_shown_to_fill_its_box_is_not_spared_by_its_corners(kernel):
    # The deck's one plane face is an L (X 0..20 at Y 0..5 and X 0..5 at Y 5..10, 125 of
    # its box's 200 mm^2, not filling it), or no kernel result shows its shape. Faced over
    # X 0..5, then over X 5..20 at Y 0..5, the only uncut part of its box is the empty
    # corner.
    data = deck_bundle("deck", [[0.0, 5.0], [5.0, 20.0]])
    data.plan["setups"][0]["ops"][1]["stock_removal_bounds"]["y"] = [0.0, 5.0]
    if kernel == "none":
        del data.kernel
    else:
        data.kernel["faces"][0].update(area_mm2=125.0, fills_bbox=False)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


_DECKS = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
deck = Part.makeBox(20, 10, 10)
for name, shape in [
    ("filled", deck),
    # A 0.005 mm square hole through the middle: its top has a second, inner wire.
    ("small-hole", deck.cut(Part.makeBox(0.005, 0.005, 12, V(9.9975, 4.9975, -1)))),
    # The same square notched out of the X 20, Y 10 corner: one wire of six edges.
    ("notch", deck.cut(Part.makeBox(0.005, 0.005, 12, V(19.995, 9.995, -1)))),
    # A block beside it as tall splits the top's X 20 edge at Y 5, a rectangle still.
    ("split-edge", deck.fuse(Part.makeBox(10, 5, 10, V(20, 0, 0)))),
    # X 0..20.0000006, notched through its X end 0.0000009 mm deep at Y 4..6: every edge
    # within the kernel's 1e-6 mm of a side, and its box rounded out to X 20.000001.
    (
        "thin-notch",
        Part.makeBox(20.0000006, 10, 10).cut(Part.makeBox(1, 2, 12, V(19.9999997, 4, -1))),
    ),
    # Pocketed to Z 5 inside 0.0000009 mm walls on three sides, open at Y 10: its Z 10
    # top is a rim along three sides of its box, every edge within 1e-6 mm of a side.
    ("rim", deck.cut(Part.makeBox(20 - 1.8e-6, 11, 6, V(9e-7, 9e-7, 5)))),
]:
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")
"""


@pytest.fixture(scope="module")
def deck_tops(tmp_path_factory, freecad_kernel):
    """The kernel's face record of each authored deck's Z 10 top from X 0, Y 0..10."""
    directory = tmp_path_factory.mktemp("decks")
    script = directory / "author.py"
    script.write_text(_DECKS, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    engine, tops = Engine(directory, freecad_kernel), {}
    for path in directory.glob("*.step"):
        [tops[path.stem]] = [
            f
            for f in engine.faces(path)
            if f["bbox_mm"][:3] == [0.0, 0.0, 10.0] and f["bbox_mm"][4:] == [10.0, 10.0]
        ]
    assert len(tops) == 6, process.stdout[-2000:] + process.stderr[-2000:]
    return tops


def deck_faced_in(face, regions):
    """:func:`deck_bundle` faced to Z 5 over each X/Y region of ``regions``."""
    data = deck_bundle(face, [x for x, _ in regions])
    for cut, (_, y) in zip(data.plan["setups"][0]["ops"][:-1], regions, strict=True):
        cut["stock_removal_bounds"]["y"] = y
    return data


def sparing(x, y):
    """Regions that between them face all of X -1..21, Y -1..11 but the box ``x`` by ``y``."""
    (x0, x1), (y0, y1) = x, y
    return [
        [[-1.0, x0], [-1.0, 11.0]],
        [[x1, 21.0], [-1.0, 11.0]],
        [[x0, x1], [-1.0, y0]],
        [[x0, x1], [y1, 11.0]],
    ]


def drill_pickup(data):
    """(status, Z Axis Set) of the one touch derived for ``data``'s drill."""
    finding = evaluate(data)[0]
    [touch] = finding.numbers["derived_touches"]
    return finding.status, touch["z_axis_set"]


UNPROVEN, SPARED = ("unknown", "unknown"), ("pass", pytest.approx(10.05))
# The 0.005 mm squares of the hole and the notch, and 1 mm squares about them.
HOLE, NOTCH = ([9.9975, 10.0025], [4.9975, 5.0025]), ([19.995, 20.0], [9.995, 10.0])
CENTRE, CORNER = ([9.5, 10.5], [4.5, 5.5]), ([19.0, 20.0], [9.0, 10.0])
# Faces to Z 5 sparing only the thin notch's X 19.9999997.. end of the deck at Y 4..6.
THIN_NOTCH_CUTS = [
    [[0.0, 19.9999997], [0.0, 10.0]],
    [[19.9999997, 21.0], [0.0, 4.0]],
    [[19.9999997, 21.0], [6.0, 10.0]],
]


@pytest.mark.parametrize(
    "deck, cuts, pickup",
    [
        ("small-hole", sparing(*HOLE), UNPROVEN),
        ("small-hole", sparing(*CENTRE), UNPROVEN),
        ("notch", sparing(*NOTCH), UNPROVEN),
        ("notch", sparing(*CORNER), UNPROVEN),
        ("thin-notch", THIN_NOTCH_CUTS, UNPROVEN),
        ("rim", sparing([10.0, 20.0], [0.0, 10.0]), UNPROVEN),
        ("filled", sparing(*CENTRE), SPARED),
        ("filled", sparing(*CORNER), SPARED),
        ("filled", sparing([10.0, 20.0], [0.0, 10.0]), SPARED),
        ("split-edge", sparing(*CENTRE), SPARED),
        ("thin-notch", sparing([19.0, 20.5], [0.0, 1.0]), SPARED),
    ],
    ids=[
        "small-hole",
        "about-small-hole",
        "notch",
        "about-notch",
        "thin-notch",
        "rim",
        "filled-centre",
        "filled-corner",
        "filled-half",
        "split-edge",
        "thin-notch-clear-end",
    ],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_land_every_cut_spares_holds_the_datum_only_where_the_face_fills_its_box(
    deck_tops, face, deck, cuts, pickup
):
    # The deck's top as the kernel measures it, bounded by its box, faced in parts. A
    # hole or notch in the spared square leaves no Z 10 at all there, however little of
    # the box the face lacks; so does a notch 0.0000009 mm deep, inside the kernel's side
    # tolerance, at the only part of the box (rounded out past the notch) every cut
    # spares, and a rim along three sides with no surface inside it. Where the face fills
    # its box, the spared 1 mm square is still Z 10, as is the thin notch's clear end.
    data = deck_faced_in(face, cuts)
    top = deck_tops[deck]
    box = top["bbox_mm"]
    bounds = {"x": [box[0], box[3]], "y": [box[1], box[4]], "z": [box[2], box[5]]}
    data.features["features"]["deck"]["bounds"] = bounds
    data.kernel = {"status": "ok", "mapping": {"#1/FACE": top["index"]}, "faces": [top]}
    assert drill_pickup(data) == pickup


@pytest.mark.parametrize(
    "cuts, pickup",
    [
        (sparing(*HOLE), UNPROVEN),
        (sparing([9.7505, 10.2495], [4.5, 5.5]), UNPROVEN),
        (sparing([9.75, 10.25], [4.75, 5.25]), SPARED),
        (sparing([19.6, 20.0], [0.0, 10.0]), UNPROVEN),
        # An L of the X 19..20, Y 9..10 corner, 0.3 mm wide along X 19 and along Y 10.
        (
            [[[-1.0, 19.0], [-1.0, 11.0]], [[19.0, 21.0], [-1.0, 9.0]], [[19.3, 21.0], [9.0, 9.7]]],
            UNPROVEN,
        ),
        # That 1 mm corner whole, with two other cuts ending at X 19.4 and X 19.6.
        (
            [
                [[-1.0, 19.0], [-1.0, 11.0]],
                [[19.0, 21.0], [-1.0, 9.0]],
                [[19.4, 21.0], [-1.0, 1.0]],
                [[18.0, 19.6], [-1.0, 1.0]],
            ],
            SPARED,
        ),
    ],
    ids=["hole-sized", "just-narrower", "touch-sized", "strip", "narrow-L", "across-cut-ends"],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_spared_patch_holds_the_datum_only_where_a_touch_fits_on_it(face, cuts, pickup):
    # The deck fills its box, faced in parts that spare a 0.005 mm square, a 0.499 by
    # 1 mm patch, a 0.5 mm square, a 0.4 by 10 mm strip or a 0.3 mm wide L: only a land
    # 0.5 mm square holds a touch, wherever the other cuts' ends cross it.
    assert drill_pickup(deck_faced_in(face, cuts)) == pickup


@pytest.mark.parametrize(
    "turn, cuts, pickup",
    [
        # Its setup X/Y box is X 0..22.32, Y -10..8.66; the spared X 0..2, Y -10..-8
        # corner of it lies off the face.
        (30, [[[2.0, 22.4], [-10.1, 8.7]], [[-0.1, 2.0], [-8.0, 8.7]]], UNPROVEN),
        # Its setup X/Y box is the face, X 0..10, Y -20..0: the spared corner is Z 10.
        (90, [[[2.0, 10.0], [-20.0, 0.0]], [[0.0, 2.0], [-18.0, 0.0]]], SPARED),
    ],
    ids=["turned-30", "turned-90"],
)
def test_a_face_filling_its_box_fills_the_setup_box_only_square_to_the_setup(turn, cuts, pickup):
    # The deck fills its model box, but the setup's X/Y axes are turned against the
    # model's about Z: turned 30 deg, the face's setup box has corners the face is not in.
    data = deck_faced_in("deck", cuts)
    c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    data.features["frames"]["F"].update(x=[c, s, 0.0], y=[-s, c, 0.0])
    assert drill_pickup(data) == pickup


def retouch_deck(data, retouch):
    """Re-touch ``data``'s deck after op 10: a listed top retouch, else a touch authored
    for the centre drill before op 20."""
    zero = data.plan["setups"][0]["zero"]
    if retouch == "listed":
        zero["z"] = {**zero["z"], "face": "top", "retouch_after": [10]}
    else:
        touch = {"tool": "centre", "z_face": "deck", "edge_mm": 10.0, "paper_mm": 0.05}
        zero["tool_touches"] = [{**touch, "method": "touch_then_set", "before_ops": [20]}]


@pytest.mark.parametrize("retouch", ["listed", "authored"])
def test_a_datum_re_touched_after_a_cut_of_unknown_extent_stays_unproven(retouch):
    # Op 10 faces part of the deck, whose footprint is unresolved, so whether any of its
    # Z 10 is left is unknown; touching it again at its nominal Z 10 does not show it.
    data = deck_bundle("deck", [[0.0, 10.0]], footprint=False)
    ops = data.plan["setups"][0]["ops"]
    ops[1:] = [op(20, "spot", "hole", "centre"), op(30, "drill", "hole", "drill")]
    retouch_deck(data, retouch)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    derived = [t["z_axis_set"] for t in finding.numbers["derived_touches"]]
    assert derived and set(derived) == {"unknown"}


@pytest.mark.parametrize(
    "depth, status, axis_set",
    [({"to_z": 5.0}, "pass", 5.05), ({}, "unknown", "unknown")],
    ids=["to-z-5", "omitted"],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_touch_at_a_z_its_surface_was_not_made_at_is_not_repeated(face, depth, status, axis_set):
    # Op 10 faces the whole deck, the stock top (to Z 5, or to no stated depth), then the
    # centre drill is touched off on the deck or the top as if still at Z 10: the drill
    # repeats the deck op 10 made, not the touch's Z 10.
    data = deck_bundle("deck", [[0.0, 20.0]])
    ops = data.plan["setups"][0]["ops"]
    ops[0] = op(10, "face", "deck", "mill", **depth)
    ops[1:] = [op(20, "spot", "hole", "centre"), op(30, "drill", "hole", "drill")]
    retouch_deck(data, "authored")
    data.plan["setups"][0]["zero"]["tool_touches"][0]["z_face"] = face
    finding = evaluate(data)[0]
    assert finding.status == status
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == (axis_set if axis_set == "unknown" else pytest.approx(axis_set))


@pytest.mark.parametrize("retouch", ["listed", "authored"])
def test_a_datum_re_touched_between_partial_faces_keeps_the_first_cut(retouch):
    # Op 10 faces the left half of the deck, the deck is touched again at its uncut Z 10,
    # then op 30 faces the right half: the re-touch does not undo op 10, so no Z 10 is
    # left for the drill.
    data = deck_bundle("deck", [[0.0, 10.0]])
    ops = data.plan["setups"][0]["ops"]
    right = {**ops[0], "op": 30, "stock_removal_bounds": {**ops[0]["stock_removal_bounds"]}}
    right["stock_removal_bounds"]["x"] = [10.0, 20.0]
    ops[1:] = [op(20, "spot", "hole", "centre"), right, op(40, "drill", "hole", "drill")]
    retouch_deck(data, retouch)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    before_30, before_40 = finding.numbers["derived_touches"]
    assert before_30["before_ops"] == [30]
    assert before_30["z_axis_set"] == pytest.approx(10.05)
    assert (before_40["before_ops"], before_40["z_axis_set"]) == ([40], "unknown")


@pytest.mark.parametrize("incoming", ["unknown", "not-in-inventory"])
def test_an_unresolved_incoming_tool_keeps_the_tool_change_unknown(incoming):
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", incoming)]
    finding = evaluate(bundle("mill", mill_zero(DECK), ops))[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []


@pytest.mark.parametrize("machine", ["mill", "lathe"])
def test_a_setup_with_no_zero_has_no_tool_dro_to_change(machine):
    # No recipe set the DRO, so no tool cuts on another tool's Axis Set: the zero is
    # missing (unknown), not a tool change to touch off.
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    if machine == "lathe":
        ops = [op(10, "face", "end", "turner"), op(20, "part_off", "relief", "parter")]
    finding = evaluate(bundle(machine, {}, ops))[0]
    assert finding.status == "unknown"
    assert finding.numbers["derived_touches"] == []
    assert finding.numbers["missing_touches"] == []


def test_a_measured_zero_gives_no_plan_z_to_re_touch_so_the_change_is_an_error():
    z = {
        "face": "deck",
        "edge_mm": 10.0,
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "deck height above the vise floor",
        "offset_mm": -1.0,
        "tool": "centre",
    }
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", mill_zero(z), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 20, "tool": "drill", "axes": ["z"], "dro_set_by": "centre"}
    ]


@pytest.mark.parametrize(
    "change,axis_set,check,mirror",
    [
        ({}, "M -0.95", "M +4.05", "M -5.95"),
        ({"gauge": "unknown"}, "unknown", "unknown", "unknown"),
        ({"measure": ""}, "unknown", "unknown", "unknown"),
        ({"measure": "unknown"}, "unknown", "unknown", "unknown"),
        ({"offset_mm": "unknown"}, "unknown", "unknown", "unknown"),
    ],
)
def test_a_measured_z_zero_sets_the_measurement_plus_offset_and_paper(
    change, axis_set, check, mirror
):
    z = {
        "face": "deck",
        "edge_mm": 10.0,
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "deck height above the vise floor",
        "offset_mm": -1.0,
        "tool": "centre",
        **change,
    }
    finding = evaluate(bundle("mill", mill_zero(z), [op(10, "spot", "hole", "centre")]))[0]
    row = finding.numbers["axes"]["z"]
    assert (row["axis_set"], row["check_reading"], row["mirrored_reading"]) == (
        axis_set,
        check,
        mirror,
    )
    assert finding.status == ("pass" if axis_set != "unknown" else "unknown")


@pytest.mark.parametrize(
    "measure,axis_set,status",
    [("boss height above the deck", "M +10.05", "pass"), ("unknown", "unknown", "unknown")],
)
def test_a_mill_tool_touch_is_z_only_and_may_be_measured(measure, axis_set, status):
    touch = {
        "tool": "drill",
        "z_face": "boss",
        "edge_mm": 3.0,
        "paper_mm": 0.05,
        "method": "measure_then_set",
        "z_gauge": "mic",
        "z_measure": measure,
        "z_offset_mm": 10.0,
        "before_ops": [20],
    }
    zero = {**mill_zero(DECK), "tool_touches": [touch]}
    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops))[0]
    assert finding.status == status
    [row] = finding.numbers["tool_touches"]
    assert (row["x_axis_set"], row["z_axis_set"]) == ("not_applicable", axis_set)
    assert finding.numbers["derived_touches"] == []


def sheet_of(data):
    finding = evaluate(data)[0]
    return _Traveler(data, [finding], {}, {}), data.plan["setups"][0]


def test_the_datum_transfer_prints_before_the_zero_it_sets_up():
    transfer = {"from": "S0", "indicate": "journal", "gauge": "mic", "runout_limit_mm": 0.02}
    data = bundle(
        "lathe", {**lathe_zero([]), "transfer": transfer}, [op(10, "turn", "j", "turner")]
    )
    sheet, setup = sheet_of(data)
    html = sheet.dro(setup, {"turner": "T1 turner"})
    # Indicate, then touch off: the sweep comes before the zero table and its tool setting.
    assert html.index("Before zeroing: indicate the") < html.index("<table")
    assert html.index("Before zeroing: indicate the") < html.index("Before touching off")


def measured_hold(before_hold):
    zero = lathe_zero([])
    zero["z"] = {
        "face": "stub end",
        "edge_mm": 5.0,
        "from": "+z",
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "length from the thrust face to the stub end",
        "offset_mm": -9.0,
        "tool": "turner",
        "paper_mm": 0.0,
        "check_jog_mm": 10.0,
        "retouch_after": [],
    }
    if before_hold is not None:
        zero["z"]["measure_before_hold"] = before_hold
    data = bundle("lathe", zero, [op(10, "face", "stub end", "turner", to_z=0.0)])
    data.plan["setups"][0]["hold"] = {
        "fixture": "chuck",
        "stop": "thrust face seated on the jaw fronts",
        "clamp": "tighten the chuck at all three pinions",
    }
    return sheet_of(data)


def test_a_zero_measured_before_the_hold_is_measured_before_clamping():
    sheet, setup = measured_hold(True)
    steps, _ = sheet.hold(setup)
    measure = steps.index("length from the thrust face to the stub end")
    assert measure < steps.index("thrust face seated") < steps.index("Tighten the chuck")
    assert "measure Z M = length from the thrust face" in steps
    # The zero row then refers back to that reading instead of introducing M itself.
    row = sheet.dro(setup, {"turner": "T1 turner"})
    assert "length from the thrust face" not in row and "M measured before clamping" in row


@pytest.mark.parametrize("before_hold", [None, False])
def test_a_zero_measured_at_the_machine_stays_in_the_zero_table(before_hold):
    sheet, setup = measured_hold(before_hold)
    steps, _ = sheet.hold(setup)
    assert "length from the thrust face" not in steps
    assert "M = length from the thrust face" in sheet.dro(setup, {"turner": "T1 turner"})


def x_touch(x_face, before, ops=LATHE_OPS, x_method="paper on the measured diameter", x=None):
    """The blade's authored touch before op ``before`` with its X on ``x_face`` (None:
    words only)."""
    touch = {**BLADE, "x_method": x_method, "x_face": x_face, "before_ops": [before]}
    if x_face is None:
        del touch["x_face"]
    zero = lathe_zero([touch])
    zero["x"].update(x or {})
    data = bundle("lathe", zero, ops)
    data.plan["setups"][0]["stock_in"] = "stock"
    return data


def x_row(data, setup=0):
    finding = evaluate(data)[setup]
    [row] = finding.numbers["tool_touches"]
    return finding, row


FORMED = [*LATHE_OPS[:3], op(35, "form_dome", "journal", "turner"), LATHE_OPS[3]]


@pytest.mark.parametrize(
    ("x_face", "before", "ops", "x", "status"),
    [
        # Turned in ops 10 and 30, it stands at op 40.
        ("journal", 40, LATHE_OPS, None, "pass"),
        # Formed in op 35: the diameter the touch names is gone.
        ("journal", 40, FORMED, None, "error"),
        # Not yet turned when the blade touches it before op 10.
        ("journal", 10, LATHE_OPS, None, "error"),
        ("no_such_feature", 40, LATHE_OPS, None, "error"),
        # The X zero's trial-cut land stands until a cut runs.
        ("x_zero", 10, LATHE_OPS, None, "pass"),
        ("x_zero", 40, LATHE_OPS, None, "unknown"),
        # No trial cut, no land.
        ("x_zero", 10, LATHE_OPS, {"method": "touch"}, "error"),
        # Words alone name no surface the rule can follow.
        (None, 40, LATHE_OPS, None, "unknown"),
    ],
)
def test_an_authored_x_touch_is_on_a_surface_standing_where_it_touches(
    x_face, before, ops, x, status
):
    finding, row = x_row(x_touch(x_face, before, ops, x=x))
    assert row["x_face_status"] == status, row
    if status == "error":
        assert finding.status == "error" and "X touch" in finding.sentence
    elif status == "unknown":
        assert finding.status in ("unknown", "error")


def test_a_blade_trial_cut_is_its_own_x_surface():
    _, row = x_row(x_touch(None, 40, x_method="trial_cut_measure"))
    assert row["x_face_status"] == "pass"


@pytest.mark.parametrize(
    ("earlier_op", "routed", "status"),
    [
        (op(10, "finish_turn", "journal", "turner"), True, "pass"),
        # Formed after it was turned: no cylinder arrives.
        (op(10, "form_dome", "journal", "turner"), True, "error"),
        # Turned in a setup the plan does not route to this one.
        (op(10, "finish_turn", "journal", "turner"), False, "unknown"),
    ],
)
def test_a_diameter_turned_in_an_earlier_setup_stands_for_a_touch(earlier_op, routed, status):
    data = x_touch("journal", 40, [op(40, "form_relief", "relief", "parter")])
    earlier = {
        "id": "S0",
        "machine": "lathe",
        "frame": "F",
        "zero": {},
        "stock_state": {},
        "stock_in": "stock",
        "ops": [earlier_op],
    }
    data.plan["setups"].insert(0, earlier)
    if routed:
        data.plan["setups"][1]["stock_in"] = "S0"
    else:
        del data.plan["setups"][1]["stock_in"]
    _, row = x_row(data, setup=1)
    assert row["x_face_status"] == status


@pytest.mark.parametrize(
    ("radius_mode", "paper", "axis_set"),
    [
        (False, 0.05, "measured D + 0.1"),
        (True, 0.05, "measured D/2 + 0.05"),
        (False, 0.0, "measured D"),
        (False, "unknown", "unknown"),
    ],
)
def test_an_x_touch_through_paper_sets_the_measured_diameter_plus_the_paper(
    radius_mode, paper, axis_set
):
    data = x_touch("journal", 40)
    data.plan["dro"] = {**DRO, "radius_mode": radius_mode}
    data.plan["setups"][0]["zero"]["tool_touches"][0]["x_paper_mm"] = paper
    _, row = x_row(data)
    assert row["x_axis_set"] == axis_set


@pytest.mark.parametrize(
    ("x_face", "ops", "stop"),
    [("journal", LATHE_OPS, False), ("journal", FORMED, True), (None, LATHE_OPS, True)],
)
def test_an_authored_x_touch_prints_its_axis_set_and_stops_on_a_diameter_not_shown_standing(
    x_face, ops, stop
):
    sheet, setup = sheet_of(x_touch(x_face, 40, ops))
    html = sheet.dro(setup, {"parter": "T4 blade", "turner": "T1 turner"})
    start = html.index("touch off T4 blade")
    line = html[start : html.index("Z —", start)]
    # The paper counts once on the radius, twice on a diameter display.
    assert "Axis Set X measured Ø + 0.10" in line, line
    assert ("STOP" in line) is stop, line


def x_printed(data, touch):
    """The X half of ``touch`` as the sheet prints it."""
    sheet, setup = sheet_of(data)
    return sheet.tool_touch(setup, touch, {}).split("X — ", 1)[1].split(" Z — ", 1)[0]


@pytest.mark.parametrize(
    ("x_method", "paper", "contact"),
    [
        # Words that name the surface but not the paper the Axis Set counts.
        ("touch the journal just measured", 0.05, "paper 0.05"),
        ("touch the journal just measured", 0.0, "no paper"),
        # Words that name neither.
        ("bring the blade in until it drags", 0.05, "paper 0.05"),
        # Paper not stated: its Axis Set is unknown, and so is the paper printed.
        ("touch the journal just measured", "unknown", "paper ?"),
    ],
)
def test_an_authored_x_touch_prints_the_surface_and_paper_its_axis_set_counts(
    x_method, paper, contact
):
    data = x_touch("journal", 40, x_method=x_method)
    data.plan["setups"][0]["zero"]["tool_touches"][0]["x_paper_mm"] = paper
    _, row = x_row(data)
    printed = x_printed(data, row)
    assert x_method in printed, printed
    assert "journal Ø" in printed and contact in printed, printed


def test_a_derived_x_re_touch_prints_the_surface_and_that_it_takes_no_paper():
    ops = [*LATHE_OPS, op(50, "face", "dome", "turner", to_z=0.0)]
    data = bundle("lathe", lathe_zero([BLADE]), ops)
    [touch] = evaluate(data)[0].numbers["derived_touches"]
    printed = x_printed(data, touch)
    # Its Axis Set is the measured diameter alone: a direct touch on the journal.
    assert "journal Ø" in printed and "no paper" in printed, printed
    assert printed.endswith("Axis Set X measured Ø."), printed


def test_a_trial_cut_is_withdrawn_along_z_and_the_spindle_stopped_before_it_is_measured():
    # The X zero's trial cut and a blade's own: the tool backs off along Z only (its X is
    # what the Axis Set counts) and the spindle stops before the mic touches the work.
    touch = {**BLADE, "x_method": "trial_cut_measure"}
    del touch["x_face"]
    sheet, setup = sheet_of(bundle("lathe", lathe_zero([touch]), LATHE_OPS))
    html = sheet.dro(setup, {"turner": "T1 turner", "parter": "T2 parter"})
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    steps = re.findall(r"trial cut.*?measure", text)
    assert len(steps) == 2, text
    for step in steps:
        assert "withdraw along Z without moving X, stop the spindle," in step, step


def test_authored_prose_keeps_its_proper_nouns_as_written():
    # Shop words come from the plan's own identifiers; a maker's or vendor's name an author
    # wrote is a name to look up, printed as written.
    sheet, setup = sheet_of(bundle("lathe", lathe_zero([]), LATHE_OPS))
    note = "Buttons from McMaster, oil from LittleMachineShop, ProTap on the tap."
    assert sheet.bench(note, setup) == note
