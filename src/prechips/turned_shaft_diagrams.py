"""Turned-shaft pictures for the ``turned-shaft`` template.

One picture per setup, drawn from the ``turned_shaft`` adapter's values.
``data-hold`` names how the work is held:

- ``saw``: the round stock (``process.stock_dia_in``) with the saw cut at
  ``process.blank_length_in`` from its end, the blank dimensioned (a kerf
  ``process.saw_kerf_in`` drawn when stated);
- ``bar``: round bar in the chuck, ``process.parts_per_pull`` parts (one by
  default) out past the jaws, each a ``cad.pitch_mm`` along the bar;
- ``blank``: a sawn blank in the chuck, ``cad.end_stickout_mm`` out, the
  ``cad.face_stock_per_end_mm`` on its out end;
- ``regrip``: the part turned round, the jaws on its ``data-grip`` diameter
  (``outer`` by default) over a shim wrap;
- ``vise``: a top view in the milling vise, the flats up, the ``data-x0`` end
  (``datum``, the default, or ``far``: the end the mill's X0 is set on) at the
  left, the jaws from ``process.vise_jaw_from_x0_mm`` to
  ``process.vise_jaw_to_x0_mm`` (the jaw sides' distances from that end, as a
  beam clamps), the flats' stations dimensioned from the ends their drawing
  states, and an end view of the hold;
- ``inspect``: the finished part with its printed sizes.

Lathe holds are side elevations, chuck at the left, ``data-out`` (``datum``
or ``far``) the part's end toward the tailstock. ``data-work`` lists what the
setup does: ``face``, ``turn``, ``dome`` (the out end's), ``groove``,
``thread``, ``chamfer``, ``part`` (lathe holds) and ``flat`` (the vise);
``steps`` labels the out end's dome with the adapter's stepped-turning table
(``process.dome_steps``);
``data-done`` what earlier setups made (``turn``, ``groove``, ``thread``,
``dome-datum``, ``dome-far``, ``face-datum``, ``face-far``); the vise and the inspection assume every
lathe feature made. A feature not yet made is drawn at the size it arrives
at. Lathe pictures are to scale; the vise and inspection pictures are to
scale along the axis and draw diameters larger when the part is slender (the
title says so). Material arriving is dashed, material removed in the setup
hatched, the part solid; holes made at assembly are dashed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from xml.etree import ElementTree

from prechips.bush_diagrams import _AXIS, _JAW, _SHIM, _chuck
from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _cad, _el, _line, _rect
from prechips.jig_diagrams import _datum_label, _finish, _groups, _param, _title
from prechips.shaft_diagrams import _break, _callouts, _clip, _dimension, _pt

Groups = dict[str, list[Element]]
Profile = list[tuple[float, float]]  # (Z, radius) along the upper meridian

_HOLDS = ("saw", "bar", "blank", "regrip", "vise", "inspect")
_OUTS = ("datum", "far")
_WORK = ("face", "turn", "dome", "steps", "groove", "thread", "chamfer", "part", "flat")
_DONE = ("turn", "groove", "thread", "dome-datum", "dome-far", "face-datum", "face-far")
_TITLES = {
    "saw": "Sawing the blank, seen from the side",
    "bar": "Bar in the chuck, seen from the operator's side",
    "blank": "Sawn blank in the chuck, seen from the operator's side",
    "regrip": "Part turned round in the chuck, seen from the operator's side",
    "vise": "In the vise, flats up, seen from above",
    "inspect": "Finished part, seen from the side",
}
_X0 = 110.0  # page x of the window's chuck-side end
_HELD = 10.0  # mm of work drawn in the jaws
_ARC = 12  # points per dome meridian


@dataclass(frozen=True)
class _View:
    """Z maps right from ``x0`` at ``z0``; radii scale by ``radial``. With
    ``flip`` set, station z is drawn at ``flip - z`` (the far end at left)."""

    x0: float
    z0: float
    scale: float
    radial: float
    flip: float | None = None

    def x(self, z: float) -> float:
        if self.flip is not None:
            z = self.flip - z
        return self.x0 + (z - self.z0) * self.scale

    def up(self, radius: float) -> float:
        return _AXIS - radius * self.radial

    def down(self, radius: float) -> float:
        return _AXIS + radius * self.radial


def _band(key: str, places: int = 3) -> str:
    return (
        f"{{{{cad.{key}_min_in:.{places}dot}}}}–{{{{cad.{key}_max_in:.{places}dot}}}}"
    )


def _names(values: dict, prefix: str, suffix: str) -> list[str]:
    return sorted(
        key.removesuffix(suffix)
        for key in values
        if key.startswith(prefix) and key.endswith(suffix)
    )


def _diameters(values: dict) -> list[str]:
    return sorted(
        (name for name in ("outer", "step") if f"{name}_dia_mm" in values),
        key=lambda name: values[f"{name}_z0_mm"],
    )


def _radius(values: dict, name: str, made: set) -> float:
    """A diameter's radius as it stands: its bar until it is turned."""
    if (
        "turn" in made
        or values.get(f"{name}_stock")
        or values.get(f"{name}_as_supplied")
        or "stock_dia_mm" not in values
    ):
        return values[f"{name}_dia_mm"] / 2
    return values["stock_dia_mm"] / 2


