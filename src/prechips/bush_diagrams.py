"""Turned-part lathe pictures for the ``turned-bush`` template.

One side elevation per setup, spindle axis across the page, chuck at the
left, tailstock at the right, operator side at the bottom. ``data-hold``
names how the work is held:

- ``bar``: round bar in the chuck, ``process.parts_per_pull`` parts (one by
  default) out past the jaws, each a ``cad.pitch_mm`` along the bar;
- ``block``: a squared blank (``process.blank_side_in``) in the 4-jaw;
- ``regrip``: the parted part turned round, the jaws on its ``data-grip``
  diameter over a shim wrap, ``cad.regrip_allowance_mm`` (left on by the
  parting) on its out end to face; it may turn what stands out of the
  jaws, never a diameter inside them, and then marks Z0 on its out end;
  ``data-z0="out"`` marks Z0 there without turning (a DRO set from a
  measured length), and ``data-seat="none"`` draws the chuck body clear of
  the part's end, nothing behind it (default ``chuck``: seated on the body);
  unseated, the grip reaches the part's chuck-side end or only smaller
  diameters stand behind it, inside the jaws' bore;
- ``mandrel``: the squared blank on a bolt through its bore, the bolt in the
  chuck, a washer and nut on each face;
- ``inspect``: the finished part alone with its printed sizes, its datum end
  labelled ``data-datum`` (default "Z0 datum end").

``data-out`` (``datum`` or ``far``) names the part's end toward the
tailstock; ``data-work`` lists what the setup does, from ``face``,
``centre``, ``drill``, ``ream``, ``turn``, ``knurl``, ``recess``, ``pocket``,
``tap``, ``countersink``, ``chamfer`` and ``part``; ``data-turn`` names the
diameters a setup with ``turn`` turns (``outer``, ``step``, ``step_*``; all
by default on the bar or blank, required in a regrip; a knurled diameter is
turned to its knurl blank): on the bar or blank another diameter stands at
the largest turned
here where those passes run over it, else as it arrived, for a later setup;
in a regrip the others are finished already; ``data-chamfers`` names the
chamfers a setup with ``chamfer`` cuts (all by default); ``data-chuck``
(``3-jaw`` or ``4-jaw``) names the chuck;
``data-member`` draws a member on its own bar (the default member when
omitted or named). Part
sizes come from the adapter; chuck, jaws, tools, bolt and nut are schematic
symbols. Material arriving is dashed, material removed in the setup hatched,
material kept solid, holes made by now dashed as hidden edges.
"""

from __future__ import annotations

from xml.etree import ElementTree

from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _bound, _cad, _el, _line, _rect
from prechips.jig_diagrams import _datum_label, _finish, _groups, _param, _title
from prechips.shaft_diagrams import CHAR, _break, _callouts, _dimension

Groups = dict[str, list[Element]]

_HOLDS = ("bar", "block", "regrip", "mandrel", "inspect")
_OUTS = ("datum", "far")
_Z0S = ("datum", "out")
_SEATS = ("chuck", "none")
_WORK = (
    "face",
    "centre",
    "drill",
    "ream",
    "turn",
    "knurl",
    "recess",
    "pocket",
    "tap",
    "countersink",
    "chamfer",
    "part",
)
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
_GAP = 14.0  # an unseated regrip: chuck body behind the part's end, px
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
        for name in (outer, "step", *values.get("step_diameters", []))
        if f"{name}_dia_mm" in values
    ]


def _knurl_lines(name: str) -> list[str]:
    return [
        f"{{{{cad.{name}_knurl_pattern}}}} knurl",
        f"{{{{cad.{name}_knurl_tpi}}}} TPI",
    ]


def _countersinks(values: dict, out: str | None = None) -> list[str]:
    """The part's countersinks; with ``out``, those at the end toward the
    tailstock (``datum``: the datum end; ``far``: the far end or recess)."""
    ends = {"datum": {"datum_end"}, "far": {"far_end", "recess"}}.get(out)
    return [
        name
        for name in values.get("countersinks", [])
        if ends is None or ends & set(values[f"{name}_ends"])
    ]


