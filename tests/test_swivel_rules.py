"""A vise swivelled about Z (#300): how the swivel is set, the tolerance that setting
holds, the bands it widens, and the HOLD steps the traveler prints for it."""

import math
import re

import pytest
from test_hold_align import ALIGN, hold_text
from test_hold_align import bundle as square_bundle
from test_hold_align import setup as square_setup
from test_sheet_ops import Markup, content

from prechips import kernel
from prechips.inputs import Bundle
from prechips.rules import headroom, hold_fields, swivel, zero_recipe
from prechips.sheet import _Traveler

MEASURED = {
    "status": "measured",
    "by": "test value",
    "date": "2026-10-17",
    "instrument": "test fixture",
}
STEP = 0.005
INDICATE = {**ALIGN, "method": "indicate_jaw", "limit_mm": 0.02, "over_mm": 100.0}
GRADUATIONS = {"method": "graduations", "tolerance_deg": 0.5, "cite": "vise maker's manual p3"}
ANGLE = -43.77


def setup(sid="V1", angle=ANGLE, align=INDICATE, ops=None, **hold):
    hold = {
        "fixture": "vise",
        "jaws_along": "x",
        "fixed_jaw": "rear",
        "jaws_angle_deg": angle,
        "stop": "none",
        "grip_mm": 10.0,
        "clamp": "tighten",
        **hold,
    }
    if angle is None:
        del hold["jaws_angle_deg"]
    if align is not None:
        hold["align"] = align
    return {
        "id": sid,
        "machine": "mill",
        "hold": hold,
        "coolant": "none",
        "deburr_mm": 0.2,
        "stock_state": {"top_z": 0.0, "bottom_z": -10.0},
        "ops": ops or [],
    }


def taper(op=10, do="side_mill", feature="taper"):
    """A side-milled edge op, its sweep bounded so its reach from the zero is known."""
    return {
        "op": op,
        "do": do,
        "feature": feature,
        "tool": "em",
        "holder": "collet",
        "direction": "climb",
        "stock_removal_bounds": {"x": [0.0, 30.0], "y": [-40.0, 0.0]},
    }


