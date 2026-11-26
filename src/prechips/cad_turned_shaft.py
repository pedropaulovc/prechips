"""Bindings for a turned shaft or pin: a long shaft left at its ground rod's
size, or a short pin turned from bar, with domed ends, set-screw flats, an
external thread, relief grooves and cross holes.

The features and stations are ``turned_bush``'s (see its module): every
station is a distance from the ``datum_end`` into the part, and ``outer`` and
``step`` take the same three acceptances. Added here:

- either end may be ``kind = "dome"``, its ``plane`` the apex: a ``radius``
  band (or ``radius_ref``) and at most one of a ``height`` band,
  ``height_ref`` or a ``root_station`` band from the datum end, optionally
  ``made_at = "assembly"``. The diameters then run from one dome's root to
  the other's, and the cap must fit the diameter it domes;
- ``far_end`` takes a ``length`` band or ``length_ref``, and optionally a
  ``body_length`` band or ``body_length_ref`` (root to root) and a
  ``supply_length`` band (made uncut, cut to fit at assembly);
- a diameter may carry an external ``thread`` (at most one);
- ``groove``/``groove_*``, ``cross_hole``/``cross_hole_*``, ``flat_*`` and
  ``fillet_*``;
- further diameters ``step_*`` (a head, a land), each with ``outer``'s
  acceptances, plus a press fit's ``dia_ref`` turned over its measured
  ``mate`` for a ``diametral_interference`` (``mate_dia`` its mate's printed
  limits); a fit may name several running ``mates``.

Flats, cross holes, grooves and ``far_end.station`` are stationed from
``datum_end``, ``far_end``, a domed end's root (``datum_root``,
``far_root``) or a ``shoulder`` with an ``outward`` normal (its stations run
that way); a flat's station runs to its nearer end, or with ``station_to =
"centre"`` to its centre; a groove's to its nearer wall, or with
``station_to = "far_wall"`` to its farther. The ``shoulder`` itself may be
stationed from a domed end's root, and a diameter may print a ``length``
from one of those origins (``length_from``) that it runs from. A domed end
may be cut by its own form tool (``dome_datum_form_radius_in`` /
``dome_far_form_radius_in`` and their ``_form_dia_min_in``/``_max_in``) in
place of the shared ``dome_form_*``; the radius is equally the one a radius
(ball) turner is set to, which sweeps the same sphere about a pivot on the
axis (``_form_sweep_deg``, the angle off the axis where its tip leaves the
corner), and ``_form_chamfer_max`` is the longest 45° chamfer leg on the
square corner that stays outside that sphere (``dome_chamfer_in``, a
roughing chamfer, is held under it). The plan binds either the bar-fed
cycle (turned_bush's round bar) or a sawn blank of round stock.
"""

import math
import re
from fractions import Fraction
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _all_or_none,
    _edge_breaks,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
)
from .cad_turned_bush import (
    _AXES,
    _BAR,
    _BAR_LENGTH,
    _PULL,
    _TOLERANCE,
    _as_supplied,
    _bar,
    _bar_size,
    _chamfer,
    _count,
    _diameter,
    _frame,
    _lathe_z,
    _limits,
    _nominal,
    _rough_sizes,
    _shoulder,
    _span,
    _station,
    _tap,
)

_DIAMETERS = ("outer", "step")
_DOMES = {"datum_end": "dome_datum", "far_end": "dome_far"}
_FAMILIES = ("chamfer_", "groove", "cross_hole", "flat_", "fillet_", "step_")
# A groove's station runs to its wall nearer the origin, or the farther.
_GROOVE_WALLS = ("near_wall", "far_wall")
_BLANK = ("stock_dia_in", "blank_length_in")
# Model coordinates against printed nominals and cap geometry, mm.
_STATION = 1e-3
# ASME B1.1 external inch threads: #N-TPI or a/b-TPI (or N-TPI), UNC, UNF or
# UNEF, an optional class 1A-3A.
_THREAD = re.compile(
    r"(#\d+|[1-9]\d*/[1-9]\d*|[1-9]\d*)-([1-9]\d*) UN(?:C|F|EF)(?:-[123]A)?"
)


def _point(item: dict, name: str, frame: tuple) -> float:
    """The station of ``at``, a point on the turning axis."""
    at = item.get("at")
    if not isinstance(at, list) or len(at) != 3:
        raise CadError(f"{name}.at: expected a point on the turning axis")
    if any(_number(v, f"{name}.at") != 0 for i, v in enumerate(at) if i != frame[0]):
        raise CadError(f"{name}.at: expected a point on the turning axis")
    return _station(frame, _number(at[frame[0]], f"{name}.at"))


def _radial(item: dict, key: str, name: str, frame: tuple) -> list[float]:
    """A unit vector square to the turning axis."""
    vector = item.get(key)
    if not isinstance(vector, list) or len(vector) != 3:
        raise CadError(f"{name}.{key}: expected a radial unit vector")
    vector = [_number(v, f"{name}.{key}") for v in vector]
    if abs(vector[frame[0]]) > _TOLERANCE or abs(math.hypot(*vector) - 1) > 1e-6:
        raise CadError(f"{name}.{key}: expected a radial unit vector")
    return vector


def _inside(z: float, values: dict, name: str) -> None:
    if not 0 < z < values["length_mm"]:
        raise CadError(f"{name}.at: not inside the part")


def _least(values: dict, name: str) -> float:
    """The smallest a diameter is made."""
    return values.get(f"{name}_turn_min_mm", values[f"{name}_dia_mm"])


def _length(far: dict, frame: tuple, values: dict) -> None:
    plane = far.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") != _AXES[frame[0]]:
        raise CadError("far_end.plane: expected a plane on the datum end's axis")
    if far.get("length_from") != "datum_end":
        raise CadError("far_end.length_from: expected datum_end")
    station = _station(frame, _number(plane.get("value"), "far_end.plane.value"))
    requirements = far.get("requirements", [])
    if "length" in requirements:
        band = _limits(far, "length", "far_end", "length", values)
        nominal = _nominal(far, "length_nominal", band, "far_end")
    else:
        nominal = _positive(far.get("length_ref"), "far_end.length_ref")
        values["length_ref_in"] = nominal / 25.4
    if abs(station - nominal) > _TOLERANCE:
        raise CadError("far_end.plane: not the nominal length from the datum end")
    values["length_mm"] = nominal
    values["length_nominal_in"] = nominal / 25.4
    if "supply_length" in requirements:
        # Cut to fit at assembly, it can only be shortened: every supply
        # length must reach the part's longest.
        longest = values.get("length_band_mm", [nominal, nominal])[1]
        band = _limits(far, "supply_length", "far_end", "supply_length", values)
        supply = _nominal(far, "supply_length_nominal", band, "far_end")
        if band[0] < longest - _TOLERANCE:
            raise CadError("far_end.supply_length: shorter than the part it is cut to")
        values["supply_length_mm"] = supply


