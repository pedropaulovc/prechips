"""Lathe op starts, relief plunges and dome roughing as the rules derive them."""

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.inputs import Bundle
from prechips.rules import coordinates, op_chain, zero_recipe


def _setup(ops, setup_id="S3"):
    return {"id": setup_id, "machine": "lathe", "ops": ops}


def _bundle(setups, features):
    data = SimpleNamespace(
        plan={"setups": setups},
        features={"units": "mm", "features": features},
        inventory={"machines": {"lathe": {"kind": "lathe"}}, "tools": {}},
        policy={},
    )
    data.feature_definitions = data.features["features"]
    return data


_DOME = {"kind": "dome", "sphere_radius": 4.11}
_PART = {"op": 10, "do": "cut_to_fit", "feature": "dome", "to_z": 1.75}
_FORM = {
    "op": 20,
    "do": "form_dome",
    "feature": "dome",
    "z_from": 1.75,
    "z_to": 0.25,
    "contour": {"method": "axial_table", "step_mm": 0.1},
}


def _chain(ops):
    rows = op_chain.evaluate(_bundle([_setup(ops)], {"dome": dict(_DOME)}))
    return {row.subject: row for row in rows}["dome"]


def test_a_dome_table_cannot_start_on_a_face_left_only_within_a_band():
    # Parting to Z1.75 accepted anywhere in 1.5..2.0 leaves the apex row in air or the
    # table 0.25 under unfaced stock: the dome's printed start is not a known face.
    row = _chain([{**_PART, "to_z_band": [1.5, 2.0]}, _FORM])
    assert row.status == "error"
    assert row.numbers["banded_starts"] == [
        "S3 op 20 starts at Z 1.75, which op 10 leaves anywhere in 1.5 to 2; "
        "an op must leave that face at a deterministic to_z first"
    ]
    # A band that merely contains the start is the same unknown face.
    shifted = _chain([{**_PART, "to_z": 2.0, "to_z_band": [1.5, 2.0]}, _FORM])
    assert shifted.status == "error"


def test_a_deterministic_facing_after_the_banded_part_off_fixes_the_dome_start():
    banded = {**_PART, "to_z": 2.25, "to_z_band": [2.0, 2.5]}
    face = {"op": 15, "do": "face", "feature": "dome", "to_z": 1.75}
    assert _chain([banded, face, _FORM]).status == "not_applicable"
    # Without the facing op the banded part-off still decides the start.
    assert _chain([banded, {**_FORM, "z_from": 2.25}]).status == "error"
    # An unbanded part-off is itself deterministic.
    assert _chain([_PART, _FORM]).status == "not_applicable"


_IDENTITY = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "nominal",
}


