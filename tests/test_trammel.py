"""Oblique-trammel guided sweeps (docs/plan.md "Manual arcs", issue #269).

A trammel carrier rides one pin on each of two straight rails whose pin-lines cross at the
spindle axis at the rail angle α. The pins subtend α at the cutter at every pose, so in the
carrier's frame the cutter centre runs on the circle through both pins of radius
``D / (2 sin α)``; the carrier turns half the swept angle while it translates, and the
table, the DRO and every handwheel stay locked. The radius error budget comes from the
fixture's measured tolerances; anything undeclared or unmeasured is debt.
"""

import math

import pytest
from test_guided_sweep import LONG_ARC, MEASURED, SWING
from test_manual_arc import arcs, change, coordinates_row, debts, errors, op, scratch

from prechips.rules import trammel

ALPHA = 16.44
# The concave R800 strap edge cut by an Ø6 cutter on the R797.25 pin circle: the wall at
# R800.25, mid-band.
SPACING = round(2 * 797.25 * math.sin(math.radians(ALPHA)), 4)
TRAMMEL = (
    "[fixtures.tram]\nkind = 'trammel'\nname = 'R800 trammel'\n"
    f"rail_angle_deg = {{ value = {ALPHA}, {MEASURED} }}\n"
    f"rail_angle_error_deg = {{ value = 0.001, {MEASURED} }}\n"
    f"pin_spacing_mm = {{ inner = {{ value = {SPACING}, {MEASURED} }} }}\n"
    f"pin_spacing_error_mm = {{ value = 0.01, {MEASURED} }}\n"
    f"pin_clearance_mm = {{ value = 0.005, {MEASURED} }}\n"
    f"rail_offset_mm = {{ value = 0.01, {MEASURED} }}\n"
    f"rail_travel_mm = {{ value = [40.0, 420.0], {MEASURED} }}\n"
    "verify = false\n"
)


def trammel_contour(**more):
    fields = {
        "guide": "'trammel'",
        "fixture": "'tram'",
        "pin_pair": "'inner'",
        "pins_deg": f"[-{ALPHA}, {ALPHA}]",
        "sweep_deg": "25.0",
    }
    fields.update({key: value for key, value in more.items() if value is not None})
    for key in [key for key, value in more.items() if value is None]:
        fields.pop(key)
    sweep = ", ".join(f"{key} = {value}" for key, value in fields.items())
    return f"{{ method = 'guided_sweep', step_deg = 1.0, sweep = {{ {sweep} }} }}"


def trammel_plan(
    tmp_path, *, allowance=None, hold="fixture = 'tram'", inventory=TRAMMEL, target=LONG_ARC, **more
):
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", trammel_contour(**more), allowance=allowance),
        hold=hold,
        target=target,
    )
    path = plan.with_name("inventory.toml")
    path.write_text(path.read_text(encoding="utf-8") + inventory, encoding="utf-8")
    return plan


def trammel_row(tmp_path, **kwargs):
    return coordinates_row(trammel_plan(tmp_path, **kwargs), stock_bbox=SWING)


def recipe(row):
    (table,) = arcs(row, 20)
    return table, table["guided"]


# --- kinematics ---------------------------------------------------------------------


def test_the_issue_numbers_give_r795_and_47_mm_of_radius_per_degree():
    # #269: D = 450 mm on rails at 16.44° runs an Ø10 cutter's centre on R795.
    assert trammel.radius(450.0, 16.44) == pytest.approx(795.02, abs=0.01)
    # ∂R/∂α = D cos α / (2 sin² α): about 47 mm of radius per degree of rail angle.
    assert trammel.per_degree(450.0, 16.44) == pytest.approx(47.0, abs=0.05)
    assert trammel.per_spacing(16.44) == pytest.approx(1 / (2 * math.sin(math.radians(16.44))))
    # And ∂R/∂α agrees with a finite difference of R itself.
    step = 1e-4
    slope = (trammel.radius(450.0, 16.44 - step) - trammel.radius(450.0, 16.44 + step)) / (2 * step)
    assert slope == pytest.approx(trammel.per_degree(450.0, 16.44), rel=1e-6)


def _setup(alpha=16.44, spacing=450.0, sweep=26.0):
    r = trammel.radius(spacing, alpha)
    centre, heading = [12.0, 800.0], -90.0
    return r, centre, heading, [-alpha, alpha], -sweep / 2, sweep / 2


def _pin(centre, heading, r, angle):
    theta = math.radians(heading + angle)
    return [centre[0] + r * math.cos(theta), centre[1] + r * math.sin(theta)]


def test_every_pose_keeps_both_pins_on_their_rails_and_the_cutter_on_the_circle():
    r, centre, heading, pins, lo, hi = _setup()
    spindle = _pin(centre, heading, r, 0.0)
    directions = trammel.rails(centre, heading, r, pins)
    cross = abs(directions[0][0] * directions[1][0] + directions[0][1] * directions[1][1])
    assert math.degrees(math.acos(cross)) == pytest.approx(16.44)
    for k in range(401):
        psi = lo + (hi - lo) * k / 400
        for pin, direction in zip(pins, directions, strict=True):
            at = trammel.place(centre, heading, r, psi, _pin(centre, heading, r, pin))
            v = [at[0] - spindle[0], at[1] - spindle[1]]
            # On its rail's pin-line, on the ray toward its own rail, at its station.
            assert v[0] * direction[1] - v[1] * direction[0] == pytest.approx(0.0, abs=1e-9)
            assert v[0] * direction[0] + v[1] * direction[1] > 0
            assert math.hypot(*v) == pytest.approx(trammel.station(r, pin, psi))
        # The virtual centre stays R from the spindle: the cutter cuts the R circle.
        assert math.dist(trammel.place(centre, heading, r, psi, centre), spindle) == pytest.approx(
            r
        )


def test_the_carrier_turns_half_the_swept_angle_and_travels_about_350_mm_per_rail():
    r, centre, heading, pins, lo, hi = _setup()
    a, b = (_pin(centre, heading, r, pin) for pin in pins)

    def bearing(psi):
        p, q = (trammel.place(centre, heading, r, psi, x) for x in (a, b))
        return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))

    assert bearing(hi) - bearing(lo) == pytest.approx(-(hi - lo) / 2)
    assert abs(bearing(hi) - bearing(0.0)) == pytest.approx(6.5)
    for pin in pins:
        low, high = trammel.station_range(r, pin, lo, hi)
        assert high - low == pytest.approx(356.0, abs=5.0)


