"""One fact, one source: free text must not restate a derived fact, nor contradict a field."""

import re
from copy import deepcopy
from dataclasses import replace
from html import unescape
from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.rules import consistency
from prechips.rules.resolution import jaw_top_z
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


@pytest.mark.parametrize("keep", [True, False])
@pytest.mark.parametrize(
    ("source", "where", "text"),
    [
        ("S0", "stop", "same chucking as S0; do not loosen the jaws."),
        ("S0-A", "note", "Use the same chucking as S0-A."),
        ("rough-turn", "note", "Use the same chucking as rough-turn."),
        ("S0", "note", "Use the same chucking as S0-A."),
        ("S0", "note", "This is not the same chucking as S0; loosen and re-clamp the work."),
        ("S0", "stock", "the same chucking turned 12.5182 degrees."),
        (None, "stop", "same chucking as S0; do not loosen the jaws."),
    ],
)
def test_text_restating_the_chucking_is_an_error_whatever_the_transfer_says(
    source, where, text, keep
):
    setup = {"hold": {"stop": text} if where == "stop" else {"note": text}}
    if where == "stock":
        setup = {"stock_state": {"note": text}}
    if source:
        transfer = {**TRANSFER, "from": source, "keep_clamped": keep, "recovery": "re-plan"}
        setup["zero"] = {"transfer": transfer}
    found = errors(bundle([setup]))["S1"]
    assert "same chucking" in found and "keep_clamped" in found and "drop" in found


@pytest.mark.parametrize(
    "note",
    [
        "Do not loosen the toolpost; loosen the workpiece jaws for transfer.",
        "Do not loosen the jaws.",
        "Leave it in the chuck, never loosen it.",
        "Use the same chuck as S0.",
    ],
)
def test_other_chucking_wording_is_not_read(note):
    data = bundle([{"hold": {"note": note}, "zero": {"transfer": TRANSFER}}])
    assert rows(data)["S1"].status == "not_applicable"


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
    "note",
    [
        "Leave the nut hand tight.",
        "M6 nut on the button stud, hand-tight.",
        "Do not leave this clamp hand tight; torque it to 15 N m.",
        "Hand tight for alignment; torque C1 to 15 N m.",
        "Initially hand-tightened for alignment.",
        "Nut tightened by hand.",
        "Finish by tightening by hand.",
        "Keep it finger tight.",
    ],
)
@pytest.mark.parametrize("field", [{"tighten": "hand"}, {"torque_nm": 15}, {}])
def test_a_clamp_note_restating_its_tightening_is_an_error(note, field):
    hold = {"clamps": [{"ref": "strap", "note": note, **field}], "clamp_order": [1]}
    found = errors(bundle([{"hold": hold}]))["S1"]
    assert "C1" in found and "tighten / torque_nm" in found and "drop" in found


STRAP = {"ref": "strap", "torque_nm": 15}


@pytest.mark.parametrize(
    "hold",
    [
        {"clamps": [{**STRAP, "note": "Run the nut down by hand."}], "clamp_order": [1]},
        {"clamps": [STRAP], "clamp_order": [1], "clamp": "Strap C1, hand tight."},
        {"clamps": [STRAP], "clamp_order": [1], "note": "Leave the nut hand tight."},
        {"clamps": [{**STRAP, "note": "Leave the nut hand tight."}]},
    ],
)
def test_hand_tightening_outside_an_ordered_clamp_note_is_not_read(hold):
    assert rows(bundle([{"hold": hold}]))["S1"].status == "not_applicable"


def test_a_hand_tight_clamp_cannot_also_carry_a_torque():
    hold = {"clamps": [{"ref": "strap", "tighten": "hand", "torque_nm": 15}], "clamp_order": [1]}
    assert "torque_nm" in errors(bundle([{"hold": hold}]))["S1"]


# ------------------------------------------------------------ tool numbers
def test_a_tool_number_in_text_must_be_on_the_setup_tools_table():
    found = errors(bundle([{"ops": [FACE, {**DRILL, "note": "Change to T3 for the hole."}]}]))
    assert "TOOLS" in found["S1:20"]


@pytest.mark.parametrize("count", [2, 8, 9, 10, 12])
@pytest.mark.parametrize(
    "form",
    [
        "Use T1 ({n}-flute) for this cut.",
        "Use the {n}-flute T1 for this cut.",
        "Use T1, the {n}fl cutter.",
    ],
)
def test_a_flute_count_bound_to_a_tool_number_must_match_its_inventory(form, count):
    note = form.format(n=count)
    assert "4 flutes" in errors(bundle([{"ops": [{**FACE, "note": note}]}]))["S1:10"]


@pytest.mark.parametrize(
    "note", ["Touch T1 on the top first.", "Touch T1, the 4fl cutter, on top.", "Use T1 (4-flute)."]
)
def test_tool_numbers_and_flutes_that_match_the_tools_table_pass(note):
    assert rows(bundle([{"ops": [FACE, {**DRILL, "note": note}]}]))["S1:20"].status == "pass"


