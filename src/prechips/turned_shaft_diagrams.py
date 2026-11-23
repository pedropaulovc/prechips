"""Turned-shaft pictures for the ``turned-shaft`` template.

One picture per setup, drawn from the ``turned_shaft`` adapter's values.
``data-hold`` names how the work is held:

- ``saw``: the round stock (``process.stock_dia_in``) with the saw cut at
  ``process.blank_length_in`` from its end, the blank dimensioned (a kerf
  ``process.saw_kerf_in`` drawn when stated);
- ``bar``: round bar in the chuck, ``process.parts_per_pull`` parts (one by
  default) out past the jaws, each a ``cad.pitch_mm`` along the bar; with
  ``process.centre_stub_in`` (inside ``process.face_allowance_in``, and
  ``face`` in ``data-work``), that much bar is kept beyond the out end's Z0
  as a stub, a tailstock dead centre in its centre hole;
- ``blank``: a sawn blank in the chuck, ``cad.end_stickout_mm`` out, the
  ``cad.face_stock_per_end_mm`` on its out end (``data-wrap="shim"`` on a
  bar or blank draws the jaws over a shim wrap);
- ``regrip``: the part turned round, the jaws on its ``data-grip`` diameter
  (``outer`` by default) over a shim wrap;
- ``vise``: a top view in the milling vise, the flats up, the ``data-x0`` end
  (``datum``, the default, or ``far``: the end the mill's X0 is set on) at the
  left, the jaws from ``process.vise_jaw_from_x0_mm`` to
  ``process.vise_jaw_to_x0_mm`` (the jaw sides' distances from that end, as a
  beam clamps), the flats' stations dimensioned from the ends their drawing
  states, and an end view of the hold: the jaw tops
  ``process.jaw_top_over_od_mm`` over the rod (the end view drops to keep
  them under the callouts), the rod on a ``process.parallel_thickness_mm``
  wide parallel when given;
- ``inspect``: the finished part with its printed sizes, its ``data-x0``
  end (``datum`` or ``far``: the end its lengths are read from) at the left,
  marked "<end> end" or ``data-end-label`` (the plan's own name for it).

``data-end-label`` names the one end a picture names, in the plan's words:
the inspection's x0 end, or a turned-round blank's out end in its caption.

Lathe holds are side elevations, chuck at the left, ``data-out`` (``datum``
or ``far``) the part's end toward the tailstock. ``data-work`` lists what the
setup does: ``face``, ``turn``, ``dome`` (the out end's), ``groove``,
``thread`` (a die from the tailstock, or a single-point bit for
``thread_process = "single_point"``), ``chamfer``, ``part`` (lathe holds)
and ``flat`` (the vise);
on an inspect hold, ``data-name-<flat>`` names a flat as the operations do
(default: the feature's suffix);
on a vise hold, ``data-flats`` names the flats this setup mills (default:
every flat) and ``data-flats-done`` the flats an earlier setup milled (drawn
as kept, unlabelled; any other flat is not drawn: its O.D. is uncut);
``steps`` labels the out end's dome with the adapter's stepped-turning table
(``process.dome_steps``);
``data-done`` what earlier setups made (``turn``, ``groove``, ``thread``,
``dome-datum``, ``dome-far``, ``face-datum``, ``face-far``). The vise and
the inspection assume every lathe feature this traveler makes made (a dome
made at assembly is not); on an inspection, ``data-done`` (when given, even
empty) is what the part leaves with: square ends where no dome is done, and
the faced length (both ends faced) or ``process.blank_length_in``. A feature
not yet made is drawn at the size it arrives at. A form-cut dome
(``process.dome_form_radius_in``) is labelled with the tool's R and its
height at the root (its range when formed per part on
``process.dome_form_dia_min_in``–``_max_in``; ``SR`` alone for a full
hemisphere) and the form tool is
drawn where ``dome`` is worked. Lathe pictures are to scale; the vise and inspection pictures are to
scale along the axis and draw diameters larger when the part is slender (the
title says so). Material arriving is dashed, material removed in the setup
hatched, the part solid; cross holes made at assembly are dashed on the
finished inspection and left out of the vise and an as-left inspection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from xml.etree import ElementTree

from prechips.bush_diagrams import _AXIS, _JAW, _SHIM, _chuck
from prechips.cad import CadError
from prechips.cad_diagrams import Element, Layout, _bound, _cad, _el, _line, _rect
from prechips.jig_diagrams import _datum_label, _finish, _groups, _param, _title
from prechips.shaft_diagrams import (
    CHAR,
    _break,
    _callouts,
    _clip,
    _dimension,
    _pt,
)

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


def _groove_dia(values: dict, groove: str) -> str:
    """A groove's printed Ø: its band, or its single MAX limit."""
    if f"{groove}_dia_max_mm" in values:
        return f"Ø{{{{cad.{groove}_dia_max_in:.3dot}}}} max"
    return f"Ø{_band(f'{groove}_dia')}"


