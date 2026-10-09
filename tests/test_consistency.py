"""One fact, one source: free text must not restate a derived fact, nor contradict a field."""

import itertools
import re
import sys
from copy import deepcopy
from dataclasses import replace
from functools import cache
from html import unescape
from pathlib import Path
from unicodedata import category, decomposition, normalize

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
    "fixtures": {
        "buttons": {"kind": "custom"},
        "strap": {"kind": "strap_clamp"},
        "par": {"kind": "parallels", "height_mm": 20.0},
        "par-verify": {"kind": "parallels", "height_mm": 20.0, "verify": True},
        "par-bare": {"kind": "parallels"},
    },
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
    assert re.search(r"C1\b[^|.;]*\bhand only\b", page)
    assert re.search(r"C1\b[^|.;]*\bno wrench\b", page)
    assert "tighten fully" not in page


def test_mixed_hand_and_wrench_clamps_name_the_hand_ones():
    hold = {
        "clamps": [{"ref": "strap"}, {"ref": "buttons", "tighten": "hand"}],
        "clamp_order": [1, 2],
    }
    page = sheet(bundle([{"hold": hold}]))
    assert re.search(r"order\b[^|.;]*\bC1,\s*C2\b", page)
    assert re.search(r"\bsnug\b[^|.;]*\bthen\b[^|.;]*\btighten\b", page)
    assert "fully" in page and "same order" in page
    assert re.search(r"C2\b[^|.;]*\bhand only\b[^|.;]*\bno wrench\b", page)
    assert not re.search(r"C1\b[^|.;:]*\bhand only\b", page)


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


def test_one_tool_spelled_two_ways_is_one_tool_number_in_the_check_and_the_table():
    # ``em4`` and ``tools.em4`` select one cutter: TOOLS prints one T1, so T2 is not a tool.
    second = {**FACE, "op": 20, "tool": "tools.em4", "note": "Finish with T2."}
    data = bundle([{"ops": [FACE, second]}])
    assert "has T1" in errors(data)["S1:20"]
    assert "T2" not in re.findall(r"\|(T\d+)\|", sheet(data))


# ------------------------------------------------------------ jaw heights
def bar(note, top=0.525, bottom=-18.525, jaw=13.1953):
    return {
        "stock_state": {"top_z": top, "bottom_z": bottom},
        "hold": {
            "fixture": "vise",
            "parallels": "par",
            "jaw_above_parallels_mm": jaw,
            "note": note,
        },
    }


BAR_BOX = kernel([-10, -10, -18.525, 10, 10, 0.525])


def work_top(data):
    """The work-top-above-the-jaw-tops fact the HOLD of the bundle's first setup prints."""
    setup = data.plan["setups"][0]
    facts = _Traveler(data, [], {}, None).hold_facts(setup, setup["hold"], False)
    return dict(facts)["work top above jaw tops mm"]


def test_the_hold_prints_the_work_top_height_above_the_jaw_tops():
    data = bundle([bar("Bar flat on parallels.")])
    page = sheet(data)
    assert work_top(data) == "5.855" and "work top above jaw tops mm" in page and "5.855" in page


UNSET = "? jaw height, parallels, seat or stock top unknown or unverified"


@pytest.mark.parametrize("rail", ["unknown", -21.0])
def test_an_unknown_rail_leaves_the_jaw_tops_and_the_work_top_height_unknown(rail):
    setup = bar("Bar flat on parallels.")
    setup["stock_state"]["retained_rail_bottom_z"] = rail
    data = bundle([setup])
    derived = jaw_top_z(data, setup, setup["hold"], 1.0)
    if rail == "unknown":
        assert derived is None and work_top(data) == UNSET
    else:
        assert derived == pytest.approx(-21.0 + 13.1953) and work_top(data) == "8.330"


@pytest.mark.parametrize(
    "hold",
    [
        {"jaw_above_parallels_mm_verify": True},
        {"jaw_above_parallels_mm_verify": "unknown"},
        {"jaw_above_parallels_mm": -2.0},
        {"parallels": "unknown"},
        {"parallels": "no-such-parallels"},
        {"parallels": "par-verify"},
        {"parallels": "par-bare"},
    ],
)
def test_a_pending_or_unknown_jaw_input_leaves_the_jaw_tops_unknown(hold):
    setup = bar("Bar flat on parallels.")
    setup["hold"].update(hold)
    data = bundle([setup])
    assert jaw_top_z(data, setup, setup["hold"], 1.0) is None
    assert work_top(data) == UNSET


@pytest.mark.parametrize(
    "hold", [{}, {"jaw_above_parallels_mm_verify": False}, {"parallels": "none"}]
)
def test_accepted_jaw_inputs_give_the_jaw_tops(hold):
    setup = bar("Bar flat on parallels.")
    setup["hold"].update(hold)
    data = bundle([setup])
    assert jaw_top_z(data, setup, setup["hold"], 1.0) == pytest.approx(-18.525 + 13.1953)
    assert work_top(data) == "5.855"


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


def test_a_touched_top_feature_the_kernel_did_not_measure_is_unknown_against_any_stock_top():
    box = kernel([-170, -40, -11.528, 170, 40, 4.47175])
    for top in (0.0, 4.47175, 4.6):
        state = {"stock_state": {"top_feature": "hub", "top_z": top, "bottom_z": -11.528}}
        row = rows(bundle([state], kernel=box))["S1"]
        assert row.status == "unknown" and "top_feature hub" in row.sentence


