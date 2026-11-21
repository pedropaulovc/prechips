"""Bindings for a part milled from one length of flat or square bar.

The part is whatever its drawing declares: faces, bosses, profiles, holes,
threaded holes, notches and slots, each a model-frame feature whose
`requirements` name its printed values. This adapter knows no layout. It
binds every declared value by its feature and field name, checks each band
against its nominal, checks that every `*_from` names a declared feature,
and takes the part's finished envelope from the declared face planes and
`extent_<axis>` spans. Every binding is new: a feature/field pair that joins
to a key already bound (another feature's, or the loader's own) refuses.

Per feature `F` and listed requirement `R`:

- a two-number band binds `F_R_in`/`_min_in`/`_max_in`/`_band_mm` and
  `F_R_mm`, the nominal (`R_nominal` or `nominal_R`) when declared, refused
  outside the band, else the band's middle; a nominal also binds
  `F_R_nominal_in`;
- `plane` binds `F_plane_mm` from the feature's `plane` table;
- `thru` must be true;
- `finish_ra` binds `F_finish_ra_um` and `F_finish_ra_uin`;
- a string (`process`, `thread`...) binds `F_R`; a point as below; any
  other single number (a `*_max` limit, a BASIC distance, a position zone)
  binds `F_R_mm` and `F_R_in`.

Other fields bind too: strings as `F_field`; `axis` as `F_axis` (`+X`...);
every three-number point (`at`, `tip_at`...) as `F_field_x_mm`/`_y_mm`/
`_z_mm` and `_in`; a two-number list as `F_field_band_mm`; a lone number
as `F_field_mm`/`_in`; string lists joined with `|`. `extent_<axis>` spans
are not bound: they only widen the envelope.

The envelope is the union, per model axis, of every face's plane and every
`extent_<axis>` span ([low, high] mm, covered material). The plan names
the bar's axes, `blank_length_axis` and `blank_thickness_axis` (0, 1, 2 for
model X, Y, Z; width is the third): the stock requirement then reads
`blank_length_in`, `blank_width_in` and `blank_thickness_in` along them.
"""

import re
from pathlib import Path

from .cad import (
    _RA_UIN,
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _all_or_none,
    _band,
    _edge_breaks,
    _mid,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
)

_KINDS = {"face", "boss", "profile", "hole", "threaded_hole", "notch", "slot"}
_AXES = ("x", "y", "z")
_ROLES = ("length", "width", "thickness")
_NAME = re.compile(r"[a-z][a-z0-9_]*")
# Manifest bookkeeping and fields the requirement pass binds itself.
_SKIP = {"kind", "frame", "requirements", "cite", "faces", "precision", "plane"}
_TOLERANCE = 1e-6


def _bind(values: dict, key: str, value: object) -> None:
    """Bind one new key; a key already bound is a name collision."""
    if key in values:
        raise CadError(f"cad.{key}: bound twice (feature and field names collide)")
    values[key] = value


def _limits(values: dict, key: str, band: tuple[float, float]) -> None:
    """`_inch_limits` for any band, a location from a datum included."""
    _bind(values, f"{key}_in", _mid(band) / 25.4)
    _bind(values, f"{key}_min_in", band[0] / 25.4)
    _bind(values, f"{key}_max_in", band[1] / 25.4)
    _bind(values, f"{key}_band_mm", [band[0], band[1]])


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


def _is_point(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(type(item) in (int, float) for item in value)
    )


def _point(values: dict, prefix: str, value: list, where: str) -> None:
    for axis, item in zip(_AXES, value, strict=True):
        coordinate = _number(item, where)
        _bind(values, f"{prefix}_{axis}_mm", coordinate)
        _bind(values, f"{prefix}_{axis}_in", coordinate / 25.4)


def _axis(value: object, where: str) -> str:
    if not _is_point(value):
        raise CadError(f"{where}: expected a unit model axis")
    nonzero = [index for index, item in enumerate(value) if item]
    if len(nonzero) != 1 or abs(value[nonzero[0]]) != 1.0:
        raise CadError(f"{where}: expected a unit model axis")
    index = nonzero[0]
    return ("+" if value[index] > 0 else "-") + _AXES[index].upper()


def _number_binding(values: dict, prefix: str, value: object, where: str) -> None:
    number = _number(value, where)
    _bind(values, f"{prefix}_mm", number)
    _bind(values, f"{prefix}_in", number / 25.4)


def _requirement(values: dict, feature: dict, name: str, key: str) -> None:
    where = f"{name}.{key}"
    prefix = f"{name}_{key}"
    if key == "plane":
        return
    if key.startswith("extent_"):
        raise CadError(f"{where}: an extent widens the envelope; it is not printed")
    if key not in feature:
        raise CadError(f"{where}: missing drawing requirement")
    value = feature[key]
    if key == "thru":
        if value is not True:
            raise CadError(f"{where}: expected true")
        return
    if key == "finish_ra":
        grade = _positive(value, where)
        if grade not in _RA_UIN:
            raise CadError(f"{where}: {grade:g} um is not a preferred Ra grade")
        _bind(values, f"{prefix}_um", grade)
        _bind(values, f"{prefix}_uin", _RA_UIN[grade])
        return
    if isinstance(value, str):
        _bind(values, prefix, _string(value, where))
        return
    if _is_point(value):
        _point(values, prefix, value, where)
        return
    if isinstance(value, list):
        band = _band(feature, key, name)
        _limits(values, prefix, band)
        nominal = _nominal(feature, key, name)
        if nominal is None:
            _bind(values, f"{prefix}_mm", _mid(band))
            return
        if not band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE:
            raise CadError(f"{where}: nominal {nominal:g} mm lies outside its band")
        _bind(values, f"{prefix}_mm", nominal)
        _bind(values, f"{prefix}_nominal_in", nominal / 25.4)
        return
    _number_binding(values, prefix, value, where)


