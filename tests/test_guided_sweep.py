"""Guided-sweep manual arcs (docs/plan.md "Manual arcs", issue #255).

An arc whose centre lies far off the part is swept under a locked cutter by a fixture
that holds the work to rotation about that centre: a swing arm on a pivot pin, or a sled
whose filed rail bears on two rollers in the T-slots. The cutter is touched to a named
master and X and Y are locked, so no handwheel moves while it cuts. The master's radius
limits, widened by how far the guide lets the centre move (pivot play, or the rail's
form error and roller runout through the rollers' geometry), must lie inside the band;
anything undeclared or unmeasured is debt, never a perfect guide.
"""

import dataclasses
import math
import re
import subprocess
from html import unescape

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise
from test_manual_arc import arcs, change, coordinates_row, debts, errors, op, scratch

from prechips.inputs import load_bundle
from prechips.kernel import build_job, table_checkpoints
from prechips.rules import coordinates
from prechips.rules.guided_sweep import roller_gain, swept_angles
from prechips.sheet import _Traveler

MEASURED = (
    "measured = { status = 'measured', by = 'synthetic test operator', "
    "date = '2026-10-05', instrument = 'test gauge' }"
)
# A concave R800 arc (the part below it, the cutter inside it) about model (20, 810), 21°
# long about its lowest point (20, 10): the drawing band R800.0 to R800.5.
HALF = math.radians(10.5)
END = [20.0 + 800.0 * math.sin(HALF), 810.0 - 800.0 * math.cos(HALF)]
LONG_ARC = (
    "kind = 'profile'\nrequirements = ['radius']\nradius = [800.0, 800.5]\n"
    f"radius_nominal = 800.0\narc_centre = [20.0, 810.0, 0.0]\nend = {END}\n"
)
GUIDES = (
    "[fixtures.arm]\nkind = 'swing_arm'\nname = 'R800 swing arm'\n"
    f"pivot_play_mm = {{ value = 0.02, {MEASURED} }}\nverify = false\n"
    "[fixtures.sled]\nkind = 'arc_sled'\nname = 'R850 arc sled'\nrail_radius_mm = 850.0\n"
    f"rail_form_error_mm = {{ value = 0.05, {MEASURED} }}\n"
    f"roller_runout_mm = {{ value = 0.01, {MEASURED} }}\nverify = false\n"
    "[gauges.bar]\nkind = 'setting_bar'\nname = 'R800 setting bar'\n"
    f"radius_limits_mm = {{ value = [800.10, 800.12], {MEASURED} }}\nverify = false\n"
    "[gauges.master]\nkind = 'master_arc'\nname = 'R800 master arc'\n"
    f"radius_limits_mm = {{ value = [800.20, 800.25], {MEASURED} }}\nverify = false\n"
)
SWING = [-160.0, -20.0, -10.0, 190.0, 20.0, 0.0]


def sweep_contour(guide="pivot", **more):
    fields = {
        "guide": f"'{guide}'",
        "fixture": "'arm'" if guide == "pivot" else "'sled'",
        "master": "'bar'" if guide == "pivot" else "'master'",
        "touch_axis": "'-Y'",
        "sweep_deg": "25.0",
    }
    if guide == "rail":
        fields.update(rollers_deg="[-15.0, 15.0]", rail_deg="[-40.0, 40.0]")
    fields.update({key: value for key, value in more.items() if value is not None})
    for key in [key for key, value in more.items() if value is None]:
        fields.pop(key)
    sweep = ", ".join(f"{key} = {value}" for key, value in fields.items())
    return f"{{ method = 'guided_sweep', step_deg = 1.0, sweep = {{ {sweep} }} }}"


def guided_plan(tmp_path, guide="pivot", *, allowance=None, hold=None, inventory="", **more):
    fixture = "arm" if guide == "pivot" else "sled"
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", sweep_contour(guide, **more), allowance=allowance),
        hold=hold or f"fixture = '{fixture}'",
        target=LONG_ARC,
    )
    path = plan.with_name("inventory.toml")
    path.write_text(path.read_text(encoding="utf-8") + GUIDES + inventory, encoding="utf-8")
    return plan


