"""Bindings for a built-up part: a turned hub joined through a flat strap, its
bore and its hub length finished after joining.

The drawing describes the finished part and must permit the built-up
construction (`construction = "built_up_permitted"`). The two members arrive
made: the strap at its finished thickness, the hub with its outside at the
finished size and its length and bore left with stock. The traveler joins
them, then drills the bore through the hub and faces each hub end. The
manifest names its features; the adapter finds the members by kind and
geometry, never by name:

- the hub: the one `boss`, along a model axis (`at`, `axis`, a `dia` band);
- the bore: the one `hole` on the hub's axis (parallel, its `at` on the
  axis), through;
- the hub's length across its two ends: the one feature listing `length`,
  a band with `length_nominal`;
- the strap's thickness: every feature listing `thickness`, all one band
  with one `thickness_nominal`;
- strap holes: every other `hole` or `threaded_hole`, parallel to the hub's
  axis and through.

Every feature also binds by feature and field as in `flat_bar` (its binder,
imported unchanged), with any kind accepted and no envelope; angles (`angle`
or `*_deg`) bind in degrees as in `formed_blank`; a field written true binds
`F_field` true; a table field (a note on how a zone governs a size, say) is
not printed and binds nothing.

The members bind as `hub_dia_*`, `bore_dia_*` (and `bore_drill` when the
bore names its drill), `hub_length_*` and `strap_thickness_*`
(`_in`/`_min_in`/`_max_in`/`_band_mm`, the nominal as `_mm`). Derived:

- `hub_end_height_mm`/`_in`: half the hub's nominal length less the strap's
  nominal thickness, each hub end's height over its own strap face. Facing
  both ends to it from their own faces centres the strap on the hub and
  makes the length twice it plus the strap; across the strap's thickness band
  that must stay inside the length band, else refused;
- `bore_depth_mm`/`_in`: the hub's nominal length, the bore's run;
- per strap hole `H`: `H_from_bore_<a>_mm`/`_in` along each of the two model
  axes square to the hub's, and `H_from_bore_mm`/`_in`, its distance from the
  bore's axis.

The plan states the members as made (inches): `hub_land_min_in` and
`hub_land_max_in`, the hub's outside as turned, refused unless inside the
hub's `dia` band (it is not cut again); `hub_supply_length_min_in` and
`hub_supply_length_max_in`, its length as supplied; `bond_offset_max_in`, how
far off the hub's middle the joint may leave the strap. Each end's facing
depth binds as `face_depth_min_mm`/`_max_mm` (and `_in`), from the shortest
hub with the thickest strap and the joint's offset toward that end, to the
longest with the thinnest and the offset away; a depth of zero or less
refuses (the end would not clean up). `hub_end_supply_max_mm`/`_in` is the
highest an unfaced end stands over its strap face. The `stock_fit`
requirement is the hub's supplied length (`hub_supply_length_min_in`) over
the hub's longest finished length.
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
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
)
from .cad_flat_bar import _bind, _bind_feature
from .cad_formed_blank import _angle, _is_angle

_AXES = "xyz"
_HOLES = ("hole", "threaded_hole")
# Model agreement: the members' axes and points come from the same CAD values.
_TOLERANCE = 1e-3
_SUPPLY = (
    "hub_land_min_in",
    "hub_land_max_in",
    "hub_supply_length_min_in",
    "hub_supply_length_max_in",
    "bond_offset_max_in",
)


class _AnyKind(frozenset):
    """Every feature kind binds: the members are found by geometry."""

    def __contains__(self, kind: object) -> bool:
        return isinstance(kind, str) and bool(kind)


def _claims_for(feature: dict):
    def claims(key: str) -> bool:
        if key.startswith("nominal_") or key.endswith("_nominal"):
            return False
        value = feature.get(key)
        return _is_angle(key) or value is True or isinstance(value, dict)

    return claims


def _bind_claimed(values: dict, feature: dict, name: str, key: str) -> None:
    value = feature[key]
    if isinstance(value, dict):
        return
    if value is True:
        if key != "thru":
            _bind(values, f"{name}_{key}", True)
        return
    _angle(values, feature, name, key)


def _unit_axis(value: object, where: str) -> tuple[int, int]:
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


def _nominal_band(
    feature: dict, key: str, name: str
) -> tuple[tuple[float, float], float]:
    """A listed band and its declared nominal, which must lie inside it."""
    band = _band(feature, key, name)
    nominal = _positive(feature.get(f"{key}_nominal"), f"{name}.{key}_nominal")
    if not band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE:
        raise CadError(f"{name}.{key}_nominal: {nominal:g} mm lies outside its band")
    return band, nominal


def _listing(features: dict, key: str) -> list[str]:
    return [
        name
        for name, feature in features.items()
        if key in feature.get("requirements", ())
    ]


def _hub(features: dict) -> tuple[str, int, list[float]]:
    bosses = [name for name, f in features.items() if f.get("kind") == "boss"]
    if len(bosses) != 1:
        raise CadError("cad.features: expected exactly one boss, the hub")
    name = bosses[0]
    index, _sign = _unit_axis(features[name].get("axis"), f"{name}.axis")
    return name, index, _point(features[name].get("at"), f"{name}.at")


def _off_axis(point: list[float], at: list[float], index: int) -> list[float]:
    """The point's offset from the hub's axis, its axial component zeroed."""
    return [0.0 if i == index else point[i] - at[i] for i in range(3)]


def _bore(features: dict, index: int, at: list[float]) -> tuple[str, list[str]]:
    """The one hole on the hub's axis; the other holes are the strap's."""
    bores, others = [], []
    for name, feature in features.items():
        if feature.get("kind") not in _HOLES:
            continue
        axis, _sign = _unit_axis(feature.get("axis"), f"{name}.axis")
        if axis != index:
            raise CadError(f"{name}.axis: expected parallel to the hub's axis")
        if feature.get("thru") is not True:
            raise CadError(f"{name}.thru: expected a through hole")
        offset = _off_axis(_point(feature.get("at"), f"{name}.at"), at, index)
        (bores if math.hypot(*offset) <= _TOLERANCE else others).append(name)
    if len(bores) != 1 or features[bores[0]].get("kind") != "hole":
        raise CadError(
            "cad.features: expected exactly one plain hole on the hub's axis"
        )
    return bores[0], others


def _thickness(features: dict) -> tuple[tuple[float, float], float]:
    names = _listing(features, "thickness")
    if not names:
        raise CadError("cad.features: expected the strap's thickness")
    bands = {_nominal_band(features[name], "thickness", name) for name in names}
    if len(bands) != 1:
        raise CadError(f"{', '.join(names)}: the strap's thickness disagrees")
    return bands.pop()


def _length(features: dict) -> tuple[tuple[float, float], float]:
    names = _listing(features, "length")
    if len(names) != 1:
        raise CadError("cad.features: expected exactly one hub length")
    return _nominal_band(features[names[0]], "length", names[0])


def _supply(
    values: dict,
    parameters: dict,
    dia: tuple[float, float],
    length: tuple[float, float],
    thickness: tuple[float, float],
    height: float,
) -> None:
    """The members as made: the land in the hub's band, each end's facing."""
    missing = [key for key in _SUPPLY if key not in parameters]
    if missing:
        raise CadError(f"process: joined_hub needs {', '.join(missing)}")
    mm = {key: _number(parameters[key], f"process.{key}") * 25.4 for key in _SUPPLY}
    land = (mm["hub_land_min_in"], mm["hub_land_max_in"])
    if not dia[0] <= land[0] <= land[1] <= dia[1]:
        raise CadError(
            "process.hub_land_*: the turned land lies outside the hub's band"
        )
    _inch_limits(values, "hub_land", land)
    short, long = mm["hub_supply_length_min_in"], mm["hub_supply_length_max_in"]
    offset = mm["bond_offset_max_in"]
    if long < short or offset < 0:
        raise CadError("process: expected a supplied length band and an offset ≥ 0")
    if short < length[1]:
        raise CadError("process.hub_supply_length_min_in: under the finished length")
    least = (short - thickness[1]) / 2 - offset - height
    most = (long - thickness[0]) / 2 + offset - height
    if least <= 0:
        raise CadError(
            "process: the shortest hub, offset by the joint, leaves an end "
            "that facing does not clean up"
        )
    for key, value in (
        ("face_depth_min", least),
        ("face_depth_max", most),
        ("hub_end_supply_max", most + height),
    ):
        _bind(values, f"{key}_mm", value)
        _bind(values, f"{key}_in", value / 25.4)


def load_joined_hub(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the members, the finishing heights and the strap holes' offsets."""
    raw, values, features = _read_manifest(path, part, "joined_hub")
    _model_frame(raw)
    if raw.get("construction") != "built_up_permitted":
        raise CadError("cad.construction: the drawing does not permit a built-up part")
    if not features:
        raise CadError("cad.features: expected the part's features")
    for name, feature in features.items():
        if not isinstance(feature, dict):
            raise CadError(f"cad.features.{name}: expected a table")
        _bind_feature(
            values,
            features,
            name,
            None,
            kinds=_AnyKind(),
            claims=_claims_for(feature),
            bind_claimed=_bind_claimed,
        )
    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["material_spec"] = _string(material.get("spec"), "cad.material.spec")
    values["material_name"] = _string(material.get("name"), "cad.material.name")
    values["finish"] = _string(material.get("finish"), "cad.material.finish")
    _edge_breaks(raw, values)

    hub, index, at = _hub(features)
    bore, holes = _bore(features, index, at)
    dia = _band(features[hub], "dia", hub)
    _inch_limits(values, "hub_dia", dia)
    bore_dia = _band(features[bore], "dia", bore)
    _inch_limits(values, "bore_dia", bore_dia)
    if bore_dia[1] >= dia[0]:
        raise CadError(f"{bore}: the bore is not inside the hub")
    if "drill" in features[bore]:
        _bind(values, "bore_drill", _string(features[bore]["drill"], f"{bore}.drill"))
    length, length_nominal = _length(features)
    thickness, thickness_nominal = _thickness(features)
    _inch_limits(values, "hub_length", length)
    _bind(values, "hub_length_mm", length_nominal)
    _inch_limits(values, "strap_thickness", thickness)
    _bind(values, "strap_thickness_mm", thickness_nominal)
    height = (length_nominal - thickness_nominal) / 2
    if height <= 0:
        raise CadError("cad.features: the hub is not longer than the strap is thick")
    if not (
        length[0] - _TOLERANCE <= 2 * height + thickness[0]
        and 2 * height + thickness[1] <= length[1] + _TOLERANCE
    ):
        raise CadError(
            "cad.features: facing each hub end from its own strap face leaves "
            "the length band across the strap's thickness band"
        )
    for key, value in (("hub_end_height", height), ("bore_depth", length_nominal)):
        _bind(values, f"{key}_mm", value)
        _bind(values, f"{key}_in", value / 25.4)
    plane = [i for i in range(3) if i != index]
    for name in holes:
        offset = _off_axis(_point(features[name]["at"], f"{name}.at"), at, index)
        for i in plane:
            _bind(values, f"{name}_from_bore_{_AXES[i]}_mm", offset[i])
            _bind(values, f"{name}_from_bore_{_AXES[i]}_in", offset[i] / 25.4)
        distance = math.hypot(*offset)
        _bind(values, f"{name}_from_bore_mm", distance)
        _bind(values, f"{name}_from_bore_in", distance / 25.4)
    _supply(values, parameters, dia, length, thickness, height)
    stock = (StockAxis("hub length", "hub_supply_length_min_in", length[1]),)
    return CadData(values, StockRequirement("in", stock), path.resolve())