def _meridian(values: dict, made: set, *, flats: bool = False) -> Profile:
    """``(station, radius)`` from the datum end's apex to the far end's."""
    length = _cad(values, "length_mm")
    names = _diameters(values)
    runs = [
        (values[f"{n}_z0_mm"], values[f"{n}_z1_mm"], _radius(values, n, made))
        for n in names
    ]
    cuts = []
    if "groove" in made:
        cuts += [
            (values[f"{g}_z0_mm"], values[f"{g}_z1_mm"], values[f"{g}_dia_mm"] / 2)
            for g in _names(values, "groove", "_width_mm")
        ]
    if flats:
        for f in _names(values, "flat_", "_across_mm"):
            dia = values[f"{values[f'{f}_on']}_dia_mm"]
            cuts.append(
                (
                    values[f"{f}_z0_mm"],
                    values[f"{f}_z1_mm"],
                    values[f"{f}_across_mm"] - dia / 2,
                )
            )
    domes = {
        prefix: f"dome-{prefix.removeprefix('dome_')}" in made
        and f"{prefix}_height_mm" in values
        for prefix in ("dome_datum", "dome_far")
    }
    start = values["dome_datum_root_z_mm"] if domes["dome_datum"] else 0.0
    end = values["dome_far_root_z_mm"] if domes["dome_far"] else length
    stops = sorted({start, end, *(z for run in runs + cuts for z in run[:2])})
    stops = [z for z in stops if start - 1e-9 <= z <= end + 1e-9]
    points: Profile = []
    if domes["dome_datum"]:
        points += _cap(values, "dome_datum", 0.0, 1)
    else:
        points.append((0.0, 0.0))
    for a, b in pairwise(stops):
        mid = (a + b) / 2
        radius = next((r for z0, z1, r in cuts if z0 <= mid <= z1), None)
        if radius is None:
            radius = next(
                (r for z0, z1, r in runs if z0 - 1e-6 <= mid <= z1 + 1e-6),
                runs[0][2] if mid < runs[0][0] else runs[-1][2],
            )
        points += [(a, radius), (b, radius)]
    if domes["dome_far"]:
        points += list(reversed(_cap(values, "dome_far", length, -1)))
    else:
        points.append((length, 0.0))
    return points


def _cap(values: dict, prefix: str, apex: float, inward: int) -> Profile:
    """A dome's meridian from its apex to its root, as stations."""
    radius, height = values[f"{prefix}_radius_mm"], values[f"{prefix}_height_mm"]
    return [
        (apex + inward * s, math.sqrt(max(s * (2 * radius - s), 0.0)))
        for s in (height * i / _ARC for i in range(_ARC + 1))
    ]


def _outline(
    view: _View, top: Profile, bottom: Profile | None = None, *, cut: bool = False
) -> Element:
    """Closed outline; ``cut`` breaks its left end (the work runs on)."""
    bottom = top if bottom is None else bottom
    upper = [(view.x(z), view.up(r)) for z, r in top]
    lower = [(view.x(z), view.down(r)) for z, r in reversed(bottom)]
    d = "M" + "L".join(_pt(*p) for p in upper + lower)
    if cut:
        d += _break(lower[-1][0], lower[-1][1], upper[0][1])
    return _el("path", d=d + "Z")


def _layout(values: dict, parameters: dict, root: ElementTree.Element) -> Layout:
    hold = root.attrib.pop("data-hold", None)
    out = root.attrib.pop("data-out", "datum")
    work = set(root.attrib.pop("data-work", "").split())
    done = set(root.attrib.pop("data-done", "").split())
    grip = root.attrib.pop("data-grip", "outer")
    x0 = root.attrib.pop("data-x0", "datum")
    if x0 not in _OUTS or (x0 != "datum" and hold != "vise"):
        raise CadError("turned-shaft: data-x0 is datum or far, on a vise hold")
    if hold not in _HOLDS:
        raise CadError(
            f"turned-shaft: data-hold must be one of {', '.join(_HOLDS)}, not {hold!r}"
        )
    if out not in _OUTS:
        raise CadError("turned-shaft: data-out must be datum or far")
    if work - set(_WORK):
        raise CadError(
            f"turned-shaft: unknown data-work {', '.join(sorted(work - set(_WORK)))}"
        )
    if done - set(_DONE):
        raise CadError(
            f"turned-shaft: unknown data-done {', '.join(sorted(done - set(_DONE)))}"
        )
    if hold == "vise" and work - {"flat"}:
        raise CadError("turned-shaft: the vise mills flats only")
    if hold in ("bar", "blank", "regrip") and "flat" in work:
        raise CadError("turned-shaft: flats are milled in the vise")
    if hold in ("bar", "regrip") and "pitch_mm" not in values:
        raise CadError(f"turned-shaft: a {hold} hold needs the bar-fed cycle")
    if "part" in work and hold != "bar":
        raise CadError("turned-shaft: parts are parted off in a bar hold")
    if hold == "blank" and "end_stickout_mm" not in values:
        raise CadError("turned-shaft: a blank hold needs process.end_stickout_in")
    if "steps" in work and not ("dome" in work and "dome_steps" in parameters):
        raise CadError("turned-shaft: steps label a dome with process.dome_steps")
    groups = _groups(root)
    if hold == "saw":
        return _saw(groups, values, parameters)
    if hold in ("vise", "inspect"):
        made = {"turn", "groove", "thread", "dome-datum", "dome-far"}
        if hold == "vise":
            return _vise(groups, values, parameters, made, x0)
        return _inspect(groups, values, made)
    _title(groups, 20, 24, _TITLES[hold])
    made = done | (work & {"turn", "groove", "thread"})
    if "dome" in work:
        made.add(f"dome-{out}")
    return _lathe(groups, values, parameters, hold, out, work, made, grip)