def _basic_major(thread: object) -> float:
    """An inch thread's basic major diameter in mm; 0 for none or another form
    (``_thread`` refuses those)."""
    match = _THREAD.fullmatch(thread) if isinstance(thread, str) else None
    if match is None:
        return 0.0
    size = match[1]
    if size.startswith("#"):
        return (0.060 + 0.013 * int(size[1:])) * 25.4
    return float(Fraction(size)) * 25.4


def _inward_limits(
    values: dict, key: str, band: tuple[float, float], *, strict: bool = False
) -> None:
    """Bind a band the adapter derives: ``_band_mm`` exact (what checks
    read), ``_min_in``/``_max_in`` rounded inward to .001 in (min up, max
    down) so a .3dot print never reads outside it. A band too narrow to hold
    a .001 in reading is refused when ``strict``, else its limits stay exact
    (print them at .4dot)."""
    _inch_limits(values, key, band)
    low = math.ceil(band[0] / 25.4 * 1000 - 1e-6) / 1000
    high = math.floor(band[1] / 25.4 * 1000 + 1e-6) / 1000
    if low <= high:
        values[f"{key}_min_in"], values[f"{key}_max_in"] = low, high
    elif strict:
        raise CadError(f"cad.{key}: the band holds no .001 in reading")


def _cap(radius: float, root: float) -> float:
    """A spherical cap's height on a diameter of radius ``root``."""
    return radius - math.sqrt(max(radius**2 - root**2, 0.0))


def _dome(
    item: dict, end: str, values: dict, root: float, roots: tuple[float, float]
) -> None:
    """Bind a domed end; ``root`` is the nominal radius of the diameter it
    domes and ``roots`` the least and greatest it may be."""
    prefix = _DOMES[end]
    requirements = item.get("requirements", [])
    band = None
    if "radius" in requirements:
        band = _limits(item, "radius", end, f"{prefix}_radius", values)
        radius = _nominal(item, "radius_nominal", band, end)
    else:
        radius = _positive(item.get("radius_ref"), f"{end}.radius_ref")
        values[f"{prefix}_radius_ref_in"] = radius / 25.4
    values[f"{prefix}_radius_mm"] = radius
    if radius < roots[0] - _TOLERANCE:
        raise CadError(
            f"{end}.radius: R{radius:.3f} is under the least R{roots[0]:.3f} it domes"
        )
    root = min(root, radius)
    cap = _cap(radius, root)
    given = [key for key in ("height", "root_station") if key in requirements] + (
        ["height_ref"] if "height_ref" in item else []
    )
    if len(given) > 1:
        raise CadError(f"{end}: expected one of height, height_ref or root_station")
    length = values["length_mm"]
    if "height" in given:
        heights = _limits(item, "height", end, f"{prefix}_height", values)
        height = _nominal(item, "height_nominal", heights, end)
    elif "height_ref" in given:
        height = _positive(item["height_ref"], f"{end}.height_ref")
        values[f"{prefix}_height_ref_in"] = height / 25.4
    elif "root_station" in given:
        stations = _limits(item, "root_station", end, f"{prefix}_root_station", values)
        station = _nominal(item, "root_station_nominal", stations, end)
        height = station if end == "datum_end" else length - station
    else:
        height = cap
    if band is not None and given == [] and band[0] < root - _TOLERANCE:
        raise CadError(
            f"{end}.radius: the least R{band[0]:.3f} is under the R{root:.3f} it domes"
        )
    # A shop checks a radius by the height it gives on the diameter: the
    # radius band's caps, unless a root station sets the height (a far
    # root station over a REF length sets none a shop can measure).
    caps = band is not None and (
        given == []
        or given == ["root_station"]
        and end == "far_end"
        and "length_band_mm" not in values
    )
    if caps:
        _inward_limits(
            values,
            f"{prefix}_height",
            # Under the root an R's cap is R itself (a full hemisphere).
            (_cap(band[1], min(root, band[1])), _cap(band[0], min(root, band[0]))),
        )
    # The declared height must be a cap of R somewhere on the diameter's range.
    least, most = (_cap(radius, min(r, radius)) for r in roots)
    if not least - _STATION <= height <= most + _STATION:
        raise CadError(
            f"{end}: height {height:.4f} is off the R{radius:.4f} cap's "
            f"{least:.4f}-{most:.4f} on Ø{2 * roots[0]:.4f}-{2 * roots[1]:.4f}"
        )
    values[f"{prefix}_height_mm"] = height
    # Every height source binds its nominal and limits in inches: a band, a
    # root-station band, a radius band's heights, or the REF or cap alone.
    if f"{prefix}_height_band_mm" not in values and "root_station" in given:
        _inward_limits(
            values,
            f"{prefix}_height",
            stations
            if end == "datum_end"
            else (length - stations[1], length - stations[0]),
        )
    elif f"{prefix}_height_band_mm" not in values:
        values[f"{prefix}_height_band_mm"] = [height, height]
        values[f"{prefix}_height_min_in"] = values[f"{prefix}_height_max_in"] = (
            height / 25.4
        )
    values[f"{prefix}_height_in"] = height / 25.4
    values[f"{prefix}_root_dia_mm"] = 2 * root
    inward = 1 if end == "datum_end" else -1
    apex = 0.0 if end == "datum_end" else length
    values[f"{prefix}_apex_z_mm"] = apex
    values[f"{prefix}_root_z_mm"] = apex + inward * height
    # The root in the lathe's Z frame with this end out (Z0 the faced end).
    values[f"{prefix}_root_out_z_mm"] = -height
    values[f"{prefix}_centre_z_mm"] = apex + inward * radius
    made_at = item.get("made_at")
    if made_at not in (None, "assembly"):
        raise CadError(f"{end}.made_at: expected assembly")
    values[f"{prefix}_made_at"] = made_at or "traveler"


def _form_keys(parameters: dict, prefix: str) -> tuple[str | None, tuple[str, str]]:
    """The plan keys of the form tool that cuts ``prefix``'s dome: its own
    ``<prefix>_form_radius_in`` (with its own ``_form_dia_min_in``/``_max_in``),
    else the shared ``dome_form_radius_in`` (and ``dome_form_dia_*``); the
    radius key is None when neither is given."""
    own = f"{prefix}_form_radius_in"
    if own in parameters and "dome_form_radius_in" in parameters:
        raise CadError(
            f"process.{own}: name one form radius, not dome_form_radius_in too"
        )
    own_dias = (f"{prefix}_form_dia_min_in", f"{prefix}_form_dia_max_in")
    if any(key in parameters for key in own_dias):
        return (own if own in parameters else "dome_form_radius_in"), own_dias
    radius = own if own in parameters else "dome_form_radius_in"
    shared = ("dome_form_dia_min_in", "dome_form_dia_max_in")
    return (radius if radius in parameters else None), shared


