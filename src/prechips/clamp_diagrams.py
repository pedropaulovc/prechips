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

A lying ``half`` draws the near side (X0) at the left; ``data-x0="right"``
draws it at the right, stations measured leftward, for holds that put the
near side at the operator's right.

``pair``: the two halves screwed together for the bore, from above: the
back's outside face on the fixed jaw, a block between the screw heads on the
front's, parallels clear of the bore. ``inspect``: the finished half, seen
along the bore and at its outside face; ``data-bored="no"`` draws it before
the bore, at the depth it is bored at and at its mating face with the ears'
drill exits.

Sizes come from the adapter (envelope, bore, ears, the pair) and from
authored holding parameters (parallels, jaw height, block, screws). Jaws,
parallels, blocks, cutters, taps and screws are schematic symbols.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _rect
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
_JAW = 40.0  # schematic jaw body, px
_S = 6.0  # px per mm
_REMOVED = 7.0  # px: the layer a face takes off, schematic


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


def _half(
    groups: Groups,
    values: dict,
    parameters: dict,
    up: str,
    work: str,
    end: str | None,
    mirror: bool,
) -> Layout:
    """One half in the vise, seen along the jaws, with a plan from above
    for the lying holds."""
    if mirror and up == "end":
        raise CadError("clamp-half: data-x0 goes with a lying hold, not data-up end")
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
        grip = ["jaws on two", "sawn sides"]
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
    # To scale above the vise bed; only the top of the vise is drawn when
    # the parallels are tall, cut off below the seat.
    bed = 120.0 + max(jaw, rise + tall * s)
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
        groups["cutter"].append(_rect(centre - 30, top - _REMOVED - 48, 60, 42))
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
        items.append((centre + 30, top - _REMOVED / 2, text))
    if up == "outside":
        # An ear hole through the depth, at its height from the fixed jaw.
        hole = _cad(values, "ear_dia_in") * 25.4 * s
        middle = left + _cad(values, "ear_height_mm") * s
        groups["hidden"].append(_rect(middle - hole / 2, top, hole, tall * s))
        if work == "tap":
            tool = top - 50
            groups["cutter"].append(
                _rect(middle - hole / 2, tool, hole, 50 + tall * s / 3)
            )
            groups["part-rest"].append(_rect(middle - 50, tool - 9, 100, 9))
            text = ["{{cad.ear_thread}} by hand,", "through, centre on top"]
        else:
            text = _ear_text(values, drill=True)
        items.append((middle - hole / 2, top + tall * s / 2, text))
    low = _callouts(groups, items, cut + 24, above=False)
    if up == "end":
        return _finish(groups, low)
    return _plan(groups, values, up, work, across, low, mirror)


def _plan(
    groups: Groups,
    values: dict,
    up: str,
    work: str,
    across: float,
    low: float,
    mirror: bool,
) -> Layout:
    """From above: the width along the jaws, the near side at the left, or at
    the right when ``mirror``, the stations measured from it."""
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
        return _finish(groups, y0 + deep + 40)
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
    return _finish(groups, y0 + deep + 40)


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
    _label(groups, x0 - 8, (y0 + face) / 2 + 5, "NEAR SIDE", "end")
    _dimension(
        groups,
        x0,
        x0 + wide,
        y0 - (48 if bored else 56),
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
                bore + station + hole / 2,
                face - deep / 2,
                [
                    "2X {{cad.ear_station_min_in:.3dot}}–{{cad.ear_station_max_in:.3dot}}",
                    "from the bore axis",
                ],
            ),
        ]
    else:
        # No bore yet: the ears from the near side, where the program put them.
        for x, y, key in (
            (bore - station, y0 - 16, "ear_near_x"),
            (bore + station, y0 - 34, "ear_far_x"),
        ):
            _dimension(groups, x0, x, y, y0, f"{{{{cad.{key}_in:.3dot}}}}")
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
        "{{cad.ear_height_min_in:.3dot}}–{{cad.ear_height_max_in:.3dot}} up",
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
    # The block between the heads, shortened, then the moving jaw.
    block = _param(parameters, "spacer_block_width_mm") * s
    stub = 70.0
    groups["fixture-support"].append(_rect(bore - block / 2, face, block, stub))
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
    groups["cutter"].append(_el("circle", cx=bore + radius - 22, cy=split, r=22))
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
    x0 = root.attrib.pop("data-x0", "left")
    bored = root.attrib.pop("data-bored", "yes")
    if step not in _TITLES:
        raise CadError(
            f"clamp-half: data-step must be one of {', '.join(_TITLES)}, not {step!r}"
        )
    if x0 not in ("left", "right"):
        raise CadError(f"clamp-half: data-x0 must be left or right, not {x0!r}")
    if x0 == "right" and step != "half":
        raise CadError("clamp-half: data-x0 goes with the half step")
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
    return _half(groups, values, parameters, up, work, end, x0 == "right")


CLAMP_LAYOUTS = {"clamp-half": _clamp_half}
