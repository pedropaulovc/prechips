"""Guided-sweep manual arcs (docs/plan.md "Manual arcs", docs/rules-coordinates.md).

An arc whose centre is too far off the part for a rotary table is cut by sweeping the work
under a locked cutter in a fixture that holds it to rotation about that centre: a swing
arm on a ``pivot`` pin at the centre, or a sled whose ``rail`` (an arc concentric with the
part) is pushed against two rollers fixed in the table's T-slots. The table is locked and
the fixture moves, so no handwheel moves at all while it cuts, never two at once.

The cut radius is set by touching the stationary cutter itself to a named ``master`` (a
``setting_bar`` seated on the pivot pin, or a ``master_arc`` pinned on the fixture),
along a setup axis that lies on the cutter's radial line, then locking X and Y: the
cutter's own size never enters it. The master's declared radius limits, widened by how
far the guide lets the arc centre move between the touch-off and the cut (a swing arm's
pivot play; a rail's form error and roller runout, carried through the two rollers'
geometry), must lie inside the arc's radial band. An undeclared or unmeasured guide or
master error is debt, never a perfect guide.
"""

from __future__ import annotations

import itertools
import math

from .. import trig
from ..measurements import length_debt, length_fact, limits_debt, limits_fact, record_debt
from .coordinates import _JOIN_TOL, _WALL_TOL, _grid, _pair, _samples, dro_grid
from .resolution import UNKNOWN, identity, number, record, resolve, uncertain

METHOD = "guided_sweep"
# The fixture kind each guide rides on: a swing arm pivots on its pin, a sled on its rail.
FIXTURE_KINDS = {"pivot": "swing_arm", "rail": "arc_sled"}
MASTER_KINDS = frozenset({"setting_bar", "master_arc"})
# (setup axis index, sign): which axis lies on the cutter's radial line, and on which side
# of the arc centre the cutter stands.
TOUCH_AXES = {"+X": (0, 1), "-X": (0, -1), "+Y": (1, 1), "-Y": (1, -1)}
# Each guide's consumed fixture facts: (field, require a fact-local measurement, words).
_GUIDE_FACTS = {
    "pivot": (("pivot_play", True, "pivot play"),),
    "rail": (
        ("rail_radius", False, "rail radius"),
        ("rail_form_error", True, "rail form error"),
        ("roller_runout", True, "roller runout"),
    ),
}


def swept_angles(start, end, step, sweep, full):
    """A guided sweep's cutter-centre sample angles (feature angle convention, see
    ``coordinates._arc``): the arc's own samples (:func:`coordinates._samples`, exact ends
    included) extended at both ends by half the declared ``sweep``'s excess over the
    arc's span, with the arc's ends kept as rows so the kernel judges the cutter where the
    arc ends as well as where the sweep stops. A full circle, an unknown or short sweep
    keeps the arc's own samples."""
    arc = _samples(start, end, step)
    if full or not arc or not number(sweep):
        return arc
    over = (sweep - abs(end - start)) / 2
    if over <= _JOIN_TOL:
        return arc
    sign = 1 if end >= start else -1
    values = _samples(start - sign * over, end + sign * over, step) + [start, end]
    values = sorted(values, reverse=sign < 0)
    kept = [values[0]]
    for value in values[1:]:
        if abs(value - kept[-1]) > _JOIN_TOL:
            kept.append(value)
    return kept


def roller_gain(rollers):
    """How far the cut radius moves per unit of radial contact error at the rollers, worst
    case over both contacts: ``(|sin a| + |sin b|) / |sin(a - b)|`` for rollers at ``a``
    and ``b`` degrees about the arc centre from the cutter's radial line. The sled's
    centre translates so each roller's contact moves its own error along its own radial
    line; the cut moves by that translation along the cutter's. None when both rollers lie
    on one line through the centre: they leave the sled free to slide along it."""
    a, b = (math.radians(v) for v in rollers)
    det = trig.sin(a - b)
    if abs(det) < 1e-9:
        return None
    return (abs(trig.sin(a)) + abs(trig.sin(b))) / abs(det)


def _fact(item, field, measured, category, key, debts, measurements, words):
    """A consumed guide or master length (mm), or UNKNOWN with its debt and ``measure:``
    instruction; a negative value proves nothing."""
    fact = length_fact(item, field, require_measured=measured)
    value = fact["value"] if fact["verified"] else UNKNOWN
    if number(value) and value >= 0 and (field != "rail_radius" or value > 0):
        return value
    debts.append(f"the {words} of {key} is unknown or not measured")
    debt = length_debt(item, field, category, key, require_measured=measured)
    if debt is None:
        debt = record_debt(item, category, key, field, require_measured=measured)
    if debt:
        measurements.append(debt)
    return UNKNOWN