def _form(
    values: dict,
    parameters: dict,
    prefix: str,
    root: float,
    roots: tuple[float, float],
) -> None:
    """``dome_form_radius_in``: the dome cut by a form tool of that radius,
    full to the centre on the end's diameter at nominal (radius ``root``); its
    height is the cap the tool leaves there. With ``dome_form_dia_min_in`` and
    ``_max_in`` the tool cuts full on each part's own diameter, anywhere in
    that band (holding the nominal, within ``roots``, the least and greatest
    the diameter may be; every form-cut end shares it), so the height goes by
    the part: ``_form_height_min_*``/``_max_*`` are the caps at the band's
    ends. An end's own ``<prefix>_form_*`` keys take the shared keys' place
    (``_form_keys``). A dome made at assembly is not this traveler's to cut."""
    if values[f"{prefix}_made_at"] == "assembly":
        return
    key, keys = _form_keys(parameters, prefix)
    if key is None or key not in parameters:
        raise CadError(f"process.{keys[0]}: binds only with a form radius")
    form = _positive(parameters[key], f"process.{key}")
    radius = form * 25.4
    per_part = _all_or_none(parameters, keys, "the dome form diameter band")
    if per_part:
        least, most = (
            _positive(parameters[k], f"process.{k}") * 25.4 / 2 for k in keys
        )
        if not (
            roots[0] - _TOLERANCE <= least <= root + _TOLERANCE
            and root - _TOLERANCE <= most <= roots[1] + _TOLERANCE
        ):
            raise CadError(
                f"process.{keys[0]}/_max_in: Ø{2 * least / 25.4:.4f}–"
                f"Ø{2 * most / 25.4:.4f} must hold the nominal "
                f"Ø{2 * root / 25.4:.4f} inside the Ø{2 * roots[0] / 25.4:.4f}–"
                f"Ø{2 * roots[1] / 25.4:.4f} it domes"
            )
        sizes = (least, most)
    else:
        sizes = (root, root)
    if radius < sizes[1] - _TOLERANCE:
        raise CadError(
            f"process.{key}: R{form:.4f} is under the "
            f"Ø{2 * sizes[1] / 25.4:.4f} it domes"
        )
    # The nominal's cap lies between the band ends' (a cap grows with Ø).
    height = _cap(radius, min(root, radius))
    caps = [_cap(radius, min(s, radius)) for s in sizes]
    low, high = values[f"{prefix}_height_band_mm"]
    for cap in caps:
        if low < high and not low - _STATION <= cap <= high + _STATION:
            raise CadError(
                f"process.{key}: its {cap / 25.4:.4f} high {prefix} "
                "is outside the drawing's height band"
            )
    values[f"{prefix}_form_radius_mm"] = radius
    values[f"{prefix}_form_radius_in"] = form
    values[f"{prefix}_form_height_mm"] = height
    values[f"{prefix}_form_height_in"] = height / 25.4
    if per_part:
        for end, cap in zip(("min", "max"), caps, strict=True):
            values[f"{prefix}_form_height_{end}_mm"] = cap
            values[f"{prefix}_form_height_{end}_in"] = cap / 25.4
    # The diameters this end may arrive at: the plan's per-part band when it
    # forms each part on its own diameter, else the diameter's printed range.
    least, most = sizes if per_part else roots
    most = min(most, radius)
    # A radius (ball) turner cuts the same sphere, its tip swung about a pivot
    # on the axis one radius behind the apex: from the apex until the tip
    # leaves the end's corner, asin(r / R) off the axis (90° on a tangent
    # hemisphere), taken on the largest diameter so no ring is left unswept.
    values[f"{prefix}_form_sweep_deg"] = math.degrees(math.asin(most / radius))
    # The longest leg of a 45° chamfer on the end's square corner (a leg along
    # each face) that stays outside the sphere, so roughing it off ahead of
    # the form never cuts the dome: the chamfer's line first meets the sphere
    # where the sphere slopes 45°, R/√2 off the axis, while that lies on the
    # cap (leg r + R − √2·R), else at the root (leg = the cap's height). Both
    # grow with r, so it is taken on the least diameter.
    least = min(least, radius)
    leg = (
        least + radius - math.sqrt(2) * radius
        if radius / math.sqrt(2) <= least
        else _cap(radius, least)
    )
    values[f"{prefix}_form_chamfer_max_mm"] = leg
    values[f"{prefix}_form_chamfer_max_in"] = leg / 25.4


def _dome_chamfer(values: dict, parameters: dict) -> None:
    """``dome_chamfer_in``: the leg of the 45° chamfer a plan roughs each
    formed dome's corner off with; it must stay outside every formed dome's
    sphere (``_form_chamfer_max``)."""
    leg = _positive(parameters["dome_chamfer_in"], "process.dome_chamfer_in")
    formed = [p for p in _DOMES.values() if f"{p}_form_chamfer_max_in" in values]
    if not formed:
        raise CadError(
            "process.dome_chamfer_in: binds only on a dome this traveler forms"
        )
    for prefix in formed:
        most = values[f"{prefix}_form_chamfer_max_in"]
        if leg > most + _TOLERANCE:
            raise CadError(
                f"process.dome_chamfer_in: a {leg:.4f} leg cuts into the "
                f"{prefix} sphere (at most {most:.4f})"
            )


def _steps(values: dict, parameters: dict) -> None:
    """``dome_steps`` = N: a stepped-turning table per dome.

    The dome's height is cut into N + 1 equal Z steps; step k (1 next to the
    root) is turned from the apex back to its shoulder, ``_z_`` back from the
    apex, at the cap's diameter there. Each shoulder's corner lies on the
    sphere, so stepping never cuts inside it; the file removes the steps.
    """
    count = _count(parameters, "dome_steps")
    if count < 2:
        raise CadError("process.dome_steps: expected 2 or more")
    for prefix in _DOMES.values():
        if f"{prefix}_height_mm" not in values:
            continue
        height, radius = values[f"{prefix}_height_mm"], values[f"{prefix}_radius_mm"]
        for k in range(1, count + 1):
            z = height * (count + 1 - k) / (count + 1)
            dia = 2 * math.sqrt(z * (2 * radius - z))
            key = f"{prefix}_step_{k}"
            values[f"{key}_dia_mm"], values[f"{key}_dia_in"] = dia, dia / 25.4
            values[f"{key}_z_mm"], values[f"{key}_z_in"] = z, z / 25.4
            # The shoulder in the lathe's Z frame, Z0 the apex, Z+ out.
            values[f"{key}_end_z_mm"] = -z


def _tiles(values: dict, names: list[str], start: float, end: float) -> None:
    """The diameters run end to end from the datum root to the far root."""
    spans = sorted((values[f"{n}_z0_mm"], values[f"{n}_z1_mm"], n) for n in names)
    reach = start
    for low, high, name in spans:
        if abs(low - reach) > _STATION:
            raise CadError(
                f"{name}.span: the diameters must run end to end from root to root"
            )
        reach = high
    if abs(reach - end) > _STATION:
        raise CadError("cad.features: the diameters stop short of the far root")


