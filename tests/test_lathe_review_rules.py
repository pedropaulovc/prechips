"""Lathe op starts, relief plunges and dome roughing as the rules derive them."""

import dataclasses
import re
from html import unescape
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


@pytest.mark.parametrize(
    ("checks", "z_to", "band", "groove"),
    [
        # Inspected for Ø and plunged over its own Z window: the row's inspection cell
        # and Z window already print both, so the plunge lines add neither.
        ({"dia": "caliper"}, 2.0, False, False),
        # Not inspected for Ø in this op: the band rides with the plunge diameter.
        ({}, 2.0, True, False),
        # A blade wider than the authored span leaves a groove beyond the row's window.
        ({"dia": "caliper"}, 1.0, False, True),
    ],
)
def test_a_relief_row_prints_its_band_and_groove_extent_once(checks, z_to, band, groove):
    from prechips.sheet import _Traveler

    op = {"op": 50, "do": "form_relief", "feature": "relief", "tool": "blade"}
    op.update(z_from=0.0, z_to=z_to, direction="plunge_radial", checks=checks)
    tools = {"blade": _blade()}
    bundle = _lathe([op], {"relief": dict(_RELIEF)}, tools, zero=_scribe_touch("chuck_side"))
    sheet = _Traveler(bundle, [], {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    sheet.records[("coordinates", "S1")] = coordinates.evaluate(bundle)[0].numbers
    printed = sheet.relief_plunges(setup, op)
    assert any(line.startswith("to Ø 5.700") or "each to Ø 5.700" in line for line in printed)
    assert any("(5.57" in line for line in printed) is band, printed
    assert any(line.startswith("groove Z") for line in printed) is groove, printed


@pytest.mark.parametrize(("dia", "radial"), [(6.35, "3.18"), (6.33, "3.17"), (2.25, "1.13")])
def test_a_half_way_travel_rounds_up_on_a_coarser_dro(dia, radial):
    # Parting Ø6.35 to the axis plunges 3.175 radial; a 0.01 DRO prints that 3.18, the
    # same as the hand rounding of half the drawing diameter, never a float's 3.17.
    from prechips.sheet import _Traveler

    op = {"op": 10, "do": "part_off", "feature": "relief", "tool": "blade", "to_z": 0.0}
    bundle = _lathe([op], {"relief": dict(_RELIEF)}, {"blade": _blade()})
    bundle.inventory["machines"]["lathe"]["resolution_mm"] = 0.01
    sheet = _Traveler(bundle, [], {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    sheet.records[("coordinates", "S1")] = {"x_display": "diameter"}
    sheet.records[("reach", "S1:10")] = {"reach_depth_mm": dia / 2}
    (line,) = sheet.plunge_x(setup, op)
    assert line.endswith(f"→ 0.00 ({radial} radial)"), line


_DOME = {"kind": "dome", "frame": "model", "height": [0.7, 2.3], "sphere_radius": 4.1102}
_AR = {
    "kind": "turning_tool",
    "hand": "right",
    "nose_radius_mm": 0.4,
    "entering_angle_deg": 93.0,
    "insert_angle_deg": 60.0,
}


def _dome_bundle(**extra):
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
    return _lathe([op], {"dome": dict(_DOME)}, {"ar": dict(_AR)})


def _dome(**extra):
    return coordinates.evaluate(_dome_bundle(**extra))[0]


def _on_display(bundle, radius_mode):
    """``bundle`` with its lathe DRO X display as ``radius_mode`` (None: not stated)."""
    if radius_mode is None:
        del bundle.plan["dro"]["radius_mode"]
    else:
        bundle.plan["dro"]["radius_mode"] = radius_mode
    return bundle


@pytest.mark.parametrize(
    ("radius_mode", "per_radius"), [(False, 2), (True, 1), ("unknown", None), (None, None)]
)
def test_lathe_x_readings_are_in_the_dro_display_and_unknown_without_one(radius_mode, per_radius):
    bundle = _on_display(_dome_bundle(rough_allowance_mm=0.2), radius_mode)
    # A declared base radius gives the dome's op rows a size to turn to: Ø6.35.
    bundle.features["features"]["dome"]["base_radius"] = 3.175
    [finding] = coordinates.evaluate(bundle)
    turned = [row for row in finding.numbers["rows"] if "x_target_mm" in row]
    (finish,) = finding.numbers["contours"]
    (stair,) = finding.numbers["stair_tables"]
    table = finish["rows"] + stair["rows"]
    assert turned and table
    if per_radius:
        assert finding.status == "pass"
        assert all(row["x_target_mm"] == pytest.approx(3.175 * per_radius) for row in turned)
        for row in table:
            assert row["x_target_mm"] == pytest.approx(row["radius_mm"] * per_radius)
            assert row["setup_xz"][0] == row["x_target_mm"]
        assert all(isinstance(row["x_tool_mm"], float) for row in finish["rows"])
        return
    # Not knowing whether the DRO shows radius or diameter, no X reading is printable;
    # the physical sizes stay.
    assert finding.status == "unknown" and "radius_mode" in finding.sentence
    assert {row["x_target_mm"] for row in turned} == {"unknown"}
    for row in table:
        assert isinstance(row["radius_mm"], float)
        assert row["x_target_mm"] == row["setup_xz"][0] == "unknown"
        assert row.get("x_tool_mm", "unknown") == "unknown"


@pytest.mark.parametrize(
    ("radius_mode", "shown"), [(False, "diameter"), (True, "radius"), ("unknown", None)]
)
def test_a_dome_table_prints_x_in_the_dro_display_or_withholds_it(radius_mode, shown):
    bundle = _on_display(_dome_bundle(rough_allowance_mm=0.2), radius_mode)
    _, _, sheet, setup = _traveler(bundle)
    html = unescape(sheet.contours(setup, {("tools", "ar"): "T1 AR"}))
    if shown:
        unit = "Ø" if shown == "diameter" else shown
        assert f"X is {shown}" in html
        assert f"in to X ({unit})" in html and f"surface X ({unit})" in html
        return
    # Neither the rough stair nor the finish table prints a number it cannot read.
    assert "<table" not in html and "X is" not in html
    assert re.search(r"STOP: contour points not computed[^<]*radius or diameter", html), html


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
    assert sheet.rest_steps(setup, op)[0] == ["follow rest on: Z 2.000"]


def test_the_jaw_clearance_is_the_tools_own_chuck_side_extent_not_the_z_its_op_names():
    # The op names Z0.25; the insert's nose, posed on the profile, reaches Z0.104 on the
    # chuck side: 2.104 from jaw fronts at Z-2, printed down the 0.01 grid as 2.10.
    sheet, setup, op = _sheet("mm", 0.01, {"tool_z_mm": [0.104, 2.15], "feed_z": -1}, 1.75, 0.25)
    setup["hold"]["pose"] = {"origin_mm": [0.0, 0.0, -2.0], "z": [0.0, 0.0, 1.0]}
    sheet.records[("headroom", "S1")] = {"stock_od_mm": 10.0}
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(2.10)}
    assert "closest planned tool stop 2.10 mm from the jaws" in sheet.clearance(setup)
    assert sheet.crash_boxes(setup, op) == ["JAWS Z -2.00: 2.10 clear — hand feed to a stop"]


def _dome_tables(compensation=0.4):
    """A dome's finish table (fed to its tool readings) and rough stair, op 10."""
    rows = [{"z_mm": 1.75, "z_tool_mm": 1.75}, {"z_mm": 0.25, "z_tool_mm": 0.104}]
    if compensation == "unknown":
        rows = [{"z_mm": row["z_mm"]} for row in rows]
    finish = {
        "op": 10,
        "method": "axial_table",
        "tool_nose_compensation_mm": compensation,
        "rows": rows,
    }
    stair = {"op": 10, "stage": "rough", "rows": [{"z_mm": 1.65}, {"z_mm": 0.45}]}
    return {"contours": [finish], "stair_tables": [stair]}


def test_a_tool_fed_to_its_tip_table_stands_where_the_table_puts_it_not_on_the_drawn_profile():
    # The plan forms the dome 0.25 above the drawn one (a cut-to-fit end): the kernel stands
    # the nose on the drawn profile down to Z-0.146, but the finish table feeds it to Z0.104
    # at most, so the tool stops 8.104 from jaw fronts at Z-8, printed down the grid as 8.10.
    numbers = {"tool_z_mm": [-0.146, 62.475], "nose_z_mm": [-0.146, 2.29], "feed_z": -1}
    sheet, setup, op = _sheet("mm", 0.01, numbers, 1.75, 0.25)
    setup["hold"]["pose"] = {"origin_mm": [0.0, 0.0, -8.0], "z": [0.0, 0.0, 1.0]}
    sheet.records[("headroom", "S1")] = {"stock_od_mm": 10.0}
    sheet.records[("coordinates", "S1")] = _dome_tables()
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(8.10)}
    assert "closest planned tool stop 8.10 mm from the jaws" in sheet.clearance(setup)
    # A shank standing 1.6 below the nose at every pose goes with it: Z-1.496, so 6.50.
    sheet.records[("accessibility", "S1:10")]["tool_z_mm"] = [-1.746, 62.475]
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(6.50)}
    # A table printing only the surface does not say where the nose stands.
    sheet.records[("coordinates", "S1")] = _dome_tables("unknown")
    assert sheet.lathe_approaches(setup) == {"10": "unknown"}
    # Nor does a tool the kernel posed without its nose's extent.
    sheet.records[("coordinates", "S1")] = _dome_tables()
    del sheet.records[("accessibility", "S1:10")]["nose_z_mm"]
    assert sheet.lathe_approaches(setup) == {"10": "unknown"}


def test_a_tool_posed_within_the_kernels_hit_test_inset_of_its_ops_z_stands_at_that_z():
    # Posed into the shoulder at the op's Z-23, the nose's outline stands 0.000977 past it: the
    # kernel clears only its 0.001 inset section, so the tool stops at Z-23.00, 4.99 from -27.99.
    numbers = {"tool_z_mm": [-23.000977, 82.88], "nose_z_mm": [-23.000977, 21.8], "feed_z": -1}
    sheet, setup, op = _sheet("mm", 0.01, numbers, 21.0, -23.0)
    setup["hold"]["pose"] = {"origin_mm": [0.0, 0.0, -27.99], "z": [0.0, 0.0, 1.0]}
    sheet.records[("headroom", "S1")] = {"stock_od_mm": 10.0}
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(4.99)}
    record = sheet.records[("accessibility", "S1:10")]
    # Farther past it than that, the outline is past the Z: down the grid, 4.98.
    record["tool_z_mm"] = [-23.0015, 82.88]
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(4.98)}
    # A blade's far face 0.0005 short of a grid line, but a whole width from the op's Z, is the
    # tool's own reach (3.9895): never printed as 3.99.
    record["tool_z_mm"] = [-24.0005, 82.88]
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(3.98)}
    # Nor is a shank's: the nose posed exactly on the Z, a wider shank 0.0005 past it stands
    # 4.9895 from the jaws, printed down the grid as 4.98.
    record.update(tool_z_mm=[-23.0005, 82.88], nose_z_mm=[-23.0, 21.8])
    assert sheet.lathe_approaches(setup) == {"10": pytest.approx(4.98)}


