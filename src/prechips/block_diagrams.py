"""Carriage-block setup pictures for the ``jig-block-*`` diagram templates.

The pivot block and feed block are drawn from their adapter
values (:mod:`prechips.cad_carriage_block`) and authored holding parameters,
in the shared jig shell and conventions of :mod:`prechips.jig_diagrams`:
arriving material dashed, kept solid, removed hatched; jaws, parallels,
cutters and spacers are schematic. Vise top views look down from the
operator's side, fixed jaw at the back (top of the page). The feed block is
recognised by its lug values; the pivot block has none.
"""

from __future__ import annotations

from xml.etree import ElementTree

from prechips.cad import CadError, _shorthand
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
    JAW,
    DimText,
    _axes,
    _datum_label,
    _finish,
    _groups,
    _label,
    _param,
    _param_in,
    _title,
    _vdim,
    _vise,
)
from prechips.shaft_diagrams import _break, _callouts, _dimension

_PARALLEL_IN = 0.125  # schematic parallel thickness
_Groups = dict[str, list[Element]]


def _feed(values: dict) -> bool:
    return "lug_x_in" in values


def _row_right(values: dict) -> bool:
    """Whether ROW SIDE is on the right in a top view, SPINDLE END at the back.

    With TOP up and SPINDLE END (-X) at the back, the model's right-handed
    frame puts +Y on the right: ROW SIDE is there when rows run from +Y.
    """
    row_from = values.get("row_from")
    if row_from not in {"plus_y_side", "minus_y_side"}:
        raise CadError("cad.row_from: expected 'plus_y_side' or 'minus_y_side'")
    return row_from == "plus_y_side"


def _label_rows(
    groups: _Groups, x: float, y: float, items: list[tuple[float, float, list[str]]]
) -> float:
    """Labels at ``x`` on their own rows from ``y`` down, below their anchors.

    ``items`` are ``(anchor_x, anchor_y, lines)``. Rows run from the lowest
    anchor to the highest. Each leader runs left from its label to its own
    vertical bus left of ``x`` (lower rows further left), up to its anchor's
    height, then across to the anchor. A lower row's leader thus turns across
    above every inner bus's top and passes under every inner bus's foot, so no
    leader crosses a label or another leader's bus. Returns the next free row.
    """
    for index, (ax, ay, lines) in enumerate(sorted(items, key=lambda r: -r[1])):
        bus = x - 10 - 8 * index
        points = [(x - 4, y - 4), (bus, y - 4), (bus, ay), (ax, ay)]
        groups["leader"] += [
            _el("polyline", points=" ".join(f"{_fmt(a)} {_fmt(b)}" for a, b in points)),
            _el("circle", cx=ax, cy=ay, r=1.8, **{"class": "leader-dot"}),
        ]
        for line_index, line in enumerate(lines):
            _label(groups, x, y + line_index * 15, line)
        y += 15 * len(lines) + 8
    return y


