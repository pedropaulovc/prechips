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
from ._bench import manual_bench, not_applicable
from .resolution import (
    UNKNOWN,
    _citations,
    length_mm,
    number,
    plan_frame_cite,
    resolve,
    setup_frame,
    uncertain,
)
from .tip_endpoints import HOLE_OPS, stock_states

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


def _located_names(setup, features):
    """This setup's located features (a located kind or a centre-op target), in op order."""
    centre = {op.get("feature") for op in setup["ops"] if op.get("do") in CENTRE_OPS}
    return [
        name
        for name in dict.fromkeys(op.get("feature") for op in setup["ops"])
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


# Plan units within which a cutter centre on an inset bound still counts as inside it.
_CLIP_TOL = 1e-9
# Plan units within which two table ends are one join of the same cutter path.
_JOIN_TOL = 1e-6
# Decimals the DRO shows per feature unit: the sheet prints, and the kernel checks, these.
DRO_DECIMALS = {"mm": 2, "in": 4}
# The operator note on a printed corner miter the kernel proves clear (rule A′).
OVERSHOOT_NOTE = "corner overshoot into scrap — OK"


def _grid(value, decimals, up):
    """``value`` on the DRO grid of ``decimals``, rounded up (True) or down (False)."""
    scale = 10**decimals
    steps = math.ceil(value * scale - 1e-6) if up else math.floor(value * scale + 1e-6)
    return round(steps / scale, decimals)


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


def _dro_xy(xy, decimals, walls, box, offset):
    """``xy`` as the DRO prints it, on the safe side: the nearest grid point no nearer any
    wall (``walls``: point -> distance) than ``xy`` or than the authored cutter-centre
    ``offset``, whichever is less, and inside ``box`` (the DRO-rounded clip box) when
    given; a corner of its grid cell, else up to two steps out, else unknown."""
    if not walls or not all(number(v) for v in xy):
        return [UNKNOWN, UNKNOWN]
    step = 10.0**-decimals
    base = [_grid(v, decimals, False) for v in xy]
    floors = [min(wall(xy), offset) - _CLIP_TOL for wall in walls]
    for reach in (1, 3):
        span = range(1 - reach, reach + 1)
        options = [
            [round(base[0] + i * step, decimals), round(base[1] + j * step, decimals)]
            for i in span
            for j in span
        ]
        for point in sorted(options, key=lambda p: math.dist(p, xy)):
            inside = box is None or _inside(point, box)
            if inside and all(wall(point) >= low for wall, low in zip(walls, floors, strict=True)):
                return point
    return [UNKNOWN, UNKNOWN]


def _printed(arcs, lines, decimals, walls, box, offset):
    """Stamp every row and join point with the value the DRO prints: ``dro_xy``
    (:func:`_dro_xy`) and ``dro_tip_z``, the tip rounded up so it is never deeper than
    authored. The sheet prints these; the kernel checks them and credits their sweep. Points
    within _JOIN_TOL of each other (a table end and the join it meets) print one value."""
    done = []

    def tip(value):
        return _grid(value, decimals, True) if number(value) else UNKNOWN

    def dro(xy):
        if all(number(v) for v in xy):
            for point, value in done:
                if math.dist(point, xy) <= _JOIN_TOL:
                    return value
        value = _dro_xy(xy, decimals, walls, box, offset)
        done.append((xy, value))
        return value

    for arc in arcs:
        arc["dro_tip_z"] = tip(arc.get("tip_z"))
        for row in arc["rows"]:
            row["dro_xy"] = dro(row["setup_xy"])
            row["dro_tip_z"] = tip(row.get("tip_z"))
    for line in lines:
        line["dro_tip_z"] = tip(line.get("tip_z"))
        line["dro_xy"] = [dro(xy) for xy in line["setup_xy"]]


def _centre_box(op, radius, units):
    """(the cutter-centre box an op's stock_removal_bounds authorise, or None, and why not).

    The bounds are the op's setup-frame clearing box (plan units, docs/plan.md); the stock
    model credits removal only inside it, so a cutter of ``radius`` mm stays in that removal
    only while its centre stays r inside each XY bound. Each axis is ``(lo + r, hi - r, lo
    marker, hi marker)``, both rounded inward to the DRO grid (:data:`DRO_DECIMALS`) so a
    printed point on a bound stays inside it; an op without bounds gives (None, None).
    """
    if "stock_removal_bounds" not in op:
        return None, None
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        return None, f"feature units {units!r} are not mm or in, so its bounds cannot clip"
    if not (number(radius) and radius > 0):
        return None, "the cutter radius is unknown, so its stock_removal_bounds cannot clip"
    bounds, r, box = mapping(op["stock_removal_bounds"]), radius / scale, []
    decimals = DRO_DECIMALS[units]
    for axis in ("x", "y"):
        span = bounds.get(axis)
        if not (
            isinstance(span, list)
            and len(span) == 2
            and all(number(v) for v in span)
            and span[0] < span[1]
        ):
            return None, f"stock_removal_bounds {axis} is not a numeric [lo, hi] span"
        lo, hi = (float(v) for v in span)
        box.append(
            (
                _grid(lo + r, decimals, True),
                _grid(hi - r, decimals, False),
                f"stock_removal_bounds {axis} {lo} + r",
                f"stock_removal_bounds {axis} {hi} − r",
            )
        )
    return tuple(box), None


def _inside(xy, box):
    return all(lo - _CLIP_TOL <= xy[i] <= hi + _CLIP_TOL for i, (lo, hi, _, _) in enumerate(box))


def _length(points):
    return sum(math.dist(a, b) for a, b in itertools.pairwise(points))


def _arc_crossings(a, b, ellipse, box):
    """(angle, marker) where the arc between row angles ``a`` and ``b`` meets an inset
    bound strictly between them, in travel order. ``ellipse`` is (p0, c, s): the setup
    frame is affine, so the cutter centre at angle t is p0 + cos(t) c + sin(t) s."""
    p0, c, s = ellipse
    low, high = sorted((a, b))
    found = []
    for axis, bound in enumerate(box):
        amplitude = math.hypot(c[axis], s[axis])
        phase = math.degrees(math.atan2(s[axis], c[axis]))
        for value, marker in ((bound[0], bound[2]), (bound[1], bound[3])):
            if amplitude == 0 or abs(value - p0[axis]) > amplitude:
                continue
            half = math.degrees(math.acos((value - p0[axis]) / amplitude))
            for angle in {phase + half, phase - half}:
                angle += 360.0 * math.ceil((low - angle) / 360.0)
                while angle < high:
                    if angle > low:
                        found.append((angle, marker))
                    angle += 360.0
    found.sort(reverse=b < a)
    return found


def _clip_rows(rows, box, row_at):
    """Pieces of an arc's rows (cutting order) inside ``box``. Each crossing is an exact
    row on the arc marked ``clipped_at`` with the bound it meets; rows past it are dropped.
    Between checkpoints the inside test follows the arc itself, not its chords."""
    p = [row_at(angle)["setup_xy"] for angle in (0.0, 90.0, 180.0)]
    p0 = [(p[0][i] + p[2][i]) / 2 for i in range(2)]
    ellipse = (p0, [(p[0][i] - p[2][i]) / 2 for i in range(2)], [p[1][i] - p0[i] for i in range(2)])
    pieces, current = [], None
    for index, row in enumerate(rows):
        if index == 0:
            current = [row] if _inside(row["setup_xy"], box) else None
            continue
        a, b = rows[index - 1]["angle_deg"], row["angle_deg"]
        stops = [(a, None), *_arc_crossings(a, b, ellipse, box), (b, None)]
        for (start, marker), (stop, _) in itertools.pairwise(stops):
            inside = _inside(row_at((start + stop) / 2)["setup_xy"], box)
            if inside and current is None:
                current = [{**row_at(start), "clipped_at": marker} if marker else rows[index - 1]]
            elif not inside and current is not None:
                if marker:
                    current.append({**row_at(start), "clipped_at": marker})
                pieces.append(current)
                current = None
        if current is not None:
            current.append(row)
    if current is not None:
        pieces.append(current)
    return [piece for piece in pieces if _length([r["setup_xy"] for r in piece]) > _CLIP_TOL]


def _segment_span(a, b, box):
    """(t in, t out, marker in, marker out) of segment a->b inside ``box``, or None."""
    enter, leave, entered, left = 0.0, 1.0, None, None
    for axis, (lo, hi, lo_marker, hi_marker) in enumerate(box):
        delta = b[axis] - a[axis]
        if delta == 0:
            if not lo - _CLIP_TOL <= a[axis] <= hi + _CLIP_TOL:
                return None
            continue
        near, far = ((lo, lo_marker), (hi, hi_marker))[:: 1 if delta > 0 else -1]
        if (t := (near[0] - a[axis]) / delta) > enter:
            enter, entered = t, near[1]
        if (t := (far[0] - a[axis]) / delta) < leave:
            leave, left = t, far[1]
    if _inside(a, box):
        enter, entered = 0.0, None
    if _inside(b, box):
        leave, left = 1.0, None
    return None if enter > leave else (enter, leave, entered, left)


def _clip_points(model, setup, box):
    """Pieces of a join polyline inside ``box`` as (model point, setup point, marker)
    triples; a clip point carries the bound it meets, the original points None."""

    def at(index, t, marker):
        a, b = index - 1, index
        return (
            [model[a][i] + t * (model[b][i] - model[a][i]) for i in range(2)],
            [setup[a][i] + t * (setup[b][i] - setup[a][i]) for i in range(2)],
            marker,
        )

    pieces, current = [], None
    for index in range(1, len(setup)):
        span = _segment_span(setup[index - 1], setup[index], box)
        if span is None:
            if current is not None:
                pieces.append(current)
                current = None
            continue
        enter, leave, entered, left = span
        if current is None or entered is not None:
            if current is not None:
                pieces.append(current)
            start = (model[index - 1], setup[index - 1], None)
            current = [at(index, enter, entered) if entered else start]
        current.append(at(index, leave, left) if left else (model[index], setup[index], None))
        if left is not None:
            pieces.append(current)
            current = None
    if current is not None:
        pieces.append(current)
    return [piece for piece in pieces if _length([p[1] for p in piece]) > _CLIP_TOL]


def _authorised(arc, lines, box, row_at):
    """([arc pieces], [line pieces], debt or None): one stage clipped at ``box``.

    Each table keeps its cutting order; a crossing becomes an exact point marked
    ``clipped_at`` with the bound it meets and the points past it are dropped. Tables
    sharing an end are one path where the shared point is kept, and a closed table whose
    seam is kept runs on through it as one piece. A path left in more than one piece, or
    none, is debt: no credited cut links the pieces and none is reconnected; a table cut
    into pieces lists each as ``fragment`` [k, n].
    """
    points = [row["setup_xy"] for row in arc["rows"]]
    points += [point for line in lines for point in line["setup_xy"]]
    if not all(number(v) for point in points for v in point):
        return [arc], lines, "cutter-centre setup XY is unknown, so its bounds clip is unknown"

    def end(pieces, first):
        """The table's own end point if a piece keeps it unclipped, else None."""
        if not pieces:
            return None
        point = pieces[0][0] if first else pieces[-1][-1]
        return point if isinstance(point, dict) else point[1] if point[2] is None else None

    tables = []  # (record, pieces, original first point, original last point, kept points)
    rows = arc["rows"]
    candidates = [(arc, _clip_rows(rows, box, row_at), rows[0], rows[-1])]
    for line in lines:
        clipped = _clip_points(line["model_xy"], line["setup_xy"], box)
        candidates.append((line, clipped, line["setup_xy"][0], line["setup_xy"][-1]))
    for record, pieces, first, last in candidates:
        kept = sum(not _clipped(point) for piece in pieces for point in piece)
        seam = end(pieces, True) is first and end(pieces, False) is last
        if len(pieces) > 1 and seam and math.dist(_xy(first), _xy(last)) <= _JOIN_TOL:
            pieces = [pieces[-1] + pieces[0][1:], *pieces[1:-1]]
        tables.append((record, pieces, first, last, kept))
    count, ends = 0, []
    for _, pieces, first, last, _ in tables:
        count += len(pieces)
        ends.append((end(pieces, True) is first, first, end(pieces, False) is last, last))
    for a, b in itertools.combinations(ends, 2):
        for x, y in ((0, 0), (0, 2), (2, 0), (2, 2)):
            if a[x] and b[y] and math.dist(_xy(a[x + 1]), _xy(b[y + 1])) <= _JOIN_TOL:
                count -= 1
    arcs, joins = [], []
    for index, (record, pieces, _, _, kept) in enumerate(tables):
        unchanged = len(pieces) == 1 and ends[index][0] and ends[index][2]
        unchanged = unchanged and all(not _clipped(point) for point in pieces[0])
        if unchanged:
            (arcs if index == 0 else joins).append(record)
            continue
        for k, piece in enumerate(pieces, 1):
            if index == 0:
                part = {**record, "rows": piece, "dropped_rows": len(rows) - kept}
            else:
                part = {
                    **record,
                    "model_xy": [point[0] for point in piece],
                    "setup_xy": [point[1] for point in piece],
                    "clipped_at": [point[2] for point in piece],
                    "dropped_points": len(record["setup_xy"]) - kept,
                }
            if len(pieces) > 1:
                part["fragment"] = [k, len(pieces)]
            (arcs if index == 0 else joins).append(part)
    if count <= 0:
        return [], [], "its cutter-centre path lies wholly outside its bounds inset by r"
    if count > 1:
        return (
            arcs,
            joins,
            (
                f"its bounds inset by r split its cutter-centre path into {count} pieces; "
                "no credited cut links them"
            ),
        )
    return arcs, joins, None


def _xy(point):
    return point["setup_xy"] if isinstance(point, dict) else point


def _clipped(point):
    return point.get("clipped_at") if isinstance(point, dict) else point[2]


def _arc(
    feature_name, feature, op, offset, frame, frames, features, sense, order, box=None, decimals=2
):
    """([arc table fragments], join lines, clip debt or None), in cutting order for
    ``sense`` (see cut_order).

    The cutter-side wall normal is radial: outward when the cutter centre runs outside the
    wall radius, inward on a concave wall. A join's normal is its offset land's normal.
    ``box`` (:func:`_centre_box`) clips the path at the op's stock_removal_bounds
    (:func:`_authorised`). Every row and join point carries the value the DRO prints at
    ``decimals``, never nearer the feature's walls (:func:`_printed`); each join's corner
    miter, the run-out past its land and taper walls, is flagged ``overshoot``.
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
        return [], [], None
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
                return [], [], None
            endpoint = joins[2] if joins else feature.get("bottom_end")
        else:
            cutter_radius = radius - offset
            linked = [f for f in features.values() if f.get("top_edge_feature") == feature_name]
            endpoints = [_top_join(feature, linked_feature, offset) for linked_feature in linked]
            if linked:
                if any(point is None for point in endpoints):
                    return [], [], None
                endpoint = endpoints[0]
                if any(math.dist(endpoint, point) > 1e-9 for point in endpoints[1:]):
                    return [], [], None
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
            return [], [], None
        half = math.degrees(math.atan2(endpoint[0] - centre[0], centre[1] - endpoint[1]))
        start, end = -half, half
    elif not full and feature.get("arc") != "upper_semicircle":
        return [], [], None
    if cutter_radius <= 0:
        return [], [], None
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

    rows = [row_at(angle) for angle in angles]
    model_centre = model_point(centre, frames.get(feature.get("frame", "model")))
    centre_xy = frame_point(model_centre, frame)[:2]
    reverse = None
    if len(rows) >= 2 and cutter_radius != radius and all(number(v) for v in centre_xy):
        a, b = rows[len(rows) // 2 - 1]["setup_xy"], rows[len(rows) // 2]["setup_xy"]
        outward = 1 if cutter_radius > radius else -1
        if all(number(v) for v in (*a, *b)):
            normal = [outward * ((a[i] + b[i]) / 2 - centre_xy[i]) for i in range(2)]
            reverse = _reversal(a, b, normal, sense)
    interpolation = (
        "continuous circle; checkpoints are not straight-chord cuts"
        if full
        else "straight chords at authored step, exact offset joins included"
    )
    arc = {
        "feature": feature_name,
        "op": op["op"],
        "method": "arc_table",
        "step_deg": step,
        "centre_model_xy": model_centre[:2],
        "centre_setup_xy": centre_xy,
        "cutter_centre_radius_mm": cutter_radius,
        "radius_mm": cutter_radius,
        "tip_z": op.get("to_z", UNKNOWN),
        "rows": rows,
        "interpolation": interpolation,
        "basis": (
            "nominal selected cutter size; measured geometry and frame binding "
            + "govern readiness"
        ),
    }
    _ordered(arc, reverse, order, ("rows",))
    if number(step):
        arc["max_chord_sagitta_mm"] = cutter_radius * (
            1 - math.cos(math.radians(min(step, abs(end - start)) / 2))
        )
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
    if not rows:
        return [], [], None
    arcs, debt = [arc], None
    if box is not None:
        arcs, lines, debt = _authorised(arc, lines, box, row_at)
    _printed(arcs, lines, decimals, walls if known else [], box, offset)
    for line in lines:
        line["overshoot"] = [any(p is m for m in miters) for p in line["model_xy"]]
        if any(line["overshoot"]):
            line["overshoot_note"] = OVERSHOOT_NOTE
    return arcs, lines, debt


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


def _linear(feature, op, offset, radius, frame, frames):
    contour = mapping(op.get("contour"))
    envelope = (
        {
            **feature,
            "bounds": contour["sweep_bounds"],
            "frame": contour.get("sweep_frame", feature.get("frame", "model")),
        }
        if isinstance(contour.get("sweep_bounds"), dict)
        else feature
    )
    boundary = _boundary(envelope, frame, frames)
    if not boundary or not all(number(v) for v in (offset, radius)):
        return None
    left, right = min(p[0] for p in boundary), max(p[0] for p in boundary)
    front, back = min(p[1] for p in boundary), max(p[1] for p in boundary)
    if op["do"] in {"pocket", "rough_pocket", "finish_pocket"}:
        side = contour.get("open_side")
        step = contour.get("step_mm", UNKNOWN)
        if side not in {"-x", "+x", "-y", "+y"} or not number(step) or step <= 0:
            return None
        along_x = side.endswith("x")
        low, high = (left, right) if along_x else (front, back)
        start, end = (
            (low - radius, high - offset) if side.startswith("-") else (high + radius, low + offset)
        )
        direction = 1 if end >= start else -1
        count = math.ceil(abs(end - start) / step)
        samples = [start + direction * i * step for i in range(count)] + [end]
        return (
            [[[v, front - radius], [v, back + radius]] for v in samples]
            if along_x
            else [[[left - radius, v], [right + radius, v]] for v in samples]
        )
    lines = [
        _offset_line(boundary[i], boundary[(i + 1) % len(boundary)], -offset)
        for i in range(len(boundary))
    ]
    if any(line is None for line in lines):
        return None
    vertices = [_line_join(*lines[i - 1], *lines[i]) for i in range(len(lines))]
    return vertices + [vertices[0]] if all(v is not None for v in vertices) else None


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


def row_id(subject, kind, table, index):
    """A printed row's id: ``S1:40 rough arc row 3`` (``arc_table``) or ``S1:40 rough line
    +X[0]`` (``line_table``); a piece of a clipped table adds ``fragment k``."""
    name = f"{subject} {table.get('stage')} " + (
        "arc" if kind == "arc_table" else f"line {table.get('side')}"
    )
    if "fragment" in table:
        name += f" fragment {table['fragment'][0]}"
    return f"{name} row {index}" if kind == "arc_table" else f"{name}[{index}]"


def checkpoints(subject, numbers, op):
    """Each printed cutter-centre table of op ``op``'s arc_table output, in cutting order,
    as its (row id (:func:`row_id`), printed setup XY ``dro_xy``, printed tip Z
    ``dro_tip_z``, corner overshoot?) checkpoints in plan units: what the DRO shows is
    what the kernel checks."""
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
            path = [
                (
                    row_id(subject, kind, table, i),
                    printed[i] if i < len(printed) else UNKNOWN,
                    z,
                    i < len(flags) and flags[i] is True,
                )
                for i, z in enumerate(tips)
            ]
            result.append(path)
    return result


def evaluate(bundle):
    result = []
    features = bundle.feature_definitions
    # Feature source frames are manifest-only; setups resolve exported or plan-owned frames.
    frames = mapping(bundle.features.get("frames"))
    dro = mapping(bundle.plan.get("dro"))
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
        names = list(dict.fromkeys(op.get("feature") for op in setup["ops"]))
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
            units = bundle.features.get("units")
            box, clip_why = _centre_box(op, radius, units)
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
                    # The depth the DRO shows: rounded up, never deeper than authored.
                    "dro_to_z": (
                        _grid(op["to_z"], DRO_DECIMALS.get(units, 2), True)
                        if number(op.get("to_z"))
                        else UNKNOWN
                    ),
                    "contour": contour,
                    "tool_dia_basis": "selected member nominal, not measured",
                }
                generated = False
                if contour.get("method") == "arc_table":
                    arcs, lines, debt = _arc(
                        name,
                        feature,
                        op,
                        offset,
                        frame,
                        frames,
                        features,
                        sense,
                        order,
                        box,
                        DRO_DECIMALS.get(units, 2),
                    )
                    debt = clip_why if arcs and clip_why else debt
                    if debt:
                        profile["clip_reason"] = debt
                        clip_debts.append(f"op {op['op']} {stage}: {debt}")
                    if arcs or lines:
                        for arc in arcs:
                            arc.update(stage=stage, allowance_mm=allowance, offset_mm=offset)
                        numbers["arc_table"].extend(arcs)
                        for line in lines:
                            line["stage"] = stage
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
                unknown |= not generated or not tool or uncertain(tool)
            if lathe:
                unknown |= not number(length_mm(tool, "nose_radius"))
        status = "unknown" if unknown or unordered or clip_debts else "pass"
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
                ],
                sentence,
            )
        )
    return result