def _lathe(
    groups: Groups,
    values: dict,
    parameters: dict,
    hold: str,
    out: str,
    work: set,
    made: set,
    grip: str,
) -> Layout:
    length = _cad(values, "length_mm")
    names = _diameters(values)

    def z_of(station: float) -> float:
        """Station into the part as lathe Z: Z0 the out end, Z+ out."""
        return -station if out == "datum" else station - length

    stock = values.get("stock_dia_mm", 0.0) / 2
    count, pitch, face, kerf, regrip = 1, length, 0.0, 0.0, 0.0
    if hold == "bar":
        count = int(parameters.get("parts_per_pull", 1))
        pitch = _cad(values, "pitch_mm")
        regrip = float(values.get("regrip_allowance_mm", 0.0))
        face = _param(parameters, "face_allowance_in") * 25.4 if "face" in work else 0.0
        kerf = _param(parameters, "part_kerf_in") * 25.4
        jaw = float(values.get("jaw_z_mm", -(count * pitch)))
    elif hold == "blank":
        face = float(values["face_stock_per_end_mm"]) if "face" in work else 0.0
        jaw = float(values["end_jaw_z_mm"])
    else:
        if f"{grip}_dia_mm" not in values:
            raise CadError(f"turned-shaft: data-grip {grip!r} is not a turned diameter")
        if "face" in work:
            face = float(values.get("regrip_allowance_mm", 0.0))
        z0, z1 = values[f"{grip}_z0_mm"], values[f"{grip}_z1_mm"]
        held_mm = float(values.get("regrip_grip_mm", math.inf))
        if out == "datum":
            near = max(z0, z1 - held_mm)
            far_side = z1
        else:
            near = min(z1, z0 + held_mm)
            far_side = z0
        jaw = z_of(near)
        back = z_of(far_side)
    zmin = jaw - _HELD if hold != "regrip" else max(jaw - _HELD, back)
    if hold == "blank":
        zmin = max(zmin, -length)
    reach = face - zmin
    largest = max([stock, *(values[f"{n}_dia_mm"] / 2 for n in names)])
    scale = min(14.0, 420.0 / reach, 70.0 / largest)
    view = _View(_X0, zmin, scale, scale)
    groups["centre-line"].append(
        _line(view.x(zmin) - 50, _AXIS, view.x(face) + 120, _AXIS)
    )
    station = _meridian(values, made)
    above: list[tuple[float, float, list[str]]] = []
    below: list[tuple[float, float, list[str]]] = []
    if hold in ("bar", "blank"):
        y0, y1 = view.up(stock), view.down(stock)
        left = view.x(zmin) - 40
        groups["part-arriving"].append(_rect(left, y0, view.x(face) - left, y1 - y0))
        bar = (
            "jaws on bar Ø{{process.stock_dia_in:.4dot}}"
            if hold == "bar"
            else "jaws on the blank"
        )
        _chuck(groups, view, view.x(zmin), view.x(jaw), stock, 0.0)
        above.append((view.x(zmin) + 4, y0 - _JAW, ["3-jaw chuck,", bar]))
    for k in range(count):
        shift = k * pitch
        # The meridian runs datum to far; lathe Z ascends toward the out end.
        profile = [(z_of(s) - shift, r) for s, r in station]
        if out == "datum":
            profile.reverse()
        clipped = _clip(profile, zmin, 0.0)
        cut = clipped[0][0] > profile[0][0] + 1e-9
        groups["part-kept"].append(_outline(view, clipped, cut=cut))
        if hold == "bar":
            # Left on the parted end to face in the regrip, then the kerf.
            end = -shift - length
            radius = clipped[0][1] if not cut else stock
            radius = next(
                (r for z, r in profile if abs(z - end) < 1e-6 and r > 0), radius
            )
            if regrip:
                groups["part-kept"].append(
                    _rect(
                        view.x(end - regrip),
                        view.up(radius),
                        regrip * scale,
                        2 * radius * scale,
                    )
                )
            line = end - regrip
            groups["part-removed"].append(
                _rect(
                    view.x(line - kerf), view.up(stock), kerf * scale, 2 * stock * scale
                )
            )
            if k == count - 1 and line - kerf > zmin:
                groups["part-rest"].append(
                    _el(
                        "path",
                        d=f"M{_pt(view.x(zmin) - 40, view.up(stock))}"
                        f"H{view.x(line - kerf):.2f}V{view.down(stock):.2f}"
                        f"H{view.x(zmin) - 40:.2f}"
                        f"{_break(view.x(zmin) - 40, view.down(stock), view.up(stock))}Z",
                    )
                )
        _removed(groups, values, view, work, made, z_of, shift, stock, out)
    if hold == "regrip":
        r_grip = values[f"{grip}_dia_mm"] / 2
        _chuck(groups, view, view.x(zmin) + 2, view.x(jaw) - 2, r_grip, _SHIM)
        above.append(
            (
                view.x(jaw) - 6,
                view.up(r_grip) - _SHIM - _JAW,
                ["3-jaw chuck, jaws", "on a shim wrap"],
            )
        )
    if face:
        # The out end arrives at the bar's size, or turned in an earlier setup.
        radius = stock
        if hold == "regrip" and "turn" in made and "turn" not in work:
            end = _diameters(values)
            end.sort(key=lambda n: values[f"{n}_z0_mm"], reverse=out == "far")
            radius = values[f"{end[0]}_dia_mm"] / 2
        if hold == "regrip":
            groups["part-arriving"].append(
                _rect(view.x(0), view.up(radius), face * scale, 2 * radius * scale)
            )
        groups["part-removed"].append(
            _rect(view.x(0), view.up(radius), face * scale, 2 * radius * scale)
        )
    top = view.up(largest)
    bottom = view.down(largest)
    groups["datum"].append(_line(view.x(0), top - 10, view.x(0), bottom + 10))
    _datum_label(groups, view.x(0) - 4, bottom + 24, "Z0", "end")
    # The stickout runs to the arriving end; a blank's to its faced end.
    _dimension(
        groups,
        view.x(jaw),
        view.x(0 if hold == "blank" else face),
        bottom + 44,
        bottom + 2,
        _stickout(values, hold, out, grip),
    )
    other = "far" if out == "datum" else "datum"
    to_length = hold == "regrip" or f"face-{other}" in made
    _labels(values, view, work, z_of, out, above, below, to_length)
    if work & {"face", "turn", "dome", "groove", "chamfer"}:
        # The turning tool, beside the out end, clear of the labels.
        x = view.x(face) + 4
        groups["cutter"].append(
            _el("path", d=f"M{x:.2f} {bottom + 6:.2f}l18 5v28h-18z")
        )
    if "part" in work:
        line = -length - float(values.get("regrip_allowance_mm", 0.0))
        x = view.x(line - kerf)
        groups["cutter"].append(_rect(x, bottom + 4, kerf * scale, 40))
        below.append(
            (x + kerf * scale / 2, bottom + 44, ["parting blade:", "part off"])
        )
    if "thread" in work and "thread_z0_mm" in values:
        radius = values[f"{values['thread_on']}_dia_mm"] / 2
        x = view.x(face) + 40
        groups["cutter"] += [
            _rect(x, view.up(radius) - 16, 14, 16),
            _rect(x, view.down(radius), 14, 16),
        ]
        groups["fixture-vise"].append(_rect(x + 14, _AXIS - 12, 40, 24))
        above.append(
            (
                x + 30,
                _AXIS - 12,
                [
                    "die from the tailstock:",
                    "{{cad.thread_designation}}",
                    f"{_band('thread_length', 3)} long",
                ],
            )
        )
    head = _callouts(groups, above, top - 34, above=True)
    if head < 34:
        raise CadError("turned-shaft: labels run off the top of the picture")
    end = bottom + 64
    if below:
        end = _callouts(groups, below, end, above=False)
    return _finish(groups, end)


