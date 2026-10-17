"""Oblique-trammel kinematics (docs/plan.md "Manual arcs", issue #269).

A trammel carrier rides one pin on each of two straight rails clamped to the table, their
pin-lines crossing at the spindle axis at the rail angle ``α``. The angle the two pins
subtend at the cutter is then constant, so in the carrier's (the work's) frame the
cutter centre traces the circle through both pins of radius ``R = D / (2 sin α)``, ``D``
the pins' spacing: the pins stand on the cutter-centre circle itself, their central angle
``2α`` (or ``360° − 2α``). The circle's centre is fixed in the carrier and virtual in the
table frame, where the carrier both turns and translates.

Angles here are degrees about the arc centre from the cutter's radial line at the
sweep's middle pose (``heading``), counterclockwise from above, in the setup frame. The
setup frame is the table frame at that pose, the cutter centre ``S0`` on the spindle
axis. A pose is the cutter's angle ``ψ`` on the circle in the work frame: the carrier has
then turned ``−ψ/2`` (a chord from a fixed point of a circle to a moving one turns at half
the rate), and a carrier point ``x`` stands at ``S0 + Rot(−ψ/2)(x − C − R u(h + ψ))``.
Every carrier point's table coordinate is therefore one sinusoid in ``ψ/2``, so the swept
extents, the pins' stations along their rails and the radius gain of a pin-line offset
are exact over a pose window (its ends plus each stationary point), never sampled.
"""

from __future__ import annotations

import math

from .. import trig


def _u(deg):
    theta = math.radians(deg)
    return [trig.cos(theta), trig.sin(theta)]


def radius(spacing, alpha):
    """The cutter-centre radius (``spacing``'s units) a pin pair ``spacing`` apart sets on
    rails crossing at ``alpha`` degrees."""
    return spacing / (2 * trig.sin(math.radians(alpha)))


def per_degree(spacing, alpha):
    """``|∂R/∂α|`` per degree of rail angle: ``D cos α / (2 sin² α)`` × π/180."""
    a = math.radians(alpha)
    return spacing * trig.cos(a) / (2 * trig.sin(a) ** 2) * math.pi / 180


def per_spacing(alpha):
    """``∂R/∂D``: radius per unit of pin spacing, ``1 / (2 sin α)``."""
    return 1 / (2 * trig.sin(math.radians(alpha)))


def fits(pins, alpha, tol=1e-3):
    """Whether pins at ``pins`` degrees on one circle subtend ``alpha`` (or its
    supplement) at every point of it off their arc: their central angle is ``2α`` or
    ``360° − 2α`` (to ``tol`` degrees)."""
    span = abs(pins[1] - pins[0]) % 360
    return any(abs(span - want) <= tol for want in (2 * alpha, 360 - 2 * alpha))


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


def crossed(pins, lo, hi):
    """The pins the cutter would pass over in the pose window ``[lo, hi]`` (it cannot)."""
    return [a for a in pins if lo - 1e-9 <= _wrap(a) <= hi + 1e-9]


def _extremes(values, lo, hi, stationary):
    """(least, greatest) of ``values(t)`` over ``[lo, hi]``: its ends and each
    ``stationary`` point inside."""
    points = [lo, hi, *(t for t in stationary if lo < t < hi)]
    found = [values(t) for t in points]
    return min(found), max(found)


def _sinusoid_stationary(a, b, lo, hi):
    """Where ``a cos t + b sin t`` is stationary, degrees, in ``[lo − 360, hi + 360]``."""
    if abs(a) < 1e-15 and abs(b) < 1e-15:
        return []
    base = math.degrees(math.atan2(b, a))
    return [base + 180.0 * k for k in range(-6, 7) if lo - 360 <= base + 180.0 * k <= hi + 360]


def station(r, pin, psi):
    """The pin at ``pin`` degrees' distance from the cutter at pose ``psi``: its station
    along its rail from the spindle axis, ``2R |sin((pin − ψ)/2)|``."""
    return 2 * r * abs(trig.sin(math.radians((pin - psi) / 2)))


def station_range(r, pin, lo, hi):
    """(least, greatest) station of the pin at ``pin`` over the pose window: exact (its
    ends, and where the chord is a diameter)."""
    peaks = [pin - 180.0 + 360.0 * k for k in range(-2, 3)]
    return _extremes(lambda psi: station(r, pin, psi), lo, hi, peaks)


