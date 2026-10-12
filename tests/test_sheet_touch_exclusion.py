"""A credited Z touch that must land outside its cut's complete footprint (zero_check
``touch_exclusion_dia_mm``, physical mm) prints that instruction beside its Axis Set on
every contact path: the zero row, explicit and derived tool touches, listed retouches.
A carried row (``setting_residual_mm``) prints the setting the report computed, exactly."""

import copy
import dataclasses
import re

import pytest
from test_tool_change_touch import (
    DECK,
    FACE,
    bundle,
    mill_zero,
    op,
    paragraphs,
    sheet_text,
    zero_rows,
)

from prechips.rules.zero_recipe import evaluate
from prechips.sheet import _outward_mm, _Traveler

OPS = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
TOOLS = {("tools", "centre/1"): "T1 centre drill", ("tools", "drill"): "T2 drill"}
MILL_TOOLS = {("tools", "mill"): "T1 end mill", ("tools", "drill"): "T2 drill"}
FACED = [
    op(10, "face", "deck", "mill", to_z=0.0),
    op(20, "face", "deck", "mill", to_z=0.0),
    op(30, "drill", "hole", "drill"),
]
UNKNOWN_NOTE = "touch the face outside its cut footprint (Ø ? mm)"


def with_rows(data, *updates):
    """The setup's sheet after each ``(path, fields)`` update of the zero_check numbers:
    ``path`` walks keys / list indexes to a row dict, or to a list the row is appended
    to, and ``fields`` are set on it."""
    finding = evaluate(data)[0]
    numbers = copy.deepcopy(finding.numbers)
    for path, fields in updates:
        row = numbers
        for step in path:
            row = row[step]
        if isinstance(row, list):
            row.append({})
            row = row[-1]
        row.update(fields)
    sheet = _Traveler(data, [dataclasses.replace(finding, numbers=numbers)], {}, {})
    return sheet, data.plan["setups"][0]


def axis_set_lines(html):
    return [line for line in paragraphs(html) if "Axis Set Z" in line]


# 11.2 cutter plus a 0.185 axis shift: 2 × (5.6 + 0.185) = 11.57, and one micron past
# the 0.001 mm grid must round outward (11.5701 → 11.571), never to nearest or inward.
# A sub-micron float excess (1.0000000001) and a value with more significant digits
# than a ``:g`` display keeps (1234.5608) round outward too, never back inward.
OUTWARD = [
    (11.57, "11.57"),
    (11.5701, "11.571"),
    (11.5709, "11.571"),
    (12, "12"),
    (1.0000000001, "1.001"),
    (1234.5608, "1234.561"),
    (0.0005, "0.001"),
]


@pytest.mark.parametrize(("dia", "printed"), OUTWARD)
def test_the_outward_diameter_is_an_exact_decimal_ceiling_on_the_micron_grid(dia, printed):
    assert _outward_mm(dia) == printed


def test_a_huge_or_long_integer_diameter_prints_every_digit_unchanged():
    assert _outward_mm(1e300) == "1" + "0" * 300
    largest = _outward_mm(1.7976931348623157e308)
    assert largest.startswith("17976931348623157") and "e" not in largest.lower()
    # More digits than a decimal context keeps: an integer is already on the grid.
    long_integer = 12345678901234567890123456789011
    assert _outward_mm(long_integer) == "12345678901234567890123456789011"
    assert _outward_mm(long_integer + 1) == "12345678901234567890123456789012"


@pytest.mark.parametrize(("dia", "printed"), OUTWARD)
def test_a_credited_z_zero_tells_the_operator_to_touch_outside_the_footprint(dia, printed):
    sheet, setup = with_rows(
        bundle("mill", mill_zero(DECK), OPS), (("axes", "z"), {"touch_exclusion_dia_mm": dia})
    )
    contact, axis_set = zero_rows(sheet.dro(setup, TOOLS))["Z"]
    assert f"touch the face outside Ø{printed} mm" in contact, contact
    assert axis_set == "10.050"
    assert not re.search(r"Ø(11\.569|11\.570|1\.000|1234\.56)\b", contact), contact