def _body(far: dict, values: dict) -> None:
    """The body between the dome roots, checked against the length."""
    body = values["length_mm"] - sum(
        values.get(f"{prefix}_height_mm", 0.0) for prefix in _DOMES.values()
    )
    if "body_length" in far.get("requirements", []):
        band = _limits(far, "body_length", "far_end", "body_length", values)
        nominal = _nominal(far, "body_length_nominal", band, "far_end")
    elif "body_length_ref" in far:
        nominal = _positive(far["body_length_ref"], "far_end.body_length_ref")
        values["body_length_ref_in"] = nominal / 25.4
    else:
        return
    if abs(nominal - body) > _STATION:
        raise CadError(
            f"far_end.body_length: {nominal:.4f} is not the length less the dome "
            f"heights, {body:.4f}"
        )
    values["body_length_mm"] = nominal


def _faced(values: dict) -> None:
    """The length a domed part is faced flat to before its domes are formed
    (each apex stays on its faced plane): the made length band (the supply
    length for a part cut at assembly, else the length) within the body
    length band plus the dome heights at nominal, else the far dome's root
    station band (from the datum end, so it holds a datum dome already) plus
    its height: a form-cut dome's tool height, or over a radius band the
    window that keeps the root in its band for any R in it (the least
    station plus the tallest cap, the greatest plus the shallowest). A dome
    formed per part narrows the window the same way: its tallest cap on the
    low end, its shallowest on the high."""

    def cut(prefix: str, end: str = "") -> float:
        return values.get(
            f"{prefix}_form_height{end}_mm",
            values.get(
                f"{prefix}_form_height_mm", values.get(f"{prefix}_height_mm", 0.0)
            ),
        )

    heights = sum(cut(p) for p in _DOMES.values())
    tallest = sum(cut(p, "_max") for p in _DOMES.values())
    shallowest = sum(cut(p, "_min") for p in _DOMES.values())
    key = "supply_length" if "supply_length_band_mm" in values else "length"
    bands = []
    nominal = values[f"{key}_mm"]
    if "body_length_band_mm" in values and key == "length":
        body_low, body_high = values["body_length_band_mm"]
        bands.append([body_low + tallest, body_high + shallowest])
        nominal = values["body_length_mm"] + heights
    if f"{key}_band_mm" in values:
        bands.append(values[f"{key}_band_mm"])
    elif "dome_far_root_station_band_mm" in values:
        height = cut("dome_far")
        least, most = values["dome_far_root_station_band_mm"]
        tall, short = cut("dome_far", "_max"), cut("dome_far", "_min")
        if "dome_far_form_height_mm" not in values and (
            "dome_far_radius_band_mm" in values
        ):
            root = values["dome_far_root_dia_mm"] / 2
            radii = values["dome_far_radius_band_mm"]
            short, tall = (_cap(r, min(root, r)) for r in reversed(radii))
        nominal = values["dome_far_root_z_mm"] + height
        if not least + tall - _STATION <= nominal <= most + short + _STATION:
            raise CadError(
                "far_end: the radius band's caps leave no faced length that "
                "keeps the dome's root inside its root_station band"
            )
        bands.append([least + tall, most + short])
    if not bands:
        return
    low, high = max(b[0] for b in bands), min(b[1] for b in bands)
    if not low - _STATION <= nominal <= high + _STATION:
        raise CadError(
            f"far_end: no faced length within both the {key} and body bands at "
            f"{nominal:.4f}"
        )
    _inward_limits(values, "faced_length", (low, high), strict=True)
    # The nominal to .001 in, inside the printed band.
    low_in, high_in = values["faced_length_min_in"], values["faced_length_max_in"]
    nominal_in = min(max(round(nominal / 25.4, 3), low_in), high_in)
    values["faced_length_mm"] = nominal_in * 25.4
    values["faced_length_in"] = nominal_in


def _thread(item: dict, name: str, values: dict, start: float, end: float) -> None:
    """An external thread cut on diameter ``name`` from one end."""
    designation = _string(item.get("thread"), f"{name}.thread")
    match = _THREAD.fullmatch(designation)
    if match is None:
        raise CadError(
            f"{name}.thread: expected an external inch thread, #N-TPI or "
            "a/b-TPI UNC, UNF or UNEF"
        )
    # The major limits are the diameter's: a dia band, or a stock size as
    # bought; never derived from the designation.
    if f"{name}_dia_band_mm" not in values and not values[f"{name}_stock"]:
        raise CadError(f"{name}: a thread is cut on a dia band or a stock size")
    tpi = int(match[2])
    band = _limits(item, "thread_length", name, "thread_length", values)
    length = _nominal(item, "thread_length_nominal", band, name)
    side = item.get("thread_end")
    if side not in _DOMES:
        raise CadError(f"{name}.thread_end: expected datum_end or far_end")
    process = item.get("thread_process")
    if process not in ("die", "single_point"):
        raise CadError(f"{name}.thread_process: expected die or single_point")
    z0, z1 = values[f"{name}_z0_mm"], values[f"{name}_z1_mm"]
    near = z0 if side == "datum_end" else z1
    if abs(near - (start if side == "datum_end" else end)) > _STATION:
        raise CadError(f"{name}.thread_end: the diameter does not run to that end")
    # At nominal: a print may thread the whole cylinder with a band either side.
    if length > z1 - z0 + _STATION:
        raise CadError(
            f"{name}.thread_length: {length:.3f} mm runs past the diameter's "
            f"{z1 - z0:.3f} mm span"
        )
    values.update(
        thread_designation=designation,
        thread_tpi=tpi,
        thread_pitch_mm=25.4 / tpi,
        thread_process=process,
        thread_on=name,
        thread_end=side,
        thread_length_mm=length,
    )
    values["thread_z0_mm"], values["thread_z1_mm"] = (
        (z0, z0 + length) if side == "datum_end" else (z1 - length, z1)
    )
    if "thread_incomplete_max" in item:
        most = _positive(item["thread_incomplete_max"], f"{name}.thread_incomplete_max")
        values["thread_incomplete_max_mm"] = most
        values["thread_incomplete_max_in"] = most / 25.4


def _shoulder_from(item: dict, frame: tuple, values: dict) -> None:
    """turned_bush's shoulder, or one stationed from the far end or a domed
    end's root; either way ``shoulder_mm`` is its station from the datum end.
    Its ``outward`` normal, when given, is the way stations from it run
    (``shoulder_outward``, +1 toward the far end)."""
    source = item.get("station_from")
    values["shoulder_station_from"] = source
    outward = item.get("outward")
    if outward is not None:
        expected = [[float(i == frame[0]) * sign for i in range(3)] for sign in (1, -1)]
        if outward not in expected:
            raise CadError("shoulder.outward: expected a unit normal along the axis")
        values["shoulder_outward"] = int(outward[frame[0]] * frame[2])
    if source not in ("far_end", "datum_root", "far_root"):
        _shoulder(item, frame, values)
        return
    if item.get("kind") != "face":
        raise CadError("shoulder: expected a face")
    band = _limits(item, "station", "shoulder", "shoulder", values)
    nominal = _nominal(item, "station_nominal", band, "shoulder")
    plane = item.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") != _AXES[frame[0]]:
        raise CadError("shoulder.plane: expected a plane on the datum end's axis")
    station = _station(frame, _number(plane.get("value"), "shoulder.plane.value"))
    length = values["length_mm"]
    if source != "far_end":
        origin, inward = _origin(item, "shoulder", values)
        if abs((station - origin) * inward - nominal) > _STATION:
            raise CadError(f"shoulder.plane: not the nominal station from {source}")
        if not 0 < station < length:
            raise CadError("shoulder.plane: not inside the part")
        # The band's far limit, from that root, inside the shortest part.
        reach = origin + inward * band[1]
        if not 0 < reach < values.get("length_band_mm", [length])[0]:
            raise CadError(f"shoulder.station: reaches past the part from {source}")
        values["shoulder_mm"] = station
        return
    if abs(length - station - nominal) > _TOLERANCE:
        raise CadError("shoulder.plane: not the nominal station from the far end")
    if band[1] >= values.get("length_band_mm", [length])[0]:
        raise CadError("shoulder.station: reaches the datum end of the shortest part")
    values["shoulder_mm"] = station


