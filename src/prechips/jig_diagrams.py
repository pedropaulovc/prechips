"""Trammel-jig setup pictures for the ``jig-*`` diagram templates.

The end bracket (TL-28) and feed lever (TL-26) are drawn from their adapter
values and authored holding parameters. Vise top views look down from the
operator's side: +X right from the part's X0 end, +Y toward the operator, down
the page. Arriving material is dashed, material kept after the setup solid,
material removed in the setup hatched, threads cross-hatched and pieces for
another sheet grey. Jaws, parallels, cutters, taps, kerfs and soft jaws are
schematic symbols owned by the SVG styles; only their positions follow the
holding parameters. Labels outside the part sit on rows spread so they cannot
overlap, with leaders back to their features.
"""

from __future__ import annotations

from fractions import Fraction
from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import (
    MM_PER_IN,
    Element,
    Layout,
    _cad,
    _el,
    _fmt,
    _line,
    _positive,
    _rect,
    _text,
    _view,
)
from prechips.shaft_diagrams import _callouts, _dimension

JAW = 14.0  # schematic jaw-plate depth in top views
LEGEND = 44.0
GROUPS = (
    "fixture",
    "jaws",
    "hidden",
    "other",
    "arriving",
    "kept",
    "removed",
    "threads",
    "holes",
    "tool",
    "active",
    "datum",
    "arrows",
    "dims",
    "leaders",
    "labels",
    "titles",
)


def _groups() -> dict[str, list[Element]]:
    return {name: [] for name in GROUPS}


def _param(parameters: dict, key: str) -> float:
    return _positive(parameters, key, "process")


def _param_in(parameters: dict, key: str) -> float:
    """An authored ``*_mm`` parameter in inches."""
    return _param(parameters, key) / MM_PER_IN


def _count(parameters: dict, key: str) -> int:
    value = _param(parameters, key)
    if value != int(value):
        raise CadError(f"process.{key}: must be a whole number for the diagram")
    return int(value)


def _stations(values: dict) -> list[float]:
    stations = values.get("hole_x_in")
    if not isinstance(stations, list) or len(stations) != 2:
        raise CadError("cad.hole_x_in: expected two hole stations for the diagram")
    mapping = dict(enumerate(stations))
    return [_positive(mapping, index, "cad.hole_x_in") for index in mapping]


def _trim(blank: float, length: float, key: str) -> float:
    if blank < length:
        raise CadError(f"process.{key}: shorter than the finished length")
    return (blank - length) / 2


def _inch(value: float, places: int = 3) -> str:
    text = f"{value:.{places}f}"
    return text[1:] if text.startswith("0.") else text


def _fraction(value: float) -> str:
    fraction = Fraction(value).limit_denominator(64)
    whole, part = divmod(fraction.numerator, fraction.denominator)
    if part == 0:
        return str(whole)
    tail = f"{part}/{fraction.denominator}"
    return f"{whole} {tail}" if whole else tail


def _title(groups: dict[str, list[Element]], x: float, y: float, text: str) -> None:
    groups["titles"].append(_text(x, y, text))


def _label(
    groups: dict[str, list[Element]],
    x: float,
    y: float,
    text: str,
    anchor: str = "start",
    **attrs: float | str,
) -> None:
    groups["labels"].append(_text(x, y, text, text_anchor=anchor, **attrs))


def _datum_label(
    groups: dict[str, list[Element]], x: float, y: float, text: str, anchor: str
) -> None:
    _label(groups, x, y, text, anchor, fill="#b22", font_weight="bold")


def _vise(
    groups: dict[str, list[Element]],
    left: float,
    right: float,
    back: float,
    front: float,
    parallel: float,
    fixed: str,
    moving: str,
    labels_right: bool = False,
) -> None:
    """Jaws behind and in front of the work; parallels under it, hidden."""
    groups["jaws"] += [
        _rect(left, back - JAW, right - left, JAW),
        _rect(left, front, right - left, JAW),
    ]
    groups["hidden"] += [
        _rect(left, back, right - left, parallel),
        _rect(left, front - parallel, right - left, parallel),
    ]
    x, anchor = (right - 4, "end") if labels_right else (left + 4, "start")
    _label(groups, x, back - JAW - 5, fixed, anchor)
    _label(groups, x, front + JAW + 15, moving, anchor)