@pytest.mark.parametrize("pins", [[-16.44, 16.44], [-50.0, -17.12], [163.56, 196.44]])
def test_swept_extents_and_stations_are_exact_against_a_dense_sample(pins):
    r, centre, heading, _, lo, hi = _setup()
    points = [[-150.0, 5.0], [150.0, 5.0], [-150.0, 40.0], [150.0, 40.0], centre]
    box = trammel.swept_box(centre, heading, r, lo, hi, points)
    samples = [
        trammel.place(centre, heading, r, lo + (hi - lo) * k / 20000, p)
        for k in range(20001)
        for p in points
    ]
    for axis in range(2):
        assert box[axis][0] == pytest.approx(min(s[axis] for s in samples), abs=1e-6)
        assert box[axis][1] == pytest.approx(max(s[axis] for s in samples), abs=1e-6)
        # Exact, not sampled: never inside the sampled extremes.
        assert box[axis][0] <= min(s[axis] for s in samples) + 1e-9
        assert box[axis][1] >= max(s[axis] for s in samples) - 1e-9
    for pin in pins:
        low, high = trammel.station_range(r, pin, lo, hi)
        dense = [trammel.station(r, pin, lo + (hi - lo) * k / 20000) for k in range(20001)]
        assert low == pytest.approx(min(dense), abs=1e-6)
        assert high == pytest.approx(max(dense), abs=1e-6)


def test_offsetting_both_pin_lines_moves_the_radius_about_one_to_one():
    r, centre, heading, pins, lo, hi = _setup()
    directions = trammel.rails(centre, heading, r, pins)
    # At the symmetric pose each line's offset moves the radius 1 / (2 cos(α/2)): both
    # together about 1:1, never 2:1.
    assert trammel.line_gain(directions, heading, 0.0, 0.0) == pytest.approx(
        1 / math.cos(math.radians(16.44 / 2))
    )
    gain = trammel.line_gain(directions, heading, lo, hi)
    assert 1.0 <= gain < 1.05
    # The worst case is exact against a dense sample of the pose window, and against
    # moving the lines themselves and re-solving where they cross.
    normals = [[-d[1], d[0]] for d in directions]
    worst = 0.0
    for k in range(2001):
        psi = lo + (hi - lo) * k / 2000
        out = [math.cos(math.radians(heading + psi / 2)), math.sin(math.radians(heading + psi / 2))]
        for e1, e2 in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            det = normals[0][0] * normals[1][1] - normals[0][1] * normals[1][0]
            x = (e1 * normals[1][1] - e2 * normals[0][1]) / det
            y = (normals[0][0] * e2 - normals[1][0] * e1) / det
            worst = max(worst, abs(x * out[0] + y * out[1]))
    assert gain == pytest.approx(worst, abs=1e-6)
    assert gain >= worst - 1e-12


def test_pins_must_subtend_the_rail_angle():
    assert trammel.fits([-16.44, 16.44], 16.44)
    assert trammel.fits([163.56, 196.44], 16.44)
    assert not trammel.fits([-15.0, 16.44], 16.44)


# --- the coordinates recipe ----------------------------------------------------------


def test_a_trammel_sweep_locks_every_axis_and_cuts_on_its_pin_circle(tmp_path):
    row = trammel_row(tmp_path)
    assert row.status == "pass", row.sentence
    table, sweep = recipe(row)
    assert sweep["guide"] == "trammel" and sweep["feed"] == "lever"
    assert sweep["locked_axes"] == ["X", "Y", "Z"] and sweep["moves"] == "fixture"
    assert sweep["pin_radius_mm"] == pytest.approx(797.25, abs=1e-3)
    # The rows stay on the drawing's R797 path, as every guided sweep's do: the kernel
    # judges that path against the nominal part, and the band check judges where the pins
    # actually put the cut (R797.25 here, 0.25 mm off it).
    for r in table["rows"]:
        assert math.dist(r["setup_xy"], table["centre_setup_xy"]) == pytest.approx(797.0)
        assert r["dro_xy"] == r["setup_xy"]
    assert table["exact_arc"]["radius"] == pytest.approx(797.0)
    # The stops set by a steel rule still hold the carrier past both arc ends, and the
    # cutter goes down clear of the stock.
    assert sweep["stops"] == "proven" and sweep["start"] == "air"
    # The error budget: rail angle, spacing and both pin-lines.
    terms = sweep["error_terms_mm"]
    # The radius at the tolerance corners: to first order the 47 mm/° and 1/(2 sin α) slopes.
    first = sweep["radius_per_deg_mm"] * 0.001 + sweep["radius_per_spacing"] * 0.01
    assert terms["radius_below"] == pytest.approx(first, rel=1e-3)
    assert terms["radius_above"] == pytest.approx(first, rel=1e-3)
    assert terms["radius_above"] > terms["radius_below"]  # R is convex in α
    assert terms["pin_lines"] == pytest.approx(sweep["line_gain"] * 0.015)
    # Plus one DRO step of margin each way, as on every guided-sweep proof (#258).
    assert sweep["margin_mm"] == pytest.approx(0.001)
    below = terms["radius_below"] + terms["pin_lines"] + sweep["margin_mm"]
    # The pin-lines' offset also slides the cutter along the circle: second order, above.
    assert 0 < terms["pin_lines_second"] < 1e-5
    above = terms["radius_above"] + terms["pin_lines"] + terms["pin_lines_second"]
    above += sweep["margin_mm"]
    assert sweep["centre_error_mm"] == pytest.approx(max(below, above))
    wall = sweep["pin_radius_mm"] + 3.0  # an Ø6 cutter inside the concave edge
    assert sweep["cut_radius_mm"] == pytest.approx([wall - below, wall + above], abs=1e-9)
    assert sweep["carrier_turn_deg"] == pytest.approx(12.5)
    low, high = sweep["station_ranges_mm"][0]
    assert 40.0 <= low < high <= 420.0
    assert sweep["rotation"] in ("clockwise", "counterclockwise")
    assert sweep["swept_mm"]["stock"] is True
    assert "inventory fixtures.tram: guided-sweep fixture" in row.cite


def test_a_rail_angle_error_beyond_the_band_is_an_error(tmp_path):
    plan = trammel_plan(tmp_path)
    change(
        plan.with_name("inventory.toml"),
        "rail_angle_error_deg = { value = 0.001",
        "rail_angle_error_deg = { value = 0.01",
    )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "error"
    assert "error budget" in errors(row) and "outside the R800 to R800.5 mm band" in errors(row)


@pytest.mark.parametrize(
    "field",
    [
        "rail_angle_deg",
        "rail_angle_error_deg",
        "pin_spacing_error_mm",
        "pin_clearance_mm",
        "rail_offset_mm",
        "rail_travel_mm",
    ],
)
def test_an_unmeasured_fixture_fact_is_debt_with_a_measure_line(tmp_path, field):
    plan = trammel_plan(tmp_path)
    path = plan.with_name("inventory.toml")
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.startswith(field + " ")]
    assert len(kept) == len(lines) - 1
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "unknown", row.sentence
    stem = field.removesuffix("_mm").removesuffix("_in")
    table, sweep = recipe(row)
    if field != "rail_travel_mm":  # the travel bounds the carriages, not the radius
        assert sweep["cut_radius_mm"] == "unknown"
    ids = [entry["id"] for entry in table["measurements"]]
    assert f"fixtures.tram.{stem}" in ids
    entry = next(e for e in table["measurements"] if e["id"] == f"fixtures.tram.{stem}")
    assert entry["instruction"].startswith("measure: tram trammel")