def _origin(
    item: dict, name: str, values: dict, key: str = "station_from"
) -> tuple[float, int]:
    """Where ``key`` (``station_from`` or ``length_from``) lies along the part
    and which way is inward."""
    source = item.get(key)
    origins = {"datum_end": (0.0, 1), "far_end": (values["length_mm"], -1)}
    if "dome_datum_root_z_mm" in values:
        origins["datum_root"] = (values["dome_datum_root_z_mm"], 1)
    if "dome_far_root_z_mm" in values:
        origins["far_root"] = (values["dome_far_root_z_mm"], -1)
    if "shoulder_mm" in values and "shoulder_outward" in values and name != "shoulder":
        origins["shoulder"] = (values["shoulder_mm"], values["shoulder_outward"])
    if source not in origins:
        raise CadError(f"{name}.{key}: expected one of {', '.join(origins)}")
    values[f"{name}_{key}"] = source
    return origins[source]


def _run_length(item: dict, name: str, values: dict) -> None:
    """A diameter's printed ``length`` band, from ``length_from``, which it
    runs from: one end on that origin, the other its nominal length on."""
    if "length" not in item.get("requirements", []):
        return
    band = _limits(item, "length", name, f"{name}_length", values)
    nominal = _nominal(item, "length_nominal", band, name)
    origin, inward = _origin(item, name, values, "length_from")
    z0, z1 = values[f"{name}_z0_mm"], values[f"{name}_z1_mm"]
    near, far = (z0, z1) if inward > 0 else (z1, z0)
    if abs(near - origin) > _STATION:
        raise CadError(f"{name}.span: does not run from {item['length_from']}")
    if abs(abs(far - origin) - nominal) > _STATION:
        raise CadError(f"{name}.span: not its nominal length")
    values[f"{name}_length_mm"] = nominal


def _located(item: dict, name: str, values: dict, edge: tuple[float, float]) -> float:
    """Bind a ``station`` band from ``station_from``, checked against the model:
    ``edge`` is the feature's nearer and farther station from the datum end
    (one point for a feature stationed to its centre). Returns the point it
    locates, from the datum end."""
    band = _limits(item, "station", name, f"{name}_station", values)
    nominal = _nominal(item, "station_nominal", band, name)
    origin, inward = _origin(item, name, values)
    station = (edge[0] - origin) if inward > 0 else (origin - edge[1])
    if abs(station - nominal) > _STATION:
        raise CadError(
            f"{name}: {station:.4f} from {item['station_from']} in the model, "
            f"not its nominal station {nominal:.4f}"
        )
    values[f"{name}_station_mm"] = nominal
    return edge[0] if inward > 0 else edge[1]


def _groove(item: dict, name: str, frame: tuple, values: dict, turned: list) -> None:
    if item.get("kind") != "groove":
        raise CadError(f"{name}: expected a model-frame groove")
    z0, z1 = _span(item, name, frame, values)
    requirements = item.get("requirements", [])
    if ("dia" in requirements) == ("dia_max" in requirements):
        raise CadError(f"{name}: expected one of a dia band or a dia_max limit")
    if "dia" in requirements:
        band = _limits(item, "dia", name, f"{name}_dia", values)
        values[f"{name}_dia_mm"] = _nominal(item, "dia_nominal", band, name)
        # The least size it is cut to, to screen a hold's stickout by.
        values[f"{name}_dia_min_mm"] = band[0]
        most = band[1]
    else:
        # A single MAX limit: any floor under it is accepted, so no least
        # size is bound; the nominal may not exceed it.
        most = _positive(item.get("dia_max"), f"{name}.dia_max")
        values[f"{name}_dia_max_mm"], values[f"{name}_dia_max_in"] = most, most / 25.4
        nominal = _positive(item.get("dia_nominal"), f"{name}.dia_nominal")
        if nominal > most + _TOLERANCE:
            raise CadError(f"{name}.dia_nominal: over its dia_max")
        values[f"{name}_dia_mm"] = nominal
    widths = _limits(item, "width", name, f"{name}_width", values)
    width = _nominal(item, "width_nominal", widths, name)
    values[f"{name}_width_mm"] = width
    if abs(z1 - z0 - width) > _STATION:
        raise CadError(f"{name}.span: not its nominal width")
    if "station" in requirements:
        to = item.get("station_to", "near_wall")
        if to not in _GROOVE_WALLS:
            raise CadError(f'{name}.station_to: expected "near_wall" or "far_wall"')
        values[f"{name}_station_to"] = to
        # _located takes (nearer, farther) from the datum end and uses the
        # one nearer its origin: swapped, it locates the wall farther off.
        edge = (z0, z1) if to == "near_wall" else (z1, z0)
        values[f"{name}_station_wall_mm"] = _located(item, name, values, edge)
    cut = [
        d
        for d in turned
        if values[f"{d}_z0_mm"] < z1 - _TOLERANCE
        and values[f"{d}_z1_mm"] > z0 + _TOLERANCE
    ]
    if not cut:
        raise CadError(f"{name}.span: cuts into no diameter")
    least = min(_least(values, d) for d in cut)
    if most >= least:
        raise CadError(f"{name}.dia: not under the Ø{least:.3f} diameter it cuts into")
    if "corner_radius_max" in item:
        corner = _positive(item["corner_radius_max"], f"{name}.corner_radius_max")
        values[f"{name}_corner_r_max_in"] = corner / 25.4
    # The groove's run in the lathe's Z frame with either end out.
    _lathe_z(values, name)


