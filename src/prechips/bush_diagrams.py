"""Turned-part lathe pictures for the ``turned-bush`` template.

One side elevation per setup, spindle axis across the page, chuck at the
left, tailstock at the right, operator side at the bottom. ``data-hold``
names how the work is held:

- ``bar``: round bar in the chuck, ``process.parts_per_pull`` parts (one by
  default) out past the jaws, each a ``cad.pitch_mm`` along the bar;
- ``block``: a squared blank (``process.blank_side_in``) in the 4-jaw;
- ``regrip``: the parted part turned round, the jaws on its ``data-grip``
  diameter over a shim wrap, ``cad.regrip_allowance_mm`` (left on by the
  parting) on its out end to face;
- ``mandrel``: the squared blank on a bolt through its bore, the bolt in the
  chuck, a washer and nut on each face;
- ``inspect``: the finished part alone with its printed sizes.

``data-out`` (``datum`` or ``far``) names the part's end toward the
tailstock; ``data-work`` lists what the setup does, from ``face``,
``centre``, ``drill``, ``turn``, ``pocket``, ``tap``, ``chamfer`` and
``part``; ``data-chuck`` (``3-jaw`` or ``4-jaw``) names the chuck;
``data-member`` draws a member on its own bar (the default member when
omitted or named). Part
sizes come from the adapter; chuck, jaws, tools, bolt and nut are schematic
symbols. Material arriving is dashed, material removed in the setup hatched,
material kept solid, holes made by now dashed as hidden edges.
"""

from __future__ import annotations

from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _rect
from prechips.jig_diagrams import _datum_label, _finish, _groups, _param, _title
from prechips.shaft_diagrams import _break, _callouts, _dimension

Groups = dict[str, list[Element]]

_HOLDS = ("bar", "block", "regrip", "mandrel", "inspect")
_OUTS = ("datum", "far")
_WORK = ("face", "centre", "drill", "turn", "pocket", "tap", "chamfer", "part")
_CHUCKS = ("3-jaw", "4-jaw")
_TITLES = {
    "bar": "Bar in the chuck, seen from the operator's side",
    "block": "Squared blank in the 4-jaw, seen from the operator's side",
    "regrip": "Part turned round in the chuck, seen from the operator's side",
    "mandrel": "Blank on the bolt mandrel, seen from the operator's side",
    "inspect": "Finished part, seen from the side",
}
_LEFT = 70.0  # chuck face of the body, page px
_CHUCK = 40.0  # schematic chuck body width, px
_JAW = 22.0  # schematic jaw depth, px
_SHIM = 3.0  # shim wrap under regrip jaws, px
_AXIS = 270.0  # spindle axis, page px


def _segments(values: dict, outer: str) -> list[tuple[str, float, float, float]]:
    """``(name, z0, z1, radius)`` of the turned diameters; ``outer`` names the
    member's outer (``outer`` for the default member)."""
    return [
        (
            name,
            float(values[f"{name}_z0_mm"]),
            _cad(values, f"{name}_z1_mm"),
            _cad(values, f"{name}_dia_mm") / 2,
        )
        for name in (outer, "step")
        if f"{name}_dia_mm" in values
    ]


def _band(key: str, places: int) -> str:
    """``min–max`` tokens of the inch band ``key``."""
    return (
        f"{{{{cad.{key}_min_in:.{places}dot}}}}–{{{{cad.{key}_max_in:.{places}dot}}}}"
    )


def _size(values: dict, name: str) -> list[str]:
    """The printed acceptance of one turned diameter, on two lines."""
    if values.get(f"{name}_stock"):
        return [f"Ø{{{{cad.{name}_ref_in:.4dot}}}}", "bar as bought"]
    fit = [f"{_band(f'{name}_clearance', 4)} under its mate"]
    if f"{name}_dia_min_in" in values:
        spread = values[f"{name}_dia_max_in"] - values[f"{name}_dia_min_in"]
        band = [f"Ø{_band(f'{name}_dia', 4 if spread < 0.002 else 3)}"]
        # A band with a fit on its mate prints both: the fit holds too.
        return band + fit if f"{name}_clearance_min_in" in values else band
    return ["to its measured mate,", f"{_band(f'{name}_clearance', 4)} under"]