def test_an_assumed_pin_spacing_is_debt_never_a_perfect_fixture(tmp_path):
    assumed = MEASURED.replace("status = 'measured'", "status = 'assumed'")
    inventory = TRAMMEL.replace(
        f"inner = {{ value = {SPACING}, {MEASURED} }}",
        f"inner = {{ value = {SPACING}, {assumed} }}",
    )
    assert inventory != TRAMMEL
    row = trammel_row(tmp_path, inventory=inventory)
    assert row.status == "unknown"
    assert "pin pair inner spacing of tram is unknown or not measured" in debts(row)
    (table,) = arcs(row, 20)
    (entry,) = [e for e in table["measurements"] if e["id"] == "fixtures.tram.pin_spacing.inner"]
    assert entry["status"] == "assumed" and "not physically measured" in entry["instruction"]


def test_a_missing_pin_pair_is_debt(tmp_path):
    row = trammel_row(tmp_path, pin_pair="'outer'")
    assert row.status == "unknown"
    assert "pin pair outer spacing of tram is unknown" in debts(row)
    (table,) = arcs(row, 20)
    assert "fixtures.tram.pin_spacing.outer" in [e["id"] for e in table["measurements"]]


def test_pins_that_do_not_fit_the_rail_angle_are_an_error(tmp_path):
    row = trammel_row(tmp_path, pins_deg="[-15.0, 15.0]")
    assert row.status == "error"
    assert "do not subtend the rails' 16.44° at the cutter" in errors(row)


def test_a_sweep_over_a_pin_is_an_error(tmp_path):
    row = trammel_row(tmp_path, sweep_deg="40.0")
    assert row.status == "error"
    assert "carries the cutter over the pin" in errors(row)


def test_a_carriage_beyond_its_rail_travel_is_an_error(tmp_path):
    plan = trammel_plan(tmp_path)
    change(plan.with_name("inventory.toml"), "[40.0, 420.0]", "[100.0, 420.0]")
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "error"
    assert "beyond the rail's 100 to 420 mm travel" in errors(row)


def test_a_master_or_touch_axis_on_a_trammel_is_an_error(tmp_path):
    row = trammel_row(tmp_path, touch_axis="'-Y'")
    assert row.status == "error"
    assert "a trammel has no touch-off" in errors(row)


def test_a_rough_stage_on_a_trammel_is_an_error(tmp_path):
    row = trammel_row(tmp_path, allowance=0.3)
    assert row.status == "error"
    assert "cannot back off for a rough stage" in errors(row)


def test_the_wrong_fixture_kind_is_an_error(tmp_path):
    inventory = TRAMMEL.replace("kind = 'trammel'", "kind = 'arc_sled'")
    row = trammel_row(tmp_path, inventory=inventory)
    assert row.status == "error"
    assert "is a arc_sled, not the trammel a trammel guide rides on" in errors(row)


# --- setup rules ---------------------------------------------------------------------


def test_travel_and_headroom_owe_a_check_quoting_the_exact_footprint(tmp_path):
    import dataclasses

    from prechips.inputs import load_bundle
    from prechips.rules import headroom, travel

    bundle = load_bundle(trammel_plan(tmp_path))
    kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": SWING}}}
    bundle = dataclasses.replace(bundle, kernel=kernel)
    (row,) = [r for r in travel.evaluate(bundle) if r.subject == "S1"]
    assert row.status in ("unknown", "error"), row.sentence
    (debt,) = row.numbers["guided_sweep_debts"]
    assert debt.startswith("op 20 guided sweep (trammel): the swept footprint of tram")
    assert "the work and pins sweep X" in debt and "about the spindle axis" in debt
    assert "check: with Z raised and the spindle stopped, lever the carrier" in debt
    assert debt in row.sentence
    (row,) = [r for r in headroom.evaluate(bundle) if r.subject == "S1"]
    assert row.status in ("unknown", "error"), row.sentence
    (debt,) = row.numbers["guided_sweep_debts"]
    assert "turning 12.5°" in debt and "the carriages, as near as" in debt


def test_a_trammel_only_setup_owes_no_xy_pickup_and_no_xy_dro_sign(tmp_path):
    # The rails fix the cut: no X/Y handwheel moves at all, so neither a pickup nor an
    # X/Y DRO direction is consumed; the DRO ZERO sheet says why.
    import re
    from html import unescape

    from test_guided_sweep import ZERO_Z

    from prechips.inputs import load_bundle
    from prechips.rules import zero_recipe
    from prechips.sheet import _Traveler

    plan = trammel_plan(tmp_path)
    text = plan.read_text(encoding="utf-8")
    dro = (
        "[dro]\ncontroller = 'el400'\nmode = 'abs'\nradius_mode = false\n"
        "[dro.direction]\nz = 'up'\n"
    )
    plan.write_text(text.replace("[[setups]]", dro + "[[setups]]", 1) + ZERO_Z, encoding="utf-8")
    bundle = load_bundle(plan)
    (row,) = [r for r in zero_recipe.evaluate(bundle) if r.subject == "S1"]
    assert set(row.numbers["axes"]) == {"z"}
    assert row.numbers["touch_set"] == {"axes": ["x", "y"], "ops": [20], "by": "trammel"}
    assert row.status != "error", row.sentence
    tools = {("tools", "cutter"): "6 mm endmill"}
    html = _Traveler(bundle, [row], {}, None).dro(bundle.plan["setups"][0], tools)
    printed = " ".join(unescape(re.sub(r"<[^>]+>", "", html)).split())
    assert "puts the cutter where its rails' pin-lines cross" in printed


# --- the traveler --------------------------------------------------------------------


def traveler_text(tmp_path, **kwargs):
    import dataclasses
    import re
    from html import unescape

    from prechips.inputs import load_bundle
    from prechips.rules import coordinates
    from prechips.sheet import _Traveler

    plan = trammel_plan(tmp_path, **kwargs)
    kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": SWING}}}
    bundle = dataclasses.replace(load_bundle(plan), kernel=kernel)
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    tools = {("tools", "cutter"): "6 mm endmill"}
    html = _Traveler(bundle, [row], {}, None).contours(bundle.plan["setups"][0], tools)
    return row, " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def test_the_traveler_prints_the_pins_stops_on_a_rail_and_the_lever_feed(tmp_path):
    row, printed = traveler_text(tmp_path)
    printed = printed.replace("( ", "(").replace(" )", ")")
    assert row.status == "pass", row.sentence
    _, sweep = recipe(row)
    assert "on its inner pin pair" in printed and "rails' crossing" in printed
    assert "lock X and Y there" in printed
    # No master, touch-off or DRO table.
    assert "master" not in printed.lower() and "flute of the cutter" not in printed
    assert "handwheel axis" not in printed
    # Stops on one rail at the pin's exact stations, the other rail's as a check.
    (start, end), (other_start, other_end) = sweep["stations_mm"]
    assert (
        f"stands {round(start, 1):g} mm from the spindle axis ({round(start - 40.0, 1):g} mm"
        in printed
    )
    assert f"Do the same at {round(end, 1):g} mm" in printed
    assert "from where the carriage stands on the rail's near end stop, 40 mm" in printed
    assert f"{round(other_start, 1):g} and {round(other_end, 1):g} mm" in printed
    assert "lever the carrier from stop to stop once" in printed
    assert "by its hand lever" in printed and "turns 12.5°" in printed
    assert "stop the spindle" in printed