def place(centre, heading, r, psi, point):
    """Carrier point ``point`` (setup XY at the middle pose) in the table frame at pose
    ``psi``: ``S0 + Rot(−ψ/2)(x − C) − R u(h + ψ/2)``."""
    half = math.radians(-psi / 2)
    c, s = trig.cos(half), trig.sin(half)
    q = [point[0] - centre[0], point[1] - centre[1]]
    start = [centre[i] + r * _u(heading)[i] for i in range(2)]
    radial = _u(heading + psi / 2)
    return [
        start[0] + c * q[0] - s * q[1] - r * radial[0],
        start[1] + s * q[0] + c * q[1] - r * radial[1],
    ]


def swept_box(centre, heading, r, lo, hi, points):
    """``[[x least, x greatest], [y least, y greatest]]`` the carrier ``points`` (setup XY
    at the middle pose) sweep in the table frame over ``[lo, hi]``: exact, since each
    coordinate is one sinusoid in ``ψ/2``."""
    h = math.radians(heading)
    box = [[math.inf, -math.inf], [math.inf, -math.inf]]
    for point in points:
        qx, qy = point[0] - centre[0], point[1] - centre[1]
        # x(t) = S0x + (qx − R cos h) cos t + (qy + R sin h) sin t, t = ψ/2; y likewise.
        terms = [
            (qx - r * trig.cos(h), qy + r * trig.sin(h)),
            (qy - r * trig.sin(h), -qx - r * trig.cos(h)),
        ]
        for axis, (a, b) in enumerate(terms):
            stationary = [2 * t for t in _sinusoid_stationary(a, b, lo / 2, hi / 2)]
            least, most = _extremes(
                lambda psi, axis=axis, point=point: place(centre, heading, r, psi, point)[axis],
                lo,
                hi,
                stationary,
            )
            box[axis] = [min(box[axis][0], least), max(box[axis][1], most)]
    return box


def rails(centre, heading, r, pins):
    """The rails' unit pin-line directions in the table frame, from the spindle axis
    toward each pin (fixed: the rails never move)."""
    start = [centre[i] + r * _u(heading)[i] for i in range(2)]
    found = []
    for pin in pins:
        p = [centre[i] + r * _u(heading + pin)[i] for i in range(2)]
        d = [p[0] - start[0], p[1] - start[1]]
        length = math.hypot(*d)
        found.append([d[0] / length, d[1] / length])
    return found


def line_gain(directions, heading, lo, hi):
    """The most the cutter's radius moves per unit offset of each pin-line, summed over
    both lines, worst case over the pose window: ``max |g₁| + |g₂|`` where ``g = M⁻ᵀ n``,
    ``M`` the lines' unit normals as rows and ``n = u(h + ψ/2)`` the cutter's outward
    radial direction in the table frame. A pin's radial play in its carriage, or a rail's
    pin-line standing off the spindle axis, offsets its line; the cut radius moves by the
    radial part of where the offset lines cross. Exact: each signed sum is a sinusoid in
    ``ψ/2``. None when the lines are parallel."""
    normals = [[-d[1], d[0]] for d in directions]
    det = normals[0][0] * normals[1][1] - normals[0][1] * normals[1][0]
    if abs(det) < 1e-12:
        return None
    # M⁻ᵀ = (1/det) [[m11, −m10], [−m01, m00]]
    inverse_t = [
        [normals[1][1] / det, -normals[1][0] / det],
        [-normals[0][1] / det, normals[0][0] / det],
    ]
    h = math.radians(heading)
    best = 0.0
    for signs in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        # Σ σᵢ gᵢ(t) = a cos(h + t) + b sin(h + t): an angle-shifted sinusoid in t.
        a = sum(signs[i] * inverse_t[i][0] for i in range(2))
        b = sum(signs[i] * inverse_t[i][1] for i in range(2))

        def value(psi, a=a, b=b):
            theta = h + math.radians(psi / 2)
            return a * trig.cos(theta) + b * trig.sin(theta)

        shift = math.degrees(h)
        stationary = [2 * (t - shift) for t in _sinusoid_stationary(a, b, -720, 720)]
        best = max(best, _extremes(value, lo, hi, stationary)[1])
    return best


# The trammel's consumed fixture lengths (mm), each with its own measured record:
# (field, words). The rail angle and its error, the pair's spacing and the rails' pin
# stations are read on their own below.
_LENGTHS = (
    ("pin_spacing_error", "pin spacing error"),
    ("pin_clearance", "pin clearance"),
    ("rail_offset", "rail offset"),
)