def test_an_unknown_top_feature_leaves_a_top_below_the_kernel_stock_unknown():
    box = kernel([-10, -10, -10, 10, 10, 0])
    below = {"stock_state": {"top_z": -5.0, "bottom_z": -10.0, "top_feature": "unknown"}}
    assert rows(bundle([below], kernel=box))["S1"].status == "unknown"
    above = {"stock_state": {"top_z": 1.0, "bottom_z": -10.0, "top_feature": "unknown"}}
    assert "top_z" in errors(bundle([above], kernel=box))["S1"]


# ------------------------------------------------------------ named faces vs kernel
# The rocker hub: two faces 7.0565 apart (its nominal), drawn 7.0565-7.1065 thick.
HUB = {
    "kind": "face",
    "requirements": ["length"],
    "length": [7.0565, 7.1065],
    "length_nominal": 7.0565,
}
RAIL = -11.52825
RAW_TOP = (-170, -40, RAIL, 170, 40, 4.47175)
CUT_TOP = (-170, -40, RAIL, 170, 40, 0.0)
# S2 seats the hub's faced lower face; its upper face is still under raw stock. S3 has both.
S2 = {
    "top_feature": "hub",
    "bottom_feature": "hub",
    "top_z": 4.47175,
    "bottom_z": -7.08,
    "retained_rail_bottom_z": RAIL,
}
S3 = {**S2, "top_z": 0.0}


def hub(state, *, up=(0.0, 0.0), down=(-7.0565, -7.0565), box=CUT_TOP, feature=HUB, faces=None):
    """``state`` against a kernel giving each hub face's finished Z and the setup-entry
    stock's Z over (``up``) or under (``down``) it, as (face, stock)."""
    if faces is None:
        faces = {
            "hub": {
                "up": {"face_z": up[0], "stock_z": up[1]},
                "down": {"face_z": down[0], "stock_z": down[1]},
            }
        }
    facts = {"stock_bbox_mm": list(box), "stock_faces_mm": faces}
    data = bundle([{"stock_state": state}], kernel={"status": "ok", "setups": {"S1": facts}})
    return replace(data, features={"units": "mm", "features": {"hub": feature}})


def test_named_faces_inside_their_drawing_band_pass():
    assert rows(hub(S2, up=(0.0, 4.47175), box=RAW_TOP))["S1"].status == "pass"
    assert rows(hub(S3))["S1"].status == "pass"


@pytest.mark.parametrize("bottom", [-7.2, -7.0])
def test_a_seated_face_outside_its_band_is_an_error(bottom):
    found = errors(hub({**S2, "bottom_z": bottom}, up=(0.0, 4.47175), box=RAW_TOP))["S1"]
    assert f"bottom_z {bottom:g}" in found and "hub" in found and "7.0565" in found


@pytest.mark.parametrize(
    ("top", "bottom", "status"),
    [(0.04, -7.08, "error"), (-0.02, -7.08, "pass"), (5.0, -2.08, "error")],
)
def test_two_cut_faces_of_one_feature_are_judged_by_their_separation(top, bottom, status):
    # 7.12 apart is over the band. 7.06 is inside it, though the top is below its CAD Z.
    # 7.08 apart with both 5 mm off: no face moves more than the band's span.
    state = {**S3, "top_z": top, "bottom_z": bottom}
    assert rows(hub(state))["S1"].status == status


def test_a_named_face_still_under_raw_stock_is_compared_with_that_stock():
    found = errors(hub(S3, up=(0.0, 4.47175), box=RAW_TOP))["S1"]
    assert "top_z 0" in found and "4.4718" in found


@pytest.mark.parametrize(
    "feature", [{"kind": "face"}, {**HUB, "length_nominal": 5.0}, {**HUB, "length": "unknown"}]
)
def test_a_face_off_its_cad_place_without_a_provable_band_is_unknown(feature):
    row = rows(hub(S2, up=(0.0, 4.47175), box=RAW_TOP, feature=feature))["S1"]
    assert row.status == "unknown" and "bottom_z -7.08" in row.sentence
    at_cad = hub({**S2, "bottom_z": -7.0565}, up=(0.0, 4.47175), box=RAW_TOP, feature=feature)
    assert rows(at_cad)["S1"].status == "pass"


@pytest.mark.parametrize(
    "faces",
    [
        {},
        {"hub": {"reason": "feature hub has no resolved faces"}},
        {"hub": {"up": {"face_z": 0.0, "stock_z": 4.47175}, "down": {"reason": "no -Z face"}}},
    ],
)
def test_a_named_face_the_kernel_did_not_measure_leaves_its_height_unknown(faces):
    row = rows(hub(S2, box=RAW_TOP, faces=faces))["S1"]
    assert row.status == "unknown" and "bottom_z -7.08" in row.sentence


def test_a_seat_without_a_bottom_feature_is_not_compared_with_a_face():
    state = {key: value for key, value in S2.items() if key != "bottom_feature"}
    row = rows(hub(state, up=(0.0, 4.47175), box=RAW_TOP))["S1"]
    assert row.status == "unknown" and "bottom_z -7.08" in row.sentence


