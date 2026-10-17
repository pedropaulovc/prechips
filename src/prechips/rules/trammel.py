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


# How far (degrees) authored pins may sit off the central angle the measured rail angle
# gives them: the plan says where the pair sits, the measured α how far apart.
FIT_TOL = 0.5


def fits(pins, alpha, tol=FIT_TOL):
    """Whether pins at ``pins`` degrees on one circle subtend ``alpha`` (or its
    supplement) at every point of it off their arc: their central angle is ``2α`` or
    ``360° − 2α`` (to ``tol`` degrees)."""
    return seat(pins, alpha, tol) is not None


def seat(pins, alpha, tol=FIT_TOL):
    """The pins' angles as the measured ``alpha`` places them about the authored pair's
    bisector (its central angle exactly ``2α`` or ``360° − 2α``, whichever the authored
    span is within ``tol`` of), in the authored order; None when it is neither."""
    span = pins[1] - pins[0]
    middle, sign = (pins[0] + pins[1]) / 2, 1 if span >= 0 else -1
    for half in (alpha, 180 - alpha):
        if abs(abs(span) % 360 - 2 * half) <= tol:
            return [middle - sign * half, middle + sign * half]
    return None


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


# How far (degrees) past the sweep's ends a stop's pose may lie: far more than any stop band.
STOP_PAD_DEG = 1.0


def repeated(pin, lo, hi, pad=STOP_PAD_DEG):
    """The pose (degrees) inside ``[lo − pad, hi + pad]`` where the pin's station along
    its rail peaks (the chord from the cutter is the pin circle's diameter), or None: a
    station that turns back repeats, so a stop at it holds the carrier at two poses."""
    for k in range(-2, 3):
        peak = pin - 180.0 + 360.0 * k
        if lo - pad <= peak <= hi + pad:
            return peak
    return None


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


def line_gain(directions, heading, lo, hi, across=0.0):
    """The most the cutter's radius moves per unit offset of each pin-line, summed over
    both lines, worst case over the pose window: ``max |g₁| + |g₂|`` where ``g = M⁻ᵀ n``,
    ``M`` the lines' unit normals as rows and ``n = u(h + ψ/2)`` the cutter's outward
    radial direction in the table frame. A pin's radial play in its carriage, or a rail's
    pin-line standing off the spindle axis, offsets its line; the cut radius moves by the
    radial part of where the offset lines cross. Exact: each signed sum is a sinusoid in
    ``ψ/2``. ``across`` (degrees) turns the direction projected onto: 90 gives the
    tangential displacement's gain instead. None when the lines are parallel."""
    normals = [[-d[1], d[0]] for d in directions]
    det = normals[0][0] * normals[1][1] - normals[0][1] * normals[1][0]
    if abs(det) < 1e-12:
        return None
    # M⁻ᵀ = (1/det) [[m11, −m10], [−m01, m00]]
    inverse_t = [
        [normals[1][1] / det, -normals[1][0] / det],
        [-normals[0][1] / det, normals[0][0] / det],
    ]
    h = math.radians(heading + across)
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


def _exact_path(arc):
    """The rows stay on the nominal cutter-centre arc, as every guided sweep's do (rules/
    guided_sweep.py :func:`guided`): the kernel judges that path against the nominal part,
    and where the pins actually put the cut is judged against the band here. The DRO places
    nothing, so each row's printed XY is its exact one, and the kernel sweeps the cutter
    along the exact arc through them, not their chords."""
    for row in arc["rows"]:
        row["dro_xy"] = list(row["setup_xy"])
    arc["exact_arc"] = {
        "centre": list(arc["centre_setup_xy"]),
        "radius": arc["cutter_centre_radius_mm"],
    }


# A stop is set by a steel rule along its rail to the printed station: the station prints
# to 0.1 mm (half that in rounding) and a novice reads a rule to half a millimetre. The
# stop-setting and start proofs hold for a stop anywhere that far off (#289).
STATION_PRINT_MM = 0.05
RULE_READING_MM = 0.5
STATION_ERROR_MM = STATION_PRINT_MM + RULE_READING_MM


