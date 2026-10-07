"""One fact, one source: free text that names a structured fact must agree with it."""

import re
from html import unescape
from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.rules import consistency
from prechips.sheet import _Traveler

INVENTORY = {
    "machines": {"mill": {"kind": "mill"}},
    "tools": {
        "em4": {"kind": "endmill", "dia_mm": 9.525, "flutes": 4},
        "drill": {"kind": "drill", "dia_mm": 5.0},
    },
    "fixtures": {"buttons": {"kind": "custom"}, "strap": {"kind": "strap_clamp"}},
}
FACE = {"op": 10, "do": "face", "feature": "top", "tool": "em4", "holder": "collet"}
DRILL = {"op": 20, "do": "drill", "feature": "hole", "tool": "drill", "holder": "chuck"}


def bundle(setups, kernel=None, frames=None):
    plan = {"setups": [{"id": "S1", "machine": "mill", "ops": [], **s} for s in setups]}
    if frames:
        plan["frames"] = frames
    return Bundle(
        plan=plan,
        inventory=INVENTORY,
        features={"features": {}, "units": "mm"},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel=kernel or {"status": "ok", "setups": {}},
    )


def errors(data):
    return {f.subject: f.sentence for f in consistency.evaluate(data) if f.status == "error"}


def sheet(data):
    traveler = _Traveler(data, [], {}, None)
    html = "".join(sum(traveler.setup_section(data.plan["setups"][0]), []))
    return unescape(re.sub(r"<[^>]+>", "|", html))


# ------------------------------------------------------------ kept chucking
TRANSFER = {"from": "S0", "indicate": ["head", "foot"], "runout_limit_mm": 0.02}


@pytest.mark.parametrize(
    "stop",
    ["same chucking as S4; do not loosen the jaws.", "Leave it in the chuck, never loosen it."],
)
def test_text_keeping_the_chucking_needs_a_transfer_that_keeps_it_clamped(stop):
    found = errors(bundle([{"hold": {"stop": stop}, "zero": {"transfer": TRANSFER}}]))
    assert "keep_clamped" in found["S1"]


def test_a_transfer_kept_clamped_agrees_with_the_kept_chucking_text():
    transfer = {**TRANSFER, "keep_clamped": True, "recovery": "stop and re-plan"}
    hold = {"stop": "same chucking as S4; do not loosen the jaws."}
    assert errors(bundle([{"hold": hold, "zero": {"transfer": transfer}}])) == {}


def test_a_kept_chucking_without_a_transfer_has_no_loosening_step_to_contradict():
    assert (
        errors(bundle([{"hold": {"stop": "same chucking as S4; do not loosen the jaws."}}])) == {}
    )


# ------------------------------------------------------------ hand tight
def test_a_hand_tight_clamp_tightens_by_hand_on_the_sheet():
    hold = {"clamps": [{"ref": "buttons", "tighten": "hand"}], "clamp_order": [1]}
    page = sheet(bundle([{"hold": hold}]))
    assert "Tighten C1 by hand only, no wrench." in page
    assert "tighten fully" not in page


def test_mixed_hand_and_wrench_clamps_name_the_hand_ones():
    hold = {
        "clamps": [{"ref": "strap"}, {"ref": "buttons", "tighten": "hand"}],
        "clamp_order": [1, 2],
    }
    page = sheet(bundle([{"hold": hold}]))
    assert (
        "Tighten in order C1, C2: snug each in turn, then tighten each fully in the same "
        "order; C2 by hand only, no wrench."
    ) in page


@pytest.mark.parametrize(
    "hold",
    [
        {"clamp": "M6 nut on the button stud, hand tight", "clamps": [{"ref": "buttons"}]},
        {"clamps": [{"ref": "buttons", "note": "stud through the bore, nut tightened by hand"}]},
        {"clamps": [{"ref": "buttons", "note": "finger-tight only"}]},
    ],
)
def test_text_calling_the_clamp_hand_tight_needs_the_hand_field(hold):
    found = errors(bundle([{"hold": {**hold, "clamp_order": [1]}}]))
    assert "tighten" in found["S1"]


def test_hand_tight_text_matches_a_clamp_declared_hand_tight():
    hold = {
        "clamp": "M6 nut on the button stud, hand tight",
        "clamps": [{"ref": "buttons", "tighten": "hand"}],
        "clamp_order": [1],
    }
    assert errors(bundle([{"hold": hold}])) == {}


def test_hold_text_that_cannot_name_one_of_several_clamps_is_not_attributed():
    hold = {
        "clamp": "nuts hand tight",
        "clamps": [{"ref": "strap"}, {"ref": "strap"}],
        "clamp_order": [1, 2],
    }
    assert errors(bundle([{"hold": hold}])) == {}


def test_running_nuts_down_by_hand_before_a_torque_is_not_hand_tight():
    hold = {
        "clamp": "run the nuts down by hand until the bridge just holds",
        "clamps": [{"ref": "strap", "torque_nm": 15}],
        "clamp_order": [1],
    }
    assert errors(bundle([{"hold": hold}])) == {}


def test_a_hand_tight_clamp_cannot_also_carry_a_torque():
    hold = {"clamps": [{"ref": "strap", "tighten": "hand", "torque_nm": 15}], "clamp_order": [1]}
    assert "torque_nm" in errors(bundle([{"hold": hold}]))["S1"]


# ------------------------------------------------------------ tool numbers
@pytest.mark.parametrize(
    "note", ["Change to T3 for the hole.", "Touch T1, the 2fl cutter, on top."]
)
def test_a_tool_number_in_text_must_match_the_setup_tools_table(note):
    found = errors(bundle([{"ops": [FACE, {**DRILL, "note": note}]}]))
    assert "TOOLS" in found["S1:20"]