def test_a_named_seat_at_the_stock_bottom_is_judged_by_its_band_and_one_above_it_errors():
    state = {"bottom_feature": "hub", "bottom_z": -7.08}
    assert rows(hub(state, box=(-170, -40, -7.0565, 170, 40, 0.0)))["S1"].status == "pass"
    # Stock hangs below the seated face elsewhere: the stock's lowest point is not authored.
    assert "bottom_z" in errors(hub(state, box=(-170, -40, -9.0, 170, 40, 0.0)))["S1"]


# Each authored height is judged by the one evidence source its declaration designates: a
# named face by the kernel's height of that face (unmeasured: unknown, the box never
# standing in), an unnamed seat and a rail by the stock box's lowest point. The box also
# proves the stock's lowest point is authored: a named seat whose measured face is not the
# box's lowest point leaves stock below it that nothing authored reaches.
# A plate between faces at Z -10 (the box bottom) and Z 0, drawn 9.95-10.05 thick:
# "outside" is its seat grown 0.025 below the box and "shrunk" 0.025 inward, both inside
# that band; "inside" a step face at Z -8.
SEAT = {
    "extreme": (-10.0, -10.0),
    "inside": (-8.0, -8.0),
    "outside": (-10.0, -10.025),
    "shrunk": (-10.0, -9.975),
}
PLATE = {
    "kind": "face",
    "requirements": ["length"],
    "length": [9.95, 10.05],
    "length_nominal": 10.0,
}
SEAT_VERDICTS = {
    # declaration: {height: (no rail, rail equal, rail 1 above, rail below)}
    "named": {
        "extreme": ("pass", "pass", "unknown", "error"),
        "inside": ("error", "error", "error", "pass"),
        "outside": ("pass", "error", "unknown", "error"),
        "shrunk": ("pass", "error", "unknown", "pass"),
    },
    "unresolved": {
        "extreme": ("unknown", "unknown", "unknown", "error"),
        "inside": ("unknown", "error", "unknown", "unknown"),
        "outside": ("unknown", "error", "unknown", "error"),
        "shrunk": ("unknown", "error", "unknown", "unknown"),
    },
    "unnamed": {
        "extreme": ("pass", "pass", "unknown", "error"),
        "inside": ("error", "error", "error", "unknown"),
        "outside": ("error", "error", "error", "error"),
        "shrunk": ("error", "error", "error", "unknown"),
    },
}
RAILS = ("none", "equal", "above", "below")


def plate(state, *, up=0.0, down=-10.0, measured=True, units="mm", feature=PLATE):
    """``state`` (mm) against the box (-50, -50, -10, 50, 50, 0) and a kernel that measures
    the plate's cut faces at Z ``up`` and ``down``, or gives the reason it could not; the
    plan states the heights and the plate's band in ``units``."""
    cut = {"up": {"face_z": up, "stock_z": up}, "down": {"face_z": down, "stock_z": down}}
    unmeasured = {side: {"reason": "no planar face of plate faces that way"} for side in cut}
    facts = {
        "stock_bbox_mm": [-50, -50, -10.0, 50, 50, 0.0],
        "stock_faces_mm": {"plate": cut if measured else unmeasured},
    }
    scale = {"mm": 1.0, "in": 25.4}[units]
    state = {key: v / scale if isinstance(v, float) else v for key, v in state.items()}
    feature = dict(feature)
    if "length" in feature:
        feature["length"] = [v / scale for v in feature["length"]]
        feature["length_nominal"] /= scale
    data = bundle([{"stock_state": state}], kernel={"status": "ok", "setups": {"S1": facts}})
    return replace(data, features={"units": units, "features": {"plate": feature}})


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize("declared", [*SEAT_VERDICTS, "unnamed, plate measured"])
@pytest.mark.parametrize("height", list(SEAT))
@pytest.mark.parametrize("rail", RAILS)
def test_each_low_height_is_judged_by_the_one_source_its_declaration_names(
    declared, height, rail, units
):
    face, seat = SEAT[height]
    state = {"bottom_z": seat}
    if declared in ("named", "unresolved"):
        state["bottom_feature"] = "plate"
    if rail != "none":
        state["retained_rail_bottom_z"] = {
            "equal": seat,
            "above": seat + 1.0,
            "below": -10.0 if seat > -10.0 else seat - 1.0,
        }[rail]
    data = plate(state, down=face, measured=declared != "unresolved", units=units)
    expected = SEAT_VERDICTS[declared.partition(",")[0]][height][RAILS.index(rail)]
    assert rows(data)["S1"].status == expected


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize(
    ("top", "bottom", "feature", "status"),
    [
        # Both cut faces moved up together, 10 apart: 0.025, and 0.1, the band's span, are
        # inside it; 0.2 is past it.
        (0.025, -9.975, PLATE, "pass"),
        (0.1, -9.9, PLATE, "pass"),
        (0.2, -9.8, PLATE, "error"),
        # The seat alone moved 0.025 inward with no band to judge it by, and 0.1 inward,
        # past its band's 0.05 shrink.
        (None, -9.975, {"kind": "face"}, "unknown"),
        (None, -9.9, PLATE, "error"),
    ],
)
def test_a_seat_moved_inward_from_the_box_bottom_is_judged_by_its_band_alone(
    top, bottom, feature, status, units
):
    # The seat's measured face is the stock's lowest point: no other stock hangs below it.
    state = {"bottom_feature": "plate", "bottom_z": bottom}
    if top is not None:
        state.update(top_feature="plate", top_z=top)
    assert rows(plate(state, units=units, feature=feature))["S1"].status == status


