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
from .coordinates import _JOIN_TOL, _WALL_TOL, _grid, _pair, _samples, dro_grid, dro_grid_debt
from .resolution import UNKNOWN, authored, identity, number, record, resolve, uncertain

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


def touch_set(setup):
    """The ops of ``setup`` when every spindle op in it (one with a ``tool``) is a guided
    sweep, else []: such a setup's X and Y are set by each sweep's touch-off against its
    master and stay locked, so its zero picks up no X/Y edge. Manual ops (deburr,
    inspect, scribe) carry no tool and do not count."""
    swept = []
    for op in setup.get("ops") or []:
        op = record(op)
        if "tool" not in op:
            continue
        if record(op.get("contour")).get("method") != METHOD:
            return []
        swept.append(op.get("op"))
    return swept


def unmodelled(bundle, setup, rule):
    """The ``check:`` debts ``rule`` (``"travel"`` or ``"headroom"``) owes for each guided
    sweep op in ``setup``: what neither models while the fixture moves, so the finding is
    unknown, never a pass. ``travel``: the fixture's swept footprint (a swing arm's pivot
    post, possibly on a table extension, or a sled pushed along its rollers) against the
    table, column and way covers. ``headroom``: the spindle stack and fixture clearance,
    judged at the setup pose only, at every pose of the sweep."""
    debts = []
    for op in setup.get("ops") or []:
        op = record(op)
        contour = record(op.get("contour"))
        if contour.get("method") != METHOD:
            continue
        sweep = record(contour.get("sweep"))
        fixture = sweep.get("fixture", UNKNOWN)
        angle = sweep.get("sweep_deg", UNKNOWN)
        turn = f"{angle:g}°" if number(angle) else "its whole sweep"
        if rule == "travel":
            what = (
                "the pivot post at the arc centre, on the table or a table extension, and the "
                "arm swung"
                if sweep.get("guide") == "pivot"
                else "the rollers in the T-slots and the sled pushed"
            )
            debts.append(
                f"op {op.get('op', UNKNOWN)} guided sweep: the swept footprint of {fixture} is "
                f"not modelled; check: with Z raised and the spindle stopped, {what} through "
                f"{turn} clear the column, the table ends and the way covers"
            )
        else:
            debts.append(
                f"op {op.get('op', UNKNOWN)} guided sweep: the spindle stack and fixture "
                f"clearance are judged with {fixture} at its setup pose only; check: the dry "
                f"pass from stop to stop ({turn}) clears the spindle nose, holder and column "
                "at every pose"
            )
    return debts


def swept_angles(start, end, step, sweep, full):
    """A guided sweep's cutter-centre sample angles (feature angle convention, see
    ``coordinates._arc``): the arc's own samples (:func:`coordinates._samples`, exact ends
    included) extended at both ends by half the declared ``sweep``'s excess over the
    arc's span, with the arc's ends kept as rows so the kernel judges the cutter where the
    arc ends as well as where the sweep stops. A full circle, an unknown or short sweep
    keeps the arc's own samples."""
    arc = _samples(start, end, step)
    # A sweep of a full turn or more is an error (:func:`_sweep_span`): never expanded, so a
    # huge one cannot run the sampling away.
    if full or not arc or not number(sweep) or sweep >= 360.0:
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


def _item_flagged(bundle, category, key):
    """Whether the inventory item ``key`` is flagged to verify as a whole, as the shop list
    states it: its own ``verify``, ``present`` or coverage, or any record about the item
    rather than one of its measured facts (its ``source`` provenance, say). A flag on one
    measured fact (a ``_mm`` / ``_in`` record) does not count, though resolving an item
    folds those into its ``verify``: each fact the sweep consumes is checked on its own,
    and one it does not consume (a picture-only dimension, a bed height headroom reads)
    must not leave the cut unproven. A selected member (``bars/r800``) is read the same
    way beside its set."""
    parent = authored(bundle, category, key)
    stated = [parent]
    member = key.partition("/")[2] if isinstance(key, str) else ""
    if member:
        chosen = record(parent.get("members")).get(member, {})
        if chosen == UNKNOWN:
            return True
        stated.append(record(chosen))
    return any(_flagged_as_a_whole(item) for item in stated)


def _flagged_as_a_whole(item):
    if (
        item.get("verify") is True
        or item.get("verify") == UNKNOWN
        or item.get("present") == UNKNOWN
        or "verify" in str(item.get("coverage", "")).lower()
    ):
        return True
    return any(
        uncertain(value)
        for name, value in item.items()
        if isinstance(value, dict) and name != "members" and not name.endswith(("_mm", "_in"))
    )


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
    if _item_flagged(bundle, category, key):
        debts.append(f"the sweep fixture {reference} is flagged to verify")
        _flagged(item, [(f, m) for f, m, _ in fields], category, key, measurements)
        return None
    found = {
        field: _fact(item, field, measured, category, key, debts, measurements, words)
        for field, measured, words in fields
    }
    record_.update({f"{field}_mm": value for field, value in found.items()})
    if guide == "rail":
        orbit = _roller_orbit(item, found["rail_radius"], category, key, debts, measurements)
        found["roller_orbit"] = orbit
        record_["roller_orbit_mm"] = orbit
    return found


def _roller_orbit(item, rail, category, key, debts, measurements):
    """The rollers' centres' least distance (mm) from the arc centre, the radius the rail
    bound turns its finite terms on: at least the rail radius for rollers outside the rail
    (``rail_side = "outer"``), whatever their size; the rail radius less half the measured
    roller diameter for rollers inside it. UNKNOWN with a debt when the side is undeclared
    or an inside roller's diameter is unmeasured or no smaller than the rail's."""
    if not number(rail):
        return UNKNOWN
    side = item.get("rail_side")
    if side == "outer":
        return rail
    if side != "inner":
        debts.append(
            f"declare {key}'s rail_side (outer or inner): which side the rollers bear on sets "
            "how far their centres orbit, which the rail's bound turns on"
        )
        return UNKNOWN
    dia = _fact(item, "roller_dia", True, category, key, debts, measurements, "roller diameter")
    if not number(dia):
        return UNKNOWN
    if rail - dia / 2 <= 0:
        debts.append(f"a Ø{dia:g} mm roller cannot bear inside {key}'s R{rail:g} mm rail")
        return UNKNOWN
    return rail - dia / 2


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
    if _item_flagged(bundle, category, key):
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