@pytest.mark.parametrize(
    "note", ["Touch T1 on the top first.", "Touch T1, the 4fl cutter, on top."]
)
def test_tool_numbers_and_flutes_that_match_the_tools_table_pass(note):
    assert errors(bundle([{"ops": [FACE, {**DRILL, "note": note}]}])) == {}


def test_a_tool_number_that_is_also_a_frame_name_is_not_attributed():
    data = bundle([{"ops": [FACE, {**DRILL, "note": "the T3 trial-cut land"}]}], frames={"T3": {}})
    assert errors(data) == {}


# ------------------------------------------------------------ jaw heights
def bar(note, top=0.525, bottom=-18.525, jaw=13.1953):
    return {
        "stock_state": {"top_z": top, "bottom_z": bottom},
        "hold": {"fixture": "vise", "jaw_above_parallels_mm": jaw, "note": note},
    }


@pytest.mark.parametrize("jaws", ["the jaws", "the jaw tops"])
def test_the_stated_height_above_the_jaws_must_match_the_stock_and_jaw_heights(jaws):
    found = errors(bundle([bar(f"Bar flat on parallels; it stands 5.3 mm above {jaws}.")]))
    assert "jaw_above_parallels_mm" in found["S1"] and "5.855" in found["S1"]


@pytest.mark.parametrize("stated", ["5.9", "5.85", "6"])
def test_a_height_above_the_jaws_agrees_to_its_stated_precision(stated):
    data = bundle([bar(f"Bar flat on parallels; it stands {stated} mm above the jaws.")])
    assert errors(data) == {}


def test_a_z_stated_above_the_jaw_tops_must_match_the_jaw_top_height():
    good = "Rough only down to Z +16, 5.63 mm above the jaw tops."
    assert errors(bundle([bar(good, top=27.2, bottom=-6.0, jaw=16.3703)])) == {}
    bad = "Rough only down to Z +16, 6.5 mm above the jaw tops."
    assert "jaw tops" in errors(bundle([bar(bad, top=27.2, bottom=-6.0, jaw=16.3703)]))["S1"]


# ------------------------------------------------------------ stock heights vs kernel
def kernel(box):
    return {"status": "ok", "setups": {"S1": {"stock_bbox_mm": box}}}


def test_authored_stock_heights_must_match_the_kernel_stock_the_setup_receives():
    state = {"stock_state": {"top_z": 22.3702, "bottom_z": -22.3702}}
    found = errors(bundle([state], kernel=kernel([-50, -20, -22.376691, 50, 20, 22.414118])))
    assert "top_z" in found["S1"] and "bottom_z" in found["S1"]


def test_stock_heights_within_the_kernel_tolerance_pass():
    state = {"stock_state": {"top_z": 0.0, "bottom_z": -24.2}}
    assert errors(bundle([state], kernel=kernel([-9, -22, -24.2, 9, 4, 1e-6]))) == {}


def test_retained_rails_set_the_lowest_stock_point():
    state = {"stock_state": {"top_z": 0.0, "bottom_z": -7.08, "retained_rail_bottom_z": -11.528}}
    assert errors(bundle([state], kernel=kernel([-170, -40, -11.528, 170, 40, 0.0]))) == {}


def test_a_touched_top_feature_may_stand_below_raw_rails_but_never_above_the_stock():
    box = kernel([-170, -40, -11.528, 170, 40, 4.47175])
    below = {"stock_state": {"top_feature": "hub", "top_z": 0.0, "bottom_z": -11.528}}
    assert errors(bundle([below], kernel=box)) == {}
    above = {"stock_state": {"top_feature": "hub", "top_z": 4.6, "bottom_z": -11.528}}
    assert "top_z" in errors(bundle([above], kernel=box))["S1"]


def test_without_a_kernel_stock_box_the_heights_are_unknown_not_passed():
    state = {"stock_state": {"top_z": 22.3702, "bottom_z": -22.3702}}
    (row,) = consistency.evaluate(bundle([state], kernel={"status": "unknown"}))
    assert row.status == "unknown"


# ------------------------------------------------------------ NO-GO
def gauged(method):
    return {
        "op": 34,
        "do": "inspect",
        "feature": "rod_hole",
        "go_no_go": {"dia": {"go": 2.0, "no_go": 2.09}},
        "checks": {"dia": "plugs"},
        "inspection_methods": {"dia": method},
    }


@pytest.mark.parametrize(
    "method",
    [
        "The GO and NO-GO plugs first. Push each plug by hand through the strap; never force it.",
        "Clean the hole, then push the drawing GO and NO-GO plugs by hand through the strap.",
        "Push the NO-GO plug (2.090) through the strap to clear the burr.",
    ],
)
def test_text_passing_the_no_go_plug_through_contradicts_the_go_no_go_check(method):
    assert "NO-GO" in errors(bundle([{"ops": [gauged(method)]}]))["S1:34"]


@pytest.mark.parametrize(
    "method",
    [
        "The 2.000 GO plug enters through the hub and the 2.090 NO-GO plug does not.",
        "Push the GO plug through; the NO-GO plug must not enter.",
        "The GO plug (2.000) must pass by hand through the strap; offer the NO-GO plug "
        "(2.090) gently at each mouth: it must not enter.",
    ],
)
def test_a_no_go_plug_that_does_not_enter_passes(method):
    assert errors(bundle([{"ops": [gauged(method)]}])) == {}