def _flagged(item, fields, category, key, measurements):
    """Measurement debts for an item flagged to verify as a whole: each consumed field."""
    for field, measured in fields:
        limits = field == "radius_limits"
        debt = (limits_debt if limits else length_debt)(
            item, field, category, key, require_measured=measured
        )
        if debt is None and item.get("verify") in (True, UNKNOWN):
            debt = record_debt(item, category, key, field)
        if debt:
            measurements.append(debt)


def _carrier(bundle, setup, sweep, guide, errors, debts, measurements, record_):
    """The guide fixture's consumed facts (mm) by field, or None when it proves none."""
    reference = sweep.get("fixture", UNKNOWN)
    record_["fixture"] = reference
    item = resolve(bundle, "fixtures", reference) if isinstance(reference, str) else None
    if not isinstance(item, dict) or reference == UNKNOWN:
        debts.append(f"the sweep fixture {reference} is not in the fixtures inventory")
        return None
    category, key = identity(bundle, reference, "fixtures")
    record_["fixture_name"] = item.get("name", reference)
    kind = item.get("kind", UNKNOWN)
    hold = record(setup.get("hold")).get("fixture")
    if identity(bundle, hold, "workholding") != (category, key):
        errors.append(
            f"the sweep fixture {reference} does not carry the work: it is not setup "
            f"{setup['id']}'s hold.fixture"
        )
    if guide not in FIXTURE_KINDS:
        return None
    if kind != FIXTURE_KINDS[guide]:
        if kind == UNKNOWN:
            debts.append(f"the sweep fixture {reference}'s kind is unknown")
        else:
            errors.append(
                f"the sweep fixture {reference} is a {kind}, not the {FIXTURE_KINDS[guide]} "
                f"a {guide} guide rides on"
            )
        return None
    fields = _GUIDE_FACTS[guide]
    if uncertain(item):
        debts.append(f"the sweep fixture {reference} is flagged to verify")
        _flagged(item, [(f, m) for f, m, _ in fields], category, key, measurements)
        return None
    found = {
        field: _fact(item, field, measured, category, key, debts, measurements, words)
        for field, measured, words in fields
    }
    record_.update({f"{field}_mm": value for field, value in found.items()})
    return found


def _master(bundle, sweep, guide, errors, debts, measurements, record_):
    """The master's radius limits [least, greatest] mm, or None when unproven."""
    reference = sweep.get("master", UNKNOWN)
    record_["master"] = reference
    item = resolve(bundle, "gauges", reference) if isinstance(reference, str) else None
    if not isinstance(item, dict) or reference == UNKNOWN:
        debts.append(f"the touch-off master {reference} is not in the gauges inventory")
        return None
    category, key = identity(bundle, reference, "gauges")
    kind = item.get("kind", UNKNOWN)
    record_.update(master_kind=kind, master_name=item.get("name", reference))
    if kind not in MASTER_KINDS:
        if kind == UNKNOWN:
            debts.append(f"the touch-off master {reference}'s kind is unknown")
        else:
            errors.append(
                f"the touch-off master {reference} is a {kind}, not a setting_bar or master_arc"
            )
        return None
    if guide == "rail" and kind == "setting_bar":
        errors.append(
            f"the setting bar {reference} seats on a pivot pin, and a rail guide has none: "
            "touch off a master_arc pinned on the sled"
        )
        return None
    if uncertain(item):
        debts.append(f"the touch-off master {reference} is flagged to verify")
        _flagged(item, [("radius_limits", True)], category, key, measurements)
        return None
    fact = limits_fact(item, "radius_limits", require_measured=True)
    if not fact["verified"]:
        debts.append(f"the radius limits of {reference} are unknown or not measured")
        debt = limits_debt(item, "radius_limits", category, key, require_measured=True)
        if debt:
            measurements.append(debt)
        return None
    record_["master_radius_mm"] = fact["value"]
    return fact["value"]