def _rail(sweep, errors, debts, record_):
    """The rollers' gain on the cut (:func:`roller_gain`), or None when unproven. Whether
    the rail bears on both rollers through the travel the printed stops set is checked
    once they are placed (:func:`_rail_coverage`)."""
    rollers, rail = sweep.get("rollers_deg", UNKNOWN), sweep.get("rail_deg", UNKNOWN)
    record_.update(rollers_deg=rollers, rail_deg=rail, rail_coverage=UNKNOWN)
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
    return gain


def _rail_coverage(arc, sweep, found, record_, errors, debts):
    """``rail_coverage`` over the travel the printed stops set, not the authored
    ``sweep_deg``: the stops sit on the arc ends' radial strokes, so the fixture turns the
    arc's span plus, at each end, the printed overrun and the stop's placement slop
    (``stop_slop_mm``) measured on the shortest touch reach (``stop_travel_deg``). A sweep
    short of the arc within its tolerance still travels the whole span. Each end of the
    rail is narrowed further by how far a roller's contact may sit off its printed angle
    (``roller_slack_deg``, :func:`_roller_slack`)."""
    span, overrun = arc.get("span_deg"), record_.get("stop_overrun_mm")
    slop, reach = record_.get("stop_slop_mm"), record_.get("touch_reach_min_mm")
    if not (number(span) and number(overrun) and number(slop) and number(reach) and reach > 0):
        debts.append(
            "the travel the stops set is unknown, so the rail is not proven to bear on both "
            "rollers through it"
        )
        return
    travel = span + 2 * math.degrees((overrun + slop) / reach)
    record_["stop_travel_deg"] = travel
    rollers, rail = sweep.get("rollers_deg"), sweep.get("rail_deg")
    slack = _roller_slack(rollers, found)
    if slack is None:
        debts.append(
            "the rollers' placement error is unbounded, so the rail is not proven to bear on "
            "both rollers through the sweep"
        )
        return
    record_["roller_slack_deg"] = slack
    record_["rail_coverage"] = _on_rail(rollers, rail, travel, errors, debts, slack)


def _roller_slack(rollers, found):
    """How far (degrees about the arc centre) a roller's contact on the rail may sit off
    its printed angle: the roller set to a contact printed to 0.1 mm on X and on Y (the
    diagonal of two half-steps), plus the sled's own shift through the rollers when each
    contact errs by that, the rail's form error and half its roller's runout
    (:func:`_contact_error`), over the rail's radius. None when unknown or unbounded."""
    found = found or {}
    form, runout, radius, orbit = (
        found.get(k) for k in ("rail_form_error", "roller_runout", "rail_radius", "roller_orbit")
    )
    if not (_pair(rollers) and number(form) and number(runout) and number(radius) and radius > 0):
        return None
    half = ROLLER_PRINT_MM / 2
    placed = math.hypot(half, half)
    contact = _contact_error(rollers, placed + form + runout / 2, orbit)
    if contact is None:
        return None
    a, b = (math.radians(v) for v in rollers)
    shift = 2 * contact / abs(trig.sin(a - b))
    return math.degrees((placed + shift) / radius)


def _second_order(shift, radius):
    """How much more than ``shift`` (mm) a point ``radius`` mm from a centre can change its
    distance from it when the centre moves ``shift``: at most ``shift² / (2 (radius -
    shift))``. None when the shift reaches half the radius, where no bound is claimed."""
    if not (number(radius) and radius > 0 and number(shift)) or shift >= radius / 2:
        return None
    return shift * shift / (2 * (radius - shift))


def rail_cut_shift(rollers, per_contact, orbit, cutter_radius):
    """The most the cut radius moves at one pose (mm) when each roller contact errs by up
    to ``per_contact`` mm along its radial line: a finite bound, never the linearized gain
    alone. The sled's centre shift ``d`` meets each contact's constraint to within ``q = d²
    / (2 (ρ - d))`` (:func:`_second_order`), ρ the roller centres' least distance from the
    arc centre (``orbit``, :func:`_roller_orbit`); ``|d| <= 2 (e + q) / |sin(a - b)|`` for
    rollers at ``a`` and ``b``, solved as a fixed point. The cut then moves by the rollers'
    gain (:func:`roller_gain`) on ``e + q`` plus the cutter's own second-order term at
    ``cutter_radius`` mm. None when the rollers leave the sled free or no bound converges
    inside half of either radius."""
    gain = roller_gain(rollers)
    contact = _contact_error(rollers, per_contact, orbit)
    if gain is None or contact is None:
        return None
    a, b = (math.radians(v) for v in rollers)
    term = _second_order(2 * contact / abs(trig.sin(a - b)), cutter_radius)
    if term is None:
        return None
    return gain * contact + term


def _contact_error(rollers, per_contact, orbit):
    """``e + q`` (mm): each roller contact's radial error ``e`` (``per_contact``) plus the
    finite term ``q`` the sled centre's shift leaves at it (:func:`rail_cut_shift`) on the
    rollers' least ``orbit`` about the arc centre, solved as a fixed point. None when the
    rollers leave the sled free, ``e`` or the orbit is unknown or no bound converges inside
    half the orbit."""
    a, b = (math.radians(v) for v in rollers)
    spread = abs(trig.sin(a - b))
    if spread < 1e-9 or not (number(per_contact) and per_contact >= 0):
        return None
    error = 0.0
    for _ in range(200):
        shift = 2 * (per_contact + error) / spread
        bound = _second_order(shift, orbit if number(orbit) else None)
        if bound is None:
            return None
        settled = bound - error <= 1e-12
        error = bound
        if settled:
            return per_contact + error
    return None


