"""One fact, one source: free text that names a structured fact must agree with it."""

import re
from copy import deepcopy
from dataclasses import replace
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


def rows(data):
    return {f.subject: f for f in consistency.evaluate(data)}


def errors(data):
    return {s: f.sentence for s, f in rows(data).items() if f.status == "error"}


def sheet(data):
    traveler = _Traveler(data, [], {}, None)
    html = "".join(sum(traveler.setup_section(data.plan["setups"][0]), []))
    return unescape(re.sub(r"<[^>]+>", "|", html))


def kernel(box):
    return {"status": "ok", "setups": {"S1": {"stock_bbox_mm": box}}}


# ------------------------------------------------------------ kept chucking
TRANSFER = {"from": "S0", "indicate": ["head", "foot"], "runout_limit_mm": 0.02}


@pytest.mark.parametrize(
    "stop",
    [
        "same chucking as S0; do not loosen the jaws.",
        "Use the same chucking as S0.",
        "Do not loosen the jaws.",
    ],
)
def test_the_same_chucking_as_the_transfer_setup_needs_a_transfer_kept_clamped(stop):
    found = errors(bundle([{"hold": {"stop": stop}, "zero": {"transfer": TRANSFER}}]))
    assert "keep_clamped" in found["S1"]


def test_a_transfer_kept_clamped_agrees_with_the_same_chucking():
    transfer = {**TRANSFER, "keep_clamped": True, "recovery": "stop and re-plan"}
    hold = {"stop": "same chucking as S0; do not loosen the jaws."}
    assert rows(bundle([{"hold": hold, "zero": {"transfer": transfer}}]))["S1"].status == "pass"


@pytest.mark.parametrize(
    "note",
    [
        "This is not the same chucking as S0; loosen and re-clamp the work.",
        "Do not loosen the toolpost; loosen the workpiece jaws for transfer.",
        "Leave it in the chuck, never loosen it.",
        "Use the same chucking as S4.",
        "same chucking as S0 until op 20, then re-clamp the work.",
        "same chucking as S4; do not loosen the jaws until the work is indicated.",
        "Do not loosen the jaws until the work is indicated.",
    ],
)
def test_kept_chucking_text_is_attributed_only_as_the_same_chucking_as_the_transfer_setup(note):
    assert errors(bundle([{"hold": {"note": note}, "zero": {"transfer": TRANSFER}}])) == {}