def _rail(sweep, sweep_deg, errors, debts, record_):
    """The rollers' gain on the cut (:func:`roller_gain`), or None when unproven; the rail
    must bear on both rollers through the whole sweep."""
    rollers, rail = sweep.get("rollers_deg", UNKNOWN), sweep.get("rail_deg", UNKNOWN)
    record_.update(rollers_deg=rollers, rail_deg=rail)
    if not _pair(rollers):
        debts.append("contour.sweep.rollers_deg (the two rollers' angles) is unknown")
        return None
    gain = roller_gain(rollers)
    if gain is None:
        errors.append(
            f"the rollers at {rollers[0]:g}° and {rollers[1]:g}° lie on one line through "
            "the arc centre: they leave the sled free to slide along it"
        )
        return None
    record_["roller_gain"] = gain
    if not _pair(rail):
        debts.append(
            "contour.sweep.rail_deg (the rail's ends) is unknown, so the rail is not proven "
            "to bear on both rollers through the sweep"
        )
    elif number(sweep_deg):
        low, high = sorted(rail)
        for angle in rollers:
            if not low + sweep_deg / 2 - _JOIN_TOL <= angle <= high - sweep_deg / 2 + _JOIN_TOL:
                errors.append(
                    f"the roller at {angle:g}° runs off the rail (ends {low:g}° to {high:g}°) "
                    f"during the {sweep_deg:g}° sweep"
                )
    return gain


def _sweep_span(arc, sweep_deg, label, errors, debts, record_, scale, grid):
    """Check the declared sweep reaches both arc ends (to within one DRO ``grid`` step of
    cutter travel: where a sweep stops is a mark, not a dial); record its overrun past
    each end and the cutter's path along the work, mm."""
    span, radius = arc.get("span_deg", UNKNOWN), arc["cutter_centre_radius_mm"]
    record_.update(span_deg=span, sweep_deg=sweep_deg)
    if not number(sweep_deg) or sweep_deg <= 0:
        debts.append(f"{label}: contour.sweep.sweep_deg is unknown")
        return
    if not number(span):
        debts.append(f"{label}: the arc's span is unknown")
        return
    tolerance = math.degrees(grid[0] / radius) if number(radius) and radius > 0 else 0.0
    need = 360.0 if arc["full_circle"] else span
    if sweep_deg < need - tolerance:
        errors.append(
            f"{label}: the {sweep_deg:g}° sweep stops short of the arc: the cutter needs "
            f"{need:.4f}° to reach "
            + ("all the way round" if arc["full_circle"] else "both its ends")
        )
        return
    over = 0.0 if arc["full_circle"] else max(0.0, (sweep_deg - span) / 2)
    if number(radius):
        record_.update(
            overrun_mm=math.radians(over) * radius * scale,
            path_mm=math.radians(min(sweep_deg, 360.0)) * radius * scale,
        )


