"""Nominal feature targets and finite cutter-centre tables.

A model point is transformed by the dot product with each setup basis. Unknown
components propagate only through nonzero basis coefficients. Local authored Z
can substitute only an unknown model transform in an unbound frame, retaining
local_from operation provenance. No tolerance-band midpoint defines geometry.

A located feature is placed by its own ``at``, else by its parent hole's ``at``
(:func:`located_by`), else by the kernel's measured faces of revolution about setup Z
through X0 Y0 (:func:`revolved_located`); otherwise its row stays unknown.
"""

from __future__ import annotations

import itertools
import math

from ..findings import Finding
from ..measurements import angle_fact
from ..model import tolerance_requirements
from ._bench import manual_bench, not_applicable
from .datum_consistency import _cuts
from .resolution import (
    UNKNOWN,
    _citations,
    length_mm,
    number,
    op_features,
    plan_frame_cite,
    resolve,
    setup_frame,
    uncertain,
)
from .tip_endpoints import FACING, HOLE_OPS, POCKETING, stock_states

AXES = ("x", "y", "z")
CENTRE_OPS = HOLE_OPS | {"center"}
LOCATED_KINDS = {"hole", "counterbore", "thread", "threaded_hole", "boss"}
# Side-milling traverse sense. With n the cutter-side surface normal (from the cut wall
# toward the cutter centre) and t the travel, a clockwise spindle (viewed from above,
# looking down setup -Z) cuts conventionally when (n x t)·Z > 0 and climbs when it is < 0;
# a counterclockwise spindle inverts both.
_CUT_SENSE = {"conventional": 1, "climb": -1}
_SPINDLE_SENSE = {"cw": 1, "ccw": -1}


def mapping(value):
    return value if isinstance(value, dict) else {}


def located_by(features, name, feature):
    """The feature whose ``at`` locates ``name``, that feature's frame name and its name.

    An explicit ``at`` (even ``unknown``) wins; otherwise a child names its
    parent hole (``hole``/``parent``) and is located at that parent's ``at`` in the
    parent's frame. A missing parent locates nothing, so the child stays unknown.
    """
    parent = feature.get("hole", feature.get("parent"))
    if "at" in feature or not isinstance(parent, str):
        return feature, feature.get("frame", "model"), name
    owner = mapping(features.get(parent))
    return owner, owner.get("frame", "model"), parent


def _op_names(setup):
    """Every feature the setup's ops name, in op order; an absent feature stays ``None``."""
    return dict.fromkeys(name for op in setup["ops"] for name in op_features(op) or [None])


def _located_names(setup, features):
    """This setup's located features (a located kind or a centre-op target), in op order."""
    centre = {op.get("feature") for op in setup["ops"] if op.get("do") in CENTRE_OPS}
    return [
        name
        for name in _op_names(setup)
        if mapping(features.get(name)).get("kind") in LOCATED_KINDS or name in centre
    ]


def revolved_located(setup, features):
    """Located features of ``setup`` with neither ``at`` nor a parent locator.

    Only the kernel's faces of revolution about setup Z through X0 Y0 can locate them; the
    kernel request asks it to measure them in every setup (turning setups measure every
    feature anyway).
    """
    return [
        name
        for name in _located_names(setup, features)
        if isinstance(name, str)
        and "at" not in mapping(features.get(name))
        and located_by(features, name, mapping(features.get(name)))[2] == name
    ]


def _sum(terms):
    return sum(terms) if all(number(v) for v in terms) else UNKNOWN


def model_point(point, frame):
    frame = mapping(frame)
    if not isinstance(point, list) or len(point) != 3:
        return [UNKNOWN] * 3
    origin = mapping_vector(frame.get("origin"))
    return [
        _sum(
            [origin[i]]
            + [
                point[j] * mapping_vector(frame.get(axis))[i]
                if number(point[j]) and number(mapping_vector(frame.get(axis))[i])
                else UNKNOWN
                for j, axis in enumerate(AXES)
                if mapping_vector(frame.get(axis))[i] != 0
            ]
        )
        for i in range(3)
    ]


def mapping_vector(value):
    return value if isinstance(value, list) and len(value) == 3 else [UNKNOWN] * 3


def frame_point(point, frame):
    frame = mapping(frame)
    if not isinstance(point, list) or len(point) != 3:
        return [UNKNOWN] * 3
    origin = mapping_vector(frame.get("origin"))
    result = []
    for axis in AXES:
        basis = mapping_vector(frame.get(axis))
        terms = [
            (point[i] - origin[i]) * basis[i]
            if all(number(v) for v in (point[i], origin[i], basis[i]))
            else UNKNOWN
            for i in range(3)
            if basis[i] != 0
        ]
        result.append(_sum(terms))
    return result


def _nominal(feature, key):
    explicit = feature.get(key + "_nominal", UNKNOWN)
    if number(explicit):
        return explicit
    return feature.get(key, UNKNOWN) if number(feature.get(key)) else UNKNOWN


def _samples(start, end, step):
    """Both exact endpoints plus grid checkpoints; no extrapolated full circle."""
    if not all(number(v) for v in (start, end, step)) or step <= 0:
        return []
    reverse = end < start
    low, high = sorted((start, end))
    values = (
        [low]
        + [i * step for i in range(math.floor(low / step) + 1, math.ceil(high / step))]
        + ([high] if high != low else [])
    )
    return list(reversed(values)) if reverse else values


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def cut_order(machine, op):
    """(required sign of (n x t)·Z or None, order record) from op direction and spindle.

    Only an authored ``conventional``/``climb`` op on a machine whose spindle ``rotation``
    is declared (bare, or a ``{value, measured}`` fact not flagged ``verify``) has a
    cutting order; anything else keeps the order unknown.
    """
    direction = op.get("direction", UNKNOWN)
    rotation = mapping(mapping(machine).get("spindle")).get("rotation", UNKNOWN)
    flagged = isinstance(rotation, dict) and rotation.get("verify") is True
    if isinstance(rotation, dict):
        rotation = rotation.get("value", UNKNOWN)
    if direction not in _CUT_SENSE:
        reason = f"op direction {direction!r} is neither conventional nor climb"
    elif flagged:
        reason = "the machine spindle rotation is flagged verify"
    elif rotation not in _SPINDLE_SENSE:
        reason = "the machine spindle rotation is not declared"
    else:
        sense = _CUT_SENSE[direction] * _SPINDLE_SENSE[rotation]
        return sense, {"cut_order": direction, "spindle_rotation": rotation}
    return None, {"cut_order": UNKNOWN, "cut_order_reason": reason}


def contouring(machine):
    """(the machine's contouring, or None, and why it is unknown).

    ``mdi`` types each arc or diagonal row as one coordinated MDI move; ``jog`` moves one
    handwheel axis at a time. Only a bare value or a ``{value, measured}`` fact not flagged
    ``verify`` declares it; anything else leaves arc and diagonal moves unproven.
    """
    value = mapping(machine).get("contouring", UNKNOWN)
    flagged = isinstance(value, dict) and value.get("verify") is True
    if isinstance(value, dict):
        value = value.get("value", UNKNOWN)
    if flagged:
        return None, "flagged verify"
    if value not in ("mdi", "jog"):
        return None, "not declared"
    return value, None


def _reversal(a, b, normal, sense):
    """Whether travel a->b (setup XY) must reverse to cut with ``sense``, or None.

    ``normal`` is the cutter-side wall normal there; an unknown sense, unknown values or a
    travel parallel to the normal cannot establish an order.
    """
    values = (*a, *b, *normal)
    if sense is None or not all(number(v) for v in values):
        return None
    turn = _cross(normal, [b[0] - a[0], b[1] - a[1]])
    if abs(turn) < 1e-12:
        return None
    return (turn > 0) != (sense > 0)


def _side(a, b, normal, reverse):
    """``left`` or ``right``: the side of the travel the cutter-side wall ``normal`` points
    to, for travel a->b (setup XY), reversed when ``reverse``; unknown when not determined.
    The kernel rounds a clipped point no nearer the walls: toward this side."""
    values = (*a, *b, *normal)
    if not all(number(v) for v in values):
        return UNKNOWN
    turn = _cross(normal, [b[0] - a[0], b[1] - a[1]])
    if abs(turn) < 1e-12:
        return UNKNOWN
    return "left" if (turn < 0) != (reverse is True) else "right"


def _ordered(record, reverse, order, keys):
    """Reverse ``keys`` lists for the traverse and stamp the order (unknown if unproven)."""
    if reverse is None:
        order = {"cut_order": UNKNOWN, **{k: v for k, v in order.items() if k != "cut_order"}}
        order.setdefault("cut_order_reason", "the traverse direction is not determined")
    elif reverse:
        for key in keys:
            record[key] = list(reversed(record[key]))
    record.update(order)
    return record


def _offset_line(a, b, offset):
    delta = [b[i] - a[i] for i in range(2)]
    norm = math.hypot(*delta)
    if norm == 0:
        return None
    direction = [v / norm for v in delta]
    return [a[0] - direction[1] * offset, a[1] + direction[0] * offset], direction


def _line_join(a, u, b, v):
    divisor = _cross(u, v)
    if abs(divisor) < 1e-12:
        return None
    t = _cross([b[i] - a[i] for i in range(2)], v) / divisor
    return [a[i] + t * u[i] for i in range(2)]


def _circle_join(point, direction, centre, radius, target):
    q = [point[i] - centre[i] for i in range(2)]
    dot = sum(q[i] * direction[i] for i in range(2))
    disc = dot * dot - sum(v * v for v in q) + radius * radius
    if disc < 0:
        return None
    roots = (-dot - math.sqrt(disc), -dot + math.sqrt(disc))
    candidates = [[point[i] + root * direction[i] for i in range(2)] for root in roots]
    return min(candidates, key=lambda p: math.dist(p, target))