@pytest.mark.parametrize("extent", [{"tool_z_mm": "unknown"}, {}], ids=["unknown", "absent"])
def test_a_tool_the_kernel_could_not_pose_whole_has_an_unknown_jaw_clearance(extent):
    # Its holder is undeclared, or the kernel stopped before posing it at all: the shank may
    # stand nearer the jaws than the Z the op names, so no distance is printed and the op
    # still gets its hand-feed check.
    sheet, setup, op = _sheet("mm", 0.01, {**extent, "feed_z": -1}, 1.75, 0.25)
    setup["hold"]["pose"] = {"origin_mm": [0.0, 0.0, -8.0], "z": [0.0, 0.0, 1.0]}
    sheet.records[("headroom", "S1")] = {"stock_od_mm": 10.0}
    assert sheet.lathe_approaches(setup) == {"10": "unknown"}
    assert "closest tool approach not computed — check at the machine" in sheet.clearance(setup)
    assert sheet.crash_boxes(setup, op) == [
        "JAWS Z -8.00: tool clearance not computed — hand feed to a stop"
    ]


def test_a_follow_rest_z_is_printed_on_the_clear_side_of_the_dro_grid():
    # Clear from Z155.47 toward the chuck; declared 155.46 passes, but ordinary rounding
    # to the 0.1 grid prints 155.5, where the jaws still meet the centre.
    engage = {"declared_z_mm": 155.46, "engage_z_mm": 155.47}
    sheet, setup, op = _sheet("mm", 0.1, {"rest_engagement": [engage], "feed_z": -1}, 166.0, 0.2)
    assert sheet.rest_steps(setup, op)[0] == ["follow rest on: Z 155.4"]
    # Feeding away from the chuck the clear side is up the grid.
    sheet, setup, op = _sheet(
        "mm",
        0.1,
        {"rest_engagement": [{"declared_z_mm": 10.04, "engage_z_mm": 10.03}], "feed_z": 1},
        0.0,
        50.0,
    )
    assert sheet.rest_steps(setup, op)[0] == ["follow rest on: Z 10.1"]
    # No grid position between the clear Z and the op's end is refused, not rounded in.
    sheet, setup, op = _sheet(
        "mm",
        0.1,
        {"rest_engagement": [{"declared_z_mm": 0.25, "engage_z_mm": 0.26}], "feed_z": -1},
        166.0,
        0.22,
    )
    [line] = sheet.rest_steps(setup, op)[0]
    assert line.startswith("STOP")