def _angle(item, field, category, key, debts, measurements, words):
    """A consumed fixture angle (degrees) with its own measured record, or UNKNOWN with
    its debt and ``measure:`` instruction; a negative value proves nothing."""
    from ..measurements import angle_debt, angle_fact
    from .resolution import UNKNOWN, number

    fact = angle_fact(item, field, require_measured=True)
    value = fact["value"] if fact["verified"] else UNKNOWN
    if number(value) and value >= 0:
        return value
    debts.append(f"the {words} of {key} is unknown or not measured")
    debt = angle_debt(item, field, category, key, require_measured=True)
    if debt:
        measurements.append(debt)
    return UNKNOWN


def _facts(bundle, setup, sweep, errors, debts, measurements, record_):
    """The trammel fixture's consumed facts by field (mm and degrees), or None when it
    proves none: the setup's hold must be it, of ``kind = "trammel"``."""
    from ..measurements import limits_debt, limits_fact
    from .guided_sweep import _carrier, _fact
    from .resolution import UNKNOWN, identity, number, resolve

    found = _carrier(bundle, setup, sweep, "trammel", errors, debts, measurements, record_)
    if found is None:
        return None
    reference = sweep.get("fixture")
    item = resolve(bundle, "fixtures", reference)
    category, key = identity(bundle, reference, "fixtures")
    found["rail_angle"] = _angle(
        item, "rail_angle_deg", category, key, debts, measurements, "rail angle"
    )
    found["rail_angle_error"] = _angle(
        item, "rail_angle_error_deg", category, key, debts, measurements, "rail angle error"
    )
    pair = sweep.get("pin_pair", UNKNOWN)
    found["pin_spacing"] = UNKNOWN
    if not isinstance(pair, str) or pair == UNKNOWN:
        debts.append("contour.sweep.pin_pair (the carrier's pin pair this pass rides) is unknown")
    else:
        found["pin_spacing"] = _fact(
            item,
            ("pin_spacing", pair),
            True,
            category,
            key,
            debts,
            measurements,
            f"pin pair {pair} spacing",
        )
    travel = limits_fact(item, "rail_travel", require_measured=True)
    found["rail_travel"] = travel["value"] if travel["verified"] else UNKNOWN
    if not travel["verified"]:
        debts.append(f"the rail travel of {key} is unknown or not measured")
        debt = limits_debt(item, "rail_travel", category, key, require_measured=True)
        if debt:
            measurements.append(debt)
    record_.update(
        {
            "rail_angle_deg": found["rail_angle"],
            "rail_angle_error_deg": found["rail_angle_error"],
            "pin_pair": pair,
            "pin_spacing_mm": found["pin_spacing"],
            "rail_travel_mm": found["rail_travel"],
        }
    )
    alpha = found["rail_angle"]
    if number(alpha) and not 0 < alpha < 90:
        errors.append(
            f"the rail angle {alpha:g}° of {key} is not between 0° and 90°: its rails' "
            "pin-lines must cross at an acute angle"
        )
        found["rail_angle"] = UNKNOWN
    return found


def _rescale(bundle, arc, radius, scale):
    """Move ``arc``'s rows radially onto the pin-defined cutter-centre ``radius`` (plan
    units): the pins, not the drawing, set where the cutter runs. The DRO places nothing,
    so each row's printed XY is its exact one."""
    from .coordinates import mapping

    centre = arc["centre_setup_xy"]
    nominal = arc["cutter_centre_radius_mm"]
    feature = mapping(bundle.feature_definitions.get(arc["feature"]))
    plane = feature.get("arc_centre", feature.get("at"))
    k = radius / nominal
    for row in arc["rows"]:
        xy = [centre[i] + k * (row["setup_xy"][i] - centre[i]) for i in range(2)]
        row.update(setup_xy=xy, x=xy[0], y=xy[1], dro_xy=list(xy))
        if isinstance(plane, list) and len(plane) >= 2:
            row["model_xy"] = [plane[i] + k * (row["model_xy"][i] - plane[i]) for i in range(2)]
    middle = arc.get("arc_mid_setup_xy")
    if isinstance(middle, list) and len(middle) == 2:
        arc["arc_mid_setup_xy"] = [centre[i] + k * (middle[i] - centre[i]) for i in range(2)]
    arc["cutter_centre_radius_mm"] = arc["radius_mm"] = radius
    # The kernel sweeps the cutter along this exact circle, not the rows' chords.
    arc["exact_arc"] = {"centre": list(centre), "radius": radius}


