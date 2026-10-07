"""One DRO per setup: a tool that did not set it is touched off before it cuts."""

from types import SimpleNamespace

import pytest

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
        features={"frames": {"F": {"binding": "nominal"}}, "features": {}},
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


BLADE = {
    "tool": "parter",
    "x_method": "touch the journal just measured",
    "gauge": "mic",
    "z_face": "shoulder",
    "edge_mm": -7.5,
    "paper_mm": 0.05,
    "method": "paper",
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
    finding = evaluate(bundle("lathe", lathe_zero([{**BLADE, "before_ops": [20]}]), ops))[0]
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
    """A deck X 0..20, Y 0..10 at Z 10 (its footprint unresolved unless ``footprint``),
    touched as ``face`` by the mill, faced to Z 5 over each X span of ``cuts``, then
    drilled."""
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
    deck = {"frame": "model", "kind": "plane"}
    if footprint:
        deck["bounds"] = {"x": [0.0, 20.0], "y": [0.0, 10.0], "z": [10.0, 10.0]}
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


def test_a_round_datum_faced_in_parts_is_not_spared_by_its_box_corners():
    # The deck is a dia 10 disc at X 10, Y 5, faced in two passes that between them cover
    # all of it but not the corners of its square: no Z 10 is left for the drill.
    data = deck_bundle("deck", [[5.0, 15.0], [6.4, 13.6]])
    ops = data.plan["setups"][0]["ops"]
    ops[0]["stock_removal_bounds"]["y"] = [1.5, 8.5]
    data.features["features"]["deck"] = {"frame": "model", "at": [10.0, 5.0, 10.0], "dia": 10.0}
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


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
    zero = data.plan["setups"][0]["zero"]
    if retouch == "listed":
        zero["z"] = {**zero["z"], "face": "top", "retouch_after": [10]}
    else:
        touch = {"tool": "centre", "z_face": "deck", "edge_mm": 10.0, "paper_mm": 0.05}
        zero["tool_touches"] = [{**touch, "method": "touch_then_set", "before_ops": [20]}]
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
