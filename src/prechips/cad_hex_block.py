"""Bindings for a short block cut from hex bar, tapped in both ends and
cross-bored through its corners.

Model Y is the hex axis, the bottom face at Y0 and the top face at the block
height; two corners lie on the X axis and two flats are normal to Z (the
Z flats). A cross bore along X runs through the two corners. A tapped hole
enters each end on the axis: the rod tap from the bottom, blind, and the
thumb tap from the top, drilled into the bore.

With the plan's cross-setup parameters the adapter also binds how the block
lies for the cross bore: corner down between two parallels, one against each
jaw, gripped on its two vertical flats.
"""

import math
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _all_or_none,
    _band,
    _edge_breaks,
    _feature,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
)

_FEATURES = {
    "bottom_face",
    "top_face",
    "hex_flats",
    "lever_bore",
    "thumb_tap",
    "rod_tap",
}
_BLANK = ("blank_length_min_in", "blank_length_max_in")
_CROSS = ("parallel_thickness_mm", "cross_parallel_end_mm")
_TAN30 = math.tan(math.radians(30))
# A 118° drill point is this many radii long.
_POINT = 1 / math.tan(math.radians(59))
_TOLERANCE = 1e-6


def _window(feature: dict, key: str, where: str) -> tuple[float, float]:
    """A stated two-number window that is not itself a drawing requirement."""
    value = feature.get(key)
    if not isinstance(value, list) or len(value) != 2:
        raise CadError(f"{where}.{key}: expected a two-number window")
    low, high = (_positive(item, f"{where}.{key}") for item in value)
    if low > high:
        raise CadError(f"{where}.{key}: reversed window")
    return low, high


def _nominal(feature: dict, band: tuple[float, float], where: str) -> float:
    """The depth the program drills to, inside its band."""
    nominal = _positive(feature.get("drill_depth_nominal"), f"{where}.drill_depth")
    if not band[0] <= nominal <= band[1]:
        raise CadError(f"{where}.drill_depth_nominal: outside its band")
    return nominal


def _height(features: dict, values: dict) -> float:
    """Block height: both end faces carry the one band, square to the axis."""
    faces = [_feature(features, name, "face") for name in ("bottom_face", "top_face")]
    band = _band(faces[0], "height", "bottom_face")
    nominal = _positive(faces[0].get("height_nominal"), "bottom_face.height_nominal")
    for face, name, at in zip(
        faces, ("bottom_face", "top_face"), (0.0, nominal), strict=True
    ):
        plane = face.get("plane")
        if (
            _band(face, "height", name) != band
            or face.get("height_nominal") != nominal
            or not isinstance(plane, dict)
            or plane.get("axis") != "y"
            or _number(plane.get("value"), f"{name}.plane.value") != at
        ):
            raise CadError(f"{name}: expected the height band between Y0 and the top")
    if not band[0] <= nominal <= band[1]:
        raise CadError("bottom_face.height_nominal: outside height band")
    _inch_limits(values, "block_height", band)
    values["block_height_mm"] = nominal
    return nominal


def _hex(features: dict, values: dict) -> float:
    """The bar as bought: across flats (a stock reference) and across corners."""
    flats = _feature(features, "hex_flats", "stock")
    af = _positive(flats.get("af_ref"), "hex_flats.af_ref")
    ac = _positive(flats.get("ac_nominal"), "hex_flats.ac_nominal")
    if abs(ac - af / math.cos(math.radians(30))) > _TOLERANCE:
        raise CadError("hex_flats.ac_nominal: not a regular hexagon's across corners")
    normals = flats.get("flat_normals")
    if not isinstance(normals, list) or [0, 0, 1] not in normals:
        raise CadError("hex_flats.flat_normals: expected a flat normal to Z")
    values["af_mm"], values["ac_mm"] = af, ac
    values["af_in"], values["ac_in"] = af / 25.4, ac / 25.4
    # One flat's width: the height the jaws grip when a corner is down.
    values["flat_width_mm"] = af * _TAN30
    return af


def _axial(feature: dict, name: str, at: list, axis: list) -> None:
    if feature.get("at") != at or feature.get("axis") != axis:
        raise CadError(f"{name}: expected on the hex axis, entering its end face")


