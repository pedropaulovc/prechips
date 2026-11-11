"""Bind released-CAD geometry into the setup-diagram SVG templates.

An SVG opts in with a root ``data-cad-template`` naming one of the layouts
below, a ``shaft-*`` layout from :mod:`prechips.shaft_diagrams` or a ``jig-*``
layout from :mod:`prechips.jig_diagrams`. A layout
turns finished CAD geometry and authored blank parameters into
``view`` scalars for ``{{view.KEY}}`` tokens and fills elements marked
``data-cad-group`` with repeated features (blanks, holes, slots, sections).
The SVG owns styles, fixtures, tools and authored hardware; only their anchor
points follow the part. Generated text may hold ``{{cad.*}}``/``{{process.*}}``
tokens, so every label is formatted once by :func:`prechips.cad.bind_text`.
SVGs without a template are only token-bound.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from xml.etree import ElementTree

from prechips.cad import CadData, CadError, bind_text, id_range, point_columns

SVG_NS = "http://www.w3.org/2000/svg"
ElementTree.register_namespace("", SVG_NS)

Element = tuple[str, dict[str, str], str | None]
Layout = tuple[dict[str, float], dict[str, list[Element]]]

MM_PER_IN = 25.4


def _fmt(value: float | str) -> str:
    if isinstance(value, str):
        return value
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _el(tag: str, text: str | None = None, **attrs: float | str) -> Element:
    return (
        tag,
        {key.replace("_", "-"): _fmt(value) for key, value in attrs.items()},
        text,
    )


def _rect(x: float, y: float, w: float, h: float, **attrs: float | str) -> Element:
    return _el("rect", x=x, y=y, width=w, height=h, **attrs)


def _line(x1: float, y1: float, x2: float, y2: float, **attrs: float | str) -> Element:
    return _el("line", x1=x1, y1=y1, x2=x2, y2=y2, **attrs)


def _dim(x1: float, y1: float, x2: float, y2: float) -> Element:
    return _line(x1, y1, x2, y2, marker_start="url(#arr)", marker_end="url(#arr)")


def _text(x: float, y: float, text: str, **attrs: float | str) -> Element:
    return _el("text", text, x=x, y=y, **attrs)


def _view(**values: float) -> dict[str, float]:
    return {key: round(value, 2) for key, value in values.items()}


def _number(mapping: dict, key: str, where: str) -> float:
    value = mapping.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise CadError(f"{where}.{key}: expected a finite number for the diagram")
    return float(value)


def _positive(mapping: dict, key: str, where: str) -> float:
    value = _number(mapping, key, where)
    if value <= 0:
        raise CadError(f"{where}.{key}: must be positive for the diagram")
    return value


def _cad(values: dict, key: str) -> float:
    return _positive(values, key, "cad")


def _process(parameters: dict, key: str) -> float:
    return _number(parameters, key, "process")


def _points(values: dict, key: str) -> list[tuple[float, float]]:
    """Return ``(X, rise)`` pairs; rise = -DRO Y = printed y-down offset."""
    points = values.get(key)
    if not isinstance(points, list) or not points:
        raise CadError(f"cad.{key}: expected a non-empty point list for the diagram")
    result = []
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise CadError(f"cad.{key}[{index}]: expected [X, Y]")
        pair = dict(enumerate(point))
        result.append(
            (
                _number(pair, 0, f"cad.{key}[{index}]"),
                -_number(pair, 1, f"cad.{key}[{index}]"),
            )
        )
    return result


def _slots(values: dict) -> list[dict[str, float]]:
    shapes = values.get("slot_shapes_in")
    if not isinstance(shapes, list) or not shapes:
        raise CadError("cad.slot_shapes_in: expected a non-empty list for the diagram")
    result = []
    for index, shape in enumerate(shapes):
        where = f"cad.slot_shapes_in[{index}]"
        if not isinstance(shape, dict):
            raise CadError(f"{where}: expected a table")
        near = -_number(shape, "near_y_in", where)
        far = -_number(shape, "far_y_in", where)
        result.append(
            {
                "x": _number(shape, "x_in", where),
                "rise_low": min(near, far),
                "rise_high": max(near, far),
                "width": _positive(shape, "width_in", where),
            }
        )
    return result


def _root_mm(root: ElementTree.Element, name: str) -> float:
    raw = root.get(name)
    try:
        value = float(raw) if raw is not None else math.nan
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise CadError(f"diagram {name}: expected a positive authored mm value")
    return value


def _top_view_features(
    values: dict, x0: float, top: float, scale: float
) -> dict[str, list[Element]]:
    """Rail holes, counterbored bracket holes and slots on a y-down top view."""
    rail_r = _cad(values, "rail_dia_in") * scale / 2
    bracket_r = _cad(values, "bracket_dia_in") * scale / 2
    counterbore_r = _cad(values, "counterbore_dia_in") * scale / 2
    rails = [
        _el("circle", cx=x0 + x * scale, cy=top + rise * scale, r=rail_r)
        for x, rise in _points(values, "rail_points_in")
    ]
    brackets: list[Element] = []
    for x, rise in _points(values, "bracket_points_in"):
        cx, cy = x0 + x * scale, top + rise * scale
        brackets.append(_el("circle", cx=cx, cy=cy, r=counterbore_r))
        brackets.append(_el("circle", cx=cx, cy=cy, r=bracket_r))
    slots = []
    for slot in _slots(values):
        width = slot["width"] * scale
        slots.append(
            _rect(
                x0 + slot["x"] * scale - width / 2,
                top + slot["rise_low"] * scale - width / 2,
                width,
                (slot["rise_high"] - slot["rise_low"]) * scale + width,
                rx=width / 2,
            )
        )
    return {"rail-holes": rails, "bracket-holes": brackets, "slots": slots}


def _saw(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 1: authored blanks marked on the authored parent bar."""
    length = _process(parameters, "blank_length_in")
    width = _process(parameters, "blank_width_in")
    thickness = _process(parameters, "blank_thickness_in")
    if "quantity" not in parameters:
        raise CadError("process.quantity: required for the diagram")
    quantity = parameters["quantity"]
    kerf, rest, x_start, top = 4.0, 134.0, 40.0, 60.0
    scale = min(12.0, (506 - kerf * quantity) / (quantity * length), 90 / width)
    lpx, hpx = length * scale, width * scale
    bottom, mid = top + hpx, top + hpx / 2
    blanks, labels, dims, cuts, leaders = [], [], [], [], []
    for index in range(quantity):
        x = x_start + index * (lpx + kerf)
        blanks.append(_rect(x, top, lpx, hpx))
        labels.append(
            _text(x + lpx / 2, mid + 5, f"BLANK {index + 1}", text_anchor="middle")
        )
        labels.append(
            _text(
                x + lpx / 2,
                top - 23,
                "{{process.blank_length_in:fraction}} in",
                text_anchor="middle",
            )
        )
        dims.append(_line(x, top - 2 if index == 0 else top - 12, x, top - 20))
        dims.append(_line(x + lpx, top - 12, x + lpx, top - 20))
        dims.append(_dim(x + 1, top - 16, x + lpx - 1, top - 16))
        cut = x + lpx + kerf / 2
        cuts.append(cut)
    cut_lines = [_line(cut, top - 10, cut, bottom + 10) for cut in cuts]
    label_x = (cuts[0] + cuts[1]) / 2 if len(cuts) > 1 else cuts[0] + 60
    labels.append(_text(label_x, bottom + 36, "cutlines", text_anchor="middle"))
    for cut in cuts[:2]:
        side = -31 if cut < label_x else 31
        leaders.append(
            _line(
                label_x + side, bottom + 28, cut + (2 if side < 0 else -2), bottom + 12
            )
        )
    rest_x = x_start + quantity * (lpx + kerf)
    end = rest_x + rest
    stock_rest = [
        _el(
            "path",
            d=(
                f"M{_fmt(rest_x)} {_fmt(top)}H{_fmt(end)}"
                f"L{_fmt(end - 8)} {_fmt(top + hpx / 4)}"
                f"L{_fmt(end + 6)} {_fmt(mid)}"
                f"L{_fmt(end - 6)} {_fmt(top + 3 * hpx / 4)}"
                f"L{_fmt(end)} {_fmt(bottom)}H{_fmt(rest_x)}Z"
            ),
        )
    ]
    side_top = 220.0
    side_t = 2 * thickness * scale  # side view drawn at 2x vertical scale
    side_bottom = side_top + side_t
    side_bar = [
        _el(
            "path",
            d=(
                f"M{_fmt(x_start)} {_fmt(side_top)}H{_fmt(end)}"
                f"L{_fmt(end - 4)} {_fmt(side_top + side_t / 2)}"
                f"L{_fmt(end)} {_fmt(side_bottom)}H{_fmt(x_start)}Z"
            ),
        )
    ]
    view = _view(
        top=top,
        bottom=bottom,
        mid=mid,
        width_ext_x=x_start - 2,
        width_dim_top=top + 1,
        width_dim_bottom=bottom - 1,
        rest_label_x=rest_x + 64,
        label_y=mid + 5,
        cut=cuts[0],
        blade_x=cuts[0] - 3,
        push_x=cuts[0] + 17,
        blade_text_x=cuts[0] + 41,
        blade_leader_x1=cuts[0] + 37,
        blade_leader_x2=cuts[0] + 5,
        side_cut_bottom=side_bottom + 8,
        side_bottom=side_bottom,
        bed_x=cuts[0] - 60,
        bed_label_y=side_bottom + 30,
        notch_x1=cuts[0] - 6,
        notch_x2=cuts[0] + 6,
        notch_top=side_bottom + 1,
        notch_bottom=side_bottom + 18,
        bed_label_x=cuts[0] - 1,
        support_left=90.0,
        support_right=end - 80,
        support_label_left=100.0,
        support_label_right=end - 70,
        floor_y=side_bottom + 52,
        caption_y=side_bottom + 74,
        height=side_bottom + 88,
    )
    return view, {
        "blanks": blanks,
        "blank-labels": labels,
        "length-dims": dims,
        "cutlines": cut_lines,
        "cut-leaders": leaders,
        "stock-rest": stock_rest,
        "side-bar": side_bar,
    }