def test_the_same_chucking_without_a_transfer_has_no_loosening_step_to_contradict():
    assert (
        errors(bundle([{"hold": {"stop": "same chucking as S0; do not loosen the jaws."}}])) == {}
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


@pytest.mark.parametrize("where", ["clamp", "hold"])
def test_a_clamp_the_text_leaves_hand_tight_needs_tighten_hand(where):
    clamp = {"ref": "strap", "torque_nm": 15}
    hold = {"clamps": [clamp], "clamp_order": [1]}
    (clamp if where == "clamp" else hold)["note"] = "Leave the nut hand tight."
    assert 'tighten = "hand"' in errors(bundle([{"hold": hold}]))["S1"]


@pytest.mark.parametrize(
    "note",
    [
        "Do not leave this clamp hand tight; torque it to 15 N m.",
        "Initially hand tight for alignment; then torque this clamp to 15 N m.",
        "Tighten by hand, then torque to 15 N m.",
    ],
)
def test_a_torqued_clamp_whose_note_mentions_hand_tightening_is_not_an_error(note):
    hold = {"clamps": [{"ref": "strap", "torque_nm": 15, "note": note}], "clamp_order": [1]}
    assert errors(bundle([{"hold": hold}])) == {}


def test_a_hand_tight_clamp_cannot_also_carry_a_torque():
    hold = {"clamps": [{"ref": "strap", "tighten": "hand", "torque_nm": 15}], "clamp_order": [1]}
    assert "torque_nm" in errors(bundle([{"hold": hold}]))["S1"]


# ------------------------------------------------------------ tool numbers
def test_a_tool_number_in_text_must_be_on_the_setup_tools_table():
    found = errors(bundle([{"ops": [FACE, {**DRILL, "note": "Change to T3 for the hole."}]}]))
    assert "TOOLS" in found["S1:20"]


@pytest.mark.parametrize(
    "note",
    [
        "Use T1 (2-flute) for this cut.",
        "Use the 2-flute T1 for this cut.",
        "Use T1, the 2fl cutter.",
    ],
)
def test_a_flute_count_bound_to_a_tool_number_must_match_its_inventory(note):
    assert "4 flutes" in errors(bundle([{"ops": [{**FACE, "note": note}]}]))["S1:10"]


@pytest.mark.parametrize(
    "note", ["Touch T1 on the top first.", "Touch T1, the 4fl cutter, on top.", "Use T1 (4-flute)."]
)
def test_tool_numbers_and_flutes_that_match_the_tools_table_pass(note):
    assert rows(bundle([{"ops": [FACE, {**DRILL, "note": note}]}]))["S1:20"].status == "pass"


@pytest.mark.parametrize(
    "note", ["Use T1 instead of the old 2-flute cutter.", "T1 replaces the old 2-flute cutter."]
)
def test_a_flute_count_that_describes_another_cutter_is_not_attributed_to_the_tool(note):
    assert errors(bundle([{"ops": [{**FACE, "note": note}]}])) == {}


def test_a_flute_count_the_inventory_cannot_confirm_is_unknown_not_passed():
    data = bundle([{"ops": [{**FACE, "note": "Use T1, the 2-flute cutter."}]}])
    inventory = deepcopy(data.inventory)
    del inventory["tools"]["em4"]["flutes"]
    assert rows(replace(data, inventory=inventory))["S1:10"].status == "unknown"


@pytest.mark.parametrize("note", ["Saw the 6061-T6 bar to length.", "the T3 trial-cut land"])
def test_a_t_number_inside_a_name_or_naming_a_frame_is_not_a_tool(note):
    data = bundle([{"ops": [FACE, {**DRILL, "note": note}]}], frames={"T3": {}})
    assert errors(data) == {}


def test_a_tool_number_beyond_a_table_with_an_unchosen_tool_is_unknown():
    ops = [FACE, {**DRILL, "tool": "unknown", "note": "Drill with T2."}]
    assert rows(bundle([{"ops": ops}]))["S1:20"].status == "unknown"


# ------------------------------------------------------------ jaw heights
def bar(note, top=0.525, bottom=-18.525, jaw=13.1953):
    return {
        "stock_state": {"top_z": top, "bottom_z": bottom},
        "hold": {"fixture": "vise", "jaw_above_parallels_mm": jaw, "note": note},
    }


BAR_BOX = kernel([-10, -10, -18.525, 10, 10, 0.525])


def test_the_hold_prints_the_work_top_height_above_the_jaw_tops():
    page = sheet(bundle([bar("Bar flat on parallels.")]))
    assert "work top above jaw tops mm" in page and "5.855" in page


@pytest.mark.parametrize("jaws", ["the jaws", "the jaw tops"])
def test_the_stated_height_of_the_work_above_the_jaws_must_match_the_hold(jaws):
    found = errors(bundle([bar(f"Bar flat on parallels; the bar stands 5.3 mm above {jaws}.")]))
    assert "jaw_above_parallels_mm" in found["S1"] and "5.855" in found["S1"]


@pytest.mark.parametrize("stated", ["5.9", "5.85", "6"])
def test_a_height_above_the_jaws_agrees_to_its_stated_precision(stated):
    note = f"Bar flat on parallels; the raw bar stands {stated} mm above the jaws."
    assert rows(bundle([bar(note)], kernel=BAR_BOX))["S1"].status == "pass"


@pytest.mark.parametrize(
    "note",
    [
        "The stop stands 2 mm above the jaws; the work stands 5.855 mm above the jaws.",
        "Before this setup the stock stands 8 mm above the jaws; now it stands 5.855 mm above "
        "the jaws.",
        "The work stands 5.8 mm above the jaws (+/- 0.2 mm).",
    ],
)
def test_a_height_above_the_jaws_of_another_object_state_or_tolerance_is_not_an_error(note):
    assert errors(bundle([bar(note)])) == {}


def test_a_stated_height_above_the_jaws_without_the_jaw_height_is_unknown():
    data = bundle([bar("The work stands 5.855 mm above the jaws.", jaw="not_applicable")], BAR_BOX)
    assert rows(data)["S1"].status == "unknown"


def test_a_z_stated_above_the_jaw_tops_must_match_the_jaw_top_height():
    good = "Rough only down to Z +16, 5.63 mm above the jaw tops."
    assert errors(bundle([bar(good, top=27.2, bottom=-6.0, jaw=16.3703)])) == {}
    bad = "Rough only down to Z +16, 6.5 mm above the jaw tops."
    assert "jaw tops" in errors(bundle([bar(bad, top=27.2, bottom=-6.0, jaw=16.3703)]))["S1"]


# ------------------------------------------------------------ stock heights vs kernel
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


def test_an_unknown_top_feature_leaves_a_top_below_the_kernel_stock_unknown():
    box = kernel([-10, -10, -10, 10, 10, 0])
    below = {"stock_state": {"top_z": -5.0, "bottom_z": -10.0, "top_feature": "unknown"}}
    assert rows(bundle([below], kernel=box))["S1"].status == "unknown"
    above = {"stock_state": {"top_z": 1.0, "bottom_z": -10.0, "top_feature": "unknown"}}
    assert "top_z" in errors(bundle([above], kernel=box))["S1"]


def test_without_a_kernel_stock_box_the_heights_are_unknown_not_passed():
    state = {"stock_state": {"top_z": 22.3702, "bottom_z": -22.3702}}
    assert rows(bundle([state], kernel={"status": "unknown"}))["S1"].status == "unknown"


def test_an_unknown_authored_height_is_unknown_even_when_the_other_agrees():
    state = {"stock_state": {"top_z": "unknown", "bottom_z": -10.0}}
    data = bundle([state], kernel=kernel([-10, -10, -10, 10, 10, 0]))
    assert rows(data)["S1"].status == "unknown"


def test_authored_heights_without_plan_units_are_unknown_not_passed():
    setup = {"stock_state": {"top_z": 0.0, "bottom_z": -10.0}, "note": "Touch T1.", "ops": [FACE]}
    data = bundle([setup], kernel=kernel([-10, -10, -10, 10, 10, 0]))
    data = replace(data, features={"units": "unknown", "features": {}})
    assert rows(data)["S1"].status == "unknown"


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
        "Push both plugs through the hole.",
        "Push the NO-GO plug through the hole, but do not force it.",
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
        "Push the GO plug through and verify the NO-GO plug cannot pass through.",
        "Try to push the NO-GO plug through; it must not enter.",
    ],
)
def test_a_no_go_plug_that_does_not_enter_is_not_an_error(method):
    assert errors(bundle([{"ops": [gauged(method)]}])) == {}
