"""Bindings for a part cut from one straight length of strip, wire or tube and
formed at the bench.

The part is whatever its drawing declares, as with `flat_bar`: faces,
bosses, profiles, holes, threaded holes, notches and slots bind by feature
and field name through `flat_bar`'s binders. Two kinds are added:

- `bend`: one formed bend. It carries exactly one of `radius` (to the inside
  surface) or `centreline_radius`, each a band or a number bound as declared
  (no conversion between them), and an `angle` in degrees.
- `blank`: the straight developed blank, exactly one. `section` names its
  cross-section: `"strip"` (`width`, `thickness`), `"round"` (`dia`) or
  `"tube"` (`od`, `wall`); `developed_length` is its length through every
  bend. Each size is a number in mm, or a band with its `<size>_nominal`.

Angles are degrees: a field named `angle` or ending `_deg` binds as
`F_angle_deg` (a band also as `_min_deg`, `_max_deg` and `_band_deg`, the
nominal or else the band's middle as `F_angle_deg`). A `k_factor` binds as
the plain number `F_k_factor`. Every other field binds as in `flat_bar`.

Each bend also binds `F_allowance_mm`/`_in`, the arc length it takes of the
developed blank at its nominal angle on its neutral line: the centreline
radius as declared; else the inside radius plus the blank's `k_factor` times
its thickness (strip; none without a `k_factor`) or plus half its section
(round, tube). The developed length itself is the manifest's, never summed.

A formed part's model envelope is not its stock, so this adapter binds none:
the stock requirement is the blank's developed length and section, read
from the plan's `blank_length_in` and, by section, `blank_width_in` and
`blank_thickness_in`, `stock_dia_in`, or `stock_od_in` and `stock_wall_in`.
Each declared stock size also binds as `<parameter>` in mm (`blank_length_mm`,
`stock_dia_mm`...) and its allowance over the blank as `<role>_allowance_in`.
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
)
from .cad_flat_bar import (
    _KINDS,
    _NAME,
    _SKIP,
    _TOLERANCE,
    _bind,
    _field,
    _nominal,
    _plane_value,
    _requirement,
)

_FORMED_KINDS = _KINDS | {"bend", "blank"}
_RADII = ("radius", "centreline_radius")
# Section: its size fields, each with its stock role and plan parameter.
_SECTIONS = {
    "strip": (
        ("width", "width", "blank_width_in"),
        ("thickness", "thickness", "blank_thickness_in"),
    ),
    "round": (("dia", "diameter", "stock_dia_in"),),
    "tube": (
        ("od", "outside diameter", "stock_od_in"),
        ("wall", "wall", "stock_wall_in"),
    ),
}


def _is_angle(key: str) -> bool:
    return key == "angle" or key.endswith("_deg")


def _angle(values: dict, feature: dict, name: str, key: str) -> None:
    """Bind an angle in degrees, a band or a single number."""
    where = f"{name}.{key}"
    base = f"{name}_{key.removesuffix('_deg')}"
    value = feature[key]
    if isinstance(value, list):
        band = _band(feature, key, name)
        nominal = _nominal(feature, key, name)
        if nominal is not None and not (
            band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE
        ):
            raise CadError(f"{where}: nominal {nominal:g} deg lies outside its band")
        _bind(values, f"{base}_deg", _mid(band) if nominal is None else nominal)
        _bind(values, f"{base}_min_deg", band[0])
        _bind(values, f"{base}_max_deg", band[1])
        _bind(values, f"{base}_band_deg", [band[0], band[1]])
        return
    _bind(values, f"{base}_deg", _number(value, where))


def _check_kind(feature: dict, name: str) -> None:
    kind = feature["kind"]
    if kind in ("hole", "threaded_hole"):
        for key in ("at", "axis"):
            if key not in feature:
                raise CadError(f"{name}.{key}: a hole needs its {key}")
    if kind == "bend":
        radii = [key for key in _RADII if key in feature]
        if len(radii) != 1:
            raise CadError(
                f"{name}: a bend needs exactly one of radius (inside) or "
                "centreline_radius"
            )
        if "angle" not in feature:
            raise CadError(f"{name}.angle: a bend needs its angle")
    if kind == "blank":
        section = feature.get("section")
        if section not in _SECTIONS:
            raise CadError(f"{name}.section: expected strip, round or tube")
        for key in ("developed_length", *(size for size, *_ in _SECTIONS[section])):
            if key not in feature:
                raise CadError(f"{name}.{key}: a {section} blank needs its {key}")


def _bind_feature(values: dict, features: dict, name: str) -> None:
    feature = features[name]
    if not _NAME.fullmatch(name):
        raise CadError(f"cad.features.{name}: expected a snake_case name")
    if (
        not isinstance(feature, dict)
        or feature.get("kind") not in _FORMED_KINDS
        or feature.get("frame") != "model"
    ):
        raise CadError(
            f"{name}: expected a model-frame {', '.join(sorted(_FORMED_KINDS))}"
        )
    requirements = feature.get("requirements")
    if not isinstance(requirements, list) or not all(
        isinstance(key, str) for key in requirements
    ):
        raise CadError(f"{name}.requirements: expected a list of names")
    if not requirements and feature["kind"] != "blank":
        raise CadError(f"{name}.requirements: expected a nonempty list of names")
    _check_kind(feature, name)
    if "plane" in feature:
        _bind(values, f"{name}_plane_mm", _plane_value(feature, name)[1])
    elif "plane" in requirements:
        raise CadError(f"{name}.plane: missing drawing requirement")
    angles = {key for key in feature if _is_angle(key)}
    nominals = {
        form.format(key)
        for key in (*requirements, *angles)
        for form in ("{}_nominal", "nominal_{}")
    }
    for key in requirements:
        if key not in feature and key != "plane":
            raise CadError(f"{name}.{key}: missing drawing requirement")
        if key in angles:
            _angle(values, feature, name, key)
        elif key == "k_factor":
            _bind(values, f"{name}_k_factor", _number(feature[key], f"{name}.{key}"))
        else:
            _requirement(values, feature, name, key)
    for key, value in feature.items():
        if key in _SKIP or key in requirements or key in nominals:
            continue
        if key.endswith("_from") and (
            not isinstance(value, str) or value not in features
        ):
            raise CadError(f"{name}.{key}: {value!r} is not a declared feature")
        if key.startswith("extent_"):
            raise CadError(f"{name}.{key}: a formed part binds no envelope")
        if key in angles:
            _angle(values, feature, name, key)
        elif key == "k_factor":
            _bind(values, f"{name}_k_factor", _number(value, f"{name}.{key}"))
        else:
            _field(values, name, key, value)


def _size(feature: dict, key: str, name: str) -> float:
    """One blank size in mm: a number, or a band's declared nominal."""
    value = feature[key]
    if isinstance(value, list):
        nominal = _nominal(feature, key, name)
        if nominal is None:
            raise CadError(f"{name}.{key}: a banded blank size needs its nominal")
        return _positive(nominal, f"{name}.{key}_nominal")
    return _positive(value, f"{name}.{key}")