def rail_transverse_shift(rollers, per_contact, orbit):
    """The most the sled's centre stands beside the cutter's radial line (mm) when each
    roller contact errs by up to ``per_contact`` mm along its radial line: the sideways
    part of the shift :func:`roller_gain` measures along the line, ``(|cos a| + |cos b|) /
    |sin(a - b)|`` on the finite contact error (:func:`_contact_error`) for rollers at
    ``a`` and ``b`` degrees, on the rollers' least ``orbit``. Rollers close in angle
    amplify it. None when the rollers leave the sled free or no bound converges."""
    contact = _contact_error(rollers, per_contact, orbit)
    if contact is None:
        return None
    a, b = (math.radians(v) for v in rollers)
    return (abs(trig.cos(a)) + abs(trig.cos(b))) / abs(trig.sin(a - b)) * contact


def _wrap(angle):
    """``angle`` (degrees) on (-180, 180]."""
    return -((-angle + 180.0) % 360.0 - 180.0)


def _on_rail(rollers, rail, sweep_deg, errors, debts, slack=0.0):
    """Whether each roller bears on the rail through the whole sweep: ``"proven"``,
    ``"off"`` (an error per roller) or ``"unknown"`` (a debt). A roller must stand within
    the rail's arc narrowed at both ends by half the sweep and its own placement ``slack``
    (degrees). The rail is the shorter arc
    between its two ends (a sled's rail is under half a turn), wherever it lies about the
    centre, across the ±180° line included; ends half a turn apart leave its side
    unknown."""
    turn = _wrap(rail[1] - rail[0])
    if abs(abs(turn) - 180.0) <= _JOIN_TOL:
        debts.append(
            f"the rail's ends at {rail[0]:g}° and {rail[1]:g}° are half a turn apart, so which "
            "side of the arc centre the rail runs is unknown"
        )
        return UNKNOWN
    middle, reach = rail[0] + turn / 2, abs(turn) / 2 - sweep_deg / 2 - slack
    coverage = "proven"
    for angle in rollers:
        if abs(_wrap(angle - middle)) > reach + _JOIN_TOL:
            errors.append(
                f"the roller at {angle:g}° runs off the rail (ends {rail[0]:g}° to "
                f"{rail[1]:g}°) during the {sweep_deg:.3f}° the stops let the fixture turn"
            )
            coverage = "off"
    return coverage


def _sweep_span(arc, sweep_deg, label, errors, debts, record_, scale, grid):
    """Check the declared sweep reaches both arc ends (to within one DRO ``grid`` step of
    cutter travel: where a sweep stops is a mark, not a dial) and stays under a full turn;
    record its overrun past each end and the cutter's path along the work, mm.

    Two stop blocks bound the sweep, one at each end pose. A full circle, or a sweep of a
    full turn or more, brings the fixture back to its start pose, so no pair of stops
    bounds it: an error (a full circle is cut on a rotary table)."""
    span, radius = arc.get("span_deg", UNKNOWN), arc["cutter_centre_radius_mm"]
    record_.update(span_deg=span, sweep_deg=sweep_deg)
    if arc["full_circle"]:
        errors.append(
            f"{label}: a guided sweep cannot cut a full circle: its sweep starts and ends at "
            "one fixture pose, so no pair of stop blocks bounds it; cut it on a rotary_table"
        )
        return
    if not number(sweep_deg) or sweep_deg <= 0:
        debts.append(f"{label}: contour.sweep.sweep_deg is unknown")
        return
    if not number(span):
        debts.append(f"{label}: the arc's span is unknown")
        return
    if sweep_deg >= 360.0:
        errors.append(
            f"{label}: the {sweep_deg:g}° sweep is a full turn or more: it brings the fixture "
            "back to its start pose, so no pair of stop blocks bounds it"
        )
        return
    tolerance = math.degrees(grid[0] / radius) if number(radius) and radius > 0 else 0.0
    if sweep_deg < span - tolerance:
        errors.append(
            f"{label}: the {sweep_deg:g}° sweep stops short of the arc: the cutter needs "
            f"{span:.4f}° to reach both its ends"
        )
        return
    over = max(0.0, (sweep_deg - span) / 2)
    if number(radius):
        overrun = math.radians(over) * radius * scale
        # The printed stop overrun (stop_overrun_mm) is measured on the touch path, where
        # the stops are set: :func:`_start_clear` records it.
        record_.update(overrun_mm=overrun, path_mm=math.radians(sweep_deg) * radius * scale)


def _touch_reaches(arc, master, convex):
    """The cutter-centre reaches (mm) the master's radius limits give at the touch: each
    limit plus the cutter's radius on a convex arc, less it on a concave one; [] when
    unknown."""
    cutter = arc.get("cutter_radius_mm")
    if master is None or not number(cutter):
        return []
    return [limit + (cutter if convex else -cutter) for limit in master]


def _margin(bundle, setup, arc, label, debts, record_, scale, grid):
    """The one explicit safety margin every geometric proof of the sweep carries:
    ``margin_mm``, the machine's DRO resolution, one display step. The cut's widening
    and the start's clearance (which also places both stops past the arc's ends) each
    add it. Any bound term provably smaller than it is absorbed rather than modelled:
    a setting bar's touch up to one step beside its line moves the cut by at most
    ``hypot(reach, step) - reach``, and a touch axis leaning within its one-step
    tolerance turns a back-off ``b`` short by ``b (1 - cos)``, both under one step for
    any cutter-centre reach of two steps or more (#272). A DRO resolution the machine
    does not state as a measured fact leaves the margin unproven, and a reach under two
    steps leaves the absorbed terms unbounded: debt either way."""
    margin = grid[0] * scale
    record_["margin_mm"] = margin
    why = dro_grid_debt(bundle, setup)
    if why is not None:
        debts.append(f"{label}: {why}, so the sweep's one-DRO-step margin is unproven")
    reach = arc["cutter_centre_radius_mm"]
    if number(reach) and reach * scale < 2 * margin:
        debts.append(
            f"{label}: the cutter's centre runs within two DRO steps of the arc's centre, "
            "so the one-step margin bounds nothing it absorbs"
        )