@pytest.mark.parametrize(
    ("declared", "height", "status"),
    [
        ("named", "extreme", "pass"),
        ("named", "inside", "pass"),
        ("named", "outside", "pass"),
        ("unresolved", "extreme", "unknown"),
        ("unresolved", "inside", "unknown"),
        ("unresolved", "outside", "unknown"),
        ("unnamed", "extreme", "pass"),
        ("unnamed", "inside", "error"),
        ("unnamed", "outside", "error"),
        ("unnamed, plate measured", "inside", "error"),
    ],
)
def test_a_top_is_judged_by_its_named_face_alone_or_else_by_the_box_top(declared, height, status):
    # Mirrored: the face at Z 0 (the box top), a touched step at Z -2, grown 0.025 above.
    face, top = {"extreme": (0.0, 0.0), "inside": (-2.0, -2.0), "outside": (0.0, 0.025)}[height]
    state = {"top_z": top}
    if declared in ("named", "unresolved"):
        state["top_feature"] = "plate"
    assert rows(plate(state, up=face, measured=declared != "unresolved"))["S1"].status == status


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


# ------------------------------------------------------------ shop-made make notes
def jig(*solids, decimals=1):
    """A setup held on a shop-made jig of ``solids``, made to ``decimals`` places."""
    pose = {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]}
    data = bundle([{"hold": {"fixture": "jig", "pose": pose}}])
    fixtures = {**INVENTORY["fixtures"], "jig": {"kind": "custom", "solids": list(solids)}}
    return replace(
        data,
        inventory={**INVENTORY, "fixtures": fixtures},
        policy={"numbers": {"fixture_make_decimals": decimals}},
    )


def block(name, size, note=None, **extra):
    solid = {"name": name, "shape": "box", "at_mm": [0, 0, 0], "size_mm": size, **extra}
    return {**solid, "note": note} if note else solid


def rod(name, dia, length, note=None, **extra):
    solid = {
        "name": name,
        "shape": "cylinder",
        "at_mm": [0, 0, 20],
        "axis": [0, 0, 1],
        "dia_mm": dia,
        "length_mm": length,
        **extra,
    }
    return {**solid, "note": note} if note else solid


ARM = "1/2 x 3/8 in bar (bought), sawn, then mill the arm to {}; drill the stop hole"


@pytest.mark.parametrize(
    "size",
    [
        "11 x 10 x 65.16",
        "65.2 × 11 × 10",
        "11.0 wide x 10 high x 65.20 long (±0.1)",
        "158.67 (the plate's length) x 11 x 10",
        "65.2 x 11 x 10 (±0.1 (approx))",
        "65.2 x 11 x 10 (approx",
        "65.2 x 11 x 10' long",
        "65.16 mm x 11 mm x 10 mm",
        "2.57 x 0.43 x 0.39 inches",
        "2.57 x 0.43 x 0.39 (in)",
        "2.57 x 0.43 x 0.39 in",
        '2.57" x 0.43" x 0.39"',
        "11 x 10 x unknown",
        "11 x 10 x ?",
        "unknown x 11 x 10",
    ],
)
def test_a_make_note_giving_a_named_made_row_s_size_restates_it(size):
    # The table prints the arm 65.2 × 11 × 10: in any value, unit or order, or with an
    # unknown edge, the note restates it.
    row = rows(jig(block("arm", [65.1631, 11, 10], ARM.format(size))))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 1)
    assert f'"the arm to {size}"' in row.sentence and "arm 65.2 × 11 × 10" in row.sentence
    assert "drop the restatement" in row.sentence


