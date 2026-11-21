"""Bindings for a drilled block: any part described by its faces, round ends
and turned outsides, with a table of plain, reamed and tapped holes along the
model axes.

The manifest names the part's features; the adapter knows no feature by name.
Each kind has a geometric meaning:

* ``face``: a plane square to a model axis (``plane``);
* ``arc``: a round end or arched top about a model axis (``center``,
  ``radius``);
* ``outside_cylinder``: a turned outside (``at`` one end, ``axis`` along its
  length, ``dia``, ``length``);
* ``hole`` and ``threaded_hole``: drilled, reamed or tapped along a model axis
  from its entry point (``at``, ``axis`` into the part), through, blind or
  running into another hole.

Any other kind (a pocket, a step, a chamfer) is bound by its bands alone.
Every banded drawing requirement binds the same way whatever it is named, and
a band located from a face or another feature is checked against the model:
the plan prints what the drawing requires, in the part's own words.

The envelope is the box over every face plane, arc and outside cylinder; a
manifest must declare every outside face for it to be the part's.
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
    _edge_breaks,
    _model_frame,
    _number,
    _read_manifest,
    _string,
)

_AXES = "xyz"
# Model agreement: positions and their nominal dimensions come from the same
# CAD values, so they agree far finer than any drawing prints.
_TOLERANCE = 1e-3
_HOLES = ("hole", "threaded_hole")
_SKIP = {"kind", "frame", "requirements", "faces", "cite", "precision", "configuration"}
# ASME B1.1 internal threads: numbered (#N-TPI) and fractional (a/b-TPI).
_THREAD = re.compile(r"(#\d+|\d+/\d+|\d+)-(\d+) UN(?:C|F|EF)-[123]B")


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


def _bands(name: str, feature: dict, values: dict) -> None:
    """Every banded requirement, its nominal and the scalars beside them."""
    requirements = feature.get("requirements")
    if not isinstance(requirements, list):
        raise CadError(f"{name}.requirements: expected a list")
    for key in requirements:
        if key in ("plane", "unknown"):
            continue
        if key not in feature:
            raise CadError(f"{name}.{key}: missing drawing requirement")
        band = feature[key]
        if not _is_band(band):
            if isinstance(band, (str, bool)) or type(band) in (int, float):
                _bind(values, f"{name}_{key}", band)
            continue
        low, high = (_number(item, f"{name}.{key}") for item in band)
        if low > high:
            raise CadError(f"{name}.{key}: expected [low, high]")
        _bind(values, f"{name}_{key}_in", (low + high) / 2 / 25.4)
        _bind(values, f"{name}_{key}_min_in", low / 25.4)
        _bind(values, f"{name}_{key}_max_in", high / 25.4)
        _bind(values, f"{name}_{key}_band_mm", [low, high])
        nominal = feature.get(f"{key}_nominal")
        if nominal is not None:
            nominal = _number(nominal, f"{name}.{key}_nominal")
            if not low - 1e-6 <= nominal <= high + 1e-6:
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


def _thread(name: str, feature: dict, values: dict) -> float:
    """The thread's basic major diameter, mm; binds its pitch."""
    thread = _string(feature.get("thread"), f"{name}.thread")
    match = _THREAD.fullmatch(thread)
    if match is None:
        raise CadError(
            f"{name}.thread: expected an internal inch thread, e.g. #4-40 UNC-2B"
        )
    size, tpi = match[1], int(match[2])
    if size.startswith("#"):
        major = 0.060 + 0.013 * int(size[1:])
    else:
        major = float(Fraction(size))
    _bind(values, f"{name}_thread_major_mm", major * 25.4)
    _bind(values, f"{name}_thread_pitch_mm", 25.4 / tpi)
    _bind(values, f"{name}_thread_tpi", tpi)
    return major * 25.4


class _Shape:
    """Positions (for located bands) and the envelope, accumulated per kind."""

    def __init__(self) -> None:
        self.low = [math.inf] * 3
        self.high = [-math.inf] * 3
        self.positions: dict[str, list[float | None]] = {}
        self.planes: dict[str, int] = {}

    def extend(self, index: int, low: float, high: float) -> None:
        self.low[index] = min(self.low[index], low)
        self.high[index] = max(self.high[index], high)


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


