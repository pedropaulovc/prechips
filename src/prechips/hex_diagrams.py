"""Hex-block setup pictures for the ``hex-block`` template.

``data-step`` picks the picture. ``saw``: the blank on the bar. ``upright``:
the block standing on parallels between the vise jaws, seen along the jaws,
``data-end`` (``bottom`` or ``top``) naming the end that is up and
``data-work`` (``drill`` or ``tap``) what is done to its hole. ``cross``: the
block lying corner down for the cross bore, seen from its end and from above.
``inspect``: the finished block, seen along its cross bore.

Sizes come from the adapter (block, holes, the corner-down seat) and from
authored holding parameters (parallels, jaw height). Jaws, parallels, drill,
tap, wrench and centre are schematic symbols.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree

from prechips.cad import CadError
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

_TITLES = {
    "saw": "Side view, bar end at the left",
    "upright": "Looking along the jaws: part upright on parallels",
    "cross": "Corner down for the cross bore: end view, and plan",
    "inspect": "Finished part, looking along the cross bore",
    "surfaces": "Finished part and its surfaces, looking along the cross bore",
}
_ENDS = ("bottom", "top")
_WORK = ("drill", "tap")
_JAW = 46.0  # schematic jaw body width, px
_S = 4.5  # px per mm in the vise views


def _band_mm(values: dict, key: str) -> tuple[float, float]:
    band = values.get(f"{key}_band_mm")
    if not isinstance(band, list) or len(band) != 2:
        raise CadError(f"cad.{key}_band_mm: expected a band for the diagram")
    return float(band[0]), float(band[1])


def _jaws(
    groups: Groups, centre: float, bed: float, gap: float, jaw: float
) -> tuple[float, float]:
    """Vise bed and both jaws about ``centre``; returns the jaws' inner faces."""
    left, right = centre - gap / 2, centre + gap / 2
    groups["fixture-vise"].append(_rect(left - _JAW - 14, bed, gap + 2 * _JAW + 28, 16))
    groups["clamp"] += [
        _rect(left - _JAW, bed - jaw, _JAW, jaw),
        _rect(right, bed - jaw, _JAW, jaw),
    ]
    return left, right


def _saw(groups: Groups, values: dict, parameters: dict) -> Layout:
    high = _param(parameters, "blank_length_max_in")
    kerf = _param(parameters, "kerf_in")
    scale = 150.0  # px per inch: a short blank drawn large
    x, top = 60.0, 78.0
    height = _cad(values, "ac_mm") / 25.4 * scale
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
    _label(groups, (x1 + cut + 660) / 2, (top + bottom) / 2 + 5, "hex bar", "middle")
    _label(
        groups,
        x,
        bottom + 22,
        "Blank {{process.blank_length_min_in:.2dot}}–{{process.blank_length_max_in:.2dot}} long:"
        " {{cad.face_stock_min_in:.2dot}}–{{cad.face_stock_max_in:.2dot}} comes off"
        " the two ends together, to {{cad.block_height_min_in:.2dot}}–{{cad.block_height_max_in:.2dot}}.",
    )
    return _finish(groups, bottom + 28)


def _upright(
    groups: Groups, values: dict, parameters: dict, end: str, work: str
) -> Layout:
    af = _cad(values, "af_mm") * _S
    tall = _cad(values, "block_height_mm") * _S
    thick = _param(parameters, "parallel_thickness_mm") * _S
    rise = _param(parameters, "parallel_height_mm") * _S
    jaw = _param(parameters, "vise_jaw_height_mm") * _S
    centre, bed = 250.0, 70.0 + max(jaw, rise + tall) + 70
    left, right = _jaws(groups, centre, bed, af, jaw)
    seat = bed - rise
    groups["fixture-support"] += [
        _rect(left, seat, thick, rise),
        _rect(right - thick, seat, thick, rise),
    ]
    top = seat - tall
    groups["part-kept"].append(_rect(left, top, af, tall))
    groups["centre-line"].append(_line(centre, top - 62, centre, seat + 10))
    _datum_label(groups, left - 10, top - 8, "X0 Y0: hex axis", "end")
    # The hole worked from the end that is up: the rod tap's from the bottom
    # end, the thumb tap's from the top end, which runs into the cross bore.
    hole = "rod" if end == "bottom" else "thumb"
    drill = _cad(values, "tap_drill_dia_in") * 25.4 * _S
    depth = _band_mm(values, f"{hole}_drill_depth")[1] * _S
    groups["part-removed"].append(_rect(centre - drill / 2, top, drill, depth))
    bore = _cad(values, "bore_height_mm") * _S
    radius = _cad(values, "bore_dia_in") * 25.4 * _S / 2
    if end == "top":
        groups["holes"].append(_el("circle", cx=centre, cy=seat - bore, r=radius))
    tool_top = top - 48
    groups["cutter"].append(
        _rect(centre - drill / 2, tool_top, drill, 48 + depth * 0.3)
    )
    items = [
        (
            left + thick / 2,
            seat + rise / 2,
            ["parallels, one against", "each jaw, part on both"],
        ),
        (
            right + _JAW / 2,
            bed - jaw / 2,
            ["jaws on the two", "opposite flats"],
        ),
    ]
    name = "BOTTOM" if end == "bottom" else "TOP"
    _label(groups, right + 10, top + 4, f"{name} end up", "start")
    if work == "tap":
        # Wrench across the tap, the centre in its top hole.
        groups["part-rest"].append(_rect(centre - 70, tool_top - 9, 140, 9))
        groups["cutter"].append(
            _el(
                "path",
                d=f"M{centre - 9:.1f} {tool_top - 40:.1f} L{centre + 9:.1f} "
                f"{tool_top - 40:.1f} L{centre:.1f} {tool_top - 10:.1f} Z",
            )
        )
        text = [
            "tap by hand until its",
            f"point is {{{{cad.{hole}_tap_reach_min_in:.3dot}}}}–{{{{cad.{hole}_tap_reach_max_in:.3dot}}}} below this end",
        ]
        items.append((centre, top, text))
        _label(groups, centre + 76, tool_top - 1, "wrench, centre in its top", "start")
    else:
        text = [
            "tap drill",
            f"{{{{cad.{hole}_drill_depth_min_in:.2dot}}}}–{{{{cad.{hole}_drill_depth_max_in:.2dot}}}} deep",
        ]
        mark = top + depth
        if end == "top":
            text[1] += ", into the bore"
            # On the hole itself, in the wall above the bore.
            mark = top + (seat - bore - radius - top) * 0.75
        items.append((centre + drill / 2, mark, text))
    return _finish(groups, _callouts(groups, items, bed + 34, above=False))


