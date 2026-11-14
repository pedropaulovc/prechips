"""Oblique-trammel carrier (TL-21) setup pictures for the ``jig-carrier-*`` templates.

The plate is held flat on the mill table, vise off, on four 1-2-3 blocks under
strap clamps; it is too long for the vise. Plan views look down on the table
from above with the operator at the bottom of the page: +X right from ZERO END,
+Y up the page from ZERO EDGE (the front edge), as sheet 2 draws the plate.
Plate geometry, hole positions and block stations come from the adapter; the
blank, cutter, block and strap-toe sizes from authored parameters. Blocks,
straps, cutters and pins are schematic symbols, and the face elevations
exaggerate the removed layer so it shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

from prechips.cad import CadError, _shorthand
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _rect
from prechips.jig_diagrams import (
    _blank,
    _cutter,
    _datum_label,
    _finish,
    _groups,
    _label,
    _param,
    _param_in,
    _title,
    _trim,
)
from prechips.shaft_diagrams import _callouts, _dimension

Groups = dict[str, list[Element]]
Items = list[tuple[float, float, list[str]]]

_STEPS = {
    "edges": "Both long edges to width; end straps at mid-width",
    "ends": "Straps moved onto the end blocks; both ends to length",
    "face": "TOP up. Edge straps first; end straps (dashed) after the last full pass",
    "holes": "TOP up, ZERO END left, ZERO EDGE front: one strap over each block",
}
_STRAP = 0.55  # schematic strap bar width, inches
_HEEL = 1.1  # schematic step-block distance outside the plate edge, inches
# Straps lie on top of the plate: drawn in the tool layer (above the kept
# plate) in the fixture colour of the jaws layer.
_STRAP_STYLE = {"fill": "#8a9099"}


@dataclass(frozen=True)
class _Plan:
    """One plan view: scale, the plate's X0 and its finished long edges."""

    step: str
    s: float
    x0: float
    back: float  # arriving material's back edge (page y)
    front: float  # arriving material's front edge (page y)
    kept_back: float
    kept_front: float
    length: float
    width: float
    trim: float
    blocks: list[float]
    along: float
    across: float
    toe: float  # strap toe centre in from the long edge, inches
    cutter: float  # inches; 0 for the holes picture

    def px(self, x: float) -> float:
        return self.x0 + x * self.s

    def py(self, y: float) -> float:
        """Sheet Y up from ZERO EDGE, at the front."""
        return self.kept_front - y * self.s

    @property
    def middle(self) -> float:
        return (self.kept_back + self.kept_front) / 2

    @property
    def ends(self) -> tuple[float, float]:
        """Arriving material's left and right ends (page x)."""
        if self.step in ("edges", "ends"):
            return self.px(-self.trim), self.px(self.length + self.trim)
        return self.px(0), self.px(self.length)


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


def _plan(values: dict, parameters: dict, step: str) -> _Plan:
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    blank = _param(parameters, "blank_length_in")
    raw_length = blank if step in ("edges", "ends") else length
    raw_width = _param(parameters, "blank_width_in") if step == "edges" else width
    cutter_key = "face_cutter_dia_mm" if step == "face" else "cutter_dia_mm"
    # The arriving outline plus the step blocks and straps past each end fit
    # between x 30 and 690.
    s = min(30.0, 600 / (raw_length + 3.2))
    trim = _trim(blank, length, "blank_length_in")
    back = 92.0
    kept_back = back + (raw_width - width) / 2 * s
    return _Plan(
        step=step,
        s=s,
        x0=30 + 1.6 * s + (trim if step in ("edges", "ends") else 0.0) * s,
        back=back,
        front=back + raw_width * s,
        kept_back=kept_back,
        kept_front=kept_back + width * s,
        length=length,
        width=width,
        trim=trim,
        blocks=_blocks(values),
        along=_param(parameters, "block_length_in"),
        across=_param(parameters, "block_width_in"),
        toe=_param(parameters, "strap_toe_in"),
        cutter=0.0 if step == "holes" else _param_in(parameters, cutter_key),
    )