def _round(name: str, feature: dict, shape: _Shape, kind: str) -> None:
    """An arc's or outside cylinder's centre line and envelope."""
    if kind == "arc":
        centre = _point(feature.get("center"), f"{name}.center")
        index, _sign = _axis(feature.get("axis"), f"{name}.axis")
        radius = _number(feature.get("radius_nominal"), f"{name}.radius_nominal")
        span = None
    else:
        centre = _point(feature.get("at"), f"{name}.at")
        index, sign = _axis(feature.get("axis"), f"{name}.axis")
        radius = _number(feature.get("nominal_dia"), f"{name}.nominal_dia") / 2
        length = _number(feature.get("length_nominal"), f"{name}.length_nominal")
        span = sorted((centre[index], centre[index] + sign * length))
    if radius <= 0:
        raise CadError(f"{name}: expected a positive radius")
    for other in range(3):
        if other != index:
            shape.extend(other, centre[other] - radius, centre[other] + radius)
    if span is not None:
        shape.extend(index, *span)
    position: list[float | None] = list(centre)
    if span is not None:
        # A turned outside has no one station along its length: its ends do.
        position[index] = None
    shape.positions[name] = position


def _hole(name: str, feature: dict, values: dict, shape: _Shape, kind: str) -> None:
    at = _point(feature.get("at"), f"{name}.at")
    _axis(feature.get("axis"), f"{name}.axis")
    dia = feature.get("dia")
    if not _is_band(dia) or "dia" not in feature.get("requirements", []):
        raise CadError(f"{name}.dia: expected a drawing band")
    ends = [key for key in ("thru", "into", "depth", "drill_depth") if key in feature]
    if feature.get("thru") not in (None, True) or len(ends) != 1:
        raise CadError(
            f"{name}: expected exactly one of thru = true, into, "
            + ("drill_depth" if kind == "threaded_hole" else "depth")
        )
    if kind == "hole":
        if feature.get("process") not in ("drill", "ream"):
            raise CadError(f'{name}.process: expected "drill" or "ream"')
        if "drill_depth" in feature:
            raise CadError(f"{name}: a plain hole's blind end is its depth")
    else:
        major = _thread(name, feature, values)
        if dia[1] >= major:
            raise CadError(
                f"{name}.dia: the tap drill reaches the thread's major diameter"
            )
        if "depth" in feature:
            raise CadError(f"{name}: a tapped hole's blind end is its drill_depth")
        if "thread_depth" in feature and "drill_depth" in feature:
            thread = feature["thread_depth"]
            drill = feature["drill_depth"]
            if not (_is_band(thread) and _is_band(drill)) or drill[0] <= thread[1]:
                raise CadError(f"{name}.drill_depth: must exceed the thread depth")
        lead = feature.get("plug_tap_lead")
        if lead is not None and _number(lead, f"{name}.plug_tap_lead") <= 0:
            raise CadError(f"{name}.plug_tap_lead: expected a positive length")
    shape.positions[name] = at


def _into(
    name: str, feature: dict, features: dict, values: dict, shape: _Shape
) -> None:
    """A hole run into another: square to it, on its axis line, ahead of the
    entry; binds the entry's distance to that axis."""
    target = feature["into"]
    other = features.get(target)
    if not isinstance(other, dict) or other.get("kind") not in _HOLES:
        raise CadError(f"{name}.into: expected another hole, not {target!r}")
    index, sign = _axis(feature["axis"], f"{name}.axis")
    other_index, _sign = _axis(other["axis"], f"{target}.axis")
    if index == other_index:
        raise CadError(f"{name}.into: expected square to {target}")
    third = 3 - index - other_index
    mine, theirs = shape.positions[name], shape.positions[target]
    if abs(mine[third] - theirs[third]) > _TOLERANCE:
        raise CadError(f"{name}.into: its axis misses {target}'s axis")
    reach = sign * (theirs[index] - mine[index])
    if reach <= 0:
        raise CadError(f"{name}.into: {target} lies behind its entry")
    _bind_mm(values, f"{name}_into_axis", reach)