@pytest.mark.parametrize(
    "note",
    [
        "3/4 in round (bought): turn the screw Ø6.4 x 13.5, cut 1/4-20",
        "turned the screw Ø6.30 x 13.45 on the lathe",
        "turn the screw to 6.35 x 13.5",
        "turn the screw to Ø6.4 mm x 13.5 mm",
        # A feature verb or a fraction in another clause or sentence governs nothing here.
        "drill the bore, then turn the screw to Ø6.4 x 13.5",
        "Drill the 1/4 bore. Turn the screw Ø6.4 x 13.5",
        "Turn the screw Ø6.4 x 13.5 mm. Drill the bore",
    ],
)
def test_a_named_cylinder_s_diameter_and_length_restate_its_size(note):
    row = rows(jig(rod("screw", 6.35, 13.45, note)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 1)
    assert "screw Ø6.4 × 13.5" in row.sentence


SPACINGS = ("{a} {by} {b}", "{a}{by}{b}", "{a} {by}{b}", "{a}{by} {b}")
SEPARATORS = ("x", "X", "×", "*")
UNITS = ("", "mm", " in", " (inches)", " mm.")
SHAPING = ("turn", "mill", "finish")
FEATURE = ("drill", "bore", "ream", "tap", "counterbore", "countersink", "spot", "chamfer")
ANGLES = ("", "°", " deg", " degrees", " (deg)", " (°)", "º", " (nominal) (deg)", " mm. (deg)")


def named_size_edges(note, name):
    """Real parser output, independent of bundle construction and diagnostic prose."""
    return [(key, edges) for key, _, edges in consistency._named_sizes(note, [(name,)])]


def test_a_named_cylinder_size_is_restated_in_every_spacing_separator_unit_and_verb():
    # The stud prints Ø10 × 50. Only a feature verb (a hole or a chamfer) governing the
    # statement, or an angle on either edge, makes it something other than the size.
    wrong = []
    for spacing, by, unit, verb, angle, first in itertools.product(
        SPACINGS, SEPARATORS, UNITS, SHAPING + FEATURE, ANGLES, (True, False)
    ):
        a, b = ("4" + angle, "8" + unit) if first else ("4" + unit, "8" + angle)
        note = f"{verb.title()} the stud to Ø" + spacing.format(a=a, by=by, b=b)
        actual = named_size_edges(note, "stud")
        expected = [(("stud",), 2)] if verb in SHAPING and not angle else []
        if actual != expected:
            wrong.append((note, actual))
    assert wrong == []


TOOLING = (
    "",
    " from drill rod",
    " from drill-rod",
    " from drill - rod",
    " using a boring bar",
    " using a bore gauge",
    " using a boring tool",
    " with a tap wrench",
    " on the mill",
    " (use the mill)",
    " (use a sharp bit, lubricate well)",
    " with a 4 mm. bit",
)


def test_the_verb_governs_a_named_size_whatever_tooling_text_its_clause_holds():
    # A feature verb anywhere in the clause, a hyphenated one or one in parentheses
    # included, makes the size its feature's; a feature word before a tool or stock noun
    # (drill rod, drill-rod, boring bar) is that noun's, and no verb.
    wrong = []
    verbs = SHAPING + FEATURE + ("spot-drill", "counter-sink", "c'bore", "re-drill")
    for verb, tooling, before in itertools.product(verbs, TOOLING, (True, False)):
        lead, tail = (tooling, "") if before else ("", tooling)
        note = f"{verb.capitalize()}{lead} the stud to Ø4 x 8 deep{tail}"
        actual = named_size_edges(note, "stud")
        expected = [(("stud",), 2)] if verb in SHAPING else []
        if actual != expected:
            wrong.append((note, actual))
    elsewhere = (" (then drill)", " and drill", " and counter-sink", " (spot, then drill)")
    for verb, feature, before in itertools.product(SHAPING, elsewhere, (True, False)):
        lead, tail = (feature, "") if before else ("", feature)
        note = f"{verb.capitalize()}{lead} the stud to Ø4 x 8{tail}"
        actual = named_size_edges(note, "stud")
        if actual != []:
            wrong.append((note, actual))
    assert wrong == []


NOT_EDGES = ("1/2", "1 / 2", "½", "1⁄2", "1∕2", "4½", "4 1/2", "8²", "8,5")
NOT_EDGES += ("8-10", "8 - 10", "8–10", "8—10", "8−10")


def test_a_fraction_range_or_split_number_is_no_edge_of_a_named_size():
    # In any edge and with any unit: a fraction (ASCII, spaced, a vulgar or slashed glyph),
    # a range in any dash, a superscript or a decimal comma is not a size's edge.
    wrong = []
    for edge, unit, position in itertools.product(NOT_EDGES, UNITS, range(5)):
        cylinder = position < 2
        edges = ["4", "8"] if cylinder else ["65.2", "11", "10"]
        edges[position if cylinder else position - 2] = edge
        size = " x ".join(e + unit for e in edges)
        name = "stud" if cylinder else "arm"
        note = ("Turn the stud to Ø" if cylinder else "Mill the arm to ") + size
        actual = named_size_edges(note, name)
        if actual != []:
            wrong.append((note, actual))
    assert wrong == []


@cache
def unicode_grammar_domains():
    """Scan the complete Unicode domain once, only when its grammar tests execute."""
    punctuation, opens, closes, scripts = [], [], [], []
    for codepoint in range(sys.maxunicode + 1):
        glyph = chr(codepoint)
        folded = normalize("NFKC", glyph)
        if category(glyph).startswith("P"):
            if folded == "(":
                opens.append(glyph)
            if folded == ")":
                closes.append(glyph)
            if not set("()") & set(folded):
                punctuation.append(glyph)
        if decomposition(glyph).startswith(("<fraction>", "<super>", "<sub>")):
            scripts.append(glyph)
    kept = [s for s in scripts if any(d.isdigit() for d in normalize("NFKC", s))]
    kept += ["º", "˚", "¹/₂", "¹⁄₂", "¹ / ₂", "₁/₂"]
    folded = [s for s in scripts if s not in kept]
    return tuple(punctuation), tuple(opens), tuple(closes), tuple(kept), tuple(folded)


def test_a_parenthesis_that_closes_is_its_edge_s_whatever_punctuation_it_holds():
    # Before the row or on any edge, nested or a second one: a closed annotation splits no
    # clause and ends no size, whatever mark it holds (a ; included); the size goes on.
    wrong = []
    forms = ("(rough{p} finish later)", "(rough (check{p} measure))", "(rough) (check{p} measure)")
    punctuation, opens, closes, _, _ = unicode_grammar_domains()
    marks = [(p, "(", ")") for p in punctuation]
    marks += [(";", o, c) for o, c in itertools.product(opens, closes)]
    places = [(2, None), (2, 0), (2, 1), (3, None), (3, 0), (3, 1), (3, 2)]
    for (p, o, c), form, (arity, at) in itertools.product(marks, forms, places):
        annotation = " " + form.format(p=p).replace("(", o).replace(")", c)
        edges = ["4", "8"] if arity == 2 else ["65.2", "11", "10"]
        if at is not None:
            edges[at] += annotation
        lead = annotation if at is None else ""
        name = "stud" if arity == 2 else "arm"
        verb = "Turn" if arity == 2 else "Mill"
        note = f"{verb}{lead} the {name} to " + " x ".join(edges)
        actual = named_size_edges(note, name)
        if actual != [((name,), arity)]:
            wrong.append((note, actual))
    assert wrong == []


def test_a_kept_glyph_anywhere_in_the_clause_makes_a_named_size_ambiguous():
    # Before the row, or after the size bare or in parentheses: a fraction, a superscript
    # or subscript digit or an angle glyph leaves the size unread; a folded glyph does not.
    wrong = []
    forms = ("Turn from {g} rod the stud to 4 x 8", "Turn the stud to 4 x 8 (from {g} rod)")
    forms += ("Turn the stud to 4 x 8 from {g} rod", "Mill from {g} bar the arm to 65.2 x 11 x 10")
    forms += ("Mill the arm to 65.2 x 11 x 10 (from {g} bar)",)
    _, _, _, kept, folded = unicode_grammar_domains()
    for glyph, form in itertools.product(["", *kept, *folded], forms):
        note = form.format(g=glyph)
        name, arity = ("stud", 2) if "stud" in note else ("arm", 3)
        actual = named_size_edges(note, name)
        expected = [] if glyph in kept else [((name,), arity)]
        if actual != expected:
            wrong.append((note, actual))
    assert wrong == []


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("Turn the stud to Ø4mmx8mm", ("error", 1)),
        ("Turn the stud to 4（rough； finish later） x 8", ("error", 1)),
        ("Turn from ™ rod the stud to 4 x 8", ("error", 1)),
        ("Turn from ¹⁄₂ rod the stud to 4 x 8", ("not_applicable", 0)),
        ("Turn the stud to 4 x 8º", ("not_applicable", 0)),
        ("Turn the stud to 4 x 8 (then counter-sink)", ("not_applicable", 0)),
    ],
)
def test_named_size_parser_classification_reaches_the_consistency_consumer(note, expected):
    row = rows(jig(rod("stud", 10, 50, note)))["S1"]
    assert (row.status, row.numbers["claims"]) == expected


