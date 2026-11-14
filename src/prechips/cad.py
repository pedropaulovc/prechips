"""Small, explicit bindings for supported harmonic part manifests."""

import math
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from html import escape
from pathlib import Path


class CadError(ValueError):
    """A CAD source or a named binding cannot supply a required value."""


# ASME B46.1 preferred roughness averages: micrometres to microinches.
_RA_UIN = {0.4: 16, 0.8: 32, 1.6: 63, 3.2: 125, 6.3: 250}


@dataclass
class StockAxis:
    """One declared stock parameter and the size it must cover along one axis."""

    name: str
    parameter: str
    required_mm: float


@dataclass
class StockRequirement:
    """Declared stock axes, each read from `parameters` in `unit` ("in" or "mm")."""

    unit: str
    axes: tuple[StockAxis, ...]
    label: str = "CAD requires"


@dataclass
class CadData:
    values: dict
    stock_requirement: StockRequirement | None
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


def _inch_limits(values: dict, key: str, band: tuple[float, float]) -> None:
    """Bind one positive drawing band as `<key>_in`/`_min_in`/`_max_in`/`_band_mm`."""
    low, high = band
    if low <= 0:
        raise CadError(f"cad.{key}: expected positive drawing limits")
    values[f"{key}_in"] = _mid(band) / 25.4
    values[f"{key}_min_in"] = low / 25.4
    values[f"{key}_max_in"] = high / 25.4
    values[f"{key}_band_mm"] = [low, high]


def _model_frame(raw: dict) -> None:
    """Require the identity model frame the harmonic jig adapters read."""
    frames = raw.get("frames")
    model = frames.get("model") if isinstance(frames, dict) else None
    if not isinstance(model, dict) or any(
        model.get(key) != expected
        for key, expected in (
            ("origin", [0, 0, 0]),
            ("x", [1, 0, 0]),
            ("y", [0, 1, 0]),
            ("z", [0, 0, 1]),
        )
    ):
        raise CadError("cad.frames.model: expected the identity model frame")


def _harmonic_manifest(path: Path, part: str, adapter: str) -> tuple[dict, dict, dict]:
    """Read one mm manifest for `part`: raw table, drawing identity and features."""
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if raw.get("units") != "mm" or raw.get("part") != part:
        raise CadError(f"cad: {adapter} requires {part} in mm")
    drawing = raw.get("drawing", {})
    if not isinstance(drawing, dict):
        raise CadError("cad.drawing: expected a table")
    values = {
        "part": part,
        "drawing_number": _string(drawing.get("number"), "cad.drawing.number"),
        "revision": _string(drawing.get("revision"), "cad.drawing.revision"),
    }
    features = raw.get("features")
    if not isinstance(features, dict):
        raise CadError("cad.features: expected a table")
    return raw, values, features


def _edge_breaks(raw: dict, values: dict) -> dict:
    """Bind the title-block edge break in inches; return the tolerance table."""
    general = raw.get("general_tolerances", {})
    if not isinstance(general, dict):
        raise CadError("cad.general_tolerances: expected a table")
    for key, field in (
        ("edge_break_in", "edge_break_r"),
        ("chamfer_max_in", "chamfer_max"),
    ):
        values[key] = (
            _positive(general.get(field), f"general_tolerances.{field}") / 25.4
        )
    return general


def _blank_mm(values: dict, parameters: dict) -> None:
    """Analysis fields are millimetres; plans declare their blanks in inches."""
    for key in ("length", "width", "thickness"):
        if f"blank_{key}_in" in parameters:
            values[f"blank_{key}_mm"] = parameters[f"blank_{key}_in"] * 25.4


def load_cad(path: Path, parameters: dict, adapter: str) -> CadData:
    """Dispatch a required, explicit part adapter without guessing from the source."""
    if adapter == "harmonic_base_bar":
        return _load_base_bar(path, parameters)
    if adapter == "harmonic_pivot_shaft":
        from prechips.cad_shaft import load_shaft

        return load_shaft(path, parameters)
    if adapter == "harmonic_pivot_bracket":
        from prechips.cad_bracket import load_bracket

        return load_bracket(path, parameters)
    if adapter == "harmonic_rocker_arm":
        from prechips.cad_rocker import load_rocker

        return load_rocker(path, parameters)
    if adapter == "harmonic_end_bracket":
        from prechips.cad_end_bracket import load_end_bracket

        return load_end_bracket(path, parameters)
    if adapter == "harmonic_feed_lever":
        from prechips.cad_feed_lever import load_feed_lever

        return load_feed_lever(path, parameters)
    if adapter == "harmonic_riser":
        from prechips.cad_riser import load_riser

        return load_riser(path, parameters)
    if adapter == "harmonic_leadscrew_kit":
        from prechips.cad_leadscrew_kit import load_leadscrew_kit

        return load_leadscrew_kit(path, parameters)
    if adapter == "harmonic_carrier":
        from prechips.cad_carrier import load_carrier

        return load_carrier(path, parameters)
    raise CadError(f"cad.adapter: unsupported adapter {adapter!r}")