def stop_poses(r, pin, psi, error=STATION_ERROR_MM):
    """The poses (degrees, as ``psi``) a stop set at the pin's station for pose ``psi``,
    off by up to ``error`` mm along its rail, can hold the carrier at, on a pin circle of
    radius ``r``: the exact inverse of :func:`station` on the same side of the pin, as
    ``[least, greatest]``; None when the station is within ``error`` of the pin's reach."""
    s = station(r, pin, psi)
    side = 1 if _wrap(pin - psi) > 0 else -1
    found = []
    for target in (s - error, s + error):
        if not 0 < target < 2 * r:
            return None
        half = math.degrees(math.asin(target / (2 * r)))
        found.append(pin - side * 2 * half)
    return sorted(found)


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
    from .coordinates import _WALL_TOL, _pair, dro_grid
    from .guided_sweep import _margin, _on_mill, _own_setup, _rotation, _row_spacing, _sweep_span
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
    if number(spacing) and spacing <= 0:
        errors.append(
            f"{label}: pin pair {sweep.get('pin_pair')}'s spacing {spacing:g} mm is not "
            "positive: two pins that far apart set no circle"
        )
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
    elif number(alpha):
        # The measured rail angle, not the plan's rounding, sets how far apart they sit.
        pins = seat(pins, alpha)
        record_["pins_deg"] = pins
    if pinned:
        r_mm = radius(spacing, alpha)
        record_.update(
            pin_radius_mm=r_mm,
            radius_per_deg_mm=per_degree(spacing, alpha),
            radius_per_spacing=per_spacing(alpha),
        )
    _exact_path(arc)
    grid = (1e-9, 9)  # the DRO sets nothing: a sweep's reach is judged exactly
    sweep_deg = sweep.get("sweep_deg", UNKNOWN)
    _sweep_span(arc, sweep_deg, label, errors, debts, record_, scale, grid)
    _row_spacing(contour, label, errors)
    _own_setup(setup, label, errors)
    _on_mill(bundle, setup, label, errors, debts)
    # One DRO step of margin on every geometric proof, as for every guided sweep (#258):
    # the cut's widening, the stops' setting error and the start's clearance.
    _margin(bundle, setup, arc, label, debts, record_, scale, dro_grid(bundle, setup))
    margin = record_["margin_mm"]
    centre, middle = arc["centre_setup_xy"], arc.get("arc_mid_setup_xy")
    window = None
    if number(sweep_deg) and sweep_deg > 0 and _pair(centre) and _pair(middle):
        heading = math.degrees(trig.atan2(middle[1] - centre[1], middle[0] - centre[0]))
        window = (heading, -sweep_deg / 2, sweep_deg / 2)
    # The pins stand on their own circle: the pose and stations are the real fixture's.
    r_plan = record_["pin_radius_mm"] / scale if pinned else UNKNOWN
    gain = UNKNOWN
    if window and pinned and _pair(pins):
        heading, lo, hi = window
        hit = crossed(pins, lo, hi)
        repeat = repeated(pins[0], lo, hi)
        if repeat is not None:
            errors.append(
                f"{label}: rail 1's pin station peaks at {repeat:g}° inside the sweep and comes "
                "back to the same stations, so a stop on rail 1 cannot tell the sweep's ends "
                "apart: place the pins so each runs one way along its rail over the sweep"
            )
        elif hit:
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
        error, give = terms
        if not (alpha - error > 0 and alpha + error < 90 and spacing - give > 0):
            errors.append(
                f"{label}: the rail angle {alpha:g}° ± {error:g}° or the pin spacing "
                f"{spacing:g} ± {give:g} mm leaves no acute crossing or no spacing"
            )
        else:
            # R = D / (2 sin α) falls with α and grows with D, so its exact extremes over
            # the measured tolerances are at the corners, not the first-order slopes.
            nominal = record_["pin_radius_mm"]
            offset = lines[0] + lines[1]
            parts = {
                "radius_below": nominal - radius(spacing - give, alpha + error),
                "radius_above": radius(spacing + give, alpha - error) - nominal,
                "pin_lines": gain * offset,
            }
            # The cutter stands off the pin circle by x_r radially and x_t along it, so
            # its distance from the centre is sqrt((R + x_r)² + x_t²): at least R − |x_r|,
            # at most R + |x_r| + x_t² / (2 (R − |x_r|)), exactly, with R the circle's
            # least radius. Beyond R the bound is unproven.
            least = nominal - parts["radius_below"] - parts["pin_lines"]
            tangent = record_.get("tangent_gain")
            if not number(tangent) or least <= 0:
                debts.append(f"{label}: the pin-lines' offset is too large to bound the cut")
                parts["pin_lines_second"] = "unknown"
            else:
                parts["pin_lines_second"] = (tangent * offset) ** 2 / (2 * least)
            record_["error_terms_mm"] = parts
            second = parts["pin_lines_second"] if number(parts["pin_lines_second"]) else 0.0
            below = parts["radius_below"] + parts["pin_lines"] + margin
            above = parts["radius_above"] + parts["pin_lines"] + second + margin
            widen = max(below, above)
            wall = nominal + to_wall * scale
            if number(parts["pin_lines_second"]):
                record_["cut_radius_mm"] = [wall - below, wall + above]
    record_["centre_error_mm"] = widen
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
    if window and pinned and number(gain):
        _stops_proof(arc, record_, found, pins, window, label, errors, debts, scale)
        _travel(record_, found, label, errors)
        _start_clear(bundle, setup, arc, record_, pins, window, label, debts, scale)
    else:
        record_.update(stops="unproven", start="unproven")
    if not (errors or debts) and not _pair(record_["cut_radius_mm"]):
        # Unknown is never a pass: an unproven cut always names itself.
        debts.append(f"{label}: the cut radius is unproven")
    if measurements:
        by_id = {entry["id"]: entry for entry in measurements}
        arc["measurements"] = [*arc.get("measurements", []), *by_id.values()]
    # Whatever the rule left open stops the card, printed value or not (#258's gate).
    record_["open_debts"] = [*errors, *debts]
    return errors, debts