def _cross_hole(
    item: dict, name: str, frame: tuple, values: dict, turned: list
) -> None:
    if item.get("kind") != "hole":
        raise CadError(f"{name}: expected a model-frame hole")
    if item.get("thru") is not True:
        raise CadError(f"{name}.thru: expected a through hole")
    values[f"{name}_axis"] = _radial(item, "axis", name, frame)
    z = _point(item, name, frame)
    _inside(z, values, name)
    values[f"{name}_z_mm"] = z
    band = _limits(item, "dia", name, f"{name}_dia", values)
    values[f"{name}_dia_mm"] = _nominal(item, "nominal_dia", band, name)
    crossed = [
        d
        for d in turned
        if values[f"{d}_z0_mm"] - _TOLERANCE <= z <= values[f"{d}_z1_mm"] + _TOLERANCE
    ]
    if not crossed:
        raise CadError(f"{name}.at: not on a diameter")
    least = min(_least(values, d) for d in crossed)
    if band[1] >= least:
        raise CadError(f"{name}.dia: not under the Ø{least:.3f} diameter it crosses")
    made_at = item.get("made_at")
    if made_at == "assembly":
        if "process" in item:
            raise CadError(f"{name}.process: a hole made at assembly takes none")
    elif made_at is None:
        if item.get("process") not in ("drill", "ream"):
            raise CadError(f"{name}.process: expected drill or ream")
        values[f"{name}_process"] = item["process"]
    else:
        raise CadError(f"{name}.made_at: expected assembly")
    values[f"{name}_made_at"] = made_at or "traveler"
    # An assembly hole's mate may set its station: the print need give none.
    if made_at != "assembly" or "station" in item.get("requirements", []):
        _located(item, name, values, (z, z))
    if "callout" in item:
        values[f"{name}_callout"] = _string(item["callout"], f"{name}.callout")


def _flat(
    item: dict, name: str, frame: tuple, values: dict, turned: list, parameters: dict
) -> None:
    if item.get("kind") != "flat":
        raise CadError(f"{name}: expected a model-frame flat")
    values[f"{name}_normal"] = _radial(item, "normal", name, frame)
    z0, z1 = _span(item, name, frame, values)
    on = [
        d
        for d in turned
        if values[f"{d}_z0_mm"] - _TOLERANCE <= z0
        and z1 <= values[f"{d}_z1_mm"] + _TOLERANCE
    ]
    if not on:
        raise CadError(f"{name}.span: not on one diameter")
    dia = on[0]
    if _press_ref(values, dia):
        raise CadError(f"{name}.span: on {dia}, a REF turned to its mate")
    nominal_dia = values.get(f"{dia}_nominal_mm", values[f"{dia}_dia_mm"])
    low, high = values.get(f"{dia}_dia_band_mm", [values[f"{dia}_dia_mm"]] * 2)
    across = _limits(item, "across", name, f"{name}_across", values)
    nominal = _nominal(item, "across_nominal", across, name)
    values[f"{name}_across_mm"] = nominal
    if across[1] >= low:
        raise CadError(f"{name}.across: does not cut into the Ø{low:.3f} {dia}")
    # Worst cases: the smallest diameter under the widest across, and back.
    _inch_limits(values, f"{name}_depth", (low - across[1], high - across[0]))
    values[f"{name}_depth_mm"] = nominal_dia - nominal
    radius = nominal_dia / 2
    width = 2 * math.sqrt(radius**2 - (nominal - radius) ** 2)
    values[f"{name}_width_mm"] = width
    lengths = _limits(item, "length", name, f"{name}_length", values)
    length = _nominal(item, "length_nominal", lengths, name)
    values[f"{name}_length_mm"] = length
    if abs(z1 - z0 - length) > _STATION:
        raise CadError(f"{name}.span: not its nominal length")
    to = item.get("station_to", "near")
    if to not in ("near", "centre"):
        raise CadError(f'{name}.station_to: expected "near" or "centre"')
    values[f"{name}_station_to"] = to
    middle = (z0 + z1) / 2
    # The point the station locates, from the datum end: the vise picture
    # dimensions to it.
    values[f"{name}_station_point_mm"] = _located(
        item, name, values, (middle, middle) if to == "centre" else (z0, z1)
    )
    whole = values["length_mm"]
    values[f"{name}_from_datum_mm"] = [z0, z1]
    values[f"{name}_from_far_mm"] = [whole - z1, whole - z0]
    values[f"{name}_on"] = dia
    if "flat_cutter_dia_mm" in parameters:
        # An end mill's face sweeps the flat in one pass: its centre runs a
        # cutter radius inside each end.
        cutter = _positive(
            parameters["flat_cutter_dia_mm"], "process.flat_cutter_dia_mm"
        )
        if cutter > length + _STATION:
            raise CadError(f"{name}: shorter than process.flat_cutter_dia_mm")
        # The flat is widest on the largest diameter cut to the least across.
        most = high / 2
        widest = 2 * math.sqrt(most**2 - (across[0] - most) ** 2)
        if cutter < widest:
            raise CadError(f"{name}: wider than process.flat_cutter_dia_mm")
        path = [z0 + cutter / 2, z1 - cutter / 2]
        values[f"{name}_path_mm"] = path
        values[f"{name}_path_z0_mm"], values[f"{name}_path_z1_mm"] = path


def _fillet(item: dict, name: str, frame: tuple, values: dict, turned: list) -> None:
    if item.get("kind") != "fillet":
        raise CadError(f"{name}: expected a model-frame fillet")
    z = _point(item, name, frame)
    # A step: one diameter ends where another starts, within the tiling's tolerance.
    steps = [
        values[f"{a}_z1_mm"]
        for a in turned
        for b in turned
        if abs(values[f"{a}_z1_mm"] - values[f"{b}_z0_mm"]) <= _STATION
    ]
    if not any(abs(z - step) <= _STATION for step in steps):
        raise CadError(f"{name}.at: not at a step between two diameters")
    values[f"{name}_z_mm"] = z
    if "station" in item.get("requirements", []):
        _located(item, name, values, (z, z))
    if "radius" in item.get("requirements", []):
        band = _limits(item, "radius", name, f"{name}_radius", values)
        values[f"{name}_radius_mm"] = _nominal(item, "radius_nominal", band, name)
    else:
        most = _positive(item.get("radius_max"), f"{name}.radius_max")
        values[f"{name}_radius_max_mm"] = most
        values[f"{name}_radius_max_in"] = most / 25.4


def _press_ref(values: dict, name: str) -> bool:
    """A REF turned over its measured mate for a press (no dia band)."""
    return (
        f"{name}_interference_band_mm" in values and f"{name}_dia_band_mm" not in values
    )


