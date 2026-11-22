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
- `thru` must be true; any other true-or-false requirement (`flat_bottom`...)
  must be true and binds `F_R` true: the drawing prints a property the part
  has, never its absence;
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

A built-up part (plates bonded to a strap, say) is several blanks. The plan
may name `blank_groups = ["<g>", ...]`, each with `<g>_blank_features`, the
declared features cut from that blank. A grouped feature binds as any other,
but its planes and extents never widen the bar's envelope; the bar keeps at
least one feature of its own. A group's blank is sized either from its own
envelope, bounded on all three axes by its features' planes and extents and
read along `<g>_blank_length_axis` and `<g>_blank_thickness_axis` (binding
`<g>_envelope_<axis>_mm` and `<g>_envelope_<role>_axis`), or from
`<g>_blank_size_fields`, three `<feature>.<field>` requirements of its own
features in length, width, thickness order (a band's high end or a positive
number; never `finish_ra`, `plane`, `angle` or a `*_deg`/`*_angle` field),
for a feature that describes several alike pieces. Those fields are the
printed sizes of one piece: the group's modelled planes and extents, which
may span several pieces or the part they bond to, are not checked against
them. Either way it binds `<g>_envelope_<role>_mm`/`_in` and adds the stock
axes `<g> <role>` on `<g>_blank_<role>_in`; an optional `<g>_blank_count`
(identical pieces) binds as it is.
"""

import re
from collections.abc import Callable
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
_INF = float("inf")
# Requirements that are not a length a blank must cover.
_NOT_LENGTHS = {"finish_ra", "plane", "thru", "angle"}


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
    if isinstance(value, bool):
        if value is not True:
            raise CadError(f"{where}: expected true")
        _bind(values, prefix, True)
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
        # A unilateral fit (.3750 +.0015/+.0010) has its nominal size outside
        # its band; any other nominal lies in it.
        inside = band[0] - _TOLERANCE <= nominal <= band[1] + _TOLERANCE
        if key != "dia" and not inside:
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


# A consumer's own fields: which keys it claims, and how it binds one.
Claims = Callable[[str], bool]
BindClaimed = Callable[[dict, dict, str, str], None]


def _bind_feature(
    values: dict,
    features: dict,
    name: str,
    span: list | None,
    *,
    kinds: frozenset[str] | set[str] = _KINDS,
    bare_kinds: frozenset[str] = frozenset(),
    claims: Claims | None = None,
    bind_claimed: BindClaimed | None = None,
) -> None:
    """Bind one feature. `kinds` are the feature kinds accepted, `bare_kinds`
    those that may list no requirement. A key `claims` accepts (listed or
    not, its `_nominal` with it) binds through `bind_claimed`. With `span`
    None the part has no envelope: `extent_<axis>` is refused."""
    feature = features[name]
    if not _NAME.fullmatch(name):
        raise CadError(f"cad.features.{name}: expected a snake_case name")
    if (
        not isinstance(feature, dict)
        or feature.get("kind") not in kinds
        or feature.get("frame") != "model"
    ):
        raise CadError(f"{name}: expected a model-frame {', '.join(sorted(kinds))}")
    requirements = feature.get("requirements")
    if (
        not isinstance(requirements, list)
        or (not requirements and feature["kind"] not in bare_kinds)
        or not all(isinstance(key, str) for key in requirements)
    ):
        raise CadError(f"{name}.requirements: expected a nonempty list of names")
    if "plane" in feature:
        index, value = _plane_value(feature, name)
        _bind(values, f"{name}_plane_mm", value)
        if feature["kind"] == "face" and span is not None:
            _widen(span, index, value, value)
    elif "plane" in requirements:
        raise CadError(f"{name}.plane: missing drawing requirement")
    if feature["kind"] in ("hole", "threaded_hole"):
        for key in ("at", "axis"):
            if key not in feature:
                raise CadError(f"{name}.{key}: a hole needs its {key}")
    claimed = {key for key in feature if claims is not None and claims(key)}
    for key in requirements:
        if key in claimed:
            continue
        _requirement(values, feature, name, key)
    for key in sorted(claimed):
        bind_claimed(values, feature, name, key)
    # A listed or claimed band's nominal binds with it.
    nominals = {
        form.format(key)
        for key in (*requirements, *claimed)
        for form in ("{}_nominal", "nominal_{}")
    }
    for key, value in feature.items():
        if key in _SKIP or key in requirements or key in claimed or key in nominals:
            continue
        if key.endswith("_from") and (
            not isinstance(value, str) or value not in features
        ):
            raise CadError(f"{name}.{key}: {value!r} is not a declared feature")
        if key.startswith("extent_"):
            if span is None:
                raise CadError(f"{name}.{key}: this part binds no envelope")
            axis = key.removeprefix("extent_")
            if axis not in _AXES:
                raise CadError(f"{name}.{key}: expected extent_x, extent_y or extent_z")
            low, high = _band({"requirements": [key], key: value}, key, name)
            _widen(span, _AXES.index(axis), low, high)
            continue
        _field(values, name, key, value)


def _bar_axes(parameters: dict, prefix: str, what: str) -> tuple[int, int, int]:
    """The length, width and thickness model axes the plan names."""
    keys = (f"{prefix}blank_length_axis", f"{prefix}blank_thickness_axis")
    if not _all_or_none(parameters, keys, what):
        raise CadError(
            f"process: flat_bar needs {keys[0]} and {keys[1]} "
            "(0, 1, 2 for model X, Y, Z)"
        )
    length, thickness = (parameters[key] for key in keys)
    axes_ok = all(
        type(value) is int and value in (0, 1, 2) for value in (length, thickness)
    )
    if not axes_ok or length == thickness:
        raise CadError(
            f"process.{keys[0]}, {keys[1]}: expected two "
            "different model axes, 0, 1 or 2"
        )
    return length, 3 - length - thickness, thickness


def _blanks(
    values: dict, parameters: dict, prefix: str, sizes: list[tuple[float, str, str]]
) -> list[StockAxis]:
    """Bind each role's required size and authored blank; refuses a short blank.

    ``sizes`` holds, per role, the size in mm, its model axis (empty when the
    size is a field's) and where the size comes from, for the refusal."""
    axes = []
    for role, (size, axis, source) in zip(_ROLES, sizes, strict=True):
        _bind(values, f"{prefix}envelope_{role}_mm", size)
        _bind(values, f"{prefix}envelope_{role}_in", size / 25.4)
        if axis:
            _bind(values, f"{prefix}envelope_{role}_axis", axis)
        key = f"{prefix}blank_{role}_in"
        if key in parameters:
            blank = _positive(parameters[key], f"process.{key}")
            if blank * 25.4 < size - _TOLERANCE:
                raise CadError(
                    f"process.{key}: {blank:g} in is under the part's "
                    f"{size / 25.4:.4f} in {source}"
                )
            _bind(values, f"{prefix}blank_{role}_mm", blank * 25.4)
            _bind(values, f"{prefix}stock_{role}_in", blank - size / 25.4)
        name = f"{prefix.removesuffix('_')} {role}" if prefix else role
        axes.append(StockAxis(name, key, size))
    return axes


def _stock(values: dict, parameters: dict, sizes: list[float]) -> list[StockAxis]:
    """The stock axes along the bar the plan names; refuses a short blank."""
    indices = _bar_axes(parameters, "", "the bar's axes")
    return _blanks(
        values,
        parameters,
        "",
        [
            (sizes[index], _AXES[index].upper(), f"along model {_AXES[index].upper()}")
            for index in indices
        ],
    )


def _groups(parameters: dict, features: dict) -> tuple[list[str], dict[str, str]]:
    """The plan's blank groups and the group each grouped feature is cut in."""
    if "blank_groups" not in parameters:
        return [], {}
    groups = parameters["blank_groups"]
    if (
        not isinstance(groups, list)
        or not groups
        or not all(
            isinstance(group, str) and _NAME.fullmatch(group) for group in groups
        )
        or len(set(groups)) != len(groups)
    ):
        raise CadError(
            "process.blank_groups: expected a nonempty list of unique snake_case names"
        )
    owner: dict[str, str] = {}
    for group in groups:
        key = f"{group}_blank_features"
        names = parameters.get(key)
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(name, str) for name in names)
        ):
            raise CadError(f"process.{key}: expected a nonempty list of feature names")
        for name in names:
            if name not in features:
                raise CadError(f"process.{key}: {name!r} is not a declared feature")
            if name in owner:
                raise CadError(
                    f"process.{key}: {name} is already in blank group {owner[name]}"
                )
            owner[name] = group
    if len(owner) == len(features):
        raise CadError(
            "process.blank_groups: every feature is in a blank group; the bar "
            "keeps at least one of its own"
        )
    return groups, owner


