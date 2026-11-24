"""Bindings for a built-up part: a turned hub joined through a flat strap, its
bore and its hub length finished after joining.

The drawing describes the finished part and must permit the built-up
construction (`construction = "built_up_permitted"`). The two members arrive
made: the strap at its finished thickness, the hub with its outside at the
finished size and its length and bore left with stock. The traveler joins
them, then drills the bore through the hub and faces each hub end. The
manifest names its features; the adapter finds the members by kind,
geometry and requirement, never by feature name:

- the hub: the one `boss`, along a model axis (`at`, `axis`, a `dia` band);
- the bore: the one `hole` on the hub's axis (parallel, its `at` on the
  axis), through;
- the hub's length across its two ends: the one feature listing `length`
  (a drawing that prints another `length` is refused), a band with its
  nominal (`length_nominal` or `nominal_length`);
- the strap's thickness: every feature listing `thickness`, all one band
  with one nominal;
- strap holes: every other `hole` or `threaded_hole`, parallel to the hub's
  axis, through and wholly outside the hub's largest diameter.

Every feature also binds by feature and field as in `flat_bar` (its binder,
imported unchanged), with any kind accepted and no envelope; angles (`angle`
or `*_deg`) bind in degrees as in `formed_blank`; a field written true binds
`F_field` true, listed or not (a drawing statement with no number, such as a
mirror-symmetric outline); a table field not listed (a note on how a zone
governs a size, say) binds nothing, and a listed one is refused.

The members bind as `hub_dia_*`, `bore_dia_*` (and `bore_drill` when the
bore names its drill), `hub_length_*` and `strap_thickness_*`
(`_in`/`_min_in`/`_max_in`/`_band_mm`, the declared nominal, else the
band's middle, as `_mm`). Derived:

- `hub_end_height_mm`/`_in`: each hub end's height over its own strap face,
  the .001 in reading the sheet prints. Facing both ends to it from their
  own faces centres the strap on the hub and makes the length twice it plus
  the strap, so it must keep that inside the length band across the strap's
  thickness band: of the readings that do, the one nearest half the hub's
  nominal length less the strap's nominal thickness, the lower on a tie;
  refused when none does;
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
    _model_frame,
    _number,
    _read_manifest,
    _string,
    inch_thread,
)
from .cad_flat_bar import _axis, _bind, _bind_feature, _is_point, _limits, _nominal
from .cad_formed_blank import _angle, _is_angle

_AXES = "xyz"
_HOLES = ("hole", "threaded_hole")
# Model agreement: the members' axes and points come from the same CAD values.
_TOLERANCE = 1e-3
# Inch-to-millimetre conversion noise in the supply checks.
_NOISE = 1e-9
_INCH_READING = 0.0254
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
        if isinstance(value, dict):
            # A malformed list is the binder's to refuse; never claim for it.
            listed = feature.get("requirements")
            return isinstance(listed, list) and key not in listed
        return _is_angle(key) or value is True

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
    axis = _axis(value, where)
    return _AXES.index(axis[1].lower()), 1 if axis[0] == "+" else -1


def _point(value: object, where: str) -> list[float]:
    if not _is_point(value):
        raise CadError(f"{where}: expected a model point [x, y, z]")
    return [float(item) for item in value]


def _nominal_in(
    feature: dict, key: str, name: str, band: tuple[float, float]
) -> float | None:
    """The declared nominal, inside its band except a diameter's: a
    unilateral fit's nominal size lies outside its band, as in `flat_bar`."""
    nominal = _nominal(feature, key, name)
    if (
        nominal is not None
        and key != "dia"
        and not band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE
    ):
        raise CadError(
            f"{name}.{key}: its nominal {nominal:g} mm lies outside its band"
        )
    return nominal


def _member(
    values: dict, feature: dict, key: str, name: str, prefix: str
) -> tuple[float, float]:
    """A member's listed band, bound as `<prefix>_*` with its declared nominal
    (else the band's middle) as `<prefix>_mm`."""
    band = _band(feature, key, name)
    nominal = _nominal_in(feature, key, name, band)
    _limits(values, prefix, band)
    _bind(
        values, f"{prefix}_mm", (band[0] + band[1]) / 2 if nominal is None else nominal
    )
    return band


def _declared(feature: dict, key: str, name: str) -> tuple[tuple[float, float], float]:
    """A listed band and its declared positive nominal, inside it."""
    band = _band(feature, key, name)
    nominal = _nominal_in(feature, key, name, band)
    if nominal is None or nominal <= 0:
        raise CadError(f"{name}.{key}: expected its positive nominal")
    return band, nominal


def _hole_radius(feature: dict, name: str) -> float:
    """A strap hole's largest radius: its `dia` (a band's high end or one
    number, listed or not), else its thread's basic major."""
    dia = feature.get("dia")
    if isinstance(dia, list) and dia:
        return max(_number(item, f"{name}.dia") for item in dia) / 2
    if dia is not None:
        return _number(dia, f"{name}.dia") / 2
    if isinstance(feature.get("thread"), str):
        return inch_thread(feature["thread"], f"{name}.thread")[0] / 2
    raise CadError(f"{name}: a strap hole states no size (dia or thread)")


