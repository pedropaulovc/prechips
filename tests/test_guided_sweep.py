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
from test_manual_arc import ARC, arcs, change, coordinates_row, debts, errors, op, scratch

from prechips.inputs import load_bundle
from prechips.kernel import build_job, table_checkpoints
from prechips.rules import coordinates
from prechips.rules.guided_sweep import rail_cut_shift, roller_gain, swept_angles
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


def guided_plan(
    tmp_path,
    guide="pivot",
    *,
    allowance=None,
    hold=None,
    inventory="",
    target=LONG_ARC,
    doc=None,
    **more,
):
    fixture = "arm" if guide == "pivot" else "sled"
    stepped = {} if doc is None else {"doc_mm": doc}
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", sweep_contour(guide, **more), allowance=allowance, **stepped),
        hold=hold or f"fixture = '{fixture}'",
        target=target,
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
        # The bar's R800.10-800.12 widened by the beam's 0.02 pivot play, plus the
        # cutter's own second-order term at R797: 0.02² / (2 × 796.98).
        assert sweep["centre_error_mm"] == pytest.approx(0.02 + 0.02**2 / (2 * 796.98))
        assert cut == pytest.approx([800.08, 800.14])
    else:
        # Rollers at ±15°: each contact's 0.05 form error + 0.005 half runout, at the touch
        # and again at the cut, through a 1/cos 15° gain, plus the finite-geometry terms:
        # never below the linear bound, and only a hair above it at R850.
        gain = 1 / math.cos(math.radians(15.0))
        assert sweep["roller_gain"] == pytest.approx(gain)
        linear = 2 * gain * 0.055
        assert linear < sweep["centre_error_mm"] < linear + 1e-3
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
        ({"sweep_deg": "360.0"}, "error", "the 360° sweep is a full turn or more"),
    ],
    ids=[
        "short-sweep",
        "wrong-fixture",
        "not-a-gauge",
        "range-gauge",
        "no-guide",
        "no-axis",
        "no-sweep",
        "full-turn",
    ],
)
def test_a_pivot_sweep_that_cannot_cut_the_arc_is_an_error_or_debt(tmp_path, more, status, message):
    row = guided_row(tmp_path, **more)
    assert row.status == status, row.sentence
    assert message in (errors(row) if status == "error" else debts(row))


@pytest.mark.parametrize("case", ["opposite-side", "rotated-frame"])
def test_a_touch_axis_off_the_cutters_radial_line_is_an_error(tmp_path, case):
    # The setup frame is the work at the sweep's middle pose: the touch axis must run from
    # the arc centre to the arc's middle, else the touch and back-off are not radial.
    if case == "opposite-side":
        plan = guided_plan(tmp_path, touch_axis="'+Y'")
    else:
        plan = guided_plan(tmp_path)
        c, s = math.cos(math.radians(5.0)), math.sin(math.radians(5.0))
        change(
            plan.with_name("features.toml"),
            "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]",
            f"x = [{c}, {s}, 0.0]\ny = [{-s}, {c}, 0.0]",
        )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "error", row.sentence
    assert "touch_axis must be the setup axis from the arc centre" in errors(row)


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


def test_a_full_circle_cannot_be_swept_between_two_stops(tmp_path):
    # A full circle starts and ends at one fixture pose: no pair of stop blocks bounds the
    # sweep, so the rule rejects it and the traveler prints nothing to run.
    row, printed = traveler_text(tmp_path, target=ARC, sweep_deg="360.0")
    assert row.status == "error", row.sentence
    assert "a guided sweep cannot cut a full circle" in errors(row)
    assert "Lock X and Y" not in printed and "stop block" not in printed


# A convex R10 upper semicircle about model (20, 10), 0° to 180°: its middle is +Y of the
# centre, and the R10 setting bar sets a cut inside its band.
SEMICIRCLE = (
    "kind = 'profile'\nrequirements = ['radius']\nradius = [9.9, 10.1]\n"
    "radius_nominal = 10.0\narc_centre = [20.0, 10.0, 0.0]\narc = 'upper_semicircle'\n"
)
BAR10 = (
    "[gauges.bar10]\nkind = 'setting_bar'\nname = 'R10 setting bar'\n"
    f"radius_limits_mm = {{ value = [10.00, 10.02], {MEASURED} }}\nverify = false\n"
)