def test_an_unproven_trammel_prints_only_a_stop(tmp_path):
    inventory = "\n".join(
        line for line in TRAMMEL.splitlines() if not line.startswith("rail_angle_deg ")
    )
    row, printed = traveler_text(tmp_path, inventory=inventory + "\n")
    assert row.status == "unknown"
    assert "STOP: guided sweep not established (" in printed
    assert "cut radius unproven" in printed
    assert "hand lever" not in printed


# --- the kernel ----------------------------------------------------------------------

_EXACT = r"""
import importlib.util
import json
import math
import os
import sys

kernel, out = sys.argv[sys.argv.index("--") + 1 :]
spec = importlib.util.spec_from_file_location("trammel_job", os.path.join(kernel, "freecad_job.py"))
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
R, r, sweep, height = 797.0, 3.0, 25.0, 10.0
c = [0.0, 816.0]
angles = [math.radians(-sweep / 2 + sweep * k / 25) for k in range(26)]
rows = [[c[0] + R * math.sin(a), c[1] - R * math.cos(a)] for a in angles]
arc = {"centre": c, "radius": R}
exact = job._centre_sweep([(rows, 0.0, arc)], r, height)
chords = job._centre_sweep([(rows, 0.0)], r, height)
# Two rows only (a short sweep under one step): still the arc, never its chord.
two = job._centre_sweep([([rows[0], rows[-1]], 0.0, arc)], r, height)
# The disc swept along the arc: its annular sector and a half disc at each end.
want = (2 * R * r * math.radians(sweep) + math.pi * r * r) * height
with open(out, "w") as handle:
    found = {"exact": exact.Volume, "chords": chords.Volume, "two": two.Volume}
    json.dump({**found, "want": want}, handle)
"""


def test_the_kernel_sweeps_the_exact_annulus_not_the_rows_chords(tmp_path, freecad_kernel):
    import json
    import subprocess
    from pathlib import Path

    import prechips.kernel

    script, out = tmp_path / "exact.py", tmp_path / "exact.json"
    script.write_text(_EXACT, encoding="utf-8")
    kernel = Path(prechips.kernel.__file__).parent
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(kernel), str(out)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert out.is_file(), process.stdout[-2000:] + process.stderr
    found = json.loads(out.read_text(encoding="utf-8"))
    assert found["exact"] == pytest.approx(found["want"], rel=1e-9)
    assert found["two"] == pytest.approx(found["want"], rel=1e-9)
    # The rows' chords fall short of the arc by their sagitta: the exact sweep is not them.
    assert found["chords"] < found["want"] - 0.1


def kernel_checkpoints(tmp_path, sweep_deg=25.0):
    """The trammel's rows as build_job hands them to the kernel: a finish of the plate's
    concave R800 top edge to Z 1 with a 6 mm cutter on the R797 pin circle."""
    from test_guided_sweep import TOP_EDGE

    from prechips.inputs import load_bundle
    from prechips.kernel import table_checkpoints
    from prechips.rules import coordinates

    spacing = 2 * 797.0 * math.sin(math.radians(ALPHA))
    inventory = TRAMMEL.replace(f"value = {SPACING},", f"value = {spacing!r},")
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", trammel_contour(sweep_deg=sweep_deg)),
        origin="[0.0, 0.0, 0.0]",
        hold="fixture = 'tram'",
        target=TOP_EDGE,
    )
    path = plan.with_name("inventory.toml")
    path.write_text(path.read_text(encoding="utf-8") + inventory, encoding="utf-8")
    change(plan, "to_z = -1.0", "to_z = 1.0")
    bundle = load_bundle(plan)
    row = next(r for r in coordinates.evaluate(bundle, pre_kernel=True) if r.subject == "S1")
    (table,) = row.numbers["arc_table"]
    return table, table_checkpoints("S1:20", row.numbers, 20, "mm")


def test_the_kernel_receives_the_exact_pin_circle(tmp_path):
    table, checkpoints = kernel_checkpoints(tmp_path)
    (path,) = checkpoints["paths"]
    assert path["exact_arc_mm"]["radius"] == pytest.approx(797.0)
    assert path["exact_arc_mm"]["centre"] == pytest.approx(table["centre_setup_xy"])
    for xy in path["xy_mm"]:
        assert math.dist(xy, path["exact_arc_mm"]["centre"]) == pytest.approx(797.0)


@pytest.fixture(scope="module")
def plates(tmp_path_factory, freecad_kernel):
    """The open and walled R800 plates of test_guided_sweep's kernel tests."""
    import subprocess

    from test_guided_sweep import _PLATES

    directory = tmp_path_factory.mktemp("trammel-plates")
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


def trammel_run(tmp_path, freecad_kernel, step, render=None):
    from test_guided_sweep import PLATE_BLANK
    from test_kernel_geometry import Engine, _op, _setup, _vise

    table, checkpoints = kernel_checkpoints(tmp_path / "plan")
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
    first = _setup([finish], hold, setup_id="S1")
    if render is not None:
        first["render"] = render
    setups = [first, _setup([], hold, setup_id="S2")]
    result = engine.run(engine.job(step, {"edge": edge}, setups, stock=PLATE_BLANK))
    assert result["status"] == "ok", result.get("reason")
    return table, result


def test_the_kernel_clears_the_pin_circle_and_judges_the_run_past_its_ends(
    tmp_path, freecad_kernel, plates
):
    table, result = trammel_run(tmp_path, freecad_kernel, plates["open"])
    assert table["guided"]["overrun_mm"] > 25.0
    facts = result["ops"]["S1:20"]
    assert facts["claimed_indices"] and not facts["claim_errors"], facts
    assert facts["checkpoint_errors"] == [], facts["checkpoint_errors"]
    assert "stock_reason" not in result["setups"]["S2"], result["setups"]["S2"]
    _, walled = trammel_run(tmp_path / "walled", freecad_kernel, plates["walled"])
    errors = walled["ops"]["S1:20"]["checkpoint_errors"]
    assert errors and {error["obstacle"] for error in errors} == {"finished part"}, errors


