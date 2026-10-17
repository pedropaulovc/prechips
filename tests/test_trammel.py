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


def trammel_plan(tmp_path, *, allowance=None, hold="fixture = 'tram'", inventory=TRAMMEL, **more):
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", trammel_contour(**more), allowance=allowance),
        hold=hold,
        target=LONG_ARC,
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
    # The rows run on the pin-defined circle, not the drawing's R797.
    for r in table["rows"]:
        assert math.dist(r["setup_xy"], table["centre_setup_xy"]) == pytest.approx(
            sweep["pin_radius_mm"]
        )
        assert r["dro_xy"] == r["setup_xy"]
    assert table["exact_arc"]["radius"] == pytest.approx(sweep["pin_radius_mm"])
    # The error budget: rail angle, spacing and both pin-lines.
    terms = sweep["error_terms_mm"]
    assert terms["rail_angle"] == pytest.approx(sweep["radius_per_deg_mm"] * 0.001)
    assert terms["pin_spacing"] == pytest.approx(sweep["radius_per_spacing"] * 0.01)
    assert terms["pin_lines"] == pytest.approx(sweep["line_gain"] * 0.015)
    widen = sum(terms.values())
    assert sweep["centre_error_mm"] == pytest.approx(widen)
    assert sweep["cut_radius_mm"] == pytest.approx([800.25 - widen, 800.25 + widen], abs=1e-3)
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
    inventory = TRAMMEL.replace(
        f"inner = {{ value = {SPACING}, {MEASURED} }}",
        f"inner = {{ value = {SPACING}, {MEASURED.replace("status = 'measured'", "status = 'assumed'")} }}",
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