def _chamfer_leg(values: dict, name: str) -> str:
    """A chamfer's leg: its band, or its single MAX limit."""
    if f"{name}_leg_min_in" in values:
        return _band(f"{name}_leg")
    return f"{{{{cad.{name}_leg_max_in:.3dot}}}} max"


def _names(values: dict, prefix: str, suffix: str) -> list[str]:
    return sorted(
        key.removesuffix(suffix)
        for key in values
        if key.startswith(prefix) and key.endswith(suffix)
    )


def _diameters(values: dict) -> list[str]:
    """The turned diameters (``outer``, ``step``, ``step_*``) by station."""
    family = {key.removesuffix("_z0_mm") for key in values if key.endswith("_z0_mm")}
    names = [n for n in ("outer", "step") if f"{n}_dia_mm" in values] + [
        name
        for name in family
        if name.startswith("step_") and f"{name}_dia_mm" in values
    ]
    return sorted(names, key=lambda name: values[f"{name}_z0_mm"])


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


def _cap(
    values: dict, prefix: str, apex: float, inward: int, *, form: bool = False
) -> Profile:
    """A dome's meridian from its apex to its root, as stations: the
    drawing's (whose root the diameters and stations meet), or with ``form``
    the form tool's."""
    kind = "_form" if form else ""
    radius = values[f"{prefix}{kind}_radius_mm"]
    height = values[f"{prefix}{kind}_height_mm"]
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
    # On an inspection, data-done (when given) is what the part leaves with.
    as_left = "data-done" in root.attrib
    done = set(root.attrib.pop("data-done", "").split())
    grip = root.attrib.pop("data-grip", "outer")
    x0 = root.attrib.pop("data-x0", "datum")
    names = {
        key.removeprefix("data-name-"): root.attrib.pop(key)
        for key in [k for k in root.attrib if k.startswith("data-name-")]
    }
    if names and hold != "inspect":
        raise CadError("turned-shaft: data-name-<flat> is on an inspect hold")
    if any(not name.strip() for name in names.values()):
        raise CadError("turned-shaft: a data-name-<flat> is non-blank text")
    milled = root.attrib.pop("data-flats", None)
    milled_before = set(root.attrib.pop("data-flats-done", "").split())
    if (milled is not None or milled_before) and hold != "vise":
        raise CadError(
            "turned-shaft: data-flats and data-flats-done are on a vise hold"
        )
    if x0 not in _OUTS or (x0 != "datum" and hold not in ("vise", "inspect")):
        raise CadError(
            "turned-shaft: data-x0 is datum or far, on a vise or inspect hold"
        )
    end_label = root.attrib.pop("data-end-label", None)
    if end_label is not None and (
        not end_label.strip() or not (hold == "inspect" or (hold == "blank" and done))
    ):
        raise CadError(
            "turned-shaft: data-end-label is a non-blank label, on inspect"
            " or a turned-round blank"
        )
    x0_label = end_label or f"{x0} end"
    wrap = root.attrib.pop("data-wrap", "none")
    if wrap not in ("none", "shim") or (
        wrap == "shim" and hold not in ("bar", "blank")
    ):
        raise CadError(
            "turned-shaft: data-wrap is none or shim, on a bar or blank hold"
        )
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
        # Everything this traveler makes; a dome made at assembly is not.
        made = {"turn", "groove", "thread", "face-datum", "face-far"} | {
            f"dome-{end}"
            for end in _OUTS
            if values.get(f"dome_{end}_made_at", "traveler") != "assembly"
        }
        if hold == "vise":
            return _vise(
                groups,
                values,
                parameters,
                made,
                x0,
                None if milled is None else milled.split(),
                milled_before,
            )
        return _inspect(
            groups,
            values,
            parameters,
            done if as_left else made,
            as_left,
            x0,
            x0_label,
            names,
        )
    title = _TITLES[hold]
    if hold == "blank" and done:
        named = end_label or f"{out} end"
        title = f"Turned round, the {named} out, seen from the operator's side"
    _title(groups, 20, 24, title)
    made = done | (work & {"turn", "groove", "thread"})
    if "dome" in work:
        made.add(f"dome-{out}")
    return _lathe(groups, values, parameters, hold, out, work, made, grip, wrap)