def guided_row(tmp_path, guide="pivot", **kwargs):
    return coordinates_row(guided_plan(tmp_path, guide, **kwargs), stock_bbox=SWING)


def recipe(row, stage="finish"):
    (table,) = [t for t in arcs(row, 20) if t["stage"] == stage]
    return table, table["guided"]


@pytest.mark.parametrize("guide", ["pivot", "rail"])
def test_a_guided_sweep_locks_the_cutter_and_moves_only_the_fixture(tmp_path, guide):
    row = guided_row(tmp_path, guide)
    assert row.status == "pass", row.sentence
    table, sweep = recipe(row)
    assert table["method"] == "guided_sweep"
    assert sweep["locked_axes"] == ["X", "Y"] and sweep["moves"] == "fixture"
    assert sweep["touch_axis"] == "-Y"
    # Concave: the cutter stands inside the arc on -Y and touches the master moving -Y.
    assert sweep["convex"] is False and sweep["touch_feed"] == "-Y"
    assert sweep["span_deg"] == pytest.approx(21.0)
    assert sweep["sweep_deg"] == 25.0
    # Two degrees of run past each end, at the R797 cutter-centre radius.
    assert sweep["overrun_mm"] == pytest.approx(math.radians(2.0) * 797.0)
    assert sweep["rotation"] in ("clockwise", "counterclockwise")
    assert sweep["back_off_mm"] == 0.0 and "back_off_dro" not in sweep
    cut, band = sweep["cut_radius_mm"], sweep["band_mm"]
    assert band == pytest.approx([800.0, 800.5])
    assert band[0] <= cut[0] <= cut[1] <= band[1]
    if guide == "pivot":
        # The bar's R800.10-800.12 widened by the beam's 0.02 pivot play.
        assert sweep["centre_error_mm"] == pytest.approx(0.02)
        assert cut == pytest.approx([800.08, 800.14])
    else:
        # Rollers at ±15°: each contact's 0.05 form error + 0.005 half runout, at the touch
        # and again at the cut, through a 1/cos 15° gain.
        gain = 1 / math.cos(math.radians(15.0))
        assert sweep["roller_gain"] == pytest.approx(gain)
        assert sweep["centre_error_mm"] == pytest.approx(2 * gain * 0.055)
    assert "inventory gauges." + sweep["master"] + ": touch-off master" in row.cite


def test_the_rows_span_the_whole_sweep_and_keep_the_arc_ends(tmp_path):
    row = guided_row(tmp_path)
    table, _ = recipe(row)
    angles = sorted(r["angle_deg"] for r in table["rows"])
    assert angles[0] == pytest.approx(-12.5) and angles[-1] == pytest.approx(12.5)
    assert any(abs(a + 10.5) < 1e-9 for a in angles) and any(abs(a - 10.5) < 1e-9 for a in angles)
    # Every row stands on the R797 cutter-centre circle about the arc centre.
    centre = table["centre_setup_xy"]
    for r in table["rows"]:
        assert math.dist(r["setup_xy"], centre) == pytest.approx(797.0)


def test_swept_angles_extend_both_ends_by_half_the_excess():
    assert swept_angles(-10.0, 10.0, 5.0, 20.0, False) == [-10.0, -5.0, 0.0, 5.0, 10.0]
    assert swept_angles(10.0, -10.0, 5.0, 30.0, False) == [
        15.0,
        10.0,
        5.0,
        0.0,
        -5.0,
        -10.0,
        -15.0,
    ]
    assert swept_angles(0.0, 360.0, 90.0, 400.0, True) == [0.0, 90.0, 180.0, 270.0, 360.0]


@pytest.mark.parametrize(
    ("rollers", "gain"),
    [((-15.0, 15.0), 1 / math.cos(math.radians(15.0))), ((-90.0, 90.0), None)],
)
def test_roller_gain_is_the_worst_case_cut_shift_per_contact_error(rollers, gain):
    found = roller_gain(rollers)
    assert found == (None if gain is None else pytest.approx(gain))