def bundle(*setups, resolution=STEP, band=1.0, general=None):
    machine = {"kind": "mill"}
    if resolution is not None:
        machine["resolution_mm"] = {"value": resolution, "measured": MEASURED}
    feature = {"kind": "face", "requirements": []}
    if band is not None:
        feature["angle_tol_deg"] = band
    features = {"units": "mm", "features": {"taper": feature}}
    if general is not None:
        features["general_tolerances"] = {"angular_deg": general}
    return Bundle(
        plan={"setups": list(setups)},
        features=features,
        inventory={
            "machines": {"mill": machine, "lathe": {"kind": "lathe"}},
            "fixtures": {
                "vise": {"kind": "vise", "name": "6 in vise"},
                "chuck": {"kind": "three_jaw_chuck", "name": "3-jaw chuck"},
            },
            "gauges": {"dti": {"kind": "dial_test_indicator", "name": "0.0005 in test indicator"}},
            "tools": {"em": {"kind": "endmill", "dia_mm": 6.0}},
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=None,
        kernel={},
    )


def derived(limit=0.02, over=100.0, step=STEP):
    return math.degrees(math.asin((limit + math.sqrt(2) * step) / over))


# ---------------------------------------------------------------- setting tolerance


def test_indicating_the_jaw_derives_the_tolerance_from_limit_move_and_dro_step():
    data = bundle(setup())
    set_by = swivel.setting(data, data.plan["setups"][0])
    assert set_by["method"] == "indicate_jaw" and set_by["unresolved"] == []
    assert set_by["line_deg"] == ANGLE
    assert set_by["tolerance_deg"] == pytest.approx(derived())


@pytest.mark.parametrize(
    ("change", "debt"),
    [
        ({"resolution": None}, "DRO resolution"),
        ({"align": {**INDICATE, "limit_mm": "unknown"}}, "align.limit_mm"),
        ({"align": {**INDICATE, "over_mm": "unknown"}}, "align.over_mm"),
        ({"align": {k: v for k, v in INDICATE.items() if k != "method"}}, "align.method"),
        ({"angle": "unknown"}, "jaws_angle_deg"),
        ({"align": {**GRADUATIONS, "tolerance_deg": "unknown"}}, "align.tolerance_deg"),
        ({"align": {k: v for k, v in GRADUATIONS.items() if k != "cite"}}, "align.cite"),
    ],
)
def test_an_unknown_setting_input_leaves_the_tolerance_unknown(change, debt):
    resolution = change.pop("resolution", STEP)
    data = bundle(setup(**change), resolution=resolution)
    set_by = swivel.setting(data, data.plan["setups"][0])
    assert set_by["tolerance_deg"] == "unknown"
    assert any(debt in item for item in set_by["unresolved"]), set_by["unresolved"]


def test_a_stated_method_carries_its_cited_tolerance():
    data = bundle(setup(align=GRADUATIONS))
    set_by = swivel.setting(data, data.plan["setups"][0])
    assert set_by["tolerance_deg"] == 0.5 and GRADUATIONS["cite"] in set_by["cite"]


# ---------------------------------------------------------------- band check


@pytest.mark.parametrize(
    ("band", "align", "status"),
    [
        (1.0, INDICATE, "pass"),
        (0.01, INDICATE, "error"),  # tighter than the derived ±0.0196°
        (1.0, GRADUATIONS, "pass"),
        (0.25, GRADUATIONS, "error"),  # graduations alone cannot hold ±0.25°
        (None, INDICATE, "unknown"),  # no band: general angular tolerance absent
    ],
)
def test_the_setting_tolerance_is_held_against_each_cut_edges_angle_band(band, align, status):
    data = bundle(setup(align=align, ops=[taper()]), band=band)
    (row,) = swivel.evaluate(data)
    assert row.status == status, row.sentence
    (cut,) = row.numbers["cuts"]
    assert cut["cut"] == "edge"
    reach = math.hypot(30.0, 40.0)
    assert cut["reach_mm"] == pytest.approx(reach)
    assert cut["shift_mm"] == pytest.approx(
        reach * math.sin(math.radians(row.numbers["tolerance_deg"]))
    )


def test_a_band_falls_back_to_the_title_block_angular_tolerance():
    data = bundle(setup(ops=[taper()]), band=None, general=0.5)
    (row,) = swivel.evaluate(data)
    assert row.status == "pass"
    assert row.numbers["cuts"][0]["band_source"] == "features.general_tolerances.angular_deg"


def test_an_unknown_tolerance_is_never_a_pass():
    data = bundle(setup(ops=[taper()]), resolution=None)
    (row,) = swivel.evaluate(data)
    assert row.status == "unknown" and row.numbers["tolerance_deg"] == "unknown"


def test_facing_and_holes_carry_no_angle_band_and_square_vises_no_finding():
    ops = [taper(do="finish_face", op=10), taper(do="drill", op=20)]
    (row,) = swivel.evaluate(bundle(setup(ops=ops), band=None))
    assert row.status == "pass" and [c["cut"] for c in row.numbers["cuts"]] == ["point"]
    assert swivel.evaluate(bundle(setup(angle=None, align=ALIGN))) == []


def _accepted_errors(line, limit, over, step):
    """Every jaw-angle error (degrees) an operator following the printed indicate_jaw step
    accepts: the jaw truly at ``line + e``, the table set to the printed move within a DRO
    step on each axis, the indicator reading at P2 within ``limit`` of P1."""
    accepted = []
    for e in (i * 1e-4 for i in range(-1000, 1001)):
        a = math.radians(line + e)
        normal = (-math.sin(a), math.cos(a))
        target = (over * math.cos(math.radians(line)), over * math.sin(math.radians(line)))
        for ex in (-step, 0.0, step):
            for ey in (-step, 0.0, step):
                reading = normal[0] * (target[0] + ex) + normal[1] * (target[1] + ey)
                if abs(reading) <= limit:
                    accepted.append(e)
    return accepted


@pytest.mark.parametrize("angle", [ANGLE, 30.0, 0.5])
@pytest.mark.parametrize("band", [0.05, 0.02, 0.019, 0.01])
def test_an_operator_at_the_edge_of_the_setting_keeps_the_cut_in_band_or_gets_a_stop(angle, band):
    """Operator perturbation: the swivel set by the printed step as badly as it accepts
    (the DRO a step off on each axis, the reading at its limit) lands within the derived
    tolerance; the cut's edge is then off by that error, so a passing finding means the
    edge stays inside its band, and an edge the error could leave says so (error or ?)."""
    data = bundle(setup(angle=angle, ops=[taper()]), band=band)
    (row,) = swivel.evaluate(data)
    tolerance = row.numbers["tolerance_deg"]
    worst = max(map(abs, _accepted_errors(angle, 0.02, 100.0, STEP)))
    assert worst <= tolerance
    if row.status == "pass":
        assert worst <= band
    else:
        assert row.status in ("error", "unknown")
    assert (row.status == "pass") is (tolerance <= band)


# ---------------------------------------------------------------- hold fields


def test_a_changed_swivel_sets_the_vise_again_and_an_unchanged_one_does_not():
    data = bundle(
        setup("V1"),
        setup("V2", align=None),  # same swivel: the vise stays set
        setup("V3", angle=30.0),
        setup("V4", angle=None, align=ALIGN),  # back to square jaws
    )
    assert hold_fields.align_due(data) == {
        "V1": "mounted",
        "V3": "jaws swivelled",
        "V4": "jaws swivelled",
    }


def test_a_swivelled_vise_is_set_by_its_method_not_squared_along_a_travel():
    (row,) = hold_fields.evaluate(bundle(setup()))
    assert row.status == "pass", row.sentence
    assert "hold.align.travel" not in row.numbers["missing"]
    (row,) = hold_fields.evaluate(bundle(setup(align={**GRADUATIONS, "cite": "unknown"})))
    assert row.status == "unknown" and row.numbers["missing"] == ["hold.align.cite"]


@pytest.mark.parametrize(
    ("hold", "message"),
    [
        ({"fixture": "chuck"}, "swivels a vise"),
        ({"angle": None, "align": INDICATE}, "sets a swivel"),
    ],
)
def test_a_swivel_on_anything_but_a_vise_or_a_method_without_one_is_an_error(hold, message):
    (row,) = hold_fields.evaluate(bundle(setup(**hold)))
    assert row.status == "error" and message in row.sentence


# ---------------------------------------------------------------- headroom


def test_headroom_reads_the_jaw_faces_in_the_jaw_frame():
    data = bundle(setup())
    data = Bundle(
        **{
            **data.__dict__,
            "kernel": {
                "status": "ok",
                "setups": {
                    "V1": {
                        "stock_bbox_mm": [0, -50, 0, 50, 0, 10],
                        "jaw_frame_stock_bbox_mm": [0, 0, 0, 70, 20, 10],
                    }
                },
            },
        }
    )
    plan_setup = data.plan["setups"][0]
    assert headroom._jaw_faces(data, plan_setup) == (1, [0, 20], ANGLE)
    unknown = {**plan_setup, "hold": {**plan_setup["hold"], "jaws_angle_deg": "unknown"}}
    assert headroom._jaw_faces(data, unknown) is None
    # A sweep along the turned jaws, 10 mm inside them, spans the jaw-frame y 10 only.
    line = math.radians(ANGLE)
    op = {"op": 10, "stock_removal_bounds": {}}
    printed = {
        "line_table": [
            {
                "op": 10,
                "dro_xy": [
                    [
                        r * math.cos(line) - 10 * math.sin(line),
                        r * math.sin(line) + 10 * math.cos(line),
                    ]
                    for r in (5.0, 60.0)
                ],
            }
        ]
    }
    assert headroom._span(op, printed, 1, ANGLE) == pytest.approx([10.0, 10.0])
    assert headroom._span(op, printed, 0, ANGLE) == pytest.approx([5.0, 60.0])


# ---------------------------------------------------------------- zero


def test_an_edge_touch_under_a_swivel_does_not_set_x_or_y():
    data = bundle(setup())
    data.plan["setups"][0]["zero"] = {
        "x": {"edge": "left", "edge_mm": 0.0, "from": "-x", "tool": "em", "check_jog_mm": 5},
        "y": {"feature": "bore", "edge_mm": 0.0, "from": "indicated", "tool": "dti"},
    }
    (row,) = zero_recipe.evaluate(data)
    assert row.status != "pass" and row.numbers["swivel_unproven_axes"] == ["X"]
    assert "indicating a bore" in row.sentence


# ---------------------------------------------------------------- traveler


def test_the_hold_prints_the_swivel_and_the_indicated_setting_step():
    data = bundle(setup(), setup("V2", align=None))
    text = hold_text(data, "V1")
    assert "swivelled 43.77° clockwise seen from above" in text
    assert "fixed jaw runs 43.77° clockwise from the X travel" in text
    dx, dy = (100.0 * f(math.radians(ANGLE)) for f in (math.cos, math.sin))
    assert f"X {dx:.3f}, Y {dy:.3f} mm" in text
    assert "zero DRO X and Y there" in text and "work's zero is picked up below" in text
    assert "0.02 mm" in text and f"±{derived():.2g}°" in text
    assert "Swivel" not in hold_text(data, "V2")


def test_a_stated_method_prints_its_reference_and_tolerance():
    text = hold_text(bundle(setup(align=GRADUATIONS)), "V1")
    assert "base's graduations" in text and "±0.5°" in text


# One test per printed field: each unknown prints a STOP naming it, never a runnable step.
@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"angle": "unknown"}, "the swivel angle"),
        ({"align": {k: v for k, v in INDICATE.items() if k != "method"}}, "the setting method"),
        ({"align": {**INDICATE, "indicator": "unknown"}}, "the indicator"),
        ({"align": {**INDICATE, "over_mm": "unknown"}}, "the DRO move"),
        ({"align": {**INDICATE, "limit_mm": "unknown"}}, "the limit"),
        ({"resolution": None}, "the setting tolerance"),
        ({"align": {**GRADUATIONS, "tolerance_deg": "unknown"}}, "the setting tolerance"),
        ({"align": {**GRADUATIONS, "cite": "unknown"}}, "the setting tolerance"),
    ],
)
def test_each_unknown_printed_swivel_field_is_a_stop(change, field):
    resolution = change.pop("resolution", STEP)
    text = hold_text(bundle(setup(**change), resolution=resolution), "V1")
    assert "STOP: set the vise swivel" in text and field in text and "do not run" in text
    assert not re.search(r"move to X -?\d", text)