def semicircle_row(tmp_path, step, direction="conventional"):
    plan = guided_plan(
        tmp_path,
        target=SEMICIRCLE,
        inventory=BAR10,
        master="'bar10'",
        touch_axis="'+Y'",
        sweep_deg="180.0",
    )
    change(plan, "step_deg = 1.0", f"step_deg = {step}")
    change(plan, "direction = 'conventional'", f"direction = '{direction}'")
    return coordinates_row(plan, stock_bbox=SWING)


def test_rows_under_half_a_turn_apart_keep_the_sweep_direction(tmp_path):
    # Rows just under a half turn apart still show which way the cutter goes between
    # them: the turn follows the cutting order, as with fine rows.
    def rotation(name, step, direction):
        _, sweep = recipe(semicircle_row(tmp_path / name, step, direction))
        return sweep["rotation"]

    fine = rotation("fine", 1.0, "conventional")
    assert fine in ("clockwise", "counterclockwise")
    assert rotation("fine-climb", 1.0, "climb") != fine
    assert rotation("coarse", 179.0, "conventional") == fine
    assert rotation("coarse-climb", 179.0, "climb") != fine


@pytest.mark.parametrize("step", [180.0, 200.0])
def test_rows_half_a_turn_or_more_apart_are_an_error(tmp_path, step):
    # The chord between rows half a turn or more apart reads as the short way round: the
    # rows' order and the fixture's turn cannot be told from it.
    row = semicircle_row(tmp_path, step)
    assert row.status == "error", row.sentence
    assert f"step_deg {step:g}° puts rows half a turn or more apart" in errors(row)


def test_a_master_on_the_swing_arm_moves_with_its_play_at_the_touch_and_the_cut(tmp_path):
    # A setting bar seated on the pin is set from the pin's own axis: the play counts once.
    # A master arc pinned on the arm moves with the beam at the touch-off too: twice.
    row = guided_row(tmp_path, master="'master'")
    assert row.status == "pass", row.sentence
    _, sweep = recipe(row)
    assert sweep["master_kind"] == "master_arc"
    assert sweep["centre_error_mm"] == pytest.approx(2 * (0.02 + 0.02**2 / (2 * 796.98)))
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


def test_a_rail_across_the_half_turn_line_carries_its_rollers(tmp_path):
    # Ends at 160° and -160° are the 40° rail through 180°, behind the arc centre: rollers
    # at ±175° stay on it through the 25° sweep, one at 150° runs off. Ends half a turn
    # apart leave the rail's side unknown.
    behind = guided_row(
        tmp_path / "behind", "rail", rail_deg="[160.0, -160.0]", rollers_deg="[175.0, -175.0]"
    )
    assert "runs off the rail" not in errors(behind)
    off = guided_row(
        tmp_path / "off", "rail", rail_deg="[160.0, -160.0]", rollers_deg="[150.0, -175.0]"
    )
    assert "the roller at 150° runs off the rail" in errors(off)
    assert "the roller at -175°" not in errors(off)
    half, printed = traveler_text(tmp_path / "half", "rail", rail_deg="[-90.0, 90.0]")
    assert "are half a turn apart" in debts(half)
    # Numeric ends are not proof the rollers bear on the rail: nothing runnable prints.
    assert "rollers not proven on the rail through the sweep) — do not run." in printed
    assert "Lock X and Y" not in printed


def test_a_guided_sweep_takes_a_setup_of_its_own(tmp_path):
    # The fixture turns the work off the setup frame, and nothing holds it at that pose for
    # another spindle op, before the sweep or after it.
    plan = guided_plan(tmp_path)
    drill = op(30, "drill", feature="bore", tool="bore-drill")
    plan.write_text(plan.read_text(encoding="utf-8") + drill, encoding="utf-8")
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "error", row.sentence
    assert "also runs spindle op 30" in errors(row)
    assert "give the guided sweep a setup of its own" in errors(row)


