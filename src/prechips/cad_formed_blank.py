"""Bindings for a part cut from one straight length of strip, wire or tube and
formed at the bench.

The part is whatever its drawing declares, as with `flat_bar`: faces,
bosses, profiles, holes, threaded holes, notches and slots bind by feature
and field name through `flat_bar`'s feature binder, given the two added
kinds:

- `bend`: one formed bend. It carries exactly one of `radius` (to the inside
  surface) or `centreline_radius`, each a positive band or number bound as
  declared (no conversion between them), and a positive `angle` in degrees,
  under 360.
- `blank`: the straight developed blank, exactly one. `section` names its
  cross-section: `"strip"` (`width`, `thickness`), `"round"` (`dia`) or
  `"tube"` (`od`, `wall`); `developed_length` is its length through every
  bend. Each size is a positive number in mm, or a band with its
  `<size>_nominal` inside it. An optional `k_factor` lies in 0 to 0.5.

Angles are degrees: a field named `angle` or ending `_deg`, listed in
`requirements` or not, binds as `F_angle_deg` (a band also as `_min_deg`,
`_max_deg` and `_band_deg`, the nominal or else the band's middle as
`F_angle_deg`). A `k_factor` binds as the plain number `F_k_factor`. Every
other field binds as in `flat_bar`.

Each bend also binds `F_allowance_mm`/`_in`, the arc length it takes of the
developed blank at its nominal angle on its neutral line: the centreline
radius as declared (a band at its nominal, else its middle); else the inside
radius plus the blank's `k_factor` times its thickness (strip; none without
a `k_factor`) or plus half its section (round, tube). The developed length
itself is the manifest's, never summed.

A formed part's model envelope is not its stock, so this adapter binds none
(`extent_<axis>` is refused): the stock requirement is the blank's developed
length and section, read from the plan's `blank_length_in` and, by section,
`blank_width_in` and `blank_thickness_in`, `stock_dia_in`, or `stock_od_in`
and `stock_wall_in`. The length and a strip's width are cut down, so the
stock may exceed them, binding the excess as `length_allowance_in` and
`width_allowance_in`; a thickness, diameter, O.D. or wall is formed as
bought and must match the blank (inside its band, or equal). Each declared
stock size binds as `<parameter>` in mm (`blank_length_mm`, `stock_dia_mm`...).
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
    _TOLERANCE,
    _bind,
    _bind_feature,
    _nominal,
)

_FORMED_KINDS = _KINDS | {"bend", "blank"}
_RADII = ("radius", "centreline_radius")
# A section given as one number matches stock within .001 in, as turned_bush's
# size left as bought does.
_AS_BOUGHT = 0.0254
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


def _listed_band(value: object, key: str, name: str) -> tuple[float, float]:
    """A two-number band checked as declared, listed in `requirements` or not."""
    return _band({"requirements": [key], key: value}, key, name)


def _in_band(nominal: float, band: tuple[float, float], where: str) -> None:
    if not band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE:
        raise CadError(f"{where}: nominal {nominal:g} lies outside its band")


def _angle(values: dict, feature: dict, name: str, key: str) -> None:
    """Bind an angle in degrees, a band or a single number."""
    where = f"{name}.{key}"
    base = f"{name}_{key.removesuffix('_deg')}"
    value = feature[key]
    if isinstance(value, list):
        band = _listed_band(value, key, name)
        nominal = _nominal(feature, key, name)
        if nominal is not None:
            _in_band(nominal, band, where)
        _bind(values, f"{base}_deg", _mid(band) if nominal is None else nominal)
        _bind(values, f"{base}_min_deg", band[0])
        _bind(values, f"{base}_max_deg", band[1])
        _bind(values, f"{base}_band_deg", [band[0], band[1]])
        return
    number = _number(value, where)
    nominal = _nominal(feature, key, name)
    if nominal is not None and abs(nominal - number) > _TOLERANCE:
        raise CadError(f"{where}: nominal {nominal:g} deg is not the angle {number:g}")
    _bind(values, f"{base}_deg", number)


def _claims(key: str) -> bool:
    """Angles and the K-factor; a `nominal_*` or `*_nominal` spelling is its
    field's nominal, read with that field, never an angle of its own."""
    if key.startswith("nominal_") or key.endswith("_nominal"):
        return False
    return _is_angle(key) or key == "k_factor"


def _bind_claimed(values: dict, feature: dict, name: str, key: str) -> None:
    if key == "k_factor":
        _bind(values, f"{name}_k_factor", _number(feature[key], f"{name}.{key}"))
    else:
        _angle(values, feature, name, key)