@pytest.mark.parametrize(
    ("more", "status", "message"),
    [
        ({"sweep_deg": "20.0"}, "error", "the 20° sweep stops short of the arc"),
        ({"fixture": "'sled'"}, "error", "is a arc_sled, not the swing_arm"),
        ({"master": "'cutter'"}, "unknown", "is not in the gauges inventory"),
        ({"master": "'radius-gauge'"}, "error", "is a radius_gauge, not a setting_bar"),
        ({"guide": "unknown"}, "unknown", "contour.sweep.guide is neither pivot nor rail"),
        ({"touch_axis": None}, "unknown", "contour.sweep.touch_axis"),
        ({"sweep_deg": None}, "unknown", "contour.sweep.sweep_deg is unknown"),
    ],
    ids=[
        "short-sweep",
        "wrong-fixture",
        "not-a-gauge",
        "range-gauge",
        "no-guide",
        "no-axis",
        "no-sweep",
    ],
)
def test_a_pivot_sweep_that_cannot_cut_the_arc_is_an_error_or_debt(tmp_path, more, status, message):
    row = guided_row(tmp_path, **more)
    assert row.status == status, row.sentence
    assert message in (errors(row) if status == "error" else debts(row))


def test_a_sweep_that_reaches_the_arc_ends_within_a_dro_step_needs_no_overrun(tmp_path):
    # The arc spans exactly 21°; a sweep a hair over one DRO step's angle short of that is
    # short, one within it reaches the ends.
    step = math.degrees(0.001 / 797.0)
    short = guided_row(tmp_path / "short", sweep_deg=f"{21.0 - 1.5 * step!r}")
    assert short.status == "error" and "needs 21.0000°" in errors(short)
    exact = guided_row(tmp_path / "exact", sweep_deg=f"{21.0 - 0.5 * step!r}")
    assert exact.status == "pass", exact.sentence
    _, sweep = recipe(exact)
    assert sweep["overrun_mm"] == 0.0


def test_a_master_on_the_swing_arm_moves_with_its_play_at_the_touch_and_the_cut(tmp_path):
    # A setting bar seated on the pin is set from the pin's own axis: the play counts once.
    # A master arc pinned on the arm moves with the beam at the touch-off too: twice.
    row = guided_row(tmp_path, master="'master'")
    assert row.status == "pass", row.sentence
    _, sweep = recipe(row)
    assert sweep["master_kind"] == "master_arc"
    assert sweep["centre_error_mm"] == pytest.approx(0.04)
    assert sweep["cut_radius_mm"] == pytest.approx([800.16, 800.29])


def test_the_guide_fixture_must_carry_the_work(tmp_path):
    row = guided_row(tmp_path, hold="fixture = 'unknown'")
    assert row.status == "error"
    assert "does not carry the work" in errors(row)


def test_a_setting_bar_cannot_set_a_rail_sweep(tmp_path):
    row = guided_row(tmp_path, "rail", master="'bar'")
    assert row.status == "error"
    assert "seats on a pivot pin" in errors(row)


def test_rollers_on_one_line_through_the_centre_leave_the_sled_free(tmp_path):
    row = guided_row(tmp_path, "rail", rollers_deg="[-90.0, 90.0]")
    assert row.status == "error"
    assert "free to slide" in errors(row)


def test_a_roller_that_runs_off_the_rail_during_the_sweep_is_an_error(tmp_path):
    # The rail reaches 20° past the cutter line each way; a 25° sweep carries its end 12.5°
    # toward a roller at 15°.
    row = guided_row(tmp_path, "rail", rail_deg="[-20.0, 20.0]")
    assert row.status == "error"
    assert "runs off the rail" in errors(row)


def test_the_rail_form_error_is_carried_into_the_band(tmp_path):
    # A 0.2 rail: 2 x 1.035 x 0.205 = 0.42 either way of R800.20-800.25 leaves the band.
    worn = f"rail_form_error_mm = {{ value = 0.2, {MEASURED} }}"
    plan = guided_plan(tmp_path, "rail")
    change(
        plan.with_name("inventory.toml"),
        f"rail_form_error_mm = {{ value = 0.05, {MEASURED} }}",
        worn,
    )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "error", row.sentence
    assert "centre error" in errors(row) and "outside the R800 to R800.5 mm band" in errors(row)