def _outline(values: dict, left: float, back: float, s: float) -> str:
    """Finished top-view outline: Y (rows) across the page, X (stations) down it.

    The pivot block is a rectangle. The feed block's head sits at ROW SIDE,
    on the hand :func:`_row_right` gives it; its lug runs on to LUG END on the
    far side, the notch cut from SPINDLE END (the back).
    """
    across = _cad(values, "y_length_in") * s
    deep = _cad(values, "length_in") * s
    if not _feed(values):
        return _rect(left, back, across, deep)
    head = across - _cad(values, "lug_length_nominal_in") * s
    lug = _cad(values, "lug_x_nominal_in") * s
    if _row_right(values):
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
    ``width`` (on edge or on end, to the 1.64 length) or ``ends`` (on end,
    the sawn ends to the Y length). ``data-arriving`` names the arriving face
    where it differs from the hold's default; ``data-passes`` replaces the
    layer caption under the second panel. With ``faces``, ``data-offcut``
    names a piece of the same bar faced in the block's place last: a third
    panel shows it on the same parallels, its top cut at the block's finish Z.
    """
    hold = root.get("data-hold")
    offcut = root.get("data-offcut")
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
    if offcut is not None and hold != "faces":
        raise CadError("diagram data-offcut: only the 'faces' hold faces an offcut")
    names = (root.get("data-arriving") or names[0], *names[1:])
    passes = root.get("data-passes") or (
        "layers ≤ {{process.layer_in:.2dot}}; last .005–.010"
    )
    if arriving <= final:
        raise CadError(f"diagram {hold}: the blank is not larger than the part")
    clean = min(_param(parameters, "cleanup_in"), (arriving - final) / 2)
    jaw_h = _param_in(parameters, "vise_jaw_height_mm")
    cutter = _param_in(parameters, "face_cutter_dia_mm")
    s = min(110.0, 250 / (parallel + arriving), 200 / across)
    tall = (parallel + arriving) * s
    groups = _groups(root)

    def panel(
        centre: float,
        bed: float,
        title: str,
        arrive: float,
        keep: float,
        low: str,
        top: str,
        dim: str | None = None,
    ) -> None:
        """One hold. ``dim`` labels a dimension of the kept height drawn
        inside the part at its fixed-jaw side; the face names then centre in
        the rest of the width, clear of it."""
        half = across * s / 2
        left, right = centre - half, centre + half
        floor = bed - parallel * s
        jaw_top = bed - jaw_h * s
        _title(groups, centre - 150, bed - tall - 80, title)
        groups["clamp"] += [
            _rect(left - 26, jaw_top, 26, bed - jaw_top),
            _rect(right, jaw_top, 26, bed - jaw_top),
        ]
        groups["fixture-support"] += [
            _rect(left, floor, _PARALLEL_IN * s, parallel * s),
            _rect(right - _PARALLEL_IN * s, floor, _PARALLEL_IN * s, parallel * s),
        ]
        groups["fixture-vise"].append(_line(left - 46, bed, right + 46, bed))
        top_y, keep_y = floor - arrive * s, floor - keep * s
        groups["part-arriving"].append(_rect(left, top_y, right - left, arrive * s))
        groups["part-removed"].append(_rect(left, top_y, right - left, keep_y - top_y))
        groups["part-kept"].append(_rect(left, keep_y, right - left, floor - keep_y))
        groups["active-face"].append(_line(left, keep_y, right, keep_y))
        groups["cutter"].append(
            _rect(centre - cutter / 2 * s, top_y - 40, cutter * s, 32)
        )
        inset = 0.0
        if dim is not None:
            inset = 24.0
            _vdim(groups, left + 16, keep_y, floor, dim, place=DimText.ALONG_LEFT)
        if across * s - inset >= 8 * max(len(low), len(top)) + 8:
            _label(groups, centre + inset / 2, floor - 6, low, "middle")
            _label(groups, centre + inset / 2, keep_y + 16, top, "middle")
        else:
            # Narrow on edge or on end: the face down on the parallels is
            # named level with it, outside the fixed jaw; the new face's name
            # sits beside it, above the jaws.
            _label(groups, left - 30, floor - 4, low, "end")
            _label(groups, right + 6, keep_y + 5, top)
        _label(groups, left - 13, jaw_top - 6, "fixed", "middle")
        _label(groups, right + 13, jaw_top - 6, "moving", "middle")

    bed = 110 + tall
    panel(
        190,
        bed,
        f"1  {names[0]} face up: clean it, mark {names[1]}",
        arriving,
        arriving - clean,
        names[0],
        names[1],
    )
    panel(
        530,
        bed,
        f"2  {names[1]} down: cut {names[2]} to size",
        arriving - clean,
        final,
        names[1],
        names[2],
    )
    floor = bed - parallel * s
    right = 530 + across * s / 2
    _vdim(groups, right + 70, floor - final * s, floor, size, place=DimText.ALONG_LEFT)
    end_y = _callouts(
        groups,
        [
            (190, bed, [f"on {_shorthand(parallel, 2)} in parallels"]),
            (530, bed, [passes]),
        ],
        bed + 4,
        above=False,
    )
    if offcut is None:
        return _finish(groups, end_y)
    # The offcut takes the block's place, as bought both sides: only its top
    # is cut, at the Z the block's finish pass ran.
    bed = end_y + 110 + tall
    panel(
        190,
        bed,
        f"3  {offcut} offcut in its place: cut at the block's finish Z",
        arriving,
        final,
        names[0],
        offcut,
        # The offcut's height, H, is the block's: drawn inside it, from the
        # parallels to its cut top, clear of both jaws.
        "H",
    )
    end_y = _callouts(
        groups,
        [(190, bed, ["same parallels, Z unmoved:", "H = the block's height"])],
        bed + 4,
        above=False,
    )
    return _finish(groups, end_y)


def _holes(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Top-face holes: the part in the vise (``vise``) or finished (``inspect``).

    Top view, SPINDLE END at the back (fixed jaw), ROW SIDE on the hand the
    model frame gives it (:func:`_row_right`): right on the feed block, LUG END on the
    left; left on the pivot block. The holes come before the feed block's notch, so the
    vise view is the full rectangle; the finished view shows the notch.
    Beside it a stepped section through H1 and B, looking toward ROW SIDE.
    """
    mode = root.get("data-mode")
    if mode not in {"vise", "inspect"}:
        raise CadError("diagram data-mode: expected 'vise' or 'inspect'")
    feed = _feed(values)
    row_right = _row_right(values)
    length = _cad(values, "length_in")
    y_length = _cad(values, "y_length_in")
    height = _cad(values, "height_in")
    rows = [_cad(values, f"hole_y{n}_nominal_in") for n in (1, 2)]
    stations = [_cad(values, f"hole_x{n}_nominal_in") for n in (1, 2)]
    bore = (_cad(values, "bore_y_nominal_in"), _cad(values, "bore_x_nominal_in"))
    groups = _groups(root)
    s = min(110.0, 290 / y_length)
    left = 110.0
    back = 110.0 if mode == "vise" else 128.0
    front = back + length * s
    across = y_length * s
    right = left + across
    _title(
        groups,
        20,
        24,
        "Top view, SEAT down, SPINDLE END at the fixed jaw (top)"
        if mode == "vise"
        else "Top view, finished",
    )
    if mode == "vise":
        _vise(groups, left - 20, right + 20, back, front, _PARALLEL_IN * s, "", "")
    groups["part-kept"].append(
        _outline(values, left, back, s)
        if mode == "inspect"
        else _rect(left, back, across, length * s)
    )
    # Rows run from ROW SIDE into the part.
    edge, inward = (right, -1.0) if row_right else (left, 1.0)
    # Everything on TOP is cut in the vise setup; the finished view marks none.
    cut = groups["active-face"] if mode == "vise" else []
    cbore_r = _cad(values, "cbore_dia_in") / 2 * s
    names = iter(("H1", "H2", "H3", "H4"))
    for station in stations:
        for row in rows:
            x, y = edge + inward * row * s, back + station * s
            for radius in (cbore_r, _cad(values, "hole_dia_in") / 2 * s):
                groups["holes"].append(_el("circle", cx=x, cy=y, r=radius))
                cut.append(_el("circle", cx=x, cy=y, r=radius))
            _label(groups, x, y - cbore_r - 4, next(names), "middle")
    bx, by = edge + inward * bore[0] * s, back + bore[1] * s
    bore_r = _cad(values, "bore_dia_in") / 2 * s
    groups["holes"].append(_el("circle", cx=bx, cy=by, r=bore_r))
    groups["part-threads"].append(
        _el("circle", cx=bx, cy=by, r=_cad(values, "tap_drill_in") / 2 * s)
    )
    cut.append(_el("circle", cx=bx, cy=by, r=bore_r))
    _label(groups, bx, by - bore_r - 4, "B", "middle")
    groups["datum"].append(_el("circle", cx=edge, cy=back, r=3.5))
    dim_top = back - (JAW if mode == "vise" else 0) - 14
    _datum_label(
        groups,
        edge + 6 * -inward,
        dim_top + 10,
        "X0 Y0",
        "start" if row_right else "end",
    )
    # ROW SIDE is named along its face (X0), haloed over the station
    # dimensions' witness lines that cross it.
    middle = (back + front) / 2
    name_x = edge - 14 * inward
    _label(
        groups,
        name_x,
        middle,
        "ROW SIDE",
        "middle",
        transform=f"rotate(-90 {_fmt(name_x)} {_fmt(middle)})",
        **{"class": "label-halo"},
    )
    for index, row in enumerate(sorted([*rows, bore[0]])):
        _dimension(
            groups,
            edge + inward * row * s,
            edge,
            dim_top - 18 * index,
            back,
            _shorthand(row, 3),
        )
    # Stations from SPINDLE END, right of the part, each with witness lines
    # from the back edge and from its rightmost feature.
    station_x = {
        station: max(edge + inward * row * s for row in rows) for station in stations
    }
    station_x[bore[1]] = max(station_x.get(bore[1], bx), bx)
    for index, station in enumerate(sorted(station_x)):
        _vdim(
            groups,
            right + 32 + 22 * index,
            back,
            back + station * s,
            _shorthand(station, 3),
            witness=(right, station_x[station]),
            place=DimText.ALONG_LEFT,
        )
    end_y = front + (JAW + 6 if mode == "vise" else 6)
    lug_side = left if row_right else right
    if feed:
        lug = back + _cad(values, "lug_x_nominal_in") * s
        end_y = _callouts(
            groups,
            [(lug_side, (lug + front) / 2, ["LUG END"])],
            end_y,
            above=False,
        )
    if mode == "inspect":
        # On the feed block SPINDLE END is cut away over the lug: witnesses to
        # it start at the step.
        step_x = left
        if feed:
            step_x = lug_side - inward * _cad(values, "lug_length_nominal_in") * s
        _vdim(
            groups,
            left - 30,
            back,
            front,
            _shorthand(length, 2),
            witness=(step_x, left) if feed else None,
            place=DimText.ALONG_LEFT,
        )
        _dimension(groups, left, right, end_y + 22, front, _shorthand(y_length, 2))
        end_y += 30
        if feed:
            _dimension(
                groups,
                lug_side,
                step_x,
                dim_top - 54,
                back,
                "{{cad.lug_length_nominal_in:.2f}}",
            )
            # SPINDLE END is cut away over the lug: its witness starts at the
            # step, the lug face's at the lug side.
            _vdim(
                groups,
                left - 56,
                back,
                lug,
                "{{cad.lug_x_nominal_in:.2dot}}",
                witness=(step_x, lug_side),
                place=DimText.ALONG_LEFT,
            )
    # Inspect: above the left dimension column, clear of its lines.
    _axes(groups, 24, front - 34 if mode == "vise" else back - 52)

    # Stepped section through H1 and B, looking toward ROW SIDE, TOP up,
    # beside the top view; labels in a column under it. Looking toward ROW
    # SIDE puts SPINDLE END (the top view's back) on the viewer's left when
    # ROW SIDE is on the right (feed block), on the right when it is on the left
    # (pivot block): stations run from the matching edge.
    s_left = right + 32 + 22 * len(station_x) + 28
    t = min(110.0, (650 - s_left) / length)

    def sx(station: float) -> float:
        return s_left + (station if row_right else length - station) * t

    top = 70.0
    seat = top + height * t
    _title(groups, s_left - 30, top - 30, "Section through H1 and B")
    _title(groups, s_left - 30, top - 14, "(toward ROW SIDE)")
    groups["part-kept"].append(_rect(s_left, top, length * t, height * t))
    hx = sx(stations[0])
    cb_w = _cad(values, "cbore_dia_in") * t
    hole_w = _cad(values, "hole_dia_in") * t
    floor = seat - _cad(values, "cbore_floor_nominal_in") * t
    bxs = sx(bore[1])
    bore_w = _cad(values, "bore_dia_in") * t
    tap_w = _cad(values, "tap_drill_in") * t
    bore_floor = top + _cad(values, "bore_depth_nominal_in") * t
    groups["part-threads"].append(
        _rect(bxs - tap_w / 2 - 3, bore_floor, tap_w + 6, seat - bore_floor)
    )
    sections = [
        _rect(hx - cb_w / 2, top, cb_w, floor - top),
        _rect(hx - hole_w / 2, floor, hole_w, seat - floor),
        _rect(bxs - bore_w / 2, top, bore_w, bore_floor - top),
        _rect(bxs - tap_w / 2, bore_floor, tap_w, seat - bore_floor),
    ]
    groups["holes"] += sections
    cut += sections
    step_x = (hx + bxs) / 2
    groups["hidden"].append(_line(step_x, top, step_x, seat))
    s_right = s_left + length * t
    _vdim(
        groups, s_right + 18, top, seat, _shorthand(height, 2), place=DimText.ALONG_LEFT
    )
    _label(groups, s_right + 26, seat - 4, "SEAT")
    _label(groups, s_right + 26, top + 12, "TOP")
    # Each leader lands on its feature's edge facing the buses (the section's
    # left), the tap's in the upper third of its run and the hole's in the
    # lower third, so the two through-features' leaders stay apart.
    y = _label_rows(
        groups,
        s_left,
        seat + 30,
        [
            (
                bxs - bore_w / 2,
                (top + bore_floor) / 2,
                [
                    "Ø{{cad.bore_dia_min_in:.3dot}}–{{cad.bore_dia_max_in:.3dot}}, flat floor,",
                    "{{cad.bore_depth_min_in:.3dot}}–{{cad.bore_depth_max_in:.3dot}} deep",
                ],
            ),
            (
                hx - cb_w / 2,
                floor,
                [
                    "Ø{{cad.cbore_dia_nominal_in:.2dot}} counterbore, floor",
                    "{{cad.cbore_floor_min_in:.3dot}}–{{cad.cbore_floor_max_in:.3dot}} above SEAT",
                ],
            ),
            (
                bxs - tap_w / 2,
                bore_floor + (seat - bore_floor) / 3,
                ["{{cad.pivot_thread}} thru"],
            ),
            (
                hx - hole_w / 2,
                floor + 2 * (seat - floor) / 3,
                ["Ø{{cad.hole_dia_nominal_in:.3dot}} thru"],
            ),
        ],
    )
    return _finish(groups, max(end_y + 10, y))