def _lathe(
    groups: Groups,
    values: dict,
    parameters: dict,
    hold: str,
    out: str,
    work: set,
    made: set,
    grip: str,
    wrap: str,
) -> Layout:
    length = _cad(values, "length_mm")
    names = _diameters(values)

    def z_of(station: float) -> float:
        """Station into the part as lathe Z: Z0 the out end, Z+ out."""
        return -station if out == "datum" else station - length

    stock = values.get("stock_dia_mm", 0.0) / 2
    count, pitch, face, kerf, regrip, stub = 1, length, 0.0, 0.0, 0.0, 0.0
    if hold == "bar":
        count = int(parameters.get("parts_per_pull", 1))
        pitch = _cad(values, "pitch_mm")
        regrip = float(values.get("regrip_allowance_mm", 0.0))
        face = _param(parameters, "face_allowance_in") * 25.4 if "face" in work else 0.0
        kerf = _param(parameters, "part_kerf_in") * 25.4
        jaw = float(values.get("jaw_z_mm", -(count * pitch)))
        if "centre_stub_in" in parameters:
            # Bar kept beyond Z0 for the tailstock centre, inside the facing.
            stub = _param(parameters, "centre_stub_in") * 25.4
            if "face" not in work:
                raise CadError("turned-shaft: a centre stub needs face in data-work")
            if stub >= face - 1e-9:
                raise CadError(
                    "turned-shaft: process.centre_stub_in must lie inside"
                    " process.face_allowance_in"
                )
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
        if f"regrip_stickout_{out}_mm" in values:
            # The jaws stand the part this far out, the diameter running on
            # through them into the chuck.
            key = f"{grip}_regrip_jaw_z_{out}_mm"
            if key not in values:
                raise CadError(
                    f"turned-shaft: the regrip's jaw fronts are not on {grip!r}"
                )
            jaw = float(values[key])
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
        shim = _SHIM if wrap == "shim" else 0.0
        if shim:
            bar = bar.replace("jaws on", "jaws over a shim wrap on")
        _chuck(groups, view, view.x(zmin), view.x(jaw), stock, shim)
        above.append((view.x(zmin) + 4, y0 - shim - _JAW, ["3-jaw chuck,", bar]))
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
            _rect(
                view.x(stub), view.up(radius), (face - stub) * scale, 2 * radius * scale
            )
        )
    if stub:
        # Cut off with the part when this setup parts it.
        fill = "part-removed" if "part" in work else "part-kept"
        groups[fill].append(
            _rect(view.x(0), view.up(stock), stub * scale, 2 * stock * scale)
        )
        # The dead centre's 60° point in the stub's centre hole, its quill
        # beyond the faced end.
        x = view.x(stub) - 4
        groups["fixture-vise"].append(
            _el(
                "path",
                d=f"M{_pt(x, _AXIS)}L{_pt(x + 10, _AXIS - 6)}H{x + 44:.2f}"
                f"V{_AXIS + 6:.2f}H{x + 10:.2f}Z",
            )
        )
        below.append((x + 30, _AXIS + 6, ["dead centre"]))
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
    _labels(values, view, work, z_of, out, above, below, to_length, stub=stub)
    if work & {"face", "turn", "dome", "groove", "chamfer"}:
        # The turning tool, beside the out end, clear of the labels.
        x = view.x(face) + 4
        groups["cutter"].append(
            _el("path", d=f"M{x:.2f} {bottom + 6:.2f}l18 5v28h-18z")
        )
    prefix = f"dome_{out}"
    if "dome" in work and f"{prefix}_form_radius_mm" in values:
        # The form tool, its concave face standing off the dome it cuts.
        apex = 0.0 if out == "datum" else length
        cap = _cap(values, prefix, apex, 1 if out == "datum" else -1, form=True)
        gap = face * scale + 8
        top_side = [(view.x(z_of(s)) + gap, view.up(r)) for s, r in reversed(cap)]
        bottom_side = [(view.x(z_of(s)) + gap, view.down(r)) for s, r in cap]
        back = max(x for x, _ in top_side) + 24
        corners = [(back, bottom_side[-1][1]), (back, top_side[0][1])]
        points = top_side + bottom_side + corners
        groups["cutter"].append(
            _el("path", d="M" + "L".join(_pt(*p) for p in points) + "Z")
        )
        # Its label's leader ends on the tool body, just under its top edge.
        text = _dome_text(values, prefix)
        if "steps" in work:
            text.append("step-turn {{process.dome_steps:d}} steps, file")
        above.append((back - 12, top_side[0][1] + 4, text))
    if "part" in work:
        line = -length - float(values.get("regrip_allowance_mm", 0.0))
        x = view.x(line - kerf)
        groups["cutter"].append(_rect(x, bottom + 4, kerf * scale, 40))
        below.append(
            (x + kerf * scale / 2, bottom + 44, ["parting blade:", "part off"])
        )
    if "thread" in work and "thread_z0_mm" in values:
        radius = values[f"{values['thread_on']}_dia_mm"] / 2
        lines = ["{{cad.thread_designation}}", f"{_band('thread_length', 3)} long"]
        if values["thread_process"] == "single_point":
            # A 60° threading bit on the thread's top, from the cross slide.
            a = view.x(z_of(values["thread_z0_mm"]))
            b = view.x(z_of(values["thread_z1_mm"]))
            x, y = (a + b) / 2, view.up(radius)
            groups["cutter"].append(
                _el(
                    "path",
                    d=f"M{_pt(x, y)}L{_pt(x + 7, y - 12)}V{y - 40:.2f}"
                    f"H{x - 7:.2f}V{y - 12:.2f}Z",
                )
            )
            above.append((x, y - 40, ["single-point threading bit:", *lines]))
        else:
            x = view.x(face) + 40
            groups["cutter"] += [
                _rect(x, view.up(radius) - 16, 14, 16),
                _rect(x, view.down(radius), 14, 16),
            ]
            groups["fixture-vise"].append(_rect(x + 14, _AXIS - 12, 40, 24))
            above.append(
                (x + 7, view.up(radius) - 16, ["die from the tailstock:", *lines])
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
    stub: float = 0.0,
) -> None:
    length = values["length_mm"]
    if "face" in work:
        # With a centre stub the faced end stands the stub beyond Z0.
        text = (
            ["face the bar end", "for the stub"] if stub else ["face the end", "to Z0"]
        )
        if to_length:
            band = (
                _band("faced_length")
                if "faced_length_min_in" in values
                else _length_text(values)
            )
            text = ["face to length", band]
        below.append(
            (view.x(stub) + 1, view.down(values.get("stock_dia_mm", 0) / 2 or 1), text)
        )
    if "turn" in work:
        for name in _diameters(values):
            if values.get(f"{name}_stock") or values.get(f"{name}_as_supplied"):
                continue
            a = view.x(z_of(values[f"{name}_z0_mm"]))
            b = view.x(z_of(values[f"{name}_z1_mm"]))
            mid = (max(min(a, b), view.x0) + max(a, b)) / 2
            text = (
                [f"turn Ø{_band(f'{name}_dia', 4)}"]
                if f"{name}_dia_min_in" in values
                else ["turn to the measured mate,", *_size(values, name)[1:]]
            )
            if values.get("thread_on") == name:
                text.append("thread blank")
            above.append((mid, view.up(values[f"{name}_dia_mm"] / 2), text))
    prefix = f"dome_{out}"
    # A form-cut dome is labelled on its tool (drawn by _lathe).
    formed = f"{prefix}_form_radius_mm" in values
    if "dome" in work and f"{prefix}_height_mm" in values and not formed:
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
                    [f"groove {_groove_dia(values, g)}", f"{_band(f'{g}_width')} wide"],
                )
            )
    if "chamfer" in work:
        chamfers = _names(values, "chamfer_", "_leg_mm")
        if chamfers:
            below.append(
                (
                    view.x(0) - 4,
                    view.down(values.get("stock_dia_mm", 2) / 2),
                    [
                        "break edges:",
                        *(f"{_chamfer_leg(values, c)} × 45°" for c in chamfers),
                    ],
                )
            )