_CSK_ENDS = {"datum_end": "datum end", "far_end": "far end", "recess": "in the recess"}


def _csk_text(name: str) -> str:
    return (
        f"countersink Ø{{{{cad.{name}_dia_max_in:.2dot}}}} max"
        f" × {{{{cad.{name}_angle_deg:.0f}}}}°"
    )


def _recess_lines() -> list[str]:
    return [
        "recess Ø{{cad.recess_dia_min_in:.2dot}}–{{cad.recess_dia_max_in:.2dot}}",
        "to Ø{{cad.recess_floor_dia_min_in:.2dot}}–{{cad.recess_floor_dia_max_in:.2dot}} floor,",
        "{{cad.recess_depth_min_in:.2dot}}–{{cad.recess_depth_max_in:.2dot}} deep",
    ]


def _band(key: str, places: int) -> str:
    """``min–max`` tokens of the inch band ``key``."""
    return (
        f"{{{{cad.{key}_min_in:.{places}dot}}}}–{{{{cad.{key}_max_in:.{places}dot}}}}"
    )


def _chamfer_leg(values: dict, name: str) -> str:
    """A chamfer's leg: its band, or its single MAX limit."""
    if f"{name}_leg_min_in" in values:
        return _band(f"{name}_leg", 3)
    return f"{{{{cad.{name}_leg_max_in:.3dot}}}} max"


def _bore_band(values: dict) -> str:
    """``min–max`` tokens of the bore's band: four places on a band under
    .002 in wide (a reamed fit), as the turned diameters print."""
    spread = values["bore_dia_max_in"] - values["bore_dia_min_in"]
    return _band("bore_dia", 4 if spread < 0.002 else 3)