def _blank(
    groups: dict[str, list[Element]],
    x0: float,
    x1: float,
    keep0: float,
    keep1: float,
    top: float,
    bottom: float,
) -> None:
    """Arriving outline x0..x1; kept keep0..keep1; the rest removed."""
    height = bottom - top
    groups["arriving"].append(_rect(x0, top, x1 - x0, height))
    if keep0 > x0:
        groups["removed"].append(_rect(x0, top, keep0 - x0, height))
        groups["active"].append(_line(keep0, top, keep0, bottom))
    if keep1 < x1:
        groups["removed"].append(_rect(keep1, top, x1 - keep1, height))
        groups["active"].append(_line(keep1, top, keep1, bottom))
    groups["kept"].append(_rect(keep0, top, keep1 - keep0, height))


def _cutter(
    groups: dict[str, list[Element]],
    x: float,
    radius: float,
    start: float,
    end: float,
    at_end: bool,
) -> None:
    """End mill symbol and its feed arrow along ``x`` from ``start`` to ``end``.

    The symbol sits at the end (``at_end``) or start of the stroke, clear of
    the arrow.
    """
    step = (radius + 2) * (1 if end > start else -1)
    if at_end:
        groups["arrows"].append(_line(x, start, x, end - step))
    else:
        groups["arrows"].append(_line(x, start + step, x, end))
    y = end if at_end else start
    groups["tool"].append(_el("circle", cx=x, cy=y, r=radius))


def _axes(groups: dict[str, list[Element]], x: float, y: float) -> None:
    groups["arrows"] += [_line(x, y, x + 36, y), _line(x, y, x, y + 28)]
    _label(groups, x + 40, y + 5, "+X")
    _label(groups, x + 6, y + 32, "+Y")


def _finish(groups: dict[str, list[Element]], bottom: float, **view: float) -> Layout:
    """Legend under ``bottom`` and the picture height."""
    legend_y = bottom + 12
    return _view(**view, legend_x=12.0, legend_y=legend_y, height=legend_y + LEGEND), (
        groups
    )