def _length_text(values: dict) -> str:
    """The length band, or ``(.82) REF`` when the drawing gives a REF."""
    if "length_min_in" in values:
        return _band("length")
    return "({{cad.length_ref_in:.2dot}}) REF"


def _left_length(values: dict, parameters: dict, made: set) -> str:
    """The length the part leaves at: the drawing's once its domes are made;
    before, the faced length when both ends are faced, else the blank's."""
    domed = [end for end in ("datum", "far") if f"dome_{end}_height_mm" in values]
    if all(f"dome-{end}" in made for end in domed):
        return _length_text(values)
    if {"face-datum", "face-far"} <= made and "faced_length_min_in" in values:
        return _band("faced_length")
    if "blank_length_in" not in parameters:
        raise CadError(
            "turned-shaft: a part leaving before its domes needs both ends "
            "faced or process.blank_length_in"
        )
    return "{{process.blank_length_in:.3dot}}"


def _dome_text(values: dict, prefix: str) -> list[str]:
    """A dome's radius and its height at the root: the form tool's when
    form-cut (the range over the part's diameter when the plan forms it per
    part), ``SR`` alone for a full hemisphere."""
    if f"{prefix}_form_height_min_in" in values:
        # Formed per part: no one height (nor a hemisphere on every part).
        return [
            f"R{{{{cad.{prefix}_form_radius_in:.3dot}}}} form,",
            (
                f"{{{{cad.{prefix}_form_height_min_in:.4dot}}}}–"
                f"{{{{cad.{prefix}_form_height_max_in:.4dot}}}} high"
            ),
            "at the root,",
            "by the turned Ø",
        ]
    if f"{prefix}_form_radius_in" in values:
        if (
            abs(
                values[f"{prefix}_form_radius_mm"] - values[f"{prefix}_root_dia_mm"] / 2
            )
            < 1e-3
        ):
            return [f"SR{{{{cad.{prefix}_form_radius_in:.3dot}}}} form"]
        return [
            f"R{{{{cad.{prefix}_form_radius_in:.3dot}}}} form,",
            f"{{{{cad.{prefix}_form_height_in:.4dot}}}} high",
            "at the root",
        ]
    if f"{prefix}_radius_min_in" in values:
        radius = f"R{_band(f'{prefix}_radius')},"
    else:
        radius = f"R{{{{cad.{prefix}_radius_ref_in:.3dot}}}} REF,"
    low, high = values[f"{prefix}_height_band_mm"]
    if high > low:
        least, most = (values[f"{prefix}_height_{e}_in"] for e in ("min", "max"))
        if abs(most - least) < 1e-9:
            # Rounded inward to one .001 in reading.
            text = f"{{{{cad.{prefix}_height_min_in:.3dot}}}}"
        elif abs(least * 1000 - round(least * 1000)) > 1e-6:
            # Too narrow for a .001 in reading: its exact limits.
            text = _band(f"{prefix}_height", 4)
        else:
            text = _band(f"{prefix}_height")
        return [radius, f"{text} high", "at the root"]
    return [radius, f"{{{{cad.{prefix}_height_in:.3dot}}}} high", "at the root REF"]


