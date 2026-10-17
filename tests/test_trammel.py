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
    assert "STOP: guided sweep not established (cut radius unproven" in printed
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
# The disc swept along the arc: its annular sector and a half disc at each end.
want = (2 * R * r * math.radians(sweep) + math.pi * r * r) * height
with open(out, "w") as handle:
    json.dump({"exact": exact.Volume, "chords": chords.Volume, "want": want}, handle)
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
