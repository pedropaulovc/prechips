"""Carriage-block setup pictures for the ``jig-block-*`` diagram templates.

The pivot block (TL-22) and feed block (TL-32) are drawn from their adapter
values (:mod:`prechips.cad_carriage_block`) and authored holding parameters,
in the shared jig shell and conventions of :mod:`prechips.jig_diagrams`:
arriving material dashed, kept solid, removed hatched; jaws, parallels,
cutters and spacers are schematic. Vise top views look down from the
operator's side, fixed jaw at the back (top of the page). The feed block is
recognised by its lug values; the pivot block has none.
"""

from __future__ import annotations

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
    _text,
)
from prechips.jig_diagrams import (
    JAW,
    _axes,
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

_PARALLEL_IN = 0.125  # schematic parallel thickness
_Groups = dict[str, list[Element]]


def _feed(values: dict) -> bool:
    return "lug_x_in" in values


def _vdim(groups: _Groups, x: float, y0: float, y1: float, text: str) -> None:
    """Vertical dimension at ``x`` from ``y0`` to ``y1``, text to its left."""
    groups["dims"].append(
        _line(x, y0, x, y1, marker_start="url(#arr)", marker_end="url(#arr)")
    )
    middle = (y0 + y1) / 2
    groups["labels"].append(
        _text(
            x - 5,
            middle,
            text,
            text_anchor="middle",
            transform=f"rotate(-90 {_fmt(x - 5)} {_fmt(middle)})",
        )
    )


def _label_rows(
    groups: _Groups, x: float, rows: list[tuple[float, float, float, list[str]]]
) -> None:
    """Labels at ``x`` on their own rows below their anchors.

    Each leader runs left from its label to its own vertical bus left of ``x``
    (lower rows further left), up to its anchor's height, then across to the
    anchor, so no leader crosses a label or another leader's bus.
    """
    for index, (y, ax, ay, lines) in enumerate(rows):
        bus = x - 10 - 8 * index
        points = [(x - 4, y - 4), (bus, y - 4), (bus, ay), (ax, ay)]
        groups["leaders"] += [
            _el("polyline", points=" ".join(f"{_fmt(a)} {_fmt(b)}" for a, b in points)),
            _el("circle", cx=ax, cy=ay, r=1.8, fill="#333"),
        ]
        for line_index, line in enumerate(lines):
            _label(groups, x, y + line_index * 15, line)


def _outline(
    values: dict, left: float, back: float, s: float, mirror: bool = False
) -> str:
    """Top-view outline: Y (rows) across the page, X (stations) down it.

    The pivot block is a rectangle. The feed block's head sits at the row
    side, its lug runs on to LUG END on the far side of the stations from
    SPINDLE END. ``mirror`` puts the row side on the right.
    """
    across = _cad(values, "y_length_in") * s
    deep = _cad(values, "length_in") * s
    if not _feed(values):
        return _rect(left, back, across, deep)
    head = across - _cad(values, "lug_length_in") * s
    lug = _cad(values, "lug_x_in") * s
    if mirror:
        points = [
            (left, back + lug),
            (left + across - head, back + lug),
            (left + across - head, back),
            (left + across, back),
            (left + across, back + deep),
            (left, back + deep),
        ]
    else:
        points = [
            (left, back),
            (left + head, back),
            (left + head, back + lug),
            (left + across, back + lug),
            (left + across, back + deep),
            (left, back + deep),
        ]
    return _el("polygon", points=" ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points))


def _section(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Square-up setups seen along the jaws: clean one face, flip, cut to size.

    ``data-hold`` picks the pair of faces: ``faces`` (flat, the 1 in faces),
    ``width`` (on edge, the as-bought 3 in edges to the 1.64 length) or
    ``ends`` (on end, the sawn ends to the Y length).
    """
    hold = root.get("data-hold")
    feed = _feed(values)
    height = _cad(values, "height_in")
    if hold == "faces":
        across = _param(parameters, "blank_width_in")
        arriving = _param(parameters, "blank_thickness_in")
        final = height
        parallel = _param_in(parameters, "face_parallel_height_mm")
        names = ("as bought", "SEAT", "TOP")
        size = "{{cad.height_min_in:.3dot}}–{{cad.height_max_in:.3dot}}"
    elif hold == "width":
        across = height
        arriving = _param(parameters, "blank_width_in")
        final = _cad(values, "length_in")
        parallel = _param_in(parameters, "edge_parallel_height_mm")
        names = ("as bought", "SPINDLE END", "OUTER END")
        size = "{{cad.length_min_in:.3f}}–{{cad.length_max_in:.3f}}"
    elif hold == "ends":
        across = height
        arriving = _param(parameters, "blank_length_in")
        final = _cad(values, "y_length_in")
        parallel = _param_in(parameters, "edge_parallel_height_mm")
        names = ("sawn", "ROW SIDE", "LUG END" if feed else "FAR SIDE")
        size = "{{cad.y_length_min_in:.3f}}–{{cad.y_length_max_in:.3f}}"
    else:
        raise CadError("diagram data-hold: expected 'faces', 'width' or 'ends'")
    if arriving <= final:
        raise CadError(f"diagram {hold}: the blank is not larger than the part")
    clean = min(_param(parameters, "cleanup_in"), (arriving - final) / 2)
    jaw_h = _param_in(parameters, "vise_jaw_height_mm")
    s = min(110.0, 250 / (parallel + arriving), 200 / across)
    bed = 70 + (parallel + arriving) * s + 40
    groups = _groups(root)

    def panel(
        centre: float, title: str, arrive: float, keep: float, low: str, top: str
    ) -> None:
        half = across * s / 2
        left, right = centre - half, centre + half
        floor = bed - parallel * s
        jaw_top = bed - jaw_h * s
        _title(groups, centre - 150, 30, title)
        groups["jaws"] += [
            _rect(left - 26, jaw_top, 26, bed - jaw_top),
            _rect(right, jaw_top, 26, bed - jaw_top),
        ]
        groups["fixture"] += [
            _rect(left, floor, _PARALLEL_IN * s, parallel * s),
            _rect(right - _PARALLEL_IN * s, floor, _PARALLEL_IN * s, parallel * s),
            _line(left - 46, bed, right + 46, bed),
        ]
        top_y, keep_y = floor - arrive * s, floor - keep * s
        groups["arriving"].append(_rect(left, top_y, right - left, arrive * s))
        groups["removed"].append(_rect(left, top_y, right - left, keep_y - top_y))
        groups["kept"].append(_rect(left, keep_y, right - left, floor - keep_y))
        groups["active"].append(_line(left, keep_y, right, keep_y))
        groups["tool"].append(_rect(centre - 0.375 * s, top_y - 40, 0.75 * s, 32))
        if across * s >= 8 * max(len(low), len(top)) + 8:
            _label(groups, centre, floor - 6, low, "middle")
            _label(groups, centre, keep_y + 16, top, "middle")
        else:
            # Narrow on edge or on end: the low name runs up the part, the
            # new face's name sits beside it, above the jaws.
            _label(
                groups,
                centre + 5,
                floor - 6,
                low,
                "start",
                transform=f"rotate(-90 {_fmt(centre + 5)} {_fmt(floor - 6)})",
            )
            _label(groups, right + 6, keep_y + 5, top)
        _label(groups, left - 13, jaw_top - 6, "fixed", "middle")
        _label(groups, right + 13, jaw_top - 6, "moving", "middle")

    panel(
        190,
        f"1  {names[0]} face up: clean it, mark {names[1]}",
        arriving,
        arriving - clean,
        names[0],
        names[1],
    )
    panel(
        530,
        f"2  {names[1]} down: cut {names[2]} to size",
        arriving - clean,
        final,
        names[1],
        names[2],
    )
    floor = bed - parallel * s
    right = 530 + across * s / 2
    _vdim(groups, right + 70, floor - final * s, floor, size)
    end_y = _callouts(
        groups,
        [
            (190, bed, [f"on {_inch(parallel, 2)} in parallels"]),
            (530, bed, ["layers ≤ {{process.layer_in:.2dot}}; last pass to size"]),
        ],
        bed + 4,
        above=False,
    )
    return _finish(groups, end_y)


def _holes(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Top-face holes: the part in the vise (``vise``) or finished (``inspect``).

    Top view, SPINDLE END at the back (fixed jaw), ROW SIDE left; below it a
    stepped section through H1 and B looking from ROW SIDE.
    """
    mode = root.get("data-mode")
    if mode not in {"vise", "inspect"}:
        raise CadError("diagram data-mode: expected 'vise' or 'inspect'")
    feed = _feed(values)
    length = _cad(values, "length_in")
    y_length = _cad(values, "y_length_in")
    height = _cad(values, "height_in")
    rows = [_cad(values, f"hole_y{n}_nominal_in") for n in (1, 2)]
    stations = [_cad(values, f"hole_x{n}_nominal_in") for n in (1, 2)]
    bore = (_cad(values, "bore_y_nominal_in"), _cad(values, "bore_x_nominal_in"))
    groups = _groups(root)
    s = min(110.0, 290 / y_length)
    left = 150.0
    back = 110.0 if mode == "vise" else 128.0
    front = back + length * s
    across = y_length * s
    _title(
        groups,
        20,
        24,
        "Top view, SEAT down, SPINDLE END at the fixed jaw (top)"
        if mode == "vise"
        else "Top view, finished",
    )
    if mode == "vise":
        _vise(
            groups, left - 20, left + across + 20, back, front, _PARALLEL_IN * s, "", ""
        )
    groups["kept"].append(_outline(values, left, back, s))
    for row in rows:
        for station in stations:
            x, y = left + row * s, back + station * s
            groups["holes"] += [
                _el("circle", cx=x, cy=y, r=_cad(values, "cbore_dia_in") / 2 * s),
                _el("circle", cx=x, cy=y, r=_cad(values, "hole_dia_in") / 2 * s),
            ]
    bx, by = left + bore[0] * s, back + bore[1] * s
    groups["holes"].append(
        _el("circle", cx=bx, cy=by, r=_cad(values, "bore_dia_in") / 2 * s)
    )
    groups["threads"].append(
        _el("circle", cx=bx, cy=by, r=_cad(values, "tap_drill_in") / 2 * s)
    )
    groups["datum"].append(_el("circle", cx=left, cy=back, r=3.5))
    dim_top = back - (JAW if mode == "vise" else 0) - 14
    _datum_label(groups, left - 6, dim_top + 10, "X0 Y0", "end")
    _label(groups, left - 8, front + 16, "ROW SIDE", "end")
    for index, row in enumerate(sorted([*rows, bore[0]])):
        _dimension(groups, left, left + row * s, dim_top - 18 * index, back, _inch(row))
    for index, station in enumerate(sorted([*stations, bore[1]])):
        _vdim(groups, left - 26 - 24 * index, back, back + station * s, _inch(station))
    labels = [
        (left + rows[0] * s, back + stations[0] * s, ["H1"]),
        (bx, by, ["B"]),
        (left + rows[1] * s, back + stations[1] * s, ["H4"]),
    ]
    if feed:
        lug = back + _cad(values, "lug_x_in") * s
        labels.append((left + across, (lug + front) / 2, ["LUG END"]))
    end_y = _callouts(
        groups, labels, front + (JAW + 6 if mode == "vise" else 6), above=False
    )
    if mode == "inspect":
        _vdim(groups, left + across + 30, back, front, _inch(length, 2))
        _dimension(groups, left, left + across, end_y + 22, front, _inch(y_length, 2))
        end_y += 30
        if feed:
            head = across - _cad(values, "lug_length_in") * s
            _dimension(
                groups,
                left + head,
                left + across,
                dim_top - 54,
                back,
                "{{cad.lug_length_in:.2f}}",
            )
            _vdim(groups, left + across + 60, back, lug, "{{cad.lug_x_in:.2dot}}")
    _axes(groups, 24, front - 34)

    # Stepped section through H1 and B, looking from ROW SIDE: SPINDLE END
    # left, TOP up, beside the top view; labels in a column under it.
    s_left = left + across + (70 if mode == "inspect" else 40) + 30
    t = min(110.0, (650 - s_left) / length)
    top = 70.0
    seat = top + height * t
    _title(groups, s_left - 30, top - 30, "Section through H1 and B")
    _title(groups, s_left - 30, top - 14, "(SPINDLE END left)")
    groups["kept"].append(_rect(s_left, top, length * t, height * t))
    hx = s_left + stations[0] * t
    cb_w = _cad(values, "cbore_dia_in") * t
    hole_w = _cad(values, "hole_dia_in") * t
    floor = seat - _cad(values, "cbore_floor_nominal_in") * t
    groups["holes"] += [
        _rect(hx - cb_w / 2, top, cb_w, floor - top),
        _rect(hx - hole_w / 2, floor, hole_w, seat - floor),
    ]
    bxs = s_left + bore[1] * t
    bore_w = _cad(values, "bore_dia_in") * t
    tap_w = _cad(values, "tap_drill_in") * t
    bore_floor = top + _cad(values, "bore_depth_nominal_in") * t
    groups["threads"].append(
        _rect(bxs - tap_w / 2 - 3, bore_floor, tap_w + 6, seat - bore_floor)
    )
    groups["holes"] += [
        _rect(bxs - bore_w / 2, top, bore_w, bore_floor - top),
        _rect(bxs - tap_w / 2, bore_floor, tap_w, seat - bore_floor),
    ]
    groups["active"].append(
        _line(bxs - bore_w / 2, bore_floor, bxs + bore_w / 2, bore_floor)
    )
    step_x = (hx + bxs) / 2
    groups["hidden"].append(_line(step_x, top, step_x, seat))
    right = s_left + length * t
    _vdim(groups, right + 18, top, seat, _inch(height, 2))
    _label(groups, right + 26, seat - 4, "SEAT")
    _label(groups, right + 26, top + 12, "TOP")
    texts = [
        (
            bxs + bore_w / 2,
            (top + bore_floor) / 2,
            [
                "Ø{{cad.bore_dia_min_in:.4dot}}–{{cad.bore_dia_max_in:.4dot}}, flat floor,",
                "{{cad.bore_depth_min_in:.3dot}}–{{cad.bore_depth_max_in:.3dot}} deep",
            ],
        ),
        (
            hx + cb_w / 2,
            floor,
            [
                "Ø{{cad.cbore_dia_nominal_in:.2dot}} counterbore, floor",
                "{{cad.cbore_floor_min_in:.3dot}}–{{cad.cbore_floor_max_in:.3dot}} above SEAT",
            ],
        ),
        (bxs + tap_w / 2, (bore_floor + seat) / 2, ["{{cad.pivot_thread}} thru"]),
        (
            hx + hole_w / 2,
            (floor + seat) / 2,
            ["Ø{{cad.hole_dia_nominal_in:.3dot}} thru"],
        ),
    ]
    y = seat + 30
    rows = []
    for ax, ay, lines in texts:
        rows.append((y, ax, ay, lines))
        y += 15 * len(lines) + 8
    _label_rows(groups, s_left, rows)
    return _finish(groups, max(end_y + 10, y))


def _notch(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Feed-block L-notch: LUG END out past the right jaw side, spacer left."""
    if not _feed(values):
        raise CadError("diagram jig-block-notch: needs the feed block's lug values")
    length = _cad(values, "length_in")
    y_length = _cad(values, "y_length_in")
    lug_length = _cad(values, "lug_length_in")
    lug_x = _cad(values, "lug_x_in")
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    over = _param_in(parameters, "notch_overhang_mm")
    spacer = _param(parameters, "spacer_length_in")
    cutter = _param_in(parameters, "half_cutter_dia_mm")
    s = min(70.0, 600 / (jaw + over + cutter))
    jaw_left = 40.0
    jaw_right = jaw_left + jaw * s
    back = 120.0
    front = back + length * s
    end = jaw_right + over * s
    start = end - y_length * s
    step = end - lug_length * s
    groups = _groups(root)
    _title(groups, 20, 24, "Top view: LUG END out right, spacer at the left jaw end")
    _vise(
        groups,
        jaw_left,
        jaw_right,
        back,
        front,
        _PARALLEL_IN * s,
        "fixed jaw · SPINDLE END",
        "moving jaw",
    )
    groups["arriving"].append(_rect(start, back, end - start, front - back))
    groups["kept"].append(_outline(values, start, back, s))
    groups["removed"].append(_rect(step, back, end - step, lug_x * s))
    groups["active"] += [
        _line(step, back, step, back + lug_x * s),
        _line(step, back + lug_x * s, end, back + lug_x * s),
    ]
    groups["fixture"].append(_rect(jaw_left + 6, back, spacer * s, front - back))
    _label(
        groups,
        jaw_left + 6 + spacer * s / 2,
        (back + front) / 2 + 5,
        "spacer",
        "middle",
    )
    radius = cutter / 2 * s
    cy = back + lug_x * s - radius
    groups["tool"].append(_el("circle", cx=end + radius + 6, cy=cy, r=radius))
    groups["arrows"].append(_line(end + 2 * radius + 14, cy, step + radius + 4, cy))
    _dimension(groups, step, end, back - JAW - 22, back, "{{cad.lug_length_in:.2f}}")
    _vdim(
        groups, end + 2 * radius + 40, back, back + lug_x * s, "{{cad.lug_x_in:.2dot}}"
    )
    _datum_label(groups, end + 4, front + 4, "LUG END", "start")
    end_y = _callouts(
        groups,
        [
            (
                jaw_left + 6 + spacer * s / 2,
                front,
                ["same-height block", "fills the left end"],
            ),
            ((start + step) / 2, front, ["ROW SIDE head", "gripped"]),
            (jaw_right, front + JAW, [f"~{_inch(over, 2)} past", "jaw side"]),
        ],
        front + JAW + 8,
        above=False,
    )
    _axes(groups, 24, end_y + 6)
    return _finish(groups, end_y + 44)


def _lug_bore(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Feed-block leadscrew bore: on SPINDLE END, OUTER END up, SEAT at fixed jaw.

    Front view (from the operator, LUG END left) and end view (from LUG END,
    SEAT and the fixed jaw left) at one scale; the bore runs down through the
    lug from OUTER END into the gap above the parallels.
    """
    if not _feed(values):
        raise CadError("diagram jig-block-lug-bore: needs the feed block's lug values")
    length = _cad(values, "length_in")
    y_length = _cad(values, "y_length_in")
    height = _cad(values, "height_in")
    lug_length = _cad(values, "lug_length_in")
    lug_x = _cad(values, "lug_x_in")
    row = _cad(values, "screw_y_nominal_in")
    z = _cad(values, "screw_z_nominal_in")
    dia = _cad(values, "screw_dia_in")
    parallel = _param_in(parameters, "edge_parallel_height_mm")
    jaw_h = _param_in(parameters, "vise_jaw_height_mm")
    t = min(110.0, 400 / y_length)
    left = 70.0
    right = left + y_length * t
    bed = 110 + (length + parallel) * t
    floor = bed - parallel * t
    top = floor - length * t
    step = left + lug_length * t
    lug_bottom = floor - lug_x * t
    jaw_top = bed - jaw_h * t
    groups = _groups(root)
    _title(groups, 20, 24, "Front view, standing on SPINDLE END")
    groups["fixture"] += [
        _rect(left - 10, floor, right - left + 20, parallel * t),
        _line(left - 30, bed, right + 30, bed),
    ]
    groups["hidden"].append(_line(left - 20, jaw_top, right + 20, jaw_top))
    _label(groups, right + 22, jaw_top + 4, "jaw top")
    groups["kept"].append(
        _el(
            "polygon",
            points=" ".join(
                f"{_fmt(x)},{_fmt(y)}"
                for x, y in (
                    (left, top),
                    (right, top),
                    (right, floor),
                    (step, floor),
                    (step, lug_bottom),
                    (left, lug_bottom),
                )
            ),
        )
    )
    bx = left + row * t
    groups["hidden"] += [
        _line(bx - dia / 2 * t, top, bx - dia / 2 * t, lug_bottom),
        _line(bx + dia / 2 * t, top, bx + dia / 2 * t, lug_bottom),
    ]
    groups["active"].append(_line(bx - dia / 2 * t, top, bx + dia / 2 * t, top))
    groups["tool"].append(_rect(bx - dia / 2 * t, top - 40, dia * t, 32))
    groups["datum"].append(_el("circle", cx=left, cy=top, r=3.5))
    _datum_label(groups, left - 6, top + 4, "X0", "end")
    _label(groups, left - 6, (top + lug_bottom) / 2 + 5, "LUG END", "end")
    _label(groups, (step + right) / 2, top - 6, "OUTER END", "middle")
    _dimension(
        groups,
        left,
        bx,
        top - 50,
        top,
        "{{cad.screw_y_min_in:.3dot}}–{{cad.screw_y_max_in:.3dot}}",
    )
    _vdim(groups, step - 12, lug_bottom, floor, "{{cad.lug_x_in:.2dot}}")

    # End view from LUG END: the lug's end face, the head behind it hidden.
    e_left = right + 110
    e_right = e_left + height * t
    _title(groups, e_left - 50, 24, "From LUG END")
    groups["jaws"] += [
        _rect(e_left - 22, jaw_top, 22, bed - jaw_top),
        _rect(e_right, jaw_top, 22, bed - jaw_top),
    ]
    groups["fixture"].append(_line(e_left - 40, bed, e_right + 40, bed))
    groups["hidden"].append(_rect(e_left, top, e_right - e_left, floor - top))
    groups["kept"].append(_rect(e_left, top, e_right - e_left, lug_bottom - top))
    ex = e_left + z * t
    groups["hidden"] += [
        _line(ex - dia / 2 * t, top, ex - dia / 2 * t, lug_bottom),
        _line(ex + dia / 2 * t, top, ex + dia / 2 * t, lug_bottom),
    ]
    groups["active"].append(_line(ex - dia / 2 * t, top, ex + dia / 2 * t, top))
    _label(groups, e_left - 11, jaw_top - 6, "fixed", "middle")
    _label(groups, e_right + 11, jaw_top - 6, "moving", "middle")
    _label(groups, e_left - 26, (top + jaw_top) / 2, "SEAT", "end")
    groups["datum"].append(_el("circle", cx=e_left, cy=top, r=3.5))
    _dimension(groups, e_left, ex, top - 50, top, "{{cad.screw_z_band_text}}")
    end_y = _callouts(
        groups,
        [
            (bx, lug_bottom, ["bore exits", "into the gap"]),
            (
                (step + right) / 2,
                floor,
                ["head on SPINDLE END,", "on 1/2 in parallels"],
            ),
            (e_left + height * t / 2, (lug_bottom + floor) / 2, ["head behind"]),
        ],
        bed + 4,
        above=False,
    )
    return _finish(groups, end_y)


BLOCK_LAYOUTS = {
    "jig-block-section": _section,
    "jig-block-holes": _holes,
    "jig-block-notch": _notch,
    "jig-block-lug-bore": _lug_bore,
}