def test_an_x_or_y_contact_never_takes_the_z_touch_exclusion():
    sheet, setup = with_rows(
        bundle("mill", mill_zero(DECK), OPS), (("axes", "z"), {"touch_exclusion_dia_mm": 11.57})
    )
    rows = zero_rows(sheet.dro(setup, TOOLS))
    assert "touch the face outside Ø11.57 mm" in rows["Z"][0]
    assert "outside" not in rows["X"][0] and "outside" not in rows["Y"][0]


# Absent: no exclusion. Zero (the face was cut before any bounded axial plunge): nothing
# to keep off, so no circle is invented and no unknown is claimed.
@pytest.mark.parametrize("updates", [(), ((("axes", "z"), {"touch_exclusion_dia_mm": 0.0}),)])
def test_an_absent_or_zero_exclusion_prints_no_touch_constraint(updates):
    sheet, setup = with_rows(bundle("mill", mill_zero(DECK), OPS), *updates)
    html = sheet.dro(setup, TOOLS)
    assert "touch the face outside" not in sheet_text(html)
    assert "outside" not in zero_rows(html)["Z"][0] and "Ø ?" not in zero_rows(html)["Z"][0]


@pytest.mark.parametrize("dia", ["unknown", None, -3.0, float("nan"), True, "11.57", "0"])
def test_an_unknown_or_malformed_exclusion_never_prints_a_numeric_constraint(dia):
    sheet, setup = with_rows(
        bundle("mill", mill_zero(DECK), OPS), (("axes", "z"), {"touch_exclusion_dia_mm": dia})
    )
    contact = zero_rows(sheet.dro(setup, TOOLS))["Z"][0]
    assert UNKNOWN_NOTE in contact, contact
    assert not re.search(r"outside Ø\d", contact), contact
    assert "unknown" not in contact and "11.57" not in contact


def test_the_constraint_follows_the_produced_plane_with_its_raw_ref_escaped():
    hostile = "#7/ADVANCED_FACE[1]/<b>&P"
    sheet, setup = with_rows(
        bundle("mill", mill_zero(DECK), OPS),
        (("axes", "z"), {"credited_faces": [hostile], "touch_exclusion_dia_mm": 11.57}),
    )
    html = sheet.dro(setup, TOOLS)
    assert "<b>" not in html and "&lt;b&gt;&amp;P" in html
    contact = zero_rows(html)["Z"][0]
    assert f"produced plane: {hostile}; touch the face outside Ø11.57 mm" in contact, contact


def test_a_derived_touch_prints_the_constraint_after_its_axis_set_and_plane():
    sheet, setup = with_rows(
        bundle("mill", mill_zero(DECK), OPS),
        (("derived_touches", 0), {"credited_faces": [FACE], "touch_exclusion_dia_mm": 11.5701}),
    )
    (line,) = [line for line in paragraphs(sheet.dro(setup, TOOLS)) if "install" in line]
    expected = f"Axis Set Z 10.050; produced plane: {FACE}; touch the face outside Ø11.571 mm."
    assert expected in line, line


def test_an_explicit_tool_touch_prints_the_constraint_and_the_unconstrained_one_does_not():
    data = bundle("mill", mill_zero(DECK), OPS)
    derived = evaluate(data)[0].numbers["derived_touches"][0]
    explicit = {**derived, "touch_exclusion_dia_mm": 11.57}
    sheet, setup = with_rows(data, (("tool_touches",), explicit))
    lines = axis_set_lines(sheet.dro(setup, TOOLS))
    assert len(lines) == 2, lines
    constrained = [line for line in lines if "touch the face outside Ø11.57 mm." in line]
    assert len(constrained) == 1, lines
    assert any("outside" not in line for line in lines), lines


def test_a_listed_retouch_prints_the_constraint_and_an_unconstrained_one_does_not():
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    data = bundle("mill", zero, FACED, {"top_z": 2.0})
    listed = [row["op"] for row in evaluate(data)[0].numbers["retouch"]]
    row = ("retouch", listed.index(10))
    sheet, setup = with_rows(
        data, (row, {"credited_faces": [FACE], "touch_exclusion_dia_mm": 11.57})
    )
    lines = paragraphs(sheet.dro(setup, MILL_TOOLS))
    (first,) = [line for line in lines if re.search(r"\bAfter op 10\b", line)]
    (second,) = [line for line in lines if re.search(r"\bAfter op 20\b", line)]
    expected = f"Axis Set Z 0.050; produced plane: {FACE}; touch the face outside Ø11.57 mm."
    assert expected in first, first
    assert "Axis Set Z 0.050." in second and "outside" not in second, second