def _limits_of(feature: dict, key: str, name: str) -> tuple[float, float]:
    """A positive size or angle as (low, high): a number twice, or its band
    with any declared nominal inside it."""
    value = feature[key]
    if isinstance(value, list):
        band = _listed_band(value, key, name)
        nominal = _nominal(feature, key, name)
        if nominal is not None:
            _in_band(nominal, band, f"{name}.{key}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        band = (float(value), float(value))
    else:
        raise CadError(f"{name}.{key}: expected a number or a two-number band")
    if band[0] <= 0.0:
        raise CadError(f"{name}.{key}: expected a positive value")
    return band


def _check_kind(feature: dict, name: str) -> None:
    kind = feature.get("kind") if isinstance(feature, dict) else None
    if kind == "bend":
        radii = [key for key in _RADII if key in feature]
        if len(radii) != 1:
            raise CadError(
                f"{name}: a bend needs exactly one of radius (inside) or "
                "centreline_radius"
            )
        _limits_of(feature, radii[0], name)
        if "angle" not in feature:
            raise CadError(f"{name}.angle: a bend needs its angle")
        if _limits_of(feature, "angle", name)[1] >= 360.0:
            raise CadError(f"{name}.angle: expected under 360 deg")
    if kind == "blank":
        section = feature.get("section")
        if section not in _SECTIONS:
            raise CadError(f"{name}.section: expected strip, round or tube")
        for key in ("developed_length", *(size for size, *_ in _SECTIONS[section])):
            if key not in feature:
                raise CadError(f"{name}.{key}: a {section} blank needs its {key}")
            _limits_of(feature, key, name)
        if "k_factor" in feature:
            k = _number(feature["k_factor"], f"{name}.k_factor")
            if not 0.0 <= k <= 0.5:
                raise CadError(f"{name}.k_factor: expected 0 to 0.5")


def _bind_formed(values: dict, features: dict, name: str) -> None:
    """flat_bar's binder with the bend and blank kinds, a blank that may list
    no requirement, angles and the K-factor bound here, and no envelope."""
    _check_kind(features[name], name)
    _bind_feature(
        values,
        features,
        name,
        None,
        kinds=_FORMED_KINDS,
        bare_kinds=frozenset({"blank"}),
        claims=_claims,
        bind_claimed=_bind_claimed,
    )


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
    """The blank's developed length and section against the declared stock.
    The length and a strip's width are cut down to size, so the stock may be
    over them (the excess binds as `<role>_allowance_in`); a thickness, wire
    diameter, tube O.D. or wall is formed as bought, so the stock must match
    it: inside its band, or equal to a single number."""
    rows = [("length", "blank_length_in", "developed_length")]
    rows += [
        (role, parameter, key) for key, role, parameter in _SECTIONS[blank["section"]]
    ]
    axes = []
    for role, parameter, key in rows:
        cut_down = role in ("length", "width")
        if cut_down:
            required = _size(blank, key, name)
        else:
            low, high = _limits_of(blank, key, name)
            if low == high:
                low, high = low - _AS_BOUGHT, high + _AS_BOUGHT
            # stock_fit reads the least size the adapter accepts.
            required = low
        if parameter in parameters:
            declared = _positive(parameters[parameter], f"process.{parameter}")
            declared_mm = declared * 25.4
            if cut_down:
                if declared_mm < required - _TOLERANCE:
                    raise CadError(
                        f"process.{parameter}: {declared:g} in is under the blank's "
                        f"{role} {required / 25.4:.4f} in"
                    )
                _bind(values, f"{role}_allowance_in", declared - required / 25.4)
            elif not low - _TOLERANCE <= declared_mm <= high + _TOLERANCE:
                raise CadError(
                    f"process.{parameter}: {declared:g} in is not the blank's "
                    f"{role} {low / 25.4:.5f}-{high / 25.4:.5f} in; it is formed "
                    "as bought"
                )
            _bind(values, f"{parameter.removesuffix('_in')}_mm", declared_mm)
        axes.append(StockAxis(role, parameter, required))
    return StockRequirement("in", tuple(axes))


def _allowance(
    values: dict, bend: dict, name: str, blank: dict, blank_name: str
) -> None:
    """`F_allowance_mm`/`_in`: the arc length one bend takes of the developed
    blank, at its nominal angle, on its neutral line: the declared
    centreline radius; else the inside radius plus the blank's `k_factor` x
    thickness for strip (none bound without a `k_factor`), or half the
    section for round and tube. A banded radius counts at its declared
    nominal, else its band's middle."""
    angle = math.radians(values[f"{name}_angle_deg"])
    key = "centreline_radius" if "centreline_radius" in bend else "radius"
    radius = values.get(f"{name}_{key}_mm")
    if radius is None:
        radius = _nominal(bend, key, name)
    if radius is None:
        radius = _mid(_limits_of(bend, key, name))
    if key == "centreline_radius":
        neutral = radius
    else:
        inside = radius
        section = blank["section"]
        if section == "strip":
            if "k_factor" not in blank:
                return
            k = _number(blank["k_factor"], f"{blank_name}.k_factor")
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
        _bind_formed(values, features, name)
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
