"""Oblique-trammel carrier (TL-21) setup pictures for the ``jig-carrier-*`` templates.

The plate is held flat on the mill table, vise off, on four 1-2-3 blocks under
strap clamps; it is too long for the vise. Plan views look down on the table
from above with the operator at the bottom of the page: +X right from ZERO END,
+Y up the page from ZERO EDGE (the front edge), as sheet 2 draws the plate.
Plate geometry, hole positions and block stations come from the adapter; the
blank, cutter and block sizes from authored parameters. Blocks, straps,
cutters and pins are schematic symbols, and the face elevations exaggerate the
removed layer so it shows.
"""

from __future__ import annotations

from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _rect
from prechips.jig_diagrams import (
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
    _trim,
)
from prechips.shaft_diagrams import _callouts, _dimension

_STEPS = {
    "edges": "Both long edges to width; end straps at mid-width",
    "ends": "Straps moved onto the long edges; both ends to length",
    "face": "TOP up. Edge straps first; then end straps (dashed) for the toe patches",
    "under": "UNDERSIDE up, ZERO EDGE at the back; straps as for TOP",
    "holes": "TOP up, ZERO END left, ZERO EDGE front: one strap over each block",
}
_STRAP = 0.55  # schematic strap bar width, inches
_TOE = 0.6  # strap toe reach onto the plate, inches


def _blocks(values: dict) -> list[float]:
    blocks = values.get("block_x_in")
    if not isinstance(blocks, list) or len(blocks) != 4:
        raise CadError("cad.block_x_in: expected four block stations for the diagram")
    return [float(x) for x in blocks]


def _points(values: dict) -> dict[str, tuple[float, float]]:
    points = values.get("hole_points_in")
    if not isinstance(points, dict) or not points:
        raise CadError("cad.hole_points_in: expected the hole table for the diagram")
    return {tag: (float(x), float(y)) for tag, (x, y) in points.items()}


def _axes_up(groups: dict[str, list[Element]], x: float, y: float) -> None:
    groups["arrows"] += [_line(x, y, x + 36, y), _line(x, y, x, y - 28)]
    _label(groups, x + 40, y + 5, "+X")
    _label(groups, x + 6, y - 32, "+Y")


def _strap_x(groups, x0: float, x1: float, y: float, s: float) -> None:
    """A strap along X from a step block at ``x0`` with its toe at ``x1``."""
    half = _STRAP * s / 2
    groups["jaws"].append(_rect(min(x0, x1), y - half, abs(x1 - x0), 2 * half))
    groups["fixture"].append(_rect(x0 - 8, y - half - 4, 16, 2 * half + 8))


def _strap_y(groups, x: float, y0: float, y1: float, s: float) -> None:
    """A strap along Y from a step block at ``y0`` with its toe at ``y1``."""
    half = _STRAP * s / 2
    groups["jaws"].append(_rect(x - half, min(y0, y1), 2 * half, abs(y1 - y0)))
    groups["fixture"].append(_rect(x - half - 4, y0 - 8, 2 * half + 8, 16))