def _start_clear(bundle, setup, arc, label, debts, record_, scale, grid):
    """The cutter goes down at the sweep's first stop, its first row, at every level: the
    stops lie past the arc's ends so it enters in air. That entry is ``start`` ``"air"``
    only when the cutter there stands wholly outside the stock box the setup receives
    (:func:`~.level_entry.in_air`, as the level-entry rule proves any entry); else
    ``"unproven"`` and debt: it would plunge into material, which nothing checks for a
    sweep, so the traveler stops.

    The entry is checked where the stop block puts it (:func:`_printed_start`, recorded
    as ``start_xy``): the pose the printed overrun (``stop_overrun_mm``) sets on the touch
    path, where every stage's stops are set. The rows stand on the nominal path, but the master
    sets the real one: the cutter is widened by the most the cut (``cut_radius_mm``,
    master and guide error) stands off the nominal wall the rows assume. An unproven cut
    leaves the start unproven too (its own debt names it)."""
    from .level_entry import in_air, stock_box

    cut, radius = record_.get("cut_radius_mm"), arc.get("cutter_radius_mm")
    centre = arc["cutter_centre_radius_mm"]
    record_["start"], record_["start_xy"] = "unproven", UNKNOWN
    record_["stop_overrun_mm"] = UNKNOWN
    allowance = arc.get("allowance_mm", 0.0)
    if not (number(radius) and number(centre) and number(allowance)):
        return
    outward = 1 if centre > arc["wall_radius_mm"] else -1
    # The stops are set at the touch, before any rough back-off: on the touch (finish)
    # cutter path, the stage's own allowance back onto the line, whatever the stage. The
    # printed overrun is measured there, 0.1 mm rounded down, so the swept path never runs
    # past the rows the kernel checked.
    stops = centre * scale - outward * allowance
    record_["stop_overrun_mm"] = _printed_overrun(record_, stops)
    if record_["stop_overrun_mm"] is None:
        record_["stop_overrun_mm"] = UNKNOWN
    if not _pair(cut):
        return
    wall = centre * scale - outward * radius
    # How far the real path stands off the nominal one, radially; the touch path differs
    # from a rough's by its back-off, rounded off the line by under one DRO step.
    radial = max(abs(cut[0] - wall), abs(cut[1] - wall))
    spread = radial + (grid[0] * scale if allowance > 0 else 0.0)
    point = _printed_start(arc, record_, stops)
    printed = _printed_overrun(record_, stops)
    record_["start_xy"] = point if point is not None else UNKNOWN
    if point is None or printed is None or stops - spread <= 0:
        point = None
    else:
        # The operator measures the printed overrun along the real path, so the stop's
        # angle lies within printed / (stops ± spread): the cutter there stands off the
        # nominal point by the radial spread plus that much arc at its own real radius.
        swing = printed * spread / (stops * (stops - spread))
        # The stop is set on a scribed mark printed at mark_step: its X and Y are each
        # rounded on their own, so its point lies up to half a step off on both, the
        # diagonal of the two. Its stroke's angle prints to 0.1°: the stroke run through
        # the cutter's axis, about a cutter radius (plus the radial spread) from the mark,
        # moves the stop by that distance times the half-step's angle.
        from .manual_arc import ANGLE_STEP_DEG, mark_step

        step = mark_step(scale)
        half = step * scale / 2 if step is not None else math.inf
        rounding = math.hypot(half, half)
        tilt = (radius + radial) * math.tan(math.radians(ANGLE_STEP_DEG / 2))
        reach = radius + radial + (centre * scale + radial) * swing + rounding + tilt
        reach += record_["margin_mm"]
        record_["start_reach_mm"] = reach
        # How far the stop itself may sit off its stroke along the path.
        record_["stop_slop_mm"] = rounding + tilt + record_["margin_mm"]
    if point is not None and in_air(stock_box(bundle, setup), point, reach, scale):
        record_["start"] = "air"
        return
    debts.append(
        f"{label}: the sweep's start is not proven clear of the stock the setup receives, "
        "so the cutter would go down into material there; sweep far enough past the arc's "
        "ends for the cutter to start clear (a longer sweep_deg), with the stock modelled"
    )


def _printed_overrun(record_, stops_mm):
    """The overrun (mm) the traveler prints for stops measured on a ``stops_mm`` radius:
    half the sweep's excess over the arc, as cutter travel there, 0.1 mm rounded down;
    None when unknown."""
    sweep_deg, span = record_.get("sweep_deg"), record_.get("span_deg")
    if not (number(sweep_deg) and number(span) and number(stops_mm) and stops_mm > 0):
        return None
    over = max(0.0, (sweep_deg - span) / 2)
    return math.floor(math.radians(over) * stops_mm * 10 + 1e-9) / 10


def _printed_start(arc, record_, stops_mm):
    """The cutter centre (setup XY, plan units) where the first stop block puts it. The
    stop is a fixture pose, set once by the steel-rule overrun the traveler prints at the
    radius the stops are measured on (``stops_mm``, the cutter-centre radius of the stage
    that sets them: the rough's, for a finish run between the rough's stops), rounded down
    to 0.1 mm. That pose's angle past the start end's landmark (``ends_cutter_setup_xy[0]``)
    is carried on this stage's own cutter-centre radius, toward the sweep's first row;
    None when any of those is unknown."""
    ends, centre = record_.get("ends_cutter_setup_xy"), arc["centre_setup_xy"]
    rows, sweep_deg, span = arc["rows"], record_.get("sweep_deg"), record_.get("span_deg")
    if not (
        isinstance(ends, list)
        and ends
        and _pair(ends[0])
        and _pair(centre)
        and number(sweep_deg)
        and number(span)
        and number(stops_mm)
        and stops_mm > 0
        and rows
        and _pair(rows[0].get("setup_xy"))
    ):
        return None
    first = ends[0]
    reach = math.dist(first, centre)
    if reach <= 0:
        return None
    printed = _printed_overrun(record_, stops_mm)
    start = trig.atan2(first[1] - centre[1], first[0] - centre[0])
    sweep = rows[0]["setup_xy"]
    toward = trig.atan2(sweep[1] - centre[1], sweep[0] - centre[0]) - start
    toward = (toward + math.pi) % math.tau - math.pi
    turn = math.copysign(printed / stops_mm, toward) if printed else 0.0
    return [centre[0] + reach * trig.cos(start + turn), centre[1] + reach * trig.sin(start + turn)]


