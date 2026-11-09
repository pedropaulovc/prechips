"""Explicit pivot-shaft drawing bindings and the authored RH turning route."""

import math
import tomllib
from pathlib import Path

from prechips.cad import CadData, CadError, _band, _number, _positive, _string


def _contour_rows(radius: float, height: float, parameters: dict) -> list[list[str]]:
    """Imaginary-tip readings: OD X touch, +Z face touch, X diametric.

    Pure math from the archived coordinates._dome / _dome_stair: offset the
    finish surface along its normal; rough corners lie on a grown sphere.
    """
    nose = _positive(parameters.get("nose_radius_mm"), "process.nose_radius_mm")
    step = _positive(parameters.get("contour_step_mm"), "process.contour_step_mm")
    allowance = _positive(
        parameters.get("dome_rough_allowance_mm"), "process.dome_rough_allowance_mm"
    )
    entering = _positive(
        parameters.get("entering_angle_deg"), "process.entering_angle_deg"
    )
    insert = _positive(parameters.get("insert_angle_deg"), "process.insert_angle_deg")
    if height > radius or height / step > 1000 or entering + insert >= 180:
        raise CadError("cad.dome: unsupported convex cap, sampling or RH tool angles")
    count = math.ceil(height / step)
    work_radius = math.sqrt(height * (2 * radius - height))
    grown = radius + allowance / 2
    cells = []
    for index in range(count + 1):
        depth = height if index == count else index * step
        surface_radius = math.sqrt(depth * (2 * radius - depth))
        normal_r, normal_z = surface_radius / radius, 1 - depth / radius
        angle = math.degrees(math.atan2(normal_z, normal_r))
        if not entering + insert - 180 <= angle <= entering:
            raise CadError(
                "cad.dome: contact normal lies outside the authored tool nose arc"
            )
        finish_x = 2 * (surface_radius + nose * (normal_r - 1))
        finish_z = -depth + nose * (normal_z - 1)
        rough_radius = math.sqrt(grown * grown - (radius - depth) ** 2)
        rough = (
            _reading(-depth, 2 * rough_radius)
            if index and rough_radius < work_radius - 1e-9
            else "—"
        )
        cells.append([rough, _reading(finish_z, finish_x)])
    split = math.ceil(len(cells) / 2)
    return [
        cells[index]
        + (cells[index + split] if index + split < len(cells) else ["—", "—"])
        for index in range(split)
    ]


def _reading(z: float, x: float) -> str:
    # Avoid negative zero at the apex; retain the meaningful negative tip X.
    return f"{0.0 if abs(z) < 0.0005 else z:.2f} / {x:.2f}".replace("-", "−")


