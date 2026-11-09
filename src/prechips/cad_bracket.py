"""Bindings for the hand-authored v39 bracket example, not a released drawing."""

import tomllib
from pathlib import Path

from .cad import CadData, CadError, _band, _number, _positive, _string


def load_bracket(path: Path, parameters: dict) -> CadData:
    """Read only the bracket facts used by the authored comparison route."""
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if raw.get("part") != "pivot-bracket" or raw.get("units") != "mm":
        raise CadError("cad: harmonic_pivot_bracket requires pivot-bracket in mm")
    frames = raw.get("frames")
    if not isinstance(frames, dict):
        raise CadError("cad.frames: expected a table")
    model = frames.get("model")
    if not isinstance(model, dict):
        raise CadError("cad.frames.model: expected a table")
    if any(
        model.get(key) != expected
        for key, expected in (
            ("origin", [0, 0, 0]),
            ("x", [1, 0, 0]),
            ("y", [0, 1, 0]),
            ("z", [0, 0, 1]),
        )
    ):
        raise CadError("cad.frames.model: unsupported bracket frame")
    drawing = raw.get("drawing", {})
    if not isinstance(drawing, dict):
        raise CadError("cad.drawing: expected a table")
    values = {
        "part": raw["part"],
        "drawing_number": _string(drawing.get("number"), "cad.drawing.number"),
        "revision": _string(drawing.get("revision"), "cad.drawing.revision"),
    }
    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["finish"] = _string(material.get("finish"), "cad.material.finish")
    features = raw.get("features", {})
    if not isinstance(features, dict):
        raise CadError("cad.features: expected a table")

    def feature(name):
        item = features.get(name)
        if not isinstance(item, dict):
            raise CadError(f"cad.features.{name}: missing feature table")
        if item.get("frame") != "model":
            raise CadError(f"cad.features.{name}: unsupported frame")
        return item

    def vector(item, key, where):
        value = item.get(key)
        if not isinstance(value, list) or len(value) != 3:
            raise CadError(f"{where}.{key}: expected three model coordinates")
        return tuple(_number(v, f"{where}.{key}") for v in value)

    def bounds(item, axis, where):
        source_bounds = item.get("bounds")
        if not isinstance(source_bounds, dict):
            raise CadError(f"{where}.bounds: expected a table")
        value = source_bounds.get(axis)
        if not isinstance(value, list) or len(value) != 2:
            raise CadError(f"{where}.bounds.{axis}: missing bounds")
        low, high = (_number(v, f"{where}.bounds.{axis}") for v in value)
        if low >= high:
            raise CadError(f"{where}.bounds.{axis}: expected increasing bounds")
        return low, high

    def plane(item, axis, where):
        value = item.get("plane", {})
        if not isinstance(value, dict):
            raise CadError(f"{where}.plane: expected a table")
        if value.get("frame") != "model" or value.get("axis") != axis:
            raise CadError(f"{where}.plane: unsupported frame or axis")
        return _number(value.get("value"), f"{where}.plane.value")

    def band(item, field, key, where):
        low, high = _band(item, field, where)
        if low <= 0:
            raise CadError(f"{where}.{field}: expected positive limits")
        values[f"{key}_min"] = low
        values[f"{key}_max"] = high

    seat = plane(feature("seat_face"), "y", "seat_face")
    foot_top = feature("foot_top")
    top = plane(foot_top, "y", "foot_top")
    foot = feature("foot_profile")
    xmin, xmax = bounds(foot, "x", "foot_profile")
    zmin, zmax = bounds(foot, "z", "foot_profile")
    ymin, ymax = bounds(foot, "y", "foot_profile")
    outer = plane(feature("outer_face"), "z", "outer_face")
    ear = feature("ear_relief")
    inner, _ = bounds(ear, "z", "ear_relief")
    sides = feature("ear_sides")
    exmin, exmax = bounds(sides, "x", "ear_sides")
    if seat != 0 or ymin != seat or ymax != top or outer != zmin or inner <= outer:
        raise CadError("cad: unsupported bracket seat/foot/ear frame")
    values.update(
        foot_x_min=xmin,
        foot_x_max=xmax,
        foot_y_min=zmin,
        foot_y_max=zmax,
        foot_depth=seat - top,
        foot_thickness=top - seat,
        inner_y=-inner,
        ear_x_min=exmin,
        ear_x_max=exmax,
        ear_thickness=inner - outer,
    )
    for item, field, key, name in (
        (foot, "width", "foot_width", "foot_profile"),
        (foot, "length", "foot_length", "foot_profile"),
        (foot_top, "height", "foot_height", "foot_top"),
        (ear, "thickness", "ear_thickness", "ear_relief"),
        (sides, "width", "ear_width", "ear_sides"),
    ):
        band(item, field, key, name)

    for suffix in ("a", "b"):
        name = f"hold_down_{suffix}"
        item = feature(name)
        x, y, z = vector(item, "at", name)
        if vector(item, "axis", name) != (0, -1, 0) or y != top or z <= 0:
            raise CadError(f"{name}: unsupported foot-hole frame or axis")
        thickness = _positive(
            item.get("through_thickness"), f"{name}.through_thickness"
        )
        if item.get("thru") is not True or thickness != top - seat:
            raise CadError(f"{name}: unsupported through-foot hole")
        values[f"hole_{suffix}_x"] = x
        values[f"hole_{suffix}_y"] = -z
        band(item, "dia", f"hole_{suffix}_dia", name)
        band(item, "station", f"hole_{suffix}_station", name)
        station = z - (inner + outer) / 2
        if (
            not values[f"hole_{suffix}_station_min"]
            <= station
            <= values[f"hole_{suffix}_station_max"]
        ):
            raise CadError(f"{name}.at: station outside station band")

    arch = feature("ear_arch")
    bore = feature("cross_bore")
    ax, ay, az = vector(arch, "at", "ear_arch")
    bx, by, bz = vector(bore, "at", "cross_bore")
    if (
        (ax, ay, az) != (bx, by, bz)
        or bz != outer
        or vector(arch, "axis", "ear_arch") != (0, 0, 1)
        or vector(bore, "axis", "cross_bore") != (0, 0, 1)
        or arch.get("arc") != "upper_semicircle"
        or bore.get("height_from") != "seat_face"
        or bore.get("thru") is not True
    ):
        raise CadError("cad: unsupported bracket arch/bore frame or axis")
    for item, name in ((arch, "ear_arch"), (bore, "cross_bore")):
        thickness = _positive(
            item.get("through_thickness"), f"{name}.through_thickness"
        )
        if thickness != inner - outer:
            raise CadError(f"{name}: unsupported through-ear thickness")
    values.update(
        bore_x=bx,
        bore_y=seat - by,
        arch_radius=_positive(arch.get("radius_nominal"), "ear_arch.radius_nominal"),
    )
    band(arch, "radius", "arch_radius", "ear_arch")
    band(bore, "dia", "bore_dia", "cross_bore")
    band(bore, "height", "bore_height", "cross_bore")
    if (
        not values["arch_radius_min"]
        <= values["arch_radius"]
        <= values["arch_radius_max"]
    ):
        raise CadError("ear_arch.radius_nominal: outside radius band")
    if not values["bore_height_min"] <= by - seat <= values["bore_height_max"]:
        raise CadError("cross_bore.at: height above seat outside height band")
    general = raw.get("general_tolerances", {})
    if not isinstance(general, dict):
        raise CadError("cad.general_tolerances: expected a table")
    for key in ("edge_break_r", "chamfer_max"):
        values[key] = _positive(general.get(key), f"general_tolerances.{key}")

    def process(key):
        return _positive(parameters.get(key), f"parameters.{key}")

    # Prepared stock and machining allowances remain authored process inputs.
    radial = process("outline_allowance_mm")
    crown = process("prepared_height_mm") - process("seat_face_allowance_mm")
    prepared_length = zmax - zmin + 2 * radial
    width_skim = (process("raw_width_mm") - process("prepared_width_mm")) / 2
    length_skim = (process("raw_length_mm") - prepared_length) / 2
    height_skim = (process("sawn_height_mm") - process("prepared_height_mm")) / 2
    if min(width_skim, length_skim, height_skim) < 0:
        raise CadError("parameters: prepared blank exceeds selected raw stock")
    values.update(
        prepared_length=prepared_length,
        width_skim=width_skim,
        length_skim=length_skim,
        height_skim=height_skim,
        ledge_z=-(zmax - zmin),
        bridge_y=seat - top,
        foot_jaw_z=process("foot_grip_mm") - (top - seat),
        seat_jaw_z=process("seat_grip_mm") - crown,
        raw_x_min=-process("prepared_width_mm") / 2,
        raw_x_max=process("prepared_width_mm") / 2,
        raw_y_min=zmin - radial,
        raw_y_max=zmax + radial,
        reverse_raw_y_min=-(zmax + radial),
        reverse_raw_y_max=-(zmin - radial),
        crown_z=crown - top,
        crown_y=-crown,
        strip_y_min=-inner - process("wall_leave_mm"),
        crown_finish_depth=-(inner - outer) - process("arch_breakthrough_mm"),
    )
    return CadData(values, None, path.resolve())