def _pose_angle(point, centre, heading):
    """``point``'s angle about ``centre`` from ``heading``, degrees in (−180, 180]."""
    theta = math.degrees(trig.atan2(point[1] - centre[1], point[0] - centre[0]))
    return _wrap(theta - heading)


def _stock_corners(bundle, setup, scale):
    """The setup-entry stock's footprint corners (setup XY, plan units) from the kernel's
    ``stock_bbox_mm``, or []: the work rides the carrier, so it sweeps with it."""
    from .resolution import number

    kernel = getattr(bundle, "kernel", None)
    if not isinstance(kernel, dict) or kernel.get("status") != "ok":
        return []
    setups = kernel.get("setups") if isinstance(kernel.get("setups"), dict) else {}
    box = (setups.get(setup["id"]) or {}).get("stock_bbox_mm")
    if not (isinstance(box, list) and len(box) == 6 and all(number(v) for v in box)):
        return []
    return [[x / scale, y / scale] for x in (box[0], box[3]) for y in (box[1], box[4])]


def recipe(bundle, setup, op, arc, band, label, scale):
    """(errors, debts): the trammel recipe for ``arc`` (its rows the cutter-centre arc in
    cutting order over the whole sweep), stamped as ``guided`` with ``guide = "trammel"``.

    The rails are aligned once so their pin-lines cross on the spindle axis, X, Y and Z are
    locked, and the operator feeds the carrier by its hand lever from stop to stop; the
    DRO places nothing. The cut radius is the pin pair's ``D / (2 sin α)``, widened by the
    error budget: the rail angle's error through ``∂R/∂α``, the pair's spacing error
    through ``1 / (2 sin α)``, and each pin-line's offset (a pin's radial play in its
    carriage plus a rail's pin-line off the spindle axis) through its exact worst radius
    gain over the sweep (:func:`line_gain`, about 1:1). The widened wall must lie inside
    the band. A trammel cannot back off, so a rough stage is an error."""
    from .coordinates import _WALL_TOL, _pair
    from .guided_sweep import _rotation, _sweep_span
    from .resolution import UNKNOWN, number, record

    contour = record(op.get("contour"))
    sweep = record(contour.get("sweep"))
    errors, debts, measurements = [], [], []
    convex = arc["cutter_centre_radius_mm"] > arc["wall_radius_mm"]
    # The wall stands a cutter radius off the cutter-centre circle, plan units.
    to_wall = arc["wall_radius_mm"] - arc["cutter_centre_radius_mm"]
    record_ = {
        "guide": "trammel",
        "fixture": UNKNOWN,
        "master": UNKNOWN,
        "convex": convex,
        "radius_mm": arc["wall_radius_mm"] * scale,
        "locked_axes": ["X", "Y", "Z"],
        "moves": "fixture",
        "feed": "lever",
        "pin_radius_mm": UNKNOWN,
        "centre_error_mm": UNKNOWN,
        "cut_radius_mm": UNKNOWN,
        "band_mm": UNKNOWN,
        "rotation": UNKNOWN,
        "overrun_mm": UNKNOWN,
        "path_mm": UNKNOWN,
        "pins_deg": sweep.get("pins_deg", UNKNOWN),
    }
    arc["guided"] = record_
    for field, words in (("master", "master"), ("touch_axis", "touch axis")):
        if field in sweep:
            errors.append(
                f"{label}: a trammel has no touch-off: its pins set the radius, so "
                f"contour.sweep.{field} (a {words}) does not apply"
            )
    allowance = arc.get("allowance_mm", 0.0)
    if arc.get("stage") == "rough" or (number(allowance) and allowance > 0):
        errors.append(
            f"{label}: a trammel's cut radius is fixed by its pin pair, so it cannot back off "
            "for a rough stage: rough by another method, or on another pin pair or cutter"
        )
    found = _facts(bundle, setup, sweep, errors, debts, measurements, record_) or {}
    alpha, spacing = found.get("rail_angle", UNKNOWN), found.get("pin_spacing", UNKNOWN)
    pins = sweep.get("pins_deg", UNKNOWN)
    pinned = number(alpha) and number(spacing) and spacing > 0
    if not _pair(pins):
        debts.append(
            f"{label}: contour.sweep.pins_deg (the pin pair's angles about the arc centre) "
            "is unknown"
        )
    elif number(alpha) and not fits(pins, alpha):
        errors.append(
            f"{label}: pins at {pins[0]:g}° and {pins[1]:g}° about the arc centre do not "
            f"subtend the rails' {alpha:g}° at the cutter: their central angle must be "
            f"{2 * alpha:g}° (or {360 - 2 * alpha:g}°)"
        )
        pinned = False
    if pinned:
        r_mm = radius(spacing, alpha)
        record_.update(
            pin_radius_mm=r_mm,
            radius_per_deg_mm=per_degree(spacing, alpha),
            radius_per_spacing=per_spacing(alpha),
        )
        _rescale(bundle, arc, r_mm / scale, scale)
    grid = (1e-9, 9)  # the DRO sets nothing: a sweep's reach is judged exactly
    sweep_deg = sweep.get("sweep_deg", UNKNOWN)
    _sweep_span(arc, sweep_deg, label, errors, debts, record_, scale, grid)
    centre, middle = arc["centre_setup_xy"], arc.get("arc_mid_setup_xy")
    window = None
    if number(sweep_deg) and sweep_deg > 0 and _pair(centre) and _pair(middle):
        heading = math.degrees(trig.atan2(middle[1] - centre[1], middle[0] - centre[0]))
        window = (heading, -sweep_deg / 2, sweep_deg / 2)
    r_plan = arc["cutter_centre_radius_mm"]
    gain = UNKNOWN
    if window and pinned and _pair(pins):
        heading, lo, hi = window
        hit = crossed(pins, lo, hi)
        if hit:
            errors.append(
                f"{label}: the {sweep_deg:g}° sweep carries the cutter over the pin at "
                f"{hit[0]:g}°: the pins must stand outside the swept window"
            )
        else:
            gain = _pose(arc, record_, found, pins, window, r_plan, scale, errors, label)
            _footprint(bundle, setup, arc, record_, pins, window, r_plan, scale)
    # The error budget, mm of cutter-centre radius.
    widen = UNKNOWN
    terms = [found.get(k, UNKNOWN) for k in ("rail_angle_error", "pin_spacing_error")]
    lines = [found.get(k, UNKNOWN) for k in ("pin_clearance", "rail_offset")]
    if pinned and number(gain) and all(map(number, terms + lines)):
        parts = {
            "rail_angle": record_["radius_per_deg_mm"] * terms[0],
            "pin_spacing": record_["radius_per_spacing"] * terms[1],
            "pin_lines": gain * (lines[0] + lines[1]),
        }
        record_["error_terms_mm"] = parts
        widen = sum(parts.values())
    record_["centre_error_mm"] = widen
    if pinned and number(widen):
        wall = record_["pin_radius_mm"] + to_wall * scale
        record_["cut_radius_mm"] = [wall - widen, wall + widen]
    if band is None:
        debts.append(f"{label}: its radial band is unknown, so the cut radius is unproven")
    else:
        low, high = band[0] * scale, band[1] * scale
        record_["band_mm"] = [low, high]
        cut = record_["cut_radius_mm"]
        if _pair(cut) and (cut[0] < low - _WALL_TOL or cut[1] > high + _WALL_TOL):
            errors.append(
                f"{label}: pin pair {found.get('pin_spacing', UNKNOWN):g} mm apart on rails at "
                f"{alpha:g}° runs the cutter centre on R{record_['pin_radius_mm']:.3f} mm; "
                f"with its {widen:.3f} mm error budget it cuts R{cut[0]:.3f} to "
                f"R{cut[1]:.3f} mm, outside the R{low:g} to R{high:g} mm band"
            )
    _rotation(arc, label, debts, record_, scale)
    if measurements:
        by_id = {entry["id"]: entry for entry in measurements}
        arc["measurements"] = [*arc.get("measurements", []), *by_id.values()]
    return errors, debts