def _carrier_table(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setups 2-6: the plate on four blocks under straps, one step per picture."""
    step = root.get("data-step")
    if step not in _STEPS:
        raise CadError(f"diagram data-step: expected one of {', '.join(_STEPS)}")
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    blank = _param(parameters, "blank_length_in")
    blank_width = _param(parameters, "blank_width_in")
    along = _param(parameters, "block_length_in")
    across = _param(parameters, "block_width_in")
    blocks = _blocks(values)
    trim = _trim(blank, length, "blank_length_in")
    raw_length = blank if step in ("edges", "ends") else length
    raw_width = blank_width if step == "edges" else width
    cutter_key = "face_cutter_dia_mm" if step in ("face", "under") else "cutter_dia_mm"
    cutter = 0.0 if step == "holes" else _param_in(parameters, cutter_key)

    # The arriving outline plus the step blocks and straps past each end fit
    # between x 30 and 690; the plate's X0 (finished ZERO END) is x0.
    s = min(30.0, 600 / (raw_length + 3.2))
    first = 30 + 1.6 * s
    x0 = first + (trim if step in ("edges", "ends") else 0.0) * s
    back = 92.0
    front = back + raw_width * s
    # Finished plate within the arriving one: centred across a 6 in blank.
    kept_back = back + (raw_width - width) / 2 * s
    kept_front = kept_back + width * s
    groups = _groups(root)
    _title(groups, 20, 26, _STEPS[step])
    _title(groups, 20, 44, "Plan, looking down; operator at the bottom")

    def px(x: float) -> float:
        return x0 + x * s

    def py(y: float) -> float:
        """Sheet Y up from ZERO EDGE; rolled over, ZERO EDGE is at the back."""
        if step == "under":
            return kept_back + y * s
        return kept_front - y * s

    # Plate: arriving dashed, kept solid, removed hatched with the cut edge.
    if step == "edges":
        left, right = px(-trim), px(length + trim)
        groups["arriving"].append(_rect(left, back, right - left, front - back))
        groups["removed"] += [
            _rect(left, back, right - left, kept_back - back),
            _rect(left, kept_front, right - left, front - kept_front),
        ]
        groups["active"] += [
            _line(left, kept_back, right, kept_back),
            _line(left, kept_front, right, kept_front),
        ]
        groups["kept"].append(_rect(left, kept_back, right - left, width * s))
    elif step == "ends":
        _blank(groups, px(-trim), px(length + trim), px(0), px(length), back, front)
    else:
        groups["kept"].append(_rect(px(0), kept_back, length * s, width * s))

    # Blocks under the plate, centred across its width.
    for x in blocks:
        groups["hidden"].append(
            _rect(
                px(x - along / 2),
                (kept_back + kept_front) / 2 - across / 2 * s,
                along * s,
                across * s,
            )
        )
    middle_y = (kept_back + kept_front) / 2
    items: list[tuple[float, float, list[str]]] = []
    end_left, end_right = (
        (px(-trim), px(length + trim))
        if step
        in (
            "edges",
            "ends",
        )
        else (px(0), px(length))
    )

    if step == "edges":
        _strap_x(groups, end_left - 1.2 * s, px(blocks[0]), middle_y, s)
        _strap_x(groups, end_right + 1.2 * s, px(blocks[3]), middle_y, s)
        radius = cutter / 2 * s
        y_front, y_back = kept_front + radius, kept_back - radius
        groups["tool"] += [
            _el("circle", cx=end_left - radius - 2, cy=y_front, r=radius),
            _el("circle", cx=end_right + radius + 2, cy=y_back, r=radius),
        ]
        groups["arrows"] += [
            _line(
                end_left + 6,
                y_front + radius + 6,
                end_left + 6 + 60,
                y_front + radius + 6,
            ),
            _line(
                end_right - 6, y_back - radius - 6, end_right - 66, y_back - radius - 6
            ),
        ]
        _datum_label(groups, px(length / 2), kept_front - 8, "ZERO EDGE", "middle")
        items += [
            (end_left - radius - 2, y_front + radius, ["front edge first, +X"]),
            (px(blocks[1]), front, ["4 blocks, 1 in up"]),
            (end_right + radius + 2, y_back, ["back edge, −X, to width"]),
        ]
        groups["dims"] += [
            _line(end_right + 36, kept_back, end_right + 52, kept_back),
            _line(end_right + 36, kept_front, end_right + 52, kept_front),
            _line(
                end_right + 46,
                kept_back,
                end_right + 46,
                kept_front,
                marker_start="url(#arr)",
                marker_end="url(#arr)",
            ),
        ]
        _label(
            groups,
            end_right + 52,
            middle_y + 5,
            "{{cad.width_in:.1f}}",
        )
    elif step in ("ends", "face", "under", "holes"):
        inner = (blocks[1], blocks[2])
        if step == "holes":
            for index, x in enumerate(blocks):
                if index % 2 == 0:
                    _strap_y(
                        groups, px(x), kept_front + 1.1 * s, kept_front - _TOE * s, s
                    )
                else:
                    _strap_y(
                        groups, px(x), kept_back - 1.1 * s, kept_back + _TOE * s, s
                    )
        else:
            _strap_y(
                groups, px(inner[0]), kept_front + 1.1 * s, kept_front - _TOE * s, s
            )
            _strap_y(groups, px(inner[1]), kept_back - 1.1 * s, kept_back + _TOE * s, s)
        if step in ("face", "under"):
            # Second clamping: end straps on faced metal over the outer blocks.
            for x, sign in ((blocks[0], -1), (blocks[3], 1)):
                tip = px(x)
                heel = px(length) + 1.2 * s if sign > 0 else px(0) - 1.2 * s
                half = _STRAP * s / 2
                groups["hidden"].append(
                    _rect(min(heel, tip), middle_y - half, abs(tip - heel), 2 * half)
                )
            radius = cutter / 2 * s
            # Facing passes: +X strokes stepping across the width.
            rows = max(2, int(width / 0.6))
            for row in range(rows):
                y = kept_back + (row + 0.5) * width * s / rows
                groups["leaders"].append(
                    _line(
                        px(0) - radius,
                        y,
                        px(length) + radius,
                        y,
                        stroke_dasharray="2 5",
                    )
                )
            groups["tool"].append(
                _el(
                    "circle",
                    cx=px(0) - radius - 2,
                    cy=kept_back + 0.5 * width * s / rows,
                    r=radius,
                )
            )
        if step == "ends":
            radius = cutter / 2 * s
            left_cut, right_cut = px(0) - radius, px(length) + radius
            _cutter(groups, left_cut, radius, back - 4, front + radius + 6, at_end=True)
            _cutter(
                groups, right_cut, radius, front + radius + 6, back - 4, at_end=False
            )
            _dimension(
                groups,
                px(0),
                px(length),
                front + 1.6 * s + 22,
                front,
                "{{cad.length_in:.2f}}",
            )
            items += [
                (left_cut, front + 2 * radius + 6, ["ZERO END first, −Y"]),
                (px(inner[0]), front + 1.1 * s, ["straps over inner blocks"]),
                (right_cut, front + 2 * radius + 6, ["right end, +Y, to length"]),
            ]
        # Datums: ZERO END left; ZERO EDGE front (back once rolled over).
        zero_edge_y = kept_back if step == "under" else kept_front
        groups["datum"] += [
            _line(px(0), kept_back, px(0), kept_front),
            _line(px(0), zero_edge_y, px(length), zero_edge_y),
        ]
        _datum_label(groups, px(0), kept_back - 8, "ZERO END", "start")
        edge_label_y = zero_edge_y - 8 if step != "under" else zero_edge_y + 18
        _datum_label(groups, px(length * 0.75), edge_label_y, "ZERO EDGE", "middle")
        if step == "under":
            _label(groups, px(length * 0.62), kept_front - 8, "UNDERSIDE up", "middle")
        elif step in ("face", "holes"):
            _label(groups, px(length * 0.62), kept_back + 18, "TOP up", "middle")

    if step == "holes":
        points = _points(values)
        pin = _cad(values, "pin_dia_max_in")
        sizes = {
            "C": _cad(values, "clamp_drill_max_in"),
            "R": _cad(values, "riser_drill_max_in"),
            "L": _cad(values, "lever_drill_max_in"),
        }
        for tag, (x, y) in points.items():
            dia = pin if tag[0] in "AB" else sizes[tag[0]]
            r = max(dia / 2 * s, 2.0)
            groups["holes"].append(_el("circle", cx=px(x), cy=py(y), r=r))
            groups["active"].append(
                _el("circle", cx=px(x), cy=py(y), r=r + 3, fill="none")
            )
            if tag[0] == "L":  # L1 sits just above L2: label beside them.
                _label(groups, px(x) + r + 5, py(y) + 4, tag, "start", font_size=12)
                continue
            above = tag in ("R1", "R2", "R3", "R4", "CL", "CR", "A2", "B2")
            _label(
                groups,
                px(x),
                py(y) - r - 6 if above else py(y) + r + 15,
                tag,
                "middle",
                font_size=12,
            )
        hub = (_cad(values, "hub_x_in"), _cad(values, "hub_y_in"))
        groups["hidden"].append(
            _el("circle", cx=px(hub[0]), cy=py(hub[1]), r=max(sizes["C"] / 2 * s, 2.0))
        )
        groups["datum"].append(_el("circle", cx=px(0), cy=py(0), r=4))
        _datum_label(groups, px(0) - 6, py(0) + 16, "X0 Y0", "end")
        items += [
            (px(hub[0]), py(hub[1]), ["HUB: not here,", "at assembly"]),
            (px(blocks[0]), kept_front + 1.1 * s, ["strap over", "each block"]),
        ]
    limit = (front if step in ("edges", "ends") else kept_front) + 1.1 * s + 30
    if step == "ends":
        limit = front + 1.6 * s + 30
    bottom = _callouts(groups, items, limit, above=False) if items else limit
    if step in ("face", "under"):
        # Elevation below the plan: plate on the blocks, removed layer exaggerated.
        base = bottom + 14
        block_h = 1.0 * s
        plate_h = max(_cad(values, "thickness_in") * s, 10.0)
        layer = 5.0
        table = base + plate_h + layer + block_h
        _title(groups, 20, base - 12, "Front elevation (removed layer exaggerated)")
        groups["fixture"].append(_line(px(0) - 30, table, px(length) + 30, table))
        for x in blocks:
            groups["fixture"].append(
                _rect(px(x - along / 2), table - block_h, along * s, block_h)
            )
        top = table - block_h - plate_h
        groups["kept"].append(_rect(px(0), top, length * s, plate_h))
        groups["removed"].append(_rect(px(0), top - layer, length * s, layer))
        groups["active"].append(_line(px(0), top, px(length), top))
        face = "UNDERSIDE" if step == "under" else "TOP"
        if step == "under":
            low, high = (_cad(values, f"thickness_{end}_in") for end in ("min", "max"))
            target = f"to {_inch(low)}–{_inch(high)} thick"
        else:
            target = f"half of (T − {_inch(_cad(values, 'thickness_in'))})"
        bottom = _callouts(
            groups,
            [
                (px(length * 0.3), top - layer / 2, [f"{face}: {target}"]),
                (px(blocks[2]), table - block_h / 2, ["1-2-3 block"]),
            ],
            table + 4,
            above=False,
        )
    _axes_up(groups, 640, 72)
    return _finish(groups, bottom + 6)


def _carrier_inspect(
    values: dict, parameters: dict, root: ElementTree.Element
) -> Layout:
    """Setup 7: underside chamfer section at A1; pin-hole relations from A1."""
    thickness = _cad(values, "thickness_in")
    pin = _cad(values, "pin_dia_max_in")
    mouth = _cad(values, "chamfer_mouth_min_in")
    seat = _param(parameters, "spacer_seat_dia_in")
    points = _points(values)
    groups = _groups(root)

    # Section through A1, UNDERSIDE down as the plate seats on its spacer.
    _title(groups, 20, 26, "Section at A1, UNDERSIDE down (chamfer enlarged)")
    s = 160.0
    cx, top = 150.0, 70.0
    bottom = top + thickness * s
    # The .012 leg is under 2 px at this scale: draw it at least 10 px.
    half_bore = pin / 2 * s
    leg = max((mouth - pin) / 2 * s, 10.0)
    half_mouth = half_bore + leg
    for sign in (-1, 1):
        inner = cx + sign * half_bore
        outer = cx + sign * 110
        groups["kept"].append(
            _el(
                "path",
                d=(
                    f"M{inner:.2f} {top:.2f}H{outer:.2f}V{bottom:.2f}"
                    f"H{cx + sign * half_mouth:.2f}L{inner:.2f} {bottom - leg:.2f}Z"
                ),
            )
        )
        groups["active"].append(
            _line(cx + sign * half_mouth, bottom, inner, bottom - leg)
        )
    spacer_half = seat / 2 * s
    groups["hidden"].append(_rect(cx - spacer_half, bottom + 2, 2 * spacer_half, 46))
    end_y = _callouts(
        groups,
        [
            (
                cx - half_mouth + leg / 2,
                bottom - leg / 2,
                ["45° chamfer:", f"mouth ≥ Ø{_inch(mouth)}"],
            ),
            (
                cx,
                top + 10,
                [
                    f"Ø{_inch(_cad(values, 'pin_dia_min_in'), 4)}–{_inch(pin, 4)}",
                    "GO / NO-GO pins",
                ],
            ),
            (
                cx + spacer_half - 10,
                bottom + 30,
                ["TL-VN-78 spacer", f"seat Ø{_inch(seat)}"],
            ),
        ],
        bottom + 80,
        above=False,
    )

    # Pin holes from A1 (plan, TOP up): B1 along X, A2/B2 up from the line.
    _title(groups, 380, 26, "Pins in A1, B1, A2, B2: read from A1")
    a1 = points["A1"]
    scale = 230 / (points["B2"][0] - points["A2"][0])
    x0, y0 = 440.0, 200.0

    def plan(tag: str) -> tuple[float, float]:
        x, y = points[tag]
        return x0 + (x - points["A2"][0]) * scale, y0 - (y - a1[1]) * scale * 4

    for tag in ("A1", "B1", "A2", "B2"):
        px, py = plan(tag)
        groups["holes"].append(_el("circle", cx=px, cy=py, r=7))
        _label(groups, px, py + 24, tag, "middle")
    (ax, ay), (bx, _) = plan("A1"), plan("B1")
    groups["datum"].append(_line(ax - 30, ay, bx + 30, ay, stroke_width=1.2))
    _label(groups, (ax + bx) / 2, ay + 18, "A1–B1 line", "middle")
    _dimension(
        groups,
        ax,
        bx,
        ay + 52,
        ay,
        "{{cad.b1_station_min_in:.3f}}–{{cad.b1_station_max_in:.3f}}",
    )
    a2x, a2y = plan("A2")
    groups["dims"].append(
        _line(
            a2x - 22,
            ay,
            a2x - 22,
            a2y,
            marker_start="url(#arr)",
            marker_end="url(#arr)",
        )
    )
    _label(
        groups,
        a2x - 26,
        (ay + a2y) / 2 + 5,
        "{{cad.outer_row_min_in:.3dot}}–{{cad.outer_row_max_in:.3dot}}",
        "end",
    )
    _title(groups, 380, 44, "Y scale ×4: A2, B2 sit above the A1–B1 line")
    return _finish(groups, max(end_y, ay + 70))


CARRIER_LAYOUTS = {
    "jig-carrier-table": _carrier_table,
    "jig-carrier-inspect": _carrier_inspect,
}