def _marks(bundle, setup, op, record_, label, debts, scale):
    """The arc-end marks the stops are set on: an earlier ``scribe`` op in this setup with
    ``layout = "ends"`` on the swept feature (its marks measured from the stock's own
    faces, :func:`~.manual_arc.arc_end_marks`). Recorded as ``marks``: the scribe ``op``
    and which mark (``A`` or ``B``) each stop sits on, the sweep's ``start`` first; else
    UNKNOWN with a debt, since nothing else places a stop on the work. An op between the
    layout and the sweep that may cut (an earlier sweep cuts through the arc's ends and
    the strokes beside them) leaves no mark to trust."""
    from .coordinates import arc_layout
    from .manual_arc import UNCUT, arc_end_marks

    record_["marks"] = UNKNOWN
    feature = op.get("feature")
    scribe = cut = None
    for other in map(record, setup.get("ops") or []):
        if other.get("op") == op.get("op"):
            break
        if (
            other.get("do") == "scribe"
            and other.get("feature") == feature
            and other.get("layout") == "ends"
        ):
            scribe, cut = other, None
        elif other.get("do") not in UNCUT:
            cut = other
    if scribe is None:
        debts.append(
            f'{label}: no earlier scribe op (layout = "ends") in setup {setup.get("id")} '
            f"marks {feature}'s ends to set the stops on"
        )
        return
    if cut is not None:
        debts.append(
            f"{label}: op {cut.get('op')} after the layout (op {scribe.get('op')}) may have "
            "cut its marks away, so no mark sets the stops: rough and finish the arc in one "
            "op, whose stops are set once"
        )
        return
    line = arc_layout(bundle, setup, feature) or {}
    ends = line.get("ends_setup_xy")
    marks, reason = arc_end_marks(bundle, setup, scribe, ends, scale, line.get("centre_setup_xy"))
    start = record_.get("ends_setup_xy")
    if marks is None or not (isinstance(start, list) and start and _pair(start[0])):
        debts.append(
            f"{label}: {reason or 'the sweep start end is unknown'}, so no mark sets the stops"
        )
        return
    first = 0 if math.dist(ends[0], start[0]) <= math.dist(ends[1], start[0]) else 1
    record_["marks"] = {"op": scribe.get("op"), "start": "AB"[first], "end": "AB"[1 - first]}


# The rollers' contacts print as X/Y offsets from the spindle to 0.1 mm each: a roller set
# to them may stand up to half a step off on both, the diagonal of the two.
ROLLER_PRINT_MM = 0.1


def _transverse_offset(record_, found, sweep, grid, scale):
    """How far the cutter's axis may stand beside the arc's radial line at the cut (mm),
    once :func:`_transverse` has put it there; None when unknown. A setting bar centres it
    to one DRO step on the pin's axis, and the beam's play moves the work's centre at the
    cut. A rail's centre stands beside the spindle's line by the sled's sideways shift
    (:func:`rail_transverse_shift`) with each contact off by its roller's printed rounding
    plus the rail's form error and half its roller's runout."""
    found = found or {}
    how = record_.get("transverse")
    if how == "bar_centred" and number(found.get("pivot_play")):
        return grid[0] * scale + found["pivot_play"]
    if how != "rollers_set":
        return None
    form, runout = found.get("rail_form_error"), found.get("roller_runout")
    if not (number(form) and number(runout) and _pair(sweep.get("rollers_deg"))):
        return None
    half = ROLLER_PRINT_MM / 2
    contact = math.hypot(half, half) + form + runout / 2
    return rail_transverse_shift(sweep["rollers_deg"], contact, found.get("roller_orbit"))


def _transverse(record_, guide, label, debts):
    """How the cutter is put on the arc's radial line before the touch, so a rough's one-
    axis back-off is radial (``transverse``): ``"bar_centred"``, a setting bar on the pivot
    pin centred between its two sides; ``"rollers_set"``, the rail's rollers set from the
    locked spindle, which puts the rail's centre on its line. A master arc on a swing arm
    gives no radial line to centre on: debt, and the traveler prints only a STOP, a finish
    too (a feeler touch would need no line, #288)."""
    kind = record_.get("master_kind")
    record_["transverse"] = UNKNOWN
    if guide == "rail":
        record_["transverse"] = "rollers_set"
    elif guide == "pivot" and kind == "setting_bar":
        record_["transverse"] = "bar_centred"
    elif guide == "pivot" and kind == "master_arc":
        debts.append(
            f"{label}: a master arc on a swing arm gives no radial line to centre the cutter "
            "on before the touch: touch off a setting bar on the pivot pin, or guide the work "
            "on a rail"
        )


def _off_line_backoff(touch, back, off):
    """How far a one-axis back-off of ``back`` mm along the touch axis misses the radial
    move it stands for when the cutter axis stands up to ``off`` mm beside the radial line
    (``touch``: the touch's cutter-centre radius, mm), worst case either way; None when
    unknown, infinite when the offset reaches the radius."""
    if not (number(touch) and number(back) and number(off)):
        return None
    if off <= 0:
        return 0.0
    if off >= touch:
        return math.inf
    along = math.sqrt(touch * touch - off * off)
    return max(
        abs((touch + sign * back) - math.hypot(off, along + sign * back)) for sign in (1, -1)
    )


def _on_mill(bundle, setup, label, errors, debts):
    """A guided sweep locks a mill's table X and Y under a vertical spindle while a fixture
    in its T-slots or on its pivot turns the work: any other machine kind (a lathe, a
    bench) is an error, and an unknown kind is debt."""
    machine = record(resolve(bundle, "machines", setup.get("machine")))
    kind = machine.get("kind", UNKNOWN)
    if kind == "mill":
        return
    if isinstance(kind, str) and kind != UNKNOWN:
        errors.append(
            f"{label}: a guided sweep locks a mill's X and Y under the cutter, but setup "
            f"{setup.get('id')} runs on a {kind}"
        )
        return
    debts.append(
        f"{label}: setup {setup.get('id')}'s machine kind is unknown, so no mill is proven "
        "to lock X and Y under the cutter for the sweep"
    )