def _length_text(values: dict) -> str:
    if values.get("length_supply"):
        return "length {{cad.length_min_in:.2dot}} MIN"
    return "length {{cad.length_min_in:.3dot}}–{{cad.length_max_in:.3dot}}"


class _Page:
    """Stations into the part (from the datum end) mapped onto the page."""

    def __init__(self, x_out: float, scale: float, length: float, out: str) -> None:
        self.x_out, self.scale, self.length, self.out = x_out, scale, length, out

    def x(self, station: float, shift: float = 0.0) -> float:
        """Page x of ``station`` on the part ``shift`` mm further from the out end."""
        depth = station if self.out == "datum" else self.length - station
        return self.x_out - (depth + shift) * self.scale

    def span(self, z0: float, z1: float, shift: float = 0.0) -> tuple[float, float]:
        a, b = self.x(z0, shift), self.x(z1, shift)
        return min(a, b), max(a, b)

    def up(self, radius: float) -> float:
        return _AXIS - radius * self.scale

    def size(self, radius: float) -> float:
        return 2 * radius * self.scale


def _profile(page: _Page, segments: list, shift: float) -> Element:
    """Solid stepped outline of one part, ``shift`` mm from the out end."""
    points = []
    for _, z0, z1, radius in sorted(segments, key=lambda seg: page.x(seg[1], shift)):
        x0, x1 = page.span(z0, z1, shift)
        points += [(x0, page.up(radius)), (x1, page.up(radius))]
    top = "L".join(f"{x:.2f} {y:.2f}" for x, y in points)
    bottom = "L".join(f"{x:.2f} {2 * _AXIS - y:.2f}" for x, y in reversed(points))
    return _el("path", d=f"M{top}L{bottom}Z")


def _holes(groups: Groups, values: dict, page: _Page, shift: float, holes: set) -> None:
    """Hidden edges of the named holes (``bore``, ``pocket``, ``tap``)."""
    runs = []
    if "bore" in holes and "bore_dia_mm" in values:
        runs.append((values["bore_z0_mm"], values["bore_z1_mm"], values["bore_dia_mm"]))
    if "pocket" in holes and "pocket_dia_mm" in values:
        runs.append((0.0, values["pocket_depth_mm"], values["pocket_dia_mm"]))
    if "tap" in holes and "tap_drill_dia_mm" in values:
        runs.append((0.0, values["tap_drill_depth_mm"], values["tap_drill_dia_mm"]))
        x0, x1 = page.span(0.0, values["tap_thread_depth_mm"], shift)
        radius = values["tap_drill_dia_mm"] / 2
        groups["part-threads"].append(
            _rect(x0, page.up(radius), x1 - x0, page.size(radius))
        )
    for z0, z1, dia in runs:
        x0, x1 = page.span(z0, z1, shift)
        groups["hidden"].append(
            _rect(x0, page.up(dia / 2), x1 - x0, page.size(dia / 2))
        )


def _chuck(
    groups: Groups, page: _Page, x0: float, x1: float, radius: float, shim: float
) -> None:
    """Chuck body and the upper and lower jaws gripping ``radius`` from x0 to x1."""
    top, bottom = page.up(radius) - shim, 2 * _AXIS - page.up(radius) + shim
    groups["fixture-vise"].append(
        _rect(x0 - _CHUCK, top - _JAW - 8, _CHUCK, bottom - top + 2 * _JAW + 16)
    )
    groups["clamp"] += [
        _rect(x0, top - _JAW, x1 - x0, _JAW),
        _rect(x0, bottom, x1 - x0, _JAW),
    ]
    if shim:
        # Shims are work holders too (the palette's ``clamp``); a callout
        # names them.
        groups["clamp"] += [
            _rect(x0, top, x1 - x0, shim),
            _rect(x0, bottom - shim, x1 - x0, shim),
        ]