def _axes_up(groups: Groups, x: float, y: float) -> None:
    groups["arrows"] += [_line(x, y, x + 36, y), _line(x, y, x, y - 28)]
    _label(groups, x + 40, y + 5, "+X")
    _label(groups, x + 6, y - 32, "+Y")


def _strap_y(groups: Groups, x: float, heel: float, toe: float, s: float) -> None:
    """A strap across a long edge at ``x``: step block at ``heel``, toe at ``toe``."""
    half = _STRAP * s / 2
    groups["tool"].append(
        _rect(x - half, min(heel, toe), 2 * half, abs(toe - heel), **_STRAP_STYLE)
    )
    groups["fixture"].append(_rect(x - half - 4, heel - 8, 2 * half + 8, 16))


def _strap_x(groups: Groups, heel: float, toe: float, y: float, s: float) -> None:
    """A strap along the plate at ``y``: step block at ``heel``, toe at ``toe``."""
    half = _STRAP * s / 2
    groups["tool"].append(
        _rect(min(heel, toe), y - half, abs(toe - heel), 2 * half, **_STRAP_STYLE)
    )
    groups["fixture"].append(_rect(heel - 8, y - half - 4, 16, 2 * half + 8))


def _edge_strap(groups: Groups, plan: _Plan, x: float, front: bool) -> None:
    """A strap across a long edge, its toe over the block at station ``x``."""
    edge, inward = (plan.kept_front, -1) if front else (plan.kept_back, 1)
    heel = edge - inward * _HEEL * plan.s
    _strap_y(groups, plan.px(x), heel, edge + inward * plan.toe * plan.s, plan.s)


def _draw_blocks(groups: Groups, plan: _Plan) -> None:
    for x in plan.blocks:
        groups["hidden"].append(
            _rect(
                plan.px(x - plan.along / 2),
                plan.middle - plan.across / 2 * plan.s,
                plan.along * plan.s,
                plan.across * plan.s,
            )
        )


def _draw_datums(groups: Groups, plan: _Plan) -> None:
    """ZERO END left; ZERO EDGE at the front."""
    edge_y = plan.kept_front
    groups["datum"] += [
        _line(plan.px(0), plan.kept_back, plan.px(0), plan.kept_front),
        _line(plan.px(0), edge_y, plan.px(plan.length), edge_y),
    ]
    _datum_label(groups, plan.px(0), plan.kept_back - 8, "ZERO END", "start")
    _datum_label(groups, plan.px(plan.length * 0.75), edge_y - 8, "ZERO EDGE", "middle")
    # Clear of the edge straps (faces) and the R-row labels (holes).
    at = 0.62 if plan.step == "holes" else 0.4
    _label(groups, plan.px(plan.length * at), plan.kept_back + 18, "TOP up", "middle")


def _edges(groups: Groups, plan: _Plan, values: dict) -> Items:
    left, right = plan.ends
    groups["arriving"].append(
        _rect(left, plan.back, right - left, plan.front - plan.back)
    )
    groups["removed"] += [
        _rect(left, plan.back, right - left, plan.kept_back - plan.back),
        _rect(left, plan.kept_front, right - left, plan.front - plan.kept_front),
    ]
    groups["active"] += [
        _line(left, plan.kept_back, right, plan.kept_back),
        _line(left, plan.kept_front, right, plan.kept_front),
    ]
    groups["kept"].append(
        _rect(left, plan.kept_back, right - left, plan.width * plan.s)
    )
    _draw_blocks(groups, plan)
    _strap_x(groups, left - 1.2 * plan.s, plan.px(plan.blocks[0]), plan.middle, plan.s)
    _strap_x(groups, right + 1.2 * plan.s, plan.px(plan.blocks[3]), plan.middle, plan.s)
    radius = plan.cutter / 2 * plan.s
    y_front, y_back = plan.kept_front + radius, plan.kept_back - radius
    groups["tool"] += [
        _el("circle", cx=left - radius - 2, cy=y_front, r=radius),
        _el("circle", cx=right + radius + 2, cy=y_back, r=radius),
    ]
    groups["arrows"] += [
        _line(left + 6, y_front + radius + 6, left + 66, y_front + radius + 6),
        _line(right - 6, y_back - radius - 6, right - 66, y_back - radius - 6),
    ]
    _datum_label(
        groups, plan.px(plan.length / 2), plan.kept_front - 8, "ZERO EDGE", "middle"
    )
    groups["dims"] += [
        _line(right + 36, plan.kept_back, right + 52, plan.kept_back),
        _line(right + 36, plan.kept_front, right + 52, plan.kept_front),
        _line(
            right + 46,
            plan.kept_back,
            right + 46,
            plan.kept_front,
            marker_start="url(#arr)",
            marker_end="url(#arr)",
        ),
    ]
    _label(groups, right + 52, plan.middle + 5, _shorthand(_cad(values, "width_in"), 1))
    return [
        (left - radius - 2, y_front + radius, ["front edge first, +X"]),
        (plan.px(plan.blocks[1]), plan.front, ["4 blocks, 1 in up"]),
        (right + radius + 2, y_back, ["back edge, −X, to width"]),
    ]