def guided(bundle, setup, op, arc, band, label, scale):
    """(errors, debts): the guided-sweep recipe for ``arc`` (its rows the cutter-centre arc
    in cutting order, over the whole sweep), stamped as ``guided``.

    ``band`` is the feature's radial band (plan units; a rough stage's moved off the line
    by its allowance) and ``scale`` mm per plan unit. The recipe names the guide fixture
    (the setup's ``hold.fixture``), the master the stationary cutter is touched to along
    ``touch_axis``, the cut radius that touch sets worst case and the sweep: the fixture
    turns the work ``rotation`` (viewed from above) through ``sweep_deg``, centred on the
    arc. A rough stage backs the cutter off the touch along that axis by its allowance,
    rounded off the line onto the DRO grid: the only handwheel move, one axis."""
    contour = record(op.get("contour"))
    sweep = record(contour.get("sweep"))
    errors, debts, measurements = [], [], []
    guide = sweep.get("guide", UNKNOWN)
    convex = arc["cutter_centre_radius_mm"] > arc["wall_radius_mm"]
    record_ = {
        "guide": guide,
        "fixture": UNKNOWN,
        "master": UNKNOWN,
        "touch_axis": sweep.get("touch_axis", UNKNOWN),
        "convex": convex,
        "radius_mm": arc["wall_radius_mm"] * scale,
        "locked_axes": ["X", "Y"],
        "moves": "fixture",
        "master_radius_mm": UNKNOWN,
        "centre_error_mm": UNKNOWN,
        "back_off_mm": UNKNOWN,
        "cut_radius_mm": UNKNOWN,
        "band_mm": UNKNOWN,
        "rotation": UNKNOWN,
        "overrun_mm": UNKNOWN,
        "path_mm": UNKNOWN,
    }
    arc["guided"] = record_
    if guide not in FIXTURE_KINDS:
        debts.append(f"{label}: contour.sweep.guide is neither pivot nor rail")
    found = _carrier(bundle, setup, sweep, guide, errors, debts, measurements, record_)
    master = _master(bundle, sweep, guide, errors, debts, measurements, record_)
    sweep_deg = sweep.get("sweep_deg", UNKNOWN)
    gain = _rail(sweep, sweep_deg, errors, debts, record_) if guide == "rail" else None
    grid = dro_grid(bundle, setup)
    _sweep_span(arc, sweep_deg, label, errors, debts, record_, scale, grid)
    axis = sweep.get("touch_axis", UNKNOWN)
    if axis not in TOUCH_AXES:
        debts.append(f"{label}: contour.sweep.touch_axis (the cutter's radial axis) is unknown")
    else:
        # Toward the centre to touch a convex arc's master from outside, away from it on a
        # concave one: the cutter approaches from the scrap side either way.
        index, side = TOUCH_AXES[axis]
        feed = -side if convex else side
        record_["touch_feed"] = ("-" if feed < 0 else "+") + "XY"[index]
    # How far the arc centre moves on the guide between the touch-off and the cut.
    widen = UNKNOWN
    if found is not None and guide == "pivot" and number(found["pivot_play"]):
        # A setting bar seated on the pin sets the cutter from the pin's own axis: the
        # beam's play moves the work once, at the cut. A master on the arm moves with the
        # beam at the touch-off too, so its play counts at both.
        bar = record_.get("master_kind") == "setting_bar"
        widen = found["pivot_play"] * (1 if bar else 2)
    elif found is not None and gain is not None:
        form, runout = found["rail_form_error"], found["roller_runout"]
        if number(form) and number(runout):
            # Each contact errs by the rail's form error plus half its roller's runout, at
            # the touch-off and again at the cut: twice that, through the rollers' gain.
            widen = 2 * gain * (form + runout / 2)
    record_["centre_error_mm"] = widen
    allowance = arc.get("allowance_mm", 0.0)
    outward = 1 if convex else -1
    back = UNKNOWN
    if number(allowance):
        step, decimals = grid
        back = _grid(allowance / scale, step, decimals, True) if allowance > 0 else 0.0
        record_["back_off_mm"] = back * scale
        if axis in TOUCH_AXES and back:
            index, side = TOUCH_AXES[axis]
            record_["back_off_dro"] = round(outward * side * back, decimals)
    else:
        debts.append(f"{label}: its allowance is unknown, so no back-off is proven")
    proven = master is not None and number(widen) and number(back)
    if proven:
        shifted = outward * back * scale
        record_["cut_radius_mm"] = [master[0] + shifted - widen, master[1] + shifted + widen]
    if band is None:
        debts.append(f"{label}: its radial band is unknown, so the cut radius is unproven")
    elif number(allowance):
        shift = outward * allowance
        low, high = band[0] * scale + shift, band[1] * scale + shift
        record_["band_mm"] = [low, high]
        cut = record_["cut_radius_mm"]
        if proven and (cut[0] < low - _WALL_TOL or cut[1] > high + _WALL_TOL):
            why = f"the master's R{master[0]:g} to R{master[1]:g} mm"
            if widen:
                why += f" widened by the guide's {widen:.3f} mm centre error"
            if back:
                why += f" and backed off {back * scale:g} mm"
            errors.append(
                f"{label}: {why} cuts R{cut[0]:.3f} to R{cut[1]:.3f} mm, outside the "
                f"R{low:g} to R{high:g} mm band"
            )
    _rotation(arc, label, debts, record_, scale)
    if measurements:
        by_id = {entry["id"]: entry for entry in measurements}
        arc["measurements"] = [*arc.get("measurements", []), *by_id.values()]
    return errors, debts


def _rotation(arc, label, debts, record_, scale):
    """The way the fixture turns the work under the cutter, viewed from above: against the
    cutter's travel about the centre along its rows (their cutting order)."""
    points = [row["setup_xy"] for row in arc["rows"]]
    centre = arc["centre_setup_xy"]
    if (
        arc["cut_order"] == UNKNOWN
        or len(points) < 2
        or not _pair(centre)
        or not all(_pair(p) for p in points)
    ):
        debts.append(f"{label}: its cutting order or cutter path is unknown")
        return
    thetas = [math.degrees(trig.atan2(p[1] - centre[1], p[0] - centre[0])) for p in points]
    travel = sum((b - a + 180.0) % 360.0 - 180.0 for a, b in itertools.pairwise(thetas))
    record_["rotation"] = "clockwise" if travel > 0 else "counterclockwise"