@pytest.mark.parametrize(
    "fact",
    [
        "rail_form_error_mm = 0.05",
        "rail_form_error_mm = { value = 0.05, measured = { status = 'assumed', by = 'x', "
        "date = '2026-10-05', instrument = 'y' } }",
        "",
    ],
    ids=["bare-nominal", "assumed", "undeclared"],
)
def test_an_unmeasured_or_undeclared_rail_form_error_is_debt_never_a_perfect_rail(tmp_path, fact):
    plan = guided_plan(tmp_path, "rail")
    change(
        plan.with_name("inventory.toml"),
        f"rail_form_error_mm = {{ value = 0.05, {MEASURED} }}\n",
        fact + "\n" if fact else "",
    )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "unknown", row.sentence
    assert "rail form error of sled is unknown or not measured" in debts(row)
    entries = {entry["id"]: entry for entry in row.numbers["measurements"]}
    entry = entries["fixtures.sled.rail_form_error"]
    assert entry["instruction"].startswith("measure: sled arc sled rail form error")
    _, sweep = recipe(row)
    assert sweep["centre_error_mm"] == "unknown" and sweep["cut_radius_mm"] == "unknown"


def test_an_unmeasured_master_or_pivot_play_is_debt(tmp_path):
    plan = guided_plan(tmp_path)
    inventory = plan.with_name("inventory.toml")
    change(inventory, f"pivot_play_mm = {{ value = 0.02, {MEASURED} }}", "pivot_play_mm = 0.02")
    change(
        inventory,
        f"radius_limits_mm = {{ value = [800.10, 800.12], {MEASURED} }}",
        "radius_limits_mm = { value = [800.10, 800.12], verify = true }",
    )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "unknown", row.sentence
    ids = {entry["id"] for entry in row.numbers["measurements"]}
    assert {"fixtures.arm.pivot_play", "gauges.bar.radius_limits"} <= ids


def test_a_guide_flagged_to_verify_proves_no_cut(tmp_path):
    plan = guided_plan(tmp_path)
    change(
        plan.with_name("inventory.toml"),
        "verify = false\n[fixtures.sled]",
        "verify = true\n[fixtures.sled]",
    )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "unknown", row.sentence
    assert "the sweep fixture arm is flagged to verify" in debts(row)
    _, sweep = recipe(row)
    assert sweep["cut_radius_mm"] == "unknown"
    assert "fixtures.arm.pivot_play" in {e["id"] for e in row.numbers["measurements"]}


@pytest.mark.parametrize(
    ("leave", "back", "dro"),
    [(0.3, 0.3, 0.3), (0.0003, 0.001, 0.001)],
    ids=["on-grid", "rounded-off-the-line"],
)
def test_a_rough_sweep_backs_off_the_touch_on_one_axis(tmp_path, leave, back, dro):
    row = guided_row(tmp_path, allowance=leave)
    assert row.status == "pass", row.sentence
    _, rough = recipe(row, "rough")
    _, finish = recipe(row, "finish")
    assert finish["back_off_mm"] == 0.0
    # Concave on -Y: off the line is toward the centre, +Y from the touch.
    assert rough["back_off_mm"] == pytest.approx(back)
    assert rough["back_off_dro"] == pytest.approx(dro)
    assert rough["band_mm"] == pytest.approx([800.0 - leave, 800.5 - leave])


def test_a_negative_leave_prints_no_sweep(tmp_path):
    row = guided_row(tmp_path, allowance=-0.2)
    assert row.status == "error"
    assert not arcs(row, 20)


def test_the_kernel_job_carries_the_swept_rows_as_checkpoints(tmp_path):
    # The kernel sweeps the cutter along the rows (in the work's frame, the fixture's
    # swing) and stands it at each: the arc ends and the run past them are judged too.
    bundle = load_bundle(guided_plan(tmp_path))
    (kernel_op,) = (
        op
        for setup in build_job(bundle)["setups"]
        for op in setup["ops"]
        if op["subject"] == "S1:20"
    )
    assert kernel_op["tool_paths"]["tables"] is True
    (path,) = kernel_op["checkpoints"]["paths"]
    assert path["method"] == "guided_sweep"
    (table,) = coordinates.evaluate(bundle, pre_kernel=True)[0].numbers["arc_table"]
    flat = [v for row in table["rows"] for v in row["dro_xy"]]
    assert [v for point in path["xy_mm"] for v in point] == pytest.approx(flat)