def _flat_name(names: dict, flat: str) -> str:
    """A flat's name on the finished part: its ``data-name-<flat>`` when the
    picture names it (as the operations do), else the feature's own suffix."""
    return names.get(flat, flat.removeprefix("flat_"))


def _slender(values: dict, length: float, width: float) -> tuple[float, float]:
    """Axial scale to fit ``width`` px, and a radial scale at least as large
    that draws the largest diameter at least 48 px."""
    largest = max(values[f"{n}_dia_mm"] / 2 for n in _diameters(values))
    scale = min(14.0, width / length)
    return scale, min(max(scale, 24.0 / largest), 70.0 / largest)


def _inspect(
    groups: Groups,
    values: dict,
    parameters: dict,
    made: set,
    as_left: bool,
    x0: str,
    x0_label: str,
    names: dict | None = None,
) -> Layout:
    """The part as it leaves, its ``data-x0`` end (the end lengths are read
    from) at the left, marked ``x0_label``, its printed sizes: the finished
    part unless data-done says what this traveler made."""
    names = names or {}
    unknown = set(names) - set(_names(values, "flat_", "_across_mm"))
    if unknown:
        raise CadError(f"turned-shaft: data-name-{min(unknown)} names no flat")
    length = _cad(values, "length_mm")
    scale, radial = _slender(values, length, 560.0)
    view = _View(80.0, 0.0, scale, radial, length if x0 == "far" else None)
    title = "Part as it leaves, seen from the side" if as_left else _TITLES["inspect"]
    _title(groups, 20, 24, title + _exaggerated(scale, radial))
    top_profile = _meridian(values, made, flats=True)
    groups["part-kept"].append(_outline(view, top_profile, _meridian(values, made)))
    # The x0 end at the left, the other at the right.
    left, right = sorted((view.x(0.0), view.x(length)))
    groups["centre-line"].append(_line(left - 30, _AXIS, right + 30, _AXIS))
    largest = max(r for _, r in top_profile)
    top, bottom = view.up(largest), view.down(largest)
    groups["datum"].append(_line(left, top - 10, left, bottom + 10))
    if len(_bound(x0_label)) * CHAR > left - 6:
        raise CadError("turned-shaft: data-end-label runs off the picture")
    _datum_label(groups, left - 6, bottom + 24, x0_label, "end")
    # Seen across the flats' normal (drawn up): a hole along the line of
    # sight is a circle.
    flats = _names(values, "flat_", "_across_mm")
    if any(values[f"{f}_normal"] != values[f"{flats[0]}_normal"] for f in flats):
        raise CadError("turned-shaft: the inspect picture draws flats on one clock")
    sight = None
    if flats:
        axis = [float(c == values["axis"]) for c in "xyz"]
        up = values[f"{flats[0]}_normal"]
        sight = [
            axis[1] * up[2] - axis[2] * up[1],
            axis[2] * up[0] - axis[0] * up[2],
            axis[0] * up[1] - axis[1] * up[0],
        ]
    _holes(groups, values, view, sight, assembly=not as_left)
    above, below = [], []
    for prefix, apex, inward in (("dome_datum", 0.0, 1), ("dome_far", length, -1)):
        if f"{prefix}_height_mm" in values and f"dome-{prefix[5:]}" in made:
            mid = apex + inward * values[f"{prefix}_height_mm"] / 3
            above.append(
                (
                    view.x(mid),
                    view.up(values[f"{prefix}_root_dia_mm"] / 4),
                    _dome_text(values, prefix),
                )
            )
    for f in flats:
        a, b = sorted((view.x(values[f"{f}_z0_mm"]), view.x(values[f"{f}_z1_mm"])))
        dia = values[f"{values[f'{f}_on']}_dia_mm"]
        above.append(
            (
                (a + b) / 2,
                view.up(values[f"{f}_across_mm"] - dia / 2),
                [f"{_flat_name(names, f)}: {_band(f'{f}_across')} across"],
            )
        )
    holes = [
        h
        for h in _names(values, "cross_hole", "_z_mm")
        if not (as_left and values[f"{h}_made_at"] == "assembly")
    ]
    # A diameter's leader lands on its outline clear of every hole through
    # it: at its middle when that is clear, else the middle of the longest
    # clear stretch (the middle again when no stretch is clear).
    spans = [
        (view.x(values[f"{h}_z_mm"]), values[f"{h}_dia_mm"] / 2 * scale + 6)
        for h in holes
    ]
    for name in _diameters(values):
        a, b = sorted(
            (view.x(values[f"{name}_z0_mm"]), view.x(values[f"{name}_z1_mm"]))
        )
        clear = [(a, b)]
        for hx, reach in spans:
            clear = [
                (lo, hi)
                for start, end in clear
                for lo, hi in (
                    (start, min(end, hx - reach)),
                    (max(start, hx + reach), end),
                )
                if hi > lo
            ]
        x = (a + b) / 2
        if clear and not any(lo <= x <= hi for lo, hi in clear):
            lo, hi = max(clear, key=lambda s: s[1] - s[0])
            x = (lo + hi) / 2
        text = _size(values, name)
        below.append((x, view.down(values[f"{name}_dia_mm"] / 2), text))
    for g in _names(values, "groove", "_width_mm"):
        a, b = view.x(values[f"{g}_z0_mm"]), view.x(values[f"{g}_z1_mm"])
        below.append(
            (
                (a + b) / 2,
                view.down(values[f"{g}_dia_mm"] / 2),
                [f"groove {_groove_dia(values, g)}"],
            )
        )
    for h in holes:
        text = [f"Ø{{{{cad.{h}_dia_min_in:.4dot}}}}"]
        if values[f"{h}_made_at"] == "assembly":
            text.append("at assembly")
        below.append(
            (view.x(values[f"{h}_z_mm"]), view.down(values[f"{h}_dia_mm"] / 2), text)
        )
    if "thread_z0_mm" in values and "thread" in made:
        a, b = sorted((view.x(values["thread_z0_mm"]), view.x(values["thread_z1_mm"])))
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
        left,
        right,
        top - 22,
        top - 2,
        f"length {_left_length(values, parameters, made)}",
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
    if f"{name}_interference_min_in" in values:
        return ["to its measured mate,", f"{_band(f'{name}_interference', 4)} over"]
    return ["to its measured mate,", f"{_band(f'{name}_clearance', 4)} under"]