def test_the_rows_stay_on_the_nominal_path_the_kernel_checks(tmp_path):
    # An R810 master in a permitted R800 to R820 band cuts R810 (the band check proves it),
    # while the kernel checks the nominal R797 cutter-centre path against the nominal part:
    # moved to the master's radius, any in-band master past nominal would be a part hit.
    target = LONG_ARC.replace("radius = [800.0, 800.5]", "radius = [800.0, 820.0]")
    master = (
        "[gauges.r810]\nkind = 'setting_bar'\nname = 'R810 setting bar'\n"
        f"radius_limits_mm = {{ value = [810.0, 810.02], {MEASURED} }}\nverify = false\n"
    )
    plan = guided_plan(tmp_path, target=target, master="'r810'", inventory=master)
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "pass", row.sentence
    table, sweep = recipe(row)
    assert sweep["cut_radius_mm"] == pytest.approx([809.98, 810.04])
    for r in table["rows"]:
        assert math.dist(r["setup_xy"], table["centre_setup_xy"]) == pytest.approx(797.0)


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


def traveler_text(tmp_path, guide="pivot", drop="", box=SWING, **kwargs):
    plan = guided_plan(tmp_path, guide, **kwargs)
    if drop:
        change(plan.with_name("inventory.toml"), drop, "")
    kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": box}}}
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
    # No cutter-centre DRO table: no row coordinates are printed for the sweep, and the
    # heading says the work moves, not the cutter.
    assert "handwheel axis" not in printed and "hole #" not in printed
    assert "guided sweep: X / Y locked, the fixture moves the work" in printed
    assert "cutter-centre X / Y" not in printed
    # The touch sets the radius anywhere on the master, which is then taken off the path;
    # stops at the arc's ends bound the sweep, and the spindle starts only then.
    assert "X needs no setting" in printed
    lift = "remove the setting bar" if guide == "pivot" else "lift R800 master arc off its pins"
    assert lift in printed and "nothing of it may stay in the sweep's path" in printed
    assert "Set the sweep's stops" in printed and "clamp a stop block" in printed
    # The stop landmark is on the cutter's path: its edge at the arc's end, its centre a
    # cutter radius off the arc (R797 on this concave R800), then the overrun along it.
    assert "cutter's edge reaches the arc's end at X" in printed
    assert "(its centre at X" in printed
    assert "measured with a steel rule along the cutter's path, outward" in printed
    assert "of cutter travel beyond the arc's ends on purpose" in printed
    assert "must pass clear of every clamp" in printed
    assert "start the spindle clockwise" in printed
    if guide == "rail":
        # The form error is carried in the rule's cut radius, not narrated to the operator.
        assert "rollers fixed in the T-slots at -15° and 15°" in printed
        assert "form error" not in printed
        assert "set the rollers so each bears on the rail about X" in printed


def test_the_sweep_names_its_stops_at_the_arc_ends_and_the_rollers_from_the_spindle(tmp_path):
    row = guided_row(tmp_path, "rail")
    table, sweep = recipe(row)
    centre = table["centre_setup_xy"]
    # The arc's ends on the work, the sweep's start end first.
    first, last = sweep["ends_setup_xy"]
    assert math.dist(first, centre) == pytest.approx(800.0)
    assert math.dist(last, centre) == pytest.approx(800.0)
    assert math.dist(first, table["rows"][0]["setup_xy"]) < math.dist(
        last, table["rows"][0]["setup_xy"]
    )
    # Each stop's landmark is the cutter's centre on that end's radial line, on its own
    # R797 path: the arc's end a cutter radius beyond it.
    for wall, cutter in zip(sweep["ends_setup_xy"], sweep["ends_cutter_setup_xy"], strict=True):
        assert math.dist(cutter, centre) == pytest.approx(797.0)
        assert math.dist(cutter, wall) == pytest.approx(3.0)
    # Rollers at ±15° bear on the R850 rail 850 sin 15° either side of the spindle along X
    # and 850 cos 15° - 797 beyond it along -Y (the cutter's radial side).
    contacts = sorted(sweep["roller_contacts_mm"])
    reach = 850.0 * math.cos(math.radians(15.0)) - 797.0
    along = 850.0 * math.sin(math.radians(15.0))
    assert contacts[0] == pytest.approx([-along, -reach])
    assert contacts[1] == pytest.approx([along, -reach])