def traveler_text(tmp_path, guide="pivot", **kwargs):
    plan = guided_plan(tmp_path, guide, **kwargs)
    kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": SWING}}}
    bundle = dataclasses.replace(load_bundle(plan), kernel=kernel)
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    tools = {("tools", "cutter"): "6 mm endmill"}
    html = _Traveler(bundle, [row], {}, None).contours(bundle.plan["setups"][0], tools)
    return row, " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


@pytest.mark.parametrize("guide", ["pivot", "rail"])
def test_the_traveler_prints_the_touch_off_and_the_sweep_not_a_dro_table(tmp_path, guide):
    row, printed = traveler_text(tmp_path, guide)
    assert row.status == "pass", row.sentence
    assert "Lock X and Y" in printed
    assert "touch" in printed.lower()
    assert "sweep" in printed.lower()
    assert "25°" in printed
    # No cutter-centre DRO table: no row coordinates are printed for the sweep.
    assert "handwheel axis" not in printed and "hole #" not in printed
    if guide == "rail":
        assert "rollers" in printed and "form error" in printed


def test_a_rough_then_finish_sweep_touches_off_once_and_returns_to_the_touch(tmp_path):
    row, printed = traveler_text(tmp_path, allowance=0.3)
    assert row.status == "pass", row.sentence
    assert printed.count("Spindle stopped: bring a flute") == 1
    rough, finish = printed.split("Finish sweep:")
    assert "Rough sweep: unlock Y only, move it +0.300 from the touch reading" in rough
    assert "return it to the touch reading" in finish
    # The touch is written down, never zeroed: the setup's DRO zero stays for its other ops.
    assert "set DRO" not in printed and "reading at the touch here" in printed
    # Each stage keeps X and Y locked while the arm sweeps.
    assert rough.count("With X and Y locked") == 1 and finish.count("With X and Y locked") == 1


def test_a_sweep_whose_cut_is_unproven_prints_a_stop(tmp_path):
    row, printed = traveler_text(tmp_path, "rail", rollers_deg=None)
    assert row.status == "unknown"
    assert "STOP" in printed