def _stickout(values: dict, hold: str, out: str, grip: str) -> str:
    if hold == "bar":
        return "{{cad.stickout_in:.3dot}} out"
    if hold == "blank":
        return "{{process.end_stickout_in:.3dot}} out"
    return f"{{{{cad.{grip}_stickout_{out}_mm:in.3dot}}}} out"


def _removed(
    groups: Groups,
    values: dict,
    view: _View,
    work: set,
    made: set,
    z_of,
    shift: float,
    stock: float,
    out: str,
) -> None:
    """Hatch what this setup cuts off one part."""
    length = values["length_mm"]

    def band(s0: float, s1: float, r_out: float, r_in: float, role="part-removed"):
        a, b = sorted((z_of(s0) - shift, z_of(s1) - shift))
        a = max(a, view.z0)
        if b <= a or r_out <= r_in + 1e-9:
            return
        w, h = (b - a) * view.scale, (r_out - r_in) * view.radial
        groups[role] += [
            _rect(view.x(a), view.up(r_out), w, h),
            _rect(view.x(a), view.down(r_in), w, h),
        ]

    if "turn" in work:
        for name in _diameters(values):
            if values.get(f"{name}_stock") or values.get(f"{name}_as_supplied"):
                continue
            band(
                values[f"{name}_z0_mm"],
                values[f"{name}_z1_mm"],
                stock,
                values[f"{name}_dia_mm"] / 2,
            )
    if "groove" in work:
        for g in _names(values, "groove", "_width_mm"):
            g0, g1 = values[f"{g}_z0_mm"], values[f"{g}_z1_mm"]
            # The diameter the groove cuts into (the adapter checks one does).
            under = max(
                values[f"{n}_dia_mm"] / 2
                for n in _diameters(values)
                if values[f"{n}_z0_mm"] < g1 and values[f"{n}_z1_mm"] > g0
            )
            band(
                values[f"{g}_z0_mm"],
                values[f"{g}_z1_mm"],
                under,
                values[f"{g}_dia_mm"] / 2,
            )
    prefix = f"dome_{out}"
    if "dome" in work and f"{prefix}_height_mm" in values:
        apex = 0.0 if out == "datum" else length
        inward = 1 if out == "datum" else -1
        cap = _cap(values, prefix, apex, inward)
        before = values[f"{prefix}_root_dia_mm"] / 2
        if "turn" not in made:
            before = stock
        for side in (view.up, view.down):
            points = [(view.x(z_of(s) - shift), side(r)) for s, r in cap]
            root_x = points[-1][0]
            points += [(root_x, side(before)), (points[0][0], side(before))]
            groups["part-removed"].append(
                _el("path", d="M" + "L".join(_pt(*p) for p in points) + "Z")
            )
    if "thread" in work and "thread_z0_mm" in values:
        radius = values[f"{values['thread_on']}_dia_mm"] / 2
        depth = min(0.6 * values["thread_pitch_mm"], radius / 3)
        band(
            values["thread_z0_mm"],
            values["thread_z1_mm"],
            radius,
            radius - depth,
            "part-threads",
        )