def proven(guide="pivot"):
    """A guided-sweep table whose every printed fact the coordinates rule established."""
    sweep = {
        "guide": guide,
        "fixture_name": "R800 swing arm",
        "master_name": "R800 setting bar",
        "master_kind": "setting_bar",
        "pivot_play_mm": 0.02,
        "touch_axis": "-Y",
        "touch_feed": "-Y",
        "rotation": "counterclockwise",
        "cut_radius_mm": [800.08, 800.14],
        "back_off_mm": 0.0,
        "start": "air",
        "sweep_deg": 25.0,
        "path_mm": 120.0,
        "overrun_mm": 10.0,
        "ends_setup_xy": [[-146.0, -3.0], [146.0, -3.0]],
        "ends_cutter_setup_xy": [[-145.5, 0.0], [145.5, 0.0]],
    }
    if guide == "rail":
        del sweep["pivot_play_mm"]
        sweep.update(
            fixture_name="R850 arc sled",
            master_name="R800 master arc",
            master_kind="master_arc",
            rollers_deg=[-15.0, 15.0],
            rail_deg=[-40.0, 40.0],
            rail_radius_mm=850.0,
            rail_coverage="proven",
            roller_contacts_mm=[[-220.0, 50.0], [220.0, 50.0]],
        )
    return {"stage": "finish", "spindle_rotation": "cw", "dro_tip_z": -1.0, "guided": sweep}


def printed_steps(arc, operative=str, **kwargs):
    from prechips.sheet_sweep import steps

    return " ".join(steps(arc, operative, "P1", "P3", **kwargs))


def test_the_sweep_is_paced_from_the_ops_feed():
    printed = printed_steps(proven(), feed=60.0)
    assert "at about the op's 60 mm/min feed: 120 s from stop to stop" in printed
    assert "to the other stop (P3)" in printed


SWEEP_FACTS = [
    "guide",
    "fixture_name",
    "master_name",
    "master_kind",
    "cut_radius_mm",
    "touch_axis",
    "touch_feed",
    "back_off_mm",
    "rotation",
    "sweep_deg",
    "path_mm",
    "overrun_mm",
    "ends_setup_xy",
    "ends_cutter_setup_xy",
    "start",
]


@pytest.mark.parametrize(
    ("guide", "where", "key"),
    [("pivot", "guided", key) for key in [*SWEEP_FACTS, "pivot_play_mm"]]
    + [
        ("rail", "guided", key)
        for key in [*SWEEP_FACTS, "rollers_deg", "rail_deg", "rail_radius_mm", "rail_coverage"]
        + ["roller_contacts_mm"]
    ]
    + [("pivot", "arc", "dro_tip_z"), ("pivot", "arc", "spindle_rotation")],
)
def test_every_unknown_fact_the_recipe_prints_stops_it(guide, where, key):
    # Unknown is never a pass: each value the printed recipe reads, made unknown on an
    # otherwise proven sweep, leaves only a STOP, never a runnable touch, lock or sweep.
    arc = proven(guide)
    assert "Lock X and Y" in printed_steps(arc)
    record = arc if where == "arc" else arc["guided"]
    record[key] = "unknown"
    printed = printed_steps(arc)
    assert printed.startswith("STOP: guided sweep not established ("), printed
    assert "Lock X and Y" not in printed and "stop block" not in printed


def test_a_rough_back_off_without_its_dro_reading_stops_the_recipe():
    arc = proven()
    arc["guided"].update(back_off_mm=0.3, back_off_dro=0.3)
    assert "Rough sweep: unlock Y only, move it +0.3" in printed_steps(arc)
    del arc["guided"]["back_off_dro"]
    assert printed_steps(arc).startswith("STOP: guided sweep not established (rough back-off")


def test_a_stepped_op_sweeps_once_per_level_top_first():
    # An op stepping down in axial levels never sweeps straight to the full depth: it sets
    # the top level, returns to the first stop for each further level, and stops the
    # spindle only after the last.
    printed = printed_steps(proven(), levels=[-0.5, -1.0])
    assert "set Z -0.5." in printed and "set Z -1.0." not in printed
    assert "set the next Z in the heading" in printed and "down to Z -1.0." in printed
    assert printed.rstrip().endswith(
        "After the last level, raise Z until the cutter clears the work and the arm, then "
        "stop the spindle and wait for it to stop."
    )
    stopped = printed_steps(proven(), levels="unknown")
    assert stopped.startswith("STOP: guided sweep not established (cut depth Z unknown)")


