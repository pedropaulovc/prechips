"""Bindings for a part milled from one length of flat or square bar.

The part is whatever its drawing declares: faces, bosses, profiles, holes,
notches and slots, each a model-frame feature whose `requirements` name its
printed bands. This adapter knows no layout. It binds every declared
requirement by its feature and field name, checks each band against its
nominal, checks that every `*_from` names a declared feature, and takes the
part's finished envelope from the declared planes and `extent_<axis>` spans.

Per feature `F` and listed requirement `R`:

- a two-number band binds `F_R_in`/`_min_in`/`_max_in`/`_band_mm` and
  `F_R_mm`, the nominal (`R_nominal` or `nominal_R`) when declared, else
  the band's middle; a declared nominal also binds `F_R_nominal_in`;
- `plane` binds `F_plane_mm` from the face's `plane` table;
- `thru` must be true; `process` binds `F_process`;
- `finish_ra` binds `F_finish_ra_um` and `F_finish_ra_uin`;
- any other single number (a `*_max` limit, a BASIC distance, a position
  zone) binds `F_R_mm` and `F_R_in`.

Other fields bind too: strings as `F_field`, `at` as `F_x_mm`/`_y_mm`/
`_z_mm` (and `_in`), other points as `F_field_x_mm`..., `axis` as `F_axis`
(`+X`...), lone numbers as `F_field_mm`/`_in` and string lists joined
with `|`.

The envelope is the union, per model axis, of every face's plane and every
`extent_<axis>` span ([low, high] mm, covered material). Its longest axis is
the blank's length, the shortest its thickness: the stock requirement reads
`blank_length_in`, `blank_width_in` and `blank_thickness_in`.
"""

import re
from pathlib import Path

from .cad import (
    _RA_UIN,
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _blank_mm,
    _edge_breaks,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
)

_KINDS = {"face", "boss", "profile", "hole", "notch", "slot"}
_AXES = ("x", "y", "z")
_NAME = re.compile(r"[a-z][a-z0-9_]*")
# Manifest bookkeeping and fields the requirement pass binds itself.
_SKIP = {"kind", "frame", "requirements", "cite", "faces", "precision", "plane"}
_TOLERANCE = 1e-6


def _nominal(feature: dict, key: str, where: str) -> float | None:
    for field in (f"{key}_nominal", f"nominal_{key}"):
        if field in feature:
            return _number(feature[field], f"{where}.{field}")
    return None


def _plane_value(feature: dict, where: str) -> tuple[int, float]:
    plane = feature.get("plane")
    if (
        not isinstance(plane, dict)
        or plane.get("frame") != "model"
        or plane.get("axis") not in _AXES
    ):
        raise CadError(f"{where}.plane: expected a model-frame plane on x, y or z")
    return _AXES.index(plane["axis"]), _number(plane.get("value"), f"{where}.plane")