def _exaggerated(scale: float, radial: float) -> str:
    return f" (diameters ×{radial / scale:.1f})" if radial > scale * 1.05 else ""


def _holes(
    groups: Groups, values: dict, view: _View, normal: list | None, *, assembly: bool
) -> None:
    """Cross holes: a circle seen along its axis, else its edges through the
    part; those made at assembly dashed (hidden), or left out when
    ``assembly`` is false (the part as it leaves this traveler)."""
    for h in _names(values, "cross_hole", "_z_mm"):
        if not assembly and values[f"{h}_made_at"] == "assembly":
            continue
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


def _vise(
    groups: Groups,
    values: dict,
    parameters: dict,
    made: set,
    x0: str,
    milled: list | None = None,
    milled_before: set | None = None,
) -> Layout:
    """Top view in the vise, flats up; an end view of the hold at the right.
    ``milled`` the flats this setup cuts (default every flat),
    ``milled_before`` those an earlier setup cut."""
    length = _cad(values, "length_mm")
    every = _names(values, "flat_", "_across_mm")
    if not every:
        raise CadError("turned-shaft: a vise hold mills the part's flats")
    normal = values[f"{every[0]}_normal"]
    if any(values[f"{f}_normal"] != normal for f in every):
        raise CadError("turned-shaft: the vise picture draws flats on one clock")
    flats = every if milled is None else milled
    before = set(milled_before or ())
    unknown = (set(flats) | before) - set(every)
    if unknown or not flats or before & set(flats):
        raise CadError(
            "turned-shaft: data-flats names the part's flats this setup mills, "
            "data-flats-done others an earlier setup milled"
        )
    # The jaws' sides from the X0 end, the end drawn at the left.
    jaw_from = float(parameters.get("vise_jaw_from_x0_mm", 0.0))
    jaw_width = _param(parameters, "vise_jaw_to_x0_mm") - jaw_from
    if jaw_width <= 0:
        raise CadError("turned-shaft: the vise jaws end before they start")
    left, right = min(0.0, jaw_from), max(length, jaw_from + jaw_width)
    scale, radial = _slender(values, right - left, 470.0)
    view = _View(100.0, left, scale, radial, length if x0 == "far" else None)

    def px(x: float) -> float:
        """X along the vise from the X0 end, in px."""
        return 100.0 + (x - left) * scale

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
    for f in sorted(before):
        a, b = sorted((view.x(values[f"{f}_z0_mm"]), view.x(values[f"{f}_z1_mm"])))
        half = values[f"{f}_width_mm"] / 2 * radial
        groups["part-kept"].append(_rect(a, _AXIS - half, b - a, 2 * half))
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
    _holes(groups, values, view, normal, assembly=False)
    end = view.x(0.0 if x0 == "datum" else length)
    groups["datum"].append(_line(end, top - 24, end, bottom + 24))
    # Left of its line, clear of the flats' leaders.
    _datum_label(groups, end - 4, top - 28, f"X0 {x0} end", "end")
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
        # The point the loader checked the station to (an end, or the centre).
        edge = values[f"{f}_station_point_mm"]
        centre = values.get(f"{f}_station_to") == "centre"
        runs.append((abs(edge - origin), origin, edge, f, source, centre))
    # End view: the part between the jaws on a parallel, the cutter above.
    # It sits low enough that its jaw tops stay under the top view's
    # callouts.
    r = 24.0
    f = flats[0]
    dia = values[f"{values[f'{f}_on']}_dia_mm"]
    k = r / (dia / 2)
    over = 4.0 - r
    if "jaw_top_over_od_mm" in parameters:
        over = _param(parameters, "jaw_top_over_od_mm") * k
    cx, cy = 640.0, max(_AXIS, top - 10 + r + over)
    # Longest nearest the part, so no text crosses a longer one's witness:
    # a shorter run's witnesses reach down past every row above its own.
    rows = sorted(runs, reverse=True)
    y = below_y + 22
    for row, (_, origin, edge, flat, source, centre) in enumerate(rows):
        text = f"{_band(f'{flat}_station')} from the {names[source]}"
        left_x, right_x = sorted((view.x(origin), view.x(edge)))
        if not centre:
            _dimension(
                groups, left_x, right_x, y, _AXIS, text, beside=right_x + 270 < 710
            )
            y += 24
            continue
        text += " to its centre"
        width = len(_bound(text)) * CHAR
        mid = (left_x + right_x) / 2
        start = left_x - 6 - width
        # The witnesses of the rows below this one.
        below = [view.x(z) for _, o, e, *_ in rows[row + 1 :] for z in (o, e)]

        # A row level with the end view ends short of its jaws, any other row
        # short of the page's right margin; a label with no room on its row
        # moves below the end view, where it runs to the margin. Beside the
        # line, centred over it, or ending short of it when no lower row's
        # witness crosses there; else above it, kept on the page.
        placed = None
        for row_y in (y, max(y, cy + r + 62)):
            level = cy - r - over - 10 < row_y + 5 and row_y - 12 < cy + r + 50
            limit = cx - r - 22 if level else 710.0
            if right_x + 6 + width <= limit:
                placed = (True, False, None)
            elif 10 <= mid - width / 2 and mid + width / 2 <= limit:
                placed = (False, False, None)
            elif start >= 10 and not any(start <= x <= left_x - 1 for x in below):
                placed = (False, True, None)
            if placed is not None:
                break
        if placed is None:
            if width > limit - 10:
                raise CadError(
                    f"turned-shaft: no room on the vise picture for {flat}'s station"
                )
            placed = (False, False, max(10.0, min(mid - width / 2, limit - width)))
        y = row_y
        beside, before, at = placed
        _dimension(
            groups,
            left_x,
            right_x,
            y,
            _AXIS,
            text,
            beside=beside,
            before=before,
            start=at,
        )
        y += 24
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
    # The jaw tops stand process.jaw_top_over_od_mm over the rod's top when
    # given (the rod on a parallel), else a little over its centre; the
    # parallel is process.parallel_thickness_mm wide when given.
    jaw_top = cy - r - over
    groups["clamp"] += [
        _rect(cx - r - 16, jaw_top, 16, cy + r + 26 - jaw_top),
        _rect(cx + r, jaw_top, 16, cy + r + 26 - jaw_top),
    ]
    width = 2 * r
    if "parallel_thickness_mm" in parameters:
        width = min(_param(parameters, "parallel_thickness_mm") * k, 2 * r)
    groups["fixture-support"].append(_rect(cx - width / 2, cy + r, width, 22))
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