def _labels(
    values: dict,
    view: _View,
    work: set,
    z_of,
    out: str,
    above: list,
    below: list,
    to_length: bool,
) -> None:
    length = values["length_mm"]
    if "face" in work:
        text = ["face the end", "to Z0"]
        if to_length:
            band = (
                _band("faced_length")
                if "faced_length_min_in" in values
                else _length_text(values)
            )
            text = ["face to length", band]
        below.append(
            (view.x(0) + 1, view.down(values.get("stock_dia_mm", 0) / 2 or 1), text)
        )
    if "turn" in work:
        for name in _diameters(values):
            if values.get(f"{name}_stock") or values.get(f"{name}_as_supplied"):
                continue
            a = view.x(z_of(values[f"{name}_z0_mm"]))
            b = view.x(z_of(values[f"{name}_z1_mm"]))
            mid = (max(min(a, b), view.x0) + max(a, b)) / 2
            text = [f"turn Ø{_band(f'{name}_dia', 4)}"]
            if values.get("thread_on") == name:
                text.append("thread blank")
            above.append((mid, view.up(values[f"{name}_dia_mm"] / 2), text))
    prefix = f"dome_{out}"
    if "dome" in work and f"{prefix}_height_mm" in values:
        apex = 0.0 if out == "datum" else length
        inward = 1 if out == "datum" else -1
        mid = apex + inward * values[f"{prefix}_height_mm"] / 2
        r = values[f"{prefix}_root_dia_mm"] / 2 * 0.7
        text = _dome_text(values, prefix)
        if "steps" in work:
            text.append("step-turn {{process.dome_steps:d}} steps, file")
        above.append((view.x(z_of(mid)), view.up(r), text))
    if "groove" in work:
        for g in _names(values, "groove", "_width_mm"):
            a = view.x(z_of(values[f"{g}_z0_mm"]))
            b = view.x(z_of(values[f"{g}_z1_mm"]))
            below.append(
                (
                    (a + b) / 2,
                    view.down(values[f"{g}_dia_mm"] / 2),
                    [f"groove Ø{_band(f'{g}_dia')}", f"{_band(f'{g}_width')} wide"],
                )
            )
    if "chamfer" in work:
        chamfers = _names(values, "chamfer_", "_leg_min_in")
        if chamfers:
            below.append(
                (
                    view.x(0) - 4,
                    view.down(values.get("stock_dia_mm", 2) / 2),
                    ["break edges:", *(f"{_band(f'{c}_leg')} × 45°" for c in chamfers)],
                )
            )


def _length_text(values: dict) -> str:
    """The length band, or ``(.82) REF`` when the drawing gives a REF."""
    if "length_min_in" in values:
        return _band("length")
    return "({{cad.length_ref_in:.2dot}}) REF"