def _table_blocks(x0: float, x1: float, cy: float, scale: float) -> dict[str, float]:
    """Setups 2–3: three 1-2-3 blocks lying flat, 3 in across the width, inboard."""
    width, height, inset = 2 * scale, 3 * scale, 35.0
    mid = (x0 + x1) / 2
    return {
        "block_w": width,
        "block_h": height,
        "block_y": cy - height / 2,
        "block1_x": x0 + inset,
        "block2_x": mid - width / 2,
        "block3_x": x1 - inset - width,
        "gap_left_x": (x0 + inset + width + mid - width / 2) / 2,
        "gap_right_x": (mid + width / 2 + x1 - inset - width) / 2,
    }


def _width(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 2: authored blank on the table; CAD finished width from ZERO EDGE."""
    blank_length = _process(parameters, "blank_length_in")
    blank_width = _process(parameters, "blank_width_in")
    width = _cad(values, "width_in")
    scale = min(27.0, 470 / blank_length, 162 / blank_width)
    x0, top = 90.0, 92.0
    lpx, hpx = blank_length * scale, blank_width * scale
    x1, bottom = x0 + lpx, top + hpx
    cleanup = 5.0  # authored front-edge cleanup, shown enlarged
    front = bottom - cleanup
    finish = max(top, front - width * scale)
    view = _view(
        x0=x0,
        x1=x1,
        top=top,
        lpx=lpx,
        hpx=hpx,
        cy=(top + bottom) / 2,
        mid=(x0 + x1) / 2,
        finish=finish,
        top_stock=finish - top,
        front=front,
        cleanup=cleanup,
        cutter1_x=x0 + 90,
        cutter1_y=front + 7,
        pass1_x1=x0 + 110,
        pass1_x2=x0 + 240,
        pass1_y=front + 23,
        pass1_label_x=x0 + 248,
        pass1_label_y=front + 28,
        cutter2_x=x1 - 90,
        cutter2_y=finish - 7,
        pass2_x1=x1 - 110,
        pass2_x2=x1 - 240,
        pass2_y=top - 14,
        pass2_label_x=x1 - 270,
        pass2_label_y=top - 9,
        dim_top=finish + 1,
        dim_bottom=front - 1,
        dim_mid=(finish + front) / 2,
        label1_y=(top + bottom) / 2 - 28,
        label2_y=(top + bottom) / 2 + 5,
        label3_y=(top + bottom) / 2 + 38,
        datum_label_y=bottom + 46,
        datum_leader_x1=x1 - 60,
        datum_leader_y1=bottom + 34,
        datum_leader_x2=x1 - 80,
        datum_leader_y2=front + 2,
        step1_y=bottom + 56,
        **_table_blocks(x0, x1, (top + bottom) / 2, scale),
    )
    return view, {}


def _ends(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 3: CAD finished length squared from the authored blank length."""
    blank_length = _process(parameters, "blank_length_in")
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    scale = min(27.0, 470 / max(blank_length, length), 148 / width)
    lpx, hpx = length * scale, width * scale
    trim = max((blank_length - length) / 2 * scale, 5.0)  # end stock, min visible
    mid, top = 325.0, 100.0
    zero, far = mid - lpx / 2, mid + lpx / 2
    bottom = top + hpx
    cy = (top + bottom) / 2
    view = _view(
        x0=zero - trim,
        x1=far + trim,
        zero=zero,
        far=far,
        trim=trim,
        mid=mid,
        top=top,
        bottom=bottom,
        bar_w=lpx + 2 * trim,
        hpx=hpx,
        cy=cy,
        cutter1_x=zero - 7,
        cutter1_y=top + 12,
        cutter2_x=far + 7,
        cutter2_y=bottom - 12,
        minus_y_label=bottom + 10,
        label1_y=cy - 9,
        label2_y=cy + 16,
        edge_label_y=bottom - 8,
        step_y=bottom + 24,
        step3_x=zero + 5,
        step4_x=far - 5,
        ext_top=bottom + 28,
        ext_bottom=bottom + 80,
        far_ext1_top=bottom + 2,
        far_ext1_bottom=bottom + 12,
        far_ext2_top=bottom + 30,
        dim_x1=zero + 1,
        dim_x2=far - 1,
        dim_y=bottom + 74,
        dim_label_x=zero + 105,
        dim_label_y=bottom + 92,
        **_table_blocks(zero - trim, far + trim, cy, scale),
    )
    return view, {}


def _face(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 4: finished-length bar in the vise, faced from blank thickness."""
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    thickness = _process(parameters, "blank_thickness_in")
    front_scale = min(28.0, 606 / length)
    centre = 333.0
    fx0, fx1 = centre - length * front_scale / 2, centre + length * front_scale / 2
    fbottom = 120 + thickness * front_scale
    # Jaw top from the bound stand-out; the vise body top sits at y=172.
    jaw_top = 120 + _cad(values, "jaw_standout_blank_in") * front_scale
    top_scale = min(14.0, 257 / length, 77 / width)
    tcentre = 201.5
    tx0, tx1 = tcentre - length * top_scale / 2, tcentre + length * top_scale / 2
    tbottom = 250 + width * top_scale
    view = _view(
        fx0=fx0,
        fx1=fx1,
        flen=fx1 - fx0,
        fthick=fbottom - 120,
        fbottom=fbottom,
        parallel_h=171.5 - fbottom,
        jaw_top=jaw_top,
        jaw_h=172 - jaw_top,
        jack_shaft_h=158 - fbottom,
        tx0=tx0,
        tx1=tx1,
        tlen=tx1 - tx0,
        twidth=tbottom - 250,
        tbottom=tbottom,
        zero_end_x=tx0 + 1,
        mark1_y=(250 + tbottom) / 2 - 3.5,
        mark2_y=(250 + tbottom) / 2 + 14.5,
        zero_end_y=(250 + tbottom) / 2 + 5.5,
        zero_end_label_x=tx0 - 6,
    )
    return view, {}


def _holes(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 5: every hole and slot at its CAD position in the vise."""
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    scale = min(32.0, 555 / length, 176 / width)
    lpx, hpx = length * scale, width * scale
    centre, top = 337.5, 72.0
    x0, x1 = centre - lpx / 2, centre + lpx / 2
    bottom = top + hpx
    groups = _top_view_features(values, x0, top, scale)
    labels = []
    for first, column in point_columns(_points(values, "bracket_points_in")):
        cx = x0 + column[0][0] * scale
        y = top + min(rise for _, rise in column) * scale + 5
        left = cx < centre
        labels.append(
            _text(
                cx + 12 if left else cx - 11,
                y,
                id_range("B", first, len(column)),
                text_anchor="start" if left else "end",
            )
        )
    for index, slot in enumerate(_slots(values), start=1):
        cx = x0 + slot["x"] * scale
        half = slot["width"] * scale / 2
        # Left-end slot: label below it, clear of the bracket column beside it.
        if cx < centre:
            below = top + slot["rise_high"] * scale + half + 15
            labels.append(_text(cx, below, f"S{index}", text_anchor="middle"))
        else:
            cy = top + (slot["rise_low"] + slot["rise_high"]) / 2 * scale + 5
            labels.append(_text(cx - half - 5, cy, f"S{index}", text_anchor="end"))
    groups["feature-labels"] = labels
    rail_y = top - _number(values, "rail_y_in", "cad") * scale
    jack1, jack2 = (
        (
            x0 + _process(parameters, f"jack_{side}_x_in") * scale,
            top - _process(parameters, f"jack_{side}_y_in") * scale,
        )
        for side in ("left", "right")
    )
    view = _view(
        x0=x0,
        x1=x1,
        top=top,
        bottom=bottom,
        lpx=lpx,
        hpx=hpx,
        mid_y=(top + bottom) / 2,
        datum_y=top + 1,
        rail_label_x=x0 + 180,
        rail_label_y=rail_y + 24,
        side_label_y=top + 0.273 * hpx,
        side_label2_y=top + 0.273 * hpx + 18,
        lower_parallel_y=bottom - 8,
        jack1_x=jack1[0],
        jack1_y=jack1[1],
        jack2_x=jack2[0],
        jack2_y=jack2[1],
        jack1_label_x=jack1[0] + 15,
        jack1_label_y=jack1[1] + 10,
        jack2_label_x=jack2[0] - 15,
        jack2_label_y=jack2[1] + 5,
        origin_label_x=x0 - 56,
        origin_label_y=top - 10,
        zero_end_x=x0 - 14,
        front_label_y=bottom + 34,
        ext_top=bottom + 4,
        ext_bottom=bottom + 60,
        dim_x1=x0 + 1,
        dim_x2=x1 - 1,
        dim_y=bottom + 55,
        dim_label_y=bottom + 74,
        height=bottom + 82,
    )
    return view, groups


def _inspect(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    """Setup 6: bar 1 plan and section through its last bracket column; bar 2 section."""
    length = _cad(values, "length_in")
    width = _cad(values, "width_in")
    thickness = _cad(values, "thickness_in")
    rail_width = _root_mm(root, "data-rail-width-mm") / MM_PER_IN
    rail_height = _root_mm(root, "data-rail-height-mm") / MM_PER_IN
    head_dia = _root_mm(root, "data-screw-head-dia-mm") / MM_PER_IN
    head_height = _root_mm(root, "data-screw-head-height-mm") / MM_PER_IN
    shank_dia = _root_mm(root, "data-screw-dia-mm") / MM_PER_IN
    shank_length = _root_mm(root, "data-screw-length-mm") / MM_PER_IN
    rail_rise = -_number(values, "rail_y_in", "cad")

    # Plan view, ZERO END left / ZERO EDGE top; the rail is trimmed flush with
    # both ends of the bar.
    scale = min(22.0, 390 / length, 121 / width)
    x0, top = 30.0, 60.0
    x1, bottom = x0 + length * scale, top + width * scale
    groups = _top_view_features(values, x0, top, scale)
    rail_y = top + rail_rise * scale
    rail_px = rail_width * scale
    groups["rail-hidden"] = [_rect(x0, rail_y - rail_px / 2, x1 - x0, rail_px)]
    column = _points(values, "bracket_section_points_in")
    section_x = x0 + column[0][0] * scale
    slots = _slots(values)
    slot = slots[-1]
    stud_x = x0 + slot["x"] * scale + slot["width"] * scale / 2
    stud_y = top + (slot["rise_high"] + slot["width"] / 2) * scale - 1

    # Bar 1 as used on the mill table: A-A turned over, C'BORE SIDE down, rail on
    # top, so ZERO EDGE falls on the left.
    sscale = min(46.0, 253 / width)
    rail_w, rail_h = rail_width * sscale, rail_height * sscale
    xr, stop = 683.0, 82 + rail_h
    xl, sbottom = xr - width * sscale, stop + thickness * sscale
    cb_r = _cad(values, "counterbore_dia_in") * sscale / 2
    cb_depth = _cad(values, "counterbore_depth_in") * sscale
    hole_r = _cad(values, "bracket_dia_in") * sscale / 2
    cuts, outlines = [], []
    hole_xs = [xl + rise * sscale for _, rise in column]
    floor = sbottom - cb_depth
    for cx in hole_xs:
        cuts.append(_rect(cx - cb_r, floor, 2 * cb_r, cb_depth + 1))
        cuts.append(_rect(cx - hole_r, stop - 1, 2 * hole_r, floor - stop + 1.7))
        outlines.append(
            _el(
                "path",
                d=(
                    f"M{_fmt(cx - cb_r)} {_fmt(sbottom)}V{_fmt(floor)}"
                    f"H{_fmt(cx - hole_r)}V{_fmt(stop)}M{_fmt(cx + hole_r)} {_fmt(stop)}"
                    f"V{_fmt(floor)}H{_fmt(cx + cb_r)}V{_fmt(sbottom)}"
                ),
            )
        )
    screw_x = hole_xs[min(2, len(hole_xs) - 1)]
    screw = [
        _rect(
            screw_x - shank_dia * sscale / 2,
            floor - shank_length * sscale,
            shank_dia * sscale,
            shank_length * sscale,
            fill="#999",
        ),
        _rect(
            screw_x - head_dia * sscale / 2,
            floor,
            head_dia * sscale,
            head_height * sscale,
            fill="#555",
        ),
    ]
    rail_cx = xl + rail_rise * sscale
    rail_section = [_rect(rail_cx - rail_w / 2, stop - rail_h, rail_w, rail_h)]
    labels = [
        _text(section_x + 6, top - 5, "A"),
        _text(section_x + 6, bottom + 15, "A"),
        _text(430, 72, "Bar 1 as used: A–A through {{cad.bracket_section_range}}"),
    ]
    for index, item in enumerate(slots, start=1):
        cx, half = x0 + item["x"] * scale, item["width"] * scale / 2
        name, size = f"S{index}", 13
        if item is slot:
            cy = top + (item["rise_low"] + item["rise_high"]) / 2 * scale + 4
            labels.append(
                _text(cx - half - 4, cy, name, text_anchor="end", font_size=size)
            )
        else:
            below = top + item["rise_high"] * scale + half + 12
            labels.append(_text(cx, below, name, text_anchor="middle", font_size=size))
    # Bar 2 as used, viewed the same way: rail on the marked RAIL SIDE (up in
    # Setup 5), so ZERO EDGE stays on the right.
    rail2_cx = xr - rail_rise * sscale
    rail2_y = 243.0
    stop2 = rail2_y + rail_h
    sbottom2 = stop2 + thickness * sscale
    view = _view(
        x0=x0,
        top=top,
        plan_w=x1 - x0,
        plan_h=bottom - top,
        cbore_label_y=top + 40,
        rail_label_y=rail_y + 25,
        rail_note_y=bottom + 59,
        rail_leader_y1=bottom + 45,
        rail_leader_x2=x0 + 35,
        rail_leader_y2=rail_y + rail_px / 2,
        section_x=section_x,
        section_arrow_x=section_x - 16,
        section_top=top - 10,
        section_bottom=bottom + 10,
        sxl=xl,
        sxr=xr,
        stop=stop,
        sw=xr - xl,
        st=sbottom - stop,
        sbottom=sbottom,
        head_leader_x=screw_x + head_dia * sscale / 2,
        head_leader_y=floor + head_height * sscale,
        rail1_label_x=rail_cx + rail_w / 2 + 8,
        rail1_label_y=stop - 8,
        row1_leader_y=sbottom + 6,
        row1_label_y=sbottom + 19,
        row2_label_y=sbottom + 38,
        stud_label_y=bottom + 33,
        stud_leader_y=bottom + 21,
        stud_x=stud_x,
        stud_y=stud_y,
        stop2=stop2,
        sbottom2=sbottom2,
        rail2_x=rail2_cx - rail_w / 2,
        rail2_y=rail2_y,
        bar2_title_y=rail2_y - 15,
        rail2_label_x=rail2_cx + rail_w / 2 + 8,
        rail2_label_y=stop2 - 8,
        rail_w=rail_w,
        rail_h=rail_h,
        seat2_leader_y=sbottom2 + 9,
        seat2_label_y=sbottom2 + 22,
        edge2_leader_y=sbottom2 + 10,
    )
    groups.update(
        {
            "section-cuts": cuts,
            "section-outlines": outlines,
            "screw": screw,
            "rail-section": rail_section,
            "labels": labels,
        }
    )
    return view, groups


LAYOUTS: dict[str, Callable[[dict, dict, ElementTree.Element], Layout]] = {
    "saw": _saw,
    "width": _width,
    "ends": _ends,
    "face": _face,
    "holes": _holes,
    "inspect": _inspect,
}


def render_cad_svg(content: bytes, cad: CadData, parameters: dict) -> bytes:
    """Return the SVG with CAD/process tokens bound and feature groups filled."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise CadError(f"diagram template is not valid XML: {error}") from error
    name = root.attrib.pop("data-cad-template", None)
    if name is None:
        if b"{{" not in content:
            return content
        return bind_text(content.decode("utf-8"), cad, parameters, xml=True).encode(
            "utf-8"
        )
    # The shaft and jig layouts build on this module's primitives, so import
    # them here.
    from prechips.jig_diagrams import JIG_LAYOUTS
    from prechips.shaft_diagrams import SHAFT_LAYOUTS

    layout = (LAYOUTS | SHAFT_LAYOUTS | JIG_LAYOUTS).get(name)
    if layout is None:
        raise CadError(f"unknown diagram template {name!r}")
    view, groups = layout(cad.values, parameters, root)
    for element in list(root.iter()):
        group = element.attrib.pop("data-cad-group", None)
        if group is None:
            continue
        if group not in groups:
            raise CadError(f"diagram template {name!r} has no group {group!r}")
        for tag, attrs, text in groups.pop(group):
            child = ElementTree.SubElement(element, f"{{{SVG_NS}}}{tag}", attrs)
            child.text = text
    if groups:
        raise CadError(f"diagram template {name!r} lacks groups {sorted(groups)}")
    text = ElementTree.tostring(root, encoding="unicode")
    bound = bind_text(text, cad, parameters, extra={"view": view}, xml=True)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + bound).encode("utf-8")