def _own_setup(setup, label, errors):
    """A guided sweep's fixture turns the work off the setup frame (the work at the sweep's
    middle pose) and nothing holds it at that pose for another spindle op, before the
    sweep or after it: a swing arm or sled moves freely between stops. Sharing the setup
    with one is an error; the sweep takes a setup of its own (manual ops aside)."""
    if touch_set(setup):
        return
    others = [
        str(op.get("op"))
        for op in map(record, setup.get("ops") or [])
        if "tool" in op and record(op.get("contour")).get("method") != METHOD
    ]
    errors.append(
        f"{label}: setup {setup.get('id')} also runs spindle op {', '.join(others)}, but the "
        "sweep's fixture turns the work off the setup frame and nothing holds it at that "
        "pose for them; give the guided sweep a setup of its own"
    )


def _row_spacing(contour, label, errors):
    """Rows half a turn or more apart (``step_deg`` of 180 or more) leave the cutter's
    path between them undetermined: the chord between two such rows reads as the short
    way round, so neither the rows' cutting order nor the fixture's turn can be told from
    them. An error; rows under half a turn apart fix both."""
    step = contour.get("step_deg")
    if number(step) and step >= 180.0:
        errors.append(
            f"{label}: step_deg {step:g}° puts rows half a turn or more apart, so the way "
            "the fixture turns between them is not determined; space them under 180°"
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
    rounded off the line onto the DRO grid: the only handwheel move, one axis.

    The rows stay on the nominal cutter-centre arc, deliberately. The kernel judges that
    path against the nominal STEP part, as for every manual-arc method; where the master
    actually sets the cut is judged here, against the band (``cut_radius_mm`` inside
    ``band_mm``). Rows moved to the master's radius would make any in-band master past
    nominal a finished-part hit, and the band already bounds how far the real path lies
    from the checked one."""
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
    gain = _rail(sweep, errors, debts, record_) if guide == "rail" else None
    grid = dro_grid(bundle, setup)
    _margin(bundle, setup, arc, label, debts, record_, scale, grid)
    _sweep_span(arc, sweep_deg, label, errors, debts, record_, scale, grid)
    _row_spacing(contour, label, errors)
    _own_setup(setup, label, errors)
    _on_mill(bundle, setup, label, errors, debts)
    axis = sweep.get("touch_axis", UNKNOWN)
    if axis not in TOUCH_AXES:
        debts.append(f"{label}: contour.sweep.touch_axis (the cutter's radial axis) is unknown")
    else:
        # Toward the centre to touch a convex arc's master from outside, away from it on a
        # concave one: the cutter approaches from the scrap side either way.
        index, side = TOUCH_AXES[axis]
        feed = -side if convex else side
        record_["touch_feed"] = ("-" if feed < 0 else "+") + "XY"[index]
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
    # The cutter's centre stands where the master puts it at the touch, and the rough's
    # back-off from there at the cut: the guide's finite terms are worst at the shortest of
    # those reaches, not the nominal path's.
    touches = _touch_reaches(arc, master, convex)
    record_["touch_reach_min_mm"] = min(touches) if touches else UNKNOWN
    cuts = [t + outward * back * scale for t in touches] if number(back) else []
    reach = min(touches + cuts) if touches and cuts else UNKNOWN
    record_["worst_reach_mm"] = reach
    # How far the arc centre moves on the guide between the touch-off and the cut.
    widen = UNKNOWN
    # With no master or back-off to place the cutter by, the cut stays unproven; their own
    # debts say why.
    placed = number(reach) and found is not None
    if placed and guide == "pivot" and number(found["pivot_play"]):
        # A setting bar seated on the pin sets the cutter from the pin's own axis: the
        # beam's play moves the work once, at the cut. A master on the arm moves with the
        # beam at the touch-off too, so its play counts at both.
        bar = record_.get("master_kind") == "setting_bar"
        play = found["pivot_play"]
        term = _second_order(play, reach)
        if term is None:
            debts.append(
                f"{label}: the pivot play is too large for the cutter's radius to bound the cut"
            )
        else:
            widen = (play + term) * (1 if bar else 2)
    elif placed and gain is not None:
        form, runout = found["rail_form_error"], found["roller_runout"]
        if number(form) and number(runout) and number(found.get("roller_orbit")):
            # Each contact errs by the rail's form error plus half its roller's runout, at
            # the touch-off and again at the cut: twice the most one pose moves the cut.
            shift = rail_cut_shift(
                sweep["rollers_deg"], form + runout / 2, found["roller_orbit"], reach
            )
            if shift is None:
                debts.append(
                    f"{label}: the rail's form error and roller runout are too large for its "
                    "radius and rollers to bound the cut"
                )
            else:
                widen = 2 * shift
    record_["centre_error_mm"] = widen
    _transverse(record_, guide, label, debts)
    # A rough's one-axis back-off is radial only on the radial line: the cutter is put on
    # it to within a residual, which turns a back-off into a slightly shorter radial move.
    residual = 0.0
    if number(back) and back > 0:
        off = _transverse_offset(record_, found, sweep, grid, scale)
        record_["transverse_offset_mm"] = off if off is not None else UNKNOWN
        # The touch puts the cutter's centre where the master is, not on the nominal path:
        # the residual is taken at the worse of the reaches its radius limits give.
        misses = [_off_line_backoff(touch, back * scale, off) for touch in touches]
        residual = max(misses) if misses and None not in misses else None
        record_["transverse_residual_mm"] = residual if residual is not None else UNKNOWN
        if residual is not None and not math.isfinite(residual):
            debts.append(
                f"{label}: the cutter may stand as far beside the arc's radial line as the "
                "arc's own radius, so no one-axis back-off is proven radial"
            )
    proven = (
        master is not None
        and number(widen)
        and number(back)
        and number(residual)
        and math.isfinite(residual)
    )
    if proven:
        shifted = outward * back * scale
        # One DRO step more, the margin every proof here carries (:func:`_margin`).
        widened = widen + residual + record_["margin_mm"]
        record_["cut_radius_mm"] = [master[0] + shifted - widened, master[1] + shifted + widened]
    elif not (errors or debts):
        # Unknown is never a pass: a cut left unproven always names itself, whatever
        # path left it so.
        debts.append(f"{label}: the cut radius is unproven")
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
            why += f" and the {record_['margin_mm']:g} mm DRO-step margin"
            if back:
                why += f" and backed off {back * scale:g} mm"
            errors.append(
                f"{label}: {why} cuts R{cut[0]:.3f} to R{cut[1]:.3f} mm, outside the "
                f"R{low:g} to R{high:g} mm band"
            )
    _rotation(arc, label, debts, record_, scale)
    _landmarks(arc, record_, sweep, axis, found, scale)
    _marks(bundle, setup, op, record_, label, debts, scale)
    _start_clear(bundle, setup, arc, label, debts, record_, scale, grid)
    if gain is not None and _pair(sweep.get("rail_deg")):
        _rail_coverage(arc, sweep, found, record_, errors, debts)
    _radial(arc, record_, axis, label, errors, grid)
    if measurements:
        by_id = {entry["id"]: entry for entry in measurements}
        arc["measurements"] = [*arc.get("measurements", []), *by_id.values()]
    # Everything this stage left unproven, whether or not a printed value shows it: the
    # traveler's gate prints the recipe only when this is known empty.
    record_["open_debts"] = [*errors, *debts]
    return errors, debts


def _radial(arc, record_, axis, label, errors, grid):
    """The setup frame is the work at the sweep's middle pose, the cutter on the arc's
    middle: ``touch_axis`` must point from the arc centre to that middle, the cutter's
    radial line, to within one DRO step of cutter travel. A touch or back-off along any
    other axis is not radial, so it would not set the radius the recipe claims: an error.
    A full circle has no middle; every direction is radial at some pose."""
    middle_xy, centre = arc.get("arc_mid_setup_xy"), arc["centre_setup_xy"]
    if arc["full_circle"] or axis not in TOUCH_AXES or not (_pair(middle_xy) and _pair(centre)):
        return
    middle = [middle_xy[i] - centre[i] for i in range(2)]
    length = math.hypot(*middle)
    if length <= 0:
        return
    index, side = TOUCH_AXES[axis]
    expected = [0.0, 0.0]
    expected[index] = float(side)
    cosine = sum(middle[i] / length * expected[i] for i in range(2))
    off = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    radius = arc["cutter_centre_radius_mm"]
    tolerance = math.degrees(grid[0] / radius) if number(radius) and radius > 0 else 0.0
    record_["touch_axis_off_deg"] = off
    if off > tolerance:
        errors.append(
            f"{label}: the cutter's radial line at the arc's middle runs {off:.3f}° off "
            f"{axis}: touch_axis must be the setup axis from the arc centre to the arc's "
            "middle, or the touch and back-off are not radial"
        )


def _landmarks(arc, record_, sweep, axis, found, scale):
    """Where the operator sets the sweep's stops and the rollers: ``ends_setup_xy``, the
    arc's ends on the work (setup XY, plan units) in cutting order, the first where the
    sweep starts (a full circle has none); and, on a rail, ``roller_contacts_mm``, each
    roller's contact on the rail as a setup X/Y offset (mm) from the spindle axis at the
    touch, the cutter on its nominal cutter-centre radius."""
    centre, rows = arc["centre_setup_xy"], arc["rows"]
    ends = arc.get("arc_ends_deg")
    wall, cutter = arc["wall_radius_mm"], arc["cutter_centre_radius_mm"]
    if not arc["full_circle"] and isinstance(ends, list) and _pair(centre) and rows:
        found_rows = [
            next((r for r in rows if abs(r["angle_deg"] - angle) <= _JOIN_TOL), None)
            for angle in ends
        ]
        if all(r is not None and _pair(r["setup_xy"]) for r in found_rows):
            points = [
                [centre[i] + wall / cutter * (r["setup_xy"][i] - centre[i]) for i in range(2)]
                for r in found_rows
            ]
            # The cutter's centre where its edge reaches each arc end: the stops' landmark,
            # on the cutter's own path (the arc's end lies a cutter radius off it).
            centres = [list(r["setup_xy"]) for r in found_rows]
            first = rows[0]["angle_deg"]
            if abs(first - ends[1]) < abs(first - ends[0]):
                points.reverse()
                centres.reverse()
            record_["ends_setup_xy"] = points
            record_["ends_cutter_setup_xy"] = centres
    rollers, radius = sweep.get("rollers_deg"), (found or {}).get("rail_radius")
    if record_.get("guide") != "rail" or axis not in TOUCH_AXES:
        return
    if not (_pair(rollers) and number(radius)):
        return
    index, side = TOUCH_AXES[axis]
    radial = [0.0, 0.0]
    radial[index] = float(side)
    tangent = [-radial[1], radial[0]]  # counterclockwise from above
    reach = cutter * scale
    contacts = []
    for angle in rollers:
        out = radius * trig.cos(math.radians(angle)) - reach
        along = radius * trig.sin(math.radians(angle))
        contacts.append([radial[i] * out + tangent[i] * along for i in range(2)])
    record_["roller_contacts_mm"] = contacts


def _rotation(arc, label, debts, record_, scale):
    """The way the fixture turns the work under the cutter, viewed from above: against the
    cutter's travel about the centre along its rows (their cutting order). Rows stand
    under half a turn apart (:func:`_row_spacing`), so each step's shortest angle is the
    way the cutter actually goes."""
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


def _support_lift(bundle, setup):
    """The height (mm) the hold's parallels and support blocks (or riser) lift the work off
    its fixture's bed, as the headroom stack reads them: 0 when none is declared, None
    when a declared one is unknown or unproven (:func:`_trusted_height`)."""
    hold = record(setup.get("hold"))
    absent = (None, "none", "not_applicable")
    parts = (
        (hold.get("parallels"), None),
        (hold.get("supports", hold.get("riser")), hold.get("support_orientation")),
    )
    total = 0.0
    for reference, orientation in parts:
        if reference in absent:
            continue
        height = _trusted_height(bundle, reference, orientation)
        if height is None:
            return None
        total += height
    return total


def _trusted_height(bundle, reference, orientation):
    """A support's height (mm) as the headroom stack reads it, or None when the item is
    missing or flagged to verify, or its declared height is itself flagged: headroom leaves
    such a stack unresolved, so the picture draws no rollers on it."""
    from .headroom import _height

    item = resolve(bundle, "fixtures", reference)
    if not isinstance(item, dict) or uncertain(item):
        return None
    fact = length_fact(item, "height", require_measured=False)
    if number(fact["value"]) and not fact["verified"]:
        return None
    height = _height(item, orientation)
    return height if number(height) else None


# The guide-element facts the setup picture draws a rail's rollers from: (field, words).
_ROLLER_FACTS = (("roller_dia", "roller diameter"), ("roller_height", "roller height"))


def guide_scene(bundle, setup, numbers, scale):
    """(``{"rollers": [...]}`` or None, picture notes) for ``setup``'s guided sweeps, from
    its coordinates ``numbers``; ``scale`` is mm per plan unit.

    The rollers and the pivot post are fixed to the table while the work turns, so they
    are drawn at the sweep's middle pose (the setup frame) for the operator to see where
    they stand, never hit-tested: the kernel draws each roller as a render-only cylinder
    (``at_mm`` its axis in setup XY, ``dia_mm``, ``z_mm`` from the table to its top). A
    rail roller stands at the rail radius plus (``rail_side = "outer"``) or minus its own
    radius from the arc centre, at its ``rollers_deg`` from the cutter's radial line; the
    table is the work's seated bottom less the supports under it and the fixture's
    ``bed_height``. A pivot post 800 mm off the part would shrink it to a speck, so it is
    a note giving where it stands. A roller fact that is missing or unmeasured leaves the
    rollers undrawn, named in a note with its ``measure:`` instruction."""
    from ..measurements import measurement_entry

    rollers, notes, seen = [], [], set()
    # The work sits on its lowest authored bottom: retained rails below ``bottom_z`` when
    # declared, as the headroom stack and the jaw seat read it; an authored but unknown
    # one leaves the seat unknown.
    state = record(setup.get("stock_state"))
    seats = [state.get(key) for key in ("bottom_z", "retained_rail_bottom_z")]
    seats = [value for value in seats if value is not None]
    bottom = min(seats) if seats and all(number(value) for value in seats) else UNKNOWN
    for arc in numbers.get("arc_table") or []:
        sweep = arc.get("guided")
        op = arc.get("op")
        if not isinstance(sweep, dict) or op in seen:
            continue
        seen.add(op)
        centre, middle = arc.get("centre_setup_xy"), arc.get("arc_mid_setup_xy")
        if not (_pair(centre) and _pair(middle)):
            notes.append(f"NOT SHOWN: op {op}'s guide (its arc centre is unknown).")
            continue
        centre_mm = [v * scale for v in centre]
        middle_mm = [v * scale for v in middle]
        heading = math.atan2(middle_mm[1] - centre_mm[1], middle_mm[0] - centre_mm[0])
        if sweep.get("guide") == "pivot":
            # Setup coordinates print as the traveler prints them: plan units, DRO decimals.
            decimals, units = dro_grid(bundle, setup)[1], bundle.features.get("units", "")
            reach = math.dist(centre, middle)
            notes.append(
                f"PIVOT POST (op {op}, off the picture): at the arc centre, setup X "
                f"{centre[0]:.{decimals}f} Y {centre[1]:.{decimals}f}, {reach:.{decimals}f} "
                f"{units} from the cutter at the arc's middle."
            )
            continue
        if sweep.get("guide") != "rail":
            continue
        reference = sweep.get("fixture")
        item = resolve(bundle, "fixtures", reference) if isinstance(reference, str) else None
        item = item if isinstance(item, dict) else {}
        category, key = identity(bundle, reference, "fixtures")
        values, missing = {}, []
        if not item or _item_flagged(bundle, category, key):
            # A sled flagged to verify as a whole proves none of its facts, measured or not;
            # a flag on one of them leaves only that fact (if the picture reads it) unproven.
            missing.append(f"{key} is not in the fixtures inventory or is flagged to verify")
        for field, _ in _ROLLER_FACTS:
            fact = length_fact(item, field, require_measured=True)
            if fact["verified"] and number(fact["value"]) and fact["value"] > 0:
                values[field] = fact["value"]
            else:
                missing.append(measurement_entry(category, key, field, item=item)["instruction"])
        bed = length_fact(item, "bed_height", require_measured=True)
        if not (bed["verified"] and number(bed["value"])):
            missing.append(measurement_entry(category, key, "bed_height", item=item)["instruction"])
        # Parallels or support blocks under the work lift it off the fixture's bed, as the
        # headroom stack counts them: the table is that much lower again.
        lift = _support_lift(bundle, setup)
        if lift is None:
            missing.append("the parallels' or support blocks' height under the work is unknown")
        side = item.get("rail_side")
        if side not in ("outer", "inner"):
            missing.append(f"declare {key}'s rail_side (outer or inner)")
        rail, angles = sweep.get("rail_radius_mm"), sweep.get("rollers_deg")
        if not (number(rail) and _pair(angles) and number(bottom)):
            missing.append("its rail radius, rollers' angles or the stock bottom are unknown")
        if missing:
            notes.append(f"NOT SHOWN: op {op}'s guide rollers — " + "; ".join(missing) + ".")
            continue
        radius = rail + (1 if side == "outer" else -1) * values["roller_dia"] / 2
        table = bottom * scale - lift - bed["value"]
        for index, angle in enumerate(angles, start=1):
            theta = heading + math.radians(angle)
            rollers.append(
                {
                    "name": f"guide roller {index} (op {op})",
                    "op": op,
                    "at_mm": [
                        centre_mm[0] + radius * trig.cos(theta),
                        centre_mm[1] + radius * trig.sin(theta),
                    ],
                    "dia_mm": values["roller_dia"],
                    "z_mm": [table, table + values["roller_height"]],
                }
            )
    return ({"rollers": rollers} if rollers else None), notes
