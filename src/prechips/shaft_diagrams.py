"""Pivot-shaft lathe setup pictures for the ``shaft-*`` diagram templates.

Each layout draws one setup in its own Z frame (X diametric, Z+ away from the
chuck) as a plan view with the operator side at the bottom. Part outlines come
from CAD values and authored process parameters: arriving material dashed,
material kept after the setup solid, material removed in the setup hatched.
Chuck, shim, centre, rest and tool shapes are schematic symbols owned by the
SVG; layouts only anchor them. Labels sit on rows, spread in anchor order so
they cannot overlap, with leaders back to their features.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import (
    Element,
    Layout,
    _cad,
    _el,
    _fmt,
    _line,
    _number,
    _positive,
    _text,
    _view,
)

Profile = list[tuple[float, float]]  # (Z, radius) along the upper meridian

WIDTH = 720.0
FONT = 14.0
CHAR = 0.58 * FONT  # conservative mean glyph width used to keep labels apart
LINE = 16.0
JAW = 26.0
CHUCK = 44.0
SHIM = 3.0
TOOL = 50.0
LEGEND = 40.0
GROUPS = (
    "removed",
    "waste",
    "arriving",
    "kept",
    "centre",
    "active",
    "planes",
    "datum",
    "arrows",
    "dims",
    "leaders",
    "labels",
)


@dataclass(frozen=True)
class _Frame:
    """Z maps right from ``x0`` at ``z0``; radii map about the horizontal axis."""

    x0: float
    z0: float
    scale: float
    axis: float

    def x(self, z: float) -> float:
        return self.x0 + (z - self.z0) * self.scale

    def up(self, radius: float) -> float:
        return self.axis - radius * self.scale

    def down(self, radius: float) -> float:
        return self.axis + radius * self.scale


def _signed(values: dict, key: str) -> float:
    return _number(values, key, "cad")


def _param(parameters: dict, key: str) -> float:
    return _positive(parameters, key, "process")


def _mm(value: float) -> str:
    text = f"{round(value, 2):g}"
    return "0" if text == "-0" else text.replace("-", "−")


def _z(value: float) -> str:
    text = _mm(value)
    return f"Z{text}" if text == "0" or text.startswith("−") else f"Z+{text}"


def _pt(x: float, y: float) -> str:
    return f"{_fmt(x)} {_fmt(y)}"


def _dome(base: float, sphere: float, height: float, steps: int = 16) -> Profile:
    """Spherical cap meridian from its base to the apex at ``base + height``."""
    points = []
    for index in range(steps + 1):
        depth = height * (1 - index / steps)
        radius = math.sqrt(max(depth * (2 * sphere - depth), 0.0))
        points.append((base + height - depth, radius))
    return points


def _clip(profile: Profile, low: float, high: float) -> Profile:
    result: Profile = []

    def add(point: tuple[float, float]) -> None:
        if not result or result[-1] != point:
            result.append(point)

    for (z0, r0), (z1, r1) in pairwise(profile):
        if z1 < low or z0 > high:
            continue
        if z0 == z1:
            add((z0, r0))
            add((z1, r1))
            continue
        for z in (max(z0, low), min(z1, high)):
            add((z, r0 + (r1 - r0) * (z - z0) / (z1 - z0)))
    return result


def _break(x: float, y0: float, y1: float) -> str:
    """Zig-zag break line from ``(x, y0)`` to ``(x, y1)``."""
    step = (y1 - y0) / 4
    zig = "".join(
        f"L{_pt(x + (5 if index % 2 else -5), y0 + step * (index + 0.5))}"
        for index in range(4)
    )
    return f"{zig}L{_pt(x, y1)}"


def _solid(
    frame: _Frame,
    profile: Profile,
    *,
    left_break: bool = False,
    right_break: bool = False,
) -> Element:
    """Full elevation of a turned body, optionally broken at either end."""
    top = [(frame.x(z), frame.up(r)) for z, r in profile]
    bottom = [(frame.x(z), frame.down(r)) for z, r in reversed(profile)]
    d = "M" + "L".join(_pt(*point) for point in top)
    if right_break:
        d += _break(top[-1][0], top[-1][1], bottom[0][1])
    d += "L" + "L".join(_pt(*point) for point in bottom)
    if left_break:
        d += _break(bottom[-1][0], bottom[-1][1], top[0][1])
    return _el("path", d=d + "Z")


def _half(
    frame: _Frame, profile: Profile, floor: float, **attrs: float | str
) -> Element:
    """Upper part of a body above radius ``floor`` (detail views)."""
    points = [
        (frame.x(profile[0][0]), frame.up(floor)),
        *[(frame.x(z), frame.up(r)) for z, r in profile],
        (frame.x(profile[-1][0]), frame.up(floor)),
    ]
    return _el("path", d="M" + "L".join(_pt(*p) for p in points) + "Z", **attrs)


def _meridian(frame: _Frame, profile: Profile, **attrs: float | str) -> Element:
    points = " ".join(_pt(frame.x(z), frame.up(r)) for z, r in profile)
    return _el("polyline", points=points, **attrs)


def _callouts(
    groups: dict[str, list[Element]],
    items: list[tuple[float, float, list[str]]],
    limit: float,
    *,
    above: bool,
    gap: float = 16.0,
) -> float:
    """Place ``(anchor_x, anchor_y, lines)`` labels on one row with leaders.

    Labels keep anchor order, so leaders never cross, and spread apart so text
    never overlaps; leaders steepen as labels move away from their anchors.
    Above: leader knees stay above ``limit`` and every anchor; returns the
    text top. Below: knees stay below ``limit`` and every anchor; returns the
    text bottom.
    """
    items = sorted(items, key=lambda item: item[0])
    widths = [max(len(line) for line in lines) * CHAR + 12 for *_, lines in items]
    centres: list[float] = []
    edge = 10.0
    for (x, _, _), width in zip(items, widths):
        centres.append(max(x, edge + width / 2))
        edge = centres[-1] + width / 2
    edge = WIDTH - 10
    for index in reversed(range(len(items))):
        centres[index] = min(centres[index], edge - widths[index] / 2)
        edge = centres[index] - widths[index] / 2
    if edge < 10:
        raise CadError("diagram labels do not fit across the printed width")
    offset = max(abs(centre - x) for (x, _, _), centre in zip(items, centres))
    gap = max(gap, min(80.0, offset / 3))
    depth = max(len(lines) for *_, lines in items)
    if above:
        knee = min([limit, *(y - 6 for _, y, _ in items)])
        end = knee - gap
        row = end - 5
    else:
        knee = max([limit, *(y + 6 for _, y, _ in items)])
        end = knee + gap
        row = end + 4
    for (x, y, lines), centre in zip(items, centres):
        first = row - (len(lines) - 1) * LINE if above else row + FONT - 2
        groups["leaders"].append(
            _el("polyline", points=f"{_pt(centre, end)} {_pt(x, knee)} {_pt(x, y)}")
        )
        groups["leaders"].append(_el("circle", cx=x, cy=y, r=1.8, fill="#333"))
        for index, line in enumerate(lines):
            groups["labels"].append(
                _text(centre, first + index * LINE, line, text_anchor="middle")
            )
    if above:
        return row - (depth - 1) * LINE - FONT
    return row + FONT - 2 + (depth - 1) * LINE + 4


def _dimension(
    groups: dict[str, list[Element]],
    x0: float,
    x1: float,
    y: float,
    edge: float,
    text: str,
) -> None:
    """Dimension at ``y`` with extension lines from ``edge``; text above it."""
    beyond = y + 4 if y > edge else y - 4
    groups["dims"] += [
        _line(x0, edge, x0, beyond),
        _line(x1, edge, x1, beyond),
        _line(x0, y, x1, y, marker_start="url(#arr)", marker_end="url(#arr)"),
    ]
    groups["labels"].append(_text((x0 + x1) / 2, y - 5, text, text_anchor="middle"))


def _chuck(
    frame: _Frame, back: float, face: float, radius: float, shim: float = 0.0
) -> dict[str, float]:
    """Schematic 3-jaw anchors: jaws from ``back`` to ``face`` on ``radius``."""
    x = frame.x(back)
    upper = frame.up(radius) - shim - JAW
    return {
        "jaw_x": x,
        "jaw_w": frame.x(face) - x,
        "jaw_h": JAW,
        "jaw_upper_y": upper,
        "jaw_lower_y": frame.down(radius) + shim,
        "chuck_x": x - CHUCK,
        "chuck_w": CHUCK,
        "chuck_y": upper - 6,
        "chuck_h": 2 * (frame.axis - upper) + 12,
        "shim_upper_y": frame.up(radius) - shim,
        "shim_lower_y": frame.down(radius),
        "shim_h": shim,
    }


def _groups() -> dict[str, list[Element]]:
    return {name: [] for name in GROUPS}


def _frame_view(
    chuck: dict[str, float],
    top: float,
    bottom: float,
    legend: tuple[float, float] | None = None,
    **view: float,
) -> dict[str, float]:
    """View scalars and picture band; the legend goes below unless placed."""
    top -= 10
    if legend is None:
        legend = (10.0, bottom + 14)
        bottom = legend[1] + LEGEND
    return _view(
        **chuck,
        **view,
        top=top,
        legend_x=legend[0],
        legend_y=legend[1],
        height=bottom + 10 - top,
    )


def _short(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 1: sawn plain end out of the 3-jaw; face to Z0 and centre-drill."""
    dia = _param(parameters, "stock_dia_mm")
    allowance = _param(parameters, "plain_end_face_allowance_mm")
    grip = _param(parameters, "short_grip_mm")
    projection = _param(parameters, "short_projection_mm")
    blank = _cad(values, "blank_length")
    if not allowance < projection < blank - grip:
        raise CadError(
            "process.short_projection_mm: must exceed the facing allowance "
            "and leave the grip on the blank"
        )
    radius = dia / 2
    scale = min(10.0, 380 / (grip + projection), 120 / dia)
    jaw_face = allowance - projection
    jaw_back = jaw_face - grip
    frame = _Frame(40.0, jaw_back - 80 / scale, scale, 200.0)
    left = frame.z0
    groups = _groups()
    arriving = [(left, radius), (allowance, radius)]
    kept = [(left, radius), (0.0, radius)]
    groups["removed"].append(_solid(frame, arriving, left_break=True))
    groups["arriving"].append(_solid(frame, arriving, left_break=True))
    groups["kept"].append(_solid(frame, kept, left_break=True))
    end = frame.x(0)
    drill = end + 20
    groups["centre"].append(
        _line(frame.x(left) - 8, frame.axis, drill + 84, frame.axis)
    )
    groups["datum"].append(
        _line(end, frame.up(radius) - 8, end, frame.down(radius) + 8)
    )
    chuck = _chuck(frame, jaw_back, jaw_face, radius)
    jaw_top = chuck["jaw_upper_y"]
    dim_y = jaw_top - 12
    _dimension(
        groups,
        frame.x(jaw_back),
        frame.x(jaw_face),
        dim_y,
        jaw_top - 2,
        f"{_mm(grip)} grip",
    )
    _dimension(
        groups,
        frame.x(jaw_face),
        frame.x(allowance),
        dim_y,
        frame.up(radius) - 2,
        f"{_mm(projection)} projection",
    )
    top = _callouts(
        groups,
        [
            (
                frame.x(left) + 18,
                frame.up(radius),
                [f"Ø{_mm(dia)} × {_mm(blank)} blank;", "rest through spindle"],
            ),
            (chuck["chuck_x"] + CHUCK / 2, chuck["chuck_y"], ["3-jaw chuck"]),
            (frame.x(allowance), frame.up(radius), [_z(allowance), "sawn end"]),
            (end, frame.up(radius), ["Z0", "faced end"]),
            (drill + 52, frame.axis - 14, ["2 centre drill", "on axis"]),
        ],
        dim_y - 20,
        above=True,
    )
    tool_y = frame.down(radius) + 2
    bottom = _callouts(
        groups,
        [(end + 9, tool_y + TOOL, ["1 AR tool", "face to Z0"])],
        chuck["jaw_lower_y"] + JAW + 6,
        above=False,
    )
    view = _frame_view(
        chuck, top, bottom, axis=frame.axis, tool_x=end, tool_y=tool_y, drill_x=drill
    )
    return view, groups