# The kernel, on authored plates under the rocker's concave R800 top edge about (0, 816)
# from X-145.24 to X+145.24. ``open`` ends drop straight to Y0 (the sweep's run past the
# ends is in air); ``walled`` ends rise to tips (test_kernel_rocker_regression), so the
# cutter's run past the arc's ends stands in the tip walls.
_PLATES = r"""
import math
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
end = 816 - math.sqrt(800**2 - 145.24**2)
arc = Part.Arc(V(145.24, end, 0), V(0, 16, 0), V(-145.24, end, 0)).toShape()
open_ = Part.Wire([
    Part.LineSegment(V(-145.24, 0, 0), V(145.24, 0, 0)).toShape(),
    Part.LineSegment(V(145.24, 0, 0), V(145.24, end, 0)).toShape(),
    arc,
    Part.LineSegment(V(-145.24, end, 0), V(-145.24, 0, 0)).toShape(),
])
walled = Part.Wire([
    Part.LineSegment(V(-155, 0, 0), V(155, 0, 0)).toShape(),
    Part.LineSegment(V(155, 0, 0), V(155, 40, 0)).toShape(),
    Part.LineSegment(V(155, 40, 0), V(145.24, 40, 0)).toShape(),
    Part.LineSegment(V(145.24, 40, 0), V(145.24, end, 0)).toShape(),
    arc,
    Part.LineSegment(V(-145.24, end, 0), V(-145.24, 40, 0)).toShape(),
    Part.LineSegment(V(-145.24, 40, 0), V(-155, 40, 0)).toShape(),
    Part.LineSegment(V(-155, 40, 0), V(-155, 0, 0)).toShape(),
])
for name, wire in (("open", open_), ("walled", walled)):
    plate = Part.Face(wire).extrude(V(0, 0, 5))
    assert plate.isValid() and len(plate.Solids) == 1
    plate.exportStep(out + "/" + name + ".step")
"""
PLATE_BLANK = {
    "shape": "box",
    "origin_mm": [-160.0, -5.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 320.0,
    "section_mm": [50.0, 5.0],
}
TOP_EDGE = (
    "kind = 'profile'\nrequirements = ['radius']\nradius = [799.49, 800.51]\n"
    "radius_nominal = 800.0\narc_centre = [0.0, 816.0, 0.0]\n"
    f"end = [145.24, {816 - math.sqrt(800**2 - 145.24**2)}]\n"
)


@pytest.fixture(scope="module")
def plates(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("guided-sweep-plates")
    script = directory / "author.py"
    script.write_text(_PLATES, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    found = {name: directory / f"{name}.step" for name in ("open", "walled")}
    assert all(p.is_file() for p in found.values()), process.stdout[-2000:] + process.stderr
    return found


def swept_checkpoints(tmp_path, sweep_deg):
    """The guided sweep's printed rows as build_job hands them to the kernel: a finish of
    the top edge to Z 1 with a 6 mm cutter, its setup frame on the model's."""
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", sweep_contour(sweep_deg=sweep_deg)),
        origin="[0.0, 0.0, 0.0]",
        hold="fixture = 'arm'",
        target=TOP_EDGE,
    )
    path = plan.with_name("inventory.toml")
    path.write_text(path.read_text(encoding="utf-8") + GUIDES, encoding="utf-8")
    change(plan, "to_z = -1.0", "to_z = 1.0")
    bundle = load_bundle(plan)
    row = next(r for r in coordinates.evaluate(bundle, pre_kernel=True) if r.subject == "S1")
    (table,) = row.numbers["arc_table"]
    return table, table_checkpoints("S1:20", row.numbers, 20, "mm")


def sweep_run(tmp_path, freecad_kernel, step, sweep_deg):
    table, checkpoints = swept_checkpoints(tmp_path / "plan", sweep_deg)
    engine = Engine(tmp_path, freecad_kernel)
    edge = engine.refs(step, (-145.25, 15.9, 0), (145.25, 29.4, 5.0), kind="Cylinder")
    assert len(edge) == 1
    finish = {
        **_op("S1:20", "edge", 3.0, 25.0, 30.0),
        "do": "finish_profile",
        "to_z": 1.0,
        "checkpoints": checkpoints,
    }
    hold = _vise(5.0, centre=0.0)
    setups = [_setup([finish], hold, setup_id="S1"), _setup([], hold, setup_id="S2")]
    result = engine.run(engine.job(step, {"edge": edge}, setups, stock=PLATE_BLANK))
    assert result["status"] == "ok", result.get("reason")
    return table, result


def test_the_kernel_clears_the_swept_arc_and_judges_the_run_past_its_ends(
    tmp_path, freecad_kernel, plates
):
    # 25° of sweep over the ~20.9° arc: the cutter runs ~29 mm past each end, in air past
    # the open plate's ends. Its corridor and swept rows clear the edge, so the setup's
    # stock is derived (no overstock on the claimed wall), and no row meets the part.
    table, result = sweep_run(tmp_path, freecad_kernel, plates["open"], 25.0)
    assert table["guided"]["overrun_mm"] > 25.0
    facts = result["ops"]["S1:20"]
    assert facts["claimed_indices"] and not facts["claim_errors"], facts
    assert facts["checkpoint_errors"] == [], facts["checkpoint_errors"]
    assert "stock_reason" not in result["setups"]["S2"], result["setups"]["S2"]


def test_the_kernel_finds_a_sweep_that_runs_into_finished_material(
    tmp_path, freecad_kernel, plates
):
    # The same sweep on the walled plate: the rows past the arc's ends stand in the tip
    # walls. The rule cannot see the walls; the kernel names those rows as hits.
    _, result = sweep_run(tmp_path, freecad_kernel, plates["walled"], 25.0)
    errors = result["ops"]["S1:20"]["checkpoint_errors"]
    assert errors and {error["obstacle"] for error in errors} == {"finished part"}, errors
