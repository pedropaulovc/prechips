"""Clamp-half setup pictures for the ``clamp-half`` template.

``data-step`` picks the picture. ``saw``: the blank on the square bar.
``half``: one half in the vise, seen along the jaws and, lying, from above;
``data-up`` names the face that is up and ``data-work`` what is done to it:

* ``end`` (the blank upright, ``data-work="face"``, ``data-end`` ``first``
  or ``length``);
* ``bottom`` and ``top`` (lying, jaws on the raw mating and outside faces;
  ``face``: the bottom cleaned up, the top faced to height);
* ``mating`` (lying, jaws on the top and bottom faces; ``face`` skims the
  split line, ``face-off`` takes the back's grip gap off after the bore);
* ``outside`` (lying, jaws on the top and bottom faces, the bottom face on
  the fixed jaw; ``drill`` faces to depth and drills the ears, ``tap`` taps
  the back's).

A lying ``half`` with the bottom face on the fixed jaw (``mating`` or
``outside`` up) draws the near side (X0) at the end the hold puts it, from
the model frame: at the right when the face up looks toward +X (the front's
outside face, the back's mating face), at the left otherwise; turning the
half over about its height swaps the ends.

``pair``: the two halves screwed together for the bore, from above: the
back's outside face on the fixed jaw, a block between the screw heads on the
front's, parallels clear of the bore. ``inspect``: the finished half, seen
along the bore and at its outside face; ``data-bored="no"`` draws it before
the bore, at the depth it is bored at and at its mating face with the ears'
drill exits.

The vise holds are seen along the jaws from the low X end, the fixed jaw at
the left, with a plan from above (beside an upright blank, below a lying
one). ``data-stop`` draws the work stop's rod against the near side (an
upright blank's left face) in the plan: ``rod``, or ``rod-labelled`` on the
one picture of a sheet that names it and says when it is set.

Sizes come from the adapter (envelope, bore, ears, the pair) and from
authored parameters. Tools are drawn to scale from the plan's numbers: the
end mill (``face_cutter_dia_mm``) at its whole stick-out
(``half_mill_projection_mm``) on the face's first pass
(``face_stepover_max_mm``, ``face_overhang_mm``), a circle from above with
the pass direction; an ear drill at the hole's diameter, its point at
``drill_tip_height_mm``; the tap at its thread's major diameter to
``tap_point_depth_mm``; the tap guide (``tap_guide_dia_mm``,
``tap_guide_point_dia_mm``); the work stop's rod (``stop_rod_dia_mm``).
Tools and rods too long for the picture end in a break line. Jaws, the
tap's wrench and the 1-2-3 block's length are schematic.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _process, _rect
from prechips.jig_diagrams import (
    DimText,
    _datum_label,
    _finish,
    _groups,
    _label,
    _param,
    _title,
    _vdim,
)
from prechips.shaft_diagrams import _callouts, _dimension

Groups = dict[str, list[Element]]

_TITLES = {
    "saw": "Side view, bar end at the left",
    "half": "Looking along the jaws",
    "pair": "The pair screwed together, from above, down the bore",
    "inspect": "Finished half, down the bore and at its outside face",
}
# The face up and the work each allows.
_HALF = {
    "end": ("face",),
    "bottom": ("face",),
    "top": ("face",),
    "mating": ("face", "face-off"),
    "outside": ("drill", "tap"),
}
_ENDS = ("first", "length")
# ``data-stop`` on a vise hold: the work stop's rod drawn at the near side
# (upright, the left face), and once on the sheet named.
_STOPS = ("rod", "rod-labelled")
_JAW = 40.0  # schematic jaw body, px
_S = 6.0  # px per mm
_REMOVED = 7.0  # px: the layer a face takes off, schematic
# Tools drawn short end in a break line; these lengths are the picture's,
# not the tools': a drill or the tap guide above the part, px.
_SHORT = 60.0
_BREAK = 3.0  # px: a break line's teeth
_ROD_OUT = 70.0  # px: the work stop's rod drawn out from its tip
# The tap's T-handle wrench (no size on record), schematic, px: its gap above
# the face and its thickness; the tap guide's point drawn out of its body.
_WRENCH_GAP = 50.0
_WRENCH = 9.0
_GUIDE_POINT = 20.0
_DRILL_POINT_DEG = 118.0  # a jobber drill's point
_GUIDE_POINT_DEG = 60.0  # the tap guide's point, as it seats in a centre hole


def _saw(groups: Groups, parameters: dict) -> Layout:
    high = _param(parameters, "blank_length_max_in")
    kerf = _param(parameters, "kerf_in")
    section = _param(parameters, "blank_section_in")
    # Px per inch: a short blank drawn large, a long one still leaving a
    # stub of bar beyond the kerf.
    scale = min(150.0, 400.0 / (high + kerf))
    x, top = 60.0, 78.0
    height = section * scale
    x1 = x + high * scale
    bottom = top + height
    groups["part-kept"].append(_rect(x, top, x1 - x, height))
    _label(groups, (x + x1) / 2, (top + bottom) / 2 + 5, "blank", "middle")
    _dimension(
        groups,
        x,
        x1,
        top - 16,
        top,
        "{{process.blank_length_min_in:.2dot}}–{{process.blank_length_max_in:.2dot}}",
    )
    cut = max(kerf * scale, 3)
    groups["part-removed"].append(_rect(x1, top, cut, height))
    groups["part-rest"].append(_rect(x1 + cut, top, 660 - x1 - cut, height))
    _label(
        groups,
        (x1 + cut + 660) / 2,
        (top + bottom) / 2 + 5,
        "{{process.blank_section_in:.3dot}} square bar",
        "middle",
    )
    _label(
        groups,
        x,
        bottom + 22,
        "Blank {{process.blank_length_min_in:.2dot}}–{{process.blank_length_max_in:.2dot}} long:"
        " {{cad.end_stock_min_in:.2dot}}–{{cad.end_stock_max_in:.2dot}} comes off"
        " the two ends together, to {{cad.width_min_in:.2dot}}–{{cad.width_max_in:.2dot}}.",
    )
    return _finish(groups, bottom + 28)


def _arc(cx: float, face: float, radius: float, gap: float, up: bool) -> Element:
    """The half bore where it meets the mating face at ``face``: a circle about
    (``cx``, ``face`` ± ``gap``) cut off by the face, bulging up or down."""
    chord = math.sqrt(radius**2 - gap**2)
    sweep = 1 if up else 0
    return _el(
        "path",
        d=f"M{cx - chord:.1f} {face:.1f} A{radius:.1f} {radius:.1f} 0 0 {sweep} "
        f"{cx + chord:.1f} {face:.1f} Z",
    )


def _ear_text(values: dict, drill: bool = False) -> list[str]:
    """The ear callout: the front's clearance holes, the back's taps or, while
    they are drilled, their tap drill."""
    if values.get("half") == "front" or drill:
        size = "2X Ø{{cad.ear_dia_min_in:.3dot}}–{{cad.ear_dia_max_in:.3dot}} thru,"
        if values.get("half") == "front":
            return [size, "{{cad.ear_clearance_for}} clearance"]
        return [size, "{{cad.ear_thread}} tap drill"]
    return ["2X {{cad.ear_thread}}", "thru"]


def _section(parameters: dict) -> float:
    """The raw bar's side, mm: what the jaws hold before a face is sized."""
    return _param(parameters, "blank_section_in") * 25.4


