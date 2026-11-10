"""Bindings for the patched MHA-071 rocker-arm example, not a process generator."""

import math
import tomllib
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _number,
    _positive,
    _string,
)


def load_rocker(path: Path, parameters: dict) -> CadData:
    """Bind model geometry to pivot-relative upper and X-turned lower setups."""
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if raw.get("units") != "mm" or raw.get("part") != "rocker-arm":
        raise CadError("cad: harmonic_rocker_arm requires rocker-arm in mm")
    values = {"part": raw["part"]}
    drawing = raw.get("drawing", {})
    if not isinstance(drawing, dict):
        raise CadError("cad.drawing: required table missing")
    for key, field in (("drawing_number", "number"), ("revision", "revision")):
        values[key] = _string(drawing.get(field), f"cad.drawing.{field}")

    def table(parent: dict, key: str) -> dict:
        item = parent.get(key)
        if not isinstance(item, dict):
            raise CadError(f"cad.{key}: required table missing")
        return item

    def vector(item: dict, field: str, size: int = 3) -> list[float]:
        result = item.get(field)
        if not isinstance(result, list) or len(result) != size:
            raise CadError(f"cad.{field}: expected {size}-coordinate vector")
        return [_number(number, f"cad.{field}") for number in result]

    frames = table(raw, "frames")
    for name, axes in (
        ("model", ([1, 0, 0], [0, 1, 0], [0, 0, 1])),
        ("A", ([1, 0, 0], [0, 1, 0], [0, 0, 1])),
        ("B", ([1, 0, 0], [0, -1, 0], [0, 0, -1])),
    ):
        frame = table(frames, name)
        vector(frame, "origin")
        if any(vector(frame, axis) != expected for axis, expected in zip("xyz", axes)):
            raise CadError(f"cad.frames.{name}: unsupported rocker frame axes")

    features = table(raw, "features")

    def feature(name: str, kind: str) -> dict:
        item = table(features, name)
        if item.get("frame") != "model" or item.get("kind") != kind:
            raise CadError(f"cad.{name}: expected {kind} in model frame")
        return item

    def band(item: dict, field: str, name: str) -> None:
        low, high = _band(item, field, name)
        if low <= 0:
            raise CadError(f"cad.{name}: expected positive limits")
        values[f"{name}_min"] = low
        values[f"{name}_max"] = high

    pivot = feature("pivot_bore", "hole")
    rod = feature("rod_hole", "hole")
    hub = feature("hub_od", "boss")
    pivot_at = vector(pivot, "at")
    rod_at = vector(rod, "at")
    for name, item in (("pivot_bore", pivot), ("rod_hole", rod), ("hub_od", hub)):
        if vector(item, "axis") != [0, 0, 1]:
            raise CadError(f"cad.{name}: unsupported hole/hub axis")
    if pivot.get("thru") is not True or rod.get("thru") is not True:
        raise CadError("cad: rocker holes must be through")
    if rod_at[2] != pivot_at[2] or vector(hub, "at") != pivot_at:
        raise CadError("cad: unsupported noncoplanar rod or offset hub")
    if hub.get("coaxial_to") != "pivot_bore" or pivot.get("process") != "ream":
        raise CadError("cad: expected reamed pivot and coaxial hub")
    if rod.get("dimension_type") != "basic":
        raise CadError("cad.rod_hole: expected basic position")
    if rod.get("position_datums") != ["A", "B", "C"]:
        raise CadError("cad.rod_hole: unsupported position datums")
    values["position_datums"] = "|".join(rod["position_datums"])
    datums = table(raw, "datums")
    for letter, name in (
        ("A", "pivot_bore"),
        ("B", "strap_datum_b"),
        ("C", "tip_land_pos_x"),
    ):
        datum = table(datums, letter)
        if datum.get("feature") != name or table(features, name).get("datum") != letter:
            raise CadError(f"cad.datums.{letter}: unsupported datum feature")
        values[f"datum_{letter}"] = _string(
            datum.get("surface"), f"cad.datums.{letter}.surface"
        )
    for name, item in (("pivot", pivot), ("rod", rod), ("hub", hub)):
        band(item, "dia", name)
    values["pivot_ra"] = _positive(pivot.get("finish_ra"), "cad.pivot.finish_ra")
    values["position_dia"] = _positive(rod.get("position_dia"), "cad.rod.position_dia")
    values["coaxiality_dia"] = _positive(
        hub.get("coaxiality_dia"), "cad.hub.coaxiality_dia"
    )
    values["rod_x"] = rod_at[0] - pivot_at[0]
    values["rod_upper_y"] = rod_at[1] - pivot_at[1]
    values["rod_lower_y"] = -values["rod_upper_y"]

    hub_faces = feature("hub_faces", "face")
    strap = feature("strap_faces", "face")
    band(hub_faces, "length", "hub_length")
    band(strap, "thickness", "strap")
    upper = _number(hub_faces.get("upper_z"), "cad.hub.upper_z")
    lower = _number(hub_faces.get("lower_z"), "cad.hub.lower_z")
    strap_upper = _number(strap.get("upper_z"), "cad.strap.upper_z")
    strap_lower = _number(strap.get("lower_z"), "cad.strap.lower_z")
    if not lower < strap_lower < strap_upper < upper:
        raise CadError("cad: unsupported hub/strap face order")
    if not math.isclose(
        upper + lower, 2 * pivot_at[2], abs_tol=1e-9
    ) or not math.isclose(strap_upper + strap_lower, 2 * pivot_at[2], abs_tol=1e-9):
        raise CadError("cad: opposed same-depth route requires centred hub/strap faces")
    datum_b = feature("strap_datum_b", "face").get("plane")
    if datum_b != {"frame": "model", "axis": "z", "value": strap_upper}:
        raise CadError("cad: datum B must be the upper strap plane")
    values["strap_z"] = strap_upper - upper

    top = feature("top_edge", "profile")
    profile = feature("profile_outer", "profile")
    if (
        top.get("height_from") != "pivot_bore"
        or profile.get("top_edge_feature") != "top_edge"
    ):
        raise CadError("cad: unsupported profile reference")
    centre = vector(top, "arc_centre")
    if (
        vector(profile, "arc_centre") != centre
        or profile.get("mirror_symmetric") is not True
    ):
        raise CadError("cad: expected concentric, mirror-symmetric profile")
    if not math.isclose(centre[0], pivot_at[0], rel_tol=0, abs_tol=1e-9):
        raise CadError("cad: profile mirror axis must pass through the pivot")
    for name, item, field in (
        ("top_radius", top, "radius"),
        ("bottom_radius", profile, "bottom_radius"),
        ("top_arc", top, "arc_len"),
        ("bottom_arc", profile, "bottom_arc_len"),
        ("top_height", top, "height_above_pivot"),
    ):
        band(item, field, name)
    top_radius = _positive(top.get("radius_nominal"), "cad.top.radius_nominal")
    bottom_radius = _positive(
        profile.get("bottom_radius_nominal"), "cad.profile.bottom_radius_nominal"
    )
    if not values["top_radius_min"] <= top_radius <= values["top_radius_max"]:
        raise CadError("cad: nominal top radius lies outside source limits")
    if not values["bottom_radius_min"] <= bottom_radius <= values["bottom_radius_max"]:
        raise CadError("cad: nominal bottom radius lies outside source limits")
    top_height = centre[1] - top_radius - pivot_at[1]
    if not values["top_height_min"] <= top_height <= values["top_height_max"]:
        raise CadError("cad: nominal top height lies outside source limits")
    points = [
        vector(top, "end", 2),
        vector(profile, "radial_tip_end", 2),
        vector(profile, "bottom_end", 2),
    ]
    lands = [feature(name, "face") for name in ("tip_land_pos_x", "tip_land_neg_x")]
    for index, land in enumerate(lands):
        for field, key in (
            ("tip_land", "land_width"),
            ("land_angle_deg", "land_angle"),
        ):
            band(land, field, f"{key}_{index}")
        endpoint = vector(land, "radial_tip_end", 2)
        expected = (
            points[1] if index == 0 else [2 * centre[0] - points[1][0], points[1][1]]
        )
        if endpoint != expected or land.get("top_edge_feature") != "top_edge":
            raise CadError("cad: unsupported land/profile relationship")
    # One printed requirement covers both lands only when their source bands agree.
    for key in ("land_width", "land_angle"):
        for suffix in ("min", "max"):
            if values[f"{key}_0_{suffix}"] != values[f"{key}_1_{suffix}"]:
                raise CadError("cad: both-land inspection needs matching land limits")
            values[f"{key}_{suffix}"] = values[f"{key}_0_{suffix}"]
    values["outline_rows"] = [
        [
            "Common centre",
            (
                f"X{centre[0] - pivot_at[0]:.3f} Y{centre[1] - pivot_at[1]:.3f}; "
                f"top R{top_radius:.2f}, bottom R{bottom_radius:.2f}"
            ),
        ]
    ]
    for sign, label in ((1, "+X end"), (-1, "−X end")):
        coords = " → ".join(
            f"({centre[0] + sign * (x - centre[0]) - pivot_at[0]:.3f},"
            f"{y - pivot_at[1]:.3f})"
            for x, y in points
        )
        values["outline_rows"].append(
            [
                label + ": top → land → bottom",
                coords + "; radial land then straight taper",
            ]
        )

    def process(key: str) -> float:
        return _positive(parameters.get(key), f"process.{key}")

    aim = process("hub_length_aim")
    lower_strap_z = lower - strap_lower
    values["strap_aim"] = aim + values["strap_z"] + lower_strap_z
    if not values["hub_length_min"] <= aim <= values["hub_length_max"]:
        raise CadError("process.hub_length_aim: outside source limits")
    if not values["strap_min"] <= values["strap_aim"] <= values["strap_max"]:
        raise CadError("cad.strap_aim: opposed face depths fall outside source limits")
    half_blank = process("blank_thickness") / 2
    values["face_skim"] = (process("stock_thickness") - 2 * half_blank) / 2
    # Two equal passes on each opposed edge, as chosen in the authored route.
    values["edge_skim"] = (process("stock_width") - process("blank_width")) / 4
    values["end_cut_z"] = -(2 * half_blank + process("end_breakthrough"))
    values["end_step"] = -values["end_cut_z"] / 3
    values["end_overhang"] = (process("blank_length") - process("end_support_span")) / 2
    values["blank_left_x"] = -process("blank_length") / 2
    values["upper_raw_top"] = pivot_at[2] + half_blank - upper
    values["raw_bottom"] = pivot_at[2] - half_blank - upper
    values["lower_raw_top"] = 2 * half_blank - aim - values["upper_raw_top"]
    values["profile_rough_z"] = (
        (upper + lower) / 2 - upper + process("profile_half_web")
    )
    actual_lower_strap_z = -aim - lower_strap_z
    values["profile_release_z"] = actual_lower_strap_z - process("release_clearance")
    values["web"] = aim + 2 * values["profile_rough_z"]
    hub_nominal = _positive(hub.get("dia_nominal"), "cad.hub.dia_nominal")
    if not values["hub_min"] <= hub_nominal <= values["hub_max"]:
        raise CadError("cad.hub.dia_nominal: outside dia band")
    values["hub_rough_island"] = hub_nominal + process("hub_rough_diametral_allowance")
    values["hub_finish_island"] = hub_nominal + process(
        "hub_finish_diametral_allowance"
    )
    for key in (
        "upper_raw_top",
        "lower_raw_top",
        "web",
        "face_skim",
        "edge_skim",
        "end_overhang",
    ):
        if values[key] <= 0 or not math.isfinite(values[key]):
            raise CadError(f"cad.{key}: source does not support retained-frame process")
    values["edge_break"] = _positive(
        table(raw, "general_tolerances").get("edge_break_r"), "cad.edge_break_r"
    )
    values["chamfer"] = _positive(
        raw["general_tolerances"].get("chamfer_max"), "cad.chamfer_max"
    )
    values["finish"] = _string(
        table(raw, "material").get("finish"), "cad.material.finish"
    )
    values["finish"] = values["finish"][0].upper() + values["finish"][1:]
    # Nominal finished envelope in the sawn flat-bar blank's axes, no rotation:
    # stock_length spans model X between the mirrored profile vertices; stock_width
    # spans model Y from the bottom arc's low point on the mirror axis (centre above
    # the part) to the highest profile vertex or hub; stock_thickness spans model Z
    # between the hub faces, which enclose the strap faces.
    ys = [y for _, y in points]
    high_y = max(*ys, pivot_at[1] + hub_nominal / 2)
    if centre[1] <= high_y:
        raise CadError("cad: stock envelope needs the profile arc centre above part")
    low_y = min(*ys, centre[1] - bottom_radius, pivot_at[1] - hub_nominal / 2)
    half_length = max(abs(x - centre[0]) for x, _ in points)
    stock = StockRequirement(
        "mm",
        (
            StockAxis("length", "stock_length", 2 * half_length),
            StockAxis("width", "stock_width", high_y - low_y),
            StockAxis("thickness", "stock_thickness", upper - lower),
        ),
    )
    return CadData(values, stock, path.resolve())