def _turned(item: dict, name: str, frame: tuple, values: dict) -> float:
    """turned_bush's diameter, a press REF turned over its measured mate
    included; a threaded one's model may sit at the thread's
    basic major above its class 2A band, so its nominal is either inside the
    band or that major (the band's middle is then the turned size). A fit may
    name its mates (``mates``, bound joined as ``<name>_mates``) and its
    mate's printed limits (``mate_dia``), from which a REF fit's least
    turned size and least bar follow (``_mate_sizes``)."""
    fitted = {"diametral_clearance", "diametral_interference"} & set(
        item.get("requirements", [])
    )
    if "mates" in item:
        if "mate" in item:
            raise CadError(f"{name}: names its mate or its mates, not both")
        if not fitted:
            raise CadError(f"{name}.mates: binds only with a fit")
        mates = item["mates"]
        if not isinstance(mates, list) or not mates:
            raise CadError(f"{name}.mates: expected a list of drawing numbers")
        joined = ", ".join(_string(mate, f"{name}.mates") for mate in mates)
        values[f"{name}_mates"] = joined
        item = {"mate": joined} | item
    if "mate_dia" in item:
        if not fitted:
            raise CadError(f"{name}.mate_dia: binds only with a fit")
        limits = item["mate_dia"]
        if not isinstance(limits, list) or len(limits) != 2:
            raise CadError(f"{name}.mate_dia: expected the mate's two limits")
        low, high = (_positive(v, f"{name}.mate_dia") for v in limits)
        if low > high:
            raise CadError(f"{name}.mate_dia: reversed limits")
        _inch_limits(values, f"{name}_mate_dia", (low, high))
    band = item.get("dia")
    nominal = item.get("dia_nominal")
    if "thread" not in item or not isinstance(band, list) or len(band) != 2:
        least = _diameter(item, name, frame, values, press_ref=True)
        return _mate_sizes(values, name, least)
    low, high = (_number(v, f"{name}.dia") for v in band)
    given = _positive(nominal, f"{name}.dia_nominal")
    if (
        not low <= given <= high
        and abs(given - _basic_major(item["thread"])) > _STATION
    ):
        raise CadError(
            f"{name}.dia_nominal: neither in its band nor the thread's major"
        )
    inside = min(max(given, low), high)
    least = _diameter(item | {"dia_nominal": inside}, name, frame, values)
    values[f"{name}_nominal_mm"] = given
    return least


def _mate_sizes(values: dict, name: str, least: float) -> float:
    """A REF fit with its mate's printed limits: turned_bush screens it at the
    mate's REF; here its least turned size is the least mate with the least
    interference (or less the most clearance), and a press's bar must reach
    the greatest mate with the most interference."""
    if f"{name}_mate_dia_band_mm" not in values or f"{name}_dia_band_mm" in values:
        return least
    low, high = values[f"{name}_mate_dia_band_mm"]
    if f"{name}_interference_band_mm" in values:
        fit = values[f"{name}_interference_band_mm"]
        values[f"{name}_turn_min_mm"] = low + fit[0]
        return max(least, high + fit[1])
    values[f"{name}_turn_min_mm"] = low - values[f"{name}_clearance_band_mm"][1]
    return least


_REGRIP_OUT = {"datum": "regrip_stickout_datum_in", "far": "regrip_stickout_far_in"}


def _regrip_stickout(values: dict, parameters: dict, turned: list) -> None:
    """``regrip_stickout_datum_in`` / ``_far_in``: a regrip with that end out
    standing the part that far out of the jaw fronts (the regrip allowance on
    the out end included), the gripped diameter running on through the jaws
    into the chuck, so a long part may be held near either end. Rebinds
    ``<name>_stickout_<end>_mm`` and ``<name>_regrip_jaw_z_<end>_mm`` on each
    diameter the jaw fronts fall on, with diameter left in the jaws; the
    others lose them (no regrip on that diameter with that end out). With
    ``chuck_grip_in``, the jaws' length, a larger diameter within it is
    refused: the jaws would close on it instead."""
    if "regrip_grip_in" in parameters:
        raise CadError("process.regrip_stickout_*_in: not with regrip_grip_in")
    length = values["length_mm"]
    for end, key in _REGRIP_OUT.items():
        if key not in parameters:
            continue
        out_mm = _positive(parameters[key], f"process.{key}") * 25.4
        front = out_mm - values["regrip_allowance_mm"]
        if not 0 < front < length:
            raise CadError(f"process.{key}: the jaw fronts are off the part")
        values[f"regrip_stickout_{end}_mm"] = out_mm
        # The jaw fronts' station from the datum end.
        station = front if end == "datum" else length - front
        for name in turned:
            z0, z1 = values[f"{name}_z0_mm"], values[f"{name}_z1_mm"]
            # The jaws run from their fronts toward the chuck, on this diameter.
            if end == "datum":
                on = z0 - _STATION <= station < z1
            else:
                on = z0 < station <= z1 + _STATION
            if on:
                values[f"{name}_stickout_{end}_mm"] = out_mm
                values[f"{name}_regrip_jaw_z_{end}_mm"] = -front
            else:
                values.pop(f"{name}_stickout_{end}_mm", None)
                values.pop(f"{name}_regrip_jaw_z_{end}_mm", None)
        gripped = [n for n in turned if f"{n}_regrip_jaw_z_{end}_mm" in values]
        if "chuck_grip_in" not in parameters or not gripped:
            continue
        reach = _positive(parameters["chuck_grip_in"], "process.chuck_grip_in") * 25.4
        inner = station + reach if end == "datum" else station - reach
        low, high = sorted((station, inner))
        held = max(values[f"{n}_dia_mm"] for n in gripped)
        for name in turned:
            z0, z1 = values[f"{name}_z0_mm"], values[f"{name}_z1_mm"]
            inside = z0 < high - _STATION and z1 > low + _STATION
            if inside and values[f"{name}_dia_mm"] > held:
                raise CadError(
                    f"process.{key}: the jaws reach {name}, larger than the "
                    "diameter they grip"
                )


def _blank(values: dict, parameters: dict, least_bar: float, turned: list) -> list:
    """A blank sawn from round stock, faced to length on the lathe."""
    stock, blank = (_positive(parameters[key], f"process.{key}") for key in _BLANK)
    values["stock_dia_mm"] = stock * 25.4
    for name in turned:
        values[f"{name}_stock_key"] = "stock_dia_in"
        _bar_size(values, name, stock * 25.4, "stock_dia_in")
        _lathe_z(values, name)
    if "quantity" in parameters:
        _count(parameters, "quantity")
    # The length this traveler makes: the faced band when bound (the made
    # length within the body band), else the supply or finished length.
    key = "supply_length" if "supply_length_mm" in values else "length"
    if "faced_length_band_mm" in values:
        key = "faced_length"
    made = values[f"{key}_mm"]
    low, high = values.get(f"{key}_band_mm", [made, made])
    if key == "faced_length":
        # Judged against the band the sheet prints.
        low, high = (values[f"faced_length_{e}_in"] * 25.4 for e in ("min", "max"))
    values["blank_length_mm"] = blank * 25.4
    if blank * 25.4 < low - _TOLERANCE:
        raise CadError("process.blank_length_in: shorter than the part")
    # A blank already inside the band is the part's length: nothing to face.
    face = 0.0 if blank * 25.4 <= high + _TOLERANCE else blank - made / 25.4
    values["face_stock_in"], values["face_stock_mm"] = face, face * 25.4
    values["face_stock_per_end_in"] = face / 2
    values["face_stock_per_end_mm"] = face * 12.7
    if "end_stickout_in" in parameters:
        out = _positive(parameters["end_stickout_in"], "process.end_stickout_in")
        values["end_stickout_mm"] = out * 25.4
        # Z0 the faced end, Z+ away from the chuck.
        values["end_jaw_z_mm"] = -out * 25.4
    return [
        StockAxis("diameter", "stock_dia_in", least_bar),
        StockAxis("length", "blank_length_in", low),
    ]


