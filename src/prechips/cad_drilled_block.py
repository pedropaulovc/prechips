"""Bindings for a drilled block: any part described by its faces, round ends
and turned outsides, with a table of plain, reamed and tapped holes along the
model axes.

The manifest names the part's features; the adapter knows no feature by name.
Each kind has a geometric meaning:

* ``face``: a plane square to a model axis (``plane``);
* ``arc``: a round end or arched top about a model axis (``center``,
  ``axis``, ``radius`` with ``radius_nominal``, and ``apex``, the unit
  direction in which it bounds the part);
* ``outside_cylinder``: a turned outside (``at`` one end, ``axis`` along its
  length, ``dia`` with ``nominal_dia`` or a ``dia_ref`` reference size with
  an optional least ``dia_ref_min`` as bought, or at most one
  ``diametral_clearance`` or ``diametral_interference`` band, ``length``
  with ``length_nominal``);
* ``outside_cone``: a tapered outside (a taper pin): ``at`` its large end,
  ``axis`` toward its small end, the large end's ``dia_ref`` (or ``dia``
  with ``nominal_dia``), ``small_dia_ref`` and ``length_ref`` (or
  ``length_nominal``);
* ``hex_prism``: a length of hex bar (``at`` one end, ``axis`` along its
  length, ``length_nominal``, its size across the flats as an ``af`` band
  with ``af_nominal`` or a stock ``af_ref``, and ``corner``, the unit
  direction square to the axis in which two corners lie);
* ``hole`` and ``threaded_hole``: drilled, reamed or tapped along a model axis
  from its entry point (``at``, ``axis`` into the part), through, blind or
  running into another hole.

Any other kind (a pocket, a step, a chamfer) is bound by its bands alone.
Every banded drawing requirement binds the same way whatever it is named, and
a band located from a face or another feature is checked against the model:
the plan prints what the drawing requires, in the part's own words.

The envelope is the box over every face plane, each arc's apex, every
outside cylinder and every hex prism's corners and flats; a manifest must
declare every outside face for it to be the part's. On an axis those leave no span, a feature's ``corners`` (a list of
model points [x, y, z]: the corners of an outside face square to no model
axis, such as a slant or tapered side) bound it; on an axis they do span,
each corner must lie within it. A corners-bound axis is the box over the
corners, so hole checks along it read that box, not the slant itself.
A hole along a hex prism is walled to its flats; one across it must enter,
and a blind one end, within them (its sides are checked against the
envelope, as across a cylinder).
"""

import math
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _edge_breaks,
    _mid,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
    inch_thread,
)

_AXES = "xyz"
# Model agreement: positions and their nominal dimensions come from the same
# CAD values, so they agree far finer than any drawing prints.
_TOLERANCE = 1e-3
_HOLES = ("hole", "threaded_hole")
_SKIP = {
    "kind",
    "frame",
    "requirements",
    "faces",
    "cite",
    "precision",
    "configuration",
    "nominal_dia",
}
# Jobber twist drills' 118° point: a blind drilled hole's point runs past its
# full-diameter depth.
_POINT_HALF_ANGLE = math.radians(59.0)


def _axis(value: object, where: str) -> tuple[int, int]:
    """A unit vector along a model axis: its index and sign."""
    if not isinstance(value, list) or len(value) != 3:
        raise CadError(f"{where}: expected a unit vector along a model axis")
    numbers = [_number(item, where) for item in value]
    nonzero = [index for index, item in enumerate(numbers) if item != 0]
    if len(nonzero) != 1 or abs(numbers[nonzero[0]]) != 1:
        raise CadError(f"{where}: expected a unit vector along a model axis")
    return nonzero[0], int(numbers[nonzero[0]])