def _top_join(top, linked, offset):
    """The upper arc's join needs each linked land, not its lower outline arc."""
    centre = top.get("arc_centre", top.get("at"))
    a, b = top.get("end"), linked.get("radial_tip_end")
    radius = _nominal(top, "radius")
    if not (
        all(isinstance(point, list) and len(point) >= 2 for point in (centre, a, b))
        and all(number(value) for point in (centre, a, b) for value in point)
        and all(number(value) for value in (radius, offset))
        and radius > offset
        and linked.get("frame", "model") == top.get("frame", "model")
    ):
        return None
    # The table spans the mirrored top arc. The -X land describes the same
    # join with reversed handedness, so evaluate it in the +X half-plane.
    a = [centre[0] + abs(a[0] - centre[0]), a[1]]
    b = [centre[0] + abs(b[0] - centre[0]), b[1]]
    land = _offset_line(a, b, offset)
    return _circle_join(*land, centre[:2], radius - offset, a) if land else None


def _joins(top, outer, offset):
    centre = outer.get("arc_centre")
    a, b, c = top.get("end"), outer.get("radial_tip_end"), outer.get("bottom_end")
    top_r, bottom_r = _nominal(top, "radius"), _nominal(outer, "bottom_radius")
    if not (
        isinstance(centre, list)
        and all(isinstance(v, list) and len(v) >= 2 for v in (a, b, c))
        and all(number(v) for point in (centre, a, b, c) for v in point)
        and all(number(v) for v in (top_r, bottom_r, offset))
    ):
        return None
    if top_r <= offset:
        return None
    land = _offset_line(a, b, offset)
    taper = _offset_line(b, c, offset)
    if land is None or taper is None:
        return None
    miter = _line_join(*land, *taper)
    upper = _circle_join(*land, centre[:2], top_r - offset, a)
    lower = _circle_join(*taper, centre[:2], bottom_r + offset, c)
    return [upper, miter, lower] if all(p is not None for p in (upper, miter, lower)) else None


def _xy_model(point, feature, frames):
    return model_point([point[0], point[1], 0.0], frames.get(feature.get("frame", "model")))


# Plan units within which a printed point still counts as no nearer a wall than its target.
_WALL_TOL = 1e-9
# Plan units within which two table ends are one join of the same cutter path.
_JOIN_TOL = 1e-6
# The DRO grid (plan units) of a machine whose inventory declares no ``resolution``: three
# decimals. The sheet prints, and the kernel checks, it.
DRO_DEFAULT_STEP = 0.001
# The operator note on a printed corner miter the kernel proves clear (rule A′).
OVERSHOOT_NOTE = "corner overshoot into scrap — OK"


def dro_grid(bundle, setup):
    """(step, decimals): the setup machine's DRO grid in plan units.

    The step is the inventory machine's declared ``resolution`` when it is a positive
    length, else :data:`DRO_DEFAULT_STEP`; the decimals print one step exactly.
    """
    units = bundle.features.get("units")
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    declared = length_mm(machine, "resolution") if scale else UNKNOWN
    step = declared / scale if number(declared) and declared > 0 else DRO_DEFAULT_STEP
    decimals = next((d for d in range(9) if abs(round(step, d) - step) <= 1e-12), 9)
    return step, decimals


def _grid(value, step, decimals, up):
    """``value`` on the DRO grid of ``step`` (printed at ``decimals``), rounded up (True)
    or down (False)."""
    steps = math.ceil(value / step - 1e-6) if up else math.floor(value / step + 1e-6)
    return round(steps * step, decimals)


def dro_z(value, grid):
    """A tip or floor Z as the DRO shows it on ``grid`` (:func:`dro_grid`): rounded up, so
    never deeper than authored; an unknown stays unknown."""
    return _grid(value, *grid, True) if number(value) else UNKNOWN


def _to_segment(point, a, b):
    delta = [b[i] - a[i] for i in range(2)]
    span = delta[0] ** 2 + delta[1] ** 2
    t = sum((point[i] - a[i]) * delta[i] for i in range(2)) / span if span else 0.0
    t = max(0.0, min(1.0, t))
    return math.dist(point, [a[i] + t * delta[i] for i in range(2)])


def _to_arc(point, centre, radius, a, b, middle):
    """Distance from ``point`` to the arc of ``radius`` about ``centre`` running from ``a``
    through ``middle`` to ``b``: radial inside its sector, else to the nearer end."""

    def angle(q):
        return math.atan2(q[1] - centre[1], q[0] - centre[0])

    sweep = (angle(b) - angle(a)) % math.tau
    if (angle(middle) - angle(a)) % math.tau > sweep:  # the arc runs the other way round
        a, b, sweep = b, a, math.tau - sweep
    if (angle(point) - angle(a)) % math.tau <= sweep:
        return abs(math.dist(point, centre) - radius)
    return min(math.dist(point, a), math.dist(point, b))


def _dro_xy(xy, grid, walls, offset):
    """``xy`` as the DRO prints it on ``grid`` (:func:`dro_grid`), on the safe side: the
    nearest grid point no nearer any wall (``walls``: point -> distance) than ``xy`` or
    than the authored cutter-centre ``offset``, whichever is less; a corner of its grid
    cell, else up to two steps out, else unknown."""
    if not walls or not all(number(v) for v in xy):
        return [UNKNOWN, UNKNOWN]
    step, decimals = grid
    base = [_grid(v, step, decimals, False) for v in xy]
    floors = [min(wall(xy), offset) - _WALL_TOL for wall in walls]
    for reach in (1, 3):
        span = range(1 - reach, reach + 1)
        options = [
            [round(base[0] + i * step, decimals), round(base[1] + j * step, decimals)]
            for i in span
            for j in span
        ]
        for point in sorted(options, key=lambda p: math.dist(p, xy)):
            if all(wall(point) >= low for wall, low in zip(walls, floors, strict=True)):
                return point
    return [UNKNOWN, UNKNOWN]


def _printed(arcs, lines, grid, walls, offset):
    """Stamp every row and join point with the value the DRO prints: ``dro_xy``
    (:func:`_dro_xy`) and ``dro_tip_z`` (:func:`dro_z`). The sheet prints these; the kernel
    clips, checks and credits them. Points within _JOIN_TOL of each other (a table end and
    the join it meets) print one value."""
    done = []

    def dro(xy):
        if all(number(v) for v in xy):
            for point, value in done:
                if math.dist(point, xy) <= _JOIN_TOL:
                    return value
        value = _dro_xy(xy, grid, walls, offset)
        done.append((xy, value))
        return value

    for arc in arcs:
        arc["dro_tip_z"] = dro_z(arc.get("tip_z"), grid)
        for row in arc["rows"]:
            row["dro_xy"] = dro(row["setup_xy"])
            row["dro_tip_z"] = dro_z(row.get("tip_z"), grid)
    for line in lines:
        line["dro_tip_z"] = dro_z(line.get("tip_z"), grid)
        line["dro_xy"] = [dro(xy) for xy in line["setup_xy"]]


# Points per leg where a single-axis step is checked clear of the part and its cusp measured.
_STAIR_SAMPLES = 16


def _axis_tangents(angles, start, hand):
    """``angles`` (feature degrees) plus, between neighbours, each angle at which the arc
    is tangent to a setup axis (its setup X or Y extreme), where no single-axis step can
    stay on the scrap side. ``start`` is the setup angle of ``angles[0]`` about the arc
    centre and ``hand`` (+1 or -1) the handedness of the feature-to-setup map."""
    result = list(angles[:1])
    for a, b in itertools.pairwise(angles):
        ends = sorted(start + hand * (value - angles[0]) for value in (a, b))
        quarters = range(math.floor((ends[0] + 1e-7) / 90) + 1, math.ceil((ends[1] - 1e-7) / 90))
        between = [angles[0] + hand * (90 * quarter - start) for quarter in quarters]
        result.extend(sorted(between, reverse=b < a))
        result.append(b)
    return result


def _route_points(route):
    for a, b in itertools.pairwise(route):
        for k in range(_STAIR_SAMPLES + 1):
            yield [a[i] + k / _STAIR_SAMPLES * (b[i] - a[i]) for i in range(2)]


def _stair(printed, path, normal, walls, cutter, offset):
    """(routes, cusp, None) or (None, None, why not): single-axis handwheel moves through
    the ``printed`` points (setup XY).

    Each route runs from one printed point to the next. Where they differ on both axes it
    turns one corner, (b.x, a.y) or (a.x, b.y): one whose legs come no nearer any wall
    (``walls``: point -> distance) than the cutter-centre ``offset`` (or than either end,
    if that is nearer: :func:`_dro_xy`), the farther from the walls (the scrap side). The
    cusp is the most material a target-surface point (``offset - cutter`` from a wall, so
    none past a wall's end) keeps from the stepped cutter of radius ``cutter``:
    ``path(k, t)`` is the exact cutter centre a fraction t from point k to k + 1 and
    ``normal(k, xy)`` its unit normal from the wall toward the cutter.
    """
    if not walls or not number(cutter) or not all(_pair(p) for p in printed):
        return None, None, "its printed points or walls are unknown"
    routes = []
    for a, b in itertools.pairwise(printed):
        floors = [min(offset, wall(a), wall(b)) - _WALL_TOL for wall in walls]
        options = (
            [[a, b]]
            if a[0] == b[0] or a[1] == b[1]
            else [[a, [b[0], a[1]], b], [a, [a[0], b[1]], b]]
        )
        clear = [
            route
            for route in options
            if all(
                wall(p) >= floor
                for p in _route_points(route)
                for wall, floor in zip(walls, floors, strict=True)
            )
        ]
        if not clear:
            return None, None, f"no single-axis step from {a} to {b} stays clear of the part"
        routes.append(max(clear, key=lambda route: min(wall(route[1]) for wall in walls)))
    cusp = 0.0
    for k in range(len(routes)):
        legs = [leg for route in routes[max(0, k - 1) : k + 2] for leg in itertools.pairwise(route)]
        for i in range(1, _STAIR_SAMPLES):
            xy = path(k, i / _STAIR_SAMPLES)
            n = normal(k, xy)
            face = [xy[j] - cutter * n[j] for j in range(2)]
            if abs(min(wall(face) for wall in walls) - (offset - cutter)) > _JOIN_TOL:
                continue  # past a wall's end (a join's miter run-out): no surface there
            cusp = max(cusp, min(_to_segment(face, p, q) for p, q in legs) - cutter)
    return routes, cusp, None