def _pose(arc, record_, found, pins, window, r_plan, scale, errors, label):
    """Record the carrier's motion over the sweep from the exact pose: its turn, each
    pin's station along its rail at the sweep's start and end (in cutting order) and
    their extremes, which must stay within the rails' measured travel; returns the
    pin-lines' worst radius gain (:func:`line_gain`)."""
    from .resolution import number

    heading, lo, hi = window
    centre, rows = arc["centre_setup_xy"], arc["rows"]
    r_mm = r_plan * scale
    ends = [_pose_angle(rows[i]["setup_xy"], centre, heading) for i in (0, -1)] if rows else []
    directions = rails(centre, heading, r_plan, pins)
    record_["rails_dir"] = directions
    record_["carrier_turn_deg"] = (hi - lo) / 2
    stations, ranges = [], []
    for pin in pins:
        stations.append([station(r_mm, pin, psi) for psi in ends])
        ranges.append(list(station_range(r_mm, pin, lo, hi)))
    record_["stations_mm"] = stations  # per rail: [at the start, at the end]
    record_["station_ranges_mm"] = ranges
    record_["rail_travel_used_mm"] = [high - low for low, high in ranges]
    travel = found.get("rail_travel")
    if isinstance(travel, list) and len(travel) == 2 and all(map(number, travel)):
        near, far = travel
        for index, (low, high) in enumerate(ranges, start=1):
            if low < near - 1e-6 or high > far + 1e-6:
                errors.append(
                    f"{label}: pin {index}'s carriage runs {low:.1f} to {high:.1f} mm from the "
                    f"spindle axis along its rail over the sweep, beyond the rail's "
                    f"{near:g} to {far:g} mm travel"
                )
    gain = line_gain(directions, heading, lo, hi)
    record_["line_gain"] = gain if gain is not None else "unknown"
    return gain if gain is not None else "unknown"