def _point(value: object, where: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise CadError(f"{where}: expected a model point [x, y, z]")
    return [_number(item, where) for item in value]


def _is_band(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(type(item) in (int, float) for item in value)
    )


def _bind(values: dict, key: str, value: object) -> None:
    if key in values:
        raise CadError(f"cad.{key}: bound twice; rename a feature or field")
    values[key] = value


def _bind_mm(values: dict, key: str, value: float) -> None:
    _bind(values, f"{key}_mm", value)
    _bind(values, f"{key}_in", value / 25.4)


def _model_feature(name: str, feature: dict) -> None:
    """Every position the adapter reads is in the model frame."""
    plane = feature.get("plane")
    if feature.get("frame") != "model" or (
        isinstance(plane, dict) and plane.get("frame") != "model"
    ):
        raise CadError(f"{name}: expected a model-frame feature")


def _nominal(feature: dict, key: str) -> object:
    """A band's nominal: `<key>_nominal`, or a diameter's `nominal_dia`."""
    if f"{key}_nominal" in feature:
        return feature[f"{key}_nominal"]
    return feature.get("nominal_dia") if key == "dia" else None


def _bands(name: str, feature: dict, values: dict) -> None:
    """Every banded requirement, its nominal and the scalars beside them.
    Signed bands (stations either side of a datum) bind as they are."""
    requirements = feature.get("requirements")
    if not isinstance(requirements, list):
        raise CadError(f"{name}.requirements: expected a list")
    for key in requirements:
        if key in ("plane", "unknown"):
            continue
        if key not in feature:
            raise CadError(f"{name}.{key}: missing drawing requirement")
        value = feature[key]
        if not _is_band(value):
            if isinstance(value, (str, bool)) or type(value) in (int, float):
                _bind(values, f"{name}_{key}", value)
            # A listed one-sided limit (a least wall, a largest corner radius)
            # is a length in the manifest's millimetres by contract; a limit
            # in any other unit ends with that unit (`point_angle_max_deg`,
            # `engagement_min_turns`). It binds `_mm` only, which the `in`
            # format prints in inches; a band's `_min_in`/`_max_in` stay its own.
            if type(value) in (int, float) and key.endswith(("_min", "_max")):
                _bind(values, f"{name}_{key}_mm", float(value))
            continue
        band = _band(feature, key, name)
        _bind(values, f"{name}_{key}_in", _mid(band) / 25.4)
        _bind(values, f"{name}_{key}_min_in", band[0] / 25.4)
        _bind(values, f"{name}_{key}_max_in", band[1] / 25.4)
        _bind(values, f"{name}_{key}_band_mm", list(band))
        nominal = _nominal(feature, key)
        if nominal is not None:
            nominal = _number(nominal, f"{name}.{key}_nominal")
            # A unilateral fit (.3750 +.0015/+.0010) has its nominal size
            # outside its band; any other nominal lies in it.
            if key != "dia" and not band[0] - 1e-6 <= nominal <= band[1] + 1e-6:
                raise CadError(
                    f"{name}.{key}_nominal: {nominal:g} mm lies outside its band"
                )
            _bind(values, f"{name}_{key}_mm", nominal)
    for key, item in feature.items():
        if key in _SKIP or key in requirements or f"{name}_{key}" in values:
            continue
        if key.endswith("_nominal"):
            base = key[: -len("_nominal")]
            if base not in requirements:
                _bind(values, f"{name}_{base}_mm", _number(item, f"{name}.{key}"))
        elif isinstance(item, (str, bool)) or type(item) in (int, float):
            _bind(values, f"{name}_{key}", item)
        elif _is_band(item):
            # An unlisted band (a reference or process range) binds in mm.
            _bind(values, f"{name}_{key}_band_mm", [float(v) for v in item])


class _Shape:
    """Positions (for located bands), hole ends and the envelope."""

    def __init__(self) -> None:
        self.low = [math.inf] * 3
        self.high = [-math.inf] * 3
        self.positions: dict[str, list[float | None]] = {}
        self.planes: dict[str, int] = {}
        # Per hole: axis index, sign, and how far past its entry it runs
        # ("thru", ("depth", least, greatest) or ("into", target)).
        self.holes: dict[str, tuple[int, int, object]] = {}
        # Per outside cylinder: axis index, its span along it, least diameter.
        self.cylinders: dict[str, tuple[int, tuple[float, float], float]] = {}
        # Per hex prism: axis index, corner axis index, its span along it,
        # least and nominal size across the flats.
        self.prisms: dict[str, tuple[int, int, tuple[float, float], float, float]] = {}

    def extend(self, index: int, low: float, high: float) -> None:
        self.low[index] = min(self.low[index], low)
        self.high[index] = max(self.high[index], high)

    def end(self, name: str, least: bool = False) -> float:
        """Where a hole's full diameter ends along its own axis: a blind hole
        at its greatest depth, or its least when `least`."""
        index, sign, run = self.holes[name]
        entry = self.positions[name][index]
        if run == "thru":
            return self.high[index] if sign > 0 else self.low[index]
        if run[0] == "depth":
            return entry + sign * (run[1] if least else run[2])
        return self.positions[run[1]][index]


def _face(name: str, feature: dict, shape: _Shape, bounds: bool = True) -> None:
    """A plane square to a model axis; `bounds` when it is an outside face."""
    plane = feature.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") not in tuple(_AXES):
        raise CadError(f"{name}.plane: expected a plane square to a model axis")
    index = _AXES.index(plane["axis"])
    value = _number(plane.get("value"), f"{name}.plane.value")
    if bounds:
        shape.extend(index, value, value)
    position: list[float | None] = [None, None, None]
    position[index] = value
    shape.positions[name] = position
    shape.planes[name] = index


def _arc(name: str, feature: dict, shape: _Shape) -> None:
    """A round end or arched top: it bounds the part only at its apex, the
    radius out from its centre along `apex` (a segmental arch is clipped by
    the faces beside it)."""
    centre = _point(feature.get("center"), f"{name}.center")
    index, _sign = _axis(feature.get("axis"), f"{name}.axis")
    apex, sign = _axis(feature.get("apex"), f"{name}.apex")
    if apex == index:
        raise CadError(f"{name}.apex: expected square to the arc's axis")
    _band(feature, "radius", name)
    radius = _number(feature.get("radius_nominal"), f"{name}.radius_nominal")
    if radius <= 0:
        raise CadError(f"{name}.radius_nominal: expected a positive radius")
    top = centre[apex] + sign * radius
    shape.extend(apex, top, top)
    shape.positions[name] = centre


_FITS = ("diametral_clearance", "diametral_interference")


def _cylinder(name: str, feature: dict, values: dict, shape: _Shape) -> None:
    """A turned outside: its diameter about the axis, its length along it.

    The diameter is a `dia` band (a fit printed beside it is bound as a
    band), or a `dia_ref` reference size: a bought outside left as
    supplied, with an optional least size `dia_ref_min` it may arrive at, or
    one turned to a measured mate with at most one fit band
    (`diametral_clearance` under it, `diametral_interference` over it).
    Walls read the least it can be: the band's low end, `dia_ref_min` (else
    the reference), the reference less the most clearance, or plus the least
    interference (the mate assumed at or over its reference). The envelope
    reads the most: the nominal, the reference, or the reference plus the
    most interference."""
    centre = _point(feature.get("at"), f"{name}.at")
    index, sign = _axis(feature.get("axis"), f"{name}.axis")
    fits = [key for key in _FITS if key in feature]
    if "dia" in feature and "dia_ref" in feature:
        raise CadError(f"{name}.dia_ref: a reference size takes no dia band")
    if "dia" not in feature and "dia_ref" not in feature:
        raise CadError(f"{name}.dia: expected a dia band or a dia_ref")
    if "dia" in feature:
        if "dia_ref_min" in feature:
            raise CadError(f"{name}.dia_ref_min: goes with a dia_ref")
        least = _band(feature, "dia", name)[0]
        radius = _number(feature.get("nominal_dia"), f"{name}.nominal_dia") / 2
    else:
        ref = _positive(feature.get("dia_ref"), f"{name}.dia_ref")
        if "nominal_dia" in feature:
            raise CadError(f"{name}.nominal_dia: a reference size takes none")
        if len(fits) > 1:
            raise CadError(f"{name}: a fit is a clearance or a press, not both")
        least, most = ref, ref
        if "dia_ref_min" in feature:
            if fits:
                raise CadError(f"{name}.dia_ref_min: a fit sets the least size")
            least = _positive(feature["dia_ref_min"], f"{name}.dia_ref_min")
            if least > ref:
                raise CadError(f"{name}.dia_ref_min: over the dia_ref")
        if fits:
            fit = _band(feature, fits[0], name)
            if fit[0] < 0:
                raise CadError(f"{name}.{fits[0]}: expected a positive band")
            if fits[0] == _FITS[0]:
                least = ref - fit[1]
            else:
                least, most = ref + fit[0], ref + fit[1]
        if least <= 0:
            raise CadError(f"{name}: its least diameter is not positive")
        radius = most / 2
        _bind_mm(values, f"{name}_dia_ref", ref)
    _bind_mm(values, f"{name}_dia_least", least)
    length = _number(feature.get("length_nominal"), f"{name}.length_nominal")
    if radius <= 0 or length <= 0:
        raise CadError(f"{name}: expected a positive diameter and length")
    for other in range(3):
        if other != index:
            shape.extend(other, centre[other] - radius, centre[other] + radius)
    span = _along(name, centre, index, sign, length, shape)
    shape.cylinders[name] = (index, span, least)


def _along(
    name: str,
    centre: list[float],
    index: int,
    sign: int,
    length: float,
    shape: _Shape,
) -> tuple[float, float]:
    """An outside's span along its axis, which bounds the part; it has no one
    station along its length (its ends do)."""
    low, high = sorted((centre[index], centre[index] + sign * length))
    shape.extend(index, low, high)
    position: list[float | None] = list(centre)
    position[index] = None
    shape.positions[name] = position
    return low, high


def _hex_prism(name: str, feature: dict, values: dict, shape: _Shape) -> None:
    """A length of hex bar: its corners bound the part along ``corner``, its
    flats across the third axis; its flats wall holes along it and bound the
    entries and blind ends of holes across it."""
    centre = _point(feature.get("at"), f"{name}.at")
    index, sign = _axis(feature.get("axis"), f"{name}.axis")
    corner, _corner_sign = _axis(feature.get("corner"), f"{name}.corner")
    if corner == index:
        raise CadError(f"{name}.corner: expected square to the prism's axis")
    if "af" in feature.get("requirements", ()):
        # A banded size binds with its nominal as any band does.
        least = _band(feature, "af", name)[0]
        af = _number(feature.get("af_nominal"), f"{name}.af_nominal")
    else:
        af = _number(feature.get("af_ref"), f"{name}.af_ref")
        least = af
        _bind_mm(values, f"{name}_af", af)
    length = _number(feature.get("length_nominal"), f"{name}.length_nominal")
    if af <= 0 or length <= 0:
        raise CadError(f"{name}: expected a positive size across the flats and length")
    across_corners = 2 * af / math.sqrt(3)
    # An exported or banded size across the corners is a check (the prism is
    # a regular hexagon); the derived size binds only what it leaves unbound.
    if abs(values.get(f"{name}_ac_mm", across_corners) - across_corners) > _TOLERANCE:
        raise CadError(f"{name}.ac: not a regular hexagon's across the corners")
    values.setdefault(f"{name}_ac_mm", across_corners)
    values.setdefault(f"{name}_ac_in", across_corners / 25.4)
    if "ac" in feature.get("requirements", ()):
        low, high = _band(feature, "ac", name)
        if not low - _TOLERANCE <= across_corners <= high + _TOLERANCE:
            raise CadError(f"{name}.ac: not a regular hexagon's across the corners")
    flats = 3 - index - corner
    shape.extend(
        corner, centre[corner] - across_corners / 2, centre[corner] + across_corners / 2
    )
    shape.extend(flats, centre[flats] - af / 2, centre[flats] + af / 2)
    span = _along(name, centre, index, sign, length, shape)
    shape.prisms[name] = (index, corner, span, least, af)


def _off_flats(at: list, centre: list, corner: int, index: int) -> float:
    """How far a point lies out from a hex prism's axis toward its farthest
    flat: the largest of its offset's projections on the three flat normals
    (one along the flats' axis, two at 30° to the corners')."""
    flats = 3 - index - corner
    dc, df = at[corner] - centre[corner], at[flats] - centre[flats]
    return max(
        abs(df),
        abs(dc * math.sqrt(3) / 2 + df / 2),
        abs(dc * math.sqrt(3) / 2 - df / 2),
    )


def _cone(name: str, feature: dict, shape: _Shape, values: dict) -> None:
    """A tapered outside: bounded by its large end across the axis and its
    length along it; a hole run along it is walled by its small end."""
    centre = _point(feature.get("at"), f"{name}.at")
    index, sign = _axis(feature.get("axis"), f"{name}.axis")
    large_key = "dia_ref" if "dia_ref" in feature else "nominal_dia"
    large = _number(feature.get(large_key), f"{name}.{large_key}")
    small = _number(feature.get("small_dia_ref"), f"{name}.small_dia_ref")
    length_key = "length_ref" if "length_ref" in feature else "length_nominal"
    length = _number(feature.get(length_key), f"{name}.{length_key}")
    if not 0 < small < large or length <= 0:
        raise CadError(
            f"{name}: expected a small end under a positive large end and a "
            "positive length"
        )
    for other in range(3):
        if other != index:
            shape.extend(other, centre[other] - large / 2, centre[other] + large / 2)
    span = sorted((centre[index], centre[index] + sign * length))
    shape.extend(index, *span)
    shape.cylinders[name] = (index, (span[0], span[1]), small)
    _bind(
        values,
        f"{name}_half_angle_deg",
        math.degrees(math.atan((large - small) / 2 / length)),
    )
    position: list[float | None] = list(centre)
    position[index] = None
    shape.positions[name] = position


def _depth(feature: dict, key: str, name: str) -> tuple[float, float]:
    """A depth band: positive, measured into the part from the entry."""
    band = _band(feature, key, name)
    if band[0] <= 0:
        raise CadError(f"{name}.{key}: expected a positive depth band")
    return band


def _hole(name: str, feature: dict, values: dict, shape: _Shape, kind: str) -> None:
    at = _point(feature.get("at"), f"{name}.at")
    index, sign = _axis(feature.get("axis"), f"{name}.axis")
    dia = _band(feature, "dia", name)
    blind = "drill_depth" if kind == "threaded_hole" else "depth"
    ends = [key for key in ("thru", "into", blind) if key in feature]
    if feature.get("thru") not in (None, True) or len(ends) != 1:
        raise CadError(f"{name}: expected exactly one of thru = true, into, {blind}")
    if kind == "hole":
        # A hole made at assembly (transferred, match-drilled) is printed but
        # not made by this traveler, so it names no process.
        if feature.get("process") not in ("drill", "ream") and not (
            feature.get("made_at") == "assembly" and "process" not in feature
        ):
            raise CadError(f'{name}.process: expected "drill" or "ream"')
        if "drill_depth" in feature:
            raise CadError(f"{name}: a plain hole's blind end is its depth")
    else:
        major, tpi, _numbered = inch_thread(
            _string(feature.get("thread"), f"{name}.thread"), f"{name}.thread"
        )
        _bind(values, f"{name}_thread_major_mm", major)
        _bind(values, f"{name}_thread_pitch_mm", 25.4 / tpi)
        _bind(values, f"{name}_thread_tpi", tpi)
        if dia[1] >= major:
            raise CadError(
                f"{name}.dia: the tap drill reaches the thread's major diameter"
            )
        if "depth" in feature:
            raise CadError(f"{name}: a tapped hole's blind end is its drill_depth")
        lead = feature.get("plug_tap_lead", 0.0)
        if _number(lead, f"{name}.plug_tap_lead") < 0:
            raise CadError(f"{name}.plug_tap_lead: expected a length")
        if "thread_depth" in feature:
            thread = _depth(feature, "thread_depth", name)
            if "drill_depth" in feature:
                drill = _depth(feature, "drill_depth", name)
                # A plug tap run to the deepest full thread puts its point the
                # lead further down: it must not bottom in the shallowest hole.
                if drill[0] <= thread[1] + lead:
                    raise CadError(
                        f"{name}.drill_depth: {drill[0]:g} mm at least does not "
                        f"clear {thread[1]:g} mm of thread plus the tap's "
                        f"{lead:g} mm lead"
                    )
    if "thru" in feature:
        run: object = "thru"
    elif "into" in feature:
        run = ("into", feature["into"])
    else:
        run = ("depth", *_depth(feature, blind, name))
    shape.positions[name] = at
    shape.holes[name] = (index, sign, run)


def _into(name: str, feature: dict, values: dict, shape: _Shape) -> None:
    """A hole run into another: square to it, on its axis line, ahead of the
    entry and within the target's length; binds the entry's distance to that
    axis."""
    target = feature["into"]
    index, sign, _run = shape.holes[name]
    other_index, _other_sign, _other_run = shape.holes[target]
    if index == other_index:
        raise CadError(f"{name}.into: expected square to {target}")
    third = 3 - index - other_index
    mine, theirs = shape.positions[name], shape.positions[target]
    if abs(mine[third] - theirs[third]) > _TOLERANCE:
        raise CadError(f"{name}.into: its axis misses {target}'s axis")
    reach = sign * (theirs[index] - mine[index])
    if reach <= 0:
        raise CadError(f"{name}.into: {target} lies behind its entry")
    # The target must reach the crossing even drilled to its least depth.
    span = sorted((theirs[other_index], shape.end(target, least=True)))
    if not span[0] - _TOLERANCE <= mine[other_index] <= span[1] + _TOLERANCE:
        raise CadError(f"{name}.into: {target} does not reach its axis")
    _bind_mm(values, f"{name}_into_axis", reach)


def _distance(feature: dict, base: str) -> tuple[float | None, tuple | None]:
    """What a located band must match: its nominal (or a number given as its
    reference value) and its band, either absent. A negative value or band is
    a signed offset from the reference; otherwise a distance."""
    nominal = feature.get(f"{base}_nominal")
    if nominal is None and type(feature.get(base)) in (int, float):
        nominal = feature[base]
    if nominal is not None:
        nominal = _number(nominal, f"{base}_nominal")
    band = feature.get(base)
    return nominal, (float(band[0]), float(band[1])) if _is_band(band) else None


def _located(name: str, feature: dict, features: dict, shape: _Shape) -> None:
    """Each `<K>_from` agrees with the model: its nominal exactly, else its
    band. A kind with no position (a pocket) is bound, not checked."""
    position = shape.positions.get(name)
    for key, reference in feature.items():
        if not key.endswith("_from"):
            continue
        base = key[: -len("_from")]
        if not isinstance(reference, str) or reference not in features:
            raise CadError(f"{name}.{key}: expected a feature name, not {reference!r}")
        if position is None:
            continue
        nominal, band = _distance(feature, base)
        if nominal is None and band is None:
            raise CadError(
                f"{name}.{key}: needs {base}_nominal, a reference {base} or a "
                f"{base} band"
            )
        if reference in shape.planes:
            index = shape.planes[reference]
            if name in shape.planes and shape.planes[name] != index:
                raise CadError(f"{name}.{key}: {reference} is not parallel")
        else:
            axis = feature.get(f"{base}_axis")
            if axis not in tuple(_AXES):
                raise CadError(f'{name}.{base}_axis: expected "x", "y" or "z"')
            index = _AXES.index(axis)
        mine = position[index]
        theirs = shape.positions.get(reference, [None] * 3)[index]
        if mine is None or theirs is None:
            raise CadError(f"{name}.{key}: no position along {_AXES[index]}")
        offset = mine - theirs
        signed = (nominal is not None and nominal < 0) or (
            band is not None and band[0] < 0
        )
        found = offset if signed else abs(offset)
        if nominal is not None and abs(found - nominal) > _TOLERANCE:
            raise CadError(
                f"{name}.{base}: the model puts it {found:.4f} mm from "
                f"{reference}, not its {nominal:g} mm nominal"
            )
        if band is not None and not (
            band[0] - _TOLERANCE <= found <= band[1] + _TOLERANCE
        ):
            raise CadError(
                f"{name}.{base}: the model puts it {found:.4f} mm from "
                f"{reference}, outside its band"
            )


def _inside(name: str, feature: dict, values: dict, shape: _Shape) -> None:
    """A hole's entry and blind end (with a drill's point) lie in the envelope,
    and its largest diameter breaks out of neither the envelope's sides nor a
    turned outside it runs along."""
    at = shape.positions[name]
    index, sign, run = shape.holes[name]
    radius = feature["dia"][1] / 2
    if feature["kind"] == "threaded_hole":
        radius = max(radius, values[f"{name}_thread_major_mm"] / 2)
    for other in range(3):
        low, high = shape.low[other], shape.high[other]
        reach = 0.0 if other == index else radius
        if (
            at[other] - reach < low - _TOLERANCE
            or at[other] + reach > high + _TOLERANCE
        ):
            raise CadError(f"{name}: breaks out of the part along {_AXES[other]}")
    end = shape.end(name)
    if run != "thru" and run[0] == "depth":
        # Every blind hole is drilled first (a reamed one too, its pilot under
        # the reamed size): bound its point with the largest diameter.
        point = feature["dia"][1] / 2 / math.tan(_POINT_HALF_ANGLE)
        tip = end + sign * point
        if not shape.low[index] - _TOLERANCE <= tip <= shape.high[index] + _TOLERANCE:
            raise CadError(f"{name}: its blind end breaks out of the part")
    # A thread tapped only part way along a through or cross-drilled hole
    # stops inside that hole's own length.
    elif (
        "thread_depth" in feature
        and feature["thread_depth"][1] > abs(end - at[index]) + _TOLERANCE
    ):
        raise CadError(f"{name}.thread_depth: runs past the hole's length")
    extent = sorted((at[index], end))
    for outside, (cylinder_index, span, least_dia) in shape.cylinders.items():
        if cylinder_index != index:
            continue
        if extent[1] <= span[0] + _TOLERANCE or extent[0] >= span[1] - _TOLERANCE:
            continue
        centre = shape.positions[outside]
        offset = math.hypot(*(at[i] - centre[i] for i in range(3) if i != index))
        wall = least_dia / 2 - offset - radius
        if wall <= 0:
            raise CadError(f"{name}: breaks out of {outside} at the band extremes")
        _bind_mm(values, f"{name}_wall_to_{outside}_worst", wall)
    for outside, (prism_index, corner, span, least_af, af) in shape.prisms.items():
        centre = shape.positions[outside]
        if prism_index == index:
            if extent[1] <= span[0] + _TOLERANCE or extent[0] >= span[1] - _TOLERANCE:
                continue
            wall = least_af / 2 - _off_flats(at, centre, corner, index) - radius
            if wall <= 0:
                raise CadError(f"{name}: breaks out of {outside} at the band extremes")
            _bind_mm(values, f"{name}_wall_to_{outside}_worst", wall)
            continue
        # A hole across the prism enters through its flats or corners, and a
        # blind one ends inside them.
        if not span[0] - _TOLERANCE <= at[prism_index] <= span[1] + _TOLERANCE:
            continue
        if _off_flats(at, centre, corner, prism_index) > af / 2 + _TOLERANCE:
            raise CadError(f"{name}: enters in the air off {outside}'s flats")
        if run != "thru" and run[0] == "depth":
            tip_at = list(at)
            tip_at[index] = end + sign * feature["dia"][1] / 2 / math.tan(
                _POINT_HALF_ANGLE
            )
            if _off_flats(tip_at, centre, corner, prism_index) > af / 2 + _TOLERANCE:
                raise CadError(f"{name}: its blind end breaks out of {outside}'s flats")


def _corners(name: str, feature: dict) -> list[list[float]]:
    """A feature's `corners`, model points on the part's outside (a scalar
    `corners` is an ordinary field and binds as one)."""
    corners = feature.get("corners")
    if not isinstance(corners, list):
        return []
    if not corners:
        raise CadError(f"{name}.corners: expected a list of model points")
    return [_point(corner, f"{name}.corners") for corner in corners]


def _bound_corners(corners: list[tuple[str, list[float]]], shape: _Shape) -> None:
    """Corners bound each axis no face or round spans, and lie within the
    span of every axis one does."""
    spanned = [shape.high[index] - shape.low[index] > 0 for index in range(3)]
    for name, point in corners:
        for index in range(3):
            if not spanned[index]:
                shape.extend(index, point[index], point[index])
            elif not (
                shape.low[index] - _TOLERANCE
                <= point[index]
                <= shape.high[index] + _TOLERANCE
            ):
                raise CadError(
                    f"{name}.corners: a corner lies outside the faces bounding "
                    f"{_AXES[index]}"
                )


def load_drilled_block(path: Path, parameters: dict, part: str) -> CadData:
    """Bind every feature's bands and positions, the envelope and, from the
    plan's `blank_<axis>_in`, the blank it is cut from."""
    raw, values, features = _read_manifest(path, part, "drilled_block")
    _model_frame(raw)
    if not features:
        raise CadError("cad.features: expected the part's features")
    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["material_spec"] = _string(material.get("spec"), "cad.material.spec")
    # What the drawing's MATERIAL cell prints (as fence_plate binds it).
    values["material_name"] = _string(material.get("name"), "cad.material.name")
    values["finish"] = _string(material.get("finish"), "cad.material.finish")
    _edge_breaks(raw, values)
    shape = _Shape()
    corners: list[tuple[str, list[float]]] = []
    for name, feature in features.items():
        if not isinstance(feature, dict):
            raise CadError(f"cad.features.{name}: expected a table")
        kind = feature.get("kind")
        if not isinstance(kind, str) or not kind:
            raise CadError(f"{name}.kind: expected a kind")
        _model_feature(name, feature)
        _bands(name, feature, values)
        if kind == "face":
            _face(name, feature, shape)
        elif kind == "arc":
            _arc(name, feature, shape)
        elif kind == "outside_cylinder":
            _cylinder(name, feature, values, shape)
        elif kind == "outside_cone":
            _cone(name, feature, shape, values)
        elif kind == "hex_prism":
            _hex_prism(name, feature, values, shape)
        elif kind in _HOLES:
            _hole(name, feature, values, shape, kind)
        else:
            for key in ("at", "center"):
                if key in feature:
                    shape.positions[name] = _point(feature[key], f"{name}.{key}")
                    break
            else:
                if isinstance(feature.get("plane"), dict):
                    _face(name, feature, shape, bounds=False)
        corners += [(name, point) for point in _corners(name, feature)]
    _bound_corners(corners, shape)
    for index, axis in enumerate(_AXES):
        low, high = shape.low[index], shape.high[index]
        if not high - low > 0:
            raise CadError(
                f"cad.features: no outside face, round or corners span {axis}"
            )
        _bind_mm(values, f"envelope_{axis}", high - low)
        _bind(values, f"{axis}_min_mm", low)
        _bind(values, f"{axis}_max_mm", high)
    # Every `into` names another hole before any end or crossing is judged:
    # a chain of holes reads its target's end.
    for name, (_index, _sign, run) in shape.holes.items():
        if run != "thru" and run[0] == "into" and run[1] not in shape.holes:
            raise CadError(f"{name}.into: expected another hole, not {run[1]!r}")
    for name, feature in features.items():
        _located(name, feature, features, shape)
        if feature["kind"] in _HOLES:
            if "into" in feature:
                _into(name, feature, values, shape)
            _inside(name, feature, values, shape)
        for index, axis in enumerate(_AXES):
            coordinate = shape.positions.get(name, [None] * 3)[index]
            if coordinate is None:
                continue
            _bind(values, f"{name}_{axis}_mm", coordinate)
            _bind_mm(values, f"{name}_{axis}_from_min", coordinate - shape.low[index])
            _bind_mm(values, f"{name}_{axis}_from_max", shape.high[index] - coordinate)
    envelope = []
    for index, axis in enumerate(_AXES):
        key = f"blank_{axis}_in"
        if key in parameters:
            values[f"blank_{axis}_mm"] = (
                _number(parameters[key], f"process.{key}") * 25.4
            )
        envelope.append(StockAxis(axis, key, shape.high[index] - shape.low[index]))
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())