def _supported(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 2: north stub in the chuck, plain end on the dead centre."""
    radius = _param(parameters, "stock_dia_mm") / 2
    bearing = _cad(values, "bearing_dia") / 2
    relief = _cad(values, "south_relief_dia") / 2
    relief_low = _signed(values, "south_relief_start")
    relief_high = _signed(values, "south_relief_end")
    shoulder = _cad(values, "shoulder_length")
    grip = _cad(values, "north_grip")
    plain = _cad(values, "plain_end_z")
    start = _cad(values, "turn_start_z")
    stop = _param(parameters, "shoulder_face_allowance_mm")
    reset = _param(parameters, "follow_rest_reset_z_mm")
    rest = reset + _param(parameters, "follow_rest_lead_mm")
    rest_jaw = _param(parameters, "follow_rest_jaw_mm")
    stub = -shoulder - grip
    scale = min(4.0, 560 / (plain - stub), 40 / (2 * radius))
    frame = _Frame(76.0, stub, scale, 200.0)
    groups = _groups()
    arriving = [(stub, radius), (plain, radius)]
    kept = [
        (stub, radius),
        (relief_low, radius),
        (relief_low, relief),
        (relief_high, relief),
        (relief_high, bearing),
        (plain, bearing),
    ]
    groups["removed"].append(_solid(frame, arriving))
    groups["arriving"].append(_solid(frame, arriving))
    groups["kept"].append(_solid(frame, kept))
    centre_x = frame.x(plain)
    groups["centre"].append(
        _line(frame.x(stub) - 8, frame.axis, centre_x + 76, frame.axis)
    )
    groups["datum"].append(
        _line(frame.x(0), frame.up(radius) - 8, frame.x(0), frame.down(radius) + 8)
    )
    arrow_y = frame.down(radius) + 12
    groups["arrows"].append(_line(frame.x(reset) - 8, arrow_y, frame.x(0) + 3, arrow_y))
    window = (-shoulder - 2, relief_high + 5)
    groups["leaders"].append(
        _el(
            "rect",
            x=frame.x(window[0]),
            y=frame.up(radius) - 5,
            width=(window[1] - window[0]) * scale,
            height=2 * radius * scale + 10,
            stroke_dasharray="3 2",
        )
    )
    chuck = _chuck(frame, stub, -shoulder, radius)
    rest_pad_y = frame.up(bearing) - 10
    rest_arm_y = rest_pad_y - 26
    top = _callouts(
        groups,
        [
            (
                frame.x(stub) + grip * scale / 2,
                chuck["jaw_upper_y"],
                ["3-jaw: north stub", f"grip {_mm(grip)}"],
            ),
            (frame.x(window[0]) + 2, frame.up(radius) - 5, ["detail A"]),
            (frame.x(rest), rest_arm_y, ["follow rest", f"reset {_z(rest)}"]),
            (centre_x + 57, frame.axis - 16, ["dead centre", f"{_z(plain)} end"]),
        ],
        chuck["chuck_y"],
        above=True,
    )
    tool_y = frame.down(bearing)
    bottom = _callouts(
        groups,
        [
            (frame.x(0), frame.down(radius), ["Z0", "thrust face"]),
            (
                (frame.x(reset) + frame.x(0)) / 2,
                arrow_y,
                ["rough ×4, finish", f"{_z(start)} → Z0"],
            ),
            (frame.x(reset) + 9, tool_y + TOOL, ["HSS at reset", _z(reset)]),
        ],
        chuck["jaw_lower_y"] + JAW + 6,
        above=False,
    )

    # Detail A: thrust shoulder and south relief, upper half enlarged; drawn
    # once at a trial height to find its label row, then below the main view.
    arriving_detail = _clip(arriving, *window)
    kept_detail = _clip(kept, *window)
    detail_scale = min(24.0, 340 / (window[1] - window[0]))
    floor = max(min(relief, bearing) - 1.0, 0.0)

    def draw_detail(box_top: float, into: dict[str, list[Element]]):
        box_left = 30.0
        detail = _Frame(
            box_left + 8, window[0], detail_scale, box_top + 8 + radius * detail_scale
        )
        box_bottom = detail.up(floor) + 8
        box_right = detail.x(window[1]) + 8
        into["removed"].append(_half(detail, arriving_detail, floor))
        into["arriving"].append(_meridian(detail, arriving_detail))
        into["kept"].append(_half(detail, kept_detail, floor, stroke="none"))
        into["kept"].append(_meridian(detail, kept_detail, fill="none"))
        into["active"].append(
            _line(detail.x(0), detail.up(relief), detail.x(0), detail.up(radius))
        )
        into["planes"].append(
            _line(
                detail.x(stop),
                detail.up(radius) - 6,
                detail.x(stop),
                detail.up(bearing),
            )
        )
        into["leaders"].append(
            _el(
                "rect",
                x=box_left,
                y=box_top,
                width=box_right - box_left,
                height=box_bottom - box_top,
            )
        )
        label_top = _callouts(
            into,
            [
                (box_left + 4, box_top, ["detail A"]),
                (
                    detail.x(-shoulder / 2),
                    detail.up(radius),
                    ["shoulder", f"Ø{_mm(2 * radius)} kept"],
                ),
                (detail.x(0), detail.up(radius), ["thrust face", "Z0"]),
                (detail.x(stop), detail.up(radius) - 6, ["rough stop", _z(stop)]),
                (
                    detail.x((relief_low + relief_high) / 2),
                    detail.up(relief),
                    ["relief", f"Ø{_mm(2 * relief)}"],
                ),
                (
                    detail.x((relief_high + window[1]) / 2),
                    detail.up(bearing),
                    ["bearing", f"Ø{_mm(2 * bearing)}"],
                ),
            ],
            box_top,
            above=True,
        )
        return label_top, box_right, box_bottom

    trial_top, box_right, _ = draw_detail(0.0, _groups())
    box_top = bottom + 14 - trial_top
    _, _, box_bottom = draw_detail(box_top, groups)
    legend_x = WIDTH - 260
    if box_right + 20 > legend_x:
        raise CadError("diagram detail A is wider than its printed band")
    view = _frame_view(
        chuck,
        top,
        max(box_bottom, box_top + 10 + 2 * LEGEND),
        (legend_x, box_top + 10),
        axis=frame.axis,
        tool_x=frame.x(reset),
        tool_y=tool_y,
        centre_x=centre_x,
        rest_x=frame.x(rest - rest_jaw / 2),
        rest_w=rest_jaw * scale,
        rest_pad_y=rest_pad_y,
        rest_arm_x=frame.x(rest) - 4,
        rest_arm_y=rest_arm_y,
        rest_top_y=frame.axis - 5,
    )
    return view, groups


def _reverse(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 3: reversed on a protected body grip; journal, relief, dome."""
    radius = _param(parameters, "stock_dia_mm") / 2
    bearing = _cad(values, "bearing_dia") / 2
    journal = _cad(values, "journal_dia") / 2
    south = _cad(values, "south_relief_dia") / 2
    south_width = _signed(values, "south_relief_end") - _signed(
        values, "south_relief_start"
    )
    north = _cad(values, "north_relief_dia") / 2
    thrust = _signed(values, "thrust_z")
    shoulder = _signed(values, "north_shoulder_z")
    relief_end = _signed(values, "north_relief_end")
    base = _signed(values, "north_base_z")
    sphere = _cad(values, "north_dome_radius")
    height = _cad(values, "north_dome_height")
    stub = _param(parameters, "stub_allowance_mm")
    grip = _param(parameters, "reverse_grip_mm")
    jaw_face = _signed(values, "reverse_jaw_z")
    scale = min(12.0, 470 / (grip + stub - jaw_face), 120 / (2 * radius))
    frame = _Frame(40.0, jaw_face - grip - 70 / scale, scale, 200.0)
    left = frame.z0
    groups = _groups()
    body = [
        (left, bearing),
        (thrust - south_width, bearing),
        (thrust - south_width, south),
        (thrust, south),
        (thrust, radius),
        (shoulder, radius),
    ]
    arriving = [*body, (stub, radius)]
    kept = [
        *body,
        (shoulder, north),
        (relief_end, north),
        (relief_end, journal),
        *_dome(base, sphere, height),
    ]
    groups["removed"].append(_solid(frame, arriving, left_break=True))
    groups["arriving"].append(_solid(frame, arriving, left_break=True))
    groups["kept"].append(_solid(frame, kept, left_break=True))
    groups["centre"].append(
        _line(frame.x(left) - 8, frame.axis, frame.x(stub) + 24, frame.axis)
    )
    groups["datum"].append(
        _line(frame.x(0), frame.up(radius) - 8, frame.x(0), frame.down(radius) + 8)
    )
    chuck = _chuck(frame, jaw_face - grip, jaw_face, bearing, SHIM)
    dome_depth = height / 2
    top = _callouts(
        groups,
        [
            (
                frame.x(jaw_face - grip / 2),
                chuck["jaw_upper_y"],
                ["3-jaw, protected", f"grip on Ø{_mm(2 * bearing)}"],
            ),
            (
                frame.x((thrust + shoulder) / 2),
                frame.up(radius),
                ["shoulder", f"Ø{_mm(2 * radius)} kept"],
            ),
            (
                frame.x((shoulder + relief_end) / 2),
                frame.up(north),
                ["2 relief", f"Ø{_mm(2 * north)}"],
            ),
            (
                frame.x((relief_end + base) / 2),
                frame.up(journal),
                ["1 journal", f"Ø{_mm(2 * journal)}"],
            ),
            (
                frame.x(-dome_depth),
                frame.up(math.sqrt(dome_depth * (2 * sphere - dome_depth))),
                ["4 dome", f"R{_mm(sphere)}"],
            ),
            (frame.x(stub / 2), frame.up(radius), ["3 face stub", "to apex Z0"]),
        ],
        chuck["chuck_y"],
        above=True,
    )
    jaw_bottom = chuck["jaw_lower_y"] + JAW
    dim_y = jaw_bottom + 26
    _dimension(
        groups,
        frame.x(jaw_face - grip),
        frame.x(jaw_face),
        dim_y,
        jaw_bottom + 2,
        f"{_mm(grip)} grip",
    )
    edge = frame.down(radius)
    bottom = _callouts(
        groups,
        [
            (frame.x(jaw_face), jaw_bottom, [_z(jaw_face), "jaw face"]),
            (
                frame.x(thrust),
                edge,
                [f"{_z(thrust)} thrust", f"{_mm(thrust - jaw_face)} from jaws"],
            ),
            (frame.x(shoulder), edge, [_z(shoulder), "shoulder"]),
            (frame.x(relief_end), edge, [_z(relief_end), "relief end"]),
            (frame.x(base), edge, [_z(base), "dome base"]),
            (frame.x(0), edge, ["Z0", "apex"]),
            (frame.x(stub), edge, [_z(stub), "stub end"]),
        ],
        dim_y + 6,
        above=False,
    )
    return _frame_view(chuck, top, bottom, axis=frame.axis), groups


def _fit(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 4: fit-scribed body held; part waste, face and dome the south end."""
    bearing = _cad(values, "bearing_dia") / 2
    sphere = _cad(values, "south_dome_radius")
    height = _cad(values, "south_dome_height")
    base = _signed(values, "south_base_z")
    parting = _signed(values, "parting_z")
    apex = _param(parameters, "fit_apex_mm")
    blade = _param(parameters, "blade_width_mm")
    grip = _param(parameters, "fit_grip_mm")
    jaw_face = -_param(parameters, "fit_jaw_offset_mm")
    scale = min(12.0, 400 / (grip + parting - jaw_face), 100 / (2 * bearing))
    frame = _Frame(40.0, jaw_face - grip - 60 / scale, scale, 200.0)
    left, right = frame.z0, parting + 110 / scale
    groups = _groups()
    arriving = [(left, bearing), (right, bearing)]
    kept = [(left, bearing), *_dome(base, sphere, height)]
    waste = [(parting + blade, bearing), (right, bearing)]
    groups["removed"].append(_solid(frame, arriving, left_break=True, right_break=True))
    groups["waste"].append(_solid(frame, waste, right_break=True))
    groups["arriving"].append(
        _solid(frame, arriving, left_break=True, right_break=True)
    )
    groups["kept"].append(_solid(frame, kept, left_break=True))
    groups["centre"].append(
        _line(frame.x(left) - 8, frame.axis, frame.x(right) + 14, frame.axis)
    )
    groups["datum"].append(
        _line(frame.x(0), frame.up(bearing) - 8, frame.x(0), frame.down(bearing) + 8)
    )
    groups["planes"].append(
        _line(
            frame.x(parting),
            frame.up(bearing) - 12,
            frame.x(parting),
            frame.down(bearing) + 12,
        )
    )
    chuck = _chuck(frame, jaw_face - grip, jaw_face, bearing, SHIM)
    dome_depth = height / 2
    top = _callouts(
        groups,
        [
            (
                frame.x(jaw_face - grip / 2),
                chuck["jaw_upper_y"],
                ["3-jaw, protected", f"grip on Ø{_mm(2 * bearing)}"],
            ),
            (frame.x(0), frame.up(bearing) - 8, ["scribe = Z0", "from ear fit"]),
            (
                frame.x(apex - dome_depth),
                frame.up(math.sqrt(dome_depth * (2 * sphere - dome_depth))),
                ["3 dome", f"R{_mm(sphere)}"],
            ),
            (
                frame.x((apex + parting) / 2),
                frame.up(bearing),
                ["2 face apex", _z(apex)],
            ),
            (
                frame.x((parting + right) / 2),
                frame.up(bearing),
                ["waste; actual end", "beyond break"],
            ),
        ],
        chuck["chuck_y"],
        above=True,
    )
    jaw_bottom = chuck["jaw_lower_y"] + JAW
    dim_y = jaw_bottom + 26
    _dimension(
        groups,
        frame.x(jaw_face - grip),
        frame.x(jaw_face),
        dim_y,
        jaw_bottom + 2,
        f"{_mm(grip)} grip",
    )
    edge = frame.down(bearing)
    blade_y = edge + 1
    bottom = _callouts(
        groups,
        [
            (frame.x(jaw_face), jaw_bottom, [_z(jaw_face), "jaw face"]),
            (frame.x(0), edge, ["Z0", "scribe"]),
            (frame.x(base), edge, [_z(base), "dome base"]),
            (frame.x(apex), edge, [_z(apex), "apex"]),
            (frame.x(parting), edge, [_z(parting), "1 part off"]),
        ],
        max(dim_y + 6, blade_y + TOOL + 4),
        above=False,
    )
    view = _frame_view(
        chuck,
        top,
        bottom,
        axis=frame.axis,
        blade_x=frame.x(parting),
        blade_y=blade_y,
        blade_w=blade * scale,
    )
    return view, groups


SHAFT_LAYOUTS = {
    "shaft-short": _short,
    "shaft-supported": _supported,
    "shaft-reverse": _reverse,
    "shaft-fit": _fit,
}