def _carried(pins, rails_, offsets, theta):
    """(cutter centre in the carrier's frame, both pins' stations along their rails) with
    the carrier turned ``theta`` degrees: table ``y = Rot(θ) x + t``, the spindle at the
    table origin, each pin on its rail's pin-line offset by ``offsets[i]`` along the
    line's normal, ``n_i · (Rot P_i + t) = e_i``; mm. None when the lines are parallel."""
    normals = [[-r[1], r[0]] for r in rails_]
    moved = [_turn(p, theta) for p in pins]
    b = [offsets[i] - sum(normals[i][k] * moved[i][k] for k in range(2)) for i in range(2)]
    det = normals[0][0] * normals[1][1] - normals[0][1] * normals[1][0]
    if abs(det) < 1e-12:
        return None
    t = [
        (b[0] * normals[1][1] - b[1] * normals[0][1]) / det,
        (normals[0][0] * b[1] - normals[1][0] * b[0]) / det,
    ]
    stations = [sum(rails_[i][k] * (moved[i][k] + t[k]) for k in range(2)) for i in range(2)]
    return _turn([-t[0], -t[1]], -theta), stations


def _stopped(pins, rails_, offsets, target, guess, reach=4.0):
    """The carrier turn (degrees) at which pin 1 stands at ``target`` mm along rail 1,
    bracketed within ``reach`` degrees of ``guess`` and found by bisection; None when the
    bracket holds no such pose."""
    lo, hi = guess - reach, guess + reach
    ends = [_carried(pins, rails_, offsets, t) for t in (lo, hi)]
    if None in ends:
        return None
    s_lo, s_hi = (end[1][0] - target for end in ends)
    if s_lo * s_hi > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        s_mid = _carried(pins, rails_, offsets, mid)[1][0] - target
        if s_mid * s_lo <= 0:
            hi = mid
        else:
            lo, s_lo = mid, s_mid
    return (lo + hi) / 2