@pytest.mark.parametrize("name", ["thread", "slot", "knurl", "recess", "groove"])
def test_a_row_named_with_a_feature_word_is_read_by_its_name(name):
    # The row's name is no governing text: "the thread" names the thread row, no verb.
    row = rows(jig(rod(name, 10, 50, f"Turn the {name} to Ø4 x 8")))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 1)
    row = rows(jig(rod(name, 10, 50, f"Drill the {name} to Ø4 x 8 deep")))["S1"]
    assert (row.status, row.numbers["claims"]) == ("not_applicable", 0)


def test_every_lead_and_edge_of_a_named_whole_size_restates_it():
    wrong = []
    for lead, edge, spacing, unit in itertools.product(
        ("to Ø", "to Ø ", "Ø", "Ø ", "to ", ""), ("10", "?", "unknown"), SPACINGS, UNITS
    ):
        if edge == "unknown" and unit == "mm":
            continue  # "unknownmm" is one word, not an edge and its unit
        note = f"Turn the stud {lead}" + spacing.format(a=edge + unit, by="x", b="50" + unit)
        actual = named_size_edges(note, "stud")
        if actual != [(("stud",), 2)]:
            wrong.append((note, actual))
    for spacing, by, unit in itertools.product(SPACINGS, SEPARATORS, UNITS):
        edges = spacing.format(a="65.2" + unit, by=by, b="11" + unit)
        note = "Mill the arm to " + spacing.format(a=edges, by=by, b="10" + unit)
        actual = named_size_edges(note, "arm")
        if actual != [(("arm",), 3)]:
            wrong.append((note, actual))
    assert wrong == []


def test_each_row_a_shared_note_names_is_its_own_restatement():
    note = "drill rod: turn the head Ø10 x 3 and the screw Ø6.4 x 13.5"
    row = rows(jig(rod("head", 10, 3, note), rod("screw", 6.35, 13.45, note)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 2)
    assert "head Ø10 × 3" in row.sentence and "screw Ø6.4 × 13.5" in row.sentence


@pytest.mark.parametrize("right", [{"size_mm": [10, 20, 40]}, {"verify": True}])
def test_every_row_a_shared_label_names_is_restated_none_discharges_another(right):
    # Two rows labelled pad: a sibling the note agrees with must not hide the other's
    # different (or withheld) size.
    note = "Mill the pad to 10 x 20 x 30"
    left = block("left", [10, 20, 30], note, label="pad")
    data = jig(left, {**block("right", [10, 20, 30], note, label="pad"), **right})
    row = rows(data)["S1"]
    other = "pad 10 × 20 × 40" if "size_mm" in right else "pad ?"
    assert (row.status, row.numbers["claims"]) == ("error", 2)
    assert "pad 10 × 20 × 30" in row.sentence and other in row.sentence


def test_each_withheld_row_a_shared_label_names_is_its_own_finding():
    note = "Mill the pad to 10 x 20 x 30"
    pads = [block(name, [10, 20, 30], note, label="pad", verify=True) for name in ("left", "right")]
    row = rows(jig(*pads))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 2)
    assert len(set(row.numbers["contradictions"])) == 2