def _first_pass(parameters: dict, across: float) -> tuple[float, float]:
    """The facing's first pass over a face ``across`` mm wide, as the recipe
    cuts it: how far the cutter's centre stands outside the fixed-jaw edge,
    and the stepover, mm. Equal passes no wider than face_stepover_max_mm
    that together reach face_overhang_mm past both edges, the first at the
    fixed jaw, the rest toward the moving jaw."""
    overhang = _process(parameters, "face_overhang_mm")
    if overhang < 0:
        raise CadError("process.face_overhang_mm: must not be negative for the diagram")
    span = across + overhang
    count = math.ceil(span / _param(parameters, "face_stepover_max_mm") - 1e-9)
    step = span / count
    return _param(parameters, "face_cutter_dia_mm") / 2 - step, step


def _zigzag(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    """A break line's teeth from (``x0``, ``y0``) to (``x1``, ``y1``), ends
    excluded: where a tool or rod drawn to scale is cut off short."""
    teeth = max(2, round(math.hypot(x1 - x0, y1 - y0) / 8))
    points = []
    for k in range(1, 2 * teeth):
        t = k / (2 * teeth)
        # Teeth stand off the line, square to it.
        lift = _BREAK if k % 2 else 0.0
        length = math.hypot(x1 - x0, y1 - y0)
        nx, ny = (y1 - y0) / length, (x0 - x1) / length
        points.append((x0 + (x1 - x0) * t + nx * lift, y0 + (y1 - y0) * t + ny * lift))
    return points


def _path(points: list[tuple[float, float]]) -> Element:
    return _el("path", d="M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points) + "Z")


def _tool(
    cx: float,
    width: float,
    tip: float,
    top: float,
    point_deg: float | None = None,
    broken: bool = False,
) -> Element:
    """A round tool seen from the side, ``width`` wide (its diameter to the
    picture's scale), from its ``tip`` up to ``top`` (page y): square ended,
    or ground to an included ``point_deg``; ``broken`` ends it in a break
    line where it is drawn short."""
    left, right = cx - width / 2, cx + width / 2
    point = (
        0.0 if point_deg is None else width / 2 / math.tan(math.radians(point_deg / 2))
    )
    outline = [(left, top), (left, tip - point)]
    if point:
        outline.append((cx, tip))
    outline += [(right, tip - point), (right, top)]
    if broken:
        outline += _zigzag(right, top, left, top)
    return _path(outline)


def _rod(tip: float, outward: int, cy: float, width: float, length: float) -> Element:
    """The work stop's rod from above: ``width`` (its diameter to scale) on
    the line ``cy``, its tip at ``tip``, running ``length`` px out on the
    ``outward`` side (-1 left, +1 right) to a break line: its post, on the
    table beyond the vise, is not drawn."""
    end = tip + outward * length
    low, high = cy - width / 2, cy + width / 2
    return _path(
        [
            (tip, low),
            (end, low),
            *_zigzag(end, low, end, high),
            (end, high),
            (tip, high),
        ]
    )


def _stop_label(groups: Groups, x: float, y: float, face: str) -> float:
    """The work stop named once, in the first picture that draws it: what the
    rod is and when it is set. Returns the bottom of the text."""
    lines = [
        "work stop rod Ø{{process.stop_rod_dia_mm:in.3dot}}, low:",
        "drawn back for the touch-offs,",
        f"then set on {face}",
    ]
    for index, line in enumerate(lines):
        _label(groups, x, y + 16 * index, line, "start")
    return y + 16 * (len(lines) - 1)


def _passes(
    groups: Groups,
    left: float,
    right: float,
    edge: float,
    s: float,
    parameters: dict,
    across: float,
) -> None:
    """From above: the end mill on the face's first pass and the pass
    direction, toward +X from the low X end, then the stepover toward the
    moving jaw (down the page). ``edge`` is the fixed-jaw edge's page y."""
    outside, step = _first_pass(parameters, across)
    radius = _param(parameters, "face_cutter_dia_mm") / 2 * s
    y = edge - outside * s
    groups["cutter"].append(_el("circle", cx=(left + right) / 2, cy=y, r=radius))
    path = [(left, y), (right, y), (right, y + step * s)]
    groups["arrow"].append(
        _el(
            "polyline",
            points=" ".join(f"{x:.1f},{y:.1f}" for x, y in path),
            fill="none",
        )
    )


def _half(
    groups: Groups,
    values: dict,
    parameters: dict,
    up: str,
    work: str,
    end: str | None,
    stop: str | None,
) -> Layout:
    """One half in the vise, seen along the jaws (from the low X end, the
    fixed jaw at the left), with a plan from above."""
    if work not in _HALF[up]:
        raise CadError(
            f"clamp-half: with data-up {up!r}, data-work must be one of "
            f"{', '.join(_HALF[up])}, not {work!r}"
        )
    if (up == "end") != (end is not None):
        raise CadError("clamp-half: data-end (first or length) goes with data-up end")
    if end is not None and end not in _ENDS:
        raise CadError(f"clamp-half: data-end must be first or length, not {end!r}")
    back = values.get("half") == "back"
    if work == "face-off" and not back:
        raise CadError("clamp-half: only the back's mating face is faced off")
    if work == "tap" and not back:
        raise CadError("clamp-half: only the back's ears are tapped")
    s = 4.0 if up == "end" else _S
    section = _section(parameters)
    height = _cad(values, "height_mm")
    depth = _cad(values, "bore_axis_depth_mm")
    # Across the jaws and upright, mm, as the part stands in this setup.
    if up == "end":
        across = section
        tall = (
            _param(parameters, "blank_length_max_in") * 25.4
            if end == "first"
            else _cad(values, "width_mm")
        )
        grip = ["jaws on two", "cold-finished faces"]
        rest = "parallel_height_mm"
    elif up in ("bottom", "top"):
        across = section
        tall = section if up == "bottom" else height
        grip = ["jaws on the raw", "outside and mating faces"]
        rest = "riser_height_mm"
    else:
        across = height
        tall = depth if up == "outside" or work == "face-off" else section
        grip = ["jaws on the top", "and bottom faces"]
        rest = "riser_height_mm"
    thick = _param(parameters, "parallel_thickness_mm") * s
    rise = _param(parameters, rest) * s
    jaw = _param(parameters, "vise_jaw_height_mm") * s
    centre = 130.0
    # The tool standing on the part, px above its top: the end mill its
    # whole stick-out; a drill, or the tap guide over the tap's wrench,
    # drawn short to a break line.
    if work == "tap":
        reach = _WRENCH_GAP + _WRENCH + _GUIDE_POINT + _SHORT
    elif work == "drill":
        reach = _SHORT
    else:
        reach = _param(parameters, "half_mill_projection_mm") * s
    # To scale above the vise bed; only the top of the vise is drawn when
    # the parallels are tall, cut off below the seat.
    bed = 60.0 + reach + max(jaw, rise + tall * s)
    seat = bed - rise
    cut = min(bed, seat + 50)
    left, right = centre - across * s / 2, centre + across * s / 2
    if cut == bed:
        groups["fixture-vise"].append(
            _rect(left - _JAW - 12, bed, across * s + 2 * _JAW + 24, 14)
        )
    groups["clamp"] += [
        _rect(left - _JAW, bed - jaw, _JAW, cut - bed + jaw),
        _rect(right, bed - jaw, _JAW, cut - bed + jaw),
    ]
    _label(
        groups,
        left - _JAW / 2,
        bed - jaw + 16,
        "fixed",
        "middle",
        **{"class": "label-on-clamp"},
    )
    groups["fixture-support"] += [
        _rect(left, seat, thick, cut - seat),
        _rect(right - thick, seat, thick, cut - seat),
    ]
    top = seat - tall * s
    groups["part-kept"].append(_rect(left, top, across * s, tall * s))
    names = {
        "end": "sawn END",
        "bottom": "BOTTOM face",
        "top": "TOP face",
        "mating": "MATING face",
        "outside": "OUTSIDE face",
    }
    _label(groups, right + _JAW + 6, top + 4, f"{names[up]} up", "start")
    items = [
        (left + thick / 2, (seat + cut) / 2, ["parallels against", "the jaws"]),
        (right + _JAW / 2, (bed - jaw + cut) / 2, grip),
    ]
    if work in ("face", "face-off") or up == "outside" and work == "drill":
        # The layer this face loses, schematic, on top of what is kept.
        groups["part-removed"].append(_rect(left, top - _REMOVED, across * s, _REMOVED))
        groups["active-face"].append(_line(left, top, right, top))
        if work != "drill":
            # The end mill in the face's first pass, at the fixed jaw.
            outside, _step = _first_pass(parameters, across)
            cutter = _param(parameters, "face_cutter_dia_mm") * s
            groups["cutter"].append(_tool(left - outside * s, cutter, top, top - reach))
        texts = {
            "end": ["face square,", "just clean"]
            if end == "first"
            else [
                "face to length",
                "{{cad.width_min_in:.3dot}}–{{cad.width_max_in:.3dot}}",
            ],
            "bottom": ["face clean,", "just flat"],
            "top": [
                "face to height",
                "{{cad.height_min_in:.3dot}}–{{cad.height_max_in:.3dot}}",
            ],
            "mating": ["skim clean:", "the split line"],
            "outside": [
                "face to depth",
                "{{cad.bore_axis_depth_min_in:.3dot}}–{{cad.bore_axis_depth_max_in:.3dot}}",
            ],
        }
        text = texts[up]
        if work == "face-off":
            text = [
                "face {{cad.grip_offset_min_in:.3dot}}–{{cad.grip_offset_max_in:.3dot}} off,",
                "to depth {{cad.depth_min_in:.3dot}}–{{cad.depth_max_in:.3dot}}",
            ]
        items.append((right - 6, top - _REMOVED / 2, text))
    if up == "outside":
        # An ear hole through the depth, at its height from the fixed jaw.
        hole = _cad(values, "ear_dia_in") * 25.4 * s
        middle = left + _cad(values, "ear_height_mm") * s
        groups["hidden"].append(_rect(middle - hole / 2, top, hole, tall * s))
        if work == "tap":
            # The tap at its thread's major diameter, its point where the
            # plan stops it; its wrench (size not on record) a little above
            # the face; the tap guide's point in the wrench's centre hole
            # and its body, both at their own diameters, drawn short.
            tip = top + _param(parameters, "tap_point_depth_mm") * s
            wrench = top - _WRENCH_GAP
            thread = _cad(values, "ear_thread_major_mm") * s
            groups["cutter"].append(_tool(middle, thread, tip, wrench))
            groups["part-rest"].append(
                _rect(middle - 50, wrench - _WRENCH, 100, _WRENCH)
            )
            point = _param(parameters, "tap_guide_point_dia_mm") * s
            seat_y = wrench - _WRENCH
            body = seat_y - _GUIDE_POINT
            groups["cutter"] += [
                _tool(middle, point, seat_y, body, _GUIDE_POINT_DEG),
                _tool(
                    middle,
                    _param(parameters, "tap_guide_dia_mm") * s,
                    body,
                    body - _SHORT,
                    broken=True,
                ),
            ]
            text = ["{{cad.ear_thread}} by hand,", "through, centre on top"]
        else:
            # The ear drill at the hole's own diameter, its point where the
            # plan puts it below the stacks' top, drawn short above the face.
            tip = seat - _process(parameters, "drill_tip_height_mm") * s
            groups["cutter"].append(
                _tool(middle, hole, tip, top - reach, _DRILL_POINT_DEG, broken=True)
            )
            text = _ear_text(values, drill=True)
        items.append((middle - hole / 2, top + tall * s / 2, text))
    low = _callouts(groups, items, cut + 24, above=False)
    if up == "end":
        _upright_plan(groups, parameters, stop)
        return _finish(groups, low)
    # Bottom face on the fixed jaw: the face up looking toward +X puts the
    # near side at the right.
    mirror = up in ("mating", "outside") and (values.get("half") == "front") == (
        up == "outside"
    )
    return _plan(groups, values, parameters, up, work, across, low, mirror, stop)


def _upright_plan(groups: Groups, parameters: dict, stop: str | None) -> None:
    """From above, beside the upright blank: the square between the jaws,
    X0 Y0 on its axis, the first facing pass and the work stop on the left
    face."""
    s = _S
    side = _section(parameters) * s
    x0, y0 = 470.0, 110.0
    _label(groups, 380, 72, "From above:", "start", **{"class": "title"})
    groups["clamp"] += [
        _rect(x0 - 20, y0 - 18, side + 40, 18),
        _rect(x0 - 20, y0 + side, side + 40, 18),
    ]
    _label(groups, x0 + side + 26, y0 - 4, "fixed jaw", "start")
    groups["part-kept"].append(_rect(x0, y0, side, side))
    cx, cy = x0 + side / 2, y0 + side / 2
    groups["datum"] += [
        _line(cx, cy - 14, cx, cy + 14),
        _line(cx - 14, cy, x0 + side + 22, cy),
    ]
    _datum_label(groups, x0 + side + 26, cy + 5, "X0 Y0: axis", "start")
    _passes(groups, x0, x0 + side, y0, s, parameters, _section(parameters))
    if stop is not None:
        rod = _param(parameters, "stop_rod_dia_mm") * s
        groups["fixture-support"].append(_rod(x0, -1, cy, rod, _ROD_OUT))
        if stop == "rod-labelled":
            _stop_label(groups, x0 - _ROD_OUT, y0 + side + 44, "the LEFT face")


def _plan(
    groups: Groups,
    values: dict,
    parameters: dict,
    up: str,
    work: str,
    across: float,
    low: float,
    mirror: bool,
    stop: str | None,
) -> Layout:
    """From above: the width along the jaws, the near side at the left, or at
    the right when ``mirror``, the stations measured from it; the work stop's
    rod on the near side when ``stop``."""
    _label(groups, 40, low + 34, "From above:", "start", **{"class": "title"})
    s = 6.0
    # Mirrored, the jaw label sits left of the part: room for it on the page.
    x0 = 210.0 if mirror else 150.0
    wide = _cad(values, "width_mm") * s
    deep = across * s
    y0 = low + 110
    # The near side's x on the page, and the page x of a station from it.
    near = x0 + wide if mirror else x0
    step = -s if mirror else s

    def at(key: str) -> float:
        return near + _cad(values, key) * step

    groups["clamp"] += [
        _rect(x0 - 20, y0 - 18, wide + 40, 18),
        _rect(x0 - 20, y0 + deep, wide + 40, 18),
    ]
    groups["part-kept"].append(_rect(x0, y0, wide, deep))
    _datum_label(
        groups,
        near + (6 if mirror else -6),
        y0 - 26,
        "X0: near side",
        "start" if mirror else "end",
    )
    groups["datum"].append(_line(near, y0 - 22, near, y0 + deep + 22))
    bottom = y0 + deep + 40
    if stop is not None:
        rod = _param(parameters, "stop_rod_dia_mm") * s
        outward = 1 if mirror else -1
        groups["fixture-support"].append(
            _rod(near, outward, y0 + deep / 2, rod, _ROD_OUT)
        )
        if stop == "rod-labelled":
            bottom = _stop_label(groups, x0, y0 + deep + 40, "the N end") + 14
    if work == "tap":
        # The tap in the near hole, at its thread's major diameter.
        thread = _cad(values, "ear_thread_major_mm") * s
        groups["cutter"].append(
            _el(
                "circle",
                cx=at("ear_near_x_mm"),
                cy=y0 + _cad(values, "ear_height_mm") * s,
                r=thread / 2,
            )
        )
    else:
        _passes(groups, x0, x0 + wide, y0, s, parameters, across)
    # The jaw label goes at the end away from the near side.
    other = x0 if mirror else x0 + wide
    if up in ("mating", "outside"):
        _label(
            groups,
            other + (-26 if mirror else 26),
            y0 - 4,
            "fixed jaw: BOTTOM face",
            "end" if mirror else "start",
        )
    if work == "face-off":
        bore = at("bore_location_mm")
        radius = _cad(values, "bore_dia_in") * 25.4 * s / 2
        groups["holes"].append(_rect(bore - radius, y0, 2 * radius, deep))
        groups["centre-line"].append(_line(bore, y0 - 30, bore, y0 + deep + 30))
    if up != "outside":
        _dimension(
            groups,
            near,
            other,
            y0 - 40,
            y0,
            "{{cad.width_min_in:.2dot}}–{{cad.width_max_in:.2dot}}",
        )
        return _finish(groups, bottom)
    hole = _cad(values, "ear_dia_in") * 25.4 * s
    ear_y = y0 + _cad(values, "ear_height_mm") * s
    first, second = at("ear_near_x_mm"), at("ear_far_x_mm")
    for x in (first, second):
        groups["holes"].append(_el("circle", cx=x, cy=ear_y, r=hole / 2))
    _dimension(groups, near, first, y0 - 40, y0, "{{cad.ear_near_x_in:.3dot}}")
    _dimension(groups, near, second, y0 - 62, y0, "{{cad.ear_far_x_in:.3dot}}")
    # The ears' height from the fixed jaw, beside the end away from X0.
    side = x0 - 34 if mirror else x0 + wide + 34
    _vdim(
        groups,
        side,
        y0,
        ear_y,
        "Y {{cad.ear_y_in:.3dot}}",
        witness=(other, second),
        place=DimText.ALONG_LEFT if mirror else DimText.RIGHT,
    )
    return _finish(groups, bottom)


# The drawing gives the bore as a reference size with a sliding fit on the
# column, not a size band.
_BORE_REF = "Ø({{cad.bore_dia_mm:in.3dot}}) REF"
_BORE_FIT = [
    "{{cad.bore_clearance_min_in:.3dot}}–{{cad.bore_clearance_max_in:.3dot}} clearance",
    "on the column",
]


def _inspect(groups: Groups, values: dict, bored: bool) -> Layout:
    """The half down its bore axis, then at its outside face; before the bore
    (``bored`` false), at the depth it is bored at and at its mating face,
    where the ears' drill exits are."""
    s = 7.0
    x0, y0 = 150.0, 100.0
    wide = _cad(values, "width_mm") * s
    depth = "depth" if bored else "bore_axis_depth"
    deep = _cad(values, f"{depth}_mm") * s
    face = y0 + deep
    back = values.get("half") == "back"
    gap = _cad(values, "grip_offset_mm") * s if back and bored else 0.0
    bore = x0 + _cad(values, "bore_location_mm") * s
    radius = _cad(values, "bore_dia_in") * 25.4 * s / 2
    station = _cad(values, "ear_station_mm") * s
    hole = _cad(values, "ear_dia_in") * 25.4 * s
    groups["part-kept"].append(_rect(x0, y0, wide, deep))
    if bored:
        groups["holes"].append(_arc(bore, face, radius, gap, True))
        groups["centre-line"].append(_line(bore, y0 - 12, bore, face + gap + 16))
    for side in (-1, 1):
        groups["hidden"].append(_rect(bore + side * station - hole / 2, y0, hole, deep))
        groups["centre-line"].append(
            _line(bore + side * station, y0 - 8, bore + side * station, face + 8)
        )
    _label(groups, x0 - 8, y0 + 12, "OUTSIDE", "end")
    _label(groups, x0 - 8, face, "MATING", "end")
    # N names the near side end, above it, not a row like the faces.
    _label(groups, x0 - 8, y0 - 14, "N: near side", "end")
    _dimension(
        groups,
        x0,
        x0 + wide,
        y0 - 48,
        y0,
        "{{cad.width_min_in:.2dot}}–{{cad.width_max_in:.2dot}}",
    )
    _vdim(
        groups,
        x0 + wide + 20,
        y0,
        face,
        f"{{{{cad.{depth}_min_in:.3dot}}}}–{{{{cad.{depth}_max_in:.3dot}}}}",
        witness=(x0 + wide, x0 + wide),
    )
    if bored:
        _dimension(
            groups,
            x0,
            bore,
            y0 - 24,
            y0,
            "{{cad.bore_location_min_in:.3dot}}–{{cad.bore_location_max_in:.3dot}}",
        )
        items = [
            (
                bore - radius * 0.7,
                face - radius * 0.7,
                [_BORE_REF, "on the bore axis,", *_BORE_FIT],
            ),
            (
                bore + station,
                face - deep / 2,
                [
                    "2X {{cad.ear_station_min_in:.3dot}}–{{cad.ear_station_max_in:.3dot}}",
                    "from the bore axis",
                ],
            ),
        ]
    else:
        # No bore yet: the ears from the near side, where the program put them;
        # the short near one below the part, its text beside it.
        for x, y, start, key in (
            (bore - station, face + 20, face, "ear_near_x"),
            (bore + station, y0 - 24, y0, "ear_far_x"),
        ):
            text = f"{{{{cad.{key}_min_in:.3dot}}}}–{{{{cad.{key}_max_in:.3dot}}}}"
            _dimension(groups, x0, x, y, start, text, beside=y > face)
        items = []
    if back and bored:
        items.append(
            (
                bore + radius + 12,
                face,
                [
                    "{{cad.grip_offset_min_in:.3dot}}–{{cad.grip_offset_max_in:.3dot}} behind",
                    "the bore axis",
                ],
            )
        )
    # At the outside face, or before the bore at the mating face (up): the
    # height and the ears' height.
    top = face + 70
    tall = _cad(values, "height_mm") * s
    groups["part-kept"].append(_rect(x0, top, wide, tall))
    _label(
        groups,
        x0 - 8,
        top + tall / 2 + 5,
        "OUTSIDE" if bored else "MATING",
        "end",
    )
    for side in (-1, 1):
        groups["holes"].append(
            _el(
                "circle",
                cx=bore + side * station,
                cy=top + tall - _cad(values, "ear_height_mm") * s,
                r=hole / 2,
            )
        )
    if bored:
        groups["hidden"] += [
            _line(bore - radius, top, bore - radius, top + tall),
            _line(bore + radius, top, bore + radius, top + tall),
        ]
    _vdim(
        groups,
        x0 + wide + 20,
        top,
        top + tall,
        "{{cad.height_min_in:.2dot}}–{{cad.height_max_in:.2dot}}",
        witness=(x0 + wide, x0 + wide),
    )
    text = [
        *_ear_text(values),
        "{{cad.ear_height_min_in:.3dot}}–{{cad.ear_height_max_in:.3dot}} up from BOTTOM",
    ]
    if not bored:
        text = ["drill exits: deburr", *text]
    items.append(
        (
            bore - station + hole / 2,
            top + tall - _cad(values, "ear_height_mm") * s,
            text,
        )
    )
    return _finish(groups, _callouts(groups, items, top + tall + 20, above=False))


def _pair(groups: Groups, values: dict, parameters: dict) -> Layout:
    """From above: the back on the fixed jaw, the front on a block between
    its screw heads, the bore on the split line; parallels underneath."""
    s = 6.0
    x0, y0 = 170.0, 110.0
    wide = _cad(values, "width_mm") * s
    split = y0 + _cad(values, "pair_back_depth_mm") * s
    face = split + _cad(values, "pair_front_depth_mm") * s
    groups["clamp"].append(_rect(x0 - 24, y0 - 22, wide + 48, 22))
    groups["part-kept"] += [
        _rect(x0, y0, wide, split - y0),
        _rect(x0, split, wide, face - split),
    ]
    bore = x0 + _cad(values, "bore_location_mm") * s
    radius = _cad(values, "bore_dia_in") * 25.4 * s / 2
    station = _cad(values, "ear_station_mm") * s
    head = _param(parameters, "screw_head_dia_mm") * s
    rise = _param(parameters, "screw_head_height_mm") * s
    shank = _cad(values, "ear_dia_in") * 25.4 * s * 0.8
    length = _param(parameters, "screw_length_mm") * s
    for side in (-1, 1):
        x = bore + side * station
        groups["hidden"].append(_rect(x - shank / 2, face - length, shank, length))
        groups["part-rest"].append(_rect(x - head / 2, face, head, rise))
    # The block between the heads, drawn short to a break line (it is
    # spacer_block_length_mm across the jaws), then the moving jaw.
    block = _param(parameters, "spacer_block_width_mm") * s
    stub = 70.0
    a, b = bore - block / 2, bore + block / 2
    mid = face + stub / 2
    groups["fixture-support"] += [
        _path(
            [
                (a, face),
                (b, face),
                (b, mid - 4),
                *_zigzag(b, mid - 4, a, mid - 4),
                (a, mid - 4),
            ]
        ),
        _path(
            [
                (a, mid + 4),
                *_zigzag(a, mid + 4, b, mid + 4),
                (b, mid + 4),
                (b, face + stub),
                (a, face + stub),
            ]
        ),
    ]
    groups["clamp"].append(_rect(x0 - 24, face + stub, wide + 48, 22))
    # Parallels under the pair: along the front against the block, and
    # along the back against the fixed jaw, stopped short of the bore when
    # the plan stops it.
    thick = _param(parameters, "parallel_thickness_mm") * s
    stopped = "back_parallel_end_mm" in parameters
    end = (
        bore - _param(parameters, "back_parallel_end_mm") * s
        if stopped
        else x0 + wide + 16
    )
    groups["fixture-support"] += [
        _rect(x0 - 16, face - thick, wide + 32, thick),
        _rect(x0 - 16, y0, end - x0 + 16, thick),
    ]
    groups["part-removed"].append(_el("circle", cx=bore, cy=split, r=radius))
    # The end mill to scale at the helix's +X start, on the bore's wall;
    # it climbs (G3, counterclockwise from above).
    cutter = _param(parameters, "face_cutter_dia_mm") * s / 2
    groups["cutter"].append(
        _el("circle", cx=bore + radius - cutter, cy=split, r=cutter)
    )
    path = radius - cutter
    start, finish = math.radians(30), math.radians(150)
    groups["arrow"].append(
        _el(
            "path",
            d=f"M{bore + path * math.cos(start):.1f} {split - path * math.sin(start):.1f} "
            f"A{path:.1f} {path:.1f} 0 0 0 "
            f"{bore + path * math.cos(finish):.1f} {split - path * math.sin(finish):.1f}",
            fill="none",
        )
    )
    groups["centre-line"] += [
        _line(bore, y0 - 34, bore, face + 10),
        _line(x0 - 30, split, x0 + wide + 30, split),
    ]
    _label(groups, x0 - 20, (y0 + split) / 2 + 5, "BACK", "end")
    _label(groups, x0 - 20, (split + face) / 2 + 5, "FRONT", "end")
    _datum_label(groups, x0 + wide + 34, split + 5, "Y0: split line", "start")
    _datum_label(groups, x0 - 6, y0 - 46, "X0: near sides", "end")
    groups["datum"].append(_line(x0, y0 - 40, x0, face + 10))
    _label(groups, x0 + wide + 28, y0 - 6, "fixed jaw", "start")
    _label(groups, x0 + wide + 28, face + stub + 16, "moving jaw", "start")
    _vdim(
        groups,
        x0 + wide + 20,
        y0,
        split,
        "{{cad.pair_back_depth_min_in:.3dot}}–{{cad.pair_back_depth_max_in:.3dot}}",
        witness=(x0 + wide, x0 + wide),
        place=DimText.ALONG_LEFT,
    )
    _vdim(
        groups,
        x0 + wide + 20,
        split,
        face,
        "{{cad.pair_front_depth_min_in:.3dot}}–{{cad.pair_front_depth_max_in:.3dot}}",
        witness=(x0 + wide, x0 + wide),
        place=DimText.ALONG_LEFT,
    )
    _dimension(
        groups,
        x0,
        bore,
        y0 - 30,
        y0,
        "{{cad.bore_location_min_in:.3dot}}–{{cad.bore_location_max_in:.3dot}}",
    )
    items = []
    if stopped:
        items.append(
            (
                end,
                y0 + thick,
                [
                    "parallel under the back",
                    "ends {{process.back_parallel_end_mm:in.3dot}} from the axis",
                ],
            )
        )
    items += [
        (
            bore - radius * 0.7,
            split + radius * 0.7,
            [
                f"interpolate {_BORE_REF}",
                "through, on the split line;",
                *_BORE_FIT,
            ],
        ),
        (
            bore + block / 2,
            face + stub / 2,
            [
                "block between the heads,",
                "{{cad.block_head_clear_in:.3dot}} clear each side",
            ],
        ),
    ]
    _label(groups, x0 + wide + 22, face + 14, "parallel under the front,", "start")
    _label(groups, x0 + wide + 22, face + 30, "against the block", "start")
    return _finish(groups, _callouts(groups, items, face + stub + 30, above=False))


def _clamp_half(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    step = root.attrib.pop("data-step", None)
    up = root.attrib.pop("data-up", None)
    work = root.attrib.pop("data-work", None)
    end = root.attrib.pop("data-end", None)
    bored = root.attrib.pop("data-bored", "yes")
    stop = root.attrib.pop("data-stop", None)
    if stop not in (None, *_STOPS):
        raise CadError(
            f"clamp-half: data-stop must be one of {', '.join(_STOPS)}, not {stop!r}"
        )
    if stop is not None and step != "half":
        raise CadError("clamp-half: data-stop goes with the half step (the vise holds)")
    if step not in _TITLES:
        raise CadError(
            f"clamp-half: data-step must be one of {', '.join(_TITLES)}, not {step!r}"
        )
    if bored not in ("yes", "no"):
        raise CadError(f"clamp-half: data-bored must be yes or no, not {bored!r}")
    if bored == "no" and step != "inspect":
        raise CadError("clamp-half: data-bored goes with the inspect step")
    groups = _groups(root)
    title = _TITLES[step]
    if bored == "no":
        title = "Half before the bore, down its axis and at its mating face"
    _title(groups, 40, 24, title)
    if step == "saw":
        return _saw(groups, parameters)
    if step == "inspect":
        return _inspect(groups, values, bored == "yes")
    if step == "pair":
        return _pair(groups, values, parameters)
    if up not in _HALF:
        raise CadError(
            f"clamp-half: the half step needs data-up ({', '.join(_HALF)}), not {up!r}"
        )
    return _half(groups, values, parameters, up, work, end, stop)


CLAMP_LAYOUTS = {"clamp-half": _clamp_half}