def _rest_steps(side, lead=8.0, engage=True, declared=None):
    """The follow-rest cells and full-width lines of a rough turn fed toward the chuck,
    the jaws on ``side`` ``lead`` mm from the tool; ``engage``: set on once past Z152,
    checked clear; ``declared``: the support's own engage_at_z_mm."""
    numbers = {"feed_z": -1}
    if engage:
        numbers["rest_engagement"] = [{**_ENGAGE, "engage_z_mm": 155.474, "declared_z_mm": 152.0}]
    sheet, setup, op = _sheet("mm", 0.01, numbers, 166.0, 0.2)
    support = {"ref": "follow_rest", "ops": [10], "jaw_side": side}
    if lead is not None:
        support["jaw_lead_mm"] = lead
    if declared is not None:
        support["engage_at_z_mm"] = declared
    setup["hold"]["supports"] = [support]
    return sheet.rest_steps(setup, op)


_PASS_END = [
    "stop the feed, then the spindle",
    "back the follow-rest jaws off",
    "withdraw the tool along X",
    "return the carriage",
]


@pytest.mark.parametrize("engage", [True, False])
def test_a_follow_rest_on_the_turned_diameter_is_backed_off_before_every_return(engage):
    # The return carries trailing jaws back past the pass start onto stock this pass never
    # cut: they come off first, the spindle stopped, then the tool, then the carriage.
    cells, lines = _rest_steps("turned", engage=engage)
    [line] = lines
    end = line[line.index("Pass end") :]
    found = [end.find(words) for words in _PASS_END]
    assert -1 not in found and found == sorted(found), end
    # The sequence prints once, full width; the coordinate cell keeps only the Z.
    assert cells == (["follow rest on: Z 152.00"] if engage else [])
    assert ("at Z 152.00: stop the feed, then the spindle; set the follow-rest jaws" in line) is (
        engage
    )


def test_a_follow_rest_riding_the_uncut_stock_is_not_released_for_the_return():
    # Leading jaws return over the diameter just cut, smaller than their setting.
    cells, lines = _rest_steps("uncut")
    assert cells == ["follow rest on: Z 152.00"]
    assert not any("back the follow-rest jaws off" in line for line in lines)
    assert any("on the uncut stock ahead of the tool" in line for line in lines)


@pytest.mark.parametrize(
    ("side", "lead"), [("turned", None), ("turned", "unknown"), ("turned", 0.0), ("unknown", 8.0)]
)
def test_a_follow_rest_with_unknown_geometry_stops_and_never_prints_a_checked_return(side, lead):
    _, lines = _rest_steps(side, lead=lead)
    assert any(line.startswith("STOP") for line in lines)
    assert not any("return the carriage" in line for line in lines)


def test_a_declared_follow_rest_z_that_was_not_checked_stops_never_falls_back_to_the_lead():
    # The plan sets the rest on at Z152 (past where the start would foul it); with no
    # clearance check of that Z, "once the tool has turned 8 mm" would contradict it.
    cells, lines = _rest_steps("turned", engage=False, declared=152.0)
    assert [type(cell).__name__ for cell in cells] == ["_Box"]
    assert str(cells[0]).startswith("STOP")
    assert not any("once the tool has turned" in str(line) for line in lines)


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
    # The groove is the row's own Z window, printed there in inches.
    assert "Z 0.000 → 0.079" in sheet.tip(setup, op)
    assert not any(line.startswith("groove Z") for line in printed), printed


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


def test_the_follow_rest_goes_on_with_the_spindle_stopped_and_it_restarts_before_the_cut(
    tmp_path,
):
    from test_cli import copy_examples

    from prechips.findings import Finding
    from prechips.inputs import load_bundle
    from prechips.sheet import render_traveler

    bundle = load_bundle(copy_examples(tmp_path) / "pivot-shaft" / "plan.toml")
    engage = {**_ENGAGE, "engage_z_mm": 155.474, "declared_z_mm": 152.0}
    clear = [
        Finding(
            "accessibility",
            f"S1:{number}",
            "pass",
            {"rest_engagement": [engage], "feed_z": -1},
            [],
            f"S1:{number}.",
        )
        for number in (10, 30)
    ]
    page = render_traveler(bundle, clear, {})
    html = unescape(re.sub(r"<[^>]+>", " ", page))
    step = re.search(r"at Z 152\.00: [^.]*", html).group(0)
    # Hands go near the work only once it has stopped, and the cut resumes on a running spindle.
    order = [
        "stop the feed, then the spindle",
        "set the follow-rest jaws",
        "lock them",
        "restart the spindle",
        "then resume the feed",
    ]
    found = [step.find(words) for words in order]
    assert -1 not in found and found == sorted(found), step
    # Ops 10 and 30 each print the sequence once, in the full-width line under the row;
    # the narrow coordinate cell keeps only the Z.
    full_width = re.findall(r'<span class="see">([^<]*)</span>', page)
    assert sum("set the follow-rest jaws" in line for line in full_width) == 2
    assert unescape(page).count("set the follow-rest jaws") == 2
    # Each op's coordinate cell prints the Z its own engagement check cleared.
    assert unescape(page).count("follow rest on: Z 152.00") == 2