def _size(values: dict, name: str) -> list[str]:
    """The printed acceptance of one turned diameter, on two lines."""
    if values.get(f"{name}_stock"):
        return [f"Ø{{{{cad.{name}_ref_in:.4dot}}}}", "bar as bought"]
    fit = [f"{_band(f'{name}_clearance', 4)} under its mate"]
    if f"{name}_dia_min_in" in values:
        spread = values[f"{name}_dia_max_in"] - values[f"{name}_dia_min_in"]
        band = [f"Ø{_band(f'{name}_dia', 4 if spread < 0.002 else 3)}"]
        if f"{name}_knurl_tpi" in values:
            return [f"{band[0]} over", *_knurl_lines(name)]
        # A band with a fit on its mate prints both: the fit holds too.
        return band + fit if f"{name}_clearance_min_in" in values else band
    if f"{name}_interference_min_in" in values:
        return ["to its measured mate,", f"{_band(f'{name}_interference', 4)} over"]
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
    """Hidden edges of the named holes (``bore``, ``pocket``, ``tap``,
    ``recess``)."""
    runs = []
    if "bore" in holes and "bore_dia_mm" in values:
        runs.append((values["bore_z0_mm"], values["bore_z1_mm"], values["bore_dia_mm"]))
    if "pocket" in holes and "pocket_dia_mm" in values:
        runs.append((0.0, values["pocket_depth_mm"], values["pocket_dia_mm"]))
    if "recess" in holes and "recess_dia_mm" in values:
        # The cone from the far end's rim down to the flat floor.
        z_rim, z_floor = values["length_mm"], values["recess_z0_mm"]
        rim, floor = values["recess_dia_mm"] / 2, values["recess_floor_dia_mm"] / 2
        points = [
            (page.x(z_rim, shift), page.up(rim)),
            (page.x(z_floor, shift), page.up(floor)),
            (page.x(z_floor, shift), page.up(-floor)),
            (page.x(z_rim, shift), page.up(-rim)),
        ]
        path = "L".join(f"{x:.2f} {y:.2f}" for x, y in points)
        groups["hidden"].append(_el("path", d=f"M{path}"))
    if "tap" in holes and values.get("tap_kind") == "thru":
        # Through the part; a dished far end ends it at the recess floor.
        end = values["length_mm"]
        if "recess" in holes and "recess_z0_mm" in values:
            end = values["recess_z0_mm"]
        runs.append((0.0, end, values["tap_drill_dia_mm"]))
        x0, x1 = page.span(0.0, end, shift)
        radius = values["tap_drill_dia_mm"] / 2
        groups["part-threads"].append(
            _rect(x0, page.up(radius), x1 - x0, page.size(radius))
        )
    elif "tap" in holes and "tap_drill_dia_mm" in values:
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
    groups: Groups,
    page: _Page,
    x0: float,
    x1: float,
    radius: float,
    shim: float,
    back: float = 0.0,
) -> None:
    """Chuck body and the upper and lower jaws gripping ``radius`` from x0 to x1.

    ``back`` stands the body that far behind x0, the jaws running out to the
    grip: nothing behind the part seats it.
    """
    top, bottom = page.up(radius) - shim, 2 * _AXIS - page.up(radius) + shim
    body = x0 - back
    groups["fixture-vise"].append(
        _rect(body - _CHUCK, top - _JAW - 8, _CHUCK, bottom - top + 2 * _JAW + 16)
    )
    groups["clamp"] += [
        _rect(body, top - _JAW, x1 - body, _JAW),
        _rect(body, bottom, x1 - body, _JAW),
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


_HOLES = ("bore", "pocket", "tap", "recess")


def _layout(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    hold = root.attrib.pop("data-hold", None)
    out = root.attrib.pop("data-out", "datum")
    work = set(root.attrib.pop("data-work", "").split())
    holes = set(root.attrib.pop("data-holes", "").split())
    chuck = root.attrib.pop("data-chuck", "4-jaw" if hold == "block" else "3-jaw")
    grip = root.attrib.pop("data-grip", "outer")
    member = root.attrib.pop("data-member", None)
    turn = root.attrib.pop("data-turn", None)
    chamfer_names = root.attrib.pop("data-chamfers", None)
    seat = root.attrib.pop("data-seat", None)
    z0 = root.attrib.pop("data-z0", None)
    datum_label = root.attrib.pop("data-datum", None)
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
    if "ream" in work and "bore_dia_mm" not in values:
        raise CadError("turned-bush: ream needs the part's bore")
    if "recess" in work and "recess_dia_mm" not in values:
        raise CadError("turned-bush: recess needs the part's recess")
    if "recess" in work and out != "far":
        raise CadError("turned-bush: the recess is cut with the far end out")
    if "countersink" in work and not _countersinks(values, out):
        raise CadError("turned-bush: countersink needs a countersink at the out end")
    if "knurl" in work and not any(k.endswith("_knurl_tpi") for k in values):
        raise CadError("turned-bush: knurl needs a knurled diameter")
    if hold == "mandrel" and "bore_dia_mm" not in values:
        raise CadError("turned-bush: a mandrel hold needs the part's bore")
    if turn is not None and "turn" not in work:
        raise CadError("turned-bush: data-turn needs turn in data-work")
    if hold == "regrip" and "turn" in work and turn is None:
        raise CadError(
            "turned-bush: a regrip that turns names its diameters in data-turn"
        )
    for name, value, allowed in (("seat", seat, _SEATS), ("z0", z0, _Z0S)):
        if value is not None and value not in allowed:
            raise CadError(
                f"turned-bush: data-{name} must be {' or '.join(allowed)}, not {value!r}"
            )
        if value is not None and hold != "regrip":
            raise CadError(f"turned-bush: data-{name} is for a regrip")
    if z0 == "datum" and "turn" in work and out == "far":
        raise CadError("turned-bush: a regrip that turns marks Z0 on its out end")
    # Where the regrip marks Z0: its out end when it turns (the regrip_jaw_z
    # bindings' frame) or when told, else the datum end.
    z0 = "out" if z0 == "out" or "turn" in work else "datum"
    if datum_label is not None and (hold != "inspect" or not datum_label.strip()):
        raise CadError("turned-bush: data-datum labels the inspect picture's datum end")
    groups = _groups(root)
    _title(groups, 20, 24, _TITLES[hold])
    if hold == "inspect":
        return _inspect(groups, values, outer, datum_label or "Z0 datum end")
    if "drill" in work:
        holes.add("bore" if "bore_dia_mm" in values else "tap")
    holes |= work & {"pocket", "tap", "recess"}
    names = [seg[0] for seg in _segments(values, outer)]
    turned = set(names)
    if turn is not None:
        # data-turn names the diameters this setup turns, by feature name
        # ("outer" the drawn member's).
        turned = {outer if name == "outer" else name for name in turn.split()}
        if not turned or turned - set(names):
            raise CadError(
                f"turned-bush: data-turn {turn!r} must name turned diameters"
                f" ({', '.join(names)})"
            )
    chamfers = sorted(
        key.removesuffix("_leg_mm")
        for key in values
        if key.startswith("chamfer_") and key.endswith("_leg_mm")
    )
    if chamfer_names is not None:
        # data-chamfers names the chamfers this setup cuts, by feature name.
        named = chamfer_names.split()
        if not named or set(named) - set(chamfers):
            raise CadError(
                f"turned-bush: data-chamfers {chamfer_names!r} must name chamfers"
                f" ({', '.join(chamfers)})"
            )
        chamfers = sorted(named)
    return _setup(
        groups,
        values,
        parameters,
        hold,
        out,
        work,
        holes,
        chuck,
        grip,
        outer,
        turned,
        chamfers,
        seat or "chuck",
        z0,
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
    turned: set,
    chamfers: list,
    seat: str,
    z0_at: str,
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
    elif "turn" in work and any(
        seg[3] >= largest - 1e-6 for seg in segments if seg[0] in turned
    ):
        # A regrip turning the largest diameter turns it from the bar.
        stock = _param(parameters, stock_key) * 12.7
    else:
        stock = largest
    if "turn" in work and hold != "regrip" and turned != {s[0] for s in segments}:
        # On the bar or blank a diameter another (later) setup turns stands
        # at the smallest this setup's passes over it leave, the largest
        # diameter turned here, or as arrived when larger than that. In a
        # regrip the others are finished already and drawn so.
        left = max(seg[3] for seg in segments if seg[0] in turned)
        segments = [
            seg if seg[0] in turned else (*seg[:3], left if seg[3] < left else stock)
            for seg in segments
        ]
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
        # A regrip turns or knurls only what stands out of its jaws.
        for name, a0, a1, _ in segments:
            inside = a0 < z1 - 1e-6 and a1 > z0 + 1e-6
            if inside and "turn" in work and name in turned:
                raise CadError(f"turned-bush: the regrip turns {name} in its jaws")
            if inside and "knurl" in work and f"{name}_knurl_tpi" in values:
                raise CadError(f"turned-bush: the regrip knurls {name} in its jaws")
        behind = 0.0
        if seat == "none":
            # Nothing behind the part: the grip must reach its chuck-side end,
            # or what stands behind it must be smaller, inside the jaws' bore
            # (the body is then drawn clear of the part's end).
            end = z0 if out == "far" else length - z1
            back_segments = [
                seg
                for seg in segments
                if (seg[2] <= z0 + 1e-6 if out == "far" else seg[1] >= z1 - 1e-6)
            ]
            if end > 1e-6 and any(seg[3] >= radius - 1e-6 for seg in back_segments):
                raise CadError(
                    "turned-bush: data-seat none needs the grip at the part's"
                    " chuck-side end, or only smaller diameters behind it"
                )
            behind = end * page.scale
        x0, x1 = page.span(z0, z1)
        jaw_end = x1
        back = _GAP + behind if seat == "none" else 0.0
        _chuck(groups, page, x0 + 2, x1 - 2, radius, _SHIM, back)
        lines = [f"{chuck} chuck, jaws", "on a shim wrap"]
        if seat == "none":
            lines.append("nothing behind the part")
        above.append((x1 - 6, page.up(radius) - _SHIM - _JAW, lines))
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
            for name, z0, z1, radius in segments:
                # In a regrip only the named diameters are cut here.
                cut = name in turned or hold != "regrip"
                if cut and radius < stock - 1e-6:
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
        through = (
            "bore"
            if "bore" in holes and "bore_dia_mm" in values
            else "tap"
            if "tap" in holes and values.get("tap_kind") == "thru"
            else None
        )
        if kerf and hold in ("bar", "block") and {"drill", "part"} <= work and through:
            # A through hole is drilled past the parting line: from the
            # hole's chuck-side end it runs on through any regrip allowance
            # and the kerf.
            radius = (
                values[f"{'bore' if through == 'bore' else 'tap_drill'}_dia_mm"] / 2
            )
            x_end = page.x(
                values[f"{through}_z1_mm" if out == "datum" else f"{through}_z0_mm"],
                shift,
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
        if hold == "regrip" and z0_at == "out":
            # A regrip that turns, or one set by data-z0="out", sets its DRO
            # Z0 on the faced out end (the regrip_jaw_z bindings' frame), not
            # the end in the jaws.
            datum_x = page.x_out
        low = 2 * _AXIS - page.up(largest)
        groups["datum"].append(_line(datum_x, page.up(largest) - 10, datum_x, low + 10))
        if hold == "regrip" and jaw_end > datum_x - 4 - 3 * CHAR:
            # Jaws reaching under the label's place: it goes past the facing
            # tool, on the tailstock side of the line.
            _datum_label(groups, datum_x + 22, low + 24, "Z0", "start")
        else:
            _datum_label(groups, datum_x - 4, low + 24, "Z0", "end")
    if "turn" in work:
        for name, z0, z1, radius in segments:
            if (
                name not in turned
                or values.get(f"{name}_stock")
                or radius >= stock - 1e-6
            ):
                continue
            a, b = page.span(z0, z1)
            lines = _size(values, name)
            if f"{name}_knurl_tpi" in values:
                # Turned to its knurl blank; the knurl raises it into its band.
                lines = [f"Ø{{{{cad.{name}_knurl_blank_in:.3dot}}}} blank"]
                if "knurl" in work:
                    band = _band(f"{name}_dia", 3)
                    lines = [
                        f"Ø{{{{cad.{name}_knurl_blank_in:.3dot}}}},",
                        "knurl to",
                        f"Ø{band}",
                    ]
            above.append(
                ((a + b) / 2, page.up(radius), [f"turn {lines[0]}", *lines[1:]])
            )
    if "knurl" in work:
        for name, z0, z1, radius in segments:
            # A knurled diameter turned here carries its knurl in its turn
            # label; any other knurled diameter gets its own.
            if f"{name}_knurl_tpi" in values and not (
                "turn" in work and name in turned
            ):
                a, b = page.span(z0, z1)
                lines = [*_knurl_lines(name), *_size(values, name)[:1]]
                above.append(((a + b) / 2, page.up(radius), lines))
    if "recess" in work:
        below.append(
            (
                page.x_out - 6,
                _AXIS + values["recess_dia_mm"] / 2 * scale,
                _recess_lines(),
            )
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
        token
        for token in ("centre", "drill", "ream", "pocket", "countersink", "tap")
        if token in work
    ]
    if hole_work:
        _tailstock(groups, x_tail + 14)
        lines = {
            "centre": "centre drill",
            # A reamed bore: the drill opens it under the reamer, which
            # makes the printed size.
            "drill": "drill under the reamer"
            if "ream" in work
            else f"drill the Ø{_bore_band(values)} hole"
            if "bore_dia_mm" in values
            else "drill through"
            if values.get("tap_kind") == "thru"
            else "drill {{cad.tap_drill_depth_min_in:.2dot}}–{{cad.tap_drill_depth_max_in:.2dot}} deep",
            "pocket": "pocket {{cad.pocket_depth_min_in:.3dot}}–{{cad.pocket_depth_max_in:.3dot}} deep",
            "countersink": ", ".join(_csk_text(n) for n in _countersinks(values, out)),
            "tap": "tap {{cad.tap_thread}}",
        }
        if "ream" in work:
            lines["ream"] = f"ream the Ø{_bore_band(values)} hole"
        head = "tailstock, in turn:" if len(hole_work) > 1 else "tailstock:"
        above.append((x_tail + 40, _AXIS - 5, [head, *(lines[t] for t in hole_work)]))
    if "chamfer" in work and chamfers:
        below.append(
            (
                page.x_out - 4,
                2 * _AXIS - page.up(largest),
                ["chamfer:"]
                + [f"{_chamfer_leg(values, name)} × 45°" for name in chamfers],
            )
        )
    top = _callouts(groups, above, top_y - 30, above=True)
    if top < 34:
        raise CadError("turned-bush: labels run off the top of the picture")
    bottom = 2 * _AXIS - top_y + 60
    if below:
        bottom = _callouts(groups, below, bottom, above=False)
    return _finish(groups, bottom)


def _inspect(groups: Groups, values: dict, outer: str, datum_label: str) -> Layout:
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
    if len(_bound(datum_label)) * CHAR + 6 > datum:
        raise CadError(f"turned-bush: data-datum {datum_label!r} runs off the page")
    _datum_label(groups, datum - 6, low + 24, datum_label, "end")
    top = page.up(largest)

    def dimension(x1: float, y: float, text: str) -> None:
        # A label wider than its span would sit across the extension lines:
        # it goes past the span's far end instead.
        beside = len(_bound(text)) * CHAR + 8 > x1 - datum
        _dimension(groups, datum, x1, y, top - 2, text, beside=beside)

    dimension(page.x(length), top - 18, _length_text(values))
    # The nearest shoulder sits nearest the part, so the extension lines of
    # the farther ones run clear of the nearer dimensions.
    shoulders = sorted(
        values.get("shoulders", []),
        key=lambda name: values[f"{name}_mm"],
    )
    for index, name in enumerate(shoulders):
        # A named shoulder's dimension runs from the datum end to that face.
        word = (
            "shoulder"
            if name == "shoulder"
            else f"to {name.removeprefix('shoulder_').replace('_', ' ')} face"
        )
        y = top - 44 - 26 * index
        if y < 34:
            raise CadError("turned-bush: the shoulder dimensions run off the top")
        dimension(
            page.x(values[f"{name}_mm"]),
            y,
            f"{word} {{{{cad.{name}_min_in:.3dot}}}}–{{{{cad.{name}_max_in:.3dot}}}}",
        )
    items = []
    for name, z0, z1, radius in segments:
        a, b = page.span(z0, z1)
        items.append(((a + b) / 2, 2 * _AXIS - page.up(radius), _size(values, name)))
    if "recess_dia_mm" in values:
        items.append(
            (
                page.x_out - 4,
                _AXIS + values["recess_dia_mm"] / 2 * scale,
                _recess_lines(),
            )
        )
    countersinks = []
    for name in _countersinks(values):
        ends = values[f"{name}_ends"]
        where = "both ends" if len(ends) > 1 else _CSK_ENDS[ends[0]]
        head, tail = _csk_text(name).split(" × ")
        countersinks += [head, f"× {tail}, {where}"]
    if values.get("tap_kind") == "thru":
        lines = ["{{cad.tap_thread}} through,", *countersinks]
        items.append((page.x(values["length_mm"] / 2), _AXIS, lines))
    elif countersinks:
        items.append((page.x(values["length_mm"] / 2), _AXIS, countersinks))
    if "bore_dia_mm" in values:
        items.append(
            (
                page.x(values["bore_z1_mm"]) - 6,
                _AXIS + values["bore_dia_mm"] / 2 * scale,
                [
                    # A drilled hole is a hole: "bore" would also name a
                    # pocket a boring bar opens on the same sheet.
                    "hole" if values.get("bore_process") == "drill" else "bore",
                    f"Ø{_bore_band(values)}",
                ],
            )
        )
    return _finish(groups, _callouts(groups, items, low + 30, above=False))


BUSH_LAYOUTS = {"turned-bush": _layout}
