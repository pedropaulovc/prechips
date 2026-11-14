"""Setup pictures for the leadscrew kit rework (TL-VN-84).

``kit-*`` templates share the jig shell (:mod:`prechips.jig_diagrams`): bare
``<svg>`` roots, the same groups, legend and conventions. Lathe and
dividing-head views are side elevations with the work's free end to the
right; the vise view is a top view. Part sizes, stations and stick-outs follow
the adapter values and authored holding parameters; chucks, jaws and cutters
are schematic.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import (
    Element,
    Layout,
    _cad,
    _el,
    _fmt,
    _line,
    _rect,
)
from prechips.jig_diagrams import (
    _axes,
    _blank,
    _cutter,
    _datum_label,
    _finish,
    _groups,
    _label,
    _param,
    _title,
    _vise,
)
from prechips.shaft_diagrams import _callouts, _dimension

Groups = dict[str, list[Element]]


def _datum(groups: Groups, x: float, top: float, bottom: float) -> None:
    groups["datum"] += [_line(x, top, x, bottom), _el("circle", cx=x, cy=top, r=3.5)]


def _chuck(
    groups: Groups, face: float, axis: float, radius: float, depth: float, label: str
) -> None:
    """Schematic 3-jaw: two jaws on ``radius`` ending at ``face``, body behind."""
    groups["jaws"] += [
        _rect(face - depth, axis - radius - 22, depth, 22),
        _rect(face - depth, axis + radius, depth, 22),
    ]
    groups["fixture"].append(
        _rect(face - depth - 26, axis - radius - 40, 26, 2 * radius + 80)
    )
    _label(groups, face - depth - 13, axis + radius + 58, label, "middle")


# --- Leadscrew kit ------------------------------------------------------------


def _kit_receipt(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Kit receipt: the nut as supplied, side elevation, and its checks."""
    s = 12.0
    flange = _cad(values, "nut_flange_thickness_mm")
    body_len = _cad(values, "nut_length_mm") - flange
    spigot = _cad(values, "nut_spigot_length_mm")
    r_flange = _cad(values, "nut_flange_dia_mm") / 2
    r_body = _cad(values, "nut_body_dia_mm") / 2
    r_spigot = _cad(values, "nut_spigot_dia_mm") / 2
    axis = 130 + r_flange * s
    x_spigot = 220.0
    x_seat = x_spigot + spigot * s
    x_head = x_seat + flange * s
    x_end = x_head + body_len * s
    groups = _groups(root)
    _title(groups, 20, 24, "Feed nut as supplied: spigot left, flange, body right")
    groups["kept"] += [
        _rect(x_seat, axis - r_flange * s, flange * s, 2 * r_flange * s),
        _rect(x_head, axis - r_body * s, body_len * s, 2 * r_body * s),
    ]
    groups["arriving"].append(
        _rect(x_spigot, axis - r_spigot * s, spigot * s, 2 * r_spigot * s)
    )
    groups["hidden"] += [
        _line(
            x_spigot,
            axis - _cad(values, "major_radius_mm") * s,
            x_end,
            axis - _cad(values, "major_radius_mm") * s,
        ),
        _line(
            x_spigot,
            axis + _cad(values, "major_radius_mm") * s,
            x_end,
            axis + _cad(values, "major_radius_mm") * s,
        ),
    ]
    top = axis - r_flange * s
    _callouts(
        groups,
        [
            (
                x_seat + flange * s / 2,
                top,
                [
                    "flange Ø{{cad.nut_flange_dia_mm:g}}",
                    "× {{cad.nut_flange_thickness_mm:g}}, {{cad.csk_count:d}} holes",
                ],
            )
        ],
        top - 6,
        above=True,
    )
    end_y = _callouts(
        groups,
        [
            (
                x_spigot + spigot * s / 2,
                axis + r_spigot * s,
                ["spigot: faced off", "in the lathe"],
            ),
            (x_end - 20, axis + r_body * s, ["body Ø{{cad.nut_body_dia_mm:g}}"]),
        ],
        axis + r_flange * s + 6,
        above=False,
    )
    return _finish(groups, end_y)