def _ends(groups: Groups, plan: _Plan, values: dict) -> Items:
    left, right = plan.ends
    _blank(groups, left, right, plan.px(0), plan.px(plan.length), plan.back, plan.front)
    _draw_blocks(groups, plan)
    _edge_strap(groups, plan, plan.blocks[0], front=True)
    _edge_strap(groups, plan, plan.blocks[3], front=False)
    radius = plan.cutter / 2 * plan.s
    left_cut, right_cut = plan.px(0) - radius, plan.px(plan.length) + radius
    below = plan.front + radius + 6
    _cutter(groups, left_cut, radius, plan.back - 4, below, at_end=True)
    _cutter(groups, right_cut, radius, below, plan.back - 4, at_end=False)
    _dimension(
        groups,
        plan.px(0),
        plan.px(plan.length),
        plan.front + 1.6 * plan.s + 22,
        plan.front,
        _shorthand(_cad(values, "length_in"), 2),
    )
    _draw_datums(groups, plan)
    return [
        (left_cut, below + radius, ["ZERO END first, −Y"]),
        (
            plan.px(plan.blocks[0]),
            plan.front + _HEEL * plan.s,
            ["toes over end blocks"],
        ),
        (right_cut, below + radius, ["right end, +Y, to length"]),
    ]


def _face(groups: Groups, plan: _Plan, values: dict) -> Items:
    groups["kept"].append(
        _rect(plan.px(0), plan.kept_back, plan.length * plan.s, plan.width * plan.s)
    )
    _draw_blocks(groups, plan)
    _edge_strap(groups, plan, plan.blocks[0], front=True)
    _edge_strap(groups, plan, plan.blocks[3], front=False)
    # Second clamping: end straps on faced metal over the outer blocks.
    half = _STRAP * plan.s / 2
    for x, heel in (
        (plan.blocks[0], plan.px(0) - 1.2 * plan.s),
        (plan.blocks[3], plan.px(plan.length) + 1.2 * plan.s),
    ):
        tip = plan.px(x)
        groups["hidden"].append(
            _rect(min(heel, tip), plan.middle - half, abs(tip - heel), 2 * half)
        )
    radius = plan.cutter / 2 * plan.s
    rows = max(2, int(plan.width / 0.6))
    pitch = plan.width * plan.s / rows
    for row in range(rows):
        y = plan.kept_back + (row + 0.5) * pitch
        groups["leaders"].append(
            _line(
                plan.px(0) - radius,
                y,
                plan.px(plan.length) + radius,
                y,
                stroke_dasharray="2 5",
            )
        )
    groups["tool"].append(
        _el(
            "circle",
            cx=plan.px(0) - radius - 2,
            cy=plan.kept_back + pitch / 2,
            r=radius,
        )
    )
    _draw_datums(groups, plan)
    return []