def test_a_retouch_with_an_unknown_exclusion_is_not_folded_into_a_numeric_one():
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    data = bundle("mill", zero, FACED, {"top_z": 2.0})
    listed = [row["op"] for row in evaluate(data)[0].numbers["retouch"]]
    sheet, setup = with_rows(
        data,
        (("retouch", listed.index(10)), {"touch_exclusion_dia_mm": 11.57}),
        (("retouch", listed.index(20)), {"touch_exclusion_dia_mm": "unknown"}),
    )
    lines = paragraphs(sheet.dro(setup, MILL_TOOLS))
    (first,) = [line for line in lines if re.search(r"\bAfter op 10\b", line)]
    (second,) = [line for line in lines if re.search(r"\bAfter op 20\b", line)]
    assert "Axis Set Z 0.050; touch the face outside Ø11.57 mm." in first, first
    assert f"Axis Set Z 0.050; {UNKNOWN_NOTE}." in second, second
    assert "11.57" not in second


# A carried AS-CUT face stands off this setup's 0.001 grid (21.0055); the rule
# already typed height plus paper on the safe-down grid and kept its nonnegative
# residual (``setting_residual_mm``). Print that report setting exactly, never
# round the physical surface up to 21.006 or move the setting a second time.
# Physical evidence retains every digit. Paper on top (+Z) and under (−Z) both.
EDGE = 21.0055
CARRIED = [
    ({"paper_mm": 0.05, "from": "+z"}, 21.055, 0.0005),
    ({"paper_mm": 0.05, "from": "-z"}, 20.955, 0.0005),
    ({"paper_mm": 0.0, "from": "+z"}, 21.005, 0.0005),
]
# Deliberately inconsistent rows exercise display fidelity, not rule acceptance.
ADVERSARIAL_CARRIED = [
    ({"paper_mm": 0.05, "from": "+z"}, 21.056, -0.0005),
    ({"paper_mm": 0.05, "from": "-z"}, 20.956, -0.0005),
]


@pytest.mark.parametrize(("touch", "axis_set", "residual"), CARRIED + ADVERSARIAL_CARRIED)
def test_a_carried_z_zero_prints_the_report_setting_and_the_physical_surface(
    touch, axis_set, residual
):
    data = bundle("mill", mill_zero({**DECK, **touch}), OPS)
    row = {
        "edge_mm": EDGE,
        "axis_set": axis_set,
        "setting_residual_mm": residual,
        "paper_mm": touch["paper_mm"],
    }
    sheet, setup = with_rows(data, (("axes", "z"), row))
    contact, printed = zero_rows(sheet.dro(setup, TOOLS))["Z"]
    assert printed == f"{axis_set:.3f}", (contact, printed)
    assert "surface at 21.0055" in contact, contact
    assert "21.006" not in contact and "21.01" not in contact, contact


def test_a_same_setup_z_zero_still_follows_the_surface_the_dro_shows():
    # Not carried: no ``setting_residual_mm``, so the surface and setting round up
    # together on this grid as before (the directional behavior is untouched).
    row = {"edge_mm": EDGE, "axis_set": 21.0555}
    sheet, setup = with_rows(bundle("mill", mill_zero(DECK), OPS), (("axes", "z"), row))
    contact, printed = zero_rows(sheet.dro(setup, TOOLS))["Z"]
    assert "surface at 21.006" in contact, contact
    assert printed == "21.056", printed


@pytest.mark.parametrize("kind", ["tool_touches", "derived_touches"])
@pytest.mark.parametrize(("touch", "axis_set", "residual"), CARRIED + ADVERSARIAL_CARRIED)
def test_a_carried_tool_touch_prints_the_report_setting_exactly(kind, touch, axis_set, residual):
    data = bundle("mill", mill_zero(DECK), OPS)
    derived = evaluate(data)[0].numbers["derived_touches"][0]
    row = {
        **derived,
        "edge_mm": EDGE,
        "z_axis_set": axis_set,
        "setting_residual_mm": residual,
        "paper_mm": touch["paper_mm"],
        "repeats": True,
    }
    path = ("tool_touches",) if kind == "tool_touches" else ("derived_touches", 0)
    sheet, setup = with_rows(data, (path, row))
    lines = axis_set_lines(sheet.dro(setup, TOOLS))
    (line,) = [line for line in lines if f"Axis Set Z {axis_set:.3f}." in line]
    assert "(Z 21.0055)" in line, line
    assert "21.006" not in line, line