def test_each_op_sets_the_follow_rest_on_the_side_its_own_support_entry_declares(tmp_path):
    from test_cli import copy_examples

    from prechips.findings import Finding
    from prechips.inputs import load_bundle
    from prechips.sheet import render_traveler

    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    one = (
        'supports = [{ ref = "follow_rest", ops = [10, 30], jaw_lead_mm = 8.0, '
        'jaw_side = "turned", engage_at_z_mm = 152.0 }]'
    )
    assert text.count(one) == 1
    # The same rest, ridden behind the tool on op 10 and ahead of it on op 30.
    plan.write_text(
        text.replace(
            one,
            'supports = [{ ref = "follow_rest", ops = [10], jaw_lead_mm = 8.0, '
            'jaw_side = "turned", engage_at_z_mm = 152.0 }, { ref = "follow_rest", '
            'ops = [30], jaw_lead_mm = 8.0, jaw_side = "uncut", engage_at_z_mm = 151.0 }]',
        ),
        encoding="utf-8",
    )
    bundle = load_bundle(plan)
    findings = [
        Finding(
            "accessibility",
            f"S1:{op}",
            "pass",
            {
                "rest_engagement": [{**_ENGAGE, "engage_z_mm": 155.474, "declared_z_mm": z}],
                "feed_z": -1,
            },
            [],
            f"S1:{op}.",
        )
        for op, z in ((10, 152.0), (30, 151.0))
    ]
    html = unescape(re.sub(r"<[^>]+>", " ", render_traveler(bundle, findings, {})))
    op10 = re.search(r"at Z 152\.00: [^;]*;[^;]*", html).group(0)
    op30 = re.search(r"at Z 151\.00: [^;]*;[^;]*", html).group(0)
    assert "on the diameter just turned" in op10, op10
    assert "on the uncut stock ahead of the tool" in op30, op30


_FACE_TOUCH = {"tool": "blade", "z_face": "shoulder", "edge_mm": 0.0, "paper_mm": 0.0}


def _parted(touch, ends, side, to_z=-5.0, face="shoulder"):
    """A blade parting the end to ``to_z`` after its Z ``touch``; a synthetic kernel gives
    the touched ``face`` its ``end_faces`` and the op its ``faced_side`` (None: no fact)."""
    op = {"op": 40, "do": "part_off", "feature": "end", "tool": "blade", "to_z": to_z}
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
    text = sheet.dro(setup, {("tools", "blade"): "T3 blade"})
    assert "Z — chuck-side corner on the north" in text
    assert "Z now reads the chuck-side corner" in text


@pytest.mark.parametrize(
    ("do", "extra", "depth", "expected"),
    [
        # The shaft's S3 op 10: the blade plunges a Ø6.4 bearing to the axis.
        ("cut_to_fit", {"to_dia": 0.0}, 3.2, "X 6.40 → 0.00 (3.20 radial)"),
        ("part_off", {}, 3.2, "X 6.40 → 0.00 (3.20 radial)"),
        # Parted to a diameter (a sleeve left on an arbor): X stops there.
        ("part_off", {"to_dia": 2.0}, 2.2, "X 6.40 → 2.00 (2.20 radial)"),
        # The plunge is unmeasured: the endpoint still prints, the start does not.
        ("cut_to_fit", {"to_dia": 0.0}, "unknown", "X → 0.00 (radial plunge unknown)"),
    ],
)
def test_a_parting_row_prints_the_x_it_plunges_to_and_the_radial_plunge(do, extra, depth, expected):
    touch = {"tool": "blade", "z_face": "shoulder", "edge_mm": 0.0, "paper_mm": 0.0}
    bundle = _parted(touch, [{"z_mm": 0.0, "normal_z": 1}], -1)
    op = bundle.plan["setups"][0]["ops"][0]
    op.update(do=do, **extra)
    _, _, sheet, setup = _traveler(bundle)
    sheet.records[("reach", "S1:40")] = {"reach_depth_mm": depth}
    parts = sheet.tip(setup, op)
    assert expected in parts, parts


def test_a_parting_row_with_an_unknown_endpoint_stops():
    touch = {"tool": "blade", "z_face": "shoulder", "edge_mm": 0.0, "paper_mm": 0.0}
    bundle = _parted(touch, [{"z_mm": 0.0, "normal_z": 1}], -1)
    op = bundle.plan["setups"][0]["ops"][0]
    op.update(do="cut_to_fit", to_dia="unknown")
    _, _, sheet, setup = _traveler(bundle)
    assert any("STOP" in str(part) and "X endpoint" in str(part) for part in sheet.tip(setup, op))