def _stop_envelope(arc, record_, found, pins, window, scale):
    """Where each stop can hold the carrier on the real fixture (#289): for every corner
    of the measured tolerances (the rails' crossing opened or closed by its error, the
    pins' spacing either way, each pin-line off by its pin clearance plus rail offset
    either way) and a stop set at its printed station (0.1 mm) off by a rule's reading
    plus one DRO step either way, the carrier's pose is solved from the two pin-on-line
    constraints. Records per stop ``stop_bands_deg`` (the cutter's angle about the arc
    centre from the heading, least and greatest), ``stop_radial_mm`` (how far the cutter
    centre stands off the nominal path there, worst case) and ``stop_stations_mm`` (each
    pin's least and greatest station at the stops). False when a pose cannot be solved."""
    import itertools

    heading = window[0]
    centre = [v * scale for v in arc["centre_setup_xy"]]
    r_pin, nominal = record_["pin_radius_mm"], arc["cutter_centre_radius_mm"] * scale
    alpha_err, spacing_err = found["rail_angle_error"], found["pin_spacing_error"]
    line = found["pin_clearance"] + found["rail_offset"]
    # The stopped carriage meets its block; the pin in it may sit up to its radial play
    # along the rail either way of the carriage's own station.
    error = RULE_READING_MM + record_["margin_mm"] + found["pin_clearance"]
    base = [[centre[i] + r_pin * _u(heading + a)[i] for i in range(2)] for a in pins]
    chord = [base[1][i] - base[0][i] for i in range(2)]
    length = math.hypot(*chord)
    chord = [v / length for v in chord]
    r1, r2 = record_["rails_dir"]
    rows = arc["rows"]
    poses = [_pose_angle(rows[i]["setup_xy"], arc["centre_setup_xy"], heading) for i in (0, -1)]
    printed = [round(v, 1) for v in record_["stations_mm"][0]]
    bands, radial, stations = [], 0.0, [[math.inf, -math.inf], [math.inf, -math.inf]]
    for psi, target in zip(poses, printed, strict=True):
        angles = []
        corners = itertools.product(
            (-alpha_err, alpha_err),
            (-spacing_err, spacing_err),
            (-line, line),
            (-line, line),
            (-error, error),
        )
        for da, dd, e1, e2, slip in corners:
            pins_ = [
                [base[0][i] - dd / 2 * chord[i] for i in range(2)],
                [base[1][i] + dd / 2 * chord[i] for i in range(2)],
            ]
            rails_ = [_turn(r1, -da / 2), _turn(r2, da / 2)]
            theta = _stopped(pins_, rails_, (e1, e2), target + slip, -psi / 2)
            if theta is None:
                return False
            cutter, at = _carried(pins_, rails_, (e1, e2), theta)
            bearing = math.degrees(trig.atan2(cutter[1] - centre[1], cutter[0] - centre[0]))
            angles.append(_wrap(bearing - heading))
            radial = max(radial, abs(math.dist(cutter, centre) - nominal))
            for k in range(2):
                stations[k] = [min(stations[k][0], at[k]), max(stations[k][1], at[k])]
        bands.append([min(angles), max(angles)])
    record_.update(stop_bands_deg=bands, stop_radial_mm=radial, stop_stations_mm=stations)
    return True