def _holes(groups: Groups, plan: _Plan, values: dict) -> Items:
    groups["kept"].append(
        _rect(plan.px(0), plan.kept_back, plan.length * plan.s, plan.width * plan.s)
    )
    _draw_blocks(groups, plan)
    for index, x in enumerate(plan.blocks):
        _edge_strap(groups, plan, x, front=index % 2 == 0)
    pin = _cad(values, "pin_dia_max_in")
    sizes = {
        "C": _cad(values, "clamp_drill_max_in"),
        "R": _cad(values, "riser_drill_max_in"),
        "L": _cad(values, "lever_drill_max_in"),
    }
    for tag, (x, y) in _points(values).items():
        dia = pin if tag[0] in "AB" else sizes[tag[0]]
        r = max(dia / 2 * plan.s, 2.0)
        cx, cy = plan.px(x), plan.py(y)
        groups["holes"].append(_el("circle", cx=cx, cy=cy, r=r))
        groups["active"].append(_el("circle", cx=cx, cy=cy, r=r + 3, fill="none"))
        _hole_label(groups, tag, cx, cy, r)
    hub = (plan.px(_cad(values, "hub_x_in")), plan.py(_cad(values, "hub_y_in")))
    groups["hidden"].append(
        _el("circle", cx=hub[0], cy=hub[1], r=max(sizes["C"] / 2 * plan.s, 2.0))
    )
    groups["datum"].append(_el("circle", cx=plan.px(0), cy=plan.py(0), r=4))
    _datum_label(groups, plan.px(0) - 6, plan.py(0) + 16, "X0 Y0", "end")
    _draw_datums(groups, plan)
    return [
        (hub[0], hub[1], ["HUB: not here,", "at assembly"]),
        (
            plan.px(plan.blocks[0]),
            plan.kept_front + _HEEL * plan.s,
            ["toe over", "each block"],
        ),
    ]


def _hole_label(groups: Groups, tag: str, cx: float, cy: float, r: float) -> None:
    if tag[0] == "L":  # L1 sits just above L2: label beside them.
        _label(groups, cx + r + 5, cy + 4, tag, "start", font_size=12)
        return
    above = tag in ("R1", "R2", "R3", "R4", "CL", "CR", "A2", "B2")
    y = cy - r - 6 if above else cy + r + 15
    _label(groups, cx, y, tag, "middle", font_size=12)


def _elevation(groups: Groups, plan: _Plan, values: dict, top_y: float) -> float:
    """Front elevation under the plan: plate on the blocks, layer exaggerated."""
    base = top_y + 14
    block_h = 1.0 * plan.s
    plate_h = max(_cad(values, "thickness_in") * plan.s, 10.0)
    layer = 5.0
    table = base + plate_h + layer + block_h
    _title(groups, 20, base - 12, "Front elevation (removed layer exaggerated)")
    groups["fixture"].append(
        _line(plan.px(0) - 30, table, plan.px(plan.length) + 30, table)
    )
    for x in plan.blocks:
        groups["fixture"].append(
            _rect(
                plan.px(x - plan.along / 2),
                table - block_h,
                plan.along * plan.s,
                block_h,
            )
        )
    top = table - block_h - plate_h
    groups["kept"].append(_rect(plan.px(0), top, plan.length * plan.s, plate_h))
    groups["removed"].append(
        _rect(plan.px(0), top - layer, plan.length * plan.s, layer)
    )
    groups["active"].append(_line(plan.px(0), top, plan.px(plan.length), top))
    low, high = (_cad(values, f"thickness_{end}_in") for end in ("min", "max"))
    target = f"TOP only, to {_shorthand(low, 3)}–{_shorthand(high, 3)} thick"
    return _callouts(
        groups,
        [
            (plan.px(plan.length * 0.3), top - layer / 2, [target]),
            (plan.px(plan.blocks[2]), table - block_h / 2, ["1-2-3 block"]),
        ],
        table + 4,
        above=False,
    )


_DRAW = {"edges": _edges, "ends": _ends, "face": _face, "holes": _holes}