def _tailstock(groups: Groups, x: float) -> None:
    """Drill or tap on the axis from the tailstock, its point at ``x``."""
    groups["cutter"].append(
        _el(
            "path",
            d=f"M{x:.2f} {_AXIS:.2f}L{x + 8:.2f} {_AXIS - 5:.2f}H{x + 46:.2f}V{_AXIS + 5:.2f}H{x + 8:.2f}Z",
        )
    )
    groups["fixture-vise"].append(_rect(x + 46, _AXIS - 14, 34, 28))


_HOLES = ("bore", "pocket", "tap")


def _layout(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    hold = root.attrib.pop("data-hold", None)
    out = root.attrib.pop("data-out", "datum")
    work = set(root.attrib.pop("data-work", "").split())
    holes = set(root.attrib.pop("data-holes", "").split())
    chuck = root.attrib.pop("data-chuck", "4-jaw" if hold == "block" else "3-jaw")
    grip = root.attrib.pop("data-grip", "outer")
    member = root.attrib.pop("data-member", None)
    outer = "outer"
    if member is not None:
        # A member drawn on its own bar: its outer and its own stock.
        by_name = {k.lower(): v for k, v in values.get("member_outers", {}).items()}
        if member.lower() not in by_name:
            raise CadError(f"turned-bush: data-member {member!r} is not a member")
        outer = by_name[member.lower()]
    if grip == "outer":
        grip = outer
    if hold not in _HOLDS:
        raise CadError(
            f"turned-bush: data-hold must be one of {', '.join(_HOLDS)}, not {hold!r}"
        )
    if out not in _OUTS:
        raise CadError("turned-bush: data-out must be datum or far")
    if work - set(_WORK):
        raise CadError(
            f"turned-bush: unknown data-work {', '.join(sorted(work - set(_WORK)))}"
        )
    if holes - set(_HOLES):
        raise CadError(
            f"turned-bush: unknown data-holes {', '.join(sorted(holes - set(_HOLES)))}"
        )
    if chuck not in _CHUCKS:
        raise CadError("turned-bush: data-chuck must be 3-jaw or 4-jaw")
    if hold == "block" and chuck != "4-jaw":
        raise CadError("turned-bush: a squared blank is held in the 4-jaw")
    if hold == "mandrel" and "bore_dia_mm" not in values:
        raise CadError("turned-bush: a mandrel hold needs the part's bore")
    if hold == "regrip" and "turn" in work:
        raise CadError("turned-bush: a regrip setup faces and drills; it does not turn")
    groups = _groups(root)
    _title(groups, 20, 24, _TITLES[hold])
    if hold == "inspect":
        return _inspect(groups, values, outer)
    if "drill" in work:
        holes.add("bore" if "bore_dia_mm" in values else "tap")
    holes |= work & {"pocket", "tap"}
    return _setup(
        groups, values, parameters, hold, out, work, holes, chuck, grip, outer
    )


def _setup(
    groups: Groups,
    values: dict,
    parameters: dict,
    hold: str,
    out: str,
    work: set,
    holes: set,
    chuck: str,
    grip: str,
    outer: str,
) -> Layout:
    length = _cad(values, "length_mm")
    segments = _segments(values, outer)
    stock_key = values.get(f"{outer}_stock_key", "stock_dia_in")
    largest = max(seg[3] for seg in segments)
    count = 1
    if hold == "bar" and "parts_per_pull" in parameters:
        count = int(_param(parameters, "parts_per_pull"))
    pitch = float(values.get("pitch_mm", length))
    if hold == "bar":
        stock = _param(parameters, stock_key) * 12.7
    elif hold in ("block", "mandrel"):
        stock = _param(parameters, "blank_side_in") * 12.7
    else:
        stock = largest
    face = 0.0
    if "face" in work and hold == "regrip":
        # The regrip faces off what the parting left on the parted end.
        face = _cad(values, "regrip_allowance_mm")
    elif "face" in work and hold != "mandrel":
        face = _param(parameters, "face_allowance_in") * 25.4
    kerf = _param(parameters, "part_kerf_in") * 25.4 if "part" in work else 0.0
    # The parting line: past the part's chuck-side end by what a regrip
    # will face off, as a station from the datum end.
    regrip = float(values.get("regrip_allowance_mm", 0.0))
    beyond = length + regrip if out == "datum" else -regrip
    held = 10.0  # mm of bar or blank drawn in the jaws
    if hold == "regrip":
        named = {seg[0]: seg for seg in segments}
        if grip not in named:
            raise CadError(f"turned-bush: data-grip {grip!r} is not a turned diameter")
        reach = length + face
    elif hold == "mandrel":
        reach = length + 16.0
    else:
        clear = 0.0
        if hold == "bar" and "jaw_clearance_in" in parameters:
            clear = _param(parameters, "jaw_clearance_in") * 25.4
        reach = (count - 1) * pitch + length + regrip + kerf + face + clear + held
    scale = min(14.0, 420.0 / reach, 150.0 / (2 * stock))
    if hold == "regrip":
        page = _Page(_LEFT + 20 + length * scale, scale, length, out)
    elif hold == "mandrel":
        page = _Page(_LEFT + 8 * scale + 30 + length * scale, scale, length, out)
    else:
        x_jaw = _LEFT + held * scale
        page = _Page(x_jaw + (reach - held - face) * scale, scale, length, out)
    x_tail = page.x_out + face * scale
    groups["centre-line"].append(_line(_LEFT - _CHUCK - 10, _AXIS, x_tail + 110, _AXIS))
    above: list[tuple[float, float, list[str]]] = []
    below: list[tuple[float, float, list[str]]] = []
    if hold in ("bar", "block"):
        end = page.x(beyond, (count - 1) * pitch) - kerf * scale
        y, low = page.up(stock), 2 * _AXIS - page.up(stock)
        back = 10.0
        groups["part-rest"].append(
            _el(
                "path",
                d=f"M{back:.2f} {y:.2f}H{end:.2f}V{low:.2f}H{back:.2f}"
                f"{_break(back, low, y)}Z",
            )
        )
        groups["part-arriving"].append(_rect(back, y, x_tail - back, low - y))
        _chuck(groups, page, _LEFT, x_jaw, stock, 0.0)
        bar = (
            f"bar Ø{{{{process.{stock_key}:.4dot}}}}"
            if hold == "bar"
            else "squared blank"
        )
        above.append((_LEFT + 4, y - _JAW, [f"{chuck} chuck,", f"jaws on {bar}"]))
    elif hold == "regrip":
        _, z0, z1, radius = named[grip]
        if "regrip_grip_mm" in values:
            # The jaws take only the stated length from the chuck-side end.
            held_mm = _cad(values, "regrip_grip_mm")
            if out == "datum":
                z0 = max(z0, z1 - held_mm)
            else:
                z1 = min(z1, z0 + held_mm)
        x0, x1 = page.span(z0, z1)
        _chuck(groups, page, x0 + 2, x1 - 2, radius, _SHIM)
        above.append(
            (
                x1 - 6,
                page.up(radius) - _SHIM - _JAW,
                [f"{chuck} chuck, jaws", "on a shim wrap"],
            )
        )
    else:
        bolt = values["bore_dia_mm"] / 2
        a, b = page.span(0.0, length)
        groups["part-rest"].append(
            _rect(10, page.up(bolt), b + 40 - 10, page.size(bolt))
        )
        _chuck(groups, page, _LEFT, _LEFT + 8 * scale, bolt, 0.0)
        nut = page.size(bolt) + 16
        groups["part-rest"] += [
            _rect(a - 6, _AXIS - nut / 2 - 6, 6, nut + 12),
            _rect(b, _AXIS - nut / 2 - 6, 6, nut + 12),
            _rect(b + 6, _AXIS - nut / 2, 14, nut),
        ]
        groups["part-arriving"].append(
            _rect(a, page.up(stock), b - a, page.size(stock))
        )
        above.append((b + 13, _AXIS - nut / 2 - 6, ["washer and nut", "each face"]))
        above.append(
            (
                _LEFT + 4,
                page.up(bolt) - _JAW,
                ["bolt through the bore,", f"in the {chuck} chuck"],
            )
        )
    for index in range(count):
        shift = index * pitch
        groups["part-kept"].append(_profile(page, segments, shift))
        if "turn" in work:
            for _, z0, z1, radius in segments:
                if radius < stock - 1e-6:
                    a, b = page.span(z0, z1, shift)
                    groups["part-removed"] += [
                        _rect(a, page.up(stock), b - a, (stock - radius) * scale),
                        _rect(a, page.up(-radius), b - a, (stock - radius) * scale),
                    ]
        if kerf:
            a = page.x(beyond, shift)
            groups["part-removed"].append(
                _rect(a - kerf * scale, page.up(stock), kerf * scale, page.size(stock))
            )
        if regrip and hold in ("bar", "block"):
            # Left on the parted end for the regrip to face off.
            end_station = length if out == "datum" else 0.0
            radius = next(
                seg[3] for seg in segments if seg[1] <= end_station <= seg[2] + 1e-6
            )
            a, b = sorted((page.x(beyond, shift), page.x(end_station, shift)))
            groups["part-kept"].append(
                _rect(a, page.up(radius), b - a, page.size(radius))
            )
        _holes(groups, values, page, shift, holes)
        if (
            kerf
            and hold in ("bar", "block")
            and {"drill", "part"} <= work
            and "bore" in holes
            and "bore_dia_mm" in values
        ):
            # A through hole is drilled past the parting line: from the
            # bore's chuck-side end it runs on through any regrip allowance
            # and the kerf.
            radius = values["bore_dia_mm"] / 2
            x_end = page.x(
                values["bore_z1_mm" if out == "datum" else "bore_z0_mm"], shift
            )
            x_cut = page.x(beyond, shift) - kerf * scale
            a, b = sorted((x_end, x_cut))
            groups["hidden"].append(_rect(a, page.up(radius), b - a, page.size(radius)))
    top_y = page.up(stock)
    if face:
        radius = stock
        if hold == "regrip":
            end_station = 0.0 if out == "datum" else length
            radius = next(
                seg[3] for seg in segments if seg[1] <= end_station <= seg[2] + 1e-6
            )
            groups["part-arriving"].append(
                _rect(page.x_out, page.up(radius), face * scale, page.size(radius))
            )
        groups["part-removed"].append(
            _rect(page.x_out, page.up(radius), face * scale, page.size(radius))
        )
    if not (hold in ("bar", "block") and (out == "far" or "face" not in work)):
        datum_x = page.x(0.0)
        low = 2 * _AXIS - page.up(largest)
        groups["datum"].append(_line(datum_x, page.up(largest) - 10, datum_x, low + 10))
        _datum_label(groups, datum_x - 4, low + 24, "Z0", "end")
    if "turn" in work:
        for name, z0, z1, radius in segments:
            if values.get(f"{name}_stock") or radius >= stock - 1e-6:
                continue
            a, b = page.span(z0, z1)
            lines = _size(values, name)
            above.append(
                ((a + b) / 2, page.up(radius), [f"turn {lines[0]}", *lines[1:]])
            )
    if "face" in work:
        if hold == "regrip":
            text = ["face to", _length_text(values)]
        elif out == "datum":
            text = ["face the end", "to Z0"]
        else:
            text = ["face the end", "square"]
        below.append((page.x_out + 1, 2 * _AXIS - top_y, text))
    if "turn" in work or "face" in work or "chamfer" in work:
        groups["cutter"].append(
            _el("path", d=f"M{page.x_out:.2f} {2 * _AXIS - top_y + 6:.2f}l18 5v44h-18z")
        )
    if "part" in work:
        a = page.x(beyond) - kerf * scale
        groups["cutter"].append(_rect(a, 2 * _AXIS - top_y + 4, kerf * scale, 46))
        below.append(
            (
                a + kerf * scale / 2,
                2 * _AXIS - top_y + 50,
                ["parting blade:", "part off"],
            )
        )
    hole_work = [
        token for token in ("centre", "drill", "pocket", "tap") if token in work
    ]
    if hole_work:
        _tailstock(groups, x_tail + 14)
        lines = {
            "centre": "centre drill",
            "drill": "drill the Ø{{cad.bore_dia_min_in:.3dot}}–{{cad.bore_dia_max_in:.3dot}} hole"
            if "bore_dia_mm" in values
            else "drill {{cad.tap_drill_depth_min_in:.2dot}}–{{cad.tap_drill_depth_max_in:.2dot}} deep",
            "pocket": "pocket {{cad.pocket_depth_min_in:.3dot}}–{{cad.pocket_depth_max_in:.3dot}} deep",
            "tap": "tap {{cad.tap_thread}}",
        }
        head = "tailstock, in turn:" if len(hole_work) > 1 else "tailstock:"
        above.append((x_tail + 40, _AXIS - 5, [head, *(lines[t] for t in hole_work)]))
    if "chamfer" in work:
        chamfers = sorted(
            key.removesuffix("_leg_min_in")
            for key in values
            if key.startswith("chamfer_") and key.endswith("_leg_min_in")
        )
        if chamfers:
            below.append(
                (
                    page.x_out - 4,
                    2 * _AXIS - page.up(largest),
                    ["break edges:"]
                    + [f"{_band(f'{name}_leg', 3)} × 45°" for name in chamfers],
                )
            )
    top = _callouts(groups, above, top_y - 30, above=True)
    if top < 34:
        raise CadError("turned-bush: labels run off the top of the picture")
    bottom = 2 * _AXIS - top_y + 60
    if below:
        bottom = _callouts(groups, below, bottom, above=False)
    return _finish(groups, bottom)


def _inspect(groups: Groups, values: dict, outer: str) -> Layout:
    """The finished part, datum end at the left, its printed sizes."""
    length = _cad(values, "length_mm")
    segments = _segments(values, outer)
    largest = max(seg[3] for seg in segments)
    scale = min(14.0, 360.0 / length, 170.0 / (2 * largest))
    page = _Page(200.0 + length * scale, scale, length, "far")
    groups["part-kept"].append(_profile(page, segments, 0.0))
    _holes(groups, values, page, 0.0, set(_HOLES))
    groups["centre-line"].append(_line(160, _AXIS, page.x_out + 40, _AXIS))
    datum = page.x(0.0)
    low = 2 * _AXIS - page.up(largest)
    groups["datum"].append(_line(datum, page.up(largest) - 10, datum, low + 10))
    _datum_label(groups, datum - 6, low + 24, "Z0 datum end", "end")
    top = page.up(largest)
    _dimension(groups, datum, page.x(length), top - 18, top - 2, _length_text(values))
    if "shoulder_mm" in values:
        _dimension(
            groups,
            datum,
            page.x(values["shoulder_mm"]),
            top - 44,
            top - 2,
            "shoulder {{cad.shoulder_min_in:.3dot}}–{{cad.shoulder_max_in:.3dot}}",
        )
    items = []
    for name, z0, z1, radius in segments:
        a, b = page.span(z0, z1)
        items.append(((a + b) / 2, 2 * _AXIS - page.up(radius), _size(values, name)))
    if "bore_dia_mm" in values:
        items.append(
            (
                page.x(values["bore_z1_mm"]) - 6,
                _AXIS + values["bore_dia_mm"] / 2 * scale,
                [
                    "bore",
                    "Ø{{cad.bore_dia_min_in:.3dot}}–{{cad.bore_dia_max_in:.3dot}}",
                ],
            )
        )
    return _finish(groups, _callouts(groups, items, low + 30, above=False))


BUSH_LAYOUTS = {"turned-bush": _layout}
