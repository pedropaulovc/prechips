"""Riser (TL-24) setup pictures for the ``jig-riser-*`` diagram templates.

Drawn from the ``harmonic_riser`` adapter values and the plan's authored
holding parameters, in the conventions of :mod:`prechips.jig_diagrams`: top
views look down from the operator's side, +X right from ZERO END, +Y toward
the operator from ZERO EDGE at the back (fixed) jaw. A skim too thin to see at
scale is drawn a few pixels deep; straps, jaws, parallels and cutters are
schematic symbols placed by the holding parameters.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _cad, _el, _fmt, _line, _rect
from prechips.jig_diagrams import (
    JAW,
    _blank,
    _cutter,
    _datum_label,
    _finish,
    _groups,
    _inch,
    _label,
    _param,
    _param_in,
    _title,
    _vise,
)
from prechips.shaft_diagrams import _callouts, _dimension

_THIN = 4.0  # least drawn depth of a skim, px


def _points(values: dict, key: str, count: int) -> list[tuple[str, float, float]]:
    points = values.get(key)
    if not isinstance(points, list) or len(points) != count:
        raise CadError(f"cad.{key}: expected {count} tagged points for the diagram")
    result = []
    for point in points:
        if not isinstance(point, list) or len(point) != 3:
            raise CadError(f"cad.{key}: expected [tag, X, Y] points")
        tag, x, y = point
        result.append((str(tag), float(x), float(y)))
    return result


def _vdim(
    groups: dict[str, list[Element]],
    x: float,
    y0: float,
    y1: float,
    edge: float,
    text: str,
) -> None:
    """Vertical dimension at ``x`` with extension lines from ``edge``; text right."""
    beyond = x + 4 if x > edge else x - 4
    groups["dims"] += [
        _line(edge, y0, beyond, y0),
        _line(edge, y1, beyond, y1),
        _line(x, y0, x, y1, marker_start="url(#arr)", marker_end="url(#arr)"),
    ]
    _label(groups, x + 6, (y0 + y1) / 2 + 5, text)


def _strap(
    groups: dict[str, list[Element]], x0: float, x1: float, top: float, bottom: float
) -> None:
    """A strap across the bar, drawn over it."""
    groups["tool"].append(_rect(x0, top - 8, x1 - x0, bottom - top + 16))


def _face(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 2: top faced on the bare table in two strap stages, Z0 the table."""
    blank = _param(parameters, "blank_length_in")
    width = _param(parameters, "blank_width_in")
    stock = _param(parameters, "blank_thickness_in")
    thickness = _cad(values, "thickness_in")
    toe = _param(parameters, "strap_toe_in")
    clear = _param(parameters, "strap_clear_in")
    overlap = _param(parameters, "face_overlap_in")
    inboard = (
        _param(parameters, "strap_b_left_x_in"),
        _param(parameters, "strap_b_right_x_in"),
    )
    strap = _param(parameters, "strap_width_in")
    cutter = _param_in(parameters, "face_cutter_dia_mm")
    a0, a1 = toe + clear, blank - toe - clear
    b0, b1 = a0 + overlap, a1 - overlap
    if not (
        b0 + clear < inboard[0] - strap / 2 and inboard[1] + strap / 2 < b1 - clear
    ):
        raise CadError("process.strap_b_*_x_in: an inboard strap sits in an end cut")
    x0 = 60.0
    s = min(44.0, 600 / blank)
    h = width * s
    groups = _groups(root)

    def bar(top: float) -> float:
        groups["arriving"].append(_rect(x0, top, blank * s, h))
        return top + h

    def faced(top: float, start: float, end: float) -> None:
        x, w = x0 + start * s, (end - start) * s
        groups["removed"].append(_rect(x, top, w, h))
        groups["active"].append(_rect(x, top, w, h, fill="none"))

    _title(groups, 20, 22, "A  Straps on both ends: face the middle")
    top = 44.0
    bottom = bar(top)
    faced(top, a0, a1)
    for start, end in ((0.0, toe), (blank - toe, blank)):
        _strap(groups, x0 + start * s, x0 + end * s, top, bottom)
    r = cutter / 2 * s
    cx = x0 + (a0 + cutter / 2) * s
    groups["tool"].append(_el("circle", cx=cx, cy=top + r, r=r))
    groups["arrows"].append(_line(cx + r + 4, top + r, cx + r + 56, top + r))
    end_y = _callouts(
        groups,
        [
            (x0 + toe / 2 * s, bottom + 8, ["strap"]),
            (cx, top + 2 * r, ["3/4 end mill, +X"]),
            (x0 + a1 * s, bottom, [f"cutter edge ≥{_inch(clear, 1)} off each toe"]),
        ],
        bottom + 10,
        above=False,
        gap=10,
    )

    top = end_y + 30
    _title(
        groups,
        20,
        top - 14,
        "B  Straps inboard on faced metal, end straps off: face both ends",
    )
    bottom = bar(top)
    groups["kept"].append(_rect(x0 + b0 * s, top, (b1 - b0) * s, h))
    faced(top, 0.0, b0)
    faced(top, b1, blank)
    for x in inboard:
        _strap(groups, x0 + (x - strap / 2) * s, x0 + (x + strap / 2) * s, top, bottom)
    end_y = _callouts(
        groups,
        [
            (x0 + b0 / 2 * s, bottom, [f"overlaps A ≥{_inch(overlap, 2)}"]),
            (x0 + inboard[0] * s, bottom + 8, ["strap"]),
            (x0 + inboard[1] * s, bottom + 8, ["strap"]),
        ],
        bottom + 10,
        above=False,
        gap=10,
    )

    # Section across the width, larger scale: bar on the table, top skimmed.
    k = 120.0
    _title(groups, 20, end_y + 20, "Section across the bar, both stages")
    left, table = 200.0, end_y + 44 + stock * k
    groups["fixture"].append(_rect(left - 50, table, width * k + 100, 14))
    kept_top = table - thickness * k
    arriving_top = min(table - stock * k, kept_top - _THIN)
    groups["arriving"].append(
        _rect(left, arriving_top, width * k, table - arriving_top)
    )
    groups["removed"].append(
        _rect(left, arriving_top, width * k, kept_top - arriving_top)
    )
    groups["kept"].append(_rect(left, kept_top, width * k, table - kept_top))
    groups["active"].append(_line(left, kept_top, left + width * k, kept_top))
    _datum_label(groups, left - 54, table + 5, "Z0 table", "end")
    right = left + width * k
    _vdim(groups, right + 20, kept_top, table, right, "Z {{cad.thickness_in:.3dot}}")
    _label(groups, right + 96, arriving_top + 4, "skim, not to scale")
    return _finish(groups, table + 16)


