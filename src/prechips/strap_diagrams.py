"""Arc-strap setup pictures for the ``plate-strap`` template.

Plan views look down on the fixture plate with the operator at the bottom of
the page: +X right from the blank's left end (X0), the fence at the back (Y0)
and the blank in front of it, pushed against it by edge clamps at the front.
The strap outline, hub hole and margin stations come from the adapter; plate,
fence, clamp and cutter sizes from authored parameters. The plate, fence, vise
jaws and clamps are schematic symbols.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree

from prechips.cad import CadError, _shorthand
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _rect
from prechips.jig_diagrams import (
    _datum_label,
    _finish,
    _groups,
    _label,
    _param,
    _title,
)
from prechips.shaft_diagrams import _callouts, _dimension

Groups = dict[str, list[Element]]
Point = tuple[float, float]

_TITLES = {
    "saw": "Top view, bar end at the left",
    "rough": "Plan: blank on the plate; rough one face, flip, rough the other",
    "finish": "Plan: blank reseated; finish the first face",
    "outline": "Plan: last face finished, hub hole, outline left on tabs",
    "inspect": "Finished strap, either face up",
}
_CLAMP = 16.0  # schematic edge-clamp body, px
_SAMPLE = 2.0  # outline sampling step along the arcs, mm


def _outline(values: dict) -> dict:
    outline = values.get("outline")
    if not isinstance(outline, dict):
        raise CadError("cad.outline: expected the strap outline for the diagram")
    return outline


def _loop(outline: dict, extra: list[float]) -> tuple[list[Point], list[bool]]:
    """The strap outline, model mm, from the top arc's middle clockwise as
    drawn, and whether each point lies on the bottom arc. ``extra`` adds
    bottom-arc stations (tab edges) to the sampling."""
    centre = outline["centre_y"]

    def arc(radius: float, reach: float, more: list[float]) -> list[Point]:
        count = max(2, math.ceil(2 * reach / _SAMPLE))
        xs = {-reach + 2 * reach * index / count for index in range(count + 1)}
        xs |= {x for x in more if abs(x) < reach}
        return [(x, centre - math.sqrt(radius**2 - x**2)) for x in sorted(xs)]

    top = arc(outline["top_radius"], outline["top_end"][0], [])
    bottom = arc(outline["bottom_radius"], outline["foot"][0], extra)
    cx, cy = outline["corner"]
    points = [*top, (cx, cy), *reversed(bottom), (-cx, cy)]
    on_bottom = [False] * (len(top) + 1) + [True] * len(bottom) + [False]
    return points, on_bottom


def _offset(points: list[Point], distance: float) -> list[Point]:
    """Each vertex moved ``distance`` outward along its mean edge normal."""
    area = sum(
        a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])
    )
    sign = 1 if area > 0 else -1
    result = []
    for index, (x, y) in enumerate(points):
        before, after = points[index - 1], points[(index + 1) % len(points)]
        normals = []
        for (x0, y0), (x1, y1) in ((before, (x, y)), ((x, y), after)):
            length = math.hypot(x1 - x0, y1 - y0)
            normals.append((sign * (y1 - y0) / length, -sign * (x1 - x0) / length))
        nx, ny = normals[0][0] + normals[1][0], normals[0][1] + normals[1][1]
        norm = math.hypot(nx, ny)
        nx, ny = nx / norm, ny / norm
        # Keep the offset distance square to both edges at a corner.
        cosine = max(0.3, nx * normals[0][0] + ny * normals[0][1])
        result.append((x + nx * distance / cosine, y + ny * distance / cosine))
    return result


def _path(points: list[Point], close: bool = True) -> str:
    body = " L".join(f"{x:.1f} {y:.1f}" for x, y in points)
    return f"M{body}" + (" Z" if close else "")


class _Plan:
    """Setup frame to page: X from the blank's left end, Y into the blank."""

    def __init__(self, values: dict, parameters: dict) -> None:
        plate = values.get("plate_x_mm")
        if not isinstance(plate, list) or len(plate) != 2:
            raise CadError("process.plate_x_mm: expected the plate's [start, end]")
        self.plate = (float(plate[0]), float(plate[1]))
        self.plate_width = _param(parameters, "plate_width_mm")
        self.fence = _param(parameters, "fence_width_mm")
        self.length = _cad(values, "blank_length_mm")
        self.width = _cad(values, "blank_width_mm")
        self.scale = 640 / (self.plate[1] - self.plate[0])
        self.x0 = 40 - self.plate[0] * self.scale
        # The fence's front face (Y0), below the title and the back labels.
        self.y0 = 96 + self.fence * self.scale
        self.hub_x = _param(parameters, "hub_x_mm")
        self.hub_y = _param(parameters, "hub_y_mm")
        stations = values.get("clamp_x_mm")
        if not isinstance(stations, list) or not stations:
            raise CadError("cad.clamp_x_mm: expected the clamp stations")
        self.clamps = [float(x) for x in stations]

    def px(self, x: float) -> float:
        return self.x0 + x * self.scale

    def py(self, depth: float) -> float:
        """Page y of a point ``depth`` in front of the fence face."""
        return self.y0 + depth * self.scale

    def model(self, outline: dict, point: Point) -> Point:
        x, y = point
        return self.px(self.hub_x + x), self.py(self.hub_y - (y - outline["hub_y"]))

    @property
    def front(self) -> float:
        return self.py(self.width)