def test_only_the_named_row_s_size_is_read_beside_other_sizes():
    note = "Saw the raw stock to 70 x 15 x 12; finish mill the arm to 65.2 x 11 x 10"
    row = rows(jig(block("arm", [65.2, 11, 10], note)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 1)
    assert "65.2 x 11 x 10" in row.sentence and "70 x 15 x 12" not in row.sentence


@pytest.mark.parametrize(
    "note",
    [
        # No made row named: another feature, raw stock, an unnamed size.
        "Mill the pocket to 4 x 5",
        "Mill the pocket to 4 x 5 (+/- 0.1 mm)",
        "Saw the raw stock to 70 x 15 x 12",
        "1/2 x 3/8 in bar (bought), sawn and milled to 11 x 10 x 65.16",
        "Mill to 65.2 x 11 x 10",
        "turned Ø16 x 9.05 on the lathe",
        # The named row, but not its whole size in the documented form.
        "mill the arm to 11 x 10",
        "mill the arm to 11 x 10 x 65.2 x 2",
        "mill the arm to 7/16 x 3/8 x 2-9/16 in",
        "mill the arm to about 11 x 10 x 65.2",
        "mill the arm, sawn, to 11 x 10 x 65.2",
        "the arm's nose to 11 x 10 x 65.2",
        "the armature to 11 x 10 x 65.2",
        "mill the arm to M6 x 11 x 10, the arm to 6061T6 x 11 x 10",
        "mill the arm to 65.2 x 11 x 10 (approx, 45°)",
    ],
)
def test_a_box_size_not_given_as_the_named_row_s_whole_size_is_not_read(note):
    row = rows(jig(block("arm", [65.2, 11, 10], note)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("not_applicable", 0)


@pytest.mark.parametrize(
    "note",
    [
        "turn the thread end Ø6.30 x 17.5, the body to 6.50 for 14.06, the Ø9 x 3 head",
        "drill 13/32 and counterbore Ø15.9 x 10.5; press the Ø4 x 16 dowels in",
        "turn the thread portion Ø4.80 x 7.2 and the tail to 6.49 x 42 x 3 x 2",
        "chamfer the stud to 0.5 x 45°, then the stud to 0.5 x 45 deg",
        "the stud Ø6.49 x 76.5 x 2 off, the stud to 6.49-6.50 x 76.5",
        "turn the stud to 6.49 x 76.5 x 3, the stud to Ø6.49",
        "Drill Ø4 x 8 deep in the stud",
        "Drill and tap the stud to Ø4 x 8 deep",
        "spot-drill, then drill the stud Ø4 x 8 and counterbore the stud Ø6 x 3",
        "Drill a hole in the stud to Ø4 x 8 deep",
        # A clause with no verb of its own reads in its sentence's, a parenthesis that
        # closes ends no clause, and a fraction anywhere in the clause makes it no size.
        "Drill, with care, the stud to Ø4 x 8 deep",
        "Drill (use a sharp bit; lubricate well) the stud to Ø4 x 8 deep",
        "Turn from ½ in rod the stud to Ø6.49 x 76.5",
    ],
)
def test_a_cylinder_size_not_given_as_the_named_row_s_whole_size_is_not_read(note):
    row = rows(jig(rod("stud", 6.49, 76.5, note)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("not_applicable", 0)


@pytest.mark.parametrize(
    "note",
    [
        "turn from drill rod the stud Ø10 x 50",
        "drill rod the stud Ø10 x 50",
        "tap stock the stud 10 x 50",
    ],
)
def test_a_feature_word_naming_a_tool_or_stock_governs_no_size(note):
    row = rows(jig(rod("stud", 10, 50, note)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("error", 1)


def test_a_bought_or_existing_part_s_note_restates_no_printed_size():
    bought = block("stop", [10, 10, 10], "grind the stop to 10 x 10 x 10", supply="bought")
    existing = block("jaw", [80, 10, 30], "mill the jaw to 80 x 10 x 30", supply="existing")
    assert rows(jig(bought, existing))["S1"].numbers["claims"] == 0


def test_the_restatement_quotes_the_table_s_own_size_cell():
    # Made to 2 places the arm prints 65.16: the finding quotes the cell the table prints.
    data = jig(block("arm", [65.1631, 11, 10], ARM.format("11 x 10 x 65.16")), decimals=2)
    assert "65.16 × 11 × 10" in rows(data)["S1"].sentence
    traveler = _Traveler(data, [], {}, None)
    traveler.setup = data.plan["setups"][0]
    table = unescape(re.sub(r"<[^>]+>", "", traveler.shop_made_tables(traveler.setup)))
    assert "65.16 × 11 × 10" in table and "11 x 10 x 65.16" in table


# ------------------------------------------------------------ picture cut vs CLEARANCE
COLLAR = "clamp 2 pin:collar"


def pictured(cut, *clearances, resolution=None):
    """S1's setup picture dimensioning ``cut`` (``(mm, tag)``, ``(mm, tag, named)`` with
    ``named`` the kernel's op fields, or None) above the CLEARANCE table's per-op
    ``clearances`` (``(op, mm, tag)``), on a mill of DRO ``resolution``."""
    scene = {
        "closest_cut": None if cut is None else {"mm": cut[0], "tag": cut[1], **dict(*cut[2:])},
        "cut_clearances": [{"op": op, "mm": mm, "tag": tag} for op, mm, tag in clearances],
    }
    data = bundle([{}], {"status": "ok", "setups": {"S1": {"render_scene": scene}}})
    if resolution is None:
        return data
    mill = {"kind": "mill", "resolution_mm": resolution}
    return replace(data, inventory={**INVENTORY, "machines": {"mill": mill}})


def test_a_picture_cut_the_clearance_table_gives_otherwise_is_an_error():
    # Rocker RK-B6: the S4 picture's 1.568 against op 27's own cut beside the same collar.
    data = pictured(
        (1.5684, COLLAR, {"op": "27"}), ("25", 4.79372, COLLAR), ("27", 2.056593, COLLAR)
    )
    found = errors(data)["S1"]
    assert "CUT 1.568 mm" in found and "op 27" in found and "2.057" in found
    assert "collar" in found


@pytest.mark.parametrize(
    ("cut", "op", "resolution"),
    [
        (2.0566, "27", None),  # 2.057 both: the least of the two ops' cuts
        (4.7937, "25", None),  # the other op's, at its printed value
        (2.0612, "27", 0.01),  # 2.06 both on a 0.01 grid
    ],
)
def test_a_picture_cut_printed_as_its_op_s_row_passes(cut, op, resolution):
    data = pictured(
        (cut, COLLAR, {"op": op}),
        ("25", 4.79372, COLLAR),
        ("27", 2.056593, COLLAR),
        resolution=resolution,
    )
    row = rows(data)["S1"]
    assert (row.status, row.numbers["claims"]) == ("pass", 1)


def test_a_half_way_value_prints_one_way_on_both_surfaces():
    # One clearance, 2.8045: the picture and the table both round the written decimal
    # half up (2.805), not the binary float (2.804), so they restate one value.
    row = rows(pictured((2.8045, COLLAR, {"op": "27"}), ("27", 2.8045, COLLAR)))["S1"]
    assert (row.status, row.numbers["claims"]) == ("pass", 1)


def test_a_picture_cut_beside_rows_not_computed_is_unknown():
    row = rows(pictured((2.0566, COLLAR, {"op": "27"}), ("27", "unknown", "unknown")))["S1"]
    assert row.status == "unknown" and "CUT 2.057 mm" in row.sentence


@pytest.mark.parametrize(
    "named",
    [{}, {"op": "unknown"}, {"op": ""}, {"op": None}],
    ids=["absent", "unknown", "empty", "none"],
)
def test_a_picture_cut_naming_no_op_is_unknown_even_beside_a_matching_row(named):
    # Whose cut the picture prints is not known, so which row it restates cannot be
    # checked: a row of the same value beside the same solid does not certify it.
    data = pictured((2.817, "loc2", named), ("27", 2.817, "loc2"), ("40", 3.017, "loc2"))
    row = rows(data)["S1"]
    assert row.status == "unknown" and "names no op" in row.sentence, row.sentence


@pytest.mark.parametrize(
    "data",
    [
        # A saw's cut alone: the table carries no row for it.
        pictured((0.0, "base", {"op": "10", "blade": True})),
        # No cut to dimension.
        pictured(None, ("27", 2.056593, COLLAR)),
    ],
    ids=["blade-alone", "no-picture-cut"],
)
def test_a_picture_cut_with_no_row_to_restate_restates_nothing(data):
    row = rows(data)["S1"]
    assert (row.status, row.numbers["claims"]) == ("not_applicable", 0)


LOC2 = "loc2"


@pytest.mark.parametrize(
    "data",
    [
        # Rocker RK-B6: the picture names op 27, but 2.817 is op 40's (a bench file's) cut.
        pictured((2.817, LOC2, {"op": "27"}), ("27", 3.017, LOC2), ("40", 2.817, LOC2)),
        # Op 27's value, beside another solid than the one the picture names.
        pictured((3.017, LOC2, {"op": "27"}), ("27", 3.017, "loc1"), ("40", 3.017, LOC2)),
    ],
    ids=["another-op-s-value", "another-solid"],
)
def test_a_picture_cut_naming_its_op_must_print_that_op_s_row(data):
    found = errors(data)["S1"]
    assert "CUT" in found and "op 27" in found and "3.017" in found


def test_a_picture_cut_printed_as_its_named_op_s_row_passes():
    data = pictured((2.8171, LOC2, {"op": "40"}), ("27", 3.017, LOC2), ("40", 2.817, LOC2))
    row = rows(data)["S1"]
    assert (row.status, row.numbers["claims"]) == ("pass", 1)


@pytest.mark.parametrize(
    "data",
    [
        # The named op's row is not computed; another op's row matches.
        pictured((2.817, LOC2, {"op": "40"}), ("27", 2.817, LOC2), ("40", "unknown", "unknown")),
        # The named op has no row at all.
        pictured((2.817, LOC2, {"op": "40"}), ("27", 2.817, LOC2)),
    ],
    ids=["row-not-computed", "no-row"],
)
def test_a_picture_cut_whose_named_op_s_row_is_missing_is_unknown(data):
    row = rows(data)["S1"]
    assert row.status == "unknown" and "op 40" in row.sentence


def test_a_saw_blade_s_cut_restates_no_clearance_row():
    # The saw carries no CLEARANCE row: a picture naming its blade restates none of the
    # other ops' rows beside the same solid.
    data = pictured((1.0, LOC2, {"op": "10", "blade": True}), ("20", 3.017, LOC2))
    row = rows(data)["S1"]
    assert (row.status, row.numbers["claims"]) == ("not_applicable", 0)