@pytest.mark.parametrize(
    "note",
    [
        "Use T1 instead of the old 2-flute cutter.",
        "T1 replaces the old 2-flute cutter.",
        "Use T1 (two-flute) for this cut.",
        "Use the 1.5-flute T1 for this cut.",
    ],
)
def test_a_flute_count_not_bound_in_digits_to_one_tool_number_is_not_read(note):
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


@pytest.mark.parametrize("rail", ["unknown", -21.0])
def test_an_unknown_rail_leaves_the_jaw_tops_and_the_work_top_height_unknown(rail):
    setup = bar("Bar flat on parallels.")
    setup["stock_state"]["retained_rail_bottom_z"] = rail
    page = sheet(bundle([setup]))
    derived = jaw_top_z(setup, setup["hold"], 1.0)
    if rail == "unknown":
        assert derived is None and "5.855" not in page
        assert "work top above jaw tops mm" in page and "? seat or stock top unknown" in page
    else:
        assert derived == pytest.approx(-21.0 + 13.1953) and "8.330" in page


@pytest.mark.parametrize(
    "note",
    [
        "Bar flat on parallels; the raw bar stands 5.855 mm above the jaw tops.",
        "Bar flat on parallels; it stands 5.3 mm above the jaws.",
        "Z 0.525, 5.855 mm above the jaw tops.",
        "Before re-seating, Z 0.525, 8 mm above the jaw tops.",
        "The work stands 5.8 mm above the jaws (tolerance +/- 0.2 mm).",
        "The stop stands 2 mm above the vise jaws.",
        "The foot top is 0.1 in below the jaw top.",
    ],
)
def test_a_height_from_the_jaw_tops_in_a_vise_hold_restates_the_derived_jaws(note):
    found = errors(bundle([bar(note)], kernel=BAR_BOX))["S1"]
    assert "jaw_above_parallels_mm" in found and "Z values" in found and "drop" in found


def test_an_op_note_restating_a_height_from_the_jaw_tops_errors_on_the_op():
    op = {**FACE, "note": "Rough only down to Z -2, 2.5 mm above the jaw tops."}
    setup = {**bar("Bar flat on parallels."), "ops": [op]}
    assert "jaw_above_parallels_mm" in errors(bundle([setup], kernel=BAR_BOX))["S1:10"]


@pytest.mark.parametrize(
    ("note", "jaw"),
    [
        ("The work stands 30 mm above the jaws.", None),
        ("The roughing stays within 18.33 mm of the jaw tops.", 13.1953),
        ("Keep the cut clear of the jaw tops.", 13.1953),
    ],
)
def test_other_jaw_wording_or_a_hold_without_a_jaw_height_is_not_read(note, jaw):
    setup = {"hold": {"note": note}} if jaw is None else bar(note, jaw=jaw)
    setup.pop("stock_state", None)
    assert rows(bundle([setup]))["S1"].status == "not_applicable"


# ------------------------------------------------------------ stock heights vs kernel
def test_authored_stock_heights_must_match_the_kernel_stock_the_setup_receives():
    state = {"stock_state": {"top_z": 22.3702, "bottom_z": -22.3702}}
    found = errors(bundle([state], kernel=kernel([-50, -20, -22.376691, 50, 20, 22.414118])))
    assert "top_z" in found["S1"] and "bottom_z" in found["S1"]


def test_stock_heights_within_the_kernel_tolerance_pass():
    state = {"stock_state": {"top_z": 0.0, "bottom_z": -24.2}}
    assert errors(bundle([state], kernel=kernel([-9, -22, -24.2, 9, 4, 1e-6]))) == {}


def test_a_seat_above_a_lower_rail_is_not_compared_with_the_box_bottom():
    state = {"stock_state": {"top_z": 0.0, "bottom_z": -7.08, "retained_rail_bottom_z": -11.528}}
    row = rows(bundle([state], kernel=kernel([-170, -40, -11.528, 170, 40, 0.0])))["S1"]
    assert row.status == "unknown" and "bottom_z -7.08" in row.sentence


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ({"retained_rail_bottom_z": -20.0}, "error"),
        ({"top_z": 0.0, "retained_rail_bottom_z": -20.0}, "error"),
        ({"top_z": 0.0, "bottom_z": -10.0, "retained_rail_bottom_z": -20.0}, "error"),
        ({"retained_rail_bottom_z": -5.0}, "unknown"),
        ({"retained_rail_bottom_z": -10.0}, "unknown"),
        ({"top_z": 0.0, "bottom_z": -10.0, "retained_rail_bottom_z": -10.0}, "pass"),
    ],
)
def test_a_rail_alone_is_compared_only_where_the_box_bottom_proves_it(state, status):
    data = bundle([{"stock_state": state}], kernel=kernel([-10, -10, -10, 10, 10, 0]))
    assert rows(data)["S1"].status == status


def test_a_touched_top_feature_below_the_stock_top_is_unknown_and_above_it_an_error():
    box = kernel([-170, -40, -11.528, 170, 40, 4.47175])
    below = {"stock_state": {"top_feature": "hub", "top_z": 0.0, "bottom_z": -11.528}}
    row = rows(bundle([below], kernel=box))["S1"]
    assert row.status == "unknown" and "hub" in row.sentence
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