def _fixture(groups: Groups, plan: _Plan) -> float:
    """Plate, fence and edge clamps; returns the picture's lowest fixture y."""
    left, right = plan.px(plan.plate[0]), plan.px(plan.plate[1])
    back = plan.y0 - plan.fence * plan.scale
    bottom = back + plan.plate_width * plan.scale
    groups["fixture-plate"] += [
        _rect(left, back, right - left, bottom - back),
        _rect(left, back, right - left, plan.y0 - back),
    ]
    groups["datum"].append(_line(left, plan.y0, right, plan.y0))
    _datum_label(groups, right, back - 8, "Y0: fence face", "end")
    groups["datum"].append(_line(plan.px(0), plan.y0, plan.px(0), plan.front))
    _datum_label(groups, plan.px(0) + 4, back - 8, "X0: blank end (probed)", "start")
    for station in plan.clamps:
        groups["clamp"].append(
            _rect(plan.px(station) - _CLAMP / 2, plan.front, _CLAMP, _CLAMP)
        )
    groups["axis"] += [
        _line(left, bottom + 30, left + 36, bottom + 30),
        _line(left, bottom + 30, left, bottom + 2),
    ]
    _label(groups, left + 40, bottom + 35, "+X")
    _label(groups, left + 6, bottom + 14, "+Y")
    return bottom


def _blank_plan(groups: Groups, plan: _Plan, roles: tuple[str, ...]) -> None:
    box = (plan.px(0), plan.y0, plan.length * plan.scale, plan.front - plan.y0)
    for role in roles:
        groups[role].append(_rect(*box))


def _faces(groups: Groups, plan: _Plan, parameters: dict) -> Layout:
    bottom = _fixture(groups, plan)
    _blank_plan(groups, plan, ("part-arriving", "part-kept"))
    radius = _param(parameters, "face_cutter_dia_mm") / 2 * plan.scale
    middle = (plan.y0 + plan.front) / 2
    start = plan.px(0) - radius - 6
    groups["cutter"].append(_el("circle", cx=start, cy=middle, r=radius))
    groups["arrow"].append(
        _line(start + radius + 4, middle, plan.px(plan.length) - 8, middle)
    )
    _label(groups, plan.px(plan.length / 2), middle - 8, "cutter path", "middle")
    items = [
        (
            plan.px(plan.clamps[0]),
            plan.front + _CLAMP,
            ["edge clamps at X {{cad.clamp_stations_in}},", "tops below the cut"],
        ),
        (
            plan.px(plan.length * 0.7),
            plan.front,
            [
                "blank {{process.blank_length_in:g}} × {{process.blank_width_in:g}},",
                "full face cut",
            ],
        ),
    ]
    return _finish(groups, _callouts(groups, items, bottom + 40, above=False))


def _outline_plan(
    groups: Groups, plan: _Plan, values: dict, parameters: dict
) -> Layout:
    outline = _outline(values)
    bottom = _fixture(groups, plan)
    _blank_plan(groups, plan, ("part-arriving",))
    tabs = [x - plan.hub_x for x in plan.clamps]
    half = _param(parameters, "tab_width_mm") / 2
    edges = [x + side * half for x in tabs for side in (-1, 1)]
    points, on_bottom = _loop(outline, edges)
    inner = [plan.model(outline, point) for point in points]
    outer = [
        plan.model(outline, point)
        for point in _offset(points, _cad(values, "slot_reach_mm"))
    ]
    groups["part-kept"].append(_el("path", d=_path(inner)))
    # The slot, in runs broken where a tab is left on the bottom arc.
    count = len(points)
    runs: list[list[int]] = [[]]
    for index in range(count):
        after = (index + 1) % count
        middle = (points[index][0] + points[after][0]) / 2
        tab = (
            on_bottom[index]
            and on_bottom[after]
            and any(abs(middle - x) < half for x in tabs)
        )
        if tab:
            runs.append([])
        else:
            runs[-1] += [index, after]
    for run in runs:
        if not run:
            continue
        order = list(dict.fromkeys(run))
        ring = [outer[i] for i in order] + [inner[i] for i in reversed(order)]
        groups["part-removed"].append(_el("path", d=_path(ring)))
    hub = plan.model(outline, (0.0, outline["hub_y"]))
    groups["holes"].append(
        _el(
            "circle",
            cx=hub[0],
            cy=hub[1],
            r=values["hub_dia_band_mm"][0] * plan.scale / 2,
        )
    )
    items = [
        (
            hub[0],
            hub[1],
            ["hub hole X {{cad.hub_x_in:.3f}}", "Y −{{cad.hub_y_in:.3f}}"],
        ),
        (
            plan.px(plan.clamps[-1]),
            plan.front,
            [
                "tab at each clamp:",
                "{{process.tab_width_mm:in.2dot}} wide, {{process.tab_height_mm:in.3dot}} thick",
            ],
        ),
        (
            plan.px(plan.clamps[0]),
            plan.front + _CLAMP,
            ["edge clamps at X", "{{cad.clamp_stations_in}}"],
        ),
    ]
    return _finish(groups, _callouts(groups, items, bottom + 40, above=False))