def _holes(features: dict, values: dict, height: float, af: float) -> None:
    bore = _feature(features, "lever_bore", "hole")
    at = bore.get("at")
    if (
        bore.get("axis") != [1, 0, 0]
        or bore.get("thru") is not True
        or bore.get("height_from") != "bottom_face"
        or not isinstance(at, list)
        or len(at) != 3
        or at[0] != 0
        or at[2] != 0
    ):
        raise CadError(
            "lever_bore: expected a through hole along X across the hex axis, "
            "its height from bottom_face"
        )
    station = _band(bore, "height", "lever_bore")
    if not station[0] <= _number(at[1], "lever_bore.at") <= station[1]:
        raise CadError("lever_bore.at: outside its height band")
    dia = _band(bore, "dia", "lever_bore")
    _inch_limits(values, "bore_dia", dia)
    _inch_limits(values, "bore_height", station)
    values["bore_height_mm"] = at[1]
    location = _band(bore, "location_from_z_flat", "lever_bore")
    if not location[0] <= af / 2 <= location[1]:
        raise CadError("lever_bore.location_from_z_flat: not half the across flats")
    _inch_limits(values, "bore_flat_location", location)
    # The bore's extent along the axis at its extremes.
    low = station[0] - dia[1] / 2
    high = station[1] + dia[1] / 2
    values["bore_span_mm"] = [low, high]

    rod = _feature(features, "rod_tap", "threaded_hole")
    thumb = _feature(features, "thumb_tap", "threaded_hole")
    _axial(rod, "rod_tap", [0, 0, 0], [0, 1, 0])
    _axial(thumb, "thumb_tap", [0, height, 0], [0, -1, 0])
    if thumb.get("into") != "lever_bore":
        raise CadError("thumb_tap.into: expected lever_bore")
    thread = _string(rod.get("thread"), "rod_tap.thread")
    drill = _band(rod, "dia", "rod_tap")
    lead = _positive(rod.get("plug_tap_lead"), "rod_tap.plug_tap_lead")
    for key, found in (
        ("thread", thumb.get("thread") == thread),
        ("dia", _band(thumb, "dia", "thumb_tap") == drill),
        (
            "location_from_z_flat",
            _band(thumb, "location_from_z_flat", "thumb_tap") == location,
        ),
        ("plug_tap_lead", thumb.get("plug_tap_lead") == lead),
    ):
        if not found:
            raise CadError(f"thumb_tap.{key}: disagrees with rod_tap")
    if _band(rod, "location_from_z_flat", "rod_tap") != location:
        raise CadError("rod_tap.location_from_z_flat: disagrees with lever_bore")
    values["thread"] = thread
    values["plug_tap_lead_mm"] = lead
    _inch_limits(values, "tap_drill_dia", drill)
    _inch_limits(values, "tap_location", location)
    # Drilled depths are to the full diameter; the point runs on past them.
    point = drill[1] / 2 * _POINT
    values["tap_drill_point_mm"] = point

    # Rod tap, blind from the bottom: the deepest drill must stay out of the
    # bore, and the tap's point stops between full thread and the drilled
    # depth.
    depth = _band(rod, "drill_depth", "rod_tap")
    threads = _band(rod, "thread_depth", "rod_tap")
    if depth[1] + point >= low:
        raise CadError(
            f"rod_tap.drill_depth: {depth[1]:g} mm deep plus the drill's "
            f"{point:.3f} mm point breaks into the bore, whose nearest wall is "
            f"{low:.3f} mm from the bottom"
        )
    reach = (threads[0] + lead, min(threads[1] + lead, depth[0]))
    if reach[0] > reach[1]:
        raise CadError(
            f"rod_tap.thread_depth: full thread {threads[0]:g} mm deep needs the "
            f"tap's point {reach[0]:g} mm in, past the {depth[0]:g} mm least "
            "drilled depth"
        )
    _inch_limits(values, "rod_drill_depth", depth)
    _inch_limits(values, "rod_thread_depth", threads)
    _inch_limits(values, "rod_tap_reach", reach)
    values["rod_drill_depth_mm"] = _nominal(rod, depth, "rod_tap")

    # Thumb tap, from the top into the bore: the shallowest drill must break
    # into the bore and the deepest stop short of its far wall.
    depth = _band(thumb, "drill_depth", "thumb_tap")
    tall = values["block_height_band_mm"]
    # The thickest wall above the bore: the highest top less the lowest
    # bore's top. The nearest far wall: the lowest top less the highest bore's
    # bottom, taken where the smallest bore meets the hole's edge.
    wall = tall[1] - station[0] - dia[0] / 2
    chord = math.sqrt((dia[0] / 2) ** 2 - (drill[1] / 2) ** 2)
    far = tall[0] - station[1] + chord
    if depth[0] <= wall or depth[1] + point >= far:
        raise CadError(
            f"thumb_tap.drill_depth: {depth[0]:g}..{depth[1]:g} mm must pass the "
            f"wall above the bore (up to {wall:.3f} mm thick) and its "
            f"{point:.3f} mm point stop short of the bore's far wall (as near "
            f"as {far:.3f} mm)"
        )
    # The tap's point stops between full thread through that wall and the
    # far wall.
    reach = _window(thumb, "tap_reach", "thumb_tap")
    if reach[0] - lead < wall or reach[1] >= far:
        raise CadError(
            f"thumb_tap.tap_reach: {reach[0]:g}..{reach[1]:g} mm must carry full "
            f"thread through the wall above the bore ({wall + lead:.3f} mm with "
            f"the tap's lead) and stop short of the bore's far wall "
            f"({far:.3f} mm)"
        )
    _inch_limits(values, "thumb_drill_depth", depth)
    _inch_limits(values, "thumb_tap_reach", reach)
    values["thumb_drill_depth_mm"] = _nominal(thumb, depth, "thumb_tap")