def test_trammel_rails_and_pins_are_drawn_but_never_hit_tested(tmp_path, freecad_kernel, plates):
    # A rail and a pin placed right through the stock and the cutter's rows: drawn, but
    # no holding solid, so every verdict matches the same job without them.
    rail = {
        "name": "trammel rail T",
        "from_mm": [-100.0, 20.0],
        "to_mm": [100.0, 20.0],
        "width_mm": 15.0,
        "z_mm": [-5.0, 9.0],
    }
    pin = {"name": "carrier pin T", "at_mm": [0.0, 20.0], "dia_mm": 8.0, "z_mm": [-5.0, 9.0]}
    broken = {**rail, "name": "trammel rail X", "to_mm": [-100.0, 20.0]}
    render = {"guides": {"rails": [rail, broken], "pins": [pin]}}
    _, plain = trammel_run(tmp_path / "plain", freecad_kernel, plates["open"])
    _, drawn = trammel_run(tmp_path / "drawn", freecad_kernel, plates["open"], render)
    scene = drawn["setups"]["S1"]["render_scene"]
    roles = {c["name"]: c.get("role") for c in scene["components"]}
    assert roles["trammel rail T"] == "guide_rail" and roles["carrier pin T"] == "guide_pin"
    assert "trammel rail X" not in roles
    assert any(debt.startswith("trammel rail X not drawn") for debt in scene["render_debts"])
    assert not any("trammel" in debt or "carrier pin" in debt for debt in scene["debts"])
    facts, before = drawn["ops"]["S1:20"], plain["ops"]["S1:20"]
    assert facts["checkpoint_errors"] == before["checkpoint_errors"] == []
    assert facts["checkpoint_hits"] == before["checkpoint_hits"]
    setup, unchanged = drawn["setups"]["S1"], plain["setups"]["S1"]
    for key in ("fixture_rendered", "fixture_clashes"):
        assert key in setup and setup[key] == unchanged[key], key
    assert scene["cut_clearances"] == plain["setups"]["S1"]["render_scene"]["cut_clearances"]


PICTURE = (
    f"pin_dia_mm = {{ value = 12.0, {MEASURED} }}\n"
    f"rail_width_mm = {{ value = 15.0, {MEASURED} }}\n"
    f"rail_height_mm = {{ value = 24.0, {MEASURED} }}\n"
    f"bed_height_mm = {{ value = 40.0, {MEASURED} }}\n"
)


def scene(tmp_path, inventory):
    from prechips.inputs import load_bundle
    from prechips.rules.guided_sweep import guide_scene

    row = trammel_row(tmp_path, inventory=inventory)
    bundle = load_bundle(trammel_plan(tmp_path / "again", inventory=inventory))
    setup = bundle.plan["setups"][0]
    return row, guide_scene(bundle, setup, row.numbers, 1.0)


def test_the_setup_picture_draws_the_rails_and_pins_where_the_pose_puts_them(tmp_path):
    row, (drawn, notes) = scene(
        tmp_path, TRAMMEL.replace("verify = false\n", PICTURE + "verify = false\n")
    )
    assert notes == []
    _, sweep = recipe(row)
    spindle = sweep["spindle_setup_xy"]
    for rail, direction in zip(drawn["rails"], sweep["rails_dir"], strict=True):
        assert rail["width_mm"] == 15.0
        for end, station in (("from_mm", 40.0), ("to_mm", 420.0)):
            want = [spindle[i] + station * direction[i] for i in range(2)]
            assert rail[end] == pytest.approx(want)
        assert rail["z_mm"][1] - rail["z_mm"][0] == pytest.approx(24.0)
    for pin, at in zip(drawn["pins"], sweep["pins_setup_xy"], strict=True):
        assert pin["at_mm"] == pytest.approx(at) and pin["dia_mm"] == 12.0
        # Each pin stands on the pin circle, at its station from the spindle axis.
        assert math.dist(at, spindle) == pytest.approx(
            trammel.station(sweep["pin_radius_mm"], ALPHA, 0.0)
        )


def test_an_unmeasured_picture_fact_leaves_the_rails_undrawn_with_a_note(tmp_path):
    _, (drawn, notes) = scene(tmp_path, TRAMMEL)
    assert drawn is None
    (note,) = notes
    assert note.startswith("NOT SHOWN: op 20's trammel rails and pins — measure: tram")
    assert "pin diameter" in note and "rail width" in note


def test_measured_alpha_seats_the_pins_not_the_plans_rounding(tmp_path):
    # Re-measuring the rails to 16.4412° keeps the plan's [-16.44, 16.44]: the measured
    # angle sets how far apart the pins sit, the plan only where the pair sits.
    inventory = TRAMMEL.replace(f"value = {ALPHA},", "value = 16.4412,")
    row = trammel_row(tmp_path, inventory=inventory)
    assert row.status in ("pass", "error"), row.sentence
    assert "do not subtend" not in errors(row)
    _, sweep = recipe(row)
    assert sweep["pins_deg"] == pytest.approx([-16.4412, 16.4412])
    assert trammel.seat([163.5, 196.5], 16.44) == pytest.approx([163.56, 196.44])
    assert trammel.seat([-15.0, 15.0], 16.44) is None


def test_a_second_pin_pair_gives_a_concentric_radius_on_the_same_rails():
    # #269: R795 and R821 cutter-centre circles from two pairs, rails unmoved.
    inner, outer = 450.0, 2 * 821.0 * math.sin(math.radians(16.44))
    assert trammel.radius(outer, 16.44) == pytest.approx(821.0)
    r_in, r_out = trammel.radius(inner, 16.44), trammel.radius(outer, 16.44)
    centre, heading = [0.0, 800.0], -90.0
    for r in (r_in, r_out):
        directions = trammel.rails(centre, heading, r, [-16.44, 16.44])
        # The same pin-line directions: one rail setting serves both pairs.
        same = trammel.rails(centre, heading, r_in, [-16.44, 16.44])
        assert [v for d in directions for v in d] == pytest.approx([v for d in same for v in d])


def test_a_trammel_flagged_to_verify_owes_every_consumed_fact(tmp_path):
    row = trammel_row(tmp_path, inventory=TRAMMEL.replace("verify = false", "verify = true"))
    assert row.status == "unknown"
    (table,) = arcs(row, 20)
    ids = {entry["id"] for entry in table["measurements"]}
    for stem in ("rail_angle_deg", "rail_angle_error_deg", "rail_travel", "pin_spacing.inner"):
        assert f"fixtures.tram.{stem}" in ids, ids


def test_a_large_rail_angle_error_is_bounded_at_its_corners_not_by_the_slope():
    # Codex on #278: a 1° error on the issue's trammel moves R by 50.11 mm at 15.44°,
    # more than the 47.02 mm the slope at 16.44° gives.
    nominal = trammel.radius(450.0, 16.44)
    assert trammel.radius(450.0, 15.44) - nominal == pytest.approx(50.11, abs=0.01)
    assert trammel.radius(450.0, 15.44) - nominal > trammel.per_degree(450.0, 16.44)