def _cutlist(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Saw setup: the shared 1165 bar's cut list, this sheet's pieces kept."""
    active = root.get("data-active")
    if active == "lever":
        lever = _param(parameters, "blank_length_in")
        bracket = _param(parameters, "bracket_blank_in")
        brackets = _count(parameters, "bracket_quantity")
    elif active == "brackets":
        lever = _param(parameters, "lever_blank_in")
        bracket = _param(parameters, "blank_length_in")
        brackets = _count(parameters, "quantity")
    else:
        raise CadError("diagram data-active: expected 'lever' or 'brackets'")
    bar = _param(parameters, "bar_length_in")
    kerf = _param(parameters, "kerf_in")
    width = _param(parameters, "blank_width_in")
    minimum = _param(parameters, "blank_min_length_in")
    pieces = [("lever", lever, "TL-26 lever")] + [("brackets", bracket, "TL-28")] * (
        brackets
    )
    rest = bar - sum(length for _, length, _ in pieces) - kerf * len(pieces)
    if rest < 0:
        raise CadError("process.bar_length_in: the cut list is longer than the bar")
    scale = (720 - 80) / bar
    x, top = 40.0, 74.0
    bottom = top + width * scale
    groups = _groups()
    _title(groups, 40, 24, "Top view of the bar, measured end at the left")
    callouts = []
    number = 0
    for kind, length, name in pieces:
        x1 = x + length * scale
        groups["kept" if kind == active else "other"].append(
            _rect(x, top, x1 - x, bottom - top)
        )
        _label(groups, (x + x1) / 2, (top + bottom) / 2 + 5, name, "middle")
        _dimension(groups, x, x1, top - 16, top, f"{length:.2f}")
        if kind == active:
            number += 1
            what = "lever blank" if kind == "lever" else f"blank {number}"
            callouts.append(((x + x1) / 2, bottom, [what, f"≥{minimum:.2f}"]))
        groups["removed"].append(_rect(x1, top, kerf * scale, bottom - top))
        x = x1 + kerf * scale
    groups["other"].append(_rect(x, top, rest * scale, bottom - top))
    _label(
        groups,
        x + rest * scale / 2,
        (top + bottom) / 2 + 5,
        f"rest ≈{rest:.1f}, keep",
        "middle",
    )
    first_kerf = 40 + lever * scale + kerf * scale / 2
    callouts.append(
        (first_kerf, bottom, [f"kerf ~{_fraction(kerf)}", "waste side of line"])
    )
    end = _callouts(groups, callouts, bottom + 4, above=False)
    return _finish(groups, end)


def _bracket_ends(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """End-bracket setup 2: two holds; INNER END cleaned, then cut to length."""
    blank = _param(parameters, "blank_length_in")
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    over = _param_in(parameters, "overhang_mm")
    parallel = _param_in(parameters, "parallel_thickness_mm")
    cutter = _param_in(parameters, "cutter_dia_mm")
    trim = _trim(blank, length, "blank_length_in")
    scale = min(48.0, 300 / (jaw + over + cutter + 0.3))
    trim_px = max(trim * scale, 4.0)
    radius = cutter / 2 * scale
    back = 96.0
    front = back + width * scale
    groups = _groups()

    # Hold 1: blank end ~over past the left jaw side; clean up INNER END.
    jaw_left = 24 + (cutter + over) * scale
    left = jaw_left - over * scale
    inner = left + trim_px
    _title(groups, 20, 30, "1  Left end out: clean up INNER END")
    _vise(
        groups,
        jaw_left,
        jaw_left + jaw * scale,
        back,
        front,
        parallel * scale,
        "fixed jaw",
        "moving jaw",
    )
    _blank(groups, left, left + blank * scale, inner, left + blank * scale, back, front)
    _label(
        groups,
        (inner + left + blank * scale) / 2,
        (back + front) / 2 + 5,
        "1 in face up",
        "middle",
    )
    _cutter(groups, inner - radius, radius, back, front + radius + 4, at_end=True)

    # Hold 2: slid right, the far end ~over past the right jaw side.
    jaw_right = 712 - (cutter + over) * scale
    end = jaw_right + over * scale
    zero = end - (blank - trim) * scale
    finish = zero + length * scale
    if end - finish < 4:
        finish = end - 4
    _title(groups, 378, 30, "2  Slid right: X0 INNER END, cut to length")
    _vise(
        groups,
        jaw_right - jaw * scale,
        jaw_right,
        back,
        front,
        parallel * scale,
        "fixed jaw",
        "moving jaw",
    )
    _blank(groups, zero, end, zero, finish, back, front)
    groups["datum"] += [
        _line(zero, back, zero, front),
        _el("circle", cx=zero, cy=back, r=3.5),
    ]
    _datum_label(groups, zero + 4, (back + front) / 2 + 5, "X0", "start")
    _cutter(groups, finish + radius, radius, front + radius + 4, back - 2, at_end=False)
    _dimension(groups, zero, finish, front + JAW + 34, front, "{{cad.length_in:.3f}}")
    end_y = _callouts(
        groups,
        [
            (
                inner - radius,
                front + 2 * radius + 4,
                ["1/2 end mill", "feed toward you"],
            ),
            (inner, front, ["INNER END"]),
            (
                finish + radius,
                front + 2 * radius + 4,
                ["feed away", "last pass L + D/2"],
            ),
        ],
        front + JAW + 44,
        above=False,
    )
    _axes(groups, 660, end_y + 4)
    return _finish(groups, end_y + 36)


def _bracket_tap(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """End-bracket setups 3/4: on edge between parallels; section at H1."""
    face = root.get("data-face")
    if face not in {"bar", "kp08"}:
        raise CadError("diagram data-face: expected 'bar' or 'kp08'")
    length = _cad(values, "length_in")
    thickness = _cad(values, "thickness_in")
    width = _cad(values, "width_in")
    row = _cad(values, "row_in")
    drill = _cad(values, "tap_drill_in")
    stations = _stations(values)
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    over = _param_in(parameters, "overhang_mm")
    parallel = _param_in(parameters, "parallel_thickness_mm")
    parallel_height = _param_in(parameters, "parallel_height_mm")
    jaw_height = _param_in(parameters, "vise_jaw_height_mm")
    touch = _param(parameters, "y_touch_x_in")
    groups = _groups()

    # Top view: INNER END ~over out left; ROW EDGE at the fixed jaw for BAR
    # SIDE, at the moving jaw once rolled over for KP08 SIDE.
    scale = 52.0
    zero, back = 92.0, 130.0
    front = back + thickness * scale
    row_y = back + (row if face == "bar" else thickness - row) * scale
    jaw_left = zero + over * scale
    _title(groups, 20, 30, "Top view")
    _vise(
        groups,
        jaw_left,
        jaw_left + jaw * scale,
        back,
        front,
        parallel * scale,
        "fixed jaw · ROW EDGE" if face == "bar" else "fixed jaw · Y0",
        "moving jaw" if face == "bar" else "moving jaw · ROW EDGE",
        labels_right=True,
    )
    end = zero + length * scale
    groups["kept"].append(_rect(zero, back, end - zero, front - back))
    hole_r = drill / 2 * scale
    for index, station in enumerate(stations):
        x = zero + station * scale
        groups["holes"].append(_el("circle", cx=x, cy=row_y, r=hole_r))
        groups["active"].append(
            _el("circle", cx=x, cy=row_y, r=hole_r + 3, fill="none")
        )
        _dimension(groups, zero, x, back - JAW - 10 - 18 * index, back, _inch(station))
    groups["datum"].append(_el("circle", cx=zero, cy=back, r=3.5))
    _datum_label(groups, zero - 4, back - 6, "X0 Y0", "end")
    _label(groups, zero - 4, (back + front) / 2 + 5, "INNER END", "end")
    finder = zero + touch * scale
    finder_r = 0.1 * scale
    groups["tool"].append(_el("circle", cx=finder, cy=back + finder_r, r=finder_r))
    _datum_label(
        groups,
        finder + finder_r + 5,
        (back + front) / 2 + 5,
        f"Y0 touch, ~X {touch:g}",
        "start",
    )
    up = "BAR SIDE up" if face == "bar" else "KP08 SIDE up"
    end_y = _callouts(
        groups,
        [
            (zero + stations[0] * scale, row_y, ["H1"]),
            (
                (zero + stations[0] * scale + zero + stations[1] * scale) / 2,
                front,
                [up],
            ),
            (zero + stations[1] * scale, row_y, ["H2"]),
        ],
        front + JAW + 22,
        above=False,
    )
    _axes(groups, 24, end_y + 6)
    top_bottom = end_y + 40

    # Section through H1 looking +X: fixed jaw left, moving jaw right.
    s = 90.0
    centre, bed = 560.0, 300.0
    half = thickness * s / 2
    part_left, part_right = centre - half, centre + half
    para_top = bed - parallel_height * s
    part_top = para_top - width * s
    jaw_top = bed - jaw_height * s
    _title(groups, 470, 30, "Section at H1, looking +X")
    _title(groups, 470, 46, "(fixed jaw left)")
    groups["jaws"] += [
        _rect(part_left - 28, jaw_top, 28, bed - jaw_top),
        _rect(part_right, jaw_top, 28, bed - jaw_top),
    ]
    groups["fixture"] += [
        _rect(part_left, para_top, parallel * s, bed - para_top),
        _rect(part_right - parallel * s, para_top, parallel * s, bed - para_top),
        _line(part_left - 40, bed, part_right + 40, bed),
    ]
    groups["kept"].append(_rect(part_left, part_top, part_right - part_left, width * s))
    hole_x = part_left + (row if face == "bar" else thickness - row) * s
    hole_w = drill * s
    thread_w = hole_w + 8

    def zone(from_top: bool, low: float, high: float, active: bool) -> float:
        """Full thread to ``low`` hatched; ``low``..``high`` lighter."""
        face_y = part_top if from_top else part_top + width * s
        sign = 1 if from_top else -1
        for depth, opacity in ((low, 1.0), (high, 0.45)):
            y0, y1 = sorted((face_y, face_y + sign * depth * s))
            groups["threads"].append(
                _rect(hole_x - thread_w / 2, y0, thread_w, y1 - y0, opacity=opacity)
            )
        y0, y1 = sorted((face_y, face_y + sign * high * s))
        if active:
            groups["active"].append(
                _rect(hole_x - thread_w / 2 - 2, y0, thread_w + 4, y1 - y0, fill="none")
            )
        return (y0 + y1) / 2

    up_key = "bar" if face == "bar" else "kp08"
    up_zone = zone(
        True,
        _cad(values, f"{up_key}_thread_min_in"),
        _cad(values, f"{up_key}_thread_max_in"),
        True,
    )
    if face == "kp08":
        down_zone = zone(
            False,
            _cad(values, "bar_thread_min_in"),
            _cad(values, "bar_thread_max_in"),
            False,
        )
    groups["holes"].append(_rect(hole_x - hole_w / 2, part_top, hole_w, width * s))
    tips = [_cad(values, f"{up_key}_tip_{end}_in") for end in ("min", "max")]
    for tip in tips:
        y = part_top + tip * s
        groups["datum"].append(
            _line(
                hole_x - thread_w / 2 - 6,
                y,
                hole_x + thread_w / 2 + 6,
                y,
                stroke_width=1.5,
            )
        )
    tool_h = 40.0
    groups["tool"].append(
        _rect(hole_x - hole_w / 2, part_top - 8 - tool_h, hole_w, tool_h)
    )
    groups["arrows"].append(
        _line(
            hole_x + hole_w / 2 + 8,
            part_top - 44,
            hole_x + hole_w / 2 + 8,
            part_top - 12,
        )
    )
    _label(groups, part_left - 4, part_top + 13, up.removesuffix(" up"), "end")
    low, high = (_cad(values, f"{up_key}_thread_{end}_in") for end in ("min", "max"))
    rows = [
        (
            part_top - 30,
            hole_x + hole_w / 2 + 8,
            part_top - 30,
            ["#29 drill, taps" if face == "bar" else "taps"],
        ),
        (
            part_top + 14,
            hole_x + thread_w / 2,
            up_zone,
            ["full thread", f"{_inch(low)}–{_inch(high)}"],
        ),
        (
            part_top + 58,
            hole_x + thread_w / 2 + 6,
            part_top + sum(tips) / 2 * s,
            ["tap tip mark", f"{_inch(tips[0])}–{_inch(tips[1])}"],
        ),
    ]
    if face == "kp08":
        low_b = _cad(values, "bar_thread_min_in")
        high_b = _cad(values, "bar_thread_max_in")
        rows.append(
            (
                part_top + 108,
                hole_x + thread_w / 2,
                down_zone,
                ["BAR thread", f"{_inch(low_b)}–{_inch(high_b)}"],
            )
        )
    gap = thickness - 2 * parallel
    rows.append(
        (bed - 30, centre, (para_top + bed) / 2, [f"{_fraction(gap)} gap below"])
    )
    for y, ax, ay, lines in rows:
        groups["leaders"] += [
            _el("polyline", points=f"{_fmt(618)} {_fmt(y - 4)} {_fmt(ax)} {_fmt(ay)}"),
            _el("circle", cx=ax, cy=ay, r=1.8, fill="#333"),
        ]
        for index, line in enumerate(lines):
            _label(groups, 622, y + index * 15, line)
    return _finish(groups, max(top_bottom, bed + 8))


def _bracket_inspect(
    values: dict, parameters: dict, root: ElementTree.Element
) -> Layout:
    """End-bracket setup 5: finished side and end views with both thread zones."""
    length = _cad(values, "length_in")
    thickness = _cad(values, "thickness_in")
    width = _cad(values, "width_in")
    row = _cad(values, "row_in")
    drill = _cad(values, "tap_drill_in")
    tolerance = _cad(values, "station_tol_mm")
    stations = _stations(values)
    groups = _groups()
    s = 150.0
    x0, top = 110.0, 70.0
    x1, bottom = x0 + length * s, top + width * s
    hole_w = drill * s
    thread_w = hole_w + 8

    def zones(centre: float) -> None:
        for face_y, sign, key in ((top, 1, "kp08"), (bottom, -1, "bar")):
            for end, opacity in (("min", 1.0), ("max", 0.45)):
                depth = _cad(values, f"{key}_thread_{end}_in") * s
                y0, y1 = sorted((face_y, face_y + sign * depth))
                groups["threads"].append(
                    _rect(centre - thread_w / 2, y0, thread_w, y1 - y0, opacity=opacity)
                )

    _title(groups, 20, 30, "Side view, KP08 SIDE up")
    groups["kept"].append(_rect(x0, top, x1 - x0, bottom - top))
    for index, station in enumerate(stations):
        x = x0 + station * s
        zones(x)
        groups["hidden"] += [
            _line(x - hole_w / 2, top, x - hole_w / 2, bottom),
            _line(x + hole_w / 2, top, x + hole_w / 2, bottom),
        ]
        y = bottom + 22 + 30 * index
        groups["dims"] += [
            _line(x0, bottom, x0, y + 4),
            _line(x, bottom, x, y + 4),
            _line(x0, y, x, y, marker_start="url(#arr)", marker_end="url(#arr)"),
        ]
        text = f"{station * MM_PER_IN:.3f} ±{tolerance:.2f} mm"
        if len(text) * 7.5 < x - x0 - 10:
            _label(groups, (x0 + x) / 2, y - 5, text, "middle")
        else:
            _label(groups, x + 6, y + 5, text)
        _label(groups, x, top - 6, f"H{index + 1}", "middle")
    middle = (x0 + stations[0] * s + x0 + stations[1] * s) / 2
    reach = x0 + stations[1] * s - thread_w / 2 - 4
    for y, key in ((top + 24, "kp08"), (bottom - 14, "bar")):
        low = _cad(values, f"{key}_thread_min_in")
        high = _cad(values, f"{key}_thread_max_in")
        text = f"full thread {_inch(low)}–{_inch(high)}"
        _label(groups, middle, y, text, "middle")
        groups["leaders"].append(_line(middle + 90, y - 4, reach, y - 4))
    _label(
        groups, middle, (top + bottom) / 2 + 5, "{{cad.thread}}, both faces", "middle"
    )
    _label(groups, x0 - 6, top + 14, "KP08 SIDE", "end")
    _label(groups, x0 - 6, bottom - 4, "BAR SIDE", "end")
    _label(groups, x0 - 6, (top + bottom) / 2 + 5, "INNER END", "end")

    # End view from INNER END, ROW EDGE on the left.
    e0 = 600.0
    e1 = e0 + thickness * s
    hole_x = e0 + row * s
    _title(groups, 560, 30, "End view")
    groups["kept"].append(_rect(e0, top, e1 - e0, bottom - top))
    zones(hole_x)
    groups["hidden"] += [
        _line(hole_x - hole_w / 2, top, hole_x - hole_w / 2, bottom),
        _line(hole_x + hole_w / 2, top, hole_x + hole_w / 2, bottom),
    ]
    _dimension(groups, e0, hole_x, bottom + 22, bottom, _inch(row))
    _label(groups, e0, bottom + 62, "ROW EDGE", "middle")
    groups["leaders"].append(_line(e0, bottom + 49, e0, bottom + 28))
    return _finish(groups, bottom + 70)


def _lever_hold(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Feed-lever setups 2/3: ZERO END out left, then the grip end out right."""
    hold = root.get("data-hold")
    if hold not in {"zero", "grip"}:
        raise CadError("diagram data-hold: expected 'zero' or 'grip'")
    blank = _param(parameters, "blank_length_in")
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    row = _cad(values, "row_in")
    hole = _cad(values, "hole_dia_in")
    stations = _stations(values)
    jaw = _param_in(parameters, "vise_jaw_width_mm")
    over = _param(parameters, "overhang_in")
    parallel = _param_in(parameters, "parallel_thickness_mm")
    cutter = _param_in(parameters, "cutter_dia_mm")
    trim = _trim(blank, length, "blank_length_in")
    scale = 48.0
    trim_px = max(trim * scale, 4.0)
    radius = cutter / 2 * scale
    back = 120.0
    front = back + width * scale
    mid = (back + front) / 2
    groups = _groups()
    x0 = 84.0  # finished X0 (ZERO END)
    row_y = back + row * scale

    def holes(active: bool) -> None:
        for station in stations:
            x = x0 + station * scale
            groups["holes"].append(_el("circle", cx=x, cy=row_y, r=hole / 2 * scale))
            if active:
                groups["active"].append(
                    _el("circle", cx=x, cy=row_y, r=hole / 2 * scale + 3, fill="none")
                )

    if hold == "zero":
        left = x0 - trim_px
        right = left + blank * scale
        jaw_left = left + over * scale
        _title(
            groups, 20, 30, f"ZERO END ~{_inch(over, 1)} out left, the rest out right"
        )
        _vise(
            groups,
            jaw_left,
            jaw_left + jaw * scale,
            back,
            front,
            parallel * scale,
            "fixed jaw · ZERO EDGE",
            "moving jaw",
            labels_right=True,
        )
        _blank(groups, left, right, x0, right, back, front)
        holes(True)
        for index, station in enumerate(stations):
            _dimension(
                groups,
                x0,
                x0 + station * scale,
                back - JAW - 10 - 18 * index,
                back,
                _inch(station),
            )
        groups["datum"].append(_el("circle", cx=x0, cy=back, r=3.5))
        _datum_label(groups, x0 - 6, back - 8, "X0 Y0", "end")
        _cutter(groups, x0 - radius, radius, back, front + radius + 4, at_end=True)
        touch = _param(parameters, "y_touch_x_in")
        finder = x0 + touch * scale
        finder_r = 0.1 * scale
        groups["tool"].append(_el("circle", cx=finder, cy=back - finder_r, r=finder_r))
        _datum_label(
            groups, finder, back - 2 * finder_r - 6, f"Y0 touch ~X {touch:g}", "middle"
        )
        overhang = jaw_left + jaw * scale
        _label(
            groups, (overhang + right) / 2, mid + 5, "overhang: keep clear", "middle"
        )
        items = [
            (x0 - radius, front + 2 * radius + 4, ["1/2 end mill", "feed toward you"]),
            (x0, front, ["ZERO END"]),
            ((x0 + (stations[0] + stations[1]) / 2 * scale), front, ["H1, H2 through"]),
            (right, front, ["grip end"]),
        ]
    else:
        right = x0 + (length + trim) * scale
        finish = x0 + length * scale
        if right - finish < 4:
            right = finish + 4
        jaw_right = right - over * scale
        _title(groups, 20, 30, f"Slid left: grip end ~{_inch(over, 1)} out right")
        _vise(
            groups,
            jaw_right - jaw * scale,
            jaw_right,
            back,
            front,
            parallel * scale,
            "fixed jaw · ZERO EDGE",
            "moving jaw",
            labels_right=True,
        )
        _blank(groups, x0, right, x0, finish, back, front)
        holes(False)
        groups["datum"] += [
            _line(x0, back, x0, front),
            _el("circle", cx=x0, cy=back, r=3.5),
        ]
        _datum_label(groups, x0 - 6, back - 8, "X0", "end")
        _label(groups, x0 - 6, mid + 5, "ZERO END", "end")
        _cutter(
            groups, finish + radius, radius, front + radius + 4, back - 2, at_end=False
        )
        _dimension(groups, x0, finish, front + JAW + 34, front, "{{cad.length_in:.3f}}")
        items = [
            (
                finish + radius,
                front + 2 * radius + 4,
                ["feed away", "last pass L + D/2"],
            ),
        ]
    end_y = _callouts(groups, items, front + JAW + 44, above=False)
    _axes(groups, 24, end_y + 12)
    return _finish(groups, end_y + 44)


def _lever_grip(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Feed-lever setup 4: finished lever; grip end upright in soft jaws."""
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    row = _cad(values, "row_in")
    hole = _cad(values, "hole_dia_in")
    stations = _stations(values)
    radius = _param(parameters, "corner_radius_in")
    layout = _param(parameters, "corner_layout_in")
    band = _cad(values, "linear_1pl_in")
    groups = _groups()

    # Whole lever, top face.
    s = 48.0
    x0, top = 90.0, 56.0
    x1, bottom = x0 + length * s, top + width * s
    r = radius * s
    _title(groups, 20, 30, "Finished lever, top face")
    groups["kept"].append(
        _el(
            "path",
            d=(
                f"M{_fmt(x0)} {_fmt(top)}H{_fmt(x1 - r)}"
                f"A{_fmt(r)} {_fmt(r)} 0 0 1 {_fmt(x1)} {_fmt(top + r)}"
                f"V{_fmt(bottom - r)}"
                f"A{_fmt(r)} {_fmt(r)} 0 0 1 {_fmt(x1 - r)} {_fmt(bottom)}"
                f"H{_fmt(x0)}Z"
            ),
        )
    )
    for station in stations:
        groups["holes"].append(
            _el("circle", cx=x0 + station * s, cy=top + row * s, r=hole / 2 * s)
        )
    _label(groups, x0 - 6, (top + bottom) / 2 + 5, "ZERO END", "end")
    _label(groups, x1 + 6, (top + bottom) / 2 + 5, "grip end", "start")

    # Grip end upright: top face toward you, end up, soft jaws in front.
    d = 140.0
    left, end_y = 170.0, 170.0
    right = left + width * d
    rd = radius * d
    jaw_y = end_y + 0.62 * d
    _title(groups, 20, 146, "Grip end up in the bench vise, top face toward you")
    groups["arriving"].append(_rect(left, end_y, right - left, jaw_y - end_y))
    groups["kept"].append(
        _el(
            "path",
            d=(
                f"M{_fmt(left)} {_fmt(jaw_y)}V{_fmt(end_y + rd)}"
                f"A{_fmt(rd)} {_fmt(rd)} 0 0 1 {_fmt(left + rd)} {_fmt(end_y)}"
                f"H{_fmt(right - rd)}"
                f"A{_fmt(rd)} {_fmt(rd)} 0 0 1 {_fmt(right)} {_fmt(end_y + rd)}"
                f"V{_fmt(jaw_y)}Z"
            ),
        )
    )
    groups["removed"] += [
        _el(
            "path",
            d=(
                f"M{_fmt(left)} {_fmt(end_y + rd)}V{_fmt(end_y)}H{_fmt(left + rd)}"
                f"A{_fmt(rd)} {_fmt(rd)} 0 0 0 {_fmt(left)} {_fmt(end_y + rd)}Z"
            ),
        ),
        _el(
            "path",
            d=(
                f"M{_fmt(right - rd)} {_fmt(end_y)}H{_fmt(right)}V{_fmt(end_y + rd)}"
                f"A{_fmt(rd)} {_fmt(rd)} 0 0 0 {_fmt(right - rd)} {_fmt(end_y)}Z"
            ),
        ),
    ]
    for limit in (radius - band, radius + band):
        if limit <= 0:
            continue
        lr = limit * d
        groups["hidden"] += [
            _el(
                "path",
                d=(
                    f"M{_fmt(left)} {_fmt(end_y + lr)}"
                    f"A{_fmt(lr)} {_fmt(lr)} 0 0 1 {_fmt(left + lr)} {_fmt(end_y)}"
                ),
            ),
            _el(
                "path",
                d=(
                    f"M{_fmt(right - lr)} {_fmt(end_y)}"
                    f"A{_fmt(lr)} {_fmt(lr)} 0 0 1 {_fmt(right)} {_fmt(end_y + lr)}"
                ),
            ),
        ]
    ld = layout * d
    groups["datum"] += [
        _line(
            left - 10,
            end_y + ld,
            right + 10,
            end_y + ld,
            stroke_width=1.2,
            stroke_dasharray="5 3",
        ),
        _line(
            left + ld,
            end_y - 10,
            left + ld,
            jaw_y,
            stroke_width=1.2,
            stroke_dasharray="5 3",
        ),
        _line(
            right - ld,
            end_y - 10,
            right - ld,
            jaw_y,
            stroke_width=1.2,
            stroke_dasharray="5 3",
        ),
    ]
    groups["fixture"].append(_rect(left - 50, jaw_y, right - left + 100, 46))
    _label(groups, (left + right) / 2, jaw_y + 28, "soft jaws", "middle")
    groups["active"] += [
        _el(
            "path",
            d=(
                f"M{_fmt(left)} {_fmt(end_y + rd)}"
                f"A{_fmt(rd)} {_fmt(rd)} 0 0 1 {_fmt(left + rd)} {_fmt(end_y)}"
            ),
            fill="none",
        ),
        _el(
            "path",
            d=(
                f"M{_fmt(right - rd)} {_fmt(end_y)}"
                f"A{_fmt(rd)} {_fmt(rd)} 0 0 1 {_fmt(right)} {_fmt(end_y + rd)}"
            ),
            fill="none",
        ),
    ]
    rows = [
        (
            end_y - 4,
            right - ld,
            end_y - 6,
            [f"scribed {_inch(layout, 2)} from each side"],
        ),
        (end_y + 24, right + 8, end_y + ld, [f"and {_inch(layout, 2)} from the end"]),
        (
            end_y + 62,
            right - rd * 0.29,
            end_y + rd * 0.29,
            [
                f"file both vertical corners to R{_inch(radius, 1)}",
                f"R{_inch(radius - band, 1)}–R{_inch(radius + band, 1)}, inside the lines",
            ],
        ),
    ]
    for y, ax, ay, lines in rows:
        groups["leaders"] += [
            _el("polyline", points=f"{_fmt(386)} {_fmt(y - 4)} {_fmt(ax)} {_fmt(ay)}"),
            _el("circle", cx=ax, cy=ay, r=1.8, fill="#333"),
        ]
        for index, line in enumerate(lines):
            _label(groups, 390, y + index * 16, line)
    return _finish(groups, jaw_y + 52)


JIG_LAYOUTS = {
    "jig-cutlist": _cutlist,
    "jig-bracket-ends": _bracket_ends,
    "jig-bracket-tap": _bracket_tap,
    "jig-bracket-inspect": _bracket_inspect,
    "jig-lever-hold": _lever_hold,
    "jig-lever-grip": _lever_grip,
}