def _located(name: str, feature: dict, features: dict, shape: _Shape) -> None:
    """Each `<K>_from` with a `<K>_nominal` agrees with the model."""
    for key, reference in feature.items():
        if not key.endswith("_from"):
            continue
        base = key[: -len("_from")]
        if not isinstance(reference, str) or reference not in features:
            raise CadError(f"{name}.{key}: expected a feature name, not {reference!r}")
        nominal = feature.get(f"{base}_nominal")
        if nominal is None:
            continue
        nominal = abs(_number(nominal, f"{name}.{base}_nominal"))
        if reference in shape.planes:
            index = shape.planes[reference]
            if name in shape.planes and shape.planes[name] != index:
                raise CadError(f"{name}.{key}: {reference} is not parallel")
        else:
            axis = feature.get(f"{base}_axis")
            if axis not in tuple(_AXES):
                raise CadError(f'{name}.{base}_axis: expected "x", "y" or "z"')
            index = _AXES.index(axis)
        mine = shape.positions.get(name, [None] * 3)[index]
        theirs = shape.positions.get(reference, [None] * 3)[index]
        if mine is None or theirs is None:
            raise CadError(f"{name}.{key}: no position along {_AXES[index]}")
        if abs(abs(mine - theirs) - nominal) > _TOLERANCE:
            raise CadError(
                f"{name}.{base}: the model puts it {abs(mine - theirs):.4f} mm from "
                f"{reference}, not its {nominal:g} mm nominal"
            )


def _inside(
    name: str, feature: dict, features: dict, values: dict, shape: _Shape
) -> None:
    """A hole's entry lies in the envelope and its largest diameter breaks out
    of neither the envelope's sides nor, along it, a turned outside."""
    at = shape.positions[name]
    index, _sign = _axis(feature["axis"], f"{name}.axis")
    radius = feature["dia"][1] / 2
    if feature.get("kind") == "threaded_hole":
        radius = max(radius, values[f"{name}_thread_major_mm"] / 2)
    for other in range(3):
        low, high = shape.low[other], shape.high[other]
        reach = 0.0 if other == index else radius
        if (
            at[other] - reach < low - _TOLERANCE
            or at[other] + reach > high + _TOLERANCE
        ):
            raise CadError(f"{name}: breaks out of the part along {_AXES[other]}")
    for outside, cylinder in features.items():
        if cylinder.get("kind") != "outside_cylinder":
            continue
        if _axis(cylinder["axis"], f"{outside}.axis")[0] != index:
            continue
        centre = shape.positions[outside]
        offset = math.hypot(*(at[i] - centre[i] for i in range(3) if i != index))
        wall = cylinder["dia"][0] / 2 - offset - radius
        if wall <= 0:
            raise CadError(f"{name}: breaks out of {outside} at the band extremes")
        _bind_mm(values, f"{name}_wall_to_{outside}_worst", wall)


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
    values["finish"] = _string(material.get("finish"), "cad.material.finish")
    _edge_breaks(raw, values)
    shape = _Shape()
    for name, feature in features.items():
        if not isinstance(feature, dict):
            raise CadError(f"cad.features.{name}: expected a table")
        kind = feature.get("kind")
        if not isinstance(kind, str) or not kind:
            raise CadError(f"{name}.kind: expected a kind")
        _bands(name, feature, values)
        if kind == "face":
            _face(name, feature, shape)
        elif kind in ("arc", "outside_cylinder"):
            _round(name, feature, shape, kind)
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
    for index, axis in enumerate(_AXES):
        low, high = shape.low[index], shape.high[index]
        if not high - low > 0:
            raise CadError(f"cad.features: no outside face or round bounds {axis}")
        _bind_mm(values, f"envelope_{axis}", high - low)
        _bind(values, f"{axis}_min_mm", low)
        _bind(values, f"{axis}_max_mm", high)
    for name, feature in features.items():
        _located(name, feature, features, shape)
        if feature["kind"] in _HOLES:
            if "into" in feature:
                _into(name, feature, features, values, shape)
            _inside(name, feature, features, values, shape)
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