def _field(values: dict, name: str, key: str, value: object) -> None:
    where = f"{name}.{key}"
    prefix = f"{name}_{key}"
    if isinstance(value, str):
        _bind(values, prefix, _string(value, where))
    elif isinstance(value, bool):
        _bind(values, prefix, value)
    elif key == "axis":
        _bind(values, prefix, _axis(value, where))
    elif _is_point(value):
        _point(values, prefix, value, where)
    elif isinstance(value, list) and value and all(isinstance(i, str) for i in value):
        _bind(values, prefix, "|".join(_string(item, where) for item in value))
    elif isinstance(value, list):
        if len(value) != 2:
            raise CadError(f"{where}: expected a point, a band or strings")
        _bind(values, f"{prefix}_band_mm", [_number(item, where) for item in value])
    else:
        _number_binding(values, prefix, value, where)


def _widen(span: list, index: int, low: float, high: float) -> None:
    span[index] = [min(span[index][0], low), max(span[index][1], high)]


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
        _bind(values, f"{name}_plane_mm", value)
        if feature["kind"] == "face":
            _widen(span, index, value, value)
    elif "plane" in requirements:
        raise CadError(f"{name}.plane: missing drawing requirement")
    if feature["kind"] in ("hole", "threaded_hole"):
        for key in ("at", "axis"):
            if key not in feature:
                raise CadError(f"{name}.{key}: a hole needs its {key}")
    for key in requirements:
        _requirement(values, feature, name, key)
    # A listed band's nominal binds with it.
    nominals = {f"{key}_nominal" for key in requirements} | {
        f"nominal_{key}" for key in requirements
    }
    for key, value in feature.items():
        if key in _SKIP or key in requirements or key in nominals:
            continue
        if key.endswith("_from") and (
            not isinstance(value, str) or value not in features
        ):
            raise CadError(f"{name}.{key}: {value!r} is not a declared feature")
        if key.startswith("extent_"):
            axis = key.removeprefix("extent_")
            if axis not in _AXES:
                raise CadError(f"{name}.{key}: expected extent_x, extent_y or extent_z")
            low, high = _band({"requirements": [key], key: value}, key, name)
            _widen(span, _AXES.index(axis), low, high)
            continue
        _field(values, name, key, value)


def _stock(values: dict, parameters: dict, sizes: list[float]) -> StockRequirement:
    """The stock axes along the bar the plan names; refuses a short blank."""
    keys = ("blank_length_axis", "blank_thickness_axis")
    if not _all_or_none(parameters, keys, "the bar's axes"):
        raise CadError(
            "process: flat_bar needs blank_length_axis and blank_thickness_axis "
            "(0, 1, 2 for model X, Y, Z)"
        )
    length, thickness = (parameters[key] for key in keys)
    if length not in (0, 1, 2) or thickness not in (0, 1, 2) or length == thickness:
        raise CadError(
            "process.blank_length_axis, blank_thickness_axis: expected two "
            "different model axes, 0, 1 or 2"
        )
    width = 3 - length - thickness
    axes = []
    for role, index in zip(_ROLES, (length, width, thickness), strict=True):
        size = sizes[index]
        _bind(values, f"envelope_{role}_mm", size)
        _bind(values, f"envelope_{role}_in", size / 25.4)
        _bind(values, f"envelope_{role}_axis", _AXES[index].upper())
        key = f"blank_{role}_in"
        if key in parameters:
            blank = _positive(parameters[key], f"process.{key}")
            if blank * 25.4 < size - _TOLERANCE:
                raise CadError(
                    f"process.{key}: {blank:g} in is under the part's "
                    f"{size / 25.4:.4f} in along model {_AXES[index].upper()}"
                )
            _bind(values, f"blank_{role}_mm", blank * 25.4)
            _bind(values, f"stock_{role}_in", blank - size / 25.4)
        axes.append(StockAxis(role, key, size))
    return StockRequirement("in", tuple(axes))


def load_flat_bar(path: Path, parameters: dict, part: str) -> CadData:
    """Bind every declared feature's values, the envelope and, from authored
    parameters, the bar's axes and the blank."""
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
    sizes = []
    for axis, (low, high) in zip(_AXES, span, strict=True):
        if not low < high:
            raise CadError(
                f"cad.features: no face plane or extent_{axis} bounds the part "
                f"along {axis.upper()}"
            )
        _bind(values, f"envelope_{axis}_mm", [low, high])
        sizes.append(high - low)
    stock = _stock(values, parameters, sizes) if parameters else None
    return CadData(values, stock, path.resolve())