@pytest.mark.parametrize(("touch", "axis_set", "residual"), CARRIED + ADVERSARIAL_CARRIED)
def test_a_carried_listed_retouch_prints_the_report_setting_exactly(touch, axis_set, residual):
    zero = mill_zero({"face": "top", "tool": "mill", **touch}, retouch_after=[10, 20])
    data = bundle("mill", zero, FACED, {"top_z": 2.0})
    listed = [row["op"] for row in evaluate(data)[0].numbers["retouch"]]
    row = {
        "top_z": EDGE,
        "paper_mm": touch["paper_mm"],
        "axis_set": axis_set,
        "setting_residual_mm": residual,
    }
    sheet, setup = with_rows(data, (("retouch", listed.index(10)), row))
    lines = paragraphs(sheet.dro(setup, MILL_TOOLS))
    (first,) = [line for line in lines if re.search(r"\bAfter op 10\b", line)]
    paper = f"{touch['paper_mm']:.3f}"
    assert f"(Z 21.0055) with {paper} paper → Axis Set Z {axis_set:.3f}." in first, first
    assert "21.006" not in first, first


def test_adversarial_carried_row_still_displays_report_not_renderer_rounding():
    # Presentation is not a second rule evaluator: even a forged negative residual
    # must not silently change the reported Axis Set or hide the physical evidence.
    sheet, setup = with_rows(
        bundle("mill", mill_zero(DECK), OPS),
        (("axes", "z"), {"edge_mm": EDGE, "axis_set": 21.056, "setting_residual_mm": -0.0005}),
    )
    contact, printed = zero_rows(sheet.dro(setup, TOOLS))["Z"]
    assert printed == "21.056"
    assert "surface at 21.0055" in contact


def test_non_grid_carried_touch_operations_consume_checked_typed_axis_set():
    # Synthetic report deliberately keeps raw/physical heights distinct from the
    # checked operative endpoints. The sheet must use the latter, not dro_z(raw).
    physical, typed = 21.0075, 21.005
    data = bundle("mill", mill_zero({**DECK, "paper_mm": 0.0}), OPS)
    data.inventory["machines"]["mill"]["resolution_mm"] = 0.005
    sheet, setup = with_rows(
        data,
        (
            ("axes", "z"),
            {"edge_mm": physical, "axis_set": typed, "setting_residual_mm": physical - typed},
        ),
    )
    spot, drill = setup["ops"]
    sheet.records["blind_depth", "hole"] = {
        "endpoints": [
            {
                "setup": setup["id"],
                "op": spot["op"],
                "entry_z": physical,
                "dro_entry_z": typed,
                "tip_z": physical - 2.0,
                "dro_tip_z": 19.005,
                "depth_mm": 2.0,
                "dro_depth_mm": 2.0,
                "depth_floor_mm": 2.0,
                "exit_face": "not_applicable",
            },
            {
                "setup": setup["id"],
                "op": drill["op"],
                "entry_z": physical,
                "dro_entry_z": typed,
                "exit_face": physical - 10.0,
                "dro_exit_face": 11.005,
                "tip_z": 10.505,
                "dro_tip_z": 10.505,
                "lead_mm": 0.0,
                "dro_exit_mm": 0.5,
            },
        ]
    }
    contact, printed = zero_rows(sheet.dro(setup, TOOLS))["Z"]
    assert printed == "21.005"
    assert "surface at 21.0075" in contact
    assert sheet.tip(setup, spot) == ["Z 21.005 → 19.005", "depth 2.000"]
    assert sheet.tip(setup, drill) == ["Z 21.005 → 10.505", "breaks through at 11.005"]
    assert sheet.tip_note(setup, drill) == (
        "Break through: the full diameter runs at least 0.500 past the exit face."
    )