def point_columns(
    points: list,
) -> list[tuple[int, list]]:
    """Group consecutive equal-X points; return (first ID number, points)."""
    columns: list[tuple[int, list]] = []
    for index, point in enumerate(points, start=1):
        if columns and math.isclose(columns[-1][1][0][0], point[0], abs_tol=1e-6):
            columns[-1][1].append(point)
        else:
            columns.append((index, [point]))
    return columns


def id_range(prefix: str, first: int, count: int) -> str:
    if count == 1:
        return f"{prefix}{first}"
    return f"{prefix}{first}–{prefix}{first + count - 1}"


def _load_base_bar(path: Path, parameters: dict) -> CadData:
    """Normalize only the supported harmonic base-bar manifest, in physical mm."""
    raw, values, features = _harmonic_manifest(
        path, "ch-rocker-arm-tl-oblique-base-bar", "harmonic_base_bar"
    )

    def feature(name: str) -> dict:
        result = features.get(name)
        if not isinstance(result, dict):
            raise CadError(f"cad.features.{name}: missing feature table")
        return result

    def limits(key: str, bands: list[tuple[float, float]]) -> None:
        if not bands or any(band != bands[0] for band in bands):
            raise CadError(f"cad.{key}: missing or inconsistent drawing limits")
        _inch_limits(values, key, bands[0])

    envelope = []
    for key, name, field in (
        ("length", "bar_far_end", "length"),
        ("width", "bar_high_side", "width"),
        ("thickness", "top_seat", "height"),
    ):
        item = feature(name)
        limits(key, [_band(item, field, name)])
        nominal = _positive(item.get(f"{field}_nominal"), f"{name}.{field}_nominal")
        envelope.append(StockAxis(key, f"blank_{key}_in", nominal))
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
    general = _edge_breaks(raw, values)
    values["angular_tol_deg"] = _positive(
        general.get("angular_deg"), "general_tolerances.angular_deg"
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
    # The inch drawing prints the ASME B46.1 preferred microinch value.
    if finishes[0] not in _RA_UIN:
        raise CadError("cad.finish_ra_uin: no preferred microinch Ra for this value")
    values["finish_ra_uin"] = _RA_UIN[finishes[0]]

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
    slots.sort(key=lambda slot: _mid(_band(slot[1], "station", slot[0])))
    threads = {_string(item.get("thread"), f"{name}.thread") for name, item in rails}
    if len(threads) != 1:
        raise CadError("cad.rail_thread: inconsistent rail threads")
    values["rail_thread"] = threads.pop()

    def points(
        items: list[tuple[str, dict]], station: Callable[[str, dict], float]
    ) -> list[list[float]]:
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
                [station(name, item) / 25.4, -_mid(_band(item, "height", name)) / 25.4]
            )
        return sorted(result, key=lambda point: (point[0], -point[1]))

    def reference_station(name: str, item: dict) -> float:
        # Rail stations print REF; the actual trimmed rail transfers them.
        return _positive(item.get("station_nominal"), f"{name}.station_nominal")

    def toleranced_station(name: str, item: dict) -> float:
        return _mid(_band(item, "station", name))

    for name, item in rails:
        if "station" in item.get("requirements", []):
            raise CadError(f"{name}.station: expected a REF rail station")
    rail_points = points(rails, reference_station)
    bracket_points = points(brackets, toleranced_station)
    values["rail_points_in"] = rail_points
    values["bracket_points_in"] = bracket_points
    values["rail_x_in"] = [point[0] for point in rail_points]
    values["rail_x_mm"] = [point[0] * 25.4 for point in rail_points]
    # The drawing prints hole 1's REF station and one REF pitch for the pattern.
    pitches = [b - a for a, b in zip(values["rail_x_mm"], values["rail_x_mm"][1:])]
    if not pitches or any(not math.isclose(p, pitches[0]) for p in pitches):
        raise CadError("cad.rail_pitch_mm: rail holes are not one regular pattern")
    values["rail_first_mm"] = values["rail_x_mm"][0]
    values["rail_pitch_mm"] = pitches[0]
    if len({point[1] for point in rail_points}) != 1:
        raise CadError("cad.rail_y_in: rail holes must share a drawing row")
    values["rail_y_in"] = rail_points[0][1]
    for key, items, field in (
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
    # Position bands for inspection, in drawing order from ZERO END / ZERO EDGE.
    limits("rail_row", [_band(item, "height", name) for name, item in rails])
    band_counts = []
    for axis, field in (("x", "station"), ("y", "height")):
        columns = sorted({_band(item, field, name) for name, item in brackets})
        band_counts.append(len(columns))
        for index, band in enumerate(columns, 1):
            _inch_limits(values, f"bracket_{axis}{index}", band)
        for index, (name, item) in enumerate(slots, 1):
            _inch_limits(values, f"slot{index}_{axis}", _band(item, field, name))
    # The plan's inspection text and gauge checks name B1–B2, B3–B4, two
    # bracket rows and S1, S2; a different layout must not bind mislabelled.
    holes_per_column = [len(column) for _, column in point_columns(bracket_points)]
    if band_counts != [2, 2] or holes_per_column != [2, 2] or len(slots) != 2:
        raise CadError(
            "cad.features: the base-bar plan expects two slots and two bracket "
            "columns (B1–B2, B3–B4) on two rows, each with one position band"
        )
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
    # One cutter makes the slot: its centre traces a rectangle offset e from the
    # arc-centre line, so width = D + 2e and overall length = spacing + D + 2e.
    cutter = (
        _positive(parameters.get("half_cutter_dia_mm"), "process.half_cutter_dia_mm")
        / 25.4
    )
    values["slot_cutter_in"] = cutter
    offset = (values["slot_width_in"] - cutter) / 2
    if offset <= 0:
        raise CadError("process.half_cutter_dia_mm: cutter must be under slot width")
    # The cutter in the spindle cuts its own diameter + 2e on this path, so it
    # must fall in the drawing's width band less 2e (tool_sizing checks it).
    values["slot_cutter_band_mm"] = [
        limit - 2 * offset * 25.4 for limit in values["slot_width_band_mm"]
    ]
    # Each end is two cutter-radius corners, so the end radius departs outward
    # from the drawn arc by e(√2 − 1). Hold that to the drawing's two-place
    # linear tolerance applied to the end radius.
    radius_tol = _positive(general.get("linear_2pl"), "general_tolerances.linear_2pl")
    if offset * (math.sqrt(2) - 1) > radius_tol / 25.4:
        raise CadError(
            "process.half_cutter_dia_mm: slot end radius departs from the drawn "
            "arc by more than the two-place tolerance"
        )
    shapes = []
    for name, item in slots:
        if item.get("height_from") != "bar_low_side" or item.get("thru") is not True:
            raise CadError(
                f"{name}: requires a through slot measured from bar_low_side"
            )
        x = _mid(_band(item, "station", name)) / 25.4
        near = -_mid(_band(item, "height", name)) / 25.4
        far = near - _mid(_band(item, "separation", name)) / 25.4
        shapes.append(
            {
                "x_in": x,
                "near_y_in": near,
                "far_y_in": far,
                "width_in": _mid(_band(item, "width", name)) / 25.4,
                "corners_in": [
                    [x - offset, near + offset],
                    [x + offset, near + offset],
                    [x + offset, far - offset],
                    [x - offset, far - offset],
                ],
            }
        )
    values["slot_shapes_in"] = shapes
    for key, prefix, count in (
        ("rail", "R", len(rails)),
        ("bracket", "B", len(brackets)),
        ("slot", "S", len(slots)),
    ):
        values[f"{key}_count"] = count
        values[f"{key}_range"] = id_range(prefix, 1, count)
    bracket_x = sorted({point[0] for point in bracket_points})
    bracket_y = sorted({point[1] for point in bracket_points}, reverse=True)
    # The inspect picture sections the last bracket column.
    first_id, section = point_columns(bracket_points)[-1]
    values["bracket_section_points_in"] = section
    values["bracket_section_range"] = id_range("B", first_id, len(section))
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
    values["hole_rows"] = [
        [
            f"Rail {values['rail_range']}",
            "REF " + ", ".join(f"{point[0]:.4f}" for point in rail_points),
            f"{values['rail_y_in']:.4f}",
        ]
    ] + bracket_rows
    values["slot_rows"] = [
        [
            f"S{index}",
            f"{shape['x_in']:.4f}",
            f"{shape['near_y_in']:.4f}, {shape['far_y_in']:.4f}",
            ", ".join(f"{x:.4f}" for x, _ in shape["corners_in"][:2]),
            ", ".join(f"{y:.4f}" for _, y in shape["corners_in"][1:3]),
        ]
        for index, shape in enumerate(shapes, 1)
    ]
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
    # The deepest single step, for the slot cut's axial depth of cut.
    values["slot_step_mm"] = min(step, final_depth) * 25.4
    # Bar top above the jaw tops, from the plan's copy of the shop vise record.
    grip = (
        _positive(parameters.get("vise_jaw_height_mm"), "process.vise_jaw_height_mm")
        - _positive(parameters.get("parallel_height_mm"), "process.parallel_height_mm")
    ) / 25.4
    values["jaw_standout_in"] = values["thickness_in"] - grip
    # A missing blank thickness is named by stock_fit, which owns that parameter.
    if "blank_thickness_in" in parameters:
        values["jaw_standout_blank_in"] = parameters["blank_thickness_in"] - grip
    if values["jaw_standout_in"] <= 0:
        raise CadError(
            "cad.jaw_standout_in: finished bar top is at or below the vise jaw "
            "tops; facing would cut the jaws"
        )
    for key in ("length", "width", "thickness"):
        values[f"{key}_mm"] = values[f"{key}_in"] * 25.4
    # Vise holds centre the finished bar on the jaws (plan's copy of the shop
    # vise jaw width); the right side is the rest.
    values["vise_centred_overhang_mm"] = (
        values["length_mm"]
        - _positive(parameters.get("vise_jaw_width_mm"), "process.vise_jaw_width_mm")
    ) / 2
    # Setup 5 jack centres stay plan-authored; refuse one off the bar or under a
    # through feature's drawn outline (rail hole, counterbore, slot).
    outlines = [
        (f"R{index}", x, y, x, y, values["rail_dia_in"] / 2)
        for index, (x, y) in enumerate(rail_points, 1)
    ]
    outlines += [
        (f"B{index} counterbore", x, y, x, y, values["counterbore_dia_max_in"] / 2)
        for index, (x, y) in enumerate(bracket_points, 1)
    ]
    slot_radius = values["slot_width_max_in"] / 2
    outlines += [
        (f"S{index}", s["x_in"], s["far_y_in"], s["x_in"], s["near_y_in"], slot_radius)
        for index, s in enumerate(shapes, 1)
    ]
    for side in ("left", "right"):
        at = f"process.jack_{side}"
        x = _number(parameters.get(f"jack_{side}_x_in"), f"{at}_x_in")
        y = _number(parameters.get(f"jack_{side}_y_in"), f"{at}_y_in")
        if not (0 < x < values["length_in"] and -values["width_in"] < y < 0):
            raise CadError(f"{at}: X {x:g} Y {y:g} is off the bar")
        for name, x1, y1, x2, y2, radius in outlines:
            # Each outline is a point or an axis-aligned segment plus a radius.
            near = (min(max(x, x1), x2), min(max(y, y1), y2))
            if math.dist((x, y), near) <= radius:
                raise CadError(f"{at}: X {x:g} Y {y:g} is under {name}")
    _blank_mm(values, parameters)
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())