def test_the_traveler_sweeps_a_stepped_op_at_each_level_in_its_heading(tmp_path):
    row, printed = traveler_text(tmp_path, doc="0.5")
    (entry,) = [e for e in row.numbers["operations"] if str(e.get("op")) == "20"]
    levels = entry["z_levels"]["levels"]
    assert len(levels) == 2, levels
    top, bottom = (f"{z:.3f}" for z in levels)
    assert "2 depth levels: run the complete path below at each Z in the heading" in printed
    # Numbers print in their own spans: stripped, a space can stand before the stop.
    assert f"set Z {top} " in printed and f"down to Z {bottom} " in printed
    assert f"set Z {bottom} " not in printed


def test_stop_landmarks_print_at_the_dros_digits_in_inches():
    # Rounding an inch landmark to 0.1 in could move a stop by 1.27 mm: the places print at
    # the DRO's own digits.
    arc = proven()
    arc["guided"].update(
        ends_setup_xy=[[-5.7481, -0.1181], [5.7481, -0.1181]],
        ends_cutter_setup_xy=[[-5.7283, 0.0], [5.7283, 0.0]],
    )
    printed = printed_steps(arc, operative=lambda value: f"{value:.4f}")
    assert "the arc's end at X -5.7481 Y -0.1181 (its centre at X -5.7283 Y 0.0000)" in printed


def test_a_rough_then_finish_sweep_touches_off_once_and_returns_to_the_touch(tmp_path):
    row, printed = traveler_text(tmp_path, allowance=0.3)
    assert row.status == "pass", row.sentence
    assert printed.count("Spindle stopped: bring a flute") == 1
    rough, finish = printed.split("Finish sweep, Z still raised clear:")
    assert "Rough sweep: unlock Y only, move it +0.300 from the touch reading" in rough
    assert "return it to the touch reading" in finish
    # The touch is written down, never zeroed: the setup's DRO zero stays for its other ops.
    assert "set DRO" not in printed and "reading at the touch here" in printed
    # Each stage keeps X and Y locked while the arm sweeps, and ends withdrawn: Z is raised
    # before Y moves for the finish, and only the last sweep stops the spindle.
    assert rough.count("With X and Y locked") == 1 and finish.count("With X and Y locked") == 1
    assert rough.rstrip().endswith("raise Z until the cutter clears the work and the arm.")
    assert "stop the spindle" not in rough
    assert finish.rstrip().endswith("then stop the spindle and wait for it to stop.")


@pytest.mark.parametrize("missing", ["rollers_deg", "rail_deg"])
def test_a_sweep_whose_guide_is_unproven_prints_only_a_stop(tmp_path, missing):
    # Unknown rail ends leave the cut radius computable but the sweep unproven: nothing
    # actionable (touch, lock, stops, sweep) prints beside the STOP.
    row, printed = traveler_text(tmp_path, "rail", **{missing: None})
    assert row.status == "unknown"
    assert "STOP: guided sweep not established (" in printed
    assert "rollers or rail ends unknown) — do not run." in printed
    assert "Lock X and Y" not in printed and "stop block" not in printed


def test_a_rail_sweep_with_an_unknown_rail_radius_prints_only_a_stop(tmp_path):
    # The measured form error and runout still bound the cut, but without the rail's
    # radius the operator cannot set the rollers from the spindle: nothing to run.
    row, printed = traveler_text(tmp_path, "rail", drop="rail_radius_mm = 850.0\n")
    assert row.status == "unknown", row.sentence
    assert "STOP: guided sweep not established (" in printed
    assert "rail radius or roller positions unknown) — do not run." in printed
    assert "Lock X and Y" not in printed and "stop block" not in printed


def test_a_sweep_whose_cut_leaves_the_band_prints_only_a_stop(tmp_path):
    # A measured bar whose worst-case cut lies outside the band is an error: the
    # recipe must not tell the operator to make that cut.
    wide = (
        "[gauges.wide]\nkind = 'setting_bar'\nname = 'R800 wide bar'\n"
        f"radius_limits_mm = {{ value = [800.6, 800.7], {MEASURED} }}\nverify = false\n"
    )
    row, printed = traveler_text(tmp_path, master="'wide'", inventory=wide)
    assert row.status == "error", row.sentence
    assert "outside the R800 to R800.5 mm band" in errors(row)
    assert "STOP: contour points not computed — do not run." in printed
    assert "Lock X and Y" not in printed and "stop block" not in printed