def _stock(values: dict, parameters: dict, blank: dict, name: str) -> StockRequirement:
    """The blank's developed length and section against the declared stock."""
    rows = [("length", "blank_length_in", _size(blank, "developed_length", name))]
    for key, role, parameter in _SECTIONS[blank["section"]]:
        rows.append((role, parameter, _size(blank, key, name)))
    axes = []
    for role, parameter, required in rows:
        if parameter in parameters:
            declared = _positive(parameters[parameter], f"process.{parameter}")
            if declared * 25.4 < required - _TOLERANCE:
                raise CadError(
                    f"process.{parameter}: {declared:g} in is under the blank's "
                    f"{role} {required / 25.4:.4f} in"
                )
            _bind(values, f"{parameter.removesuffix('_in')}_mm", declared * 25.4)
            allowance = f"{role.replace(' ', '_')}_allowance_in"
            _bind(values, allowance, declared - required / 25.4)
        axes.append(StockAxis(role, parameter, required))
    return StockRequirement("in", tuple(axes))


def _allowance(
    values: dict, bend: dict, name: str, blank: dict, blank_name: str
) -> None:
    """`F_allowance_mm`/`_in`: the arc length one bend takes of the developed
    blank, at its nominal angle, on its neutral line: the declared
    centreline radius; else the inside radius plus the blank's `k_factor` x
    thickness for strip (none bound without a `k_factor`), or half the
    section for round and tube."""
    angle = math.radians(values[f"{name}_angle_deg"])
    key = "centreline_radius" if "centreline_radius" in bend else "radius"
    radius = values.get(f"{name}_{key}_mm")
    if radius is None:
        radius = _mid(tuple(values[f"{name}_{key}_band_mm"]))
    if key == "centreline_radius":
        neutral = radius
    else:
        inside = radius
        section = blank["section"]
        if section == "strip":
            if "k_factor" not in blank:
                return
            k = _number(blank["k_factor"], f"{blank_name}.k_factor")
            if not 0.0 <= k <= 0.5:
                raise CadError(f"{blank_name}.k_factor: expected 0 to 0.5")
            neutral = inside + k * _size(blank, "thickness", blank_name)
        else:
            key = "dia" if section == "round" else "od"
            neutral = inside + _size(blank, key, blank_name) / 2.0
    _bind(values, f"{name}_allowance_mm", angle * neutral)
    _bind(values, f"{name}_allowance_in", angle * neutral / 25.4)


def load_formed_blank(path: Path, parameters: dict, part: str) -> CadData:
    """Bind every declared feature's values and, from authored parameters,
    the stock against the developed blank."""
    raw, values, features = _read_manifest(path, part, "formed_blank")
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
    values["tol_angular_deg"] = _positive(
        general.get("angular_deg"), "general_tolerances.angular_deg"
    )
    for name in features:
        _bind_feature(values, features, name)
    blanks = [
        name
        for name, feature in features.items()
        if isinstance(feature, dict) and feature.get("kind") == "blank"
    ]
    if len(blanks) != 1:
        raise CadError("cad.features: expected exactly one blank feature")
    blank = features[blanks[0]]
    for name, feature in features.items():
        if feature["kind"] == "bend":
            _allowance(values, feature, name, blank, blanks[0])
    stock = _stock(values, parameters, blank, blanks[0]) if parameters else None
    return CadData(values, stock, path.resolve())
