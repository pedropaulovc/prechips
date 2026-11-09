"""Small, explicit bindings for the released harmonic base-bar drawing export."""

import math
import re
import tomllib
from dataclasses import dataclass
from fractions import Fraction
from html import escape
from pathlib import Path


class CadError(ValueError):
    """A CAD source or a named binding cannot supply a required value."""


@dataclass
class CadData:
    values: dict
    envelope_mm: tuple[float, float, float]
    source: Path


def _number(value: object, where: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise CadError(f"{where}: expected a finite number")
    return float(value)


def _positive(value: object, where: str) -> float:
    result = _number(value, where)
    if result <= 0:
        raise CadError(f"{where}: expected a positive number")
    return result


def _string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value == "unknown":
        raise CadError(f"{where}: expected a known nonempty string")
    return value


def _band(feature: dict, key: str, where: str) -> tuple[float, float]:
    requirements = feature.get("requirements")
    if not isinstance(requirements, list) or key not in requirements:
        raise CadError(f"{where}.{key}: missing drawing requirement")
    value = feature.get(key)
    if not isinstance(value, list) or len(value) != 2:
        raise CadError(f"{where}.{key}: expected a two-number requirement band")
    low, high = (_number(item, f"{where}.{key}") for item in value)
    if low > high:
        raise CadError(f"{where}.{key}: reversed requirement band")
    return low, high


def _mid(band: tuple[float, float]) -> float:
    return band[0] / 2 + band[1] / 2


def load_cad(path: Path, parameters: dict) -> CadData:
    """Normalize only the supported harmonic base-bar manifest, in physical mm."""
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if raw.get("units") != "mm":
        raise CadError("cad.units: harmonic_base_bar requires mm")
    if raw.get("part") != "ch-rocker-arm-tl-oblique-base-bar":
        raise CadError("cad.part: unsupported harmonic_base_bar part")
    features = raw.get("features")
    if not isinstance(features, dict):
        raise CadError("cad.features: expected a table")
    values = {"part": raw["part"]}
    drawing = raw.get("drawing", {})
    if not isinstance(drawing, dict):
        raise CadError("cad.drawing: expected a table")
    for key, source_key in (("drawing_number", "number"), ("revision", "revision")):
        values[key] = _string(drawing.get(source_key), f"cad.drawing.{source_key}")

    def feature(name: str) -> dict:
        result = features.get(name)
        if not isinstance(result, dict):
            raise CadError(f"cad.features.{name}: missing feature table")
        return result

    def limits(key: str, bands: list[tuple[float, float]]) -> None:
        if not bands or any(band != bands[0] for band in bands):
            raise CadError(f"cad.{key}: missing or inconsistent drawing limits")
        low, high = bands[0]
        if low <= 0:
            raise CadError(f"cad.{key}: expected positive drawing limits")
        values[f"{key}_in"] = _mid(bands[0]) / 25.4
        values[f"{key}_min_in"] = low / 25.4
        values[f"{key}_max_in"] = high / 25.4

    envelope = []
    for key, name, field in (
        ("length", "bar_far_end", "length"),
        ("width", "bar_high_side", "width"),
        ("thickness", "top_seat", "height"),
    ):
        item = feature(name)
        limits(key, [_band(item, field, name)])
        envelope.append(
            _positive(item.get(f"{field}_nominal"), f"{name}.{field}_nominal")
        )
    dimensions = ("length", "width", "thickness")
    halfbands = [
        (values[f"{key}_max_in"] - values[f"{key}_min_in"]) / 2 for key in dimensions
    ]
    if all(math.isclose(band, halfbands[0]) for band in halfbands):
        sizes = " × ".join(f"{values[f'{key}_in']:.2f}" for key in dimensions)
        values["size_summary"] = f"{sizes} (±{halfbands[0]:.2f} each)"
    else:
        values["size_summary"] = " × ".join(
            f"{values[f'{key}_in']:.2f} (±{band:.2f})"
            for key, band in zip(dimensions, halfbands)
        )
    general = raw.get("general_tolerances", {})
    if not isinstance(general, dict):
        raise CadError("cad.general_tolerances: expected a table")
    for key, source_key in (
        ("edge_break_in", "edge_break_r"),
        ("chamfer_max_in", "chamfer_max"),
    ):
        values[key] = (
            _positive(general.get(source_key), f"general_tolerances.{source_key}")
            / 25.4
        )
    finishes = []
    for name in ("top_seat", "underside_seat"):
        item = feature(name)
        if "finish_ra" not in item.get("requirements", []):
            raise CadError(f"{name}.finish_ra: missing drawing requirement")
        finishes.append(_positive(item.get("finish_ra"), f"{name}.finish_ra"))
    if finishes[0] != finishes[1]:
        raise CadError("cad.finish_ra_um: inconsistent seat requirements")
    values["finish_ra_um"] = finishes[0]

    def group(prefix: str, kind: str) -> list[tuple[str, dict]]:
        result = [
            (name, item)
            for name, item in features.items()
            if name.startswith(prefix)
            and isinstance(item, dict)
            and item.get("kind") == kind
        ]
        if not result:
            raise CadError(f"cad.features: missing {prefix} features")
        return result

    rails = group("rail_hole_", "threaded_hole")
    brackets = group("bracket_hole_", "hole")
    slots = [
        (name, item)
        for name, item in features.items()
        if isinstance(item, dict) and item.get("kind") == "slot"
    ]
    if not slots:
        raise CadError("cad.features: missing slots")

    def points(items: list[tuple[str, dict]]) -> list[list[float]]:
        result = []
        for name, item in items:
            if (
                item.get("height_from") != "bar_low_side"
                or item.get("thru") is not True
            ):
                raise CadError(
                    f"{name}: requires through geometry measured from bar_low_side"
                )
            result.append(
                [
                    _mid(_band(item, "station", name)) / 25.4,
                    -_mid(_band(item, "height", name)) / 25.4,
                ]
            )
        return sorted(result, key=lambda point: (point[0], -point[1]))

    rail_points = points(rails)
    bracket_points = points(brackets)
    values["rail_points_in"] = rail_points
    values["bracket_points_in"] = bracket_points
    values["rail_x_in"] = [point[0] for point in rail_points]
    values["rail_x_mm"] = [point[0] * 25.4 for point in rail_points]
    values["rail_stations_mm"] = ", ".join(
        f"{station:.2f}".rstrip("0").rstrip(".") for station in values["rail_x_mm"]
    )
    if len({point[1] for point in rail_points}) != 1:
        raise CadError("cad.rail_y_in: rail holes must share a drawing row")
    values["rail_y_in"] = rail_points[0][1]
    for key, items, field in (
        ("rail_position_tol", rails, "station"),
        ("rail_row_tol", rails, "height"),
        ("bracket_position_tol", brackets, "station"),
        ("slot_position_tol", slots, "station"),
    ):
        bands = [_band(item, field, name) for name, item in items]
        tolerances = [(high - low) / 2 for low, high in bands]
        if key in ("bracket_position_tol", "slot_position_tol"):
            tolerances.extend(
                (high - low) / 2
                for name, item in items
                for low, high in [_band(item, "height", name)]
            )
        values[f"{key}_in"] = min(tolerances) / 25.4
        if key == "rail_position_tol":
            values["rail_position_tol_mm"] = min(tolerances)
    limits("bracket_dia", [_band(item, "dia", name) for name, item in brackets])
    bracket_diameters = [
        _positive(item.get("dia_nominal"), f"{name}.dia_nominal")
        for name, item in brackets
    ]
    if len(set(bracket_diameters)) != 1:
        raise CadError("cad.bracket_dia_in: inconsistent nominal bracket diameters")
    values["bracket_dia_in"] = bracket_diameters[0] / 25.4
    counterbores = []
    for name, _ in brackets:
        counterbore_name = f"{name}_counterbore"
        item = feature(counterbore_name)
        if item.get("parent") != name:
            raise CadError(f"{counterbore_name}.parent: expected {name}")
        counterbores.append((counterbore_name, item))
    rail_diameters = [
        _positive(item.get("nominal_dia"), f"{name}.nominal_dia")
        for name, item in rails
    ]
    if len(set(rail_diameters)) != 1:
        raise CadError("cad.rail_dia_in: inconsistent nominal rail diameters")
    values["rail_dia_in"] = rail_diameters[0] / 25.4
    for field in ("dia", "depth"):
        limits(
            f"counterbore_{field}",
            [_band(item, field, name) for name, item in counterbores],
        )
    limits("slot_width", [_band(item, "width", name) for name, item in slots])
    limits("slot_spacing", [_band(item, "separation", name) for name, item in slots])
    shapes = []
    for name, item in slots:
        if item.get("height_from") != "bar_low_side" or item.get("thru") is not True:
            raise CadError(
                f"{name}: requires a through slot measured from bar_low_side"
            )
        near = -_mid(_band(item, "height", name)) / 25.4
        far = near - _mid(_band(item, "separation", name)) / 25.4
        shapes.append(
            {
                "x_in": _mid(_band(item, "station", name)) / 25.4,
                "near_y_in": near,
                "far_y_in": far,
                "mid_y_in": (near + far) / 2,
                "width_in": _mid(_band(item, "width", name)) / 25.4,
            }
        )
    shapes.sort(key=lambda shape: shape["x_in"])
    values["slot_shapes_in"] = shapes
    for key, prefix, count in (
        ("rail", "R", len(rails)),
        ("bracket", "B", len(brackets)),
        ("slot", "S", len(slots)),
    ):
        values[f"{key}_count"] = count
        values[f"{key}_range"] = (
            f"{prefix}1–{prefix}{count}" if count > 1 else f"{prefix}1"
        )
    values["spot_count"] = len(rails) + len(brackets) + len(slots)
    bracket_x = sorted({point[0] for point in bracket_points})
    bracket_y = sorted({point[1] for point in bracket_points}, reverse=True)
    if len(bracket_points) == len(bracket_x) * len(bracket_y):
        bracket_rows = [
            [
                f"Bracket {values['bracket_range']}",
                ", ".join(f"{x:.4f}" for x in bracket_x) + " (each X with all Y)",
                ", ".join(f"{y:.4f}" for y in bracket_y),
            ]
        ]
    else:
        bracket_rows = [
            [f"Bracket B{index}", f"{x:.4f}", f"{y:.4f}"]
            for index, (x, y) in enumerate(bracket_points, 1)
        ]
    values["hole_rows"] = (
        [
            [
                f"Rail {values['rail_range']}",
                ", ".join(f"{point[0]:.4f}" for point in rail_points),
                f"{values['rail_y_in']:.4f}",
            ]
        ]
        + bracket_rows
        + [
            [f"Slot S{index}", f"{shape['x_in']:.4f}", f"{shape['mid_y_in']:.4f}"]
            for index, shape in enumerate(shapes, 1)
        ]
    )
    values["slot_paths"] = "; ".join(
        f"X {shape['x_in']:.4f}, Y {shape['near_y_in']:.4f} to {shape['far_y_in']:.4f}"
        for shape in shapes
    )
    for key in ("width_rough_allowance_in", "slot_breakthrough_in"):
        if _number(parameters.get(key), f"process.{key}") < 0:
            raise CadError(f"process.{key}: expected a nonnegative allowance")
    step = _positive(parameters.get("slot_step_in"), "process.slot_step_in")
    values["width_rough_in"] = (
        values["width_in"] + parameters["width_rough_allowance_in"]
    )
    final_depth = values["thickness_in"] + parameters["slot_breakthrough_in"]
    if not math.isfinite(values["width_rough_in"]) or not math.isfinite(final_depth):
        raise CadError("process: nonfinite derived cutting target")
    if final_depth / step > 1000:
        raise CadError("process.slot_step_in: unusable slot depth increment")
    values["slot_depth_in"] = final_depth
    depths = [
        index * step
        for index in range(1, math.ceil(final_depth / step))
        if index * step < final_depth
    ]
    values["slot_depths_in"] = "/".join(
        f"{depth:.2f}" for depth in [*depths, final_depth]
    )
    return CadData(values, tuple(envelope), path.resolve())


_TOKEN = re.compile(
    r"\{\{(cad|process|view)\.([A-Za-z_][A-Za-z_0-9]*)(?::([^{}]+))?\}\}"
)
_FORMAT = re.compile(r"(?:[+ -])?(?:[1-9][0-9]?)?(?:\.[0-9])?[fge%]|d")


def _lookup(
    match: re.Match, cad: CadData, parameters: dict, extra: dict | None
) -> object:
    namespace, key, _ = match.groups()
    source = {
        "cad": cad.values,
        "process": parameters,
        "view": (extra or {}).get("view", {}),
    }[namespace]
    if key not in source:
        raise CadError(f"unknown binding {namespace}.{key}")
    return source[key]


def bind_text(
    text: str,
    cad: CadData,
    parameters: dict,
    *,
    extra: dict | None = None,
    xml: bool = False,
) -> str:
    """Substitute bounded named scalar tokens, without evaluating expressions."""

    def replace(match: re.Match) -> str:
        value = _lookup(match, cad, parameters, extra)
        spec = match[3]
        if type(value) in (int, float):
            _number(value, match[0])
            if spec == "fraction":
                fraction = Fraction(str(value)).limit_denominator(64)
                if float(fraction) != value:
                    result = str(value)
                else:
                    whole, numerator = divmod(
                        abs(fraction.numerator), fraction.denominator
                    )
                    result = (
                        ("-" if value < 0 else "")
                        + (
                            f"{whole} "
                            if whole and numerator
                            else str(whole)
                            if whole or not numerator
                            else ""
                        )
                        + (f"{numerator}/{fraction.denominator}" if numerator else "")
                    )
            elif spec:
                if not _FORMAT.fullmatch(spec) or (spec == "d" and value != int(value)):
                    raise CadError(f"{match[0]}: unsupported numeric format")
                result = format(int(value) if spec == "d" else value, spec)
            else:
                result = str(value)
        elif isinstance(value, str) and spec is None:
            result = value
        else:
            raise CadError(
                f"{match[0]}: expected a scalar or a whole-field list binding"
            )
        return escape(result, quote=True) if xml else result

    # Check authored syntax before substitution; source strings are never reinterpreted.
    remainder = _TOKEN.sub("", text)
    if "{{" in remainder or "}}" in remainder:
        raise CadError(f"malformed or unknown binding in {text!r}")
    return _TOKEN.sub(replace, text)


def bind_data(value: object, cad: CadData, parameters: dict) -> object:
    """Bind authored strings and exact whole-field list tokens recursively."""
    if isinstance(value, str):
        token = _TOKEN.fullmatch(value)
        if token and token[3] is None:
            result = _lookup(token, cad, parameters, None)
            if isinstance(result, list):
                return result
        return bind_text(value, cad, parameters)
    if isinstance(value, list):
        return [bind_data(item, cad, parameters) for item in value]
    if isinstance(value, dict):
        return {key: bind_data(item, cad, parameters) for key, item in value.items()}
    return value