@pytest.mark.parametrize(
    "box",
    [[-500.0, -500.0, -10.0, 500.0, 500.0, 0.0], None],
    ids=["start-in-the-stock", "stock-not-modelled"],
)
def test_a_sweep_start_not_proven_clear_of_the_stock_prints_only_a_stop(tmp_path, box):
    # The cutter goes down at the first stop at every level: only an entry the stock box
    # proves in air prints; a start inside it, or no modelled stock, would plunge unchecked.
    row, printed = traveler_text(tmp_path, box=box)
    assert row.status == "unknown", row.sentence
    assert "the sweep's start is not proven clear of the stock" in debts(row)
    assert "sweep start not proven clear of the stock) — do not run." in printed
    assert "Lock X and Y" not in printed


def exact_cut_spread(rollers, error, rail, roller, reach):
    """How far the cut radius moves between the worst two poses, by exact contact geometry:
    the sled centre where both outer rollers (radius ``roller``) touch a rail of radius
    ``rail`` off by ±``error`` at each contact, the cutter ``reach`` from the true centre on
    the radial line the rollers' angles are measured from."""
    rho = rail + roller  # the roller centres' distance from the true centre
    points = [(rho * math.cos(math.radians(a)), rho * math.sin(math.radians(a))) for a in rollers]
    cuts = []
    for signs in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        r1, r2 = (rho + s * error for s in signs)
        (x1, y1), (x2, y2) = points
        d = math.hypot(x2 - x1, y2 - y1)
        along = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
        height = math.sqrt(r1 * r1 - along * along)
        ux, uy = (x2 - x1) / d, (y2 - y1) / d
        bx, by = x1 + along * ux, y1 + along * uy
        options = [(bx - height * uy, by + height * ux), (bx + height * uy, by - height * ux)]
        centre = min(options, key=lambda p: math.hypot(*p))
        cuts.append(math.dist((reach, 0.0), centre))
    return max(cuts) - min(cuts)


def test_the_rail_bound_holds_for_finite_form_errors():
    # The linear gain is not a bound for finite errors. An R50 rail on Ø10 rollers at ±70°
    # with a 1 mm form error: exact contact geometry moves the cut 5.913 mm between poses,
    # past the linear gain's 5.848 mm. Its finite bound does not converge: unresolved.
    rollers = [70.0, -70.0]
    assert 2 * roller_gain(rollers) * 1.0 == pytest.approx(5.848, abs=1e-3)
    assert exact_cut_spread(rollers, 1.0, 50.0, 5.0, 797.0) == pytest.approx(5.913, abs=1e-3)
    assert rail_cut_shift(rollers, 1.0, 50.0, 797.0) is None
    # Where it converges, the bound covers the exact spread, a hair above the linear gain
    # at a real sled's R850.
    for case in ((rollers, 0.5, 100.0, 5.0), ([-15.0, 15.0], 0.055, 850.0, 11.0)):
        angles, error, rail, roller = case
        bound = 2 * rail_cut_shift(angles, error, rail, 797.0)
        assert bound >= exact_cut_spread(angles, error, rail, roller, 797.0)
        assert bound >= 2 * roller_gain(angles) * error


def test_a_finish_after_a_rejected_rough_prints_no_return_to_an_unprinted_touch(tmp_path):
    # The finish cut (R800.07999975 low) sits just inside the band's R800.0799 edge; the
    # rough's 0.0003 leave rounds off the line to a 0.001 back-off, so only the rough leaves
    # its band. The rejected rough prints nothing; the finish stands alone with its touch.
    target = LONG_ARC.replace("radius = [800.0, 800.5]", "radius = [800.0799, 800.5]")
    row, printed = traveler_text(tmp_path, allowance=0.0003, target=target)
    assert row.status == "error", row.sentence
    assert "op 20 rough: " in errors(row) and "op 20 finish: " not in errors(row)
    assert "Rough sweep" not in printed and "return it to the touch reading" not in printed
    assert printed.count("Spindle stopped: bring a flute") == 1


ZERO_Z = (
    "[setups.zero.z]\nface = 'top'\nmethod = 'paper'\npaper_mm = 0.05\ntool = 'cutter'\n"
    "check_jog_mm = 10.0\nretouch_after = []\n"
)