def _listing(features: dict, key: str) -> list[str]:
    return [
        name
        for name, feature in features.items()
        if isinstance(feature.get("requirements"), list)
        and key in feature["requirements"]
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


def _bore(
    features: dict, index: int, at: list[float], hub_radius: float
) -> tuple[str, list[str]]:
    """The one hole on the hub's axis; the other holes are the strap's, each
    wholly outside the hub's largest diameter."""
    bores, others, cutting = [], [], []
    for name, feature in features.items():
        if feature.get("kind") not in _HOLES:
            continue
        axis, _sign = _unit_axis(feature.get("axis"), f"{name}.axis")
        if axis != index:
            raise CadError(f"{name}.axis: expected parallel to the hub's axis")
        if feature.get("thru") is not True:
            raise CadError(f"{name}.thru: expected a through hole")
        distance = math.hypot(
            *_off_axis(_point(feature.get("at"), f"{name}.at"), at, index)
        )
        if distance <= _TOLERANCE:
            bores.append(name)
        elif distance - _hole_radius(feature, name) <= hub_radius:
            cutting.append(name)
        else:
            others.append(name)
    if len(bores) != 1 or features[bores[0]].get("kind") != "hole":
        off = f" ({', '.join(cutting)} lies off it, inside the hub)" if cutting else ""
        raise CadError(
            f"cad.features: expected exactly one plain hole on the hub's axis{off}"
        )
    if cutting:
        raise CadError(f"{', '.join(cutting)}: a strap hole cutting into the hub")
    return bores[0], others


def _thickness(features: dict) -> tuple[tuple[float, float], float]:
    names = _listing(features, "thickness")
    if not names:
        raise CadError("cad.features: expected the strap's thickness")
    bands = {_declared(features[name], "thickness", name) for name in names}
    if len(bands) != 1:
        raise CadError(f"{', '.join(names)}: the strap's thickness disagrees")
    return bands.pop()


def _length(features: dict) -> tuple[tuple[float, float], float]:
    names = _listing(features, "length")
    if len(names) != 1:
        raise CadError(
            "cad.features: expected exactly one feature listing a length, the hub's"
        )
    return _declared(features[names[0]], "length", names[0])


def _end_height(
    length: tuple[float, float], thickness: tuple[float, float], exact: float
) -> float:
    """The .001 in reading (mm) the sheet prints for each end's height over
    its strap face: of the readings that keep twice it plus the strap's
    thickness band inside the length band, the nearest ``exact``, the lower
    on a tie; refused when no reading does."""
    low = (length[0] - thickness[0]) / 2 / _INCH_READING
    high = (length[1] - thickness[1]) / 2 / _INCH_READING
    readings = range(math.ceil(low - 1e-6), math.floor(high + 1e-6) + 1)
    if not readings:
        raise CadError(
            "cad.features: facing each hub end from its own strap face to a "
            ".001 in height leaves the length band across the strap's "
            "thickness band"
        )
    target = exact / _INCH_READING
    best = min(readings, key=lambda k: (round(abs(k - target), 6), k))
    return best * _INCH_READING


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
    if not dia[0] - _NOISE <= land[0] <= land[1] <= dia[1] + _NOISE:
        raise CadError(
            "process.hub_land_*: the turned land lies outside the hub's band"
        )
    _limits(values, "hub_land", land)
    short, long = mm["hub_supply_length_min_in"], mm["hub_supply_length_max_in"]
    offset = mm["bond_offset_max_in"]
    if long < short or offset < 0:
        raise CadError("process: expected a supplied length band and an offset ≥ 0")
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
        kind = feature.get("kind")
        if feature.get("frame") != "model" or not isinstance(kind, str) or not kind:
            raise CadError(f"{name}: expected a model-frame feature with a kind")
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
    dia = _member(values, features[hub], "dia", hub, "hub_dia")
    bore, holes = _bore(features, index, at, dia[1] / 2)
    bore_dia = _member(values, features[bore], "dia", bore, "bore_dia")
    if bore_dia[1] >= dia[0]:
        raise CadError(f"{bore}: the bore is not inside the hub")
    if "drill" in features[bore]:
        _bind(values, "bore_drill", _string(features[bore]["drill"], f"{bore}.drill"))
    length, length_nominal = _length(features)
    thickness, thickness_nominal = _thickness(features)
    _limits(values, "hub_length", length)
    _bind(values, "hub_length_mm", length_nominal)
    _limits(values, "strap_thickness", thickness)
    _bind(values, "strap_thickness_mm", thickness_nominal)
    exact = (length_nominal - thickness_nominal) / 2
    if exact <= 0:
        raise CadError("cad.features: the hub is not longer than the strap is thick")
    height = _end_height(length, thickness, exact)
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