def _edges(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 3: on edge on one 1 in parallel; end views of both holds."""
    width = _param(parameters, "blank_width_in")
    thickness = _cad(values, "thickness_in")
    finished = _cad(values, "width_in")
    cleanup = _param(parameters, "edge_cleanup_in")
    jaw_h = _param_in(parameters, "vise_jaw_height_mm")
    parallel_h = _param_in(parameters, "parallel_height_mm")
    parallel_t = _param_in(parameters, "parallel_thickness_mm")
    cutter = _param_in(parameters, "cutter_dia_mm")
    if width - cleanup <= finished:
        raise CadError("process.edge_cleanup_in: leaves nothing for the second edge")
    s = 60.0
    t = thickness * s
    jaw_w = 46.0
    groups = _groups(root)
    _title(
        groups,
        20,
        26,
        "End views from ZERO END; bar centred, about {{cad.blank_centred_overhang_in:.1f}} out each side",
    )

    def hold(
        cx: float, title: str, arriving: float, kept: float, zero_down: bool
    ) -> tuple[float, float, float, float, float]:
        bed = 74 + (parallel_h + width) * s + 30
        jaw_top = bed - jaw_h * s
        fixed, moving = cx - t / 2, cx + t / 2
        groups["jaws"] += [
            _rect(fixed - jaw_w, jaw_top, jaw_w, bed - jaw_top),
            _rect(moving, jaw_top, jaw_w, bed - jaw_top),
        ]
        groups["fixture"] += [
            _rect(fixed - jaw_w - 12, bed, 2 * jaw_w + t + 24, 10),
            _rect(fixed, bed - parallel_h * s, parallel_t * s, parallel_h * s),
        ]
        seat = bed - parallel_h * s
        top_a = seat - arriving * s
        top_k = max(seat - kept * s, top_a + _THIN)
        groups["arriving"].append(_rect(fixed, top_a, t, seat - top_a))
        groups["removed"].append(_rect(fixed, top_a, t, top_k - top_a))
        groups["kept"].append(_rect(fixed, top_k, t, seat - top_k))
        groups["active"].append(_line(fixed - 4, top_k, moving + 4, top_k))
        cut = cutter * s
        groups["tool"].append(_rect(cx - cut / 2, top_a - 6 - cut, cut, cut))
        _title(groups, cx - 150, 52, title)
        if zero_down:
            groups["datum"].append(
                _line(fixed - 2, seat, moving + 2, seat, stroke_width=3)
            )
        return seat, top_k, jaw_top, fixed, moving

    seat, top_k, jaw_top, fixed, moving = hold(
        180, "1  Clean up the top edge", width, width - cleanup, False
    )
    end_y = _callouts(
        groups,
        [
            (fixed - jaw_w, jaw_top + 30, ["fixed jaw:", "as-bought face"]),
            (fixed + parallel_t * s / 2, seat + 24, ["1 in parallel"]),
            (moving + 4, top_k + 6, ["→ ZERO EDGE"]),
            (moving + jaw_w, jaw_top + 30, ["moving jaw:", "faced top"]),
        ],
        seat + 70,
        above=False,
        gap=10,
    )
    seat, top_k, jaw_top, fixed, moving = hold(
        540, "2  Turned end-for-end, ZERO EDGE down", width - cleanup, finished, True
    )
    _vdim(groups, moving + 60, top_k, seat, moving, "{{cad.width_in:.3f}}")
    end_y = max(
        end_y,
        _callouts(
            groups,
            [
                (fixed + t / 2, seat, ["ZERO EDGE on the parallel"]),
                (moving + 4, top_k + 6, ["cut to width"]),
            ],
            seat + 70,
            above=False,
        ),
    )
    return _finish(groups, end_y + 8)


def _ends(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 4: flat on parallels; ZERO END and P1, then length and P2."""
    blank = _param(parameters, "blank_length_in")
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    stops = _points(values, "stop_points_in", 2)
    dia = _cad(values, "stop_dia_max_in")
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    over = _param(parameters, "overhang_in")
    parallel = _param_in(parameters, "parallel_thickness_mm")
    cutter = _param_in(parameters, "cutter_dia_mm")
    touch = _param(parameters, "y_touch_x_in")
    trim = (blank - length) / 2
    if trim < 0:
        raise CadError("process.blank_length_in: shorter than the finished length")
    x0 = 90.0
    s = min(44.0, (712 - x0) / (length + trim + cutter))
    radius = cutter / 2 * s
    h = width * s
    groups = _groups(root)

    def holes(back: float, active: str) -> None:
        r = max(dia / 2 * s, 2.5)
        for tag, x, y in stops:
            cx, cy = x0 + x * s, back + y * s
            groups["holes"].append(_el("circle", cx=cx, cy=cy, r=r))
            if tag == active:
                groups["active"].append(
                    _el("circle", cx=cx, cy=cy, r=r + 3, fill="none")
                )

    _title(
        groups,
        20,
        16,
        "1  Left end ~{{process.overhang_in:.1dot}} out left: ZERO END, then P1",
    )
    back = 58.0
    front = back + h
    left = x0 - trim * s
    jaw_left = left + over * s
    _vise(
        groups,
        jaw_left,
        jaw_left + jaw * s,
        back,
        front,
        parallel * s,
        "fixed jaw · ZERO EDGE",
        "moving jaw",
        labels_right=True,
    )
    _blank(groups, left, left + blank * s, x0, left + blank * s, back, front)
    holes(back, "P1")
    groups["datum"].append(_el("circle", cx=x0, cy=back, r=3.5))
    _datum_label(groups, x0 - 8, back - 4, "X0 Y0", "end")
    _cutter(groups, x0 - radius, radius, back, front + radius + 4, at_end=True)
    finder = x0 + touch * s
    groups["tool"].append(_el("circle", cx=finder, cy=back - 4, r=4))
    _datum_label(
        groups,
        finder - 8,
        back - JAW - 4,
        "Y0 touch ~X {{process.y_touch_x_in:g}}",
        "start",
    )
    p1 = stops[0]
    end_y = _callouts(
        groups,
        [
            (x0 - radius, front + 2 * radius + 4, ["end mill,", "feed toward you"]),
            (
                x0 + p1[1] * s,
                back + p1[2] * s,
                [f"P1 through: X {_inch(p1[1], 2)}, Y {_inch(p1[2], 2)}"],
            ),
        ],
        front + JAW + 20,
        above=False,
        gap=10,
    )

    _title(
        groups,
        20,
        end_y + 18,
        "2  Slid left, right end ~{{process.overhang_in:.1dot}} out right: length, then P2",
    )
    back = end_y + 42
    front = back + h
    finish = x0 + length * s
    right = finish + trim * s
    jaw_right = right - over * s
    _vise(groups, jaw_right - jaw * s, jaw_right, back, front, parallel * s, "", "")
    _blank(groups, x0, right, x0, finish, back, front)
    holes(back, "P2")
    groups["datum"] += [
        _line(x0, back, x0, front),
        _el("circle", cx=x0, cy=back, r=3.5),
    ]
    _datum_label(groups, x0 - 8, back - 4, "X0", "end")
    _label(groups, x0 - 8, (back + front) / 2 + 5, "ZERO END", "end")
    _cutter(groups, finish + radius, radius, front + radius + 4, back - 2, at_end=False)
    dim_y = front + JAW + 16
    _dimension(groups, x0, finish, dim_y, front, "{{cad.length_in:.2f}}")
    p2 = stops[1]
    end_y = _callouts(
        groups,
        [
            (
                x0 + p2[1] * s,
                back + p2[2] * s,
                [f"P2 through: X {_inch(p2[1], 2)}, Y {_inch(p2[2], 2)}"],
            ),
            (finish + radius, front + 2 * radius + 4, ["feed away, last X = L + D/2"]),
        ],
        dim_y + 6,
        above=False,
        gap=10,
    )
    return _finish(groups, end_y)


def _spots(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 5: the seven spotted holes, their vise holds and the countersink."""
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    thickness = _cad(values, "thickness_in")
    spots = _points(values, "spot_points_in", 7)
    stops = _points(values, "stop_points_in", 2)
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    parallel = _param_in(parameters, "parallel_thickness_mm")
    sizes = {
        "screw": _cad(values, "screw_dia_max_in"),
        "HUB": _cad(values, "hub_dia_max_in"),
        "clamp": _cad(values, "clamp_dia_max_in"),
        "stop": _cad(values, "stop_dia_max_in"),
    }
    csk = _cad(values, "csk_dia_in")
    x0 = 40.0
    s = min(46.0, 640 / length)
    groups = _groups(root)
    spans = (
        ("hold L", 0.0, jaw),
        ("hold C", (length - jaw) / 2, (length + jaw) / 2),
        ("hold R", length - jaw, length),
    )
    _title(
        groups,
        20,
        22,
        "Marked (carrier) face up, ZERO END left, ZERO EDGE at the fixed jaw",
    )
    top = 42.0
    for index, (name, a, b) in enumerate(spans):
        y = top + 14 * index
        groups["jaws"].append(_rect(x0 + a * s, y, (b - a) * s, 7))
        if index == 2:
            _label(groups, x0 + a * s - 4, y + 8, name, "end", font_size=12)
        else:
            _label(groups, x0 + b * s + 4, y + 8, name, font_size=12)
    back = top + 14 * len(spans) + 18
    front = back + width * s
    groups["kept"].append(_rect(x0, back, length * s, width * s))
    groups["hidden"] += [
        _rect(x0, back, length * s, parallel * s),
        _rect(x0, front - parallel * s, length * s, parallel * s),
    ]
    for _tag, x, y in stops:
        groups["holes"].append(
            _el("circle", cx=x0 + x * s, cy=back + y * s, r=sizes["stop"] / 2 * s)
        )
    items = []
    for tag, x, y in spots:
        size = sizes["screw"] if tag.startswith("R") else sizes.get(tag, sizes["clamp"])
        cx, cy, r = x0 + x * s, back + y * s, max(size / 2 * s, 2.5)
        groups["holes"].append(_el("circle", cx=cx, cy=cy, r=r))
        groups["active"].append(_el("circle", cx=cx, cy=cy, r=r + 3, fill="none"))
        items.append((cx, front, [tag]))
        groups["leaders"].append(_line(cx, cy + r + 3, cx, front))
    end_y = _callouts(groups, items, front + 6, above=False)
    groups["datum"].append(_el("circle", cx=x0, cy=back, r=3.5))
    _datum_label(groups, x0 - 4, back - 6, "X0 Y0", "start")

    # Section through an R hole, large scale: marks below, countersink on top.
    k = 260.0
    hole = sizes["screw"]
    half_angle = math.radians(_cad(values, "csk_angle_deg") / 2)
    depth = (csk - hole) / 2 / math.tan(half_angle) * k
    top_y = end_y + 58
    bottom_y = top_y + thickness * k
    cx = 360.0
    half = 0.55 * k
    _title(
        groups,
        20,
        top_y - 36,
        "Section through R1–R4 after turning over (marked face down)",
    )
    for side in (-1, 1):
        rim, bore, edge = (
            cx + side * csk / 2 * k,
            cx + side * hole / 2 * k,
            cx + side * half,
        )
        groups["kept"].append(
            _el(
                "path",
                d=(
                    f"M{_fmt(edge)} {_fmt(top_y)}H{_fmt(rim)}"
                    f"L{_fmt(bore)} {_fmt(top_y + depth)}"
                    f"V{_fmt(bottom_y)}H{_fmt(edge)}Z"
                ),
            )
        )
        groups["active"].append(_line(rim, top_y, bore, top_y + depth))
    _dimension(
        groups,
        cx - csk / 2 * k,
        cx + csk / 2 * k,
        top_y - 14,
        top_y,
        "Ø{{cad.csk_dia_in:.2dot}} × {{cad.csk_angle_deg:g}}°",
    )
    _label(groups, cx - half - 8, bottom_y - 2, "marked face", "end")
    _label(groups, cx - half - 8, top_y + 12, "countersink face", "end")
    return _finish(groups, bottom_y + 10)


RISER_LAYOUTS = {
    "jig-riser-face": _face,
    "jig-riser-edges": _edges,
    "jig-riser-ends": _ends,
    "jig-riser-spots": _spots,
}