def load_shaft(path: Path, parameters: dict) -> CadData:
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if raw.get("units") != "mm" or raw.get("part") != "pivot-shaft":
        raise CadError("cad: harmonic_pivot_shaft requires pivot-shaft in mm")
    frames = raw.get("frames")
    model = frames.get("model") if isinstance(frames, dict) else None
    expected_frame = {
        "origin": [0, 0, 0],
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
    }
    if not isinstance(model, dict) or any(
        model.get(k) != v for k, v in expected_frame.items()
    ):
        raise CadError("cad.frames.model: expected the shaft's XYZ model frame")
    drawing, features = raw.get("drawing"), raw.get("features")
    if not isinstance(drawing, dict) or not isinstance(features, dict):
        raise CadError("cad: missing drawing or features table")
    values = {
        "part": raw["part"],
        "drawing_number": _string(drawing.get("number"), "cad.drawing.number"),
        "revision": _string(drawing.get("revision"), "cad.drawing.revision"),
    }

    def feature(name: str, kind: str) -> dict:
        item = features.get(name)
        if (
            not isinstance(item, dict)
            or item.get("kind") != kind
            or item.get("frame") != "model"
        ):
            raise CadError(f"cad.{name}: expected a model-frame {kind}")
        return item

    def band(item: dict, field: str, key: str) -> tuple[float, float]:
        low, high = _band(item, field, key)
        if low <= 0:
            raise CadError(f"cad.{key}: expected positive limits")
        values[f"{key}_min"], values[f"{key}_max"] = low, high
        return low, high

    def nominal(item: dict, field: str, key: str) -> float:
        low, high = band(item, field, key)
        value = _positive(item.get(f"{field}_nominal"), f"cad.{key}_nominal")
        if not low <= value <= high:
            raise CadError(f"cad.{key}: nominal lies outside source limits")
        values[key] = value
        return value

    def finish(item: dict, key: str) -> None:
        if "finish_ra" not in item.get("requirements", []):
            raise CadError(f"cad.{key}: missing finish requirement")
        values[key] = _positive(item.get("finish_ra"), f"cad.{key}")

    def station(item: dict, name: str) -> float:
        at = item.get("at")
        if not isinstance(at, list) or len(at) != 3:
            raise CadError(f"cad.{name}.at: expected a spindle-axis point")
        point = [_number(value, f"cad.{name}.at") for value in at]
        if point[:2] != [0, 0]:
            raise CadError(f"cad.{name}.at: expected a spindle-axis point")
        return point[2]

    def plane(item: dict, name: str) -> float:
        value = item.get("plane")
        if (
            not isinstance(value, dict)
            or value.get("frame") != "model"
            or value.get("axis") != "z"
        ):
            raise CadError(f"cad.{name}.plane: expected model Z plane")
        return _number(value.get("value"), f"cad.{name}.plane.value")

    bearing = feature("pivot_bearing", "shaft")
    journal = feature("pivot_journal", "shaft")
    for key, item in (("bearing", bearing), ("journal", journal)):
        if item.get("axis") != [0, 0, 1]:
            raise CadError(f"cad.{key}.axis: expected +Z spindle axis")
        station(item, key)
        nominal(item, "dia", f"{key}_dia")
        finish(item, f"{key}_finish")
    nominal(journal, "length", "journal_length")
    values["span_ref"] = _positive(bearing.get("length_ref"), "cad.bearing.length_ref")
    nominal(feature("shoulder_od", "boss"), "dia", "shoulder_dia")
    north = feature("shoulder_north_face", "face")
    thrust = feature("shoulder_thrust", "face")
    nominal(north, "length", "shoulder_length")
    if _band(thrust, "length", "shoulder_thrust") != _band(
        north, "length", "shoulder_north_face"
    ):
        raise CadError("cad.shoulder: inconsistent length requirements")
    north_z, thrust_z = (
        plane(north, "shoulder_north_face"),
        plane(thrust, "shoulder_thrust"),
    )
    if not math.isclose(north_z - thrust_z, values["shoulder_length"]):
        raise CadError("cad.shoulder: planes disagree with nominal length")
    if (
        _number(thrust.get("upper_z"), "cad.shoulder.upper_z") != north_z
        or _number(thrust.get("lower_z"), "cad.shoulder.lower_z") != thrust_z
        or _positive(thrust.get("length_nominal"), "cad.shoulder.length_nominal")
        != values["shoulder_length"]
    ):
        raise CadError("cad.shoulder: inconsistent source stations")
    finish(thrust, "thrust_finish")

    domes = []
    for end in ("north", "south"):
        item = feature(f"{end}_dome", "dome")
        height = nominal(item, "height", f"{end}_dome_height")
        radius = _positive(item.get("sphere_radius"), f"cad.{end}_dome.sphere_radius")
        base = _number(item.get("base_z"), f"cad.{end}_dome.base_z")
        if height > radius or not math.isclose(
            height * (2 * radius - height),
            (values[f"{'journal' if end == 'north' else 'bearing'}_dia"] / 2) ** 2,
            rel_tol=1e-8,
        ):
            raise CadError(f"cad.{end}_dome: cap does not meet nominal shaft diameter")
        values[f"{end}_dome_radius"] = radius
        domes.append((height, radius, base))
    height, radius, base = domes[0]
    if domes[1][:2] != domes[0][:2]:
        raise CadError(
            "cad.domes: repeat-table route requires matching height and radius"
        )
    if not math.isclose(base - domes[1][2], values["span_ref"]):
        raise CadError("cad.span_ref: dome base stations disagree with REF span")
    apex = base + height
    if not math.isclose(base - north_z, values["journal_length"]):
        raise CadError(
            "cad.journal: shoulder and dome base disagree with nominal length"
        )
    values.update(
        thrust_z=thrust_z - apex, north_shoulder_z=north_z - apex, north_base_z=-height
    )
    blade = _positive(parameters.get("blade_width_mm"), "process.blade_width_mm")
    for end in ("north", "south"):
        item = feature(f"{end}_relief", "groove")
        nominal(item, "dia", f"{end}_relief_dia")
        width = nominal(item, "width", f"{end}_relief_width")
        centre = station(item, f"{end}_relief")
        values[f"{end}_corner_max"] = _positive(
            item.get("corner_radius_max_design"), f"cad.{end}_corner_max"
        )
        low, high = centre - width / 2, centre + width / 2
        if end == "north":
            if not math.isclose(low, north_z) or high >= base:
                raise CadError(
                    "cad.north_relief: unsupported shoulder/journal placement"
                )
            low = north_z - apex
            high = low + width
        else:
            if not math.isclose(high, thrust_z):
                raise CadError("cad.south_relief: unsupported thrust-face placement")
            low, high = 0.0, width
        if not blade <= width <= 2 * blade:
            raise CadError(
                f"cad.{end}_relief: authored two-plunge blade strategy cannot cover width"
            )
        values.update(
            {
                f"{end}_relief_start": low,
                f"{end}_relief_first_end": low + blade,
                f"{end}_relief_second_start": high - blade,
                f"{end}_relief_end": high,
            }
        )
    tolerances = raw.get("general_tolerances")
    if not isinstance(tolerances, dict):
        raise CadError("cad.general_tolerances: missing edge limits")
    values["edge_break_max"] = min(
        _positive(tolerances.get("edge_break_r"), "cad.edge_break_r"),
        _positive(tolerances.get("chamfer_max"), "cad.chamfer_max"),
    )

    def process(key: str) -> float:
        return _positive(parameters.get(key), f"process.{key}")

    supply = process("supply_length_mm")
    rough = process("turn_rough_allowance_mm")
    fit = process("fit_apex_mm")
    face_allowance = process("plain_end_face_allowance_mm")
    values.update(
        bearing_rough_dia=values["bearing_dia"] + rough,
        journal_rough_dia=values["journal_dia"] + rough,
        north_rough_stop=values["north_shoulder_z"]
        + process("shoulder_face_allowance_mm"),
        plain_end_z=supply + thrust_z - apex,
        supported_projection=supply + north_z - apex,
        north_grip=process("stub_allowance_mm") + apex - north_z,
        blank_length=supply + process("stub_allowance_mm") + face_allowance,
        plain_end_face_passes=math.ceil(face_allowance / 0.25),
        reverse_projection=apex - thrust_z + process("stub_allowance_mm"),
        south_base_z=fit - height,
        parting_z=fit + process("fit_face_allowance_mm"),
    )
    values["turn_start_z"] = values["plain_end_z"] + process("turn_start_clearance_mm")
    rest_centre = process("follow_rest_reset_z_mm") + process("follow_rest_lead_mm")
    rest_half_jaw = process("follow_rest_jaw_mm") / 2
    rest_low, rest_high = rest_centre - rest_half_jaw, rest_centre + rest_half_jaw
    if rest_low < 0 or rest_high >= values["plain_end_z"]:
        raise CadError("process.follow_rest: jaw band must lie before the plain end")
    values["rest_scribe_min"] = (
        values["plain_end_z"]
        - rest_low
        + values["south_base_z"]
        + process("follow_rest_waste_margin_mm")
    )
    scribe_expectation = supply - (apex - domes[1][2])
    tolerance = process("scribe_expectation_tolerance_mm")
    values["scribe_expected_min"] = scribe_expectation - tolerance
    values["scribe_expected_max"] = scribe_expectation + tolerance
    if values["plain_end_z"] <= 0 or not process("fit_min_mm") <= fit <= process(
        "fit_max_mm"
    ):
        raise CadError("process: unusable supply length or fit-to-scribe target")
    stock_dia = process("stock_dia_mm")
    if not values["shoulder_dia_min"] <= stock_dia <= values["shoulder_dia_max"]:
        raise CadError(
            "process.stock_dia_mm: retained bar surface is outside shoulder limits"
        )
    if max(values["bearing_rough_dia"], values["journal_rough_dia"]) >= stock_dia:
        raise CadError(
            "process: rough turning target must be below authored bar diameter"
        )
    if stock_dia - min(values["bearing_rough_dia"], values["journal_rough_dia"]) > 4:
        raise CadError(
            "process: four rough passes at 0.5 mm radial depth cannot reach target"
        )
    if process("blade_corner_radius_mm") > min(
        values["north_corner_max"], values["south_corner_max"]
    ):
        raise CadError(
            "process.blade_corner_radius_mm: tool exceeds relief corner limit"
        )
    values["contour_rows"] = _contour_rows(radius, height, parameters)
    return CadData(values, None, path.resolve())