def _size_field(
    features: dict, owner: dict, group: str, key: str, entry: object
) -> float:
    """The size in mm a `<feature>.<field>` names: a band's high end or a number."""
    name, dot, field = entry.partition(".") if isinstance(entry, str) else ("", "", "")
    if not dot or name not in features:
        raise CadError(f"process.{key}: {entry!r} names no declared feature's field")
    if owner.get(name) != group:
        raise CadError(f"process.{key}: {name} is not in blank group {group}")
    feature = features[name]
    if field not in feature.get("requirements", []) or field not in feature:
        raise CadError(f"process.{key}: {entry} is not a requirement {name} lists")
    if field in _NOT_LENGTHS or field.endswith(("_deg", "_angle")):
        raise CadError(f"process.{key}: {entry} is not a length")
    if isinstance(feature[field], list):
        return _positive(_band(feature, field, name)[1], f"{name}.{field}")
    return _positive(feature[field], f"{name}.{field}")


def _group_stock(
    values: dict,
    parameters: dict,
    features: dict,
    owner: dict,
    group: str,
    span: list,
) -> list[StockAxis]:
    """One blank group's required sizes and stock axes."""
    prefix = f"{group}_"
    count_key = f"{group}_blank_count"
    if count_key in parameters:
        count = parameters[count_key]
        if type(count) is not int or count < 1:
            raise CadError(f"process.{count_key}: expected a whole number, 1 or more")
        _bind(values, count_key, count)
    key = f"{group}_blank_size_fields"
    if key not in parameters:
        for axis, (low, high) in zip(_AXES, span, strict=True):
            if not low < high:
                raise CadError(
                    f"process.{group}_blank_features: no face plane or "
                    f"extent_{axis} bounds blank group {group} along {axis.upper()}"
                )
            _bind(values, f"{prefix}envelope_{axis}_mm", [low, high])
        indices = _bar_axes(parameters, prefix, f"blank group {group}'s axes")
        sizes = [
            (
                span[index][1] - span[index][0],
                _AXES[index].upper(),
                f"along model {_AXES[index].upper()} (blank group {group})",
            )
            for index in indices
        ]
        return _blanks(values, parameters, prefix, sizes)
    stray = [
        axis_key
        for axis_key in (f"{prefix}blank_length_axis", f"{prefix}blank_thickness_axis")
        if axis_key in parameters
    ]
    if stray:
        raise CadError(
            f"process.{key}: the fields size the blank; drop {', '.join(stray)}"
        )
    entries = parameters[key]
    if not isinstance(entries, list) or len(entries) != len(_ROLES):
        raise CadError(
            f"process.{key}: expected three <feature>.<field> names: length, "
            "width, thickness"
        )
    sizes = [
        (_size_field(features, owner, group, key, entry), "", f"of {entry}")
        for entry in entries
    ]
    return _blanks(values, parameters, prefix, sizes)


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
    groups, owner = _groups(parameters, features)
    span = [[_INF, -_INF] for _axis in _AXES]
    group_spans = {group: [[_INF, -_INF] for _axis in _AXES] for group in groups}
    for name in features:
        group = owner.get(name)
        _bind_feature(values, features, name, group_spans[group] if group else span)
    sizes = []
    for axis, (low, high) in zip(_AXES, span, strict=True):
        if not low < high:
            raise CadError(
                f"cad.features: no face plane or extent_{axis} bounds the part "
                f"along {axis.upper()}"
            )
        _bind(values, f"envelope_{axis}_mm", [low, high])
        sizes.append(high - low)
    if not parameters:
        return CadData(values, None, path.resolve())
    axes = _stock(values, parameters, sizes)
    for group in groups:
        axes += _group_stock(
            values, parameters, features, owner, group, group_spans[group]
        )
    return CadData(values, StockRequirement("in", tuple(axes)), path.resolve())