_TOKEN = re.compile(
    r"\{\{(cad|process|view)\.([A-Za-z_][A-Za-z_0-9]*)(?::([^{}]+))?\}\}"
)
_FORMAT = re.compile(r"(?:[+ -])?(?:[1-9][0-9]?)?(?:\.[0-9])?[fge%]|d")
# Shop shorthand: fixed places without the leading zero, as in ".4" or ".04".
_DOT = re.compile(r"\.([0-9])dot")


def _shorthand(value: float, places: int) -> str:
    """Fixed places without the leading zero: ``.900``, ``-.25``, ``19.111``."""
    result = format(value, f".{places}f")
    if float(result) == 0:
        result = result.lstrip("-")
    if result.lstrip("-").startswith("0."):
        result = result.replace("0.", ".", 1)
    return result


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
            elif spec and (dot := _DOT.fullmatch(spec)):
                result = _shorthand(value, int(dot[1]))
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


def bind_data(
    value: object, cad: CadData, parameters: dict, *, scalar_mode: str = "text"
) -> object:
    """Bind recursively; native mode preserves exact whole-field numeric tokens."""
    if scalar_mode not in {"text", "native"}:
        raise ValueError(f"unsupported binding scalar mode {scalar_mode!r}")
    if isinstance(value, str):
        token = _TOKEN.fullmatch(value)
        if token and token[3] is None:
            result = _lookup(token, cad, parameters, None)
            if isinstance(result, list) or (
                scalar_mode == "native" and type(result) in (int, float)
            ):
                return result
        return bind_text(value, cad, parameters)
    if isinstance(value, list):
        return [
            bind_data(item, cad, parameters, scalar_mode=scalar_mode) for item in value
        ]
    if isinstance(value, dict):
        return {
            key: bind_data(item, cad, parameters, scalar_mode=scalar_mode)
            for key, item in value.items()
        }
    return value