def _lathe(ops, features, tools, units="mm", zero=None):
    """A one-setup lathe bundle in an identity frame (setup Z = model Z, +Z free end)."""
    setup = {
        "id": "S1",
        "machine": "lathe",
        "frame": "T",
        "stock_state": {"od_mm": 10.0, "north_end_z": 20.0, "south_end_z": -5.0},
        "hold": {"fixture": "chuck", "support": "none", "stickout_mm": 20.0},
        "ops": ops,
    }
    if zero is not None:
        setup["zero"] = zero
    return Bundle(
        plan={
            "part": "lathe-review",
            "features": "features.toml",
            "dro": {"controller": "test DRO", "radius_mode": False},
            "stock": {"form": "round_bar", "dia_mm": 10.0, "cite": "test authored blank"},
            "setups": [setup],
        },
        features={
            "part": "lathe-review",
            "units": units,
            "frames": {"model": dict(_IDENTITY), "T": dict(_IDENTITY)},
            "features": features,
        },
        inventory={"machines": {"lathe": {"kind": "lathe"}}, "tools": tools},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


_RELIEF = {
    "kind": "groove",
    "frame": "model",
    "dia": [5.57, 5.83],
    "dia_nominal": 5.7,
    "width": [1.2, 2.8],
}


def _blade(hand="right"):
    return {"kind": "parting_blade", "hand": hand, "nose_radius_mm": 0.1, "blade_width_mm": 1.6}


def _scribe_touch(corner, op=50):
    """A blade Z touch on a scribe (no face normal), its corner authored."""
    touch = {"tool": "blade", "z_face": "scribe", "edge_mm": 0.0, "paper_mm": 0.0}
    return {"tool_touches": [{**touch, "corner": corner, "before_ops": [op]}]}


def _relief(z_from, z_to, corner="chuck_side"):
    op = {
        "op": 50,
        "do": "form_relief",
        "feature": "relief",
        "tool": "blade",
        "z_from": z_from,
        "z_to": z_to,
        "direction": "plunge_radial",
    }
    features, tools = {"relief": dict(_RELIEF)}, {"blade": _blade()}
    bundle = _lathe([op], features, tools, zero=_scribe_touch(corner))
    return coordinates.evaluate(bundle)[0]


def test_a_blade_narrower_than_its_relief_plunges_flush_with_each_wall():
    # The 1.6 blade cuts the 2.0 relief in two plunges whose chuck-side corners (the DRO
    # reading its touch set) sit at Z0 and Z0.4, each to the drawing diameter.
    finding = _relief(0.0, 2.0)
    (plunges,) = finding.numbers["plunges"]
    assert plunges["corner_z_mm"] == pytest.approx([0.0, 0.4])
    assert plunges["groove_z_mm"] == pytest.approx([0.0, 2.0])
    assert plunges["width_mm"] == pytest.approx(2.0)
    assert plunges["diameter_mm"] == 5.7 and plunges["dia_band_mm"] == [5.57, 5.83]
    assert finding.status != "error"
    # Authored from the far wall, the plunges are the same; after a touch that set the
    # tailstock-side corner, the DRO reads that corner instead.
    assert _relief(2.0, 0.0).numbers["plunges"][0]["corner_z_mm"] == pytest.approx([0.0, 0.4])
    far = _relief(0.0, 2.0, corner="tailstock_side").numbers["plunges"][0]
    assert far["corner_z_mm"] == pytest.approx([1.6, 2.0])


def test_blade_plunges_with_no_corner_set_stay_unknown_whatever_the_blade_hand():
    # The corner the DRO reads comes from the Z touch, never the blade's hand: with no
    # touch of the blade the plunges are not placed, and the sheet stops.
    from prechips.sheet import _Traveler

    op = {"op": 50, "do": "form_relief", "feature": "relief", "tool": "blade"}
    op.update(z_from=0.0, z_to=2.0, direction="plunge_radial")
    for hand in ("right", "left"):
        bundle = _lathe([op], {"relief": dict(_RELIEF)}, {"blade": _blade(hand)})
        finding = coordinates.evaluate(bundle)[0]
        (plunges,) = finding.numbers["plunges"]
        assert plunges["reading_corner"] == "unknown"
        assert plunges["corner_z_mm"] == "unknown"
        assert finding.status == "unknown"
        sheet = _Traveler(bundle, [], {}, None)
        setup = sheet.setup = bundle.plan["setups"][0]
        sheet.records[("coordinates", "S1")] = finding.numbers
        [stop] = sheet.relief_plunges(setup, op)
        assert stop.startswith("STOP") and "blade corner unknown" in stop


def test_relief_plunges_wider_than_the_drawing_width_band_are_refused():
    # Plunging at both printed ends of a 0..2 row with the 1.6 blade cuts 0..3.6; a span
    # authored that wide is refused against the 2.8 maximum, and 2.8 itself is accepted.
    wide = _relief(0.0, 3.6)
    assert wide.status == "error"
    assert wide.numbers["plunges"][0]["corner_z_mm"] == pytest.approx([0.0, 1.0, 2.0])
    assert "op 50 plunges leave a groove 3.6 wide, outside the drawing width 1.2 to 2.8" in (
        wide.sentence
    )
    assert _relief(0.0, 2.8).status != "error"
    # A blade wider than the authored span still cuts its own width.
    narrow = _relief(0.0, 1.0).numbers["plunges"][0]
    assert narrow["corner_z_mm"] == [0.0] and narrow["width_mm"] == pytest.approx(1.6)


_DOME = {"kind": "dome", "frame": "model", "height": [0.7, 2.3], "sphere_radius": 4.1102}
_AR = {
    "kind": "turning_tool",
    "hand": "right",
    "nose_radius_mm": 0.4,
    "entering_angle_deg": 93.0,
    "insert_angle_deg": 60.0,
}


def _dome(**extra):
    op = {
        "op": 20,
        "do": "form_dome",
        "feature": "dome",
        "tool": "ar",
        "z_from": 1.75,
        "z_to": 0.25,
        "direction": "apex_to_base",
        "contour": {"method": "axial_table", "step_mm": 0.1},
        **extra,
    }
    bundle = _lathe([op], {"dome": dict(_DOME)}, {"ar": dict(_AR)})
    return coordinates.evaluate(bundle)[0]


def test_a_dome_with_a_rough_allowance_gets_a_stair_that_never_comes_inside_it():
    finding = _dome(rough_allowance_mm=0.2)
    assert finding.status == "pass"
    (stair,) = finding.numbers["stair_tables"]
    (finish,) = finding.numbers["contours"]
    assert (stair["stage"], finish["method"]) == ("rough", "axial_table")
    rows = stair["rows"]
    # One facing row per finish Z below the apex, until the grown sphere passes the Ø6.35
    # base the dome caps.
    assert [round(r["z_mm"], 6) for r in rows] == [
        round(1.75 - 0.1 * i, 6) for i in range(1, len(rows) + 1)
    ]
    assert all(r["x_target_mm"] < 2 * stair["work_radius_mm"] for r in rows)
    assert stair["work_radius_mm"] == pytest.approx(3.1749, abs=1e-3)
    # Every corner (the imaginary-tip reading) is 0.1 (half the diametral allowance) off
    # the sphere, and the stair rises outward from each finish row.
    centre = 1.75 - 4.1102
    by_z = {round(r["z_mm"], 6): r for r in finish["rows"]}
    for row in rows:
        r, z = row["x_target_mm"] / 2, row["z_mm"]
        assert ((r * r + (z - centre) ** 2) ** 0.5) - 4.1102 == pytest.approx(0.1)
        assert row["x_target_mm"] > by_z[round(z, 6)]["x_target_mm"]
    # A rough_* op with the table carries the stair only, never the finished surface.
    rough = _dome(do="rough_dome", rough_allowance_mm=0.2)
    assert rough.numbers["stair_tables"][0]["rows"] == rows
    assert rough.numbers["contours"] == []


def test_a_dome_stair_is_not_assumed_for_an_apex_toward_the_chuck():
    finding = _dome(z_from=0.25, z_to=1.75, rough_allowance_mm=0.2)
    assert "stair_tables" not in finding.numbers
    assert finding.status == "unknown"


_ENGAGE = {"rest": "follow_rest", "start_z_mm": 166.0, "meets": ["dead centre"]}


def _rest_row(monkeypatch, engage_z, declared, units="mm", window=(166.0, 0.2)):
    """Accessibility for a clear turning op whose follow rest, set with the tool at its
    start, would meet the dead centre until the tool passes ``engage_z``."""
    from prechips.rules import accessibility
    from prechips.rules.geometry_common import TURNING, TURNING_HOLDER_KEYS, TURNING_TOOL_KEYS

    rest = {"ref": "follow_rest", "ops": [10], "jaw_lead_mm": 8.0}
    if declared is not None:
        rest["engage_at_z_mm"] = declared
    setup = {"id": "S1", "hold": {"supports": [rest]}}
    op = {"op": 10, "do": "rough_turn", "z_from": window[0], "z_to": window[1]}
    inputs = {key: 1.0 for key in TURNING_TOOL_KEYS + TURNING_HOLDER_KEYS}
    inputs.update(approach=TURNING, feed_z=-1)
    detail = {
        "sample_count": 19,
        "tool_hits": 0,
        "holder_hits": 0,
        "rest_engagement": [{**_ENGAGE, "engage_z_mm": engage_z}],
    }
    contexts = [(setup, op, {}, detail, inputs, [], None)]
    monkeypatch.setattr(accessibility, "op_contexts", lambda *_, **__: iter(contexts))
    [row] = accessibility.evaluate(SimpleNamespace(features={"units": units}))
    return row


def test_a_follow_rest_goes_on_only_once_the_tool_passes_its_declared_clear_z(monkeypatch):
    # Feeding toward the chuck, jaws set at Z152 ride clear of the centre (clear from
    # 155.474); set at Z160 they still meet it; undeclared, nobody knows where to set them.
    assert _rest_row(monkeypatch, 155.474, 152.0).status == "pass"
    late = _rest_row(monkeypatch, 155.474, 160.0)
    assert late.status == "error"
    assert "set at Z160, before Z155.474" in late.sentence
    assert _rest_row(monkeypatch, 155.474, None).status == "unknown"
    # Past the op's end the rest never goes on for the cut it serves.
    assert _rest_row(monkeypatch, 155.474, -5.0).status == "error"
    # With no clear position computed a declaration cannot be checked.
    assert _rest_row(monkeypatch, "unknown", 152.0).status == "unknown"
    assert (
        _rest_row(monkeypatch, 155.474, 152.0).numbers["rest_engagement"][0]["declared_z_mm"]
        == 152.0
    )


@pytest.mark.parametrize(
    ("band", "status", "text"),
    [
        ([1.5, "unknown"], "error", "anywhere in 1.5 to an unknown Z;"),
        (["unknown", "unknown"], "error", "anywhere in an unknown Z to an unknown Z;"),
    ],
)
def test_a_band_with_unknown_ends_still_leaves_its_own_to_z_undetermined(band, status, text):
    row = _chain([{**_PART, "to_z_band": band}, _FORM])
    assert row.status == status
    assert text in row.sentence


def test_whether_a_partly_unknown_band_holds_another_start_is_unknown():
    banded = {**_PART, "to_z": 2.25, "to_z_band": [2.0, "unknown"]}
    row = _chain([banded, _FORM])
    assert row.status == "unknown"
    assert row.numbers["unknown_starts"] == [
        "S3 op 20 starts at Z 1.75, which op 10 leaves anywhere in 2 to an unknown Z, "
        "which may hold it"
    ]


def test_a_dome_window_past_the_sphere_gets_no_stair():
    # Apex Z1.75 to base Z-7 is 8.75 of cap on a 4.11 sphere (8.22 across): no dome
    # caps that base, so neither a finish table nor a rough stair is established.
    impossible = _dome(do="rough_dome", z_to=-7.0, rough_allowance_mm=0.2)
    assert "stair_tables" not in impossible.numbers
    assert impossible.status == "unknown"


def test_an_inch_op_ends_before_a_millimetre_engagement_z_it_never_reaches(monkeypatch):
    # Z3.0 to Z1.0 in inches runs 76.2 to 25.4 mm; jaws set at 20 mm never go on in it.
    late = _rest_row(monkeypatch, 45.0, 20.0, units="in", window=(3.0, 1.0))
    assert late.status == "error"
    assert "after the op ends at Z25.4 mm" in late.sentence
    assert _rest_row(monkeypatch, 45.0, 30.0, units="in", window=(3.0, 1.0)).status == "pass"


def _sheet(units, resolution_mm, numbers, z_from, z_to):
    from prechips.sheet import _Traveler

    op = {"op": 10, "do": "rough_turn", "z_from": z_from, "z_to": z_to}
    bundle = _lathe([op], {}, {}, units=units)
    bundle.inventory["machines"]["lathe"]["resolution_mm"] = resolution_mm
    setup = bundle.plan["setups"][0]
    sheet = _Traveler(bundle, [], {}, None)
    sheet.setup = setup
    sheet.records[("accessibility", "S1:10")] = numbers
    return sheet, setup, op


def test_millimetre_start_and_engagement_facts_print_in_inch_dro_coordinates():
    start = {
        "end": "z_from",
        "z_mm": 50.8,
        "clearance_mm": 1.27,
        "max_start_z_mm": 52.07,
        "nearest_fixture": "dead centre",
    }
    engage = {"declared_z_mm": 50.8, "engage_z_mm": 52.0}
    numbers = {"window_poses": [start], "rest_engagement": [engage], "feed_z": -1}
    sheet, setup, op = _sheet("in", 0.0254, numbers, 2.0, 0.5)
    assert sheet.posed_start(setup, op) == (
        "START Z 2.000: 0.050 CLEAR OF dead centre — start no further out than Z 2.050"
    )
    assert sheet.rest_engagement(setup, op) == [
        "set the follow rest at Z 2.000 once the tool passes it"
    ]


def test_a_follow_rest_z_is_printed_on_the_clear_side_of_the_dro_grid():
    # Clear from Z155.47 toward the chuck; declared 155.46 passes, but ordinary rounding
    # to the 0.1 grid prints 155.5, where the jaws still meet the centre.
    engage = {"declared_z_mm": 155.46, "engage_z_mm": 155.47}
    sheet, setup, op = _sheet("mm", 0.1, {"rest_engagement": [engage], "feed_z": -1}, 166.0, 0.2)
    assert sheet.rest_engagement(setup, op) == [
        "set the follow rest at Z 155.4 once the tool passes it"
    ]
    # Feeding away from the chuck the clear side is up the grid.
    sheet, setup, op = _sheet(
        "mm",
        0.1,
        {"rest_engagement": [{"declared_z_mm": 10.04, "engage_z_mm": 10.03}], "feed_z": 1},
        0.0,
        50.0,
    )
    assert sheet.rest_engagement(setup, op) == [
        "set the follow rest at Z 10.1 once the tool passes it"
    ]
    # No grid position between the clear Z and the op's end is refused, not rounded in.
    sheet, setup, op = _sheet(
        "mm",
        0.1,
        {"rest_engagement": [{"declared_z_mm": 0.25, "engage_z_mm": 0.26}], "feed_z": -1},
        166.0,
        0.22,
    )
    [line] = sheet.rest_engagement(setup, op)
    assert line.startswith("STOP")


def test_an_inch_relief_is_plunged_in_millimetres_and_printed_in_inches():
    # The same 2.0 mm relief drawn in inches: the 1.6 mm blade still needs two plunges.
    inch = 25.4
    relief = {
        **_RELIEF,
        "dia": [5.57 / inch, 5.83 / inch],
        "dia_nominal": 5.7 / inch,
        "width": [1.2 / inch, 2.8 / inch],
    }
    op = {
        "op": 50,
        "do": "form_relief",
        "feature": "relief",
        "tool": "blade",
        "z_from": 0.0,
        "z_to": 2.0 / inch,
        "direction": "plunge_radial",
    }
    zero = _scribe_touch("chuck_side")
    bundle = _lathe([op], {"relief": relief}, {"blade": _blade()}, units="in", zero=zero)
    finding = coordinates.evaluate(bundle)[0]
    (plunges,) = finding.numbers["plunges"]
    assert plunges["corner_z_mm"] == pytest.approx([0.0, 0.4])
    assert plunges["width_mm"] == pytest.approx(2.0)
    assert finding.status != "error"
    from prechips.sheet import _Traveler

    sheet = _Traveler(bundle, [], {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    sheet.records[("coordinates", "S1")] = finding.numbers
    printed = sheet.relief_plunges(setup, op)
    assert printed[:2] == [
        "plunge 1 chuck-side corner Z 0.000",
        "plunge 2 chuck-side corner Z 0.016",
    ]
    assert printed[3] == "groove Z 0.000 to 0.079"


def test_an_inch_dome_stair_keeps_half_the_millimetre_allowance_off_the_sphere():
    inch = 25.4
    op = {
        "op": 20,
        "do": "rough_dome",
        "feature": "dome",
        "tool": "ar",
        "z_from": 1.75 / inch,
        "z_to": 0.25 / inch,
        "direction": "apex_to_base",
        "contour": {"method": "axial_table", "step_mm": 0.1 / inch},
        "rough_allowance_mm": 0.2,
    }
    dome = {**_DOME, "sphere_radius": 4.1102 / inch, "height": [0.7 / inch, 2.3 / inch]}
    bundle = _lathe([op], {"dome": dome}, {"ar": dict(_AR)}, units="in")
    (stair,) = coordinates.evaluate(bundle)[0].numbers["stair_tables"]
    centre = (1.75 - 4.1102) / inch
    assert stair["rows"]
    for row in stair["rows"]:
        r, z = row["x_target_mm"] / 2, row["z_mm"]
        off = (r * r + (z - centre) ** 2) ** 0.5 - 4.1102 / inch
        assert off == pytest.approx(0.1 / inch)


def _start(z_mm, clearance, max_start, feed=None):
    pose = {
        "end": "z_from",
        "z_mm": z_mm,
        "clearance_mm": clearance,
        "max_start_z_mm": max_start,
        "nearest_fixture": "dead centre",
    }
    numbers = {"window_poses": [pose]} | ({"feed_z": feed} if feed else {})
    sheet, setup, op = _sheet("mm", 0.1, numbers, z_mm, 10.0)
    return sheet.posed_start(setup, op)


def test_a_start_rounded_out_past_its_checked_limit_is_refused():
    # Checked at Z50.04 with 0.02 clear and a limit of 50.06, the start prints at Z50.1 on
    # the 0.1 grid, past the limit: refused, never printed with a borrowed clearance.
    refused = _start(50.04, 0.02, 50.06)
    assert refused.startswith("STOP: START Z 50.1 is not checked clear of dead centre")
    assert refused == _start(50.04, 0.02, 50.06, feed=-1)
    # With room, the printed start keeps the clearance less its outward rounding (0.25 -
    # 0.06 = 0.19, printed down to 0.1) and the limit stays rounded in.
    assert _start(50.04, 0.25, 50.81, feed=-1) == (
        "START Z 50.1: 0.1 CLEAR OF dead centre — start no further out than Z 50.8"
    )


def test_an_unknown_later_band_does_not_hide_a_known_band_holding_the_start():
    # Op 12's band may or may not hold Z1.75; either way the start is banded (op 12's
    # band, else op 10's 1.5..2).
    later = {**_PART, "op": 12, "to_z": 2.25, "to_z_band": [2.0, "unknown"]}
    row = _chain([{**_PART, "to_z_band": [1.5, 2.0]}, later, _FORM])
    assert row.status == "error"
    assert "which op 10 leaves anywhere in 1.5 to 2;" in row.sentence


_FACE_TOUCH = {"tool": "blade", "z_face": "shoulder", "edge_mm": 0.0, "paper_mm": 0.0}


def _parted(touch, ends, side, to_z=-5.0, face="shoulder"):
    """A blade parting to ``to_z`` after its Z ``touch``; a synthetic kernel gives the
    touched ``face`` its ``end_faces`` and the op its ``faced_side`` (None: no fact)."""
    op = {"op": 40, "do": "part_off", "tool": "blade", "to_z": to_z}
    zero = {"tool_touches": [{**touch, "before_ops": [40]}]}
    bundle = _lathe([op], {}, {"blade": _blade()}, zero=zero)
    bundle.inventory["machines"]["lathe"]["resolution_mm"] = 0.01
    facts = {} if side is None else {"faced_side": side}
    kernel = {
        "status": "ok",
        "setups": {"S1": {"revolved": {face: {"end_faces": ends}}}},
        "ops": {"S1:40": facts},
    }
    return dataclasses.replace(bundle, kernel=kernel)


def _blade_entry(bundle):
    [finding] = coordinates.evaluate(bundle)
    [entry] = [e for e in finding.numbers["operations"] if e["op"] == 40]
    return finding, entry


@pytest.mark.parametrize(
    ("ends", "edge", "corner"),
    [
        # A face toward the free end is met by the chuck-side corner, one toward the
        # chuck by the tailstock-side corner; no measured normal gives no corner.
        ([{"z_mm": 0.0, "normal_z": 1}], 0.0, "chuck_side"),
        ([{"z_mm": 0.0, "normal_z": -1}], 0.0, "tailstock_side"),
        ([], 0.0, "unknown"),
        # A feature with end faces both ways (a boss's two ends): the one at the touch Z.
        ([{"z_mm": -72.0344, "normal_z": -1}, {"z_mm": 0.0, "normal_z": 1}], 0.0, "chuck_side"),
        (
            [{"z_mm": -72.0344, "normal_z": -1}, {"z_mm": 0.0, "normal_z": 1}],
            -72.0344,
            "tailstock_side",
        ),
        # A touch Z on none of them: only end faces that all agree give a corner.
        ([{"z_mm": 0.0, "normal_z": 1}, {"z_mm": -3.0, "normal_z": 1}], 0.5, "chuck_side"),
        (
            [{"z_mm": -72.0344, "normal_z": -1}, {"z_mm": 0.0, "normal_z": 1}],
            0.5,
            "unknown",
        ),
    ],
)
def test_a_blade_z_touch_sets_the_corner_its_face_normal_gives(ends, edge, corner):
    bundle = _parted({**_FACE_TOUCH, "edge_mm": edge}, ends, -1)
    [zero] = zero_recipe.evaluate(bundle)
    [touch] = zero.numbers["tool_touches"]
    assert touch["reference_corner"] == corner
    assert zero.status != "error"
    finding, entry = _blade_entry(bundle)
    assert entry["blade"]["reading_corner"] == corner
    if corner == "unknown":
        # Its op Z stays unknown (exit 4), never a guessed corner.
        assert entry["blade"]["corner_dro_z"] == "unknown"
        assert finding.status == "unknown"


@pytest.mark.parametrize(
    ("normal", "side", "expected"),
    [
        # The tailstock-side corner forms a face toward the chuck: the chuck-side corner
        # the DRO reads stands a blade width (1.6) beyond it.
        (1, -1, -6.6),
        (1, 1, -5.0),
        (-1, -1, -5.0),
        # The chuck-side corner forms a face toward the free end: the tailstock-side
        # corner the DRO reads stands a blade width above it.
        (-1, 1, -3.4),
    ],
)
def test_a_blade_op_z_is_the_reading_of_the_corner_its_touch_set(normal, side, expected):
    bundle = _parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": normal}], side)
    finding, entry = _blade_entry(bundle)
    assert entry["blade"]["corner_dro_z"] == pytest.approx(expected)
    # The face the op leaves is unchanged; only the reading moves.
    assert entry["dro_to_z"] == pytest.approx(-5.0)
    assert finding.status != "error"


def test_a_blade_op_with_no_kernel_side_for_its_face_stays_unknown():
    finding, entry = _blade_entry(_parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": 1}], None))
    assert entry["blade"]["forming_corner"] == "unknown"
    assert entry["blade"]["corner_dro_z"] == "unknown"
    assert finding.status == "unknown"


@pytest.mark.parametrize(
    "touch",
    [
        {**_FACE_TOUCH, "corner": "tailstock_side"},
        {**_FACE_TOUCH, "method": "feed the tailstock-side corner in until it drags"},
        {**_FACE_TOUCH, "corner": "chuck_side", "method": "the tailstock-side corner"},
    ],
)
def test_a_blade_touch_naming_a_corner_its_face_cannot_give_is_an_error(touch):
    bundle = _parted(touch, [{"z_mm": 0.0, "normal_z": 1}], -1)
    [zero] = zero_recipe.evaluate(bundle)
    assert zero.status == "error"
    [row] = zero.numbers["tool_touches"]
    assert row["reference_corner"] == "unknown" and row["corner_error"]
    # Never re-read to fit: the op's Z stays unknown.
    assert _blade_entry(bundle)[1]["blade"]["corner_dro_z"] == "unknown"


def test_an_authored_corner_the_face_agrees_with_is_not_an_error():
    touch = {**_FACE_TOUCH, "corner": "chuck_side", "method": "feed the chuck-side corner in"}
    [zero] = zero_recipe.evaluate(_parted(touch, [{"z_mm": 0.0, "normal_z": 1}], -1))
    assert zero.status != "error"
    assert zero.numbers["tool_touches"][0]["corner_from"] == "face normal"


def test_a_sleeve_parted_after_a_touch_on_its_far_end_comes_out_full_length():
    # The cone's S2: the 1.6 blade touched on the +Z north face at Z21.0055 (no paper)
    # reads its chuck-side corner; op 40 parts the -Z south face at Z-21.0505. Printing
    # Z-21.05 put that corner on the line and left the sleeve a blade width short of its
    # 42.04..42.08 hold; the corner goes to -22.65.
    from prechips.sheet import _Traveler

    touch = {"tool": "blade", "z_face": "north", "edge_mm": 21.0055, "paper_mm": 0.0}
    bundle = _parted(touch, [{"z_mm": 21.0055, "normal_z": 1}], -1, -21.0505, "north")
    [zero] = zero_recipe.evaluate(bundle)
    finding, entry = _blade_entry(bundle)
    corner = entry["blade"]["corner_dro_z"]
    assert corner == pytest.approx(-22.65)
    [touched] = zero.numbers["tool_touches"]
    sleeve = touched["z_axis_set"] - (corner + 1.6)
    assert 42.04 <= sleeve <= 42.08
    sheet = _Traveler(bundle, [], {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    sheet.records[("zero_check", "S1")] = zero.numbers
    sheet.records[("coordinates", "S1")] = finding.numbers
    assert sheet.z_target(setup, bundle.plan["setups"][0]["ops"][0]) == (
        "Z → -22.65 (chuck-side corner)"
    )
    text = sheet.dro(setup, {"blade": "T3 blade"})
    assert "Z — chuck-side corner on the north" in text
    assert "Z now reads the chuck-side corner" in text


def test_each_toolpost_tool_is_set_on_centre_before_its_first_touch_off():
    from prechips.sheet import _Traveler

    ops = [
        {"op": 10, "do": "rough_turn", "feature": "body", "tool": "turner"},
        {"op": 40, "do": "part_off", "tool": "blade", "to_z": -5.0},
        {"op": 60, "do": "part_off", "tool": "blade", "to_z": -9.0},
    ]
    zero = {
        "x": {"feature": "spindle_axis", "method": "trial_cut_measure", "tool": "turner"},
        "z": {"face": "end", "edge_mm": 0.0, "method": "touch", "tool": "turner"},
        "tool_touches": [
            {**_FACE_TOUCH, "corner": "chuck_side", "before_ops": [40]},
            {**_FACE_TOUCH, "corner": "chuck_side", "before_ops": [60]},
        ],
    }
    tools = {"blade": _blade(), "turner": dict(_AR)}
    bundle = _lathe(ops, {}, tools, zero=zero)
    [finding] = zero_recipe.evaluate(bundle)
    # One step per tool, at its first touch-off; only the blade is squared.
    assert finding.numbers["tool_setting"] == [
        {
            "touch": "zero",
            "axis": "x",
            "tool": "turner",
            "centre_height": zero_recipe.CENTRE_HEIGHT,
            "square_blade": "not_applicable",
        },
        {
            "touch": "tool_touches",
            "index": 0,
            "tool": "blade",
            "centre_height": zero_recipe.CENTRE_HEIGHT,
            "square_blade": zero_recipe.SQUARE_BLADE,
        },
    ]
    # The toolpost's own words say how, and the sheet prints each step before its touch.
    bundle.inventory["machines"]["lathe"]["toolpost"] = {
        "centre_height": "shim it level with the tailstock point",
        "square_blade": "square it off the chuck face",
    }
    [finding] = zero_recipe.evaluate(bundle)
    sheet = _Traveler(bundle, [], {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    sheet.records[("zero_check", "S1")] = finding.numbers
    text = sheet.dro(setup, {"blade": "T3 blade", "turner": "T1 turner"})
    blade = "Before touching off T3 blade: shim it level with the tailstock point; then square"
    assert text.count(blade) == 1
    assert text.index(blade) < text.index("Before op 40, touch off T3 blade")
    turner = "Before touching off T1 turner: shim it level with the tailstock point."
    assert text.index(turner) < text.index("<table")