def _dome_text(values: dict, prefix: str) -> list[str]:
    """A dome's radius and height, on two lines."""
    if f"{prefix}_radius_min_in" in values:
        radius = f"R{_band(f'{prefix}_radius')}"
    else:
        radius = f"R{{{{cad.{prefix}_radius_ref_in:.3dot}}}} REF"
    low, high = values[f"{prefix}_height_band_mm"]
    if high > low:
        return [radius, f"{_band(f'{prefix}_height')} high"]
    return [radius, f"{{{{cad.{prefix}_height_in:.3dot}}}} high REF"]


def _slender(values: dict, length: float, width: float) -> tuple[float, float]:
    """Axial scale to fit ``width`` px, and a radial scale at least as large
    that draws the largest diameter at least 48 px."""
    largest = max(values[f"{n}_dia_mm"] / 2 for n in _diameters(values))
    scale = min(14.0, width / length)
    return scale, min(max(scale, 24.0 / largest), 70.0 / largest)


def _inspect(groups: Groups, values: dict, made: set) -> Layout:
    """The finished part, datum end at the left, its printed sizes."""
    length = _cad(values, "length_mm")
    scale, radial = _slender(values, length, 560.0)
    view = _View(80.0, 0.0, scale, radial)
    _title(groups, 20, 24, _TITLES["inspect"] + _exaggerated(scale, radial))
    top_profile = _meridian(values, made, flats=True)
    groups["part-kept"].append(_outline(view, top_profile, _meridian(values, made)))
    groups["centre-line"].append(
        _line(view.x(0) - 30, _AXIS, view.x(length) + 30, _AXIS)
    )
    largest = max(r for _, r in top_profile)
    top, bottom = view.up(largest), view.down(largest)
    groups["datum"].append(_line(view.x(0), top - 10, view.x(0), bottom + 10))
    _datum_label(groups, view.x(0) - 6, bottom + 24, "datum end", "end")
    # Seen across the flats' normal (drawn up): a hole along the line of
    # sight is a circle.
    flats = _names(values, "flat_", "_across_mm")
    sight = None
    if flats:
        axis = [float(c == values["axis"]) for c in "xyz"]
        up = values[f"{flats[0]}_normal"]
        sight = [
            axis[1] * up[2] - axis[2] * up[1],
            axis[2] * up[0] - axis[0] * up[2],
            axis[0] * up[1] - axis[1] * up[0],
        ]
    _holes(groups, values, view, sight)
    above, below = [], []
    for prefix, apex, inward in (("dome_datum", 0.0, 1), ("dome_far", length, -1)):
        if f"{prefix}_height_mm" in values:
            mid = apex + inward * values[f"{prefix}_height_mm"] / 3
            above.append(
                (
                    view.x(mid),
                    view.up(values[f"{prefix}_root_dia_mm"] / 4),
                    _dome_text(values, prefix),
                )
            )
    for f in flats:
        a, b = view.x(values[f"{f}_z0_mm"]), view.x(values[f"{f}_z1_mm"])
        dia = values[f"{values[f'{f}_on']}_dia_mm"]
        above.append(
            (
                (a + b) / 2,
                view.up(values[f"{f}_across_mm"] - dia / 2),
                [f"{f.removeprefix('flat_')}: {_band(f'{f}_across')} across"],
            )
        )
    for name in _diameters(values):
        a, b = view.x(values[f"{name}_z0_mm"]), view.x(values[f"{name}_z1_mm"])
        text = _size(values, name)
        below.append(((a + b) / 2, view.down(values[f"{name}_dia_mm"] / 2), text))
    for g in _names(values, "groove", "_width_mm"):
        a, b = view.x(values[f"{g}_z0_mm"]), view.x(values[f"{g}_z1_mm"])
        below.append(
            (
                (a + b) / 2,
                view.down(values[f"{g}_dia_mm"] / 2),
                [f"groove Ø{_band(f'{g}_dia')}"],
            )
        )
    for h in _names(values, "cross_hole", "_z_mm"):
        text = [f"Ø{{{{cad.{h}_dia_min_in:.4dot}}}}"]
        if values[f"{h}_made_at"] == "assembly":
            text.append("at assembly")
        below.append(
            (view.x(values[f"{h}_z_mm"]), view.down(values[f"{h}_dia_mm"] / 2), text)
        )
    if "thread_z0_mm" in values:
        a, b = view.x(values["thread_z0_mm"]), view.x(values["thread_z1_mm"])
        radius = values[f"{values['thread_on']}_dia_mm"] / 2
        depth = min(0.6 * values["thread_pitch_mm"], radius / 3)
        groups["part-threads"] += [
            _rect(a, view.up(radius), b - a, depth * radial),
            _rect(a, view.down(radius - depth), b - a, depth * radial),
        ]
        above.append(
            (
                (a + b) / 2,
                view.up(radius),
                ["{{cad.thread_designation}}", f"{_band('thread_length')} long"],
            )
        )
    _dimension(
        groups,
        view.x(0),
        view.x(length),
        top - 22,
        top - 2,
        f"length {_length_text(values)}",
    )
    head = _callouts(groups, above, top - 44, above=True) if above else 34
    if head < 34:
        raise CadError("turned-shaft: labels run off the top of the picture")
    return _finish(groups, _callouts(groups, below, bottom + 30, above=False))