def _stops_proof(arc, record_, found, pins, window, label, errors, debts, scale):
    """The stops are clamped on rail 1 at the printed stations by a steel rule (``stops``
    ``"proven"`` only when this holds): wherever the real fixture and a stop set off its
    station can hold the carrier (:func:`_stop_envelope`), each stop must still hold it
    past its arc end, so the cutter reaches the arc's whole span; a stop that could fall
    short is an error (sweep farther)."""
    heading, lo, hi = window
    centre, rows, ends = arc["centre_setup_xy"], arc["rows"], arc.get("arc_ends_deg")
    record_["stops"] = "unproven"
    if not rows or not isinstance(ends, list):
        debts.append(f"{label}: the sweep's stops are unknown")
        return
    from .resolution import number

    keys = ("rail_angle_error", "pin_spacing_error", "pin_clearance", "rail_offset")
    if not all(number(found.get(key)) for key in keys):
        # Unmeasured tolerances bound no pose: the stops stay unproven (the facts' own
        # debts name them).
        return
    if not _stop_envelope(arc, record_, found, pins, window, scale):
        debts.append(f"{label}: the stops' poses cannot be bounded from the rail stations")
        return
    poses = [_pose_angle(rows[i]["setup_xy"], centre, heading) for i in (0, -1)]
    span = record_.get("span_deg")
    first_side = 1 if poses[0] > poses[1] else -1
    arc_ends = [first_side * span / 2, -first_side * span / 2]
    bands = record_["stop_bands_deg"]
    for band, end, side in zip(bands, arc_ends, (first_side, -first_side), strict=True):
        # The stop's nearest pose to the arc must still lie past that arc end.
        nearest = band[0] if side > 0 else band[1]
        if side * (nearest - end) < 0:
            errors.append(
                f"{label}: a stop set {RULE_READING_MM + record_['margin_mm']:g} mm off its "
                "printed rail station (its pin's play along the rail besides), on a fixture "
                "at its measured tolerances, could hold "
                f"the carrier {abs(nearest - end):.3f}° short of the arc's end: sweep farther "
                "past the arc's ends"
            )
            return
    record_["stops"] = "proven"


def _arc_clear(box, centre, r, heading, band, reach, scale):
    """Whether a cutter of ``reach`` mm, its centre anywhere on the arc of radius ``r``
    (plan units) about ``centre`` over the poses ``band`` (degrees from ``heading``),
    stands wholly outside ``box`` (mm, setup frame) on one side of one axis over the
    whole band: exact, from the arc's true X and Y extremes (its ends, and any pose where
    it runs tangent to an axis); False when the box is unknown. A corner a cutter clears
    only by changing sides is not proven: conservative."""
    from .level_entry import STOCK_TOL_MM

    if box is None:
        return False
    lo, hi = heading + band[0], heading + band[1]
    extremes = [lo, hi, *(90.0 * k for k in range(-8, 9) if lo < 90.0 * k < hi)]
    xs = [(centre[0] + r * _u(t)[0]) * scale for t in extremes]
    ys = [(centre[1] + r * _u(t)[1]) * scale for t in extremes]
    return any(
        max(values) + reach <= box[axis] - STOCK_TOL_MM
        or min(values) - reach >= box[axis + 3] + STOCK_TOL_MM
        for axis, values in ((0, xs), (1, ys))
    )


def _start_clear(bundle, setup, arc, record_, pins, window, label, debts, scale):
    """The cutter goes down at the first stop: ``start`` ``"air"`` only when, at every pose
    the first stop can hold on the real fixture (:func:`_stop_envelope`, its pose band
    and radial offset), the cutter stands wholly outside the stock box the setup receives
    (:func:`~.level_entry.in_air`), as for every guided sweep; else ``"unproven"`` and
    debt, so the traveler stops."""
    from .level_entry import stock_box

    record_["start"] = "unproven"
    bands, cut = record_.get("stop_bands_deg"), record_.get("cut_radius_mm")
    radius = arc.get("cutter_radius_mm")
    heading = window[0]
    centre = arc["centre_setup_xy"]
    nominal = arc["cutter_centre_radius_mm"] * scale
    if bands and isinstance(cut, list) and isinstance(radius, (int, float)):
        # How far the real cutter centre stands off the nominal path there, radially.
        reach = radius + record_["stop_radial_mm"] + record_["margin_mm"]
        box = stock_box(bundle, setup)
        clear = _arc_clear(box, centre, nominal / scale, heading, bands[0], reach, scale)
        if clear:
            record_["start"] = "air"
            return
    debts.append(
        f"{label}: the sweep's start is not proven clear of the stock the setup receives, "
        "so the cutter would go down into material there; sweep far enough past the arc's "
        "ends for the cutter to start clear (a longer sweep_deg), with the stock modelled"
    )


