"""Nominal feature targets and finite cutter-centre tables (no kernel claims).

A model point is transformed by the dot product with each setup basis. Unknown
components propagate only through nonzero basis coefficients. Local authored Z
can substitute only an unknown model transform in an unbound frame, retaining
local_from operation provenance. No tolerance-band midpoint defines geometry.
"""

from __future__ import annotations

import itertools
import math

from ..findings import Finding
from .resolution import (
    UNKNOWN,
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


def _arc(feature_name, feature, op, offset, frame, frames, features, sense, order):
    """(arc table, join lines), each listed in cutting order for ``sense`` (see cut_order).

    The cutter-side wall normal is radial: outward when the cutter centre runs outside the
    wall radius, inward on a concave wall. A join's normal is its offset land's normal.
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
        return None, []
    cutter_radius = radius + offset
    start, end = 0.0, 360.0 if full else 180.0
    vertical_angle = False
    joins = None
    if "end" in feature or bottom:
        vertical_angle = True
        if bottom:
            top = mapping(features.get(feature.get("top_edge_feature")))
            joins = _joins(top, feature, offset)
            if joins is None:
                return None, []
            endpoint = joins[2] if joins else feature.get("bottom_end")
        else:
            cutter_radius = radius - offset
            linked = [f for f in features.values() if f.get("top_edge_feature") == feature_name]
            endpoints = [_top_join(feature, linked_feature, offset) for linked_feature in linked]
            if linked:
                if any(point is None for point in endpoints):
                    return None, []
                endpoint = endpoints[0]
                if any(math.dist(endpoint, point) > 1e-9 for point in endpoints[1:]):
                    return None, []
            else:
                endpoint = feature.get("end")
        if not isinstance(endpoint, list) or not all(number(v) for v in endpoint):
            return None, []
        half = math.degrees(math.atan2(endpoint[0] - centre[0], centre[1] - endpoint[1]))
        start, end = -half, half
    elif not full and feature.get("arc") != "upper_semicircle":
        return None, []
    if cutter_radius <= 0:
        return None, []
    step = mapping(op.get("contour")).get("step_deg", UNKNOWN)
    angles = _samples(start, end, step)
    rows = []
    for angle in angles:
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
        rows.append(
            {
                "angle_deg": angle,
                "model_xy": xy,
                "setup_xy": local[:2],
                "x": local[0],
                "y": local[1],
                "tip_z": op.get("to_z", UNKNOWN),
            }
        )
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
    lines = []
    if bottom and joins:
        sides = (-1, 1) if feature.get("mirror_symmetric") is True else (1,)
        # _joins validated both land ends; the land's unit left normal is its cutter side.
        top_end = mapping(features.get(feature.get("top_edge_feature")))["end"]
        shifted, _ = _offset_line(top_end, feature["radial_tip_end"], 1.0)
        left = [shifted[i] - top_end[i] for i in range(2)]

        def setup_xy(point):
            return frame_point(_xy_model(point, feature, frames), frame)[:2]

        for side in sides:
            xy = [[centre[0] + side * (p[0] - centre[0]), p[1]] for p in joins]
            local = [setup_xy(p) for p in xy]
            wall = setup_xy([xy[0][0] - side * left[0] * offset, xy[0][1] - left[1] * offset])
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
    return arc if rows else None, lines


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


def _spindle_rows(bundle, setup, name, feature, frame, dro):
    """(rows, citation) locating a lathe feature on the spindle axis at both ends of its
    kernel-measured axial span, or ([], None) when the kernel did not measure every face
    revolved about setup Z (``turned_profile.spindle_span``)."""
    from .turned_profile import spindle_span

    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    span, cite = spindle_span(bundle, setup, name)
    if span is None or scale is None:
        return [], None
    diameter = _nominal(feature, "dia")
    radius_mode = dro.get("radius_mode") is True
    rows = []
    for end, z in zip(("start", "end"), span, strict=True):
        local = [0.0, 0.0, z / scale]
        rows.append(
            {
                "feature": name,
                "point": f"spindle axis, kernel span {end}",
                "model": model_point(local, frame),
                "setup": local,
                "dia_nominal": diameter,
                "x_target_mm": diameter / 2 if radius_mode and number(diameter) else diameter,
            }
        )
    return rows, cite


def _dome(name, feature, op, radius_mode):
    sphere = feature.get("sphere_radius", UNKNOWN)
    apex, base = op.get("z_from", UNKNOWN), op.get("z_to", UNKNOWN)
    step = mapping(op.get("contour")).get("step_mm", UNKNOWN)
    if not all(number(v) for v in (sphere, apex, base, step)) or sphere <= 0 or step <= 0:
        return None
    sign = 1 if apex > base else -1
    centre = apex - sign * sphere
    rows = []
    count = math.ceil(abs(apex - base) / step)
    for i in range(count + 1):
        z = base if i == count else apex - sign * i * step
        squared = sphere * sphere - (z - centre) ** 2
        if squared < -1e-10:
            return None
        radius = math.sqrt(max(0, squared))
        rows.append(
            {
                "z_mm": z,
                "radius_mm": radius,
                "diameter_mm": 2 * radius,
                "x_target_mm": radius if radius_mode else 2 * radius,
                "setup_xz": [radius if radius_mode else 2 * radius, z],
            }
        )
    return {
        "feature": name,
        "op": op["op"],
        "method": "axial_table",
        "rows": rows,
        "sphere_radius_mm": sphere,
        "sphere_centre_z_mm": centre,
        "apex_z_mm": apex,
        "base_z_mm": base,
        "step_mm": step,
        "tool_nose_compensation_mm": UNKNOWN,
    }


def evaluate(bundle):
    result = []
    features = bundle.features["features"]
    # Feature source frames are manifest-only; setups resolve exported or plan-owned frames.
    frames = mapping(bundle.features.get("frames"))
    dro = mapping(bundle.plan.get("dro"))
    for setup in bundle.plan["setups"]:
        frame = setup_frame(bundle, setup)
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        lathe = machine.get("kind") == "lathe"
        unordered = set()  # why a contour table's cutting order is unknown
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
        centre_features = {op.get("feature") for op in setup["ops"] if op.get("do") in CENTRE_OPS}
        spindle_cites = []
        for name in names:
            feature = mapping(features.get(name))
            at = feature.get("at")
            located = feature.get("kind") in LOCATED_KINDS or name in centre_features
            vector = isinstance(at, list) and len(at) == 3
            placed = vector and all(number(value) for value in at)
            if located and lathe and not placed:
                # On a lathe a feature the kernel measured revolved about setup Z is located
                # by the spindle axis; off-axis or unmeasured ones still need ``at``.
                rows, cite = _spindle_rows(bundle, setup, name, feature, frame, dro)
                if rows:
                    numbers["rows"].extend(rows)
                    spindle_cites.append(cite)
                    located = vector = False
            unknown |= located and not placed
            if located or vector:
                model = model_point(at, frames.get(feature.get("frame", "model")))
                local = frame_point(model, frame)
                numbers["rows"].append({"feature": name, "model": model, "setup": local})
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
                    "contour": contour,
                    "tool_dia_basis": "selected member nominal, not measured",
                }
                generated = False
                if contour.get("method") == "arc_table":
                    arc, lines = _arc(
                        name, feature, op, offset, frame, frames, features, sense, order
                    )
                    if arc:
                        arc.update(stage=stage, allowance_mm=allowance, offset_mm=offset)
                        numbers["arc_table"].append(arc)
                        for line in lines:
                            line["stage"] = stage
                        numbers["line_table"].extend(lines)
                        profile["cutter_centre"] = arc["rows"]
                        unordered.update(
                            item["cut_order_reason"]
                            for item in (arc, *lines)
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
                    dome = _dome(name, feature, op, dro.get("radius_mode") is True)
                    if dome:
                        numbers["contours"].append(dome)
                        generated = True
                if not generated:
                    profile["cutter_centre"] = UNKNOWN
                numbers["profiles"].append(profile)
                unknown |= not generated or not tool or uncertain(tool)
            if lathe:
                unknown |= not number(length_mm(tool, "nose_radius"))
        status = "unknown" if unknown or unordered else "pass"
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
                    *spindle_cites,
                ],
                sentence,
            )
        )
    return result
