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
from .resolution import UNKNOWN, length_mm, number, resolve, uncertain
from .tip_endpoints import stock_states

AXES = ("x", "y", "z")


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


def _arc(feature_name, feature, op, offset, frame, frames, features):
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
            joins = _joins(feature, linked[0], offset) if len(linked) == 1 else None
            if linked and joins is None:
                return None, []
            endpoint = joins[0] if joins else feature.get("end")
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
        "centre_setup_xy": frame_point(model_centre, frame)[:2],
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
    if number(step):
        arc["max_chord_sagitta_mm"] = cutter_radius * (
            1 - math.cos(math.radians(min(step, abs(end - start)) / 2))
        )
    lines = []
    if bottom and joins:
        sides = (-1, 1) if feature.get("mirror_symmetric") is True else (1,)
        for side in sides:
            xy = [[centre[0] + side * (p[0] - centre[0]), p[1]] for p in joins]
            lines.append(
                {
                    "op": op["op"],
                    "feature": feature_name,
                    "side": "+X" if side == 1 else "-X",
                    "model_xy": xy,
                    "setup_xy": [frame_point(_xy_model(p, feature, frames), frame)[:2] for p in xy],
                    "offset_mm": offset,
                    "tip_z": op.get("to_z", UNKNOWN),
                    "join_method": "line-line miter and exact line-circle intersections",
                }
            )
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
            unbound = frame.get("binding") == UNKNOWN
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
    frames = mapping(bundle.features.get("frames"))
    dro = mapping(bundle.plan.get("dro"))
    for setup in bundle.plan["setups"]:
        frame = mapping(frames.get(setup.get("frame")))
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        lathe = machine.get("kind") == "lathe"
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
        for name in names:
            feature = mapping(features.get(name))
            at = feature.get("at")
            if isinstance(at, list) and len(at) == 3:
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
            allowance = (
                op.get("rough_allowance_mm", op.get("stock_to_leave_mm", UNKNOWN)) if rough else 0
            )
            offset = radius + allowance if number(radius) and number(allowance) else UNKNOWN
            profile = {
                "feature": name,
                "op": op["op"],
                "tool": op.get("tool", UNKNOWN),
                "tool_dia": diameter,
                "tool_nominal_dia_mm": diameter,
                "cutter_radius_mm": radius,
                "offset_mm": offset,
                "rough_allowance_mm": allowance if rough else "not_applicable",
                "entry_z": before["entry_z"].get(name, before["top_z"]),
                "to_z": op.get("to_z", UNKNOWN),
                "contour": contour,
                "tool_dia_basis": "selected member nominal, not measured",
            }
            generated = False
            if contour.get("method") == "arc_table":
                arc, lines = _arc(name, feature, op, offset, frame, frames, features)
                if arc:
                    arc["allowance_mm"] = allowance
                    numbers["arc_table"].append(arc)
                    numbers["line_table"].extend(lines)
                    profile["cutter_centre"] = arc["rows"]
                    generated = True
            elif contour.get("method") == "linear_table":
                path = _linear(feature, op, offset, radius, frame, frames)
                if path:
                    profile["cutter_centre"] = path
                    generated = True
            elif contour.get("method") == "axial_table":
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
        status = "unknown" if unknown else "pass"
        sentence = (
            "Feature targets use the declared model-to-setup basis; cutter tables use explicit "
            "nominal geometry and authored allowance."
        )
        if unknown:
            sentence += (
                " Missing geometry or unverified tool/frame binding prevents a cleared toolpath."
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
                ],
                sentence,
            )
        )
    return result