def load_turned_shaft(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the shaft's length, domes, diameters, thread, grooves, flats,
    cross holes and fillets, and its bar-fed or sawn-blank process."""
    raw, values, features = _read_manifest(path, part, "turned_shaft")
    _model_frame(raw)
    for name, item in features.items():
        if not isinstance(item, dict) or item.get("frame") != "model":
            raise CadError(f"{name}: expected a model-frame feature")
    if "flat_cutter_dia_mm" in parameters and "flat_mill_dia_mm" in parameters:
        # The one-pass cutter the flats' paths use and the end mill the vise
        # picture draws are one tool: refuse drift, in every profile.
        cutter = _positive(
            parameters["flat_cutter_dia_mm"], "process.flat_cutter_dia_mm"
        )
        mill = _positive(parameters["flat_mill_dia_mm"], "process.flat_mill_dia_mm")
        if abs(cutter - mill) > _STATION:
            raise CadError(
                "process.flat_mill_dia_mm: disagrees with process.flat_cutter_dia_mm"
            )
    known = {"datum_end", "far_end", "shoulder", "tap", *_DIAMETERS}
    unknown = sorted(
        name
        for name in features
        if name not in known and not name.startswith(_FAMILIES)
    )
    if unknown:
        raise CadError(f"cad.features: unsupported {', '.join(unknown)}")
    for end in _DOMES:
        if features.get(end, {}).get("kind") not in ("face", "dome"):
            raise CadError(f"{end}: expected a model-frame face or dome")
    # A domed end's plane is its apex, as a face end's is its face.
    frame = _frame({"datum_end": features["datum_end"] | {"kind": "face"}})
    values["axis"] = _AXES[frame[0]]
    _length(features["far_end"], frame, values)
    if "outer" not in features:
        raise CadError("outer: a turned part needs its outside diameter")
    turned = [name for name in _DIAMETERS if name in features] + sorted(
        name for name in features if name.startswith("step_")
    )
    sizes = {name: _turned(features[name], name, frame, values) for name in turned}
    ordered = sorted(turned, key=lambda name: values[f"{name}_z0_mm"])
    start, end = 0.0, values["length_mm"]
    for side, name in (("datum_end", ordered[0]), ("far_end", ordered[-1])):
        if features[side]["kind"] != "dome":
            continue
        if _press_ref(values, name):
            raise CadError(f"{side}: a dome on {name}, a REF turned to its mate")
        radius = values.get(f"{name}_nominal_mm", values[f"{name}_dia_mm"]) / 2
        low, high = values.get(f"{name}_dia_band_mm", [2 * radius, 2 * radius])
        # A threaded diameter's model may sit at the thread's basic major.
        major = _basic_major(features[name].get("thread"))
        roots = (low / 2, max(high / 2, radius, major / 2))
        _dome(features[side], side, values, radius, roots)
        if _form_keys(parameters, _DOMES[side])[0] is not None:
            _form(values, parameters, _DOMES[side], radius, roots)
        if side == "datum_end":
            start = values["dome_datum_root_z_mm"]
        else:
            end = values["dome_far_root_z_mm"]
    # The shared Ø band binds only where an end this traveler forms reads it
    # (an end with its own band reads that instead).
    if any(key.startswith("dome_form_dia_") for key in parameters) and not any(
        f"{prefix}_form_radius_mm" in values
        and _form_keys(parameters, prefix)[1][0] == "dome_form_dia_min_in"
        for prefix in _DOMES.values()
    ):
        raise CadError(
            "process.dome_form_dia_min_in/_max_in: bind only with "
            "dome_form_radius_in on a dome this traveler forms"
        )
    for prefix in _DOMES.values():
        own = [k for k in parameters if k.startswith(f"{prefix}_form_")]
        if own and f"{prefix}_form_radius_mm" not in values:
            raise CadError(
                f"process.{own[0]}: binds only on a dome this traveler forms"
            )
    _tiles(values, turned, start, end)
    _body(features["far_end"], values)
    _faced(values)
    if "dome_chamfer_in" in parameters:
        _dome_chamfer(values, parameters)
    threaded = [name for name in turned if "thread" in features[name]]
    if len(threaded) > 1:
        raise CadError("cad.features: at most one threaded diameter")
    for name in threaded:
        _thread(features[name], name, values, start, end)
    supplied = _as_supplied(parameters, sizes, values)
    if "shoulder" in features:
        _shoulder_from(features["shoulder"], frame, values)
    far = features["far_end"]
    if "station" in far.get("requirements", []):
        length = values["length_mm"]
        _located(far, "far_end", values, (length, length))
    for name in turned:
        _run_length(features[name], name, values)
    if "tap" in features:
        _tap(features["tap"], frame, values, parameters)
    for name in sorted(features):
        item = features[name]
        if name.startswith("chamfer_"):
            _chamfer(item, name, features, values)
        elif name.startswith("groove"):
            _groove(item, name, frame, values, turned)
        elif name.startswith("cross_hole"):
            _cross_hole(item, name, frame, values, turned)
        elif name.startswith("flat_"):
            _flat(item, name, frame, values, turned, parameters)
        elif name.startswith("fillet_"):
            _fillet(item, name, frame, values, turned)
    _edge_breaks(raw, values)
    _rough_sizes(parameters, values, sizes, turned, supplied)
    if "dome_steps" in parameters:
        _steps(values, parameters)
    least_bar = max(sizes.values())
    axes: list[StockAxis] = []
    if "blank_length_in" in parameters:
        bar_only = {
            "face_allowance_in",
            "part_kerf_in",
            "regrip_allowance_in",
            "centre_stub_in",
        }
        if (bar_only | set(_BAR_LENGTH) | set(_PULL)) & set(parameters):
            raise CadError("process: round bar and a sawn blank are exclusive")
        _all_or_none(parameters, _BLANK, "the sawn blank")
        axes = _blank(values, parameters, least_bar, turned)
    elif "stock_dia_in" in parameters and _all_or_none(parameters, _BAR, "round bar"):
        if "supply_length_mm" in values:
            raise CadError("process: a part cut to fit at assembly takes a sawn blank")
        axes = _bar(values, parameters, sizes, least_bar, turned)
        if set(_REGRIP_OUT.values()) & set(parameters):
            _regrip_stickout(values, parameters, turned)
    if set(_REGRIP_OUT.values()) & set(parameters) and "pitch_mm" not in values:
        raise CadError("process.regrip_stickout_*_in: binds only with round bar")
    if "end_stickout_in" in parameters and "blank_length_mm" not in values:
        raise CadError("process.end_stickout_in: binds only with a sawn blank")
    if "regrip_grip_in" in parameters and "pitch_mm" not in values:
        raise CadError("process.regrip_grip_in: binds only with round bar")
    if supplied and "stock_dia_mm" not in values:
        raise CadError("process.as_supplied: needs round stock")
    requirement = StockRequirement("in", tuple(axes)) if axes else None
    return CadData(values, requirement, path.resolve())