def _steps(routes):
    """Each route's points after its first as (point, axis moved, printed row index or None
    for a corner): the order the handwheel steps them."""
    for k, route in enumerate(routes):
        for p, q in itertools.pairwise(route):
            yield q, "Y" if p[0] == q[0] else "X", k + 1 if q is route[-1] else None


def _stair_band(feature, key, outward):
    """The material a stair may leave on an arc wall: the feature's ``key`` band between
    nominal and its limit on the material side (``outward``: the cutter runs outside the
    wall radius, so material left grows it), halved for a diameter; else unknown."""
    band, nominal = feature.get(key), _nominal(feature, key)
    if not (
        isinstance(band, list)
        and len(band) == 2
        and all(number(v) for v in band)
        and number(nominal)
    ):
        return UNKNOWN
    margin = band[1] - nominal if outward > 0 else nominal - band[0]
    return margin / 2 if key == "dia" else margin


def _jog(arc, lines, centre, outward, walls, cutter, offset):
    """Step ``arc`` and its join ``lines`` in single-axis moves (:func:`_stair`, walls kept
    ``offset`` away): each row names the axis (``jog``) moved to reach it and each corner
    is a row of its own (``corner``); each table records its ``stair_cusp_mm``, else its
    ``stair_reason``."""
    rows = arc["rows"]
    exact = [row["setup_xy"] for row in rows]
    if not (_pair(centre) and all(_pair(p) for p in exact)):
        arc["stair_reason"] = "its cutter-centre path is unknown"
        return
    turns = [math.atan2(p[1] - centre[1], p[0] - centre[0]) for p in exact]
    radius = arc["cutter_centre_radius_mm"]

    def along(k, t):
        sweep = (turns[k + 1] - turns[k] + math.pi) % math.tau - math.pi
        angle = turns[k] + t * sweep
        return [centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)]

    def radial(k, xy):
        span = math.dist(xy, centre)
        return [outward * (xy[i] - centre[i]) / span for i in range(2)]

    routes, cusp, why = _stair(
        [row["dro_xy"] for row in rows], along, radial, walls, cutter, offset
    )
    if why:
        arc["stair_reason"] = why
        return
    stepped = [rows[0]]
    for point, axis, index in _steps(routes):
        row = rows[index] if index is not None else None
        if row is None:
            row = {
                "angle_deg": UNKNOWN,
                "model_xy": [UNKNOWN, UNKNOWN],
                "setup_xy": list(point),
                "x": point[0],
                "y": point[1],
                "tip_z": stepped[-1].get("tip_z"),
                "dro_xy": list(point),
                "dro_tip_z": stepped[-1].get("dro_tip_z"),
                "corner": True,
            }
        row["jog"] = axis
        stepped.append(row)
    arc.update(rows=stepped, stair_cusp_mm=cusp)
    for line in lines:
        exact = line["setup_xy"]
        if not all(_pair(p) for p in exact):
            line["stair_reason"] = "its cutter-centre path is unknown"
            continue

        def straight(k, t, exact=exact):
            return [exact[k][i] + t * (exact[k + 1][i] - exact[k][i]) for i in range(2)]

        def away(k, xy, exact=exact):
            """The leg's unit normal toward the side farther from the walls."""
            delta = [exact[k + 1][i] - exact[k][i] for i in range(2)]
            span = math.hypot(*delta) or 1.0
            n = [-delta[1] / span, delta[0] / span]
            ahead = min(wall([xy[i] + 1e-3 * n[i] for i in range(2)]) for wall in walls)
            behind = min(wall([xy[i] - 1e-3 * n[i] for i in range(2)]) for wall in walls)
            return n if ahead >= behind else [-n[0], -n[1]]

        routes, cusp, why = _stair(line["dro_xy"], straight, away, walls, cutter, offset)
        if why:
            line["stair_reason"] = why
            continue
        columns = {key: [line[key][0]] for key in _LINE_COLUMNS}
        columns["jog"] = [None]
        for point, axis, index in _steps(routes):
            corner = {
                "model_xy": [UNKNOWN, UNKNOWN],
                "setup_xy": list(point),
                "dro_xy": list(point),
                "overshoot": False,
            }
            for key in _LINE_COLUMNS:
                columns[key].append(corner[key] if index is None else line[key][index])
            columns["jog"].append(axis)
        line.update(columns, stair_cusp_mm=cusp)