def _notch(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Feed-block L-notch on edge: OUTER END down, LUG END out past the jaw side.

    Front view from the operator with the moving jaw left off: the fixed jaw
    behind, the block standing on its OUTER END on the parallels, the notch
    cut down from SPINDLE END to the lug face by the end mill's end, the step
    face by its side, so the inside corner is the cutter's square corner;
    then the leadscrew clearance's last plunge, down from the lug face. The
    spacer at the left jaw end is the plan's offcut, faced to the block's
    height: the bar width (`blank_width_in`) along the jaws, its sawn length
    (`offcut_length_in`) upright.
    """
    if not _feed(values):
        raise CadError("diagram jig-block-notch: needs the feed block's lug values")
    length = _cad(values, "length_in")
    y_length = _cad(values, "y_length_in")
    lug_length = _cad(values, "lug_length_nominal_in")
    lug_x = _cad(values, "lug_x_nominal_in")
    screw = _cad(values, "screw_y_nominal_in")
    screw_dia = _cad(values, "screw_dia_in")
    mill = _param(parameters, "lug_bore_mill_in")
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    jaw_h = _param_in(parameters, "vise_jaw_height_mm")
    parallel = _param_in(parameters, "edge_parallel_height_mm")
    over_min = _param(parameters, "notch_overhang_min_in")
    over_max = _param(parameters, "notch_overhang_max_in")
    spacer = _param(parameters, "blank_width_in")
    spacer_height = _param(parameters, "offcut_length_in")
    cutter = _param_in(parameters, "half_cutter_dia_mm")
    over = (over_min + over_max) / 2
    s = min(70.0, 600 / (jaw + over + cutter))
    jaw_left = 40.0
    jaw_right = jaw_left + jaw * s
    bed = 110 + (parallel + max(length, spacer_height)) * s
    floor = bed - parallel * s
    top = floor - length * s
    jaw_top = bed - jaw_h * s
    end = jaw_right + over * s
    start = end - y_length * s
    step = end - lug_length * s
    lug_face = top + lug_x * s
    spacer_right = jaw_left + 6 + spacer * s
    groups = _groups(root)
    _title(groups, 20, 24, "Front view, moving jaw not shown: on edge, SPINDLE END up")
    # The fixed jaw stands behind the part: a clamp drawn dashed and unfilled,
    # so the spacer and parallels in front of it show. Its name sits in the
    # gap between the spacer and the block.
    groups["clamp"].append(
        _rect(
            jaw_left,
            jaw_top,
            jaw_right - jaw_left,
            bed - jaw_top,
            fill="none",
            stroke_dasharray="4 3",
        )
    )
    gap = (spacer_right + start) / 2
    _label(groups, gap, jaw_top + 16, "fixed jaw", "middle")
    _label(groups, gap, jaw_top + 31, "(behind)", "middle")
    groups["fixture-support"] += [
        _rect(jaw_left + 6, floor, jaw_right - jaw_left - 6, parallel * s),
        _rect(jaw_left + 6, floor - spacer_height * s, spacer * s, spacer_height * s),
    ]
    groups["fixture-vise"].append(_line(jaw_left - 20, bed, end + 40, bed))
    groups["hidden"].append(_line(jaw_right, jaw_top - 14, jaw_right, bed + 8))
    groups["part-arriving"].append(_rect(start, top, end - start, length * s))
    groups["part-kept"].append(
        _el(
            "polygon",
            points=" ".join(
                f"{_fmt(x)},{_fmt(y)}"
                for x, y in (
                    (start, top),
                    (step, top),
                    (step, lug_face),
                    (end, lug_face),
                    (end, floor),
                    (start, floor),
                )
            ),
        )
    )
    groups["part-removed"].append(_rect(step, top, end - step, lug_face - top))
    # The leadscrew clearance through the lug: its last plunge, Z zeroed on
    # the lug face just cut and lug_bore_mill_in down from it, is cut here.
    bx = end - screw * s
    half = screw_dia / 2 * s
    back_floor = lug_face + mill * s
    groups["hidden"] += [
        _line(bx - half, lug_face, bx - half, floor),
        _line(bx + half, lug_face, bx + half, floor),
    ]
    groups["active-face"] += [
        _line(step, top, step, lug_face),
        _line(step, lug_face, end, lug_face),
        _line(bx - half, lug_face, bx - half, back_floor),
        _line(bx + half, lug_face, bx + half, back_floor),
    ]
    mid = (step + end) / 2
    groups["cutter"].append(_rect(mid - cutter / 2 * s, top - 44, cutter * s, 36))
    groups["datum"].append(_el("circle", cx=end, cy=top, r=3.5))
    _datum_label(groups, end + 6, top - 4, "X0 Z0", "start")
    _dimension(groups, step, end, top - 58, top, "{{cad.lug_length_nominal_in:.2f}}")
    # SPINDLE END is cut away over the lug: its witness starts at the step.
    _vdim(
        groups,
        end + 20,
        top,
        lug_face,
        "{{cad.lug_x_nominal_in:.2dot}}",
        witness=(step, end),
        place=DimText.ALONG_LEFT,
    )
    _label(groups, (start + step) / 2, top - 6, "SPINDLE END", "middle")
    _label(groups, end + 6, floor - 4, "LUG END")
    _dimension(
        groups,
        jaw_right,
        end,
        bed + 24,
        bed,
        "{{process.notch_overhang_min_in:.2f}}–{{process.notch_overhang_max_in:.2f}}",
    )
    end_y = _callouts(
        groups,
        [
            (
                jaw_left + 6 + spacer * s / 2,
                floor,
                ["spacer offcut, faced to", "the block's height"],
            ),
            (
                (start + jaw_right) / 2,
                floor,
                ["OUTER END down,", f"on {_shorthand(parallel, 2)} in parallels"],
            ),
            (jaw_right, bed, ["jaw side"]),
            (bx, back_floor, ["3/8 plunge, Z0", "on the lug face"]),
        ],
        bed + 40,
        above=False,
    )
    return _finish(groups, end_y)


def _lug_bore(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Feed-block leadscrew clearance: on SPINDLE END, OUTER END up, SEAT at
    the fixed jaw.

    Front view (from the operator: the model's hand puts LUG END on the right)
    and end view (from LUG END: SEAT and the fixed jaw on the right) at one
    scale. The clearance comes before the notch: the block stands on all of
    SPINDLE END. The pilot (``pilot_dia_mm``) runs blind from OUTER END to
    ``lug_bore_depth_mm``, past the lug face to come (drawn hidden), which the
    notch opens; the 3/8 end mill follows it ``lug_bore_mill_in`` deep, and
    the notch setup plunges the rest from the lug face.
    """
    if not _feed(values):
        raise CadError("diagram jig-block-lug-bore: needs the feed block's lug values")
    length = _cad(values, "length_in")
    y_length = _cad(values, "y_length_in")
    height = _cad(values, "height_in")
    lug_length = _cad(values, "lug_length_nominal_in")
    lug_x = _cad(values, "lug_x_nominal_in")
    row = _cad(values, "screw_y_nominal_in")
    z = _cad(values, "screw_z_nominal_in")
    dia = _cad(values, "screw_dia_in")
    parallel = _param_in(parameters, "edge_parallel_height_mm")
    jaw_h = _param_in(parameters, "vise_jaw_height_mm")
    pilot = _param_in(parameters, "pilot_dia_mm")
    depth = _param_in(parameters, "lug_bore_depth_mm")
    mill = _param(parameters, "lug_bore_mill_in")
    t = min(110.0, 400 / y_length)
    left = 90.0
    right = left + y_length * t
    bed = 110 + (length + parallel) * t
    floor = bed - parallel * t
    top = floor - length * t
    step = right - lug_length * t
    lug_bottom = floor - lug_x * t
    jaw_top = bed - jaw_h * t
    pilot_floor = top + depth * t
    mill_floor = top + mill * t
    groups = _groups(root)

    def bore(x: float) -> None:
        """The 3/8 plunge over the deeper pilot, both hidden in the part."""
        for half, low in ((dia / 2 * t, mill_floor), (pilot / 2 * t, pilot_floor)):
            groups["hidden"] += [
                _line(x - half, top, x - half, low),
                _line(x + half, top, x + half, low),
                _line(x - half, low, x + half, low),
            ]
        groups["active-face"].append(_line(x - dia / 2 * t, top, x + dia / 2 * t, top))

    _title(groups, 20, 24, "Front view, standing on SPINDLE END")
    groups["fixture-support"].append(
        _rect(left - 10, floor, right - left + 20, parallel * t)
    )
    groups["fixture-vise"].append(_line(left - 30, bed, right + 30, bed))
    groups["hidden"].append(_line(left - 20, jaw_top, right + 20, jaw_top))
    _label(groups, left - 22, jaw_top + 4, "jaw top", "end")
    # The whole block: the notch (hidden outline) comes off later.
    groups["part-kept"].append(_rect(left, top, right - left, floor - top))
    groups["hidden"] += [
        _line(step, lug_bottom, right, lug_bottom),
        _line(step, lug_bottom, step, floor),
    ]
    bx = right - row * t
    bore(bx)
    groups["cutter"].append(_rect(bx - dia / 2 * t, top - 40, dia * t, 32))
    groups["datum"].append(_el("circle", cx=right, cy=top, r=3.5))
    _datum_label(groups, right + 6, top + 4, "X0", "start")
    _label(groups, right + 6, (top + lug_bottom) / 2 + 5, "LUG END", "start")
    _label(groups, (left + step) / 2, top - 6, "OUTER END", "middle")
    _dimension(
        groups,
        bx,
        right,
        top - 50,
        top,
        "{{cad.screw_y_min_in:.3dot}}–{{cad.screw_y_max_in:.3dot}}",
    )
    # Witness lines from each floor (drawn across its own hole) to its depth.
    _vdim(
        groups,
        bx - dia / 2 * t - 14,
        top,
        mill_floor,
        "{{process.lug_bore_mill_in:.2dot}}",
        witness=(bx - dia / 2 * t, bx - dia / 2 * t),
        place=DimText.ALONG_LEFT,
    )
    _vdim(
        groups,
        bx - dia / 2 * t - 40,
        top,
        pilot_floor,
        "{{process.lug_bore_depth_mm:in.2dot}}",
        witness=(bx - pilot / 2 * t, bx - pilot / 2 * t),
        place=DimText.ALONG_LEFT,
    )

    # End view from LUG END: the whole end face; the lug face to come hidden.
    e_left = right + 110
    e_right = e_left + height * t
    _title(groups, e_left - 50, 24, "From LUG END")
    groups["clamp"] += [
        _rect(e_left - 22, jaw_top, 22, bed - jaw_top),
        _rect(e_right, jaw_top, 22, bed - jaw_top),
    ]
    groups["fixture-vise"].append(_line(e_left - 40, bed, e_right + 40, bed))
    groups["part-kept"].append(_rect(e_left, top, e_right - e_left, floor - top))
    ex = e_right - z * t
    groups["hidden"].append(_line(e_left, lug_bottom, e_right, lug_bottom))
    bore(ex)
    _label(groups, e_left - 11, jaw_top - 6, "moving", "middle")
    _label(groups, e_right + 11, jaw_top - 6, "fixed", "middle")
    _label(groups, e_right + 11, jaw_top - 20, "SEAT", "middle")
    groups["datum"].append(_el("circle", cx=e_right, cy=top, r=3.5))
    _dimension(groups, ex, e_right, top - 50, top, "{{cad.screw_z_band_text}}")
    end_y = _callouts(
        groups,
        [
            (
                (left + step) / 2,
                floor,
                ["all of SPINDLE END", f"on {_shorthand(parallel, 2)} in parallels"],
            ),
            (
                bx,
                pilot_floor,
                ["pilot past the lug face", "to come; the notch opens it"],
            ),
            (e_left + height * t / 2, lug_bottom, ["lug face to come"]),
        ],
        bed + 4,
        above=False,
    )
    return _finish(groups, end_y)


def _saw(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Two saw cuts: a strip off the bar end, then the strip across to a blank.

    Top view, bar end at the left, one as-bought edge at the top: cut 1 parts
    the strip from the bar, cut 2 parts the blank from the strip's offcut.
    """
    length = _param(parameters, "blank_length_in")
    width = _param(parameters, "blank_width_in")
    bar = _param(parameters, "bar_width_in")
    kerf = _param(parameters, "kerf_in")
    if width + kerf >= bar:
        raise CadError("diagram jig-block-saw: the blank does not fit the bar width")
    rest = 1.5  # schematic stub of the remaining bar, inches
    s = min(70.0, 560 / (length + kerf + rest), 240 / bar)
    x, top = 90.0, 74.0
    bottom = top + bar * s
    x1 = x + length * s
    cut = top + width * s
    groups = _groups(root)
    _title(groups, 40, 24, "Top view, bar end at the left")
    groups["part-kept"].append(_rect(x, top, x1 - x, cut - top))
    groups["part-removed"] += [
        _rect(x1, top, kerf * s, bottom - top),
        _rect(x, cut, x1 - x, kerf * s),
    ]
    groups["part-rest"].append(
        _rect(x, cut + kerf * s, x1 - x, bottom - cut - kerf * s)
    )
    end = x1 + kerf * s + rest * s
    groups["part-rest"].append(
        _el(
            "path",
            d=f"M{_fmt(x1 + kerf * s)} {_fmt(top)}H{_fmt(end)}"
            f"{_break(end, top, bottom)}H{_fmt(x1 + kerf * s)}Z",
        )
    )
    _label(groups, (x + x1) / 2, (top + cut) / 2 + 5, "blank", "middle")
    _label(groups, (x + x1) / 2, (cut + bottom) / 2 + 5, "offcut", "middle")
    _dimension(groups, x, x1, top - 16, top, "{{process.blank_length_in:.2f}}")
    _vdim(
        groups,
        x - 20,
        top,
        cut,
        "{{process.blank_width_in:.2f}}",
        place=DimText.ALONG_LEFT,
    )
    _label(groups, x - 30, bottom - 4, "bar end", "end")
    end_y = _callouts(
        groups,
        [
            (x1 + kerf * s / 2, bottom, ["cut 1, waste side", "of the line"]),
            (x + 12, cut + kerf * s / 2, ["cut 2 across", "the strip"]),
        ],
        bottom + 4,
        above=False,
    )
    return _finish(groups, end_y)


BLOCK_LAYOUTS = {
    "jig-block-saw": _saw,
    "jig-block-section": _section,
    "jig-block-holes": _holes,
    "jig-block-notch": _notch,
    "jig-block-lug-bore": _lug_bore,
}