def _size(values: dict, name: str) -> list[str]:
    if values.get(f"{name}_stock"):
        return [f"Ø{{{{cad.{name}_ref_in:.4dot}}}}", "as bought"]
    if values.get(f"{name}_as_supplied"):
        return [f"Ø{_band(f'{name}_dia', 4)}", "as supplied"]
    if f"{name}_dia_min_in" in values:
        return [f"Ø{_band(f'{name}_dia', 4)}"]
    return ["to its measured mate,", f"{_band(f'{name}_clearance', 4)} under"]


def _exaggerated(scale: float, radial: float) -> str:
    return f" (diameters ×{radial / scale:.1f})" if radial > scale * 1.05 else ""


def _holes(groups: Groups, values: dict, view: _View, normal: list | None) -> None:
    """Cross holes: a circle seen along its axis, else its edges through the
    part; dashed (hidden) when made at assembly."""
    for h in _names(values, "cross_hole", "_z_mm"):
        x = view.x(values[f"{h}_z_mm"])
        half = values[f"{h}_dia_mm"] / 2 * view.scale
        role = "hidden" if values[f"{h}_made_at"] == "assembly" else "holes"
        along = (
            normal is not None
            and abs(sum(a * b for a, b in zip(values[f"{h}_axis"], normal))) > 0.99
        )
        if along:
            groups[role].append(_el("circle", cx=x, cy=_AXIS, r=max(half, 2.0)))
        else:
            radius = values[f"{values_on(values, values[f'{h}_z_mm'])}_dia_mm"] / 2
            groups[role].append(
                _rect(
                    x - half,
                    view.up(radius),
                    max(2 * half, 2.0),
                    2 * radius * view.radial,
                )
            )


def values_on(values: dict, station: float) -> str:
    """The diameter at ``station``."""
    for name in _diameters(values):
        if values[f"{name}_z0_mm"] - 1e-6 <= station <= values[f"{name}_z1_mm"] + 1e-6:
            return name
    return _diameters(values)[0]


def _vise(groups: Groups, values: dict, parameters: dict, made: set, x0: str) -> Layout:
    """Top view in the vise, flats up; an end view of the hold at the right."""
    length = _cad(values, "length_mm")
    flats = _names(values, "flat_", "_across_mm")
    if not flats:
        raise CadError("turned-shaft: a vise hold mills the part's flats")
    normal = values[f"{flats[0]}_normal"]
    if any(values[f"{f}_normal"] != normal for f in flats):
        raise CadError("turned-shaft: the vise picture draws flats on one clock")
    # The jaws' sides from the X0 end, the end drawn at the left.
    jaw_from = float(parameters.get("vise_jaw_from_x0_mm", 0.0))
    jaw_width = _param(parameters, "vise_jaw_to_x0_mm") - jaw_from
    if jaw_width <= 0:
        raise CadError("turned-shaft: the vise jaws end before they start")
    left, right = min(0.0, jaw_from), max(length, jaw_from + jaw_width)
    scale, radial = _slender(values, right - left, 470.0)
    view = _View(60.0, left, scale, radial, length if x0 == "far" else None)

    def px(x: float) -> float:
        """X along the vise from the X0 end, in px."""
        return 60.0 + (x - left) * scale

    _title(groups, 20, 24, _TITLES["vise"] + _exaggerated(scale, radial))
    profile = _meridian(values, made)
    groups["part-kept"].append(_outline(view, profile))
    largest = max(r for _, r in profile)
    top, bottom = view.up(largest), view.down(largest)
    groups["centre-line"].append(_line(px(left) - 10, _AXIS, px(right) + 10, _AXIS))
    groups["clamp"] += [
        _rect(px(jaw_from), top - 14, jaw_width * scale, 14),
        _rect(px(jaw_from), bottom, jaw_width * scale, 14),
    ]
    above = [(px(jaw_from + jaw_width) - 30, top - 14, ["fixed jaw"])]
    below_y = bottom + 14
    for f in flats:
        a, b = sorted((view.x(values[f"{f}_z0_mm"]), view.x(values[f"{f}_z1_mm"])))
        half = values[f"{f}_width_mm"] / 2 * radial
        groups["part-removed"].append(_rect(a, _AXIS - half, b - a, 2 * half))
        groups["active-face"].append(_rect(a, _AXIS - half, b - a, 2 * half))
        above.append(
            (
                (a + b) / 2,
                _AXIS - half,
                [
                    f"flat {_band(f'{f}_across')} across,",
                    f"{_band(f'{f}_length')} long",
                ],
            )
        )
    _holes(groups, values, view, normal)
    end = view.x(0.0 if x0 == "datum" else length)
    groups["datum"].append(_line(end, top - 24, end, bottom + 24))
    _datum_label(groups, end + 4, top - 28, f"X0 {x0} end", "start")
    # The flats' stations, each from the end its drawing states.
    origins = {
        "datum_end": 0.0,
        "far_end": length,
        "datum_root": values.get("dome_datum_root_z_mm", 0.0),
        "far_root": values.get("dome_far_root_z_mm", length),
    }
    names = {
        "datum_end": "datum end",
        "far_end": "far end",
        "datum_root": "datum dome's root",
        "far_root": "far dome's root",
    }
    runs = []
    for f in flats:
        source = values[f"{f}_station_from"]
        origin = origins[source]
        z0, z1 = values[f"{f}_z0_mm"], values[f"{f}_z1_mm"]
        edge = z0 if origin < z0 else z1
        runs.append((abs(edge - origin), origin, edge, f, source))
    # Longest nearest the part, so no text crosses a longer one's witness.
    y = below_y + 22
    for _, origin, edge, f, source in sorted(runs, reverse=True):
        text = f"{_band(f'{f}_station')} from the {names[source]}"
        x0, x1 = sorted((view.x(origin), view.x(edge)))
        _dimension(groups, x0, x1, y, _AXIS, text, beside=x1 + 270 < 710)
        y += 24
    # End view: the part between the jaws on a parallel, the cutter above.
    cx, cy = 640.0, _AXIS
    r = 24.0
    f = flats[0]
    dia = values[f"{values[f'{f}_on']}_dia_mm"]
    k = r / (dia / 2)
    flat_y = cy - (values[f"{f}_across_mm"] - dia / 2) * k
    half = math.sqrt(max(r**2 - (cy - flat_y) ** 2, 0.0))
    groups["part-kept"].append(
        _el(
            "path",
            d=f"M{_pt(cx - half, flat_y)}A{r} {r} 0 1 0 {_pt(cx + half, flat_y)}Z",
        )
    )
    groups["part-removed"].append(
        _el(
            "path",
            d=f"M{_pt(cx - half, flat_y)}A{r} {r} 0 0 1 {_pt(cx + half, flat_y)}Z",
        )
    )
    groups["clamp"] += [
        _rect(cx - r - 16, cy - 4, 16, r + 30),
        _rect(cx + r, cy - 4, 16, r + 30),
    ]
    groups["fixture-support"].append(_rect(cx - r, cy + r, 2 * r, 22))
    groups["cutter"].append(_rect(cx - r * 0.75, flat_y - 46, 1.5 * r, 40))
    groups["label"].append(
        _el("text", "end view", x=cx, y=cy + r + 40, text_anchor="middle")
    )
    head = _callouts(groups, above, top - 40, above=True)
    if head < 34:
        raise CadError("turned-shaft: labels run off the top of the picture")
    return _finish(groups, max(y, cy + r + 50))