def _saw(groups: Groups, parameters: dict) -> Layout:
    length = _param(parameters, "blank_length_in")
    width = _param(parameters, "blank_width_in")
    kerf = _param(parameters, "kerf_in")
    scale = 560 / (length + 3)
    x, top = 40.0, 70.0
    bottom = top + max(width * scale, 30)
    x1 = x + length * scale
    groups["part-kept"].append(_rect(x, top, x1 - x, bottom - top))
    _label(groups, (x + x1) / 2, (top + bottom) / 2 + 5, "blank", "middle")
    _dimension(groups, x, x1, top - 16, top, "{{process.blank_length_in:g}}")
    groups["part-removed"].append(_rect(x1, top, max(kerf * scale, 3), bottom - top))
    rest = x1 + max(kerf * scale, 3)
    groups["part-rest"].append(_rect(rest, top, 680 - rest, bottom - top))
    _label(groups, (rest + 680) / 2, (top + bottom) / 2 + 5, "bar", "middle")
    _label(
        groups,
        x,
        bottom + 22,
        "{{process.quantity:d}} blanks, one after another from the bar end",
    )
    return _finish(groups, bottom + 28)


def _inspect(groups: Groups, values: dict) -> Layout:
    outline = _outline(values)
    points, _ = _loop(outline, [])
    half = outline["corner"][0]
    scale = 620 / (2 * half)
    top = 96.0

    def page(point: Point) -> Point:
        x, y = point
        return 50 + (x + half) * scale, top + (outline["top_end"][1] - y) * scale

    groups["part-kept"].append(_el("path", d=_path([page(point) for point in points])))
    hub = page((0.0, outline["hub_y"]))
    radius = values["hub_dia_band_mm"][0] * scale / 2
    groups["holes"].append(_el("circle", cx=hub[0], cy=hub[1], r=radius))
    groups["centre-line"].append(_line(hub[0], top - 14, hub[0], hub[1] + 40))
    left, right = page((-half, outline["corner"][1])), page(outline["corner"])
    low = page((0.0, outline["bottom_y"]))[1]
    _dimension(
        groups,
        left[0],
        right[0],
        top - 30,
        left[1],
        f"({_shorthand(_cad(values, 'overall_length_in'), 2)})",
    )
    items = [
        (
            hub[0],
            hub[1] + radius,
            [
                "hub Ø{{cad.hub_dia_min_in:.4dot}}–{{cad.hub_dia_max_in:.4dot}}",
                "reamed through",
            ],
        ),
        (
            hub[0] + 90,
            low + 4,
            [
                "edges from the hub centre:",
                "{{cad.top_height_min_in:.3dot}}–{{cad.top_height_max_in:.3dot}} above, {{cad.bottom_height_min_in:.3dot}}–{{cad.bottom_height_max_in:.3dot}} below",
            ],
        ),
        (
            right[0] - 4,
            right[1],
            [
                "corner {{cad.corner_station_min_in:.2f}}–{{cad.corner_station_max_in:.2f}}",
                "from the hub centre",
            ],
        ),
    ]
    return _finish(groups, _callouts(groups, items, low + 46, above=False))


def _plate_strap(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    step = root.attrib.pop("data-step", None)
    if step not in _TITLES:
        raise CadError(
            f"plate-strap: data-step must be one of {', '.join(_TITLES)}, not {step!r}"
        )
    groups = _groups(root)
    _title(groups, 40, 24, _TITLES[step])
    if step == "saw":
        return _saw(groups, parameters)
    if step == "inspect":
        return _inspect(groups, values)
    plan = _Plan(values, parameters)
    if step == "outline":
        return _outline_plan(groups, plan, values, parameters)
    return _faces(groups, plan, parameters)


STRAP_LAYOUTS = {"plate-strap": _plate_strap}