def _footprint(bundle, setup, arc, record_, pins, window, r_plan, scale):
    """The carrier's swept footprint in the table frame, mm from the spindle axis: the
    work (the kernel's stock box, when present) and the pins over the whole sweep, exact;
    and each rail's pin-line from its nearest to its farthest station."""
    heading, lo, hi = window
    centre = arc["centre_setup_xy"]
    start = [centre[i] + r_plan * _u(heading)[i] for i in range(2)]
    points = [[centre[i] + r_plan * _u(heading + pin)[i] for i in range(2)] for pin in pins]
    stock = _stock_corners(bundle, setup, scale)
    box = swept_box(centre, heading, r_plan, lo, hi, points + stock)
    record_["swept_mm"] = {
        "x": [(box[0][0] - start[0]) * scale, (box[0][1] - start[0]) * scale],
        "y": [(box[1][0] - start[1]) * scale, (box[1][1] - start[1]) * scale],
        "stock": bool(stock),
    }
    record_["spindle_setup_xy"] = start
    record_["pins_setup_xy"] = points


def unmodelled(op, fixture, guided, rule):
    """The ``check:`` debt ``rule`` (``"travel"`` or ``"headroom"``) owes for one trammel
    op: the table's extents and the column are not modelled, nor the stack at every pose,
    so the finding stays unknown; the debt quotes the exact footprint and stations where
    the coordinates rule established them."""
    from .resolution import UNKNOWN, number

    guided = guided if isinstance(guided, dict) else {}
    name = f"op {op.get('op', UNKNOWN)} guided sweep (trammel)"
    swept, ranges = guided.get("swept_mm"), guided.get("station_ranges_mm")
    turn = guided.get("carrier_turn_deg")
    turning = f", turning {turn:g}°" if number(turn) else ""
    if rule == "travel":
        where = ""
        if isinstance(swept, dict):
            what = "the work and pins" if swept.get("stock") else "the pins"
            where = (
                f": {what} sweep X {swept['x'][0]:.0f} to {swept['x'][1]:.0f}, Y "
                f"{swept['y'][0]:.0f} to {swept['y'][1]:.0f} mm about the spindle axis (the "
                "carrier plate beyond them is not modelled)"
            )
        if isinstance(ranges, list):
            far = max(high for _, high in ranges)
            where += f", and its pins run out to {far:.0f} mm along the rails"
        return (
            f"{name}: the swept footprint of {fixture} is not checked against the table, "
            f"column or way covers{where}; check: with Z raised and the spindle stopped, "
            f"lever the carrier from stop to stop{turning} and see it, the work and both "
            "rails clear the column, the table ends and the way covers"
        )
    near = ""
    if isinstance(ranges, list):
        near = (
            f", and that the carriages, as near as {min(low for low, _ in ranges):.0f} mm to "
            "the spindle axis, pass under the cutter and holder clear"
        )
    return (
        f"{name}: the spindle stack and fixture clearance are judged with {fixture} at its "
        f"setup pose only; check: the dry pass from stop to stop{turning} clears the spindle "
        f"nose, holder and column at every pose{near}"
    )