def test_a_nonpositive_pin_spacing_is_an_error(tmp_path):
    inventory = TRAMMEL.replace(f"value = {SPACING},", "value = 0.0,")
    row = trammel_row(tmp_path, inventory=inventory)
    assert row.status == "error"
    assert "spacing 0 mm is not positive" in errors(row)


def test_a_bounded_trammel_is_debt_and_never_reaches_the_kernel_as_an_arc(tmp_path):
    # A finish method cuts its whole arc: bounds cannot clip it, so the recipe is never
    # stamped and no exact arc (or chord fragment of one) is handed on.
    from prechips.inputs import load_bundle
    from prechips.rules import coordinates

    plan = trammel_plan(tmp_path)
    text = plan.read_text(encoding="utf-8")
    bounds = "stock_removal_bounds = { x = [-200.0, 200.0], y = [-50.0, 50.0], z = [-5.0, 5.0] }\n"
    plan.write_text(
        text.replace("direction = 'conventional'\n", "direction = 'conventional'\n" + bounds, 1),
        encoding="utf-8",
    )
    bundle = load_bundle(plan)
    row = next(r for r in coordinates.evaluate(bundle, pre_kernel=True) if r.subject == "S1")
    assert row.status == "unknown"
    assert "stock_removal_bounds cannot clip it" in debts(row)
    assert not any("exact_arc" in table for table in row.numbers.get("arc_table", []))


# --- one gate for every printed value (#289) ------------------------------------------


def established_card(tmp_path):
    """The passing trammel's arc table and its printed card."""
    from prechips.sheet_sweep import steps

    row = trammel_row(tmp_path)
    (table,) = arcs(row, 20)
    card = steps(table, lambda v: f"{v:.3f}", "A", "B", feed=100.0)
    assert not card[0].startswith("STOP"), card
    return table, card


def _blank(table, field):
    """``table`` with ``field`` of the trammel card unknown, as the rule leaves it."""
    import copy

    table = copy.deepcopy(table)
    sweep = table["guided"]
    if field == "stage":
        table["stage"] = "rough"
    elif field == "depths":
        table["dro_tip_z"] = "unknown"
    elif field == "spindle_rotation":
        table["spindle_rotation"] = "unknown"
    elif field in ("stops", "start"):
        sweep[field] = "unproven"
    else:
        sweep[field] = "unknown"
    return table


def _gate_fields():
    from prechips.sheet_sweep import TRAMMEL_PRINTED

    return [field for field, _, _ in TRAMMEL_PRINTED]


@pytest.mark.parametrize("field", _gate_fields())
def test_each_printed_trammel_value_unknown_prints_only_a_stop(tmp_path, field):
    from prechips.sheet_sweep import TRAMMEL_PRINTED, established, steps

    table, _ = established_card(tmp_path)
    blank = _blank(table, field)
    (words,) = [w for f, _, w in TRAMMEL_PRINTED if f == field]
    card = steps(blank, lambda v: f"{v:.3f}", "A", "B", feed=100.0)
    assert len(card) == 1 and card[0].startswith("STOP: guided sweep not established")
    assert words in card[0]
    assert not established(blank)