def _pose(arc, record_, found, pins, window, r_plan, scale, errors, label):
    """Record the carrier's motion over the sweep from the exact pose: its turn, each
    pin's station along its rail at the sweep's start and end (in cutting order) and
    their extremes (checked against the rails' travel by :func:`_travel`); returns the
    pin-lines' worst radius gain (:func:`line_gain`)."""
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
    gain = _gain_over_angle(directions, heading, lo, hi, found.get("rail_angle_error"))
    record_["line_gain"] = gain if gain is not None else "unknown"
    # The offset lines' crossing also moves along the cutter's path, which lengthens the
    # radius at second order (the budget's exact bound needs it).
    tangent = _gain_over_angle(directions, heading, lo, hi, found.get("rail_angle_error"), 90.0)
    record_["tangent_gain"] = tangent if tangent is not None else "unknown"
    return gain if gain is not None else "unknown"


def _travel(record_, found, label, errors):
    """Each pin's carriage must stay within its rail's measured travel over the sweep on
    the real fixture: its stations at the stops at every tolerance corner and stop
    setting (:func:`_stop_envelope`), and the nominal sweep's interior extremes (the
    station runs monotone between them; a chord through the pin circle's diameter peaks
    inside, which the nominal range catches), each widened by one DRO step."""
    from .resolution import number

    travel, envelope = found.get("rail_travel"), record_.get("stop_stations_mm")
    nominal = record_.get("station_ranges_mm")
    if not (isinstance(travel, list) and len(travel) == 2 and all(map(number, travel))):
        return
    if not (isinstance(envelope, list) and isinstance(nominal, list)):
        return
    near, far = travel
    margin = record_["margin_mm"]
    used = []
    for index, (stops, swept) in enumerate(zip(envelope, nominal, strict=True), start=1):
        low, high = min(stops[0], swept[0]) - margin, max(stops[1], swept[1]) + margin
        used.append([low, high])
        if low < near - 1e-6 or high > far + 1e-6:
            errors.append(
                f"{label}: pin {index}'s carriage may run {low:.1f} to {high:.1f} mm from the "
                "spindle axis along its rail over the sweep on a fixture at its measured "
                f"tolerances, beyond the rail's {near:g} to {far:g} mm travel"
            )
    record_["station_envelope_mm"] = used


# Rail-angle samples the pin-line gain is maximized over, across the measured error.
GAIN_SAMPLES = 64


def _gain_over_angle(directions, heading, lo, hi, error, across=0.0):
    """:func:`line_gain` at its worst over the true crossing angle too: the rails' crossing
    opened or closed by up to the measured ``rail_angle_error`` (degrees). Exact in the pose;
    across the angle, the ends, the nominal and :data:`GAIN_SAMPLES` evenly spaced angles
    each way (the gain is smooth in the angle, ``1 / cos(α/2)`` at the symmetric pose).
    None when unproven: an unknown error, or lines turned parallel."""
    from .resolution import number

    if not number(error):
        return None
    worst = None
    for k in range(-GAIN_SAMPLES, GAIN_SAMPLES + 1):
        # Only the crossing angle is uncertain: turning both rails together turns the
        # whole motion with them and leaves the gain as it was, so the error is split
        # half to each rail, which keeps their bisector, the cutter's radial line at the
        # middle pose, where the pose model has it.
        half = error * k / GAIN_SAMPLES / 2
        turned = [_turn(directions[0], -half), _turn(directions[1], half)]
        gain = line_gain(turned, heading, lo, hi, across)
        if gain is None:
            return None
        worst = gain if worst is None else max(worst, gain)
    return worst


def _turn(v, deg):
    c, s = trig.cos(math.radians(deg)), trig.sin(math.radians(deg))
    return [c * v[0] - s * v[1], s * v[0] + c * v[1]]


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


# The guide-element facts the setup picture draws a trammel's rails and pins from.
_PICTURE_FACTS = (
    ("pin_dia", "pin diameter"),
    ("rail_width", "rail width"),
    ("rail_height", "rail height"),
    ("bed_height", "bed height"),
)