@pytest.mark.parametrize(
    ("radius_mode", "depth", "expected"),
    [
        # A radius display reads half of both ends: Ø2.0 is X1.00, the Ø6.4 start X3.20.
        (True, 2.2, "X 3.20 → 1.00 (2.20 radial)"),
        (True, "unknown", "X → 1.00 (radial plunge unknown)"),
        # Not knowing the display, X1.00 and X2.00 are each wrong on one of them.
        ("unknown", 2.2, None),
        ("unknown", "unknown", None),
        (None, 2.2, None),
    ],
)
def test_a_parting_row_prints_its_x_only_on_a_known_dro_display(radius_mode, depth, expected):
    bundle = _on_display(_parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": 1}], -1), radius_mode)
    op = bundle.plan["setups"][0]["ops"][0]
    op.update(to_dia=2.0)
    _, _, sheet, setup = _traveler(bundle)
    sheet.records[("reach", "S1:40")] = {"reach_depth_mm": depth}
    parts = [str(part) for part in sheet.tip(setup, op)]
    if expected:
        assert expected in parts, parts
        return
    assert not any(part.startswith("X") for part in parts), parts
    assert any(part.startswith("STOP") and "radius or diameter" in part for part in parts), parts


def _traveler(bundle):
    """(zero_check, coordinates, sheet, setup) for a one-setup bundle, records loaded."""
    from prechips.sheet import _Traveler

    [zero] = zero_recipe.evaluate(bundle)
    [finding] = coordinates.evaluate(bundle)
    sheet = _Traveler(bundle, [], {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    sheet.records[("zero_check", "S1")] = zero.numbers
    sheet.records[("coordinates", "S1")] = finding.numbers
    return zero, finding, sheet, setup


def _allowed(parts):
    """The two readings a printed op row's ``allowed lo to hi`` interval names."""
    import re

    [text] = [part for part in parts if "allowed" in part]
    return [float(v) for v in re.findall(r"-?\d+\.\d+|-?\d+", text.split("allowed", 1)[1])[:2]]


@pytest.mark.parametrize(
    ("width", "band", "readings"),
    [
        # A 1.6 blade reading its chuck-side corner forms the -Z face with its
        # tailstock-side corner: face -5.1..-4.9 is read -6.7..-6.5.
        (1.6, [-5.1, -4.9], [-6.7, -6.5]),
        # Off the 0.01 grid (1.605) the readings round inward: -6.705 up, -6.505 down.
        (1.605, [-5.1, -4.9], [-6.7, -6.51]),
    ],
)
def test_a_banded_part_off_prints_its_allowed_band_as_readings_of_the_same_corner(
    width, band, readings
):
    bundle = _parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": 1}], -1)
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = width
    op = bundle.plan["setups"][0]["ops"][0]
    op["to_z_band"] = band
    _, finding, sheet, setup = _traveler(bundle)
    assert finding.status == "pass"
    [entry] = finding.numbers["operations"]
    corner = entry["blade"]["corner_dro_z"]
    printed = _allowed(sheet.tip(setup, op))
    assert printed == pytest.approx(readings)
    assert printed[0] <= corner <= printed[1]
    # Every reading in the printed interval leaves the formed face inside the band.
    for reading in printed:
        assert band[0] - 1e-9 <= reading + width <= band[1] + 1e-9


def test_a_blade_target_whose_formed_face_leaves_its_allowed_band_is_an_error():
    # to_z -4.9 is the band's high end: the 1.605 blade's chuck-side reading rounds up to
    # -6.50, so its tailstock-side corner forms -4.895, outside -5.1..-4.9.
    bundle = _parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": 1}], -1, to_z=-4.9)
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = 1.605
    bundle.plan["setups"][0]["ops"][0]["to_z_band"] = [-5.1, -4.9]
    finding, entry = _blade_entry(bundle)
    assert entry["dro_to_z"] == pytest.approx(-4.895)
    assert finding.status == "error"
    # The 1.6 blade forms -4.9 exactly: inside.
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = 1.6
    assert _blade_entry(bundle)[0].status == "pass"


@pytest.mark.parametrize(("normal", "axis_set"), [(-1, -0.05), (1, 0.05)])
def test_paper_stands_a_blade_off_its_face_on_the_side_it_touches_from(normal, axis_set):
    # Through 0.05 paper a -Z-facing shoulder at Z0 is met from -Z: the tailstock-side
    # corner stands at Z-0.05, so the Axis Set is -0.05 (+0.05 put the reference 0.1 off
    # and cut -5.00 at -5.10). A +Z face is met from +Z: +0.05.
    touch = {**_FACE_TOUCH, "paper_mm": 0.05, "x_method": "touch the bar diameter"}
    bundle = _parted(touch, [{"z_mm": 0.0, "normal_z": normal}], -1)
    setup = bundle.plan["setups"][0]
    setup["ops"].append({"op": 50, "do": "rough_turn", "feature": "body", "tool": "turner"})
    bundle.inventory["tools"]["turner"] = dict(_AR)
    [zero] = zero_recipe.evaluate(bundle)
    [row] = zero.numbers["tool_touches"]
    assert row["paper_mm"] == 0.05
    assert row["z_axis_set"] == pytest.approx(axis_set)
    # The turner re-touches the same shoulder from the same side.
    [derived] = zero.numbers["derived_touches"]
    assert derived["z_face"] == "shoulder"
    assert derived["z_axis_set"] == pytest.approx(axis_set)
    # The blade as the setup's Z zero on that shoulder.
    bundle.plan["dro"]["direction"] = {"z": "toward_exposed_end"}
    setup["zero"] = {
        "z": {
            "face": "shoulder",
            "edge_mm": 0.0,
            "paper_mm": 0.05,
            "method": "touch_then_set",
            "tool": "blade",
            "check_jog_mm": 10.0,
            "retouch_after": [],
        }
    }
    [zero] = zero_recipe.evaluate(bundle)
    assert zero.numbers["axes"]["z"]["axis_set"] == pytest.approx(axis_set)
    assert zero.numbers["axes"]["z"]["check_reading"] == pytest.approx(axis_set + 10.0)


def test_a_blade_touch_through_paper_with_no_known_side_has_no_axis_set():
    # No face normal and no authored corner: which side the paper is on is unknown.
    touch = {**_FACE_TOUCH, "paper_mm": 0.05}
    [zero] = zero_recipe.evaluate(_parted(touch, [], -1))
    assert zero.numbers["tool_touches"][0]["z_axis_set"] == "unknown"
    # Without paper the side does not matter.
    [zero] = zero_recipe.evaluate(_parted(_FACE_TOUCH, [], -1))
    assert zero.numbers["tool_touches"][0]["z_axis_set"] == 0.0


@pytest.mark.parametrize(
    ("width", "face", "status"), [(1.605, -9.995, "error"), (1.6, -10.0, "pass")]
)
def test_a_blade_face_is_checked_where_its_rounded_corner_reading_forms_it(width, face, status):
    # The chuck-side reading of a 1.605 blade forming -10 with its tailstock-side corner
    # rounds -11.605 up to -11.60, so the face forms at -9.995: a 9.995 sleeve, outside
    # its 9.999..10.001 length. The on-grid 1.6 blade forms -10 exactly.
    bundle = _parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": 1}], -1, to_z=-10.0)
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = width
    bundle.plan["setups"][0]["ops"][0]["feature"] = "sleeve"
    bundle.features["features"]["sleeve"] = {
        "kind": "shaft",
        "length": [9.999, 10.001],
        "requirements": ["length"],
    }
    finding, entry = _blade_entry(bundle)
    assert entry["blade"]["corner_dro_z"] == pytest.approx(-11.6)
    assert entry["dro_to_z"] == pytest.approx(face)
    assert finding.status == status


@pytest.mark.parametrize(("width", "printed"), [(1.605, -9.99), (1.6, -10.0)])
def test_a_surface_a_blade_faced_prints_where_its_rounded_corner_reading_left_it(width, printed):
    # A blade facing op leaves its face where its rounded reading puts the forming corner:
    # a later touch on that face sees -9.995 (on the grid, -9.99), not the authored -10.
    from prechips.rules.tip_endpoints import operative_z

    bundle = _parted(_FACE_TOUCH, [{"z_mm": 0.0, "normal_z": 1}], -1, to_z=-10.0)
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = width
    setup = bundle.plan["setups"][0]
    setup["ops"][0].update(do="face", feature="end")
    assert operative_z(bundle, setup, -10.0, face="end", done=1) == pytest.approx(printed)


def _retouched(width):
    """On a 0.1 grid the turner turns the bar (op 30: the standing diameter its later
    re-touch reads X on); a ``width`` blade faces the end to -10 (op 40) reading its
    chuck-side corner (forming with its tailstock-side one); the turner, re-touched on that
    end, then faces the sleeve to -8 (op 50), a 7.96..8.04 length."""
    touch = {
        **_FACE_TOUCH,
        "gauge": "mic",
        "x_method": "touch bar diameter",
        "x_face": "bar",
        "x_paper_mm": 0.0,
    }
    bundle = _parted(touch, [{"z_mm": 0.0, "normal_z": 1}], -1, to_z=-10.0)
    bundle.plan["dro"].update(
        mode="abs", direction={"x": "away_from_spindle_axis", "z": "toward_exposed_end"}
    )
    bundle.inventory["machines"]["lathe"]["resolution_mm"] = 0.1
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = width
    bundle.inventory["gauges"] = {"mic": {"kind": "micrometer", "resolution_mm": 0.01}}
    bundle.inventory["tools"]["turner"] = dict(_AR)
    setup = bundle.plan["setups"][0]
    setup["zero"].update(
        x={
            "feature": "spindle_axis",
            "method": "trial_cut_measure",
            "tool": "turner",
            "gauge": "mic",
            "check_jog_mm": 10.0,
        },
        z={
            "face": "other_end",
            "edge_mm": 20.0,
            "method": "face_then_set",
            "tool": "turner",
            "paper_mm": 0.0,
            "check_jog_mm": 10.0,
            "retouch_after": [],
        },
    )
    setup["ops"][0]["do"] = "face"
    setup["ops"].insert(
        0,
        {"op": 30, "do": "turn", "feature": "bar", "tool": "turner", "z_from": 0.0, "z_to": -10.0},
    )
    bundle.features["features"]["bar"] = {"kind": "shaft", "frame": "model", "dia": [9.9, 10.0]}
    setup["ops"].append(
        {"op": 50, "do": "face", "feature": "sleeve", "tool": "turner", "to_z": -8.0}
    )
    bundle.features["features"]["sleeve"] = {
        "kind": "shaft",
        "length": [7.96, 8.04],
        "requirements": ["length"],
    }
    return bundle


def _consumer(bundle, kind):
    """``_retouched``'s op 50 as the cut that reads the re-touched end: the sleeve faced to
    -8 for its length, the same face held by its own -8.04..-7.96 band (the sleeve length
    unknown), a blind 2.0 bore from an entry at 0 held to 1.96..2.04 deep, or a 1.6 parter
    re-touched (chuck-side corner) on the end to part at -20 within -20.05..-19.95."""
    setup = bundle.plan["setups"][0]
    features = bundle.features["features"]
    if kind == "band":
        setup["ops"][2]["to_z_band"] = [-8.04, -7.96]
        features["sleeve"] = {"kind": "shaft", "length": "unknown", "requirements": ["length"]}
    elif kind == "bore":
        bundle.inventory["tools"]["turner"]["kind"] = "boring_bar"
        setup["stock_state"]["entry_z"] = {"hole": 0.0}
        setup["ops"][2] = {
            "op": 50,
            "do": "bore",
            "feature": "hole",
            "tool": "turner",
            "depth_mm": 2.0,
        }
        features["hole"] = {
            "kind": "hole",
            "thru": False,
            "depth": [1.96, 2.04],
            "requirements": ["depth"],
            "at": [0.0, 0.0, 0.0],
            "dia": [4.0, 4.1],
        }
    elif kind == "blade":
        op = {"op": 60, "do": "part_off", "tool": "parter", "to_z": -20.0}
        setup["ops"][2:] = [{**op, "to_z_band": [-20.05, -19.95]}]
        bundle.inventory["tools"]["parter"] = _blade()
        bundle.kernel["setups"]["S1"]["revolved"]["end"] = {
            "end_faces": [{"z_mm": -10.0, "normal_z": 1}]
        }
        bundle.kernel["ops"]["S1:60"] = {"faced_side": -1}
    return bundle


@pytest.mark.parametrize("kind", ["length", "band", "bore", "blade"])
@pytest.mark.parametrize("width", [1.61, 1.6])
def test_a_touch_on_a_blade_face_off_its_dro_grid_is_refused_whatever_cuts_next(kind, width):
    # The 1.61 blade's chuck-side reading -11.6 forms the end at -9.99, which a re-touch
    # on the 0.1 grid can only set as -9.9: every Z the re-touched tool then cuts to lands
    # 0.09 deeper than printed (a 8.09 sleeve, a face at -8.09, a 2.09 bore, a part-off at
    # -20.09). zero_check refuses the touch, whichever cut reads it. The on-grid 1.6 blade
    # forms -10.0 where the re-touch sets it, and every cut holds.
    from prechips.rules import tip_endpoints

    bundle = _consumer(_retouched(width), kind)
    zero, finding, sheet, setup = _traveler(bundle)
    [retouch] = zero.numbers["derived_touches"]
    assert (retouch["z_face"], retouch["before_ops"][0]) == ("end", setup["ops"][2]["op"])
    # The Axis Set the sheet prints for the end against where the blade left it.
    stands = coordinates.formed_z(bundle, setup, setup["ops"][1])
    off = sheet.datum_z(setup, "end", -10.0, done=2) != pytest.approx(stands)
    assert off is (width == 1.61)
    assert zero.status == ("error" if off else "pass")
    if not off:
        assert finding.status == "pass"
        if kind == "bore":
            [blind] = [f for f in tip_endpoints.evaluate(bundle) if f.subject == "hole"]
            assert blind.status == "pass"


@pytest.mark.parametrize("missing", ["width", "side", "edge"])
def test_a_touch_on_a_blade_face_standing_at_an_unknown_z_is_unknown(missing):
    # The on-grid blade's end stands at an unknown Z when its width, its forming side or
    # the edge its own touch set the DRO on is unknown: the re-touch on that end has no
    # known Axis Set, so it is never set from the nominal -10.
    bundle = _retouched(1.6)
    setup = bundle.plan["setups"][0]
    if missing == "width":
        bundle.inventory["tools"]["blade"]["blade_width_mm"] = "unknown"
    elif missing == "side":
        bundle.kernel["ops"]["S1:40"] = {}
    else:
        setup["zero"]["tool_touches"][0]["edge_mm"] = "unknown"
    zero, finding, sheet, setup = _traveler(bundle)
    assert coordinates.formed_z(bundle, setup, setup["ops"][1]) == "unknown"
    assert sheet.datum_z(setup, "end", -10.0, done=2) == "unknown"
    assert zero.status == "unknown"


def _zeroed_on_the_end(bundle):
    """S1 keeps its ops through op 40, the cut that leaves the end at -10; S2 takes its
    part in the same frame, zeros its turner on that end (edge -10, no paper) and faces the
    sleeve to -8, a 7.96..8.04 length."""
    import copy

    first = bundle.plan["setups"][0]
    first["ops"] = first["ops"][:2]
    second = copy.deepcopy(first)
    second.update(id="S2", stock_in="S1", machine="lathe")
    second["ops"] = [{"op": 50, "do": "face", "feature": "sleeve", "tool": "turner", "to_z": -8.0}]
    second["zero"]["tool_touches"] = []
    second["zero"]["z"].update(face="end", edge_mm=-10.0, tool="turner", method="touch")
    bundle.plan["setups"].append(second)
    return bundle


@pytest.mark.parametrize("do", ["face", "part_off"])
@pytest.mark.parametrize(
    ("width", "status"), [("unknown", "unknown"), (1.61, "error"), (1.6, "pass")]
)
def test_a_later_setup_zeroed_on_a_blade_face_reads_where_it_stands(do, width, status):
    # S2 zeros on the end S1's blade faced or parted off. Its Z zero is set where that end
    # stands: never from the nominal -10 when S1 left it at an unknown Z, refused when S1
    # left it off S2's 0.1 grid (-9.99, set as -9.9), whatever the blade's action.
    bundle = _retouched(1.6)
    bundle.inventory["tools"]["blade"]["blade_width_mm"] = width
    bundle.plan["setups"][0]["ops"][1]["do"] = do
    bundle = _zeroed_on_the_end(bundle)
    zeros = {f.subject: f.status for f in zero_recipe.evaluate(bundle)}
    assert zeros == {"S1": "pass", "S2": status}
    if status == "pass":
        assert {f.subject: f.status for f in coordinates.evaluate(bundle)} == {
            "S1": "pass",
            "S2": "pass",
        }


@pytest.mark.parametrize(
    ("fact", "to_z", "status"),
    [
        ({"faced_side": 1, "sample_count": 3}, -9.95, "error"),
        ({"faced_side": 1, "sample_count": 3}, -9.9, "pass"),
        ({}, -9.95, "unknown"),
        ({"sample_count": 3, "claimed_indices": [0]}, -9.95, "pass"),
    ],
)
def test_a_later_setup_zeroed_on_a_turned_shoulder_reads_where_it_stands(fact, to_z, status):
    # S1 turns the end's shoulder to to_z with the turner on a 0.01 lathe; S2's 0.1 DRO
    # can only set -9.95 as -9.9, so its zero on that shoulder is refused, and an on-grid
    # -9.9 shoulder passes. The kernel pose decides whether the turn left a face there:
    # unsampled, it is unknown, never stock; sampled over a cylinder alone (a diameter),
    # the end is stock its touch sets.
    bundle = _retouched(1.6)
    lathe = bundle.inventory["machines"]["lathe"]
    bundle.inventory["machines"]["fine_lathe"] = {**lathe, "resolution_mm": 0.01}
    first = bundle.plan["setups"][0]
    first["machine"] = "fine_lathe"
    first["ops"][1] = {"op": 40, "do": "turn", "feature": "end", "tool": "turner", "to_z": to_z}
    bundle.kernel["ops"]["S1:40"] = fact
    bundle.kernel["faces"] = [{"index": 0, "kind": "Cylinder"}]
    bundle = _zeroed_on_the_end(bundle)
    bundle.plan["setups"][1]["zero"]["z"]["edge_mm"] = to_z
    zeros = {f.subject: f.status for f in zero_recipe.evaluate(bundle)}
    assert zeros == {"S1": "pass", "S2": status}


_END_TOUCH = {
    "tool": "turner",
    "z_face": "end",
    "edge_mm": -10.0,
    "paper_mm": 0.0,
    "before_ops": [50],
    "gauge": "mic",
    "x_method": "touch bar diameter",
    "x_face": "bar",
    "x_paper_mm": 0.0,
    "method": "touch",
}


def _claims(bundle, kinds, count):
    """The kernel samples S1's op 40 ``count`` times over claimed faces of ``kinds``,
    posing it on no plane (no ``faced_side``)."""
    bundle.kernel["faces"] = [{"index": i, "kind": kind} for i, kind in enumerate(kinds)]
    bundle.kernel["ops"]["S1:40"] = {
        "approach": "turning",
        "sample_count": count,
        "claimed_indices": list(range(len(kinds))),
    }


def _touched_end(bundle, route):
    """The turner touched on the end at -10 after S1's op 40, re-touched in S1 before op
    50 (``authored``) or as S2's Z zero (``later_setup``): that setup's zero_check status
    and the Axis Set the sheet prints for the end."""
    from prechips.rules.tip_endpoints import operative_z

    if route == "authored":
        bundle.plan["setups"][0]["zero"]["tool_touches"].append(dict(_END_TOUCH))
        setup, done = bundle.plan["setups"][0], 2
    else:
        bundle = _zeroed_on_the_end(bundle)
        setup, done = bundle.plan["setups"][1], 0
    zeros = {f.subject: f.status for f in zero_recipe.evaluate(bundle)}
    return zeros[setup["id"]], operative_z(bundle, setup, -10.0, face="end", done=done)


@pytest.mark.parametrize("route", ["authored", "later_setup"])
@pytest.mark.parametrize(
    ("do", "to_z", "kinds", "count", "status"),
    [
        # The real kernel samples a planar end its op cuts to an unknown target, but
        # poses no plane there (no faced_side): the end stands at an unknown Z.
        ("part_off", "unknown", ["Plane"], 6, "unknown"),
        ("cut_to_fit", "unknown", ["Plane"], 6, "unknown"),
        ("turn", "unknown", ["Plane"], 6, "unknown"),
        ("finish_turn", "unknown", ["Plane"], 6, "unknown"),
        # A facing or parting op with no target leaves its face at an unknown Z.
        ("part_off", None, ["Plane"], 6, "unknown"),
        ("face", None, ["Plane"], 6, "unknown"),
        # A known target whose claims face both ways is posed on no one side, yet cuts
        # faces; with nothing sampled, nothing is known of its claims.
        ("turn", -10.0, ["Plane", "Plane"], 6, "unknown"),
        ("turn", -10.0, ["Cylinder"], 0, "unknown"),
        # The diameter-only control: a known target sampled over a cylinder alone.
        ("turn", -10.0, ["Cylinder"], 6, "pass"),
        ("part_off", -10.0, ["Cylinder"], 6, "pass"),
    ],
)
def test_a_touch_on_a_face_a_sampled_cut_may_have_left_is_never_stock(
    route, do, to_z, kinds, count, status
):
    # S1's op 40 cuts the end; the turner then zeros on it at -10, re-touched in S1
    # before op 50 or as S2's Z zero. A sampled cut the kernel did not pose on one side
    # proves no face absent unless its target is known and its claims are diameters
    # alone: else the touch meets a face standing at an unknown Z, never the nominal.
    bundle = _retouched(1.6)
    first = bundle.plan["setups"][0]
    first["ops"][1]["do"] = do
    if to_z is None:
        del first["ops"][1]["to_z"]
    else:
        first["ops"][1]["to_z"] = to_z
    _claims(bundle, kinds, count)
    zero, stands = _touched_end(bundle, route)
    assert zero == status
    assert stands == ("unknown" if status == "unknown" else pytest.approx(-10.0))


@pytest.mark.parametrize("route", ["authored", "later_setup"])
@pytest.mark.parametrize(
    ("do", "tool", "window", "kinds", "count", "status"),
    [
        # A finish turn over Z0..-10 cuts the sleeve's diameter and the shoulder its
        # window ends on; a blade relief over Z-8..-10 cuts both groove walls. The kernel
        # samples each over its claims, but poses neither on a plane.
        ("finish_turn", "turner", (0.0, -10.0), ["Plane", "Cylinder"], 20, "unknown"),
        ("form_relief", "blade", (-8.0, -10.0), ["Plane", "Plane"], 8, "unknown"),
        # Unsampled, a window proves no face absent.
        ("finish_turn", "turner", (0.0, -10.0), ["Cylinder"], 0, "unknown"),
        # The diameter-only control: a window sampled over cylinders alone.
        ("finish_turn", "turner", (0.0, -10.0), ["Cylinder", "Cylinder"], 20, "pass"),
        ("form_relief", "blade", (-8.0, -10.0), ["Cylinder"], 8, "pass"),
    ],
)
def test_a_touch_on_a_face_a_turning_window_may_have_left_is_never_stock(
    route, do, tool, window, kinds, count, status
):
    # S1's op 40 cuts the end over a z_from..z_to window with no to_z; the turner then
    # zeros on the end at -10. No to_z places a face, yet a shoulder or groove wall the
    # window claims is a face it cut: unless the kernel sampled it over diameters alone,
    # the touch meets a face standing at an unknown Z, never the nominal.
    bundle = _retouched(1.6)
    op = bundle.plan["setups"][0]["ops"][1]
    del op["to_z"]
    op.update(do=do, tool=tool, z_from=window[0], z_to=window[1])
    _claims(bundle, kinds, count)
    zero, stands = _touched_end(bundle, route)
    assert zero == status
    assert stands == ("unknown" if status == "unknown" else pytest.approx(-10.0))


def test_a_turning_window_prints_its_own_ends_whatever_an_earlier_window_left():
    # S1's rough window may have left the end's shoulder at an unknown Z: a touch on the
    # end has no Axis Set, yet the finish window after it prints the ends it is authored
    # to (its path, not a face it touches), with no STOP.
    bundle = _retouched(1.6)
    first = bundle.plan["setups"][0]
    rough = first["ops"][1]
    del rough["to_z"]
    rough.update(do="rough_turn", tool="turner", z_from=0.0, z_to=-10.0)
    finish = {**rough, "op": 45, "do": "finish_turn"}
    first["ops"].insert(2, finish)
    _claims(bundle, ["Plane", "Cylinder"], 20)
    bundle.kernel["ops"]["S1:45"] = dict(bundle.kernel["ops"]["S1:40"])
    zero, finding, sheet, setup = _traveler(bundle)
    assert sheet.datum_z(setup, "end", -10.0, done=3) == "unknown"
    assert [sheet.op_z(setup, finish, key) for key in ("z_from", "z_to")] == [0.0, -10.0]
    assert not any("STOP" in part for part in sheet.tip(setup, finish))


@pytest.mark.parametrize("op_spelling,touch_spelling", [("tools.", ""), ("", "tools.")])
def test_a_toolpost_tool_is_one_tool_however_op_and_touch_spell_it(op_spelling, touch_spelling):
    ops = [
        {"op": 10, "do": "rough_turn", "feature": "body", "tool": op_spelling + "turner"},
        {"op": 40, "do": "part_off", "tool": op_spelling + "blade", "to_z": -5.0},
    ]
    touch = {**_FACE_TOUCH, "corner": "chuck_side", "before_ops": [40]}
    zero = {
        "x": {"feature": "spindle_axis", "method": "trial_cut_measure", "tool": "turner"},
        "z": {"face": "end", "edge_mm": 0.0, "method": "touch", "tool": "turner"},
        "tool_touches": [{**touch, "tool": touch_spelling + touch["tool"]}],
    }
    zero["x"]["tool"] = zero["z"]["tool"] = touch_spelling + "turner"
    bundle = _lathe(ops, {}, {"blade": _blade(), "turner": dict(_AR)}, zero=zero)
    [finding] = zero_recipe.evaluate(bundle)
    # Each toolpost tool is set once, before its first touch-off.
    assert [(row["touch"], row["square_blade"]) for row in finding.numbers["tool_setting"]] == [
        ("zero", "not_applicable"),
        ("tool_touches", zero_recipe.SQUARE_BLADE),
    ]


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
    text = sheet.dro(setup, {("tools", "blade"): "T3 blade", ("tools", "turner"): "T1 turner"})
    blade = "Before touching off T3 blade: shim it level with the tailstock point; then square"
    assert text.count(blade) == 1
    assert text.index(blade) < text.index("Before op 40, touch off T3 blade")
    turner = "Before touching off T1 turner: shim it level with the tailstock point."
    assert text.index(turner) < text.index("<table")