def test_the_trammel_card_reads_nothing_the_gate_does_not_check():
    # Structural: every record value the card's text reads is a gate field, so no future
    # printed number can bypass the STOP.
    import ast
    import inspect

    from prechips import sheet_sweep

    tree = ast.parse(inspect.getsource(sheet_sweep._trammel))
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            key = node.slice
            if node.value.id in ("sweep", "arc") and isinstance(key, ast.Constant):
                read.add(key.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in ("sweep", "arc")
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            read.add(node.args[0].value)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_depths":
            read.add("depths")
    assert read, "the card reads no record value"
    assert read <= set(_gate_fields()), read - set(_gate_fields())


# --- operator perturbation (#289) ------------------------------------------------------
#
# An independent model of the real fixture, not the rule's own formulas: the true rail
# angle and pin spacing at either end of their measured tolerance, each rail's pin-line
# offset by the pin clearance plus the rail offset either way, and the operator's stops
# set from the printed 0.1 mm stations with a steel rule read to half a millimetre either
# way. The carrier's pose is solved from the two pin-on-line constraints at each carrier
# rotation, and the cutter (on the spindle axis) is read back in the carrier's frame. The
# Z the DRO sets does not enter the radius; no angle the card prints is set by the
# operator (the rails are aligned once, the stops by rail station), so their rounding
# reaches the cut only through the stations.

TOOL_RADIUS = 3.0  # the scratch bundle's Ø6 cutter, inside the concave edge
RULE = 0.55  # the printed 0.1 mm station's rounding plus half a millimetre of rule


def _rot(v, deg):
    t = math.radians(deg)
    return [v[0] * math.cos(t) - v[1] * math.sin(t), v[0] * math.sin(t) + v[1] * math.cos(t)]


def _carried(pins, rails_, offsets, theta):
    """(cutter in the carrier's frame, pin 1's station on rail 1) with the carrier turned
    ``theta`` degrees: table ``y = Rot(theta) x + t``, the spindle at the table origin, and
    each pin on its rail's offset pin-line, ``n_i . (Rot P_i + t) = e_i``."""
    normals = [[-r[1], r[0]] for r in rails_]
    moved = [_rot(p, theta) for p in pins]
    b = [offsets[i] - sum(normals[i][k] * moved[i][k] for k in range(2)) for i in range(2)]
    det = normals[0][0] * normals[1][1] - normals[0][1] * normals[1][0]
    t = [
        (b[0] * normals[1][1] - b[1] * normals[0][1]) / det,
        (normals[0][0] * b[1] - normals[1][0] * b[0]) / det,
    ]
    station1 = sum(rails_[0][k] * (moved[0][k] + t[k]) for k in range(2))
    return _rot([-t[0], -t[1]], -theta), station1


def _stopped(pins, rails_, offsets, target):
    """The carrier turn at which pin 1 stands at ``target`` on rail 1 (bisection)."""
    lo, hi = -20.0, 20.0
    s_lo = _carried(pins, rails_, offsets, lo)[1]
    for _ in range(80):
        mid = (lo + hi) / 2
        s_mid = _carried(pins, rails_, offsets, mid)[1]
        if (s_mid - target) * (s_lo - target) <= 0:
            hi = mid
        else:
            lo, s_lo = mid, s_mid
    return (lo + hi) / 2


def _simulate(table, angle_err, spacing_err, line_err, steps=400):
    """Every worst-case fixture and stop setting the printed card allows: yields (walls
    along the sweep, the cutter's angles about the arc centre at both stops, the cutter at
    the first stop), the carrier's frame being the setup frame, mm."""
    import itertools

    sweep = table["guided"]
    centre, middle = table["centre_setup_xy"], table["arc_mid_setup_xy"]
    heading = math.degrees(math.atan2(middle[1] - centre[1], middle[0] - centre[0]))
    r_pin = sweep["pin_radius_mm"]
    pins = [
        [centre[i] + r_pin * _rot([1.0, 0.0], heading + a)[i] for i in range(2)]
        for a in sweep["pins_deg"]
    ]
    chord = [pins[1][i] - pins[0][i] for i in range(2)]
    chord = [v / math.hypot(*chord) for v in chord]
    r1, r2 = sweep["rails_dir"]
    printed = [round(s, 1) for s in sweep["stations_mm"][0]]
    corners = itertools.product(
        (-angle_err, angle_err),
        (-spacing_err, spacing_err),
        (-1, 1),
        (-line_err, line_err),
        (-line_err, line_err),
        (-RULE, RULE),
        (-RULE, RULE),
    )
    for da, dd, turn, e1, e2, d0, d1 in corners:
        grow = dd / 2
        true_pins = [
            [pins[0][i] - grow * chord[i] for i in range(2)],
            [pins[1][i] + grow * chord[i] for i in range(2)],
        ]
        rails_ = [r1, _rot(r2, turn * da)]  # the crossing angle off by da either way
        offsets = (e1, e2)
        first = _stopped(true_pins, rails_, offsets, printed[0] + d0)
        last = _stopped(true_pins, rails_, offsets, printed[1] + d1)
        walls = [
            math.dist(
                _carried(true_pins, rails_, offsets, first + (last - first) * k / steps)[0], centre
            )
            + TOOL_RADIUS
            for k in range(steps + 1)
        ]
        angles = []
        for theta in (first, last):
            x = _carried(true_pins, rails_, offsets, theta)[0]
            bearing = math.degrees(math.atan2(x[1] - centre[1], x[0] - centre[0]))
            angles.append((bearing - heading + 180) % 360 - 180)
        yield walls, angles, _carried(true_pins, rails_, offsets, first)[0]


def _clear(point, box=SWING, radius=TOOL_RADIUS, tol=1e-6):
    return any(
        point[a] + radius <= box[a] - tol or point[a] - radius >= box[a + 3] + tol for a in range(2)
    )


def _with(clearance=0.005, angle_err=0.001):
    inventory = TRAMMEL.replace(
        "pin_clearance_mm = { value = 0.005", f"pin_clearance_mm = {{ value = {clearance}"
    )
    return inventory.replace(
        "rail_angle_error_deg = { value = 0.001", f"rail_angle_error_deg = {{ value = {angle_err}"
    )


@pytest.mark.parametrize(
    ("clearance", "angle_err"),
    [(0.005, 0.001), (0.17, 0.001), (0.005, 0.004)],
    ids=["as-built", "pin-clearance-at-its-limit", "rail-angle-error-at-its-limit"],
)
def test_the_novice_worst_case_cuts_in_band_wherever_the_card_runs(tmp_path, clearance, angle_err):
    # Each fixture the card prints runnable for, at every worst-case corner of it and of
    # the operator's stops, cuts inside the band, reaches both arc ends and goes down in
    # air; and the rule's own cut bound encloses every wall the model finds.
    from prechips.sheet_sweep import established

    row = trammel_row(tmp_path, inventory=_with(clearance, angle_err))
    (table,) = arcs(row, 20)
    sweep = table["guided"]
    assert row.status == "pass" and established(table), row.sentence
    low, high = sweep["band_mm"]
    bound, span = sweep["cut_radius_mm"], sweep["span_deg"]
    for walls, angles, start in _simulate(table, angle_err, 0.01, clearance + 0.01):
        assert low - 1e-6 <= min(walls) and max(walls) <= high + 1e-6
        assert bound[0] - 1e-6 <= min(walls) and max(walls) <= bound[1] + 1e-6
        assert min(angles) <= -span / 2 and max(angles) >= span / 2
        assert _clear(start)


def test_a_fixture_whose_worst_case_leaves_the_band_prints_only_a_stop(tmp_path):
    # Pin clearance past the budget's room: the model finds a wall outside the band, and
    # the card never prints it runnable.
    row, printed = traveler_text(tmp_path, inventory=_with(clearance=0.25))
    assert row.status == "error"
    assert "STOP: contour points not computed — do not run." in printed
    assert "hand lever" not in printed
    # The rule withholds that op's rows; the model runs on the as-built pose with that play.
    (table,) = arcs(trammel_row(tmp_path / "as-built"), 20)
    worst = max(max(walls) for walls, _, _ in _simulate(table, 0.001, 0.01, 0.26))
    assert worst > table["guided"]["band_mm"][1]


def test_stops_too_close_to_the_arc_ends_for_a_rule_are_an_error(tmp_path):
    # A sweep only 0.03° past each end (0.4 mm of station): a stop half a millimetre off
    # could hold the carrier short of the arc, so the rule refuses it.
    row = trammel_row(tmp_path, sweep_deg="21.06")
    assert row.status == "error"
    assert "short of the arc's end" in errors(row)


# --- Codex review of 4c65714 -----------------------------------------------------------


def test_the_start_is_proven_clear_over_the_whole_stop_band_not_samples():
    # The arc runs tangent to X at pose 0, inside the band: its ends and middle clear the
    # box's X face, its tangent point does not, so the start is unproven.
    from prechips.rules.trammel import _arc_clear

    box = [102.95, -50.0, -10.0, 200.0, 50.0, 0.0]
    assert not _arc_clear(box, [0.0, 0.0], 100.0, 0.0, [-10.0, 4.0], 3.0, 1.0)
    for t in (-10.0, -3.0, 4.0):  # what sampling the ends and middle would have seen
        assert 100.0 * math.cos(math.radians(t)) + 3.0 <= box[0]
    assert _arc_clear([103.5, *box[1:]], [0.0, 0.0], 100.0, 0.0, [-10.0, 4.0], 3.0, 1.0)


def test_the_pin_line_gain_is_worst_over_the_rail_angle_tolerance():
    # Codex on #278: at α = 60° ± 20° the symmetric pose's 1 / cos(α/2) is 1.155 nominal
    # but 1.305 at the 80° end; the budget takes the worse.
    from prechips.rules.trammel import _gain_over_angle

    r, centre, heading = 100.0, [0.0, 100.0], -90.0
    directions = trammel.rails(centre, heading, r, [-60.0, 60.0])
    nominal = trammel.line_gain(directions, heading, 0.0, 0.0)
    assert nominal == pytest.approx(1 / math.cos(math.radians(30.0)))
    worst = _gain_over_angle(directions, heading, 0.0, 0.0, 20.0)
    assert worst >= 1 / math.cos(math.radians(40.0)) - 1e-9
    assert _gain_over_angle(directions, heading, 0.0, 0.0, "unknown") is None


def test_an_authored_xy_zero_in_a_trammel_setup_is_an_error(tmp_path):
    # An edge pickup moves the table off the rails' crossing the trammel cuts on.
    from test_guided_sweep import ZERO_Z

    from prechips.inputs import load_bundle
    from prechips.rules import zero_recipe

    plan = trammel_plan(tmp_path)
    zero_x = (
        "[setups.zero.x]\nedge = 'left'\nmethod = 'edge_finder'\nedge_mm = 0.0\n"
        "tool = 'cutter'\ncheck_jog_mm = 10.0\n"
    )
    plan.write_text(plan.read_text(encoding="utf-8") + ZERO_Z + zero_x, encoding="utf-8")
    (row,) = [r for r in zero_recipe.evaluate(load_bundle(plan)) if r.subject == "S1"]
    assert row.status == "error", row.sentence
    assert "zero.x picks up an edge, but the trammel" in row.sentence


def test_an_open_debt_no_printed_value_shows_still_stops_the_card(tmp_path):
    # #258's gate: anything the rule left open (a machine not proven a mill, say) stops
    # the card even when every printed value is proven.
    import copy

    from prechips.sheet_sweep import established, steps

    table, _ = established_card(tmp_path)
    assert table["guided"]["open_debts"] == []
    blocked = copy.deepcopy(table)
    blocked["guided"]["open_debts"] = ["op 20 finish: setup S1's machine kind is unknown"]
    card = steps(blocked, lambda v: f"{v:.3f}", "A", "B", feed=100.0)
    assert card[0].startswith("STOP:") and "machine kind is unknown" in card[0]
    assert not established(blocked)


# --- Codex review of 6651721 -----------------------------------------------------------


def _nearest_stop_overshoot(row):
    """How far past its arc end each stop's worst pose stays, degrees (least of both)."""
    _, sweep = recipe(row)
    bands, half = sweep["stop_bands_deg"], sweep["span_deg"] / 2
    return min(min(abs(v) for v in band) - half for band in bands)


WIDE = LONG_ARC.replace("radius = [800.0, 800.5]", "radius = [798.5, 802.0]")


def test_stops_are_proven_on_the_fixture_at_its_tolerances_not_the_nominal_one(tmp_path):
    # Pin-lines standing off by the clearance plus the rail offset slide the pins along
    # their rails, so a printed station holds the carrier a little nearer the arc than on
    # the nominal fixture. On a band wide enough for 1.2 mm of play, some sweep's stops
    # are proven for the as-built fixture yet refused for the loose one: the proof runs
    # on the fixture at its measured tolerances, not the nominal one.
    loose = _with(clearance=1.2)
    found = False
    for k in range(80):
        sweep = f"{21.03 + k * 0.001:.4f}"
        tight = trammel_row(tmp_path / f"a{k}", sweep_deg=sweep, target=WIDE)
        if not arcs(tight, 20) or recipe(tight)[1]["stops"] != "proven":
            continue
        row = trammel_row(tmp_path / f"b{k}", sweep_deg=sweep, target=WIDE, inventory=loose)
        if "on a fixture at its measured tolerances" in errors(row):
            assert row.status == "error" and "short of the arc's end" in errors(row)
            found = True
            break
    assert found


def test_rail_travel_is_checked_over_the_tolerance_envelope(tmp_path):
    # A near end stop between where the as-built and the loose fixture's carriages can
    # reach: the as-built one passes, the loose one (pin-lines 0.18 mm off) does not.
    as_built = recipe(trammel_row(tmp_path / "a"))[1]["station_envelope_mm"]
    loose = recipe(trammel_row(tmp_path / "b", inventory=_with(clearance=0.17)))[1]
    lows = [min(lo for lo, _ in as_built), min(lo for lo, _ in loose["station_envelope_mm"])]
    assert lows[1] < lows[0]
    near = round(sum(lows) / 2, 4)
    nominal = TRAMMEL.replace("[40.0, 420.0]", f"[{near}, 420.0]")
    assert trammel_row(tmp_path / "nominal", inventory=nominal).status == "pass"
    inventory = _with(clearance=0.17).replace("[40.0, 420.0]", f"[{near}, 420.0]")
    row = trammel_row(tmp_path / "tight", inventory=inventory)
    assert row.status == "error"
    assert "on a fixture at its measured tolerances, beyond the rail's" in errors(row)


# --- Codex review of ad03afc -----------------------------------------------------------


def test_a_controlling_rail_whose_station_turns_back_over_the_sweep_is_an_error(tmp_path):
    # Pins in the supplementary placement: over a ±30° sweep rail 1's station peaks at
    # -16.44° and comes back, so one stop station is met at two poses.
    assert trammel.repeated(163.56, -30.0, 30.0) == pytest.approx(-16.44)
    assert trammel.repeated(-16.44, -12.5, 12.5) is None
    row = trammel_row(tmp_path, pins_deg="[163.56, 196.44]", sweep_deg="60.0")
    assert row.status == "error"
    assert "cannot tell the sweep's ends apart" in errors(row)


def test_a_pins_play_along_its_rail_widens_where_a_stop_holds_the_carrier(tmp_path):
    # Radial play lets the stopped pin sit along the rail off its carriage's station:
    # 0.165 mm more play each way is about 0.024° more stop band at 13.9 mm a degree.
    def width(row):
        bands = recipe(row)[1]["stop_bands_deg"]
        return min(band[1] - band[0] for band in bands)

    tight = width(trammel_row(tmp_path / "a"))
    loose = width(trammel_row(tmp_path / "b", inventory=_with(clearance=0.17)))
    assert loose - tight > 0.02


BROAD = LONG_ARC.replace("radius = [800.0, 800.5]", "radius = [770.0, 830.0]")


def test_the_cut_bound_holds_large_pin_line_offsets_exactly(tmp_path):
    # Codex on #278: ±10 mm of pin-line offset moves the radius by more than its radial
    # projection. The bound now adds the exact second-order term, and the independent
    # model's walls stay inside it at every corner.
    inventory = TRAMMEL.replace(
        "pin_clearance_mm = { value = 0.005", "pin_clearance_mm = { value = 5.0"
    ).replace("rail_offset_mm = { value = 0.01", "rail_offset_mm = { value = 5.0")
    row = trammel_row(tmp_path, inventory=inventory, target=BROAD)
    (table,) = arcs(row, 20)
    sweep = table["guided"]
    terms = sweep["error_terms_mm"]
    assert terms["pin_lines_second"] > 0.5
    bound = sweep["cut_radius_mm"]
    walls = [w for ws, _, _ in _simulate(table, 0.001, 0.01, 10.0, steps=100) for w in ws]
    assert bound[0] - 1e-6 <= min(walls) and max(walls) <= bound[1] + 1e-6
    # The second-order bound itself: sqrt((R + x_r)² + x_t²) − R − x_r ≤ x_t² / (2 (R − x_r))
    # for the largest tangential slide the pin-lines allow.
    r, x_r = sweep["pin_radius_mm"], terms["pin_lines"]
    x_t = sweep["tangent_gain"] * 10.0
    assert math.hypot(r + x_r, x_t) - r - x_r <= terms["pin_lines_second"] + 1e-9