def guide_scene(bundle, guided, op, bottom, lift, scale):
    """({"rails": [...], "pins": [...]}, picture notes) for one trammel op's ``guided`` record:
    drawn render-only at the sweep's middle pose (the setup frame), never hit-tested
    (rules/guided_sweep.py :func:`guide_scene`). Each rail is a box along its pin-line from
    the spindle axis, over its measured ``rail_travel`` stations, standing ``rail_height``
    from the table (the work's seat less the supports under it and the fixture's
    ``bed_height``); each pin a cylinder of ``pin_dia`` at its place on the carrier, from
    the rail tops to the work's seat. ``lift`` is the supports' height under the work (None:
    unknown). A missing or unmeasured fact leaves them undrawn, named in a note with its
    ``measure:`` instruction."""
    from ..measurements import length_fact, limits_fact, measurement_entry
    from .coordinates import _pair
    from .resolution import identity, number, resolve

    reference = guided.get("fixture")
    item = resolve(bundle, "fixtures", reference) if isinstance(reference, str) else None
    item = item if isinstance(item, dict) else {}
    category, key = identity(bundle, reference, "fixtures")
    values, missing = {}, []
    for field, _ in _PICTURE_FACTS:
        fact = length_fact(item, field, require_measured=True)
        if fact["verified"] and number(fact["value"]) and fact["value"] > 0:
            values[field] = fact["value"]
        else:
            missing.append(measurement_entry(category, key, field, item=item)["instruction"])
    travel = limits_fact(item, "rail_travel", require_measured=True)
    if not travel["verified"]:
        missing.append(measurement_entry(category, key, "rail_travel", item=item)["instruction"])
    spindle, pins = guided.get("spindle_setup_xy"), guided.get("pins_setup_xy")
    directions = guided.get("rails_dir")
    placed = (
        _pair(spindle)
        and isinstance(pins, list)
        and all(map(_pair, pins))
        and isinstance(directions, list)
        and all(map(_pair, directions))
        and number(bottom)
    )
    if not placed:
        missing.append("its pins' places on the carrier or the stock bottom are unknown")
    if lift is None:
        missing.append("the parallels' or support blocks' height under the work is unknown")
    if not missing and values["bed_height"] <= values["rail_height"]:
        missing.append(f"{key}'s bed_height does not stand above its rail_height")
    if missing:
        return {}, [f"NOT SHOWN: op {op}'s trammel rails and pins — " + "; ".join(missing) + "."]
    table = bottom * scale - lift - values["bed_height"]
    top = table + values["rail_height"]
    near, far = travel["value"]
    origin = [v * scale for v in spindle]
    rails_ = [
        {
            "name": f"trammel rail {index} (op {op})",
            "op": op,
            "from_mm": [origin[i] + near * d[i] for i in range(2)],
            "to_mm": [origin[i] + far * d[i] for i in range(2)],
            "width_mm": values["rail_width"],
            "z_mm": [table, top],
        }
        for index, d in enumerate(directions, start=1)
    ]
    pins_ = [
        {
            "name": f"carrier pin {index} (op {op})",
            "op": op,
            "at_mm": [v * scale for v in pin],
            "dia_mm": values["pin_dia"],
            "z_mm": [top, bottom * scale - lift],
        }
        for index, pin in enumerate(pins, start=1)
    ]
    return {"rails": rails_, "pins": pins_}, []


def flagged(item, sweep, category, key, measurements):
    """Measurement debts for a trammel flagged to verify as a whole, beyond its plain
    lengths (rules/guided_sweep.py ``_flagged``): the rail angle and its error, the
    pair's spacing and the rails' travel."""
    from ..measurements import angle_debt, length_debt, limits_debt, record_debt
    from .resolution import UNKNOWN

    pair = sweep.get("pin_pair", UNKNOWN)
    fields = [
        (angle_debt, "rail_angle_deg"),
        (angle_debt, "rail_angle_error_deg"),
        (limits_debt, "rail_travel"),
    ]
    if isinstance(pair, str) and pair != UNKNOWN:
        fields.append((length_debt, ("pin_spacing", pair)))
    for debt_of, field in fields:
        debt = debt_of(item, field, category, key, require_measured=True)
        if debt is None:
            debt = record_debt(item, category, key, field)
        if debt:
            measurements.append(debt)