def _saw(groups: Groups, values: dict, parameters: dict) -> Layout:
    """The stock with the saw cut a blank's length from its end."""
    blank = _param(parameters, "blank_length_in") * 25.4
    stock = _param(parameters, "stock_dia_in") * 12.7
    kerf = (
        _param(parameters, "saw_kerf_in") * 25.4 if "saw_kerf_in" in parameters else 0.0
    )
    rest = 0.25 * blank
    scale = min(14.0, 520.0 / (blank + kerf + rest))
    radial = min(max(scale, 24.0 / stock), 70.0 / stock)
    view = _View(60.0, 0.0, scale, radial)
    _title(groups, 20, 24, _TITLES["saw"] + _exaggerated(scale, radial))
    top, bottom = view.up(stock), view.down(stock)
    end = view.x(blank + kerf + rest)
    groups["part-arriving"].append(_rect(view.x(0), top, end - view.x(0), bottom - top))
    groups["part-kept"].append(_rect(view.x(0), top, blank * scale, bottom - top))
    if kerf:
        groups["part-removed"].append(
            _rect(view.x(blank), top, kerf * scale, bottom - top)
        )
    groups["part-rest"].append(
        _el(
            "path",
            d=f"M{_pt(view.x(blank + kerf), top)}H{end:.2f}"
            f"{_break(end, top, bottom)}H{view.x(blank + kerf):.2f}Z",
        )
    )
    x = view.x(blank + kerf / 2)
    groups["cutter"].append(_rect(x - 3, top - 46, 6, 40))
    groups["centre-line"].append(_line(view.x(0) - 20, _AXIS, end + 20, _AXIS))
    _dimension(
        groups,
        view.x(0),
        view.x(blank),
        bottom + 30,
        bottom + 2,
        "blank {{process.blank_length_in:.3dot}}",
    )
    above = [
        (x, top - 46, ["saw"]),
        (view.x(0) + 30, top, ["bar Ø{{process.stock_dia_in:.4dot}}"]),
    ]
    head = _callouts(groups, above, top - 56, above=True)
    if head < 34:
        raise CadError("turned-shaft: labels run off the top of the picture")
    return _finish(groups, bottom + 50)


TURNED_SHAFT_LAYOUTS = {"turned-shaft": _layout}