def _hexagon(centre: float, middle: float, ac: float) -> list[tuple[float, float]]:
    """Corners up and down, about (centre, middle), page px."""
    return [
        (
            centre + ac / 2 * math.sin(math.radians(60 * index)),
            middle - ac / 2 * math.cos(math.radians(60 * index)),
        )
        for index in range(6)
    ]


def _cross(groups: Groups, values: dict, parameters: dict) -> Layout:
    scale = 7.0
    af, ac = _cad(values, "af_mm") * scale, _cad(values, "ac_mm") * scale
    thick = _param(parameters, "parallel_thickness_mm") * scale
    rise = _param(parameters, "parallel_height_mm") * scale
    jaw = _param(parameters, "vise_jaw_height_mm") * scale
    centre = 150.0
    # Only the top of the vise is drawn: the seat is at the parallels' tops.
    seat = 190.0
    bed = seat + min(rise, 70.0)
    left, right = centre - af / 2, centre + af / 2
    reach = min(jaw - rise, ac) + (bed - seat)
    groups["clamp"] += [
        _rect(left - _JAW, bed - reach, _JAW, reach),
        _rect(right, bed - reach, _JAW, reach),
    ]
    groups["fixture-support"] += [
        _rect(left, seat, thick, bed - seat),
        _rect(right - thick, seat, thick, bed - seat),
    ]
    middle = seat - _cad(values, "cross_axis_height_mm") * scale
    points = _hexagon(centre, middle, ac)
    groups["part-kept"].append(
        _el("path", d="M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points) + " Z")
    )
    bore = _cad(values, "bore_dia_in") * 25.4 * scale
    groups["part-removed"].append(_rect(centre - bore / 2, middle - ac / 2, bore, ac))
    groups["cutter"].append(_rect(centre - bore / 2, middle - ac / 2 - 46, bore, 40))
    groups["centre-line"].append(_line(centre, middle - ac / 2 - 60, centre, bed + 6))
    _datum_label(
        groups, centre + bore / 2 + 6, middle - ac / 2 - 30, "Y0: hex axis", "start"
    )
    items = [
        (
            left + thick,
            seat,
            [
                "lower flats on the parallels'",
                "edges, corner {{cad.cross_corner_drop_mm:in.3dot}} below",
            ],
        ),
        (
            right,
            middle,
            [
                "jaws on the upright",
                "flats, {{cad.flat_width_mm:in.2dot}} tall",
            ],
        ),
    ]
    # Plan: the block along the jaws, bottom end at the left; the parallels
    # stop short of the bore.
    s = 9.0
    x0, y0 = 400.0, middle - af * s / scale / 2
    tall = _cad(values, "block_height_mm") * s
    wide = _cad(values, "af_mm") * s
    end = _param(parameters, "cross_parallel_end_mm") * s
    plate = _param(parameters, "parallel_thickness_mm") * s
    station = _cad(values, "bore_height_mm") * s
    groups["clamp"] += [
        _rect(x0 - 30, y0 - 22, tall + 60, 22),
        _rect(x0 - 30, y0 + wide, tall + 60, 22),
    ]
    groups["part-kept"].append(_rect(x0, y0, tall, wide))
    for y in (y0, y0 + wide - plate):
        groups["fixture-support"].append(_rect(x0 - 30, y, 30 + end, plate))
    groups["part-removed"].append(
        _el("circle", cx=x0 + station, cy=y0 + wide / 2, r=bore / scale * s / 2)
    )
    groups["datum"].append(_line(x0, y0 - 30, x0, y0 + wide + 30))
    _datum_label(groups, x0 + 5, y0 + wide + 42, "X0: bottom end", "start")
    _dimension(
        groups,
        x0,
        x0 + station,
        y0 - 44,
        y0 + wide / 2,
        "{{cad.bore_height_min_in:.2dot}}–{{cad.bore_height_max_in:.2dot}}",
    )
    items += [
        (
            x0 + end,
            y0 + plate / 2,
            [
                "parallels end {{process.cross_parallel_end_mm:in.3dot}} in:",
                "drill exits into air",
            ],
        ),
    ]
    low = max(bed + 30, y0 + wide + 78)
    return _finish(groups, _callouts(groups, items, low, above=False))


def _surfaces(
    groups: Groups, x0: float, low: float, tall: float, marks: list[tuple]
) -> Layout:
    """The finished view with its surfaces named and no sizes, for a step
    that treats every surface (a finish, a wash)."""
    bore, hole = marks
    items = [
        (x0, low - 12, ["both ends"]),
        (x0 + tall * 0.3, low, ["all six flats"]),
        (*bore, ["cross bore,", "inside too"]),
        (*hole, ["both tapped holes,", "inside too"]),
    ]
    return _finish(groups, _callouts(groups, items, low + 30, above=False))


def _inspect(groups: Groups, values: dict, step: str) -> Layout:
    scale = 15.0
    tall = _cad(values, "block_height_mm") * scale
    af = _cad(values, "af_mm") * scale
    x0, top = 130.0, 120.0
    low = top + af
    groups["part-kept"].append(_rect(x0, top, tall, af))
    middle = top + af / 2
    groups["centre-line"].append(_line(x0 - 16, middle, x0 + tall + 16, middle))
    station = x0 + _cad(values, "bore_height_mm") * scale
    radius = _cad(values, "bore_dia_in") * 25.4 * scale / 2
    drill = _cad(values, "tap_drill_dia_in") * 25.4 * scale
    rod = _band_mm(values, "rod_drill_depth")[1] * scale
    threads = _band_mm(values, "rod_thread_depth")[1] * scale
    groups["hidden"] += [
        _rect(x0, middle - drill / 2, rod, drill),
        # The thumb hole ends where it breaks into the bore.
        _rect(
            station + radius, middle - drill / 2, x0 + tall - station - radius, drill
        ),
    ]
    groups["part-threads"].append(_rect(x0, middle - drill / 2 - 2, threads, drill + 4))
    groups["holes"].append(_el("circle", cx=station, cy=middle, r=radius))
    _label(groups, x0 - 8, top - 8, "BOTTOM", "end")
    _label(groups, x0 + tall + 8, top - 8, "TOP", "start")
    if step == "surfaces":
        marks = [
            (station, middle + radius),
            ((station + radius + x0 + tall) / 2, middle + drill / 2),
        ]
        return _surfaces(groups, x0, low, tall, marks)
    _dimension(
        groups,
        x0,
        x0 + tall,
        top - 44,
        top,
        "{{cad.block_height_min_in:.2dot}}–{{cad.block_height_max_in:.2dot}}",
    )
    _dimension(
        groups,
        x0,
        station,
        top - 20,
        top,
        "{{cad.bore_height_min_in:.2dot}}–{{cad.bore_height_max_in:.2dot}}",
    )
    items = [
        (
            x0 + 14,
            low,
            [
                "axes {{cad.tap_location_min_in:.2dot}}–{{cad.tap_location_max_in:.2dot}} from this",
                "flat (the one parallel",
                "to the bore)",
            ],
        ),
        (
            x0 + threads,
            middle + drill / 2 + 2,
            [
                "{{cad.thread}}, full thread",
                "{{cad.rod_thread_depth_min_in:.2dot}}–{{cad.rod_thread_depth_max_in:.2dot}} deep",
            ],
        ),
        (
            station,
            middle + radius,
            [
                "bore Ø{{cad.bore_dia_min_in:.3dot}}–{{cad.bore_dia_max_in:.3dot}}",
                "through the corners",
            ],
        ),
        (
            (station + radius + x0 + tall) / 2,
            middle + drill / 2,
            [
                "{{cad.thread}}",
                "into the bore",
            ],
        ),
    ]
    return _finish(groups, _callouts(groups, items, low + 30, above=False))


def _hex_block(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    step = root.attrib.pop("data-step", None)
    end = root.attrib.pop("data-end", None)
    work = root.attrib.pop("data-work", None)
    if step not in _TITLES:
        raise CadError(
            f"hex-block: data-step must be one of {', '.join(_TITLES)}, not {step!r}"
        )
    groups = _groups(root)
    _title(groups, 40, 24, _TITLES[step])
    if step == "saw":
        return _saw(groups, values, parameters)
    if step == "cross":
        return _cross(groups, values, parameters)
    if step in ("inspect", "surfaces"):
        return _inspect(groups, values, step)
    if end not in _ENDS or work not in _WORK:
        raise CadError(
            "hex-block: the upright step needs data-end (bottom or top) and "
            "data-work (drill or tap)"
        )
    return _upright(groups, values, parameters, end, work)


HEX_LAYOUTS = {"hex-block": _hex_block}