def _kit_saw(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Saw: the piece kept from the NEAR END, the offcut beyond the mark."""
    stock = _cad(values, "stock_length_mm")
    piece = _cad(values, "saw_piece_mm")
    kerf = _param(parameters, "kerf_mm")
    s = 640 / stock
    x0, top = 40.0, 90.0
    bottom = top + 18
    cut = x0 + piece * s
    end = x0 + stock * s
    groups = _groups(root)
    _title(
        groups,
        20,
        24,
        "Screw on the bench, NEAR END (factory) at the left; not to scale across",
    )
    groups["kept"].append(_rect(x0, top, cut - x0, bottom - top))
    groups["removed"].append(_rect(cut, top, max(kerf * s, 3), bottom - top))
    groups["other"].append(
        _el(
            "path",
            d=f"M{_fmt(cut + max(kerf * s, 3))} {_fmt(top)}H{_fmt(end)}V{_fmt(bottom)}H{_fmt(cut + max(kerf * s, 3))}Z",
        )
    )
    _dimension(groups, x0, cut, top - 20, top, "≈{{cad.saw_piece_mm:.1f}} piece")
    _dimension(
        groups,
        cut,
        end,
        bottom + 24,
        bottom,
        "mark {{cad.saw_mark_from_far_mm:.1f}} from the far end",
    )
    _datum_label(groups, x0, top - 40, "NEAR END", "start")
    _label(groups, end, top - 8, "far end (offcut)", "end")
    end_y = _callouts(
        groups,
        [(cut + 1, bottom, ["hacksaw on the offcut side", "of the mark"])],
        bottom + 40,
        above=False,
    )
    return _finish(groups, end_y)


def _kit_length(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Cut end to length: screw along X in the vise, cut end just past the right jaw."""
    piece = _cad(values, "saw_piece_mm")
    length = _cad(values, "length_mm")
    jaw = _param(parameters, "vise_jaw_width_mm")
    over = _param(parameters, "cut_overhang_mm")
    cutter = _param(parameters, "cutter_dia_mm")
    s = 600 / (piece + cutter + 20)
    radius = cutter / 2 * s
    near = 40.0
    cut_arrived = near + piece * s
    cut = near + length * s
    right = cut_arrived - over * s
    left = right - jaw * s
    back = 70.0
    front = back + 18
    groups = _groups(root)
    _title(
        groups, 20, 24, "Top view: NEAR END left, cut end just past the right jaw side"
    )
    _vise(
        groups,
        left,
        right,
        back,
        front,
        5,
        "fixed jaw",
        "moving jaw",
        labels_right=True,
    )
    _blank(groups, near, cut_arrived, near, cut, back, front)
    _datum(groups, near, back - 6, front + 6)
    _datum_label(groups, near + 4, back - 12, "X0 NEAR END", "start")
    _cutter(groups, cut + radius, radius, front + radius + 26, back - 4, at_end=False)
    _dimension(
        groups,
        near,
        cut,
        front + 48,
        front,
        "{{cad.length_min_mm:.1f}}–{{cad.length_max_mm:.1f}}",
    )
    end_y = _callouts(
        groups,
        [
            (
                cut + radius,
                front + 2 * radius + 26,
                ["end mill, feed away;", "last pass X = L + D/2"],
            )
        ],
        front + 60,
        above=False,
    )
    _axes(groups, 40, end_y + 12)
    return _finish(groups, end_y + 48)


def _kit_flats(
    values: dict, parameters: dict, root: ElementTree.Element, far: bool
) -> Layout:
    """Dividing-head flats: side view out of the chuck, end view of the clocking."""
    stickout = _param(parameters, "far_stickout_mm" if far else "near_stickout_mm")
    cutter = _param(parameters, "flat_cutter_dia_mm")
    major = _cad(values, "major_dia_mm")
    depth = _cad(values, "flat_depth_mm")
    s = 360 / stickout
    r = major / 2 * s
    axis = 240 + r
    jaw_face = 120.0
    free = jaw_face + stickout * s
    groups = _groups(root)
    title = "cut end" if far else "NEAR END"
    _title(
        groups,
        20,
        24,
        f"Side view: {title} out of the BS-0 chuck; flats on top, 0° then "
        "{{cad.clock_deg:g}}°",
    )
    _chuck(groups, jaw_face, axis, r, 40, "BS-0 3-jaw")
    _datum(groups, free, axis - r - 26, axis + r + 6)
    _datum_label(groups, free + 6, axis - r - 30, f"X0 {title}", "start")

    spans: list[tuple[float, float]] = []

    def flat(from_end_start: float, from_end_stop: float) -> float:
        x0, x1 = free - from_end_stop * s, free - from_end_start * s
        spans.append((x0, x1))
        groups["removed"].append(_rect(x0, axis - r, x1 - x0, depth * s))
        groups["active"].append(
            _line(x0, axis - r + depth * s, x1, axis - r + depth * s)
        )
        return (x0 + x1) / 2

    items = []
    if far:
        length = _cad(values, "length_mm")
        start = length - _cad(values, "far_kp08_station_mm")
        centre = flat(start - _cad(values, "flat_length_mm"), start)
        hw = flat(0.0, length - _cad(values, "handwheel_station_mm"))
        items += [
            (
                centre,
                axis - r,
                ["KP08 flats", "X −(L − {{cad.far_kp08_centre_mm:.1f}})"],
            ),
            (
                hw,
                axis - r,
                [
                    "handwheel flat",
                    "X −(L − {{cad.handwheel_centre_mm:.1f}}),",
                    "then X 0",
                ],
            ),
        ]
        cutter_x = centre
    else:
        start = _cad(values, "near_kp08_station_mm")
        centre = flat(start, start + _cad(values, "flat_length_mm"))
        items.append(
            (
                centre,
                axis - r,
                ["KP08 flats", "X −{{cad.near_kp08_centre_mm:.2f}}"],
            )
        )
        cutter_x = centre
    # The thread fill stops at each flat's floor, so the removed hatch shows.
    floor = axis - r + depth * s
    groups["threads"].append(
        _rect(jaw_face - 40, floor, free - jaw_face + 40, 2 * r - depth * s)
    )
    edge = jaw_face - 40
    for x0, x1 in sorted(spans):
        if x0 > edge:
            groups["threads"].append(_rect(edge, axis - r, x0 - edge, depth * s))
        edge = max(edge, x1)
    if free > edge:
        groups["threads"].append(_rect(edge, axis - r, free - edge, depth * s))
    # Cutter drawn lifted clear of the work so the flat it cuts stays visible.
    left = cutter_x - cutter / 2 * s
    groups["tool"].append(_rect(left, axis - r - 70, cutter * s, 58))
    groups["arrows"].append(
        _line(cutter_x, axis - r - 12, cutter_x, axis - r + depth * s - 2)
    )
    label_y = _callouts(groups, items, axis - r - 80, above=True)
    if label_y < 40:
        raise CadError("flat labels overrun the picture top")
    _label(groups, left - 6, axis - r - 50, "the end mill crosses", "end")
    _label(groups, left - 6, axis - r - 34, "the screw (table Y)", "end")
    key = "far_stickout_mm" if far else "near_stickout_mm"
    _dimension(
        groups,
        jaw_face,
        free,
        axis + r + 40,
        axis + r,
        f"stick-out ≈{{{{process.{key}:g}}}}",
    )

    # End view of the free end: the 0° flat up, the 120° flat after indexing.
    cx, cy, er = 600.0, axis + r + 130, 56.0
    groups["kept"].append(_el("circle", cx=cx, cy=cy, r=er))
    floor = _cad(values, "flat_floor_mm") / (major / 2) * er
    clock = _cad(values, "clock_deg")
    for angle, name in ((0.0, "0°"), (clock, "{{cad.clock_deg:g}}°")):
        a = math.radians(90 + angle)
        nx, ny = math.cos(a), -math.sin(a)
        half = math.sqrt(er * er - floor * floor)
        p0 = (cx + nx * floor - ny * half, cy + ny * floor + nx * half)
        p1 = (cx + nx * floor + ny * half, cy + ny * floor - nx * half)
        groups["removed"].append(
            _el(
                "path",
                d=f"M{_fmt(p0[0])} {_fmt(p0[1])}A{_fmt(er)} {_fmt(er)} 0 0 0 {_fmt(p1[0])} {_fmt(p1[1])}Z",
            )
        )
        groups["active"].append(_line(*p0, *p1))
        _label(groups, cx + nx * (er + 18), cy + ny * (er + 18) + 5, name, "middle")
    _label(groups, cx, cy + er + 34, f"end view from the {title}", "middle")
    _label(
        groups, 40, cy - 20, "Across flat {{cad.af_min_mm:.2f}}–{{cad.af_max_mm:.2f}}"
    )
    _label(
        groups,
        40,
        cy,
        "Flat {{cad.flat_length_min_mm:.1f}}–{{cad.flat_length_max_mm:.1f}} long",
    )
    _label(
        groups, 40, cy + 20, "Clock {{cad.clock_min_deg:g}}–{{cad.clock_max_deg:g}}°"
    )
    return _finish(groups, cy + er + 44)


def _kit_near_flats(
    values: dict, parameters: dict, root: ElementTree.Element
) -> Layout:
    return _kit_flats(values, parameters, root, far=False)


def _kit_far_flats(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    return _kit_flats(values, parameters, root, far=True)


def _kit_nut_face(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Lathe: body in the jaws, flange against the jaw fronts, spigot faced off."""
    s = 14.0
    flange = _cad(values, "nut_flange_thickness_mm")
    body_len = _cad(values, "nut_length_mm") - flange
    spigot = _cad(values, "nut_spigot_length_mm")
    r_flange = _cad(values, "nut_flange_dia_mm") / 2 * s
    r_body = _cad(values, "nut_body_dia_mm") / 2 * s
    r_spigot = _cad(values, "nut_spigot_dia_mm") / 2 * s
    axis = 90 + r_flange
    head = 330.0
    seat = head + flange * s
    tip = seat + spigot * s
    groups = _groups(root)
    _title(groups, 20, 24, "Side view: body in the 3-jaw, spigot toward the tailstock")
    _chuck(groups, head, axis, r_body, body_len * s * 0.9, "3-jaw")
    groups["kept"] += [
        _rect(head - body_len * s, axis - r_body, body_len * s, 2 * r_body),
        _rect(head, axis - r_flange, flange * s, 2 * r_flange),
    ]
    groups["removed"].append(_rect(seat, axis - r_spigot, tip - seat, 2 * r_spigot))
    groups["arriving"].append(_rect(seat, axis - r_spigot, tip - seat, 2 * r_spigot))
    groups["active"].append(_line(seat, axis - r_spigot, seat, axis + r_spigot))
    groups["hidden"] += [
        _line(
            head - body_len * s,
            axis - _cad(values, "major_radius_mm") * s,
            tip,
            axis - _cad(values, "major_radius_mm") * s,
        ),
        _line(
            head - body_len * s,
            axis + _cad(values, "major_radius_mm") * s,
            tip,
            axis + _cad(values, "major_radius_mm") * s,
        ),
    ]
    groups["tool"].append(
        _el(
            "path",
            d=f"M{_fmt(tip + 8)} {_fmt(axis - r_spigot - 30)}l14 -6l0 34l-14 -6z",
        )
    )
    groups["arrows"].append(_line(tip + 12, axis - r_spigot - 20, tip + 12, axis - 8))
    _datum(groups, seat, axis - r_flange - 24, axis + r_flange + 4)
    _datum_label(groups, seat + 6, axis - r_flange - 28, "Z0 seat face", "start")
    _dimension(
        groups,
        head - body_len * s,
        seat,
        axis + r_flange + 30,
        axis + r_body,
        "{{cad.nut_length_min_mm:.1f}}–{{cad.nut_length_max_mm:.1f}}",
    )
    end_y = _callouts(
        groups,
        [
            (
                head - body_len * s / 2,
                axis + r_body + 22,
                ["body Ø{{cad.nut_body_dia_mm:g}}, light grip"],
            ),
            (
                (seat + tip) / 2,
                axis + r_spigot,
                ["spigot faced off", "flush with the seat face"],
            ),
        ],
        axis + r_flange + 50,
        above=False,
    )
    return _finish(groups, end_y)


def _kit_nut_csk(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Bench: the flange's body-side face up, four countersinks by hand."""
    s = 13.0
    r_flange = _cad(values, "nut_flange_dia_mm") / 2 * s
    r_body = _cad(values, "nut_body_dia_mm") / 2 * s
    r_hole = _cad(values, "nut_hole_dia_mm") / 2 * s
    r_csk = _cad(values, "csk_dia_mm") / 2 * s
    pcd = _cad(values, "nut_pcd_reference_mm") / 2 * s
    count = int(_cad(values, "csk_count"))
    cx, cy = 230.0, 60 + r_flange + 10
    groups = _groups(root)
    _title(groups, 20, 24, "Looking down on the flange's body side")
    groups["kept"] += [
        _el("circle", cx=cx, cy=cy, r=r_flange),
        _el("circle", cx=cx, cy=cy, r=r_body),
    ]
    groups["holes"].append(
        _el("circle", cx=cx, cy=cy, r=_cad(values, "major_radius_mm") * s)
    )
    anchors = []
    for index in range(count):
        a = 2 * math.pi * index / count
        hx, hy = cx + pcd * math.cos(a), cy + pcd * math.sin(a)
        groups["removed"].append(_el("circle", cx=hx, cy=hy, r=r_csk))
        groups["holes"].append(_el("circle", cx=hx, cy=hy, r=r_hole))
        groups["active"].append(_el("circle", cx=hx, cy=hy, r=r_csk, fill="none"))
        anchors.append((hx, hy))
    rx = cx + r_flange + 50
    _label(
        groups,
        rx,
        cy - 40,
        "{{cad.csk_count:d}}× Ø{{cad.csk_dia_min_mm:.2f}}–{{cad.csk_dia_max_mm:.2f}} × {{cad.csk_angle_deg:g}}°",
    )
    _label(
        groups,
        rx,
        cy - 20,
        "{{cad.csk_cutter}} in {{cad.csk_angle_deg:g}}° countersink, T-handle",
    )
    _label(groups, rx, cy, "{{cad.csk_wall_note}}")
    hx, hy = anchors[0]
    groups["leaders"].append(
        _el(
            "polyline",
            points=f"{_fmt(rx - 4)} {_fmt(cy - 44)} {_fmt(hx + r_csk)} {_fmt(hy)}",
        )
    )
    _label(
        groups,
        cx,
        cy + r_flange + 26,
        "body Ø{{cad.nut_body_dia_mm:g}} in the middle: keep the cutter off it",
        "middle",
    )
    return _finish(groups, cy + r_flange + 36)


KIT_LAYOUTS = {
    "kit-receipt": _kit_receipt,
    "kit-saw": _kit_saw,
    "kit-length": _kit_length,
    "kit-near-flats": _kit_near_flats,
    "kit-far-flats": _kit_far_flats,
    "kit-nut-face": _kit_nut_face,
    "kit-nut-csk": _kit_nut_csk,
}