def _carrier_table(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setups 2-5: the plate on four blocks under straps, one step per picture."""
    step = root.get("data-step")
    if step not in _STEPS:
        raise CadError(f"diagram data-step: expected one of {', '.join(_STEPS)}")
    plan = _plan(values, parameters, step)
    groups = _groups(root)
    _title(groups, 20, 26, _STEPS[step])
    _title(groups, 20, 44, "Plan, looking down; operator at the bottom")
    items = _DRAW[step](groups, plan, values)
    straps = plan.kept_front + _HEEL * plan.s + 30
    limit = (
        plan.front + 1.6 * plan.s + 30 if step == "ends" else max(plan.front, straps)
    )
    bottom = _callouts(groups, items, limit, above=False) if items else limit
    if step == "face":
        bottom = _elevation(groups, plan, values, bottom)
    _axes_up(groups, 640, 72)
    return _finish(groups, bottom + 6)


def _carrier_inspect(
    values: dict, parameters: dict, root: ElementTree.Element
) -> Layout:
    """Setup 6: section at A1 with its broken underside edge on the spacer;
    pin-hole relations from A1."""
    groups = _groups(root)
    end_y = _section(groups, values, parameters)
    line_y = _relations(groups, values)
    return _finish(groups, max(end_y, line_y + 70))


def _section(groups: Groups, values: dict, parameters: dict) -> float:
    """Section through A1, UNDERSIDE down as the plate seats on its spacer."""
    pin = _cad(values, "pin_dia_max_in")
    seat = _param(parameters, "spacer_seat_dia_in")
    _title(groups, 20, 26, "Section at A1, UNDERSIDE down (break enlarged)")
    s = 160.0
    cx, top = 150.0, 70.0
    bottom = top + _cad(values, "thickness_in") * s
    # The edge break is under 2 px at this scale: draw it 4 px.
    half_bore = pin / 2 * s
    brk = 4.0
    for sign in (-1, 1):
        inner = cx + sign * half_bore
        outer = cx + sign * 110
        groups["kept"].append(
            _el(
                "path",
                d=(
                    f"M{inner:.2f} {top:.2f}H{outer:.2f}V{bottom:.2f}"
                    f"H{inner + sign * brk:.2f}L{inner:.2f} {bottom - brk:.2f}Z"
                ),
            )
        )
    spacer_half = seat / 2 * s
    groups["hidden"].append(_rect(cx - spacer_half, bottom + 2, 2 * spacer_half, 46))
    low = _shorthand(_cad(values, "pin_dia_min_in"), 4)
    brk_max = _shorthand(_cad(values, "chamfer_max_in"), 3)
    return _callouts(
        groups,
        [
            (
                cx - half_bore - brk / 2,
                bottom - brk / 2,
                [f"{brk_max} max round or", "chamfer; no countersink"],
            ),
            (cx, top + 10, [f"Ø{low}–{_shorthand(pin, 4)}", "GO / NO-GO pins"]),
            (
                cx + spacer_half - 10,
                bottom + 30,
                ["TL-VN-78 spacer", f"seat Ø{_shorthand(seat, 3)}"],
            ),
        ],
        bottom + 80,
        above=False,
    )


def _relations(groups: Groups, values: dict) -> float:
    """Pins in A1, B1, A2, B2 (plan, TOP up): B1 along X, A2/B2 off the line."""
    points = _points(values)
    _title(groups, 380, 26, "For reference: the pin check before tapping")
    _title(groups, 380, 44, "From A1 and the A1–B1 line; Y scale ×4")
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
    low, high = (_cad(values, f"b1_station_{end}_in") for end in ("min", "max"))
    _dimension(
        groups, ax, bx, ay + 52, ay, f"{_shorthand(low, 3)}–{_shorthand(high, 3)}"
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
    low, high = (_cad(values, f"outer_row_{end}_in") for end in ("min", "max"))
    _label(
        groups,
        a2x - 26,
        (ay + a2y) / 2 + 5,
        f"{_shorthand(low, 3)}–{_shorthand(high, 3)}",
        "end",
    )
    return ay


CARRIER_LAYOUTS = {
    "jig-carrier-table": _carrier_table,
    "jig-carrier-inspect": _carrier_inspect,
}