@pytest.mark.parametrize("guide", ["pivot", "rail"])
def test_travel_and_headroom_owe_a_check_for_the_moving_fixture(tmp_path, guide):
    # Neither rule models the fixture moving under a still table: the swept footprint
    # (pivot post or rollers, the swing past the column and table ends) and the stack at
    # every pose are checks the operator owes, so neither finding is ever a pass.
    from prechips.rules import headroom, travel

    bundle = load_bundle(guided_plan(tmp_path, guide))
    for rule, phrase in (
        (travel, "the swept footprint of"),
        (headroom, "judged with"),
    ):
        (row,) = [r for r in rule.evaluate(bundle) if r.subject == "S1"]
        assert row.status in ("unknown", "error"), row.sentence
        (debt,) = row.numbers["guided_sweep_debts"]
        assert debt.startswith("op 20 guided sweep:") and phrase in debt and "check:" in debt
        assert debt in row.sentence
    (row,) = [r for r in travel.evaluate(bundle) if r.subject == "S1"]
    post = "the pivot post at the arc centre" if guide == "pivot" else "the rollers in the T-slots"
    assert post in row.numbers["guided_sweep_debts"][0]


def test_a_setup_without_a_guided_sweep_owes_no_sweep_check(tmp_path):
    from prechips.rules import headroom, travel

    plan = scratch(tmp_path, op(20, "finish_profile", "{ method = 'chords', count = 24 }"))
    bundle = load_bundle(plan)
    for rule in (travel, headroom):
        (row,) = [r for r in rule.evaluate(bundle) if r.subject == "S1"]
        assert "guided_sweep_debts" not in row.numbers


@pytest.mark.parametrize("mixed", [False, True], ids=["sweep-only", "with-a-drill"])
def test_a_sweep_only_setup_picks_up_no_xy_zero(tmp_path, mixed):
    # Its X and Y come from the touch-off on the master and stay locked: the zero recipe
    # needs only Z, and the DRO ZERO sheet says why. Any other spindle op still needs X/Y.
    from prechips.rules import zero_recipe

    plan = guided_plan(tmp_path)
    if mixed:
        drill = op(30, "drill", feature="bore", tool="bore-drill")
        text = plan.read_text(encoding="utf-8")
        plan.write_text(text + drill, encoding="utf-8")
    plan.write_text(plan.read_text(encoding="utf-8") + ZERO_Z, encoding="utf-8")
    bundle = load_bundle(plan)
    (row,) = [r for r in zero_recipe.evaluate(bundle) if r.subject == "S1"]
    assert set(row.numbers["axes"]) == {"z"}
    if mixed:
        assert "touch_set" not in row.numbers
        return
    assert row.numbers["touch_set"] == {"axes": ["x", "y"], "ops": [20]}
    tools = {("tools", "cutter"): "6 mm endmill"}
    html = _Traveler(bundle, [row], {}, None).dro(bundle.plan["setups"][0], tools)
    printed = " ".join(unescape(re.sub(r"<[^>]+>", "", html)).split())
    assert "X and Y: no edge pickup. The guided sweep (op 20) sets them" in printed


@pytest.mark.parametrize(
    ("direction", "status"),
    [("away", "pass"), ("toward", "error"), ("unknown", "unknown")],
    ids=["positive", "reversed", "undeclared"],
)
def test_a_sweep_only_setup_still_checks_the_dro_sign_its_back_off_moves(
    tmp_path, direction, status
):
    # Without an edge pickup the touch feed and rough back-off still move Y by its DRO
    # sign: a reversed axis is the same error, an undeclared one the same debt.
    from prechips.rules import zero_recipe

    plan = guided_plan(tmp_path, allowance=0.3)
    text = plan.read_text(encoding="utf-8")
    dro = (
        "[dro]\ncontroller = 'el400'\nmode = 'abs'\nradius_mode = false\n"
        "[dro.direction]\nx = 'right'\nz = 'up'\n"
        + (f"y = '{direction}'\n" if direction != "unknown" else "")
    )
    plan.write_text(text.replace("[[setups]]", dro + "[[setups]]", 1) + ZERO_Z, encoding="utf-8")
    (row,) = [r for r in zero_recipe.evaluate(load_bundle(plan)) if r.subject == "S1"]
    assert row.status == status, row.sentence


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