def _point(value: object, where: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise CadError(f"{where}: expected an [x, y, z] point")
    return [_number(item, where) for item in value]


def _axis(value: object, where: str) -> str:
    vector = _point(value, where)
    nonzero = [index for index, item in enumerate(vector) if item]
    if len(nonzero) != 1 or abs(vector[nonzero[0]]) != 1.0:
        raise CadError(f"{where}: expected a unit model axis")
    index = nonzero[0]
    return ("+" if vector[index] > 0 else "-") + _AXES[index].upper()


def _requirement(values: dict, feature: dict, name: str, key: str) -> None:
    where = f"{name}.{key}"
    prefix = f"{name}_{key}"
    if key == "plane":
        return
    if key == "thru":
        if feature.get("thru") is not True:
            raise CadError(f"{where}: expected true")
        return
    if key == "process":
        values[prefix] = _string(feature.get(key), where)
        return
    value = feature.get(key)
    if key == "finish_ra":
        grade = _positive(value, where)
        if grade not in _RA_UIN:
            raise CadError(f"{where}: {grade:g} um is not a preferred Ra grade")
        values[f"{prefix}_um"] = grade
        values[f"{prefix}_uin"] = _RA_UIN[grade]
        return
    if isinstance(value, list):
        band = _band(feature, key, name)
        _inch_limits(values, prefix, band)
        nominal = _nominal(feature, key, name)
        if nominal is None:
            values[f"{prefix}_mm"] = band[0] / 2 + band[1] / 2
            return
        if not band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE:
            raise CadError(f"{where}: nominal {nominal:g} mm lies outside its band")
        values[f"{prefix}_mm"] = nominal
        values[f"{prefix}_nominal_in"] = nominal / 25.4
        return
    if value is None or key not in feature:
        raise CadError(f"{where}: missing drawing requirement")
    number = _positive(value, where)
    values[f"{prefix}_mm"] = number
    values[f"{prefix}_in"] = number / 25.4


def _field(values: dict, name: str, key: str, value: object) -> None:
    where = f"{name}.{key}"
    prefix = f"{name}_{key}"
    if isinstance(value, str):
        values[prefix] = _string(value, where)
    elif isinstance(value, bool):
        values[prefix] = value
    elif key == "axis":
        values[f"{name}_axis"] = _axis(value, where)
    elif key == "at" or (
        isinstance(value, list) and len(value) == 3 and key.endswith("_at")
    ):
        point = _point(value, where)
        head = name if key == "at" else prefix
        for axis, coordinate in zip(_AXES, point, strict=True):
            values[f"{head}_{axis}_mm"] = coordinate
            values[f"{head}_{axis}_in"] = coordinate / 25.4
    elif isinstance(value, list) and value and all(isinstance(i, str) for i in value):
        values[prefix] = "|".join(_string(item, where) for item in value)
    elif isinstance(value, list):
        values[f"{prefix}_mm"] = [_number(item, where) for item in value]
    else:
        number = _number(value, where)
        values[f"{prefix}_mm"] = number
        values[f"{prefix}_in"] = number / 25.4


def _bind_feature(values: dict, features: dict, name: str, span: list) -> None:
    feature = features[name]
    if not _NAME.fullmatch(name):
        raise CadError(f"cad.features.{name}: expected a snake_case name")
    if (
        not isinstance(feature, dict)
        or feature.get("kind") not in _KINDS
        or feature.get("frame") != "model"
    ):
        raise CadError(f"{name}: expected a model-frame {', '.join(sorted(_KINDS))}")
    requirements = feature.get("requirements")
    if (
        not isinstance(requirements, list)
        or not requirements
        or not all(isinstance(key, str) for key in requirements)
    ):
        raise CadError(f"{name}.requirements: expected a nonempty list of names")
    if "plane" in feature:
        index, value = _plane_value(feature, name)
        values[f"{name}_plane_mm"] = value
        span[index] = [min(span[index][0], value), max(span[index][1], value)]
    elif "plane" in requirements:
        raise CadError(f"{name}.plane: missing drawing requirement")
    if feature["kind"] == "hole":
        for key in ("at", "axis", "dia"):
            if key not in feature:
                raise CadError(f"{name}.{key}: a hole needs its {key}")
    for key in requirements:
        _requirement(values, feature, name, key)
    for key, value in feature.items():
        if key in _SKIP or key in requirements:
            continue
        if key.endswith("_from") and value not in features:
            raise CadError(f"{name}.{key}: {value!r} is not a declared feature")
        extent = key.removeprefix("extent_")
        if extent in _AXES:
            low, high = _band({"requirements": [key], key: value}, key, name)
            index = _AXES.index(extent)
            span[index] = [min(span[index][0], low), max(span[index][1], high)]
            continue
        _field(values, name, key, value)


def load_flat_bar(path: Path, parameters: dict, part: str) -> CadData:
    """Bind every declared feature's requirements, the envelope and, from
    authored parameters, the blank."""
    raw, values, features = _read_manifest(path, part, "flat_bar")
    _model_frame(raw)
    if not features:
        raise CadError("cad.features: expected at least one feature")
    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["material_spec"] = _string(material.get("spec"), "cad.material.spec")
    values["finish"] = _string(material.get("finish"), "cad.material.finish")
    general = _edge_breaks(raw, values)
    for places in (1, 2, 3):
        key = f"linear_{places}pl"
        values[f"tol_{key}_in"] = (
            _positive(general.get(key), f"general_tolerances.{key}") / 25.4
        )
    inf = float("inf")
    span = [[inf, -inf] for _axis in _AXES]
    for name in features:
        _bind_feature(values, features, name, span)
    extents = []
    for axis, (low, high) in zip(_AXES, span, strict=True):
        if not low < high:
            raise CadError(
                f"cad.features: no declared plane or extent_{axis} bounds the "
                f"part along {axis.upper()}"
            )
        values[f"envelope_{axis}_mm"] = [low, high]
        extents.append((high - low, axis))
    (thickness, thin), (width, mid), (length, long) = sorted(extents)
    for role, size, axis in (
        ("length", length, long),
        ("width", width, mid),
        ("thickness", thickness, thin),
    ):
        values[f"envelope_{role}_mm"] = size
        values[f"envelope_{role}_in"] = size / 25.4
        values[f"envelope_{role}_axis"] = axis.upper()
        if f"blank_{role}_in" in parameters:
            blank = _positive(
                parameters[f"blank_{role}_in"], f"process.blank_{role}_in"
            )
            values[f"stock_{role}_in"] = blank - size / 25.4
    _blank_mm(values, parameters)
    stock = StockRequirement(
        "in",
        (
            StockAxis("length", "blank_length_in", length),
            StockAxis("width", "blank_width_in", width),
            StockAxis("thickness", "blank_thickness_in", thickness),
        ),
    )
    return CadData(values, stock, path.resolve())