def test_square_vises_print_as_before():
    data = square_bundle(square_setup("V1", "vise"))
    assert "Swivel" not in hold_text(data, "V1") and "Square the fixed jaw" in hold_text(data, "V1")


def test_the_zero_section_prints_a_stop_for_an_edge_pick_up_under_a_swivel():
    data = bundle(setup())
    data.plan["setups"][0]["zero"] = {
        "x": {"edge": "left", "edge_mm": 0.0, "from": "-x", "tool": "em", "check_jog_mm": 5},
    }
    sheet = _Traveler(data, zero_recipe.evaluate(data), {}, None)
    text = " ".join(content(node) for node in Markup(sheet.dro(data.plan["setups"][0], {})).nodes)
    assert "STOP: X zero — the vise is swivelled" in text and "indicating a bore" in text
    assert "from -X side" not in text


@pytest.mark.parametrize(
    ("angle", "engine_angle", "placed"),
    [(ANGLE, ANGLE, True), (0.0, None, True), (None, None, True), ("unknown", None, False)],
)
def test_the_kernel_hold_carries_a_known_swivel_and_an_unknown_one_unplaces_the_jaws(
    angle, engine_angle, placed
):
    """A known swivel reaches the engine (and its cache key); none or 0 leaves today's
    square-jaw input byte for byte; a stated-unknown swivel leaves the jaws unplaced."""
    data = bundle(setup(angle=angle))
    hold = kernel._engine_hold(kernel.hold_inputs(data, data.plan["setups"][0]))
    assert hold.get("jaws_angle_deg") == engine_angle
    assert ("jaws_angle_deg" in hold.get("reason", "")) is not placed