def _cross(values: dict, parameters: dict, af: float) -> None:
    """The block lying corner down between two parallels for the cross bore."""
    if not _all_or_none(parameters, _CROSS, "the cross-bore setup"):
        return
    thick, end = (_positive(parameters[key], f"process.{key}") for key in _CROSS)
    gap = af - 2 * thick
    if gap <= 0:
        raise CadError(
            "process.parallel_thickness_mm: two parallels leave no gap "
            "between the jaws for the corner"
        )
    # The lower flats rest on the parallels' inner top edges, half the gap
    # either side of the corner.
    drop = gap / 2 * _TAN30
    values["cross_parallel_gap_mm"] = gap
    values["cross_corner_drop_mm"] = drop
    values["cross_axis_height_mm"] = values["ac_mm"] / 2 - drop
    values["cross_top_height_mm"] = values["ac_mm"] - drop
    low = values["bore_span_mm"][0]
    if end >= low:
        raise CadError(
            f"process.cross_parallel_end_mm: the parallels reach {end:g} mm from "
            f"the bottom end, under the bore, which starts at {low:.3f} mm: the "
            "drill would break out into them"
        )
    values["cross_parallel_clear_mm"] = low - end


def load_hex_block(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the block's height, cross bore, both tapped holes and its setups."""
    raw, values, features = _read_manifest(path, part, "hex_block")
    _model_frame(raw)
    if features.keys() != _FEATURES:
        raise CadError(f"cad.features: expected exactly {', '.join(sorted(_FEATURES))}")
    height = _height(features, values)
    af = _hex(features, values)
    _holes(features, values, height, af)
    _edge_breaks(raw, values)
    if _all_or_none(parameters, _BLANK, "the sawn blank"):
        low, high = (_positive(parameters[key], f"process.{key}") for key in _BLANK)
        if low > high:
            raise CadError("process.blank_length_min_in: over blank_length_max_in")
        if low < values["block_height_max_in"]:
            raise CadError(
                "process.blank_length_min_in: shorter than the longest finished block"
            )
        values["blank_length_min_mm"], values["blank_length_max_mm"] = (
            low * 25.4,
            high * 25.4,
        )
        # Stock to face off the two ends of the shortest and longest blank.
        values["face_stock_min_in"] = low - values["block_height_max_in"]
        values["face_stock_max_in"] = high - values["block_height_min_in"]
    _cross(values, parameters, af)
    envelope = (
        StockAxis("length", "blank_length_min_in", height),
        StockAxis("across flats", "blank_af_in", af),
    )
    return CadData(values, StockRequirement("in", envelope), path.resolve())