def _arc(
    feature_name,
    feature,
    op,
    offset,
    frame,
    frames,
    features,
    sense,
    order,
    grid,
    capability=None,
    cutter=UNKNOWN,
):
    """([the arc table], join lines) in cutting order for ``sense`` (see cut_order).

    The cutter-side wall normal is radial: outward when the cutter centre runs outside the
    wall radius, inward on a concave wall. A join's normal is its offset land's normal.
    Every row and join point carries the value the DRO prints on ``grid``
    (:func:`dro_grid`), never nearer the feature's walls (:func:`_printed`); each join's
    corner miter, the run-out past its land and taper walls, is flagged ``overshoot``. A
    bounded op's tables are whole here: the kernel clips them (:func:`_kernel_clip`). On a
    ``jog`` machine (``capability``) the rows include each setup-axis tangent and step in
    single-axis moves of a cutter of radius ``cutter`` (:func:`_jog`), with the band its
    stair is held to (``stair_band_mm``, :func:`_stair_band`).
    """
    radius = _nominal(feature, "radius")
    centre = feature.get("arc_centre", feature.get("at"))
    full = feature.get("kind") in {"boss", "cylinder"}
    if full:
        diameter = _nominal(feature, "dia")
        radius = diameter / 2 if number(diameter) else UNKNOWN
    bottom = "bottom_radius" in feature
    if bottom:
        radius = _nominal(feature, "bottom_radius")
    if not (
        number(radius)
        and number(offset)
        and isinstance(centre, list)
        and len(centre) == 3
        and all(number(v) for v in centre)
    ):
        return [], []
    cutter_radius = radius + offset
    start, end = 0.0, 360.0 if full else 180.0
    vertical_angle = False
    joins = None
    lands = []  # a top arc's linked land segments (model xy): walls its end rows meet
    if "end" in feature or bottom:
        vertical_angle = True
        if bottom:
            top = mapping(features.get(feature.get("top_edge_feature")))
            joins = _joins(top, feature, offset)
            if joins is None:
                return [], []
            endpoint = joins[2] if joins else feature.get("bottom_end")
        else:
            cutter_radius = radius - offset
            linked = [f for f in features.values() if f.get("top_edge_feature") == feature_name]
            endpoints = [_top_join(feature, linked_feature, offset) for linked_feature in linked]
            if linked:
                if any(point is None for point in endpoints):
                    return [], []
                endpoint = endpoints[0]
                if any(math.dist(endpoint, point) > 1e-9 for point in endpoints[1:]):
                    return [], []
                # Each land as _top_join takes it, on both halves of the mirrored top arc.
                lands = [
                    [
                        [centre[0] + side * abs(p[0] - centre[0]), p[1]]
                        for p in (feature["end"], linked_feature["radial_tip_end"])
                    ]
                    for linked_feature in linked
                    for side in (-1, 1)
                ]
            else:
                endpoint = feature.get("end")
        if not isinstance(endpoint, list) or not all(number(v) for v in endpoint):
            return [], []
        half = math.degrees(math.atan2(endpoint[0] - centre[0], centre[1] - endpoint[1]))
        start, end = -half, half
    elif not full and feature.get("arc") != "upper_semicircle":
        return [], []
    if cutter_radius <= 0:
        return [], []
    step = mapping(op.get("contour")).get("step_deg", UNKNOWN)
    angles = _samples(start, end, step)

    def row_at(angle):
        theta = math.radians(angle)
        xy = (
            [
                centre[0] + cutter_radius * math.sin(theta),
                centre[1] - cutter_radius * math.cos(theta),
            ]
            if vertical_angle
            else [
                centre[0] + cutter_radius * math.cos(theta),
                centre[1] + cutter_radius * math.sin(theta),
            ]
        )
        local = frame_point(_xy_model(xy, feature, frames), frame)
        return {
            "angle_deg": angle,
            "model_xy": xy,
            "setup_xy": local[:2],
            "x": local[0],
            "y": local[1],
            "tip_z": op.get("to_z", UNKNOWN),
        }

    model_centre = model_point(centre, frames.get(feature.get("frame", "model")))
    centre_xy = frame_point(model_centre, frame)[:2]
    if capability == "jog" and len(angles) >= 2 and _pair(centre_xy):
        probe = [row_at(angles[0] + delta)["setup_xy"] for delta in (0.0, 1.0)]
        if all(_pair(point) for point in probe):
            first, second = (
                math.degrees(math.atan2(p[1] - centre_xy[1], p[0] - centre_xy[0])) for p in probe
            )
            hand = 1 if (second - first + 180) % 360 - 180 > 0 else -1
            angles = _axis_tangents(angles, first, hand)
    rows = [row_at(angle) for angle in angles]
    outward = 1 if cutter_radius > radius else -1
    reverse, arc_side = None, UNKNOWN
    if len(rows) >= 2 and cutter_radius != radius and all(number(v) for v in centre_xy):
        a, b = rows[len(rows) // 2 - 1]["setup_xy"], rows[len(rows) // 2]["setup_xy"]
        if all(number(v) for v in (*a, *b)):
            normal = [outward * ((a[i] + b[i]) / 2 - centre_xy[i]) for i in range(2)]
            reverse = _reversal(a, b, normal, sense)
            arc_side = _side(a, b, normal, reverse)
    arc = {
        "feature": feature_name,
        "op": op["op"],
        "method": "arc_table",
        "step_deg": step,
        "centre_model_xy": model_centre[:2],
        "centre_setup_xy": centre_xy,
        "cutter_centre_radius_mm": cutter_radius,
        "radius_mm": cutter_radius,
        "full_circle": full,
        "tip_z": op.get("to_z", UNKNOWN),
        "rows": rows,
        "basis": (
            "nominal selected cutter size; measured geometry and frame binding "
            + "govern readiness"
        ),
    }
    _ordered(arc, reverse, order, ("rows",))
    arc["cutter_side"] = arc_side
    if capability == "jog":
        key = "dia" if full else "bottom_radius" if bottom else "radius"
        arc["stair_band_mm"] = _stair_band(feature, key, outward)
    walls, miters = [], []  # point -> distance to each feature wall; join miter points
    known = all(number(v) for v in centre_xy)  # else no wall is placed and no DRO value

    def setup_xy(point):
        return frame_point(_xy_model(point, feature, frames), frame)[:2]

    def rim(wall_radius, end_xy):
        """point -> distance to the wall arc of ``wall_radius`` about the centre: mirrored
        from ``end_xy`` through its lowest point (an upper semicircle's highest), a full
        circle when ``end_xy`` is None. Never its circle past its ends."""
        if end_xy is None:
            return lambda p: abs(math.dist(p, centre_xy) - wall_radius)
        dip = -wall_radius if vertical_angle else wall_radius
        mirror = [2 * centre[0] - end_xy[0], end_xy[1]]
        a, b, m = (setup_xy(q) for q in (end_xy, mirror, [centre[0], centre[1] + dip]))
        return lambda p: _to_arc(p, centre_xy, wall_radius, a, b, m)

    if known:
        if full:
            walls.append(rim(radius, None))
        elif vertical_angle:  # _joins, _top_join or the endpoint check validated the end
            walls.append(rim(radius, feature["bottom_end"] if bottom else feature["end"]))
        else:
            walls.append(rim(radius, [centre[0] + radius, centre[1]]))
    for a, b in ([setup_xy(a), setup_xy(b)] for a, b in lands):
        known = known and all(number(v) for v in (*a, *b))
        walls.append(lambda p, a=a, b=b: _to_segment(p, a, b))
    lines = []
    if bottom and joins:
        sides = (-1, 1) if feature.get("mirror_symmetric") is True else (1,)
        # _joins validated both land ends; the land's unit left normal is its cutter side.
        top_end = mapping(features.get(feature.get("top_edge_feature")))["end"]
        shifted, _ = _offset_line(top_end, feature["radial_tip_end"], 1.0)
        left = [shifted[i] - top_end[i] for i in range(2)]
        top_r = _nominal(top, "radius")
        if known:
            walls.append(rim(top_r, top_end))
        for side in sides:
            xy = [[centre[0] + side * (p[0] - centre[0]), p[1]] for p in joins]
            local = [setup_xy(p) for p in xy]
            wall = setup_xy([xy[0][0] - side * left[0] * offset, xy[0][1] - left[1] * offset])
            ends = [
                setup_xy([centre[0] + side * (p[0] - centre[0]), p[1]])
                for p in (top_end, feature["radial_tip_end"], feature["bottom_end"])
            ]
            known = known and all(number(v) for point in ends for v in point)
            for a, b in itertools.pairwise(ends):
                walls.append(lambda p, a=a, b=b: _to_segment(p, a, b))
            miters.append(xy[1])
            normal = [
                local[0][i] - wall[i] if number(local[0][i]) and number(wall[i]) else UNKNOWN
                for i in range(2)
            ]
            line = {
                "op": op["op"],
                "feature": feature_name,
                "side": "+X" if side == 1 else "-X",
                "model_xy": xy,
                "setup_xy": local,
                "offset_mm": offset,
                "tip_z": op.get("to_z", UNKNOWN),
                "join_method": "line-line miter and exact line-circle intersections",
            }
            reverse = _reversal(local[0], local[1], normal, sense)
            lines.append(_ordered(line, reverse, order, ("model_xy", "setup_xy")))
            line["cutter_side"] = _side(local[0], local[1], normal, reverse)
    if not rows:
        return [], []
    _printed([arc], lines, grid, walls if known else [], offset)
    for line in lines:
        line["overshoot"] = [any(p is m for m in miters) for p in line["model_xy"]]
        if any(line["overshoot"]):
            line["overshoot_note"] = OVERSHOOT_NOTE
    if capability == "jog":
        _jog(arc, lines, centre_xy, outward, walls if known else [], cutter, offset)
    return [arc], lines


def _boundary(feature, frame, frames):
    bounds = mapping(feature.get("bounds"))
    if not all(
        axis in bounds
        and isinstance(bounds[axis], list)
        and len(bounds[axis]) == 2
        and all(number(v) for v in bounds[axis])
        for axis in AXES
    ):
        return None
    points = [
        frame_point(model_point(list(p), frames.get(feature.get("frame", "model"))), frame)
        for p in itertools.product(*(bounds[axis] for axis in AXES))
    ]
    if not all(number(v) for p in points for v in p[:2]):
        return None
    points = sorted(set(tuple(p[:2]) for p in points))
    if len(points) < 3:
        return None

    def half(sequence):
        hull = []
        for p in sequence:
            while (
                len(hull) >= 2
                and _cross(
                    [hull[-1][i] - hull[-2][i] for i in range(2)],
                    [p[i] - hull[-1][i] for i in range(2)],
                )
                <= 0
            ):
                hull.pop()
            hull.append(p)
        return hull

    return half(points)[:-1] + half(reversed(points))[:-1]


def _sweep_area(feature, op, frame, frames):
    """Setup-XY corners of the area a ``linear_table`` sweeps, or None: ``contour.
    sweep_bounds`` in ``sweep_frame``, else a face op's setup-frame
    ``stock_removal_bounds``, else the feature's own bounds."""
    contour = mapping(op.get("contour"))
    if isinstance(contour.get("sweep_bounds"), dict):
        envelope = {
            **feature,
            "bounds": contour["sweep_bounds"],
            "frame": contour.get("sweep_frame", feature.get("frame", "model")),
        }
        return _boundary(envelope, frame, frames)
    box = op.get("stock_removal_bounds")
    if op.get("do") in FACING and isinstance(box, dict):
        spans = [box.get(axis) for axis in ("x", "y")]
        if not all(
            isinstance(span, list) and len(span) == 2 and all(number(v) for v in span)
            for span in spans
        ):
            return None
        (x0, x1), (y0, y1) = spans
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return _boundary(feature, frame, frames)


def _linear(feature, op, offset, radius, frame, frames):
    boundary = _sweep_area(feature, op, frame, frames)
    if not boundary or not all(number(v) for v in (offset, radius)):
        return None
    lines = [
        _offset_line(boundary[i], boundary[(i + 1) % len(boundary)], -offset)
        for i in range(len(boundary))
    ]
    if any(line is None for line in lines):
        return None
    vertices = [_line_join(*lines[i - 1], *lines[i]) for i in range(len(lines))]
    return vertices + [vertices[0]] if all(v is not None for v in vertices) else None


# Raster ops: each pass is one straight single-axis cut fed one way at the op's Z, then the
# cutter lifts to its retract height and rapids back to the next pass's start.
RASTER_OPS = POCKETING | FACING
# An open side's unit vector: every pass's cutter-side wall normal, from the uncut stock
# ahead of the stepping cutter back toward the cleared side it steps away from.
_OPEN_SIDES = {"-x": (-1.0, 0.0), "+x": (1.0, 0.0), "-y": (0.0, -1.0), "+y": (0.0, 1.0)}
# Milling ops whose authored ``doc_mm`` steps them down in axial levels.
_LEVEL_OPS = RASTER_OPS | {"profile", "rough_profile", "finish_profile"}
# Wall-finishing ops: the cutter's flank engages the whole wall above its tip.
_WALL_OPS = {"pocket", "finish_pocket", "profile", "finish_profile"}


def _raster(feature, op, offset, radius, frame, frames, sense, order, lift_z):
    """(One stage's raster record in cutting order, None) or (None, why it is unknown).

    Passes stand at positions across the area, stepping from its open side
    (``contour.open_side``) toward the far side, and each runs one cutter radius past both
    ends of the area. A pocket's first pass enters wholly outside the open side, the next
    are ``step_mm`` apart and the last stops ``offset`` short of the retained far wall. A
    face's passes are evenly spaced no more than ``step_mm`` apart from centre-on-edge to
    centre-on-edge, clearing the whole area; without an open side it steps from the low
    side of the area's shorter span, so its passes run along the longer one.

    The uncut stock lies ahead of the stepping cutter, so every pass's cutter-side wall
    normal is the open side's unit vector: each pass runs the way that cuts the op's
    ``direction`` with the spindle (:func:`_reversal`), else the order is unknown. The
    cycle is one way: feed a pass, lift to ``lift_z``, rapid back to the next pass's start.
    """
    face = op.get("do") in FACING
    contour = mapping(op.get("contour"))
    step = contour.get("step_mm", UNKNOWN)
    if not number(step) or step <= 0:
        return None, "a raster needs a positive contour.step_mm"
    if not number(radius) or radius <= 0:
        return None, "its cutter radius is unknown"
    if not face and not number(offset):
        return None, "its cutter-centre offset from the far wall is unknown"
    if step > 2 * radius:
        return None, f"its step_mm {step:g} exceeds the cutter diameter {2 * radius:g}"
    boundary = _sweep_area(feature, op, frame, frames)
    if not boundary:
        return None, "its swept area has no numeric bounds"
    left, right = min(p[0] for p in boundary), max(p[0] for p in boundary)
    front, back = min(p[1] for p in boundary), max(p[1] for p in boundary)
    side = contour.get("open_side")
    if face and side is None:
        side = "-y" if right - left >= back - front else "-x"
    if side not in _OPEN_SIDES:
        return None, f"its contour.open_side {side!r} is not one of -x, +x, -y, +y"
    along_x = side.endswith("x")  # passes stand at X positions and run along Y
    low, high = (left, right) if along_x else (front, back)
    if face:
        count = math.ceil((high - low) / step - 1e-9)
        positions = (
            [low + (high - low) * i / count for i in range(count + 1)]
            if count > 1
            else [(low + high) / 2]
        )
        if side.startswith("+"):
            positions.reverse()
    else:
        start, end = (
            (low - radius, high - offset) if side.startswith("-") else (high + radius, low + offset)
        )
        direction = 1 if end >= start else -1
        count = math.ceil(abs(end - start) / step)
        positions = [start + direction * i * step for i in range(count)] + [end]
    first, last = (front, back) if along_x else (left, right)
    passes = [
        [[v, first - radius], [v, last + radius]]
        if along_x
        else [[first - radius, v], [last + radius, v]]
        for v in positions
    ]
    reverse = _reversal(*passes[0], _OPEN_SIDES[side], sense)
    if reverse:
        passes = [list(reversed(segment)) for segment in passes]
    record = {
        "cutter_centre": passes,
        "raster": {
            "open_side": side,
            "open_side_basis": "contour.open_side" if "open_side" in contour else "derived",
            "step_mm": step,
            "passes": len(passes),
            "cycle": "one_way",
            "lift_z": lift_z,
        },
    }
    return _ordered(record, None if reverse is None else False, order, ()), None


def _z_levels(op, before, declared, grid, units):
    """The axial Z levels of a milling op that authors ``doc_mm``, else None.

    Levels step from the op's start surface down to its DRO depth, each on the DRO grid and
    no more than ``doc_mm`` below the one before; the last is the DRO depth itself. A
    wall-finishing op starts at its feature's declared setup ``entry_z`` (never one an
    earlier op's floor advanced), else the current top, as its flank engages the whole
    wall; any other op starts at its feature's current entry, else the current top.
    """
    if op.get("do") not in _LEVEL_OPS or "doc_mm" not in op or "to_z" not in op:
        return None
    name, top = op.get("feature"), before["top_z"]
    if op["do"] in _WALL_OPS:
        start = declared.get(name, top)
        basis = "declared entry_z" if name in declared else "setup top_z"
    else:
        start = before["entry_z"].get(name, top)
        basis = "entry_z" if name in before["entry_z"] else "setup top_z"
    end, doc = dro_z(op["to_z"], grid), op["doc_mm"]
    record = {"start_z": start, "start_basis": basis, "dro_start_z": dro_z(start, grid)}
    record.update(dro_to_z=end, doc_mm=doc)
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    step, decimals = grid
    depth = doc / scale if scale and number(doc) and doc > 0 else UNKNOWN
    lattice = math.floor(depth / step + 1e-6) * step if number(depth) else 0
    if not (number(start) and number(end)) or lattice <= 0:
        record.update(levels=UNKNOWN, count=UNKNOWN)
        record["reason"] = "its start Z, DRO depth, plan units or doc_mm is unknown"
        return record
    levels, z = [], _grid(start - depth, step, decimals, True)
    while z > end + _WALL_TOL:
        levels.append(z)
        z = round(z - lattice, decimals)
    record.update(levels=[*levels, end], count=len(levels) + 1)
    return record


def _lathe_rows(name, feature, setup, frame, frames, radius_mode):
    rows = []
    diameter = _nominal(feature, "dia")
    if not number(diameter) and number(feature.get("base_radius")):
        diameter = 2 * feature["base_radius"]
    stations = feature.get("z_mm", [])
    if isinstance(stations, list):
        for index, z in enumerate(stations):
            model = model_point([0.0, 0.0, z], frames.get(feature.get("frame", "model")))
            rows.append(
                {
                    "feature": name,
                    "point": f"drawing station {index + 1}",
                    "model": model,
                    "setup": frame_point(model, frame),
                    "dia_nominal": diameter,
                    "x_target_mm": diameter / 2 if radius_mode and number(diameter) else diameter,
                }
            )
    for op in setup["ops"]:
        if op.get("feature") != name:
            continue
        for field in ("to_z", "z_from", "z_to"):
            z = op.get(field)
            if not number(z):
                continue
            unbound = not frame or frame.get("binding") == UNKNOWN
            model = model_point([0.0, 0.0, UNKNOWN if unbound else z], frame)
            local = frame_point(model, frame)
            row = {
                "feature": name,
                "point": f"op {op['op']} {field}",
                "model": model,
                "setup": local,
                "dia_nominal": diameter,
                "x_target_mm": diameter / 2 if radius_mode and number(diameter) else diameter,
            }
            if unbound and local[2] == UNKNOWN:
                row["setup"][2] = z
                row["local_from"] = {"op": op["op"], "field": field, "axis": "z"}
            rows.append(row)
    return rows


def _axis_rows(bundle, setup, name, feature, frame, dro, lathe):
    """(rows, citation, None) locating a feature on setup Z through X0 Y0 at both ends of
    its kernel-measured axial span, or ([], None, why not) when the kernel did not measure
    every face revolved about setup Z through the origin (``turned_profile.spindle_span``).

    On a lathe that axis is the spindle and the rows carry the DRO X target; on any other
    machine they are setup X0 Y0 points, transformed to the model through the setup frame.
    """
    from .turned_profile import spindle_span

    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if scale is None:
        return [], None, "feature units are not mm or in"
    span, cite = spindle_span(bundle, setup, name)
    if span is None:
        return [], None, f"kernel: {cite}"
    diameter = _nominal(feature, "dia")
    radius_mode = dro.get("radius_mode") is True
    rows = []
    for end, z in zip(("start", "end"), span, strict=True):
        local = [0.0, 0.0, z / scale]
        row = {
            "feature": name,
            "point": f"{'spindle' if lathe else 'setup Z'} axis, kernel span {end}",
            "model": model_point(local, frame),
            "setup": local,
        }
        if lathe:
            row["dia_nominal"] = diameter
            row["x_target_mm"] = diameter / 2 if radius_mode and number(diameter) else diameter
        rows.append(row)
    return rows, cite, None


def _nose_arc(edges):
    """(lowest, highest) contact-normal angle in degrees, measured from +X (radially out)
    toward +Z, that a right-hand insert's nose arc spans: its major edge (entering angle
    ``kappa`` from the -Z feed) bounds it at ``kappa``, its trailing edge at
    ``kappa + insert - 180``. (None, reason) when the edge facts do not establish it."""
    edges = mapping(edges)
    kappa, insert = edges.get("entering_angle_deg"), edges.get("insert_angle_deg")
    if edges.get("hand") != "right":
        return None, "the nose arc is modelled for a right-hand tool feeding toward the chuck"
    if not (number(kappa) and number(insert)) or kappa <= 0 or insert <= 0:
        return None, "the selected tool's entering or insert angle is unknown"
    if kappa + insert >= 180:
        return None, "the selected tool's entering and insert angles do not form an insert"
    return (kappa + insert - 180, kappa), None


def _dome(name, feature, op, radius_mode, nose=UNKNOWN, edges=None):
    """Axial table of the dome's finished surface and, when the selected insert's nose arc
    spans every row's contact normal, the imaginary-tip readings of a tool touched off on
    an outside diameter (X) and a +Z end face (Z), the lathe tool-touch convention: the
    nose centre sits ``nose`` along the surface normal, so the tip reads ``nose * (n - 1)``
    from the surface point per axis. A normal outside the arc is cut by an edge or flank,
    not the nose, so no nose offset holds there."""
    sphere = feature.get("sphere_radius", UNKNOWN)
    apex, base = op.get("z_from", UNKNOWN), op.get("z_to", UNKNOWN)
    step = mapping(op.get("contour")).get("step_mm", UNKNOWN)
    if not all(number(v) for v in (sphere, apex, base, step)) or sphere <= 0 or step <= 0:
        return None
    sign = 1 if apex > base else -1
    centre = apex - sign * sphere
    arc, arc_reason = _nose_arc(edges)
    if not number(nose) or nose < 0:
        compensation, why = UNKNOWN, "the selected tool's nose radius is unknown"
    elif sign < 0:
        compensation, why = UNKNOWN, "the dome apex faces the chuck, not the +Z touch-off face"
    elif arc is None:
        compensation, why = UNKNOWN, arc_reason
    else:
        compensation, why = nose, None
    display = 1 if radius_mode else 2
    rows = []
    count = math.ceil(abs(apex - base) / step)
    for i in range(count + 1):
        z = base if i == count else apex - sign * i * step
        squared = sphere * sphere - (z - centre) ** 2
        if squared < -1e-10:
            return None
        radius = math.sqrt(max(0, squared))
        normal_r, normal_z = radius / sphere, (z - centre) / sphere
        rows.append(
            {
                "z_mm": z,
                "radius_mm": radius,
                "diameter_mm": 2 * radius,
                "x_target_mm": display * radius,
                "setup_xz": [display * radius, z],
                "normal_deg": math.degrees(math.atan2(normal_z, normal_r)),
            }
        )
    if why is None:
        outside = [r["z_mm"] for r in rows if not arc[0] - 1e-9 <= r["normal_deg"] <= arc[1] + 1e-9]
        if outside:
            compensation = UNKNOWN
            why = (
                f"contact normals at Z {', '.join(f'{z:g}' for z in outside)} lie outside the "
                f"nose arc {arc[0]:g}°..{arc[1]:g}°, so an edge, not the nose, meets them"
            )
    if why is None:
        for row in rows:
            normal = math.radians(row["normal_deg"])
            row["x_tool_mm"] = display * (row["radius_mm"] + nose * (math.cos(normal) - 1))
            row["z_tool_mm"] = row["z_mm"] + nose * (math.sin(normal) - 1)
    contour = {
        "feature": name,
        "op": op["op"],
        "method": "axial_table",
        "rows": rows,
        "sphere_radius_mm": sphere,
        "sphere_centre_z_mm": centre,
        "apex_z_mm": apex,
        "base_z_mm": base,
        "step_mm": step,
        "tool_nose_compensation_mm": compensation,
        "tool_reference": "imaginary tip: X touched on an outside diameter, Z on a +Z end face",
    }
    if why is not None:
        contour["tool_nose_compensation_reason"] = why
    return contour


def _edge_facts(bundle, op):
    """The selected turning insert's hand and accepted entering/insert angles (degrees)."""
    from ._envelope import measurement_item

    item = measurement_item(bundle, "tools", op.get("tool"))
    angles = {}
    for field in ("entering_angle_deg", "insert_angle_deg"):
        fact = angle_fact(item, field, require_measured=False)
        angles[field] = fact["value"] if fact["verified"] else UNKNOWN
    return {"hand": mapping(item).get("hand", UNKNOWN), **angles}


# A printed row's id (:func:`row_id`) is its table's name, ``FRAGMENT_FORMAT`` for a piece
# of a clipped table, then ``ROW_FORMAT``: the kernel names the rows of each piece it clips
# (:func:`checkpoints`) with these same formats.
ROW_FORMAT = {"arc_table": " row {}", "line_table": "[{}]"}
FRAGMENT_FORMAT = " fragment {}"


def _table_name(subject, kind, table):
    name = f"{subject} {table.get('stage')} " + (
        "arc" if kind == "arc_table" else f"line {table.get('side')}"
    )
    if "fragment" in table:
        name += FRAGMENT_FORMAT.format(table["fragment"][0])
    return name


def row_id(subject, kind, table, index):
    """A printed row's id: ``S1:40 rough arc row 3`` (``arc_table``) or ``S1:40 rough line
    +X[0]`` (``line_table``); a piece of a clipped table adds ``fragment k``."""
    return _table_name(subject, kind, table) + ROW_FORMAT[kind].format(index)


def checkpoints(subject, numbers, op):
    """Each printed cutter-centre table of op ``op``'s arc_table output, in cutting order.

    A table is its ``name`` and ``kind`` (:func:`row_id`), its ``rows`` of (row id,
    printed setup XY ``dro_xy``, printed tip Z ``dro_tip_z``, corner overshoot?) in plan
    units, whether the kernel must clip it at its op's stock_removal_bounds (``bounded``)
    and the side of its travel its cutter clears from (``cutter_side``). What the DRO
    shows is what the kernel clips and checks.
    """
    result = []
    for kind in ("arc_table", "line_table"):
        for table in numbers.get(kind, []):
            if table.get("op") != op:
                continue
            tip = table.get("dro_tip_z", UNKNOWN)
            if kind == "arc_table":
                rows = table.get("rows", [])
                printed = [row.get("dro_xy", UNKNOWN) for row in rows]
                tips, flags = [row.get("dro_tip_z", tip) for row in rows], []
            else:
                printed, flags = table.get("dro_xy") or [], table.get("overshoot") or []
                tips = [tip] * len(table.get("setup_xy", []))
            rows = [
                (
                    row_id(subject, kind, table, i),
                    printed[i] if i < len(printed) else UNKNOWN,
                    z,
                    i < len(flags) and flags[i] is True,
                )
                for i, z in enumerate(tips)
            ]
            result.append(
                {
                    "name": _table_name(subject, kind, table),
                    "kind": kind,
                    "rows": rows,
                    "bounded": table.get("kernel_clip") is True,
                    "cutter_side": table.get("cutter_side", UNKNOWN),
                    "directed": table.get("cut_order") in _CUT_SENSE,
                }
            )
    return result


def _clip_facts(bundle, subject):
    """(op ``subject``'s kernel ``checkpoint_clips``, or None, and why its clip is unknown).

    Only the kernel finds where a bounded op's cutter first meets stock outside its
    stock_removal_bounds; without its result the printed path is never cuttable."""
    kernel = getattr(bundle, "kernel", None)
    if not isinstance(kernel, dict):
        return None, "no kernel result has clipped it"
    if kernel.get("status") != "ok":
        return None, f"the kernel is unavailable ({kernel.get('reason', UNKNOWN)})"
    clips = mapping(mapping(mapping(kernel.get("ops")).get(subject)).get("checkpoint_clips"))
    if not clips:
        return None, "the kernel reports no clip of it"
    if clips.get("reason"):
        return None, f"its kernel clip is unknown ({clips['reason']})"
    return clips, None


_LINE_COLUMNS = ("model_xy", "setup_xy", "dro_xy", "overshoot")
# A stepped join's columns: the point ones plus the axis each point is jogged on.
_STEPPED_COLUMNS = (*_LINE_COLUMNS, "jog")


def _line_rows(line):
    """A join line's point columns as one row per point."""
    return [
        {key: line[key][i] for key in _STEPPED_COLUMNS if i < len(line.get(key) or [])}
        for i in range(len(line["setup_xy"]))
    ]


def _between(a, b, t):
    if isinstance(a, list):
        return [_between(u, v, t) for u, v in zip(a, b, strict=True)]
    return a + t * (b - a) if number(a) and number(b) else UNKNOWN


def _clip_row(rows, point, marker):
    """A kernel piece point as a printed row, or None when it names no printed row: row
    ``row`` itself, or the clip point a fraction ``t`` along the printed chord after row
    ``after`` at its exact setup XY ``exact_xy``, printed at its safe-side ``dro_xy``."""
    point = mapping(point)
    clipped = "after" in point
    index = point.get("after" if clipped else "row")
    if not isinstance(index, int) or not 0 <= index < len(rows) - clipped:
        return None
    if not clipped:
        return rows[index]
    a, b, t = rows[index], rows[index + 1], point.get("t")
    exact, printed = point.get("exact_xy"), point.get("dro_xy")
    if not (number(t) and _pair(exact) and _pair(printed)):
        return None
    row = dict(a)
    row.pop("corner", None)
    for key in ("angle_deg", "model_xy"):
        if key in a:
            row[key] = _between(a[key], b[key], t)
    row.update(setup_xy=exact, dro_xy=printed, clipped_at=marker)
    if "jog" in b:  # the clip point lies on the leg that reaches b
        row["jog"] = b["jog"]
    if "overshoot" in a:
        row["overshoot"] = False
    if "x" in a:
        row.update(x=exact[0], y=exact[1])
    return row


def _pair(value):
    return isinstance(value, list) and len(value) == 2 and all(number(v) for v in value)


def _kernel_clip(subject, arcs, lines, clips):
    """(arc pieces, line pieces, debt or None): one stage's printed tables as the kernel
    clipped them (``clips``: the op's ``checkpoint_clips``) at the cutter's first contact
    with stock outside the op's stock_removal_bounds.

    Each piece keeps the printed rows the kernel names and adds its clip points, marked
    ``clipped_at``. A table cut into pieces lists each as ``fragment`` [k, n]; tables
    sharing a kept end are one path. A path left in more than one piece is debt: no
    credited cut links the pieces and none is reconnected. Facts that do not match the
    printed tables, or no piece at all, leave the stage unprinted with a reason.
    """
    paths = {
        entry.get("table"): entry for entry in clips.get("paths", []) if isinstance(entry, dict)
    }
    marker = clips.get("clipped_at", UNKNOWN)
    result = {"arc_table": [], "line_table": []}
    count, ends = 0, []
    tables = [("arc_table", arc) for arc in arcs] + [("line_table", line) for line in lines]
    for kind, table in tables:
        arc = kind == "arc_table"
        rows = table["rows"] if arc else _line_rows(table)
        entry = mapping(paths.get(row_id(subject, kind, table, 0)))
        pieces = entry.get("pieces")
        if entry.get("rows") != len(rows) or not isinstance(pieces, list):
            return [], [], "the kernel's clip does not match its printed table"
        built = [[_clip_row(rows, point, marker) for point in piece] for piece in pieces]
        if any(row is None for piece in built for row in piece):
            return [], [], "the kernel's clip does not match its printed table"
        kept = [mapping(point).get("row") for piece in pieces for point in piece]
        if len(built) == 1 and kept == list(range(len(rows))):
            built = None
        count += 1 if built is None else len(built)
        end = len(rows) - 1
        first = built is None or bool(pieces) and mapping(pieces[0][0]).get("row") == 0
        last = built is None or bool(pieces) and mapping(pieces[-1][-1]).get("row") == end
        ends.append((first, rows[0]["setup_xy"], last, rows[-1]["setup_xy"]))
        if built is None:
            result[kind].append(table)
            continue
        dropped = len(rows) - len({row for row in kept if row is not None})
        for k, piece in enumerate(built, start=1):
            if arc:
                clipped = {**table, "rows": piece, "dropped_rows": dropped}
            else:
                columns = {
                    key: [row.get(key) for row in piece] for key in _STEPPED_COLUMNS if key in table
                }
                clipped = {**table, **columns}
                clipped["overshoot"] = [flag is True for flag in clipped["overshoot"]]
                clipped["clipped_at"] = [row.get("clipped_at") for row in piece]
                clipped["dropped_points"] = dropped
                if not any(clipped["overshoot"]):
                    clipped.pop("overshoot_note", None)
            if len(built) > 1:
                clipped["fragment"] = [k, len(built)]
            result[kind].append(clipped)
    for a, b in itertools.combinations(ends, 2):
        for x, y in ((0, 0), (0, 2), (2, 0), (2, 2)):
            if a[x] and b[y] and _joined(a[x + 1], b[y + 1]):
                count -= 1
    if not result["arc_table"] and not result["line_table"]:
        return (
            [],
            [],
            (
                "no part of its cutter-centre path is clear of stock outside its "
                "stock_removal_bounds"
            ),
        )
    debt = None
    if count > 1:
        debt = (
            f"its first contact with stock outside its stock_removal_bounds splits its "
            f"cutter-centre path into {count} pieces; no credited cut links them"
        )
    return result["arc_table"], result["line_table"], debt


def _joined(a, b):
    return _pair(a) and _pair(b) and math.dist(a, b) <= _JOIN_TOL


def _sequence(tables):
    """Number one op stage's ``tables`` (each in its cutting order) ``sequence`` 0, 1, ...
    as the cutter runs them: a table follows the one whose last point is its first; chains
    keep their listed order. None is numbered while any cutting order is unestablished."""
    if any(table.get("cut_order") not in _CUT_SENSE for table in tables):
        return
    ends = [
        [row["setup_xy"] for row in table["rows"]] if "rows" in table else table["setup_xy"]
        for table in tables
    ]
    after = {}
    for i, a in enumerate(ends):
        for j, b in enumerate(ends):
            if i != j and j not in after.values() and _joined(a[-1], b[0]):
                after[i] = j
                break
    order = []
    for start in [i for i in range(len(tables)) if i not in after.values()] + list(
        range(len(tables))
    ):
        while start is not None and start not in order:
            order.append(start)
            start = after.get(start)
    for position, index in enumerate(order):
        tables[index]["sequence"] = position


def _z_residuals(bundle, setup, grid, features):
    """Each finish op whose DRO depth misses its finished face by more than its feature's
    narrowest numeric tolerance band: a final forming cut (``_cuts``) whose ``to_z`` ends
    on that face (no ``exit_mm`` run-out past it) stops :func:`dro_z` above it."""
    errors = []
    for op in setup["ops"]:
        to_z = op.get("to_z")
        if "exit_mm" in op or not number(to_z):
            continue
        if not any(cut[2] is op for cut in _cuts(bundle, op.get("feature"))):
            continue
        feature = mapping(features.get(op.get("feature")))
        bands = [
            feature[name][1] - feature[name][0]
            for name in tolerance_requirements(feature)
            if isinstance(feature.get(name), list)
            and len(feature[name]) == 2
            and all(number(v) for v in feature[name])
        ]
        residual = dro_z(to_z, grid) - to_z
        if bands and residual > min(bands) + _WALL_TOL:
            errors.append(
                f"op {op['op']} prints Z {dro_z(to_z, grid):.{grid[1]}f} for to_z {to_z:g}: "
                f"{residual:.{grid[1] + 1}g} above its finished face, more than the "
                f"{min(bands):g} tolerance band of {op.get('feature')}"
            )
    return errors


def _diagonal(points):
    """Whether any consecutive setup points differ on both axes: a move no single axis cuts."""
    return any(
        _pair(a) and _pair(b) and abs(a[0] - b[0]) > _JOIN_TOL and abs(a[1] - b[1]) > _JOIN_TOL
        for a, b in itertools.pairwise(points)
    )


def _moves(arcs, lines, capability, incapable, name, finish, decimals):
    """(why one stage's arc moves are unproven, its stair error, whether its tables are
    withheld), stamping each table's ``contouring`` and each arc's ``interpolation``.

    An arc needs the machine's declared contouring (:func:`contouring`): ``mdi`` types
    each row's move; ``jog`` steps one axis at a time (:func:`_jog`) and a finish stage
    holds the stair's cusp to the feature's band. A rough stage's cusp is recorded, not
    held: the finish pass removes it. Rows that cannot be stepped, or whose stair leaves
    more than the band, are withheld."""
    if not arcs:
        return None, None, False
    for table in (*arcs, *lines):
        table["contouring"] = capability or UNKNOWN
    for arc in arcs:
        arc["interpolation"] = (
            f"checkpoints only: the machine's contouring is {incapable}"
            if capability is None
            else "one handwheel axis per row"
            if capability == "jog"
            else "continuous circle: one G2/G3 MDI move per row"
            if arc["full_circle"]
            else "one G2/G3 MDI move per row"
        )
    if capability is None:
        return f"needs arc moves and the machine's contouring is {incapable}", None, False
    if capability == "mdi":
        return None, None, False
    debt = next((t["stair_reason"] for t in (*arcs, *lines) if "stair_reason" in t), None)
    if debt:
        return f"cannot be stepped in single-axis moves: {debt}", None, True
    cusp = max(table["stair_cusp_mm"] for table in (*arcs, *lines))
    band = arcs[0].get("stair_band_mm", UNKNOWN)
    if not finish:
        return None, None, False
    if not number(band):
        return (
            f"leaves a {cusp:.{decimals}f} single-axis stair and {name} has no tolerance "
            "band to hold it to",
            None,
            False,
        )
    if cusp > band + _WALL_TOL:
        return (
            None,
            f"single-axis steps leave {cusp:.{decimals}f} on {name}, more than its "
            f"{band:g} band",
            True,
        )
    return None, None, False


def _mdi(arcs, lines):
    """Stamp each printed row with the MDI move that reaches it (``mdi``): G1 to a table's
    first row, to and from a clip point and along a join; between arc rows G2 (clockwise)
    or G3 (counterclockwise) with I, J from the previous printed row to the arc centre."""
    for arc in arcs:
        centre, rows = arc["centre_setup_xy"], arc["rows"]
        known = _pair(centre) and all(_pair(row["dro_xy"]) for row in rows)
        turn = (
            sum(
                (a["dro_xy"][0] - centre[0]) * (b["dro_xy"][1] - centre[1])
                - (a["dro_xy"][1] - centre[1]) * (b["dro_xy"][0] - centre[0])
                for a, b in itertools.pairwise(rows)
            )
            if known
            else UNKNOWN
        )
        for k, row in enumerate(rows):
            if k == 0 or "clipped_at" in row or "clipped_at" in rows[k - 1]:
                row["mdi"] = {"g": "G1"}
            elif not known:
                row["mdi"] = {"g": UNKNOWN, "i": UNKNOWN, "j": UNKNOWN}
            else:
                start = rows[k - 1]["dro_xy"]
                row["mdi"] = {
                    "g": "G3" if turn > 0 else "G2",
                    "i": centre[0] - start[0],
                    "j": centre[1] - start[1],
                }
    for line in lines:
        line["mdi"] = [{"g": "G1"} for _ in line["setup_xy"]]


def _outline_moves(profile, capability, incapable):
    """Why a closed outline's diagonal edges are unproven, or None, stamping its
    ``contouring`` and, on an ``mdi`` machine, each vertex's G1 move (``mdi``). Single-axis
    stairs along an outline are not computed: no outline band holds their cusp."""
    profile["contouring"] = capability or UNKNOWN
    if capability == "mdi":
        profile["mdi"] = [{"g": "G1"} for _ in profile["cutter_centre"]]
        return None
    if capability is None:
        return f"needs diagonal moves and the machine's contouring is {incapable}"
    return "needs diagonal moves and single-axis stairs along an outline are not computed"


def evaluate(bundle, *, pre_kernel=False):
    """Coordinates findings, one per setup.

    A bounded op's (``stock_removal_bounds``) printed path is clipped only by the kernel,
    at the cutter's first contact with stock outside that box (:func:`_kernel_clip`). The
    kernel request (``pre_kernel``, :func:`prechips.kernel.build_job`) carries its whole
    printed tables marked ``kernel_clip``; the rule pass prints the kernel's clip of them,
    and without one leaves them unprinted and unknown, never cuttable unclipped.
    """
    result = []
    features = bundle.feature_definitions
    # Feature source frames are manifest-only; setups resolve exported or plan-owned frames.
    frames = mapping(bundle.features.get("frames"))
    dro = mapping(bundle.plan.get("dro"))
    units = bundle.features.get("units")
    for setup in bundle.plan["setups"]:
        bench = manual_bench(bundle, setup)
        if bench is not None:
            result.append(
                not_applicable(
                    "coordinates", setup, bench, "coordinates", "DRO target or cutter-centre table"
                )
            )
            continue
        frame = setup_frame(bundle, setup)
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        lathe = machine.get("kind") == "lathe"
        unordered = set()  # why a contour table's cutting order is unknown
        clip_debts = []  # why a clipped contour path is split, empty or unclipped
        capability, incapable = contouring(machine)
        unproven = []  # why a contour's arc or diagonal moves are not proven cuttable
        stairs = []  # single-axis stairs that leave more than their band on the wall
        numbers = {
            "frame": setup.get("frame", UNKNOWN),
            "binding": frame.get("binding", "nominal"),
            "rows": [],
            "profiles": [],
            "arc_table": [],
            "line_table": [],
            "contours": [],
            "entry_surfaces": [],
        }
        numbers["operations"] = [
            {
                key: value
                for key, value in op.items()
                if key
                in {
                    "op",
                    "do",
                    "feature",
                    "tool",
                    "direction",
                    "to_z",
                    "z_from",
                    "z_to",
                    "rough_allowance_mm",
                    "stock_to_leave_mm",
                }
            }
            for op in setup["ops"]
        ]
        grid = dro_grid(bundle, setup)
        numbers["dro_grid"] = {"step": grid[0], "decimals": grid[1]}
        declared = mapping(mapping(setup.get("stock_state")).get("entry_z"))
        states = stock_states(setup, features)
        for entry, (op, before, _) in zip(numbers["operations"], states, strict=True):
            if "to_z" in entry:
                # The depth the DRO shows: rounded up, never deeper than authored.
                entry["dro_to_z"] = dro_z(entry["to_z"], grid)
            levels = None if lathe else _z_levels(op, before, declared, grid, units)
            if levels is not None:
                entry["z_levels"] = levels
        residuals = _z_residuals(bundle, setup, grid, features)
        unknown = not frame or frame.get("binding") == UNKNOWN
        if lathe:
            numbers["x_display"] = (
                "radius"
                if dro.get("radius_mode") is True
                else "diameter"
                if dro.get("radius_mode") is False
                else UNKNOWN
            )
            unknown |= dro.get("controller", UNKNOWN) == UNKNOWN or any(
                not number(length_mm(resolve(bundle, "tools", op.get("tool")) or {}, "nose_radius"))
                for op in setup["ops"]
                if "tool" in op
            )
        names = list(_op_names(setup))
        located_names = set(_located_names(setup, features))
        revolved_names = set(revolved_located(setup, features))
        axis_cites, locator_cites = [], []
        for name in names:
            feature = mapping(features.get(name))
            locator, locator_frame, locator_name = located_by(features, name, feature)
            at = locator.get("at")
            located = name in located_names
            vector = isinstance(at, list) and len(at) == 3
            placed = vector and all(number(value) for value in at)
            why = None
            if located and not placed and (lathe or name in revolved_names):
                # A feature the kernel measured revolved about setup Z through X0 Y0 is
                # located on that axis (a lathe's spindle); off-axis or unmeasured ones still
                # need ``at``. Off a lathe an explicit ``at`` (even unknown) or a parent wins.
                rows, cite, why = _axis_rows(bundle, setup, name, feature, frame, dro, lathe)
                if rows:
                    numbers["rows"].extend(rows)
                    axis_cites.append(cite)
                    located = vector = False
            unknown |= located and not placed
            if located or vector:
                model = model_point(at, frames.get(locator_frame))
                local = frame_point(model, frame)
                row = {"feature": name, "model": model, "setup": local}
                if locator_name != name:
                    row["located_by"] = locator_name
                    locator_cites.extend(
                        [
                            f"features.features.{locator_name}.at",
                            *_citations(locator.get("cite"), "at"),
                        ]
                    )
                if why is not None and not lathe:
                    # Lathe rows keep their established shape; elsewhere name the debt.
                    row["reason"] = why
                numbers["rows"].append(row)
                unknown |= UNKNOWN in local
            if lathe:
                numbers["rows"].extend(
                    _lathe_rows(name, feature, setup, frame, frames, dro.get("radius_mode") is True)
                )
        for op, before, after in stock_states(setup, features):
            numbers["entry_surfaces"].append({"op": op["op"], **after["entry_z"]})
            contour = mapping(op.get("contour"))
            unknown |= op.get("contour") == UNKNOWN
            if not contour:
                continue
            name = op.get("feature")
            feature = mapping(features.get(name))
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            diameter = length_mm(tool, "dia")
            radius = diameter / 2 if number(diameter) else UNKNOWN
            rough = op.get("do", "").startswith("rough")
            paired = not rough and "rough_allowance_mm" in op
            stages = (
                [("rough", op.get("rough_allowance_mm", op.get("stock_to_leave_mm", UNKNOWN)))]
                if rough
                else [("rough", op["rough_allowance_mm"]), ("finish", 0)]
                if paired
                else [("finish", 0)]
            )
            sense, order = cut_order(machine, op)
            bounded = "stock_removal_bounds" in op
            subject = f"{setup['id']}:{op['op']}"
            for stage, allowance in stages:
                offset = radius + allowance if number(radius) and number(allowance) else UNKNOWN
                profile = {
                    "feature": name,
                    "op": op["op"],
                    "stage": stage,
                    "tool": op.get("tool", UNKNOWN),
                    "tool_dia": diameter,
                    "tool_nominal_dia_mm": diameter,
                    "cutter_radius_mm": radius,
                    "offset_mm": offset,
                    "rough_allowance_mm": allowance if stage == "rough" else "not_applicable",
                    "entry_z": before["entry_z"].get(name, before["top_z"]),
                    "to_z": op.get("to_z", UNKNOWN),
                    "dro_to_z": dro_z(op.get("to_z", UNKNOWN), grid),
                    "contour": contour,
                    "tool_dia_basis": "selected member nominal, not measured",
                }
                generated = refused = False
                if contour.get("method") == "arc_table":
                    arcs, lines = _arc(
                        name,
                        feature,
                        op,
                        offset,
                        frame,
                        frames,
                        features,
                        sense,
                        order,
                        grid,
                        capability,
                        radius,
                    )
                    for table in (*arcs, *lines):
                        table.update(stage=stage, allowance_mm=allowance, offset_mm=offset)
                    label = f"op {op['op']} {stage}"
                    why, stair, refused = _moves(
                        arcs, lines, capability, incapable, name, stage == "finish", grid[1]
                    )
                    if why:
                        unproven.append(f"{label} {why}")
                    if stair:
                        stairs.append(f"{label}: {stair}")
                    if refused:
                        profile["stair_reason"] = stair or why
                        arcs, lines = [], []
                    debt = None
                    if bounded and (arcs or lines) and pre_kernel:
                        for table in (*arcs, *lines):
                            table["kernel_clip"] = True
                    elif bounded and (arcs or lines):
                        clips, why = _clip_facts(bundle, subject)
                        if clips is None:
                            arcs, lines = [], []
                            debt = f"its bounds clip is unknown: {why}"
                        else:
                            arcs, lines, debt = _kernel_clip(subject, arcs, lines, clips)
                    if debt:
                        profile["clip_reason"] = debt
                        clip_debts.append(f"op {op['op']} {stage}: {debt}")
                    if arcs or lines:
                        _sequence([*arcs, *lines])
                        if capability == "mdi":
                            _mdi(arcs, lines)
                        numbers["arc_table"].extend(arcs)
                        numbers["line_table"].extend(lines)
                        # Clip pieces stay separate lists: nothing reconnects them.
                        profile["cutter_centre"] = (
                            arcs[0]["rows"] if len(arcs) == 1 else [arc["rows"] for arc in arcs]
                        )
                        unordered.update(
                            item["cut_order_reason"]
                            for item in (*arcs, *lines)
                            if item["cut_order"] == UNKNOWN
                        )
                        generated = True
                elif contour.get("method") == "linear_table" and op.get("do") in RASTER_OPS:
                    approach = op.get("approach_mm", UNKNOWN)
                    scale = {"mm": 1.0, "in": 25.4}.get(units)
                    lift = (
                        dro_z(before["top_z"] + approach / scale, grid)
                        if scale and number(approach) and number(before["top_z"])
                        else UNKNOWN
                    )
                    raster, why = _raster(
                        feature, op, offset, radius, frame, frames, sense, order, lift
                    )
                    if raster is None:
                        profile["raster_reason"] = why
                    else:
                        profile.update(raster)
                        if profile["cut_order"] == UNKNOWN:
                            unordered.add(profile["cut_order_reason"])
                        generated = True
                elif contour.get("method") == "linear_table":
                    path = _linear(feature, op, offset, radius, frame, frames)
                    if path:
                        profile["cutter_centre"] = path
                        if not isinstance(path[0][0], list):
                            # A closed outline runs counterclockwise with the cutter outside
                            # its walls, so (n x t)·Z > 0; rasters are independent passes.
                            reverse = None if sense is None else sense < 0
                            _ordered(profile, reverse, order, ("cutter_centre",))
                            if profile["cut_order"] == UNKNOWN:
                                unordered.add(profile["cut_order_reason"])
                            if _diagonal(path):
                                why = _outline_moves(profile, capability, incapable)
                                if why:
                                    unproven.append(f"op {op['op']} {stage} {why}")
                        generated = True
                elif contour.get("method") == "axial_table" and (not paired or stage == "finish"):
                    nose = length_mm(tool, "nose_radius") if tool and not uncertain(tool) else None
                    dome = _dome(
                        name,
                        feature,
                        op,
                        dro.get("radius_mode") is True,
                        nose if number(nose) else UNKNOWN,
                        _edge_facts(bundle, op) if tool and not uncertain(tool) else None,
                    )
                    if dome:
                        numbers["contours"].append(dome)
                        generated = True
                        unknown |= not number(dome["tool_nose_compensation_mm"])
                if not generated:
                    profile["cutter_centre"] = UNKNOWN
                numbers["profiles"].append(profile)
                unknown |= (not generated and not refused) or not tool or uncertain(tool)
            if lathe:
                unknown |= not number(length_mm(tool, "nose_radius"))
        status = (
            "error"
            if residuals or stairs
            else "unknown"
            if unknown or unordered or clip_debts or unproven
            else "pass"
        )
        sentence = (
            "Feature targets use the declared model-to-setup basis; cutter tables use explicit "
            "nominal geometry and authored allowance."
        )
        if unknown:
            sentence += (
                " Missing geometry or unverified tool/frame binding prevents a cleared toolpath."
            )
        if unordered:
            sentence += " Cutting order is unknown: " + "; ".join(sorted(unordered)) + "."
        if clip_debts:
            sentence += " Stock-removal clip debt: " + "; ".join(clip_debts) + "."
        if residuals:
            numbers["dro_z_residual_errors"] = residuals
            sentence += " DRO depth rounding error: " + "; ".join(residuals) + "."
        if unproven:
            sentence += " Moves between rows are unproven: " + "; ".join(unproven) + "."
        if stairs:
            numbers["stair_errors"] = stairs
            sentence += " Single-axis stair error: " + "; ".join(stairs) + "."
        contoured = any(
            "contouring" in table
            for table in (*numbers["arc_table"], *numbers["line_table"], *numbers["profiles"])
        )
        result.append(
            Finding(
                "coordinates",
                setup["id"],
                status,
                numbers,
                [
                    "PLAN.md §4.1 coordinates",
                    "features declared frames and nominal geometry",
                    "plan contour steps, operation targets and stock allowances",
                    "inventory selected cutter nominal diameter",
                    *plan_frame_cite(bundle, setup),
                    *dict.fromkeys(locator_cites),
                    *axis_cites,
                    *(
                        ["inventory machine contouring (mdi or jog)"]
                        if contoured or unproven or stairs
                        else []
                    ),
                ],
                sentence,
            )
        )
    return result
